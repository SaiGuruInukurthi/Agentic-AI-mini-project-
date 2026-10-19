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


async def fake_chat_json(client, messages, schema, max_tokens=600, role="small"):
    from app.graph import Explanation
    from app.nodes import QueryRewrite, ReadSummary

    if schema is ReadSummary:
        return ReadSummary(summary="fake summary")
    if schema is QueryRewrite:
        return QueryRewrite(query="refined fact check query")
    if schema.__name__ == "Explanation":
        from app.graph import Explanation

        return Explanation(explanation="fake explanation")
    return Critique(stance="supports", confidence=0.7, quote="reliable evidence text here", note="n")


def _patch_chat(monkeypatch):
    monkeypatch.setattr("app.nodes.chat_json", fake_chat_json)
    monkeypatch.setattr("app.graph.chat_json", fake_chat_json)


def test_five_sources_all_findings_present(monkeypatch):
    _patch_chat(monkeypatch)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=5), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert len(state["sources"]) == 5
    assert len(state["findings"]) == 5
    assert state["verdict"] == "True"
    assert state["explanation"] == "fake explanation"
    for f in state["findings"]:
        assert f["url"]
    healthy = [f for f in state["findings"] if "src3" not in f["url"]]
    assert len(healthy) == 4
    assert all(f["credibility"] == 0.5 for f in healthy)
    assert all(f["passages"] for f in healthy)
    dead = [f for f in state["findings"] if "src3" in f["url"]][0]
    assert dead["credibility"] == 0.5


def test_failed_fetch_branch_returns_unclear_no_crash(monkeypatch):
    _patch_chat(monkeypatch)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=5, dead_index=3), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert len(state["findings"]) == 5
    dead = [f for f in state["findings"] if "src3" in f["url"]][0]
    assert dead["stance"] == "unclear"
    assert dead["confidence"] == 0.0
    assert "page could not be read" in dead["credibility_reason"]


def test_fetch_error_prefix_detection():
    from app.mcp_client import MCPManager

    class _Content:
        def __init__(self, text):
            self.text = text

    class _Res:
        def __init__(self, text):
            self.content = [_Content(text)]

    class _StubSession:
        def __init__(self, text):
            self.text = text

        async def call_tool(self, name, args):
            return _Res(self.text)

    m = MCPManager()
    m.fetch = _StubSession("Error executing tool fetch: HTTP 403")
    assert asyncio.run(m.fetch_page("https://x.com/")) == ""
    m.fetch = _StubSession("Contents of https://x.com/ page text here")
    assert asyncio.run(m.fetch_page("https://x.com/")) == "Contents of https://x.com/ page text here"


def test_fetch_error_skips_llm_calls(monkeypatch):
    from app.nodes import read_agent

    async def exploding_chat(*a, **k):
        raise AssertionError("no LLM call may happen for a failed fetch")

    monkeypatch.setattr("app.nodes.chat_json", exploding_chat)

    class ErrorMCP(FakeMCP):
        async def fetch_page(self, url):
            return ""  # what MCPManager.fetch_page returns after detecting the error prefix

    mcp = ErrorMCP()
    result = asyncio.run(read_agent(mcp, None, "test claim", {"url": "https://src0.example.com/p", "title": "T", "snippet": ""}))
    assert result["passages"] == []
    assert result["credibility"] == 0.5
    assert "page could not be read" in result["credibility_reason"]


def test_fewer_than_two_sources_skips_fanout(monkeypatch):
    _patch_chat(monkeypatch)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=1), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert state["findings"] == []
    assert len(state["sources"]) == 1


def _src(url: str) -> dict:
    return {"url": url, "title": url, "snippet": ""}


def _finding(url: str, stance: str, cred: float, conf: float) -> dict:
    return {
        "url": url, "title": url, "credibility": cred, "credibility_reason": "r",
        "passages": ["p"], "stance": stance, "confidence": conf, "quote": "q", "critique_note": "n",
    }


class TestFanOutDedup:
    S5 = [_src(f"https://s{i}.example.com/p") for i in range(5)]

    def test_round1_five_sources_fan_out(self):
        from app.graph import make_fan_out

        sends = make_fan_out({"claim": "c", "retries": 0, "sources": self.S5, "findings": []})
        assert len(sends) == 5
        assert all(s.node == "branch" for s in sends)

    def test_round1_one_source_summarize(self):
        from app.graph import make_fan_out

        sends = make_fan_out({"claim": "c", "retries": 0, "sources": self.S5[:1], "findings": []})
        assert len(sends) == 1 and sends[0].node == "summarize"

    def test_retry_skips_urls_with_findings(self):
        from app.graph import make_fan_out

        findings = [_finding(self.S5[i]["url"], "unclear", 0.5, 0.0) for i in range(3)]
        sends = make_fan_out({"claim": "c", "retries": 1, "sources": self.S5, "findings": findings})
        assert len(sends) == 2
        assert {s.arg["source"]["url"] for s in sends} == {self.S5[3]["url"], self.S5[4]["url"]}

    def test_retry_all_seen_goes_to_summarize(self):
        from app.graph import make_fan_out

        findings = [_finding(s["url"], "unclear", 0.5, 0.0) for s in self.S5]
        sends = make_fan_out({"claim": "c", "retries": 1, "sources": self.S5, "findings": findings})
        assert len(sends) == 1 and sends[0].node == "summarize"


def test_findings_deduped_by_url(monkeypatch):
    _patch_chat(monkeypatch)
    from app.graph import dedupe_by_url

    findings = [_finding("https://x.com/a", "supports", 0.8, 0.9),
                _finding("https://x.com/a", "supports", 0.8, 0.9),
                _finding("https://y.com/b", "contradicts", 0.5, 0.9)]
    assert [f["url"] for f in dedupe_by_url(findings)] == ["https://x.com/a", "https://y.com/b"]


def test_unclear_high_cred_does_not_count_as_credible():
    from app.graph import route_after_summarize

    findings = [
        _finding("https://a.com/", "unclear", 0.8, 0.0),
        _finding("https://b.com/", "unclear", 0.85, 0.0),
        _finding("https://c.com/", "supports", 0.5, 0.9),
    ]
    state = {"retries": 0, "verdict": "Mixed", "findings": findings}
    assert route_after_summarize(state) == "prep_retry"


async def _recording_chat(client, messages, schema, max_tokens=600, role="small"):
    from app.graph import Explanation
    from app.nodes import Critique, ReadSummary

    _recording_chat.captured.append(messages)
    if schema is ReadSummary:
        return ReadSummary(summary="s")
    if schema is Critique:
        return Critique(stance="supports", confidence=0.9, quote="reliable evidence text here", note="n")
    return Explanation(explanation="e")


_recording_chat.captured = []


def test_summarizer_gets_counts_and_strongest(monkeypatch):
    _recording_chat.captured.clear()
    monkeypatch.setattr("app.graph.chat_json", _recording_chat)
    monkeypatch.setattr("app.nodes.chat_json", _recording_chat)
    from app.graph import build_graph

    graph = build_graph(FakeMCP(n_sources=2, dead_index=-1), client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim", "retries": 0}))
    assert state["verdict"] == "True"
    summarize_calls = [m for m in _recording_chat.captured if any("Verdict:" in x["content"] for x in m)]
    assert summarize_calls, "summarizer prompt not captured"
    content = summarize_calls[0][0]["content"]
    assert "Counts: supports 2, contradicts 0, unclear 0" in content
    assert "Strongest sources:" in content
    assert "[1]" in content and "[2]" in content
    assert "unclear are not disagreement" in content
