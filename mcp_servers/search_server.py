"""Keyless web search MCP server wrapping the ddgs library (npm duckduckgo-mcp-server
is blocked by DDG anomaly detection from this network)."""
import time

from mcp.server.fastmcp import FastMCP
from ddgs import DDGS

mcp = FastMCP("search")

MAX_ATTEMPTS = 3
RETRY_WAITS = [2, 4]


@mcp.tool()
def search(query: str, max_results: int = 8) -> str:
    last_error = "unknown error"
    for attempt in range(MAX_ATTEMPTS):
        try:
            results = DDGS().text(query, max_results=max_results)
            if results:
                blocks = []
                for r in results:
                    title = r.get("title", "")
                    url = r.get("href") or r.get("url", "")
                    snippet = r.get("body", "")
                    blocks.append(f"Title: {title}\nURL: {url}\nSnippet: {snippet}")
                return "\n---\n".join(blocks)
            last_error = "no results"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)])
    return f"Error: {last_error}"


if __name__ == "__main__":
    mcp.run()
