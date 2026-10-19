import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.nodes import Critique, ReadSummary
from app.state import State


class FakeMCP:
    def __init__(self, n_sources=5, dead_index=3):
        self.n_sources = n_sources
        self.dead_index = dead_index
        self.page = "reliable evidence text here about the test claim " * 80

    async def search_web(self, query, max_results=8):
        return [
            {"url": f"https://src{i}.example.com/page{i}", "title": f"Source {i}", "snippet": ""}
            for i in range(self.n_sources)
        ]

    async def fetch_page(self, url):
        if f"src{self.dead_index}" in url:
            raise RuntimeError("simulated fetch failure")
        return self.page

    async def extract_passages(self, text, claim, max_passages=4):
        return [text[:500], text[500:1000]]

    async def source_credibility(self, url):
        return {"score": 0.5, "reason": "test unknown https"}

    async def extract_date(self, text):
        return None


async def fake_chat_json(client, messages, schema, max_tokens=600):
    if schema is ReadSummary:
        return ReadSummary(summary="fake summary")
    return Critique(stance="supports", confidence=0.7, quote="reliable evidence text here", note="n")


def test_five_sources_all_findings_present(monkeypatch):
    monkeypatch.setattr("app.nodes.chat_json", fake_chat_json)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=5), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert len(state["sources"]) == 5
    assert len(state["findings"]) == 5
    stances = {f["stance"] for f in state["findings"]}
    assert "supports" in stances
    for f in state["findings"]:
        assert f["url"]
    healthy = [f for f in state["findings"] if "src3" not in f["url"]]
    assert len(healthy) == 4
    assert all(f["credibility"] == 0.5 for f in healthy)
    assert all(f["passages"] for f in healthy)
    dead = [f for f in state["findings"] if "src3" in f["url"]][0]
    assert dead["credibility"] == 0.3


def test_failed_fetch_branch_returns_unclear_no_crash(monkeypatch):
    monkeypatch.setattr("app.nodes.chat_json", fake_chat_json)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=5, dead_index=3), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert len(state["findings"]) == 5
    dead = [f for f in state["findings"] if "src3" in f["url"]][0]
    assert dead["stance"] == "unclear"
    assert dead["confidence"] == 0.0
    assert "empty or fetch failed" in dead["credibility_reason"]


def test_fewer_than_two_sources_skips_fanout(monkeypatch):
    monkeypatch.setattr("app.nodes.chat_json", fake_chat_json)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=1), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert state["findings"] == []
    assert len(state["sources"]) == 1
