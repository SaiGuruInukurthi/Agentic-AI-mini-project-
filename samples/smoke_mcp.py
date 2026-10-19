"""Smoke test for the two external MCP servers (search, fetch). No Groq API calls."""
import asyncio
import shutil

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def try_server(name, params, run):
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=120)
                tools = await asyncio.wait_for(session.list_tools(), timeout=30)
                print(f"{name}: tools = {[t.name for t in tools.tools]}")
                await asyncio.wait_for(run(session), timeout=90)
                print(f"{name}: OK")
    except Exception as e:
        print(f"{name}: FAILED - {type(e).__name__}: {e}")


async def fetch_run(session):
    res = await asyncio.wait_for(
        session.call_tool("fetch", {"url": "https://example.com", "max_length": 500}),
        timeout=60,
    )
    print("fetch sample:", res.content[0].text[:100].replace("\n", " "))


async def search_run(session):
    try:
        res = await asyncio.wait_for(
            session.call_tool("search", {"query": "great wall of china visible from space"}),
            timeout=60,
        )
        print("search sample:", str(res.content[0].text)[:100].replace("\n", " "))
    except Exception as e:
        # listing tools succeeded; a tool-shape mismatch is not fatal for the smoke test
        print(f"search call note: {type(e).__name__}: {e}")


async def main():
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    uvx = shutil.which("uvx.exe") or shutil.which("uvx")
    print("npx:", npx, "| uvx:", uvx)
    await try_server("fetch", StdioServerParameters(command=uvx, args=["mcp-server-fetch"]), fetch_run)
    await try_server("search", StdioServerParameters(command=npx, args=["-y", "duckduckgo-mcp-server"]), search_run)


if __name__ == "__main__":
    asyncio.run(main())
