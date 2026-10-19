"""Agent node functions. Used by cli.py (M1/M2) and the LangGraph graph (M3+)."""
import logging
from datetime import date

from pydantic import BaseModel, Field

from mcp_servers.evidence_core import claim_keywords, quote_in_passages

from .llm import AsyncGroq, chat_json
from .mcp_client import MCPManager, dedupe_by_domain
from .prompts import CRITIQUE_PROMPT, EXTRACT_PROMPT, QUERY_REWRITE_PROMPT, READ_PROMPT
from .state import Finding, Source

log = logging.getLogger("factchecker.nodes")

MAX_SOURCES = 5
MAX_CLAIMS = 3
PASSAGES_TOKEN_CAP = 1200
CHARS_PER_TOKEN = 4
MAX_PASSAGES_CHARS = PASSAGES_TOKEN_CAP * CHARS_PER_TOKEN


class ReadSummary(BaseModel):
    summary: str


class Critique(BaseModel):
    stance: str = Field(pattern="^(supports|contradicts|unclear)$")
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str
    note: str


class ExtractedClaims(BaseModel):
    claims: list[str] = Field(max_length=MAX_CLAIMS)
    notice: str = ""


class QueryRewrite(BaseModel):
    query: str


async def extract_claims_llm(client: AsyncGroq, text: str) -> tuple[list[str], str]:
    result = await chat_json(
        client,
        [{"role": "user", "content": EXTRACT_PROMPT.format(text=text)}],
        ExtractedClaims,
        max_tokens=600,
        role="big",
    )
    if result is None:
        return [text], ""
    return result.claims[:MAX_CLAIMS], result.notice


async def rewrite_query(client: AsyncGroq, query: str) -> str:
    result = await chat_json(
        client,
        [{"role": "user", "content": QUERY_REWRITE_PROMPT.format(query=query)}],
        QueryRewrite,
        max_tokens=600,
        role="big",
    )
    return result.query if result else query


async def search_agent(mcp: MCPManager, claim: str, top_n: int = MAX_SOURCES) -> list[Source]:
    sources = await mcp.search_web(claim)
    return dedupe_by_domain(sources)[:top_n]


def _trim_passages(passages: list[str]) -> list[str]:
    out, budget = [], MAX_PASSAGES_CHARS
    for p in passages:
        if budget <= 0:
            break
        out.append(p[:budget])
        budget -= len(p)
    return out


def _is_recent(iso_date: str) -> bool:
    try:
        y, m, d = map(int, iso_date.split("-"))
        published = date(y, m, d)
    except (ValueError, TypeError):
        return False
    return 0 <= (date.today() - published).days / 365.25 <= 2


async def read_agent(mcp: MCPManager, client: AsyncGroq, claim: str, source: Source) -> dict:
    url, title = source["url"], source["title"]
    try:
        page_text = await mcp.fetch_page(url)
    except Exception as e:
        log.warning("Fetch failed for %s: %s", url, e)
        page_text = ""
    if not page_text:
        return {
            "url": url,
            "title": title,
            "passages": [],
            "credibility": 0.3,
            "credibility_reason": "page empty or fetch failed",
            "summary": "",
        }

    passages = _trim_passages(await mcp.extract_passages(page_text, claim))
    cred = await mcp.source_credibility(url)
    score, reason = cred["score"], cred["reason"]

    page_date = await mcp.extract_date(page_text)
    if page_date and _is_recent(page_date):
        score += 0.05
        reason += "; published within 2 years"

    page_lower = page_text.lower()
    keywords = claim_keywords(claim)
    if keywords and not any(k in page_lower for k in keywords):
        score = min(score, 0.3)
        reason += "; page does not mention claim key terms"

    passages_text = "\n---\n".join(passages)
    result = await chat_json(
        client,
        [{"role": "user", "content": READ_PROMPT.format(claim=claim, passages=passages_text)}],
        ReadSummary,
        max_tokens=600,
        role="small",
    )
    return {
        "url": url,
        "title": title,
        "passages": passages,
        "credibility": round(min(score, 1.0), 2),
        "credibility_reason": reason,
        "summary": result.summary if result else "",
    }


async def critique_agent(
    client: AsyncGroq,
    claim: str,
    passages: list[str],
    url: str = "",
    title: str = "",
    credibility: float = 0.0,
    credibility_reason: str = "",
) -> Finding:
    base = {
        "url": url,
        "title": title,
        "credibility": credibility,
        "credibility_reason": credibility_reason,
        "passages": passages,
        "stance": "unclear",
        "confidence": 0.0,
        "quote": "",
        "critique_note": "",
    }
    if not passages:
        base["critique_note"] = "no passages extracted; page empty or fetch failed"
        return base
    passages_text = "\n---\n".join(passages)
    result = await chat_json(
        client,
        [{"role": "user", "content": CRITIQUE_PROMPT.format(claim=claim, passages=passages_text)}],
        Critique,
        max_tokens=600,
        role="small",
    )
    if result is None:
        base["critique_note"] = "LLM unavailable or rate limited"
        return base
    if not quote_in_passages(result.quote, passages):
        log.info("Critique quote not found in passages; forcing unclear")
        return {
            **base,
            "stance": "unclear",
            "confidence": 0.0,
            "quote": result.quote,
            "critique_note": f"quote not found in passages; original note: {result.note}",
        }
    return {
        **base,
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
