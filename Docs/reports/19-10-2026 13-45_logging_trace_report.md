# Report: Run tracing (logs/) — 19-10-2026 13:45

## What was built

Structured per-run tracing so we can assess model and pipeline quality after the fact. Every API request or CLI run now writes one JSONL file to `logs/` (gitignored, never committed):

`logs/<YYYYMMDD_HHMMSS>_<label>.jsonl` — label is `api` (per `/check` request) or `cli` (per CLI invocation).

## Event types captured

| Event | Source | Contents |
|---|---|---|
| `run_start` | `trace.start_run()` | label |
| `user_input` | `main.py` / `cli.py` | the raw pasted text / CLI claim |
| `mcp_search`, `mcp_search_result` | `mcp_client.search_web` | query, parsed results (title/url/snippet), raw DDG text |
| `mcp_fetch`, `mcp_fetch_result` | `mcp_client.fetch_page` | URL, full fetched page text, char count |
| `mcp_evidence` | evidence tool calls | tool name, claim/url, structured result, raw (truncated) |
| `llm_attempt` | `llm._chat_attempt` | schema, model, attempt #, **full messages (prompt)** |
| `llm_response` | `llm._chat_attempt` | raw content, parsed Pydantic output, per-call usage |
| `llm_done` | `llm.chat_json` | status (ok / rate_limited / error), whether fallback served |
| `finding` | `main.py` astream loop | assembled Finding (url, credibility, stance, confidence, quote) |
| `claim_result` | `main.py` | claim, verdict, score, retries, explanation |
| `run_final` | `cli.py` | final state summary (findings minus passages) |
| `run_error` | except blocks | timeout / exception messages |

## Design notes

- `app/trace.py` is ~40 lines, stdlib only (`json`, `os`, `threading`, `time`), no new dependencies.
- Trace is a **no-op until `start_run()`** is called — unit tests stay silent automatically.
- `chat_json` and `MCPManager` are the two chokepoints; hooking there captures 100% of subagent behavior with ~15 lines of call-site edits. Nothing logged from `MVP.md` scope changed.
- Full prompts and page text are logged on purpose (that is the point of quality assessment); a run file is roughly 100–300 KB.

## Test impact

- Added `tests/test_trace.py` (3 tests): no-op without `start_run`, JSONL append shape, unicode + non-serializable payloads.
- Caught a real leak during development: API tests (`test_api_m5.py`, `test_m6.py::test_multi_claim_sse`) exercise the real `/check` path and were writing `logs/api_*.jsonl` during pytest. Fixed with a `SilentTrace` stub monkeypatched over `app.main.trace` in both files.
- **60 tests pass** (57 + 3), 1.6s, zero API calls, no `logs/` recreated by the suite.

## Deliberate simplifications

- Global "current run file" (not per-request context): two concurrent `/check` requests would interleave into one file. Irrelevant for a local single-user demo; upgrade path is a contextvar.
- Filename granularity is seconds; same-second runs append to one file (still valid JSONL).
- JSON mode only — no logging of HTTP headers other than what rate-limit logic already reads.

## Budget note

No live runs were spent on this feature; verification was offline only.
