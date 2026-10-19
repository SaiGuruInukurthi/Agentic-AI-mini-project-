"""M1 CLI: one claim -> search (MCP) -> one read -> one critique -> print result."""
import asyncio
import json
import logging
import sys

from app.llm import get_client, log_usage
from app.mcp_client import MCPManager
from app.nodes import critique_agent, read_agent, search_agent, unclear_finding

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")


async def main(claim: str) -> int:
    client = get_client()
    async with MCPManager() as mcp:
        sources = await search_agent(mcp, claim, top_n=1)
        if not sources:
            print("No sources found; cannot fact-check this claim.")
            return 1
        source = sources[0]
        print(f"\nSource: {source['title']} - {source['url']}")

        try:
            page_text = await mcp.fetch_page(source["url"])
        except Exception as e:
            print(f"Fetch failed: {e}")
            page_text = ""
        if not page_text:
            finding = unclear_finding(source["url"], source["title"], "fetch failed or page empty")
            print("\nFinding:")
            print(json.dumps(finding, indent=2))
            log_usage()
            return 0

        summary = await read_agent(client, claim, page_text)
        print(f"\nRead agent summary: {summary or '(no summary)'}")

        finding = await critique_agent(client, claim, page_text)
        if finding is None:
            finding = unclear_finding(source["url"], source["title"], "LLM unavailable or rate limited")
        finding["url"] = source["url"]
        finding["title"] = source["title"]

        print("\nFinding:")
        print(json.dumps(finding, indent=2))
        log_usage()
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python cli.py "some claim"')
        sys.exit(2)
    claim = " ".join(sys.argv[1:])
    sys.exit(asyncio.run(main(claim)))
