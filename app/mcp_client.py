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

SEARCH_TOOL = "search"
FETCH_TOOL = "fetch"
SEARCH_SERVER = Path(__file__).resolve().parent.parent / "mcp_servers" / "search_server.py"


class MCPManager:
    def __init__(self):
        self._stack = AsyncExitStack()
        self.search: ClientSession | None = None
        self.fetch: ClientSession | None = None

    async def __aenter__(self):
        uvx = shutil.which("uvx.exe") or shutil.which("uvx")
        if not uvx:
            raise RuntimeError("uvx not found; the fetch MCP server needs uv")
        self.search = await self._start(sys.executable, [str(SEARCH_SERVER)])
        self.fetch = await self._start(uvx, ["mcp-server-fetch"])
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
        res = await self.search.call_tool(SEARCH_TOOL, {"query": query, "max_results": max_results})
        text = res.content[0].text if res.content else ""
        return _parse_search_text(text)

    async def fetch_page(self, url: str) -> str:
        res = await self.fetch.call_tool(FETCH_TOOL, {"url": url, "max_length": 10000})
        if not res.content:
            return ""
        return res.content[0].text


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
