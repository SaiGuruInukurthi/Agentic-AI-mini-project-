import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.nodes import Critique, ExtractedClaims, QueryRewrite, ReadSummary


class RetryFakeMCP:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def search_web(self, query, max_results=8):
        return [{"url": "https://only-one.example.com/a", "title": "Solo", "snippet": ""}]

    async def fetch_page(self, url):
        return "irrelevant filler text " * 200

    async def extract_passages(self, text, claim, max_passages=4):
        return [text[:500]]

    async def source_credibility(self, url):
        return {"score": 0.5, "reason": "test"}

    async def extract_date(self, text):
        return None


class CountingFakeMCP(RetryFakeMCP):
    def __init__(self, weak_first=True):
        self.search_calls = 0
        self.weak_first = weak_first
        self.page = "reliable evidence text here about the test claim " * 60

    async def fetch_page(self, url):
        return self.page

    async def search_web(self, query, max_results=8):
        self.search_calls += 1
        if self.weak_first and self.search_calls == 1:
            return [{"url": "https://weak.example.com/a", "title": "Weak", "snippet": ""}]
        return [
            {"url": f"https://strong{i}.example.com/p{i}", "title": f"Strong {i}", "snippet": ""}
            for i in range(3)
        ]


def make_chat(noisy=False):
    async def fake_chat_json(client, messages, schema, max_tokens=600, role="small"):
        from app.graph import Explanation

        if schema is ReadSummary:
            return ReadSummary(summary="fake")
        if schema is QueryRewrite:
            return QueryRewrite(query="refined fact check query")
        if schema is ExtractedClaims:
            if noisy:
                return ExtractedClaims(claims=["c1", "c2", "c3"], notice="kept first 3 of 5")
            return ExtractedClaims(claims=["c1"], notice="")
        if schema is Explanation:
            return Explanation(explanation="fake explanation")
        return Critique(stance="unclear", confidence=0.0, quote="", note="nothing relevant")

    return fake_chat_json


def test_vague_claim_triggers_exactly_one_retry(monkeypatch):
    fake = CountingFakeMCP()
    monkeypatch.setattr("app.nodes.chat_json", make_chat())
    monkeypatch.setattr("app.graph.chat_json", make_chat())
    from app.graph import build_graph

    graph = build_graph(fake, client=None)
    state = asyncio.run(graph.ainvoke({"claim": "vague claim", "retries": 0}))
    assert fake.search_calls == 2
    assert state["retries"] == 1
    assert state.get("search_query") == "refined fact check query"
    assert state["verdict"] == "Unverifiable"


def test_strong_evidence_does_not_retry(monkeypatch):
    fake = CountingFakeMCP(weak_first=False)

    async def strong_chat(client, messages, schema, max_tokens=600, role="small"):
        from app.graph import Explanation
        from app.nodes import QueryRewrite, ReadSummary

        if schema is ReadSummary:
            return ReadSummary(summary="fake")
        if schema is QueryRewrite:
            return QueryRewrite(query="refined fact check query")
        if schema is Explanation:
            return Explanation(explanation="fake explanation")
        from app.nodes import Critique

        return Critique(stance="supports", confidence=0.9, quote="reliable evidence text here about the test claim", note="n")

    monkeypatch.setattr("app.nodes.chat_json", strong_chat)
    monkeypatch.setattr("app.graph.chat_json", strong_chat)
    from app.graph import build_graph

    graph = build_graph(fake, client=None)
    state = asyncio.run(graph.ainvoke({"claim": "test claim here", "retries": 0}))
    assert fake.search_calls == 1
    assert state["retries"] == 0
    assert state["verdict"] == "True"


def test_extractor_caps_at_three(monkeypatch):
    noisy = make_chat(noisy=True)
    monkeypatch.setattr("app.nodes.chat_json", noisy)
    import app.nodes as nodes

    claims, notice = asyncio.run(nodes.extract_claims_llm(None, "text"))
    assert claims == ["c1", "c2", "c3"]
    assert notice == "kept first 3 of 5"


class SilentTrace:
    def start_run(self, label="run"):
        pass

    def event(self, kind, **data):
        pass


def test_multi_claim_sse(monkeypatch):
    monkeypatch.setattr("app.nodes.chat_json", make_chat(noisy=True))
    monkeypatch.setattr("app.graph.chat_json", make_chat(noisy=True))
    monkeypatch.setattr("app.main.MCPManager", lambda: RetryFakeMCP())
    monkeypatch.setattr("app.main.trace", SilentTrace())

    from app import main as api

    with TestClient(api.app) as client:
        events = []
        with client.stream("POST", "/check", json={"text": "some text with claims"}) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    results = [e for e in events if e["type"] == "result"]
    assert len(results) == 3
    notices = [e for e in events if e["type"] == "notice"]
    assert notices and notices[0]["message"] == "kept first 3 of 5"
    assert any("Extracted 3 claim(s)" in e.get("detail", "") for e in events if e["type"] == "progress")
