"""Agent node functions. Used by cli.py (M1) and the LangGraph graph (M3+)."""
import logging

from pydantic import BaseModel, Field

from .llm import AsyncGroq, chat_json
from .mcp_client import MCPManager, dedupe_by_domain
from .prompts import CRITIQUE_PROMPT, READ_PROMPT
from .state import Finding, Source

log = logging.getLogger("factchecker.nodes")

MAX_SOURCES = 5
PAGE_EXCERPT_CHARS = 6000


class ReadSummary(BaseModel):
    summary: str


class Critique(BaseModel):
    stance: str = Field(pattern="^(supports|contradicts|unclear)$")
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str
    note: str


async def search_agent(mcp: MCPManager, claim: str, top_n: int = MAX_SOURCES) -> list[Source]:
    sources = await mcp.search_web(claim)
    return dedupe_by_domain(sources)[:top_n]


async def read_agent(client: AsyncGroq, claim: str, page_text: str) -> str:
    excerpt = page_text[:PAGE_EXCERPT_CHARS]
    result = await chat_json(
        client,
        [{"role": "user", "content": READ_PROMPT.format(claim=claim, passages=excerpt)}],
        ReadSummary,
        max_tokens=600,
    )
    if result is None:
        return ""
    return result.summary


async def critique_agent(client: AsyncGroq, claim: str, page_text: str) -> Finding | None:
    excerpt = page_text[:PAGE_EXCERPT_CHARS]
    result = await chat_json(
        client,
        [{"role": "user", "content": CRITIQUE_PROMPT.format(claim=claim, passages=excerpt)}],
        Critique,
        max_tokens=600,
    )
    if result is None:
        return None
    return {
        "url": "",
        "title": "",
        "credibility": 0.0,
        "credibility_reason": "filled in M2",
        "passages": [excerpt],
        "stance": result.stance,
        "confidence": result.confidence,
        "quote": result.quote,
        "critique_note": result.note,
    }


def unclear_finding(url: str, title: str, note: str) -> Finding:
    return {
        "url": url,
        "title": title,
        "credibility": 0.0,
        "credibility_reason": note,
        "passages": [],
        "stance": "unclear",
        "confidence": 0.0,
        "quote": "",
        "critique_note": note,
    }
