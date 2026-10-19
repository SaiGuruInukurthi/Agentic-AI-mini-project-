"""Manages connections to the MCP servers: search + evidence (our FastMCP servers) and fetch (uvx)."""
import asyncio
import re
import shutil
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import trace

SEARCH_TOOL = "search"
FETCH_TOOL = "fetch"
FETCH_ERROR_PREFIX = "Error executing tool fetch"
SEARCH_SERVER = Path(__file__).resolve().parent.parent / "mcp_servers" / "search_server.py"
EVIDENCE_SERVER = Path(__file__).resolve().parent.parent / "mcp_servers" / "evidence_server.py"


class MCPManager:
    def __init__(self):
        self._stack = AsyncExitStack()
        self.search: ClientSession | None = None
        self.fetch: ClientSession | None = None
        self.evidence: ClientSession | None = None

    async def __aenter__(self):
        uvx = shutil.which("uvx.exe") or shutil.which("uvx")
        if not uvx:
            raise RuntimeError("uvx not found; the fetch MCP server needs uv")
        self.search = await self._start(sys.executable, [str(SEARCH_SERVER)])
        self.fetch = await self._start(uvx, ["mcp-server-fetch"])
        self.evidence = await self._start(sys.executable, [str(EVIDENCE_SERVER)])
        return self

    async def _start(self, command: str, args: list[str]) -> ClientSession:
        read, write = await self._stack.enter_async_context(
            stdio_client(StdioServerParameters(command=command, args=args))
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def __aexit__(self, *exc):
        await self._stack.aclose()
        return False

    async def search_web(self, query: str, max_results: int = 8) -> list[dict]:
        trace.event("mcp_search", query=query, max_results=max_results)
        res = await self.search.call_tool(SEARCH_TOOL, {"query": query, "max_results": max_results})
        text = res.content[0].text if res.content else ""
        results = _parse_search_text(text)
        trace.event("mcp_search_result", query=query, n=len(results), results=results, raw=text)
        return results

    async def fetch_page(self, url: str) -> str:
        trace.event("mcp_fetch", url=url)
        res = await self.fetch.call_tool(FETCH_TOOL, {"url": url, "max_length": 20000})
        text = res.content[0].text if res.content else ""
        trace.event("mcp_fetch_result", url=url, chars=len(text), text=text)
        if text.startswith(FETCH_ERROR_PREFIX):
            return ""
        return text

    async def extract_passages(self, text: str, claim: str, max_passages: int = 4) -> list[str]:
        import json

        res = await self.evidence.call_tool("extract_passages", {"text": text, "claim": claim, "max_passages": max_passages})
        trace.event("mcp_evidence", tool="extract_passages", claim=claim,
                    result=_structured(res), raw=(res.content[0].text if res.content else "")[:4000])
        st = _structured(res)
        if isinstance(st, list):
            return [str(x) for x in st]
        raw = res.content[0].text if res.content else ""
        if not raw or raw.startswith("Error"):
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else [raw]
        except json.JSONDecodeError:
            return [raw]

    async def source_credibility(self, url: str) -> dict:
        import json

        res = await self.evidence.call_tool("source_credibility", {"url": url})
        trace.event("mcp_evidence", tool="source_credibility", url=url,
                    result=_structured(res), raw=(res.content[0].text if res.content else "")[:2000])
        st = _structured(res)
        if isinstance(st, dict):
            return st
        raw = res.content[0].text if res.content else ""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"score": 0.0, "reason": f"unparseable evidence response: {raw[:80]}"}

    async def extract_date(self, text: str) -> str | None:
        res = await self.evidence.call_tool("extract_date", {"text": text})
        trace.event("mcp_evidence", tool="extract_date", result=_structured(res),
                    raw=(res.content[0].text if res.content else "")[:200])
        st = _structured(res)
        if st is not None:
            return None if st in ("null", "") else str(st)
        raw = res.content[0].text if res.content else ""
        return None if raw in ("null", "") else raw


def _structured(res) -> object:
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    return None


def _parse_search_text(text: str) -> list[dict]:
    if text.startswith("Error:"):
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*[-=]{3,}\s*\n", text) if b.strip()]
    results = []
    for block in blocks:
        title_m = re.search(r"Title:\s*(.+)", block)
        url_m = re.search(r"URL:\s*(\S+)", block)
        snippet_m = re.search(r"(?:Description|Snippet|Content):\s*(.+?)(?:\n|$)", block, re.DOTALL)
        if url_m:
            results.append(
                {
                    "title": title_m.group(1).strip() if title_m else "",
                    "url": url_m.group(1).strip(),
                    "snippet": snippet_m.group(1).strip() if snippet_m else "",
                }
            )
    return results


def dedupe_by_domain(sources: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for s in sources:
        domain = urlparse(s["url"]).netloc.removeprefix("www.").lower()
        if domain and domain not in seen:
            seen.add(domain)
            out.append(s)
    return out
