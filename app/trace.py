"""Run tracing: appends one JSONL event log per run into logs/ (gitignored).

Captures the user input, every MCP search/fetch/evidence call, and every LLM
prompt + response + usage, so model and pipeline quality can be assessed after
the fact. Opt-in per run via start_run(); without it, tracing is a no-op, which
keeps unit tests silent.
"""
import json
import os
import threading
import time

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

_lock = threading.Lock()
_run_file: str | None = None


def start_run(label: str = "run") -> None:
    """Open a fresh JSONL file for this run. Call once per API request / CLI invocation."""
    global _run_file
    os.makedirs(LOG_DIR, exist_ok=True)
    _run_file = os.path.join(LOG_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{label}.jsonl")
    event("run_start", label=label)


def event(kind: str, **data) -> None:
    # ponytail: global current-run file; concurrent API requests would share one file
    # (fine for a local demo). Per-request context objects if that ever matters.
    if not _run_file:
        return
    record = {"ts": round(time.time(), 3), "kind": kind, **data}
    with _lock:
        with open(_run_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
