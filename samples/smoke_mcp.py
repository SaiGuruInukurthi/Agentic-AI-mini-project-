"""Smoke test for the MCP servers: our search server + uvx fetch. No Groq API calls."""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.mcp_client import SEARCH_SERVER


async def main():
    uvx = shutil.which("uvx.exe") or shutil.which("uvx")
    async with stdio_client(StdioServerParameters(command=uvx, args=["mcp-server-fetch"])) as (fr, fw):
        async with ClientSession(fr, fw) as fetch:
            await fetch.initialize()
            res = await fetch.call_tool("fetch", {"url": "https://example.com", "max_length": 500})
            print("fetch OK:", res.content[0].text[:80].replace("\n", " "))
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[str(SEARCH_SERVER)])) as (sr, sw):
        async with ClientSession(sr, sw) as search:
            await search.initialize()
            tools = await search.list_tools()
            print("search tools:", [t.name for t in tools.tools])
            res = await search.call_tool("search", {"query": "water boiling point sea level", "max_results": 3})
            print("search OK:", res.content[0].text[:150].replace("\n", " "))


if __name__ == "__main__":
    asyncio.run(main())
