"""Custom evidence MCP server: deterministic helpers so the small model only judges."""
import evidence_core
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("evidence")


@mcp.tool()
def extract_passages(text: str, claim: str, max_passages: int = 4) -> list[str]:
    return evidence_core.extract_passages(text, claim, max_passages)


@mcp.tool()
def source_credibility(url: str) -> dict:
    return evidence_core.source_credibility(url)


@mcp.tool()
def extract_date(text: str) -> str | None:
    return evidence_core.extract_date(text)


if __name__ == "__main__":
    mcp.run()
