"""LangGraph pipeline: extract claims -> search -> fan-out (Send, max 5) read+critique -> summarize."""
import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from .llm import AsyncGroq, chat_json
from .mcp_client import MCPManager
from .nodes import critique_agent, read_agent, search_agent
from .prompts import SUMMARIZER_PROMPT
from .state import Source, State
from .verdict import compute_verdict, format_findings_for_llm

log = logging.getLogger("factchecker.graph")

MAX_SOURCES = 5


async def extract_claims_node(state: State) -> dict:
    return {"claim": state["claim"], "retries": state.get("retries", 0)}


def make_search_node(mcp: MCPManager):
    async def search_node(state: State) -> dict:
        sources = await search_agent(mcp, state["claim"], top_n=MAX_SOURCES)
        return {"sources": sources}

    return search_node


def make_fan_out(state: State) -> list[Send]:
    if len(state["sources"]) < 2:
        return [Send("summarize", state)]
    return [Send("branch", {"claim": state["claim"], "source": s}) for s in state["sources"]]


def make_branch(mcp: MCPManager, client: AsyncGroq):
    async def branch_node(payload: dict) -> dict:
        claim: str = payload["claim"]
        source: Source = payload["source"]
        try:
            read = await read_agent(mcp, client, claim, source)
        except Exception as e:
            log.error("Branch failed for %s: %s", source["url"], e)
            from .nodes import unclear_finding

            return {"findings": [unclear_finding(source["url"], source["title"], f"branch error: {e}")]}
        finding = await critique_agent(
            client,
            claim,
            read["passages"],
            url=read["url"],
            title=read["title"],
            credibility=read["credibility"],
            credibility_reason=read["credibility_reason"],
        )
        return {"findings": [finding]}

    return branch_node


class Explanation(BaseModel):
    explanation: str


def make_summarize_node(client: AsyncGroq):
    async def summarize_node(state: State) -> dict:
        findings = state.get("findings", [])
        verdict, score = compute_verdict(findings)
        result = await chat_json(
            client,
            [{
                "role": "user",
                "content": SUMMARIZER_PROMPT.format(
                    claim=state["claim"],
                    verdict=verdict,
                    score=round(score, 2),
                    findings=format_findings_for_llm(findings),
                ),
            }],
            Explanation,
            max_tokens=600,
        )
        if result is None:
            explanation = "Summary unavailable (LLM error or rate limited). Verdict computed from source findings."
        else:
            explanation = result.explanation
        return {"verdict": verdict, "score": round(score, 2), "explanation": explanation}

    return summarize_node


def build_graph(mcp: MCPManager, client: AsyncGroq):
    g = StateGraph(State)
    g.add_node("extract_claims", extract_claims_node)
    g.add_node("search", make_search_node(mcp))
    g.add_node("branch", make_branch(mcp, client))
    g.add_node("summarize", make_summarize_node(client))
    g.add_edge(START, "extract_claims")
    g.add_edge("extract_claims", "search")
    g.add_conditional_edges("search", make_fan_out, ["branch", "summarize"])
    g.add_edge("branch", "summarize")
    g.add_edge("summarize", END)
    return g.compile()
