# M6 update — Model routing + doc corrections (19-10-2026 13-26)

Post-M6 enhancement session. All changes committed after this report.

## What changed

### 1. Model routing in `app/llm.py` (user decision: summarizer + rewrite + extractor → big model)
- `chat_json(..., role=)` now routes by role: **`openai/gpt-oss-120b`** (`reasoning_effort="medium"`) for summarizer / query-rewrite / claim-extraction; **`openai/gpt-oss-20b`** (`"low"`, unchanged) for read + critique.
- Rationale (verified against console.groq.com/docs/rate-limits): Groq free-tier limits are **per model** — gpt-oss-20b / gpt-oss-120b / qwen3.8-27b each have their own 30 RPM / 1K RPD / 8K TPM / **200K TPD** bucket. Routing splits usage across two buckets, roughly doubling effective daily capacity, and puts the stronger reasoner (120b ≈ o4-mini class: MMLU 90 vs 85.3, reasoning 61.6 vs 49.7) where judgment matters.
- **Fallback chain**: on generic model errors (404 `model_not_found` etc.) or an exhausted bucket (429s surviving the backoff loop), `chat_json` retries the same schema on `qwen/qwen3.8-27b` (`GROQ_MODEL_FALLBACK`); invalid JSON is *not* a fallback trigger (budget protection). Env vars: `GROQ_MODEL`, `GROQ_MODEL_BIG`, `GROQ_MODEL_FALLBACK` (added to `.env.example`).
- Usage tracking is now **per model** (`log_usage` prints one line per bucket).
- Call sites: `nodes.py` (extract+rewrite → `"big"`, read+critique → `"small"`) and `graph.py` (summarizer → `"big"`).

### 2. Doc corrections (all user-flagged)
- `Docs/architecture.md` §7: DFD arrow `RD -->|summary| CRQ` was wrong (violated the independence rule) → critique now receives `claim + passages ONLY` from EP; added a Finding-assembly node; quoted/rephrased the verdict edge label (no unquoted `<`, which can break Mermaid). §8: removed parentheses from class attributes. §1 diagram now shows both models.
- `Docs/reports/19-10-2026 12-53_Final_report.md`: budget section corrected — the free cap is 200K tokens/day **per model**, not 500K; the "~15 runs / 12+ remain" estimate was wrong (~110K remained on the 20b bucket that day).
- `Docs/MVP.md`: §3.1 model row inline-fixed to `openai/gpt-oss-20b` (retirement noted); token-budget paragraph corrected; **new Appendix A** lists all 7 verified spec deviations.
- `AGENTS.md`: routing note + per-model bucket warning. `Docs/startup.md`: env var triple documented. Docs `startup.md`/`architecture.md` moved into `Docs/` (uncommitted move landed in this commit).

### 3. Tests
- `tests/test_llm_routing.py` (new, 6 tests, fully offline with a stub Groq client): role→model order, effort per role, fallback serving after primary error, no infinite loop when fallback == primary, invalid JSON does not fall back.
- Test fakes in `test_api_m5.py` / `test_graph_m3.py` / `test_m6.py` updated for the new `role` kwarg.
- **Result: 57 passed** (51 prior + 6 new), ~1.4s, zero API calls.

## Live acceptance run (one only, Mixed-path check)
Claim: "Drinking eight glasses of water a day is required for good health" (spec §16 expected Mixed).

- **Verdict: False (score −0.61)** — not Mixed, but formula-correct: exactly 2 findings had a clear stance, both *contradict* (Healthline conf 0.9, doctronic conf 0.92; unclear stances weigh 0), so the weighted score went below −0.4. The spec's "Mixed" expectation assumed split sources; the formula behaved exactly as designed (verdict never comes from the LLM).
- **Routing validated live**: usage log shows `gpt-oss-20b`: 10 requests (5 read + 5 critique), `gpt-oss-120b`: 1 request (summarizer). Extract/rewrite did not run (CLI path, single claim, no retry — verdict False ends the graph before `prep_retry`).
- Token spend this run: 20b bucket ≈ 5.6K (4690 in / 891 out); 120b bucket ≈ 1.0K. TPM header pauses fired correctly (e.g. "4526 tokens left, pausing"); no 429s; no fallback needed.
- Designed degradation observed: Mayo Clinic (robots.txt 403) and physiology.org (HTTP 403) fetches failed → those branches got credibility 0.3 / unclear without crashing.

## Notes / minor issues
- Source [2]'s title from search was a garbled concatenation of several results (DDG snippet quirk); the URL and evidence were still correct. Cosmetic only.
- Remaining manual check (user): open the UI in a browser and confirm live progress + result cards (costs nothing).
- 20b bucket today: ~85–95K spent total; 120b bucket barely touched; resets midnight UTC.
