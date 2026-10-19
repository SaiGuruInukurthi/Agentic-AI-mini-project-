"""Offline tests for the run-trace JSONL logger (no API calls)."""
import json

from app import trace


def test_noop_without_start_run(monkeypatch):
    monkeypatch.setattr(trace, "_run_file", None)
    trace.event("mcp_fetch", url="https://x.test")  # must not raise or create files
    assert trace._run_file is None


def test_events_append_as_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "LOG_DIR", str(tmp_path))
    trace.start_run("test")
    trace.event("mcp_fetch", url="https://x.test")
    trace.event("llm_response", content='{"a": 1}', parsed={"a": 1})
    lines = [json.loads(line) for line in open(trace._run_file, encoding="utf-8")]
    assert [r["kind"] for r in lines] == ["run_start", "mcp_fetch", "llm_response"]
    assert lines[1]["url"] == "https://x.test"
    assert lines[2]["parsed"] == {"a": 1}
    assert "ts" in lines[0]


def test_unicode_and_nonserializable_survive(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "LOG_DIR", str(tmp_path))
    trace.start_run("test")
    trace.event("user_input", text="café ☕ — naïve claim", weird=object())
    records = [json.loads(line) for line in open(trace._run_file, encoding="utf-8")]
    assert records[-1]["text"] == "café ☕ — naïve claim"
