"""Smoke test for the evidence MCP server via MCPManager. No Groq API calls."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.mcp_client import MCPManager

TEXT = (
    "The boiling point of water depends on atmospheric pressure. "
    "At sea level, water boils at 100 degrees Celsius or 212 degrees Fahrenheit. "
) * 20 + "Penguins live mostly in the southern hemisphere. " * 30


async def main():
    async with MCPManager() as mcp:
        passages = await mcp.extract_passages(TEXT, "Water boils at 100 degrees Celsius at sea level", max_passages=2)
        print(f"extract_passages: {len(passages)} passages, sizes {[len(p) for p in passages]}")
        print("passage 0 preview:", passages[0][:80].replace("\n", " "))

        for url in ("https://www.nasa.gov/x", "https://en.wikipedia.org/wiki/Y", "https://www.snopes.com/z",
                    "https://random-blog-site.net/a", "https://www.reddit.com/r/b/"):
            cred = await mcp.source_credibility(url)
            print("credibility:", url, "->", cred)

        d = await mcp.extract_date('Article <meta property="article:published_time" content="2024-06-15T10:00:00Z">')
        print("extract_date (meta):", d)
        d2 = await mcp.extract_date("No date in this text at all")
        print("extract_date (none):", d2)


if __name__ == "__main__":
    asyncio.run(main())
