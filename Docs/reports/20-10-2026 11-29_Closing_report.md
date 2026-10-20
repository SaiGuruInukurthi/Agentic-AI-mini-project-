# 20-10-2026 11-29 — Closing report (project wrap-up)

## Scope of this session

Final closure pass after the M1–M6 build and the post-MVP work (tracing, model routing, pipeline fixes, demo replay, pipeline SVG, activity log, sources table). This session:

1. **Groq API key expired and was replaced.** `models.list` returned `401 expired_api_key` (the key worked through the 20-10 00:47 trace). User generated a new key; recheck passed (11 models visible, one tiny 20b completion OK, ~86 tokens spent). The `401 expired_api_key` symptom is now recorded in `Docs/startup.md` troubleshooting.
2. **Pipeline SVG rows now auto-grow to the actual source count** (commit `8fd81c3`). Before this the UI hardcoded 3 branch rows and silently dropped sources 4+; `MAX_ROWS` raised 5 → 10 to match the backend ceiling (5 fresh sources/round + up to 5 in the retry round; the Bill Gates run had 10 unique URLs). Row/node/edge states are snapshotted and restored across rebuilds so mid-run highlights survive.
3. **Demo replay refills the prompt box** (commit `428bd08`). `/demo` emits the trace's original `user_input` as a first `input` event; the UI fills the textarea with it (falls back to the first claim for old traces). Test added to `tests/test_demo.py`.
4. **Pushed to GitHub**: https://github.com/SaiGuruInukurthi/Agentic-AI-mini-project- (`origin`, branch `master`, all 19 commits as of this session). `.env` was never committed.
5. **Docs reconciled**: architecture.md §10 documents the `input` event and the refill rule, §11 gitGraph extended; startup.md gained the 401 row; AGENTS.md records the remote.

## Verification

- JS syntax check on `static/index.html` (Node) — OK
- Offline suite: **76 passed**, ~5 s, zero API calls
- Live verification: replayed traces show correct per-round source counts; key-replacement check passed (above)

## Project closure state

**Done:** MVP M1–M6 with all acceptance checks (4 live acceptance runs during the build), post-MVP additions (tracing, model routing with per-model buckets, 6 pipeline fixes from trace analysis, demo replay, pipeline SVG, activity log, sources table, replay prompt refill), full docs set (README, `Docs/MVP.md` + deviations Appendix A, `startup.md`, `architecture.md`, `Docs/Tool-MCP.md`, per-milestone reports).

**Not done (accepted, documented):**

| Item | Why not |
|---|---|
| Gated Hitler retest (probe_extract + full skeptic-claim run, expected False) | Was gated on a budget check; the key expired before it ran. ~13K tokens. The 7 pipeline fixes behind it are covered by offline regression tests |
| MVP §17 stretch: HITL retry approval, Markdown export | Explicitly optional; SQLite checkpointer effectively superseded by the `/demo` JSONL replay |
| Concurrent `/check` runs share one global trace file | Known limitation of `app/trace.py`; single-user demo makes it moot |

## How to run (summary)

See `README.md` (10-line setup) and `Docs/startup.md` (full cold-start + troubleshooting). Tests: `pytest tests -q` (76, offline). Demo replay: ▶ button, zero tokens.
