"""CLI: claim -> LangGraph pipeline (search, fan-out read+critique, verdict+summary) -> print."""
import asyncio
import json
import logging
import sys

from app.graph import build_graph
from app.llm import get_client, log_usage
from app.mcp_client import MCPManager

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
logging.getLogger("factchecker.llm").setLevel(logging.INFO)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main(claim: str) -> int:
    client = get_client()
    async with MCPManager() as mcp:
        graph = build_graph(mcp, client)
        final = await graph.ainvoke({"claim": claim, "retries": 0})

        print(f"\nVerdict: {final.get('verdict', 'Unverifiable')} (score {final.get('score', 0.0)})")
        print(f"\n{final.get('explanation', '')}\n")
        print("Sources:")
        for i, f in enumerate(final.get("findings", []), 1):
            print(f"  [{i}] {f['title']} - {f['url']}")
            print(f"      credibility {f['credibility']}, stance {f['stance']}, confidence {f['confidence']}")
            if f["quote"]:
                print(f"      quote: \"{f['quote']}\"")
        log_usage()
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python cli.py "some claim"')
        sys.exit(2)
    claim = " ".join(sys.argv[1:])
    sys.exit(asyncio.run(main(claim)))
