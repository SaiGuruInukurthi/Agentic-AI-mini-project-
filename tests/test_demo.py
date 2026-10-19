"""Smoke-test /demo replay endpoint (zero tokens)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app, LOGS_DIR


class FakeMCP:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass


def test_demo_replay(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.MCPManager", lambda: FakeMCP())
    monkeypatch.setattr("app.main.LOGS_DIR", tmp_path)

    trace = [
        {"kind": "user_input", "text": "test claim"},
        {"kind": "llm_response", "schema": "ExtractedClaims", "parsed": {"claims": ["test claim"], "notice": ""}},
        {"kind": "mcp_search", "query": "test claim"},
        {"kind": "mcp_search_result", "query": "test claim", "n": 3, "results": []},
        {"kind": "mcp_fetch", "url": "https://a.com/"},
        {"kind": "llm_attempt", "schema": "Critique", "model": "x"},
        {"kind": "finding", "finding": {"url": "https://a.com/", "title": "A", "credibility": 0.8,
                                         "stance": "supports", "confidence": 0.9, "quote": "q", "critique_note": "n"}},
        {"kind": "claim_result", "claim": "test claim", "verdict": "True", "score": 0.9,
         "retries": 0, "explanation": "because"},
    ]
    (tmp_path / "test_trace.jsonl").write_text("\n".join(json.dumps(e) for e in trace), encoding="utf-8")

    with TestClient(app) as client:
        resp = client.get("/demo")
        assert resp.status_code == 200
        body = resp.text
        assert '"type": "progress"' in body
        assert '"type": "finding"' in body
        assert '"type": "result"' in body
        assert "True" in body
        assert "because" in body


def test_demo_no_logs(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.MCPManager", lambda: FakeMCP())
    monkeypatch.setattr("app.main.LOGS_DIR", tmp_path)

    with TestClient(app) as client:
        resp = client.get("/demo")
        assert "No recorded runs" in resp.text
