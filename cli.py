"""M1/M2 CLI: one claim -> search (MCP) -> read (evidence + LLM) -> critique (LLM) -> print."""
import asyncio
import json
import logging
import sys

from app.llm import get_client, log_usage
from app.mcp_client import MCPManager
from app.nodes import critique_agent, read_agent, search_agent, unclear_finding

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
logging.getLogger("factchecker.llm").setLevel(logging.INFO)


async def main(claim: str) -> int:
    client = get_client()
    async with MCPManager() as mcp:
        sources = await search_agent(mcp, claim, top_n=1)
        if not sources:
            print("No sources found; cannot fact-check this claim.")
            return 1
        source = sources[0]
        print(f"\nSource: {source['title']} - {source['url']}")

        read = await read_agent(mcp, client, claim, source)
        print(f"Credibility: {read['credibility']} ({read['credibility_reason']})")
        print(f"Passages kept: {len(read['passages'])} (~{sum(len(p) for p in read['passages']) // 4} tokens)")
        print(f"Read agent summary: {read['summary'] or '(no summary)'}")

        finding = await critique_agent(
            client,
            claim,
            read["passages"],
            url=read["url"],
            title=read["title"],
            credibility=read["credibility"],
            credibility_reason=read["credibility_reason"],
        )
        if not read["passages"]:
            finding = unclear_finding(source["url"], source["title"], "fetch failed or page empty")

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
