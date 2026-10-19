import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient


class FakeMCP:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def search_web(self, query, max_results=8):
        return [
            {"url": f"https://src{i}.example.com/p{i}", "title": f"Source {i}", "snippet": ""} for i in range(3)
        ]

    async def fetch_page(self, url):
        return "reliable evidence text here about the test claim " * 60

    async def extract_passages(self, text, claim, max_passages=4):
        return [text[:500]]

    async def source_credibility(self, url):
        return {"score": 0.5, "reason": "test"}

    async def extract_date(self, text):
        return None


async def fake_chat_json(client, messages, schema, max_tokens=600, role="small"):
    from app.graph import Explanation
    from app.nodes import ExtractedClaims, ReadSummary

    if schema is ReadSummary:
        return ReadSummary(summary="fake summary")
    if schema is ExtractedClaims:
        return ExtractedClaims(claims=["test claim"], notice="")
    if schema is Explanation:
        return Explanation(explanation="fake explanation")
    from app.nodes import Critique

    return Critique(stance="supports", confidence=0.7, quote="reliable evidence text here", note="n")


def test_check_sse_stream(monkeypatch):
    monkeypatch.setattr("app.nodes.chat_json", fake_chat_json)
    monkeypatch.setattr("app.graph.chat_json", fake_chat_json)
    monkeypatch.setattr("app.main.MCPManager", lambda: FakeMCP())

    from app import main as api

    with TestClient(api.app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Fact-Checker" in resp.text

        events = []
        with client.stream("POST", "/check", json={"text": "test claim"}) as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    kinds = [e["type"] for e in events]
    assert "progress" in kinds and "finding" in kinds and "result" in kinds
    result = [e for e in events if e["type"] == "result"][0]
    assert result["verdict"] == "True"
    finding = [e for e in events if e["type"] == "finding"][0]["finding"]
    assert finding["stance"] == "supports"


def test_check_empty_text(monkeypatch):
    monkeypatch.setattr("app.main.MCPManager", lambda: FakeMCP())

    from app import main as api

    with TestClient(api.app) as client:
        with client.stream("POST", "/check", json={"text": ""}) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    assert json.loads(line[6:])["type"] == "error"
                    break
