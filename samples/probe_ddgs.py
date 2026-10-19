"""Check if the Python ddgs library can reach DuckDuckGo from this network."""
from ddgs import DDGS

try:
    results = list(DDGS().text("great wall of china visible from space", max_results=5))
    print(f"OK: {len(results)} results")
    for r in results[:3]:
        print("-", r.get("title"), "|", r.get("href") or r.get("url"))
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
