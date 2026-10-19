"""Extraction-only probe: runs ONLY extract_claims_llm on a fixed input (one 120b call).

Purpose: verify the disputed-figure extractor rule without spending the small-model
(20b) budget. 120b has its own 200K TPD bucket. Check the Groq console before running.

Usage:
    & "C:\\Users\\IC1807\\anaconda3\\envs\\mini\\python.exe" samples\\probe_extract.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.llm import get_client, log_usage
from app.nodes import extract_claims_llm

TEXT = "Did Hitler kill 6 million Jews? or as it 200k shown as 6 million?"


async def main():
    if not os.getenv("GROQ_API"):
        raise SystemExit("GROQ_API missing in .env")
    client = get_client()
    claims, notice = await extract_claims_llm(client, TEXT)
    print("Notice:", notice or "(none)")
    for i, c in enumerate(claims, 1):
        print(f"  [{i}] {c}")
    log_usage()


if __name__ == "__main__":
    asyncio.run(main())
