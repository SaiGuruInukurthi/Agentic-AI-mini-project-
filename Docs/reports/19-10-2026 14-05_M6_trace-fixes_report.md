# 19-10-2026 14:05 — Post-trace fixes: verdict math, retry dedup, fetch-error handling

## Trigger

Live-trace feedback (input: "Did Hitler kill 6 million Jews? or as it 200k shown as 6 million?"). Claim 2 came out Mixed (−0.31) but is semantically False. The formula matched the user's hand recomputation (−0.17, −0.31), so the inputs and the formula definition were the problems. Six fixes, all implemented with mocked tests only — **no live Groq calls were spent**.

## Fixes (files)

1. **Extractor disputed-figure rule** (`app/prompts.py`): EXTRACT_PROMPT now requires that when the user questions/disputes a figure, the claim carries the disputed figure AND the contrast ("Only about 200,000 Jews were killed…, not six million."), never a bare-number claim the real figure would imply. The old prompt produced "Hitler killed 200,000 Jews.", which six million implies — that fed the bad dulcinea critique.
2. **Verdict denominator** (`app/verdict.py`): `compute_score` now sums weight over clear-stance findings only; `unclear` no longer dilutes toward 0. Trace regression test: contradicts 0.8×0.95 + contradicts 0.5×0.95 + supports 0.5×0.95 + unclears → −0.76/1.71 = **−0.44 → False** (was −0.31 Mixed). Also: unclear-only findings → score 0.
3. **Retry dedup** (`app/graph.py`): `make_fan_out` filters out sources whose URL already has a finding; findings deduped by URL in `summarize_node` and `route_after_summarize`. Round-2 of the trace re-read 4 URLs (271k page, Times of Israel, factually) and double-counted them. The `<2 sources → summarize` rule is unchanged in both rounds — a retry with <2 fresh sources can never reach the 2-clear-findings floor, so branching would only burn LLM calls (debug-verified during this fix).
4. **Summarizer input** (`app/verdict.py`, `app/graph.py`, `app/prompts.py`): new pure helpers `stance_counts` + `strongest_findings` (strongest supports + strongest contradicts by cred×conf, keeping original [i] indices so citations stay valid). SUMMARIZER_PROMPT gets counts + strongest block, "cite the strongest source on each side", and "unclear is not disagreement". Fixes the trace case where the summarizer discussed 2 of 10 findings and called an ambiguous source a disagreement.
5. **Fetch-error short-circuit** (`app/mcp_client.py`, `app/nodes.py`): `fetch_page` detects the full prefix "Error executing tool fetch" (successful fetches start "Contents of") and returns ""; `read_agent`'s empty-page branch now keeps **domain credibility** (Britannica 403 → 0.8, not 0.3) with note "page could not be read", and makes zero LLM calls (critique already returns unclear without calls when passages are empty). `max_length` 10000 → 20000. In the trace this wastes ~10 of ~45 calls.
   - Guarded side effect: `route_after_summarize`'s "credible" count now requires a clear stance — two fetch-failed 0.8/0.85 unclear findings would otherwise wrongly suppress a deserved retry.
6. **Evidence cleanup** (`mcp_servers/evidence_core.py`): `_clean_page_text` strips `<error>` markers and link-list/nav lines (≥3 URLs on a line) before `extract_passages`; `extract_date` trusts only `<meta>` publish-time tags and `<time datetime>` — body-date fallback (1931, 1934) and site-clock dates removed, killing false +0.05 recency bonuses.
7. **Critique figure rule** (`app/prompts.py`): "If the passages give a figure different from the claim's figure, that is 'contradicts', not 'supports'." — targets the dulcinea "6M includes 200k → supports 0.95" logic error.

## Tests

- `tests/test_verdict.py` +2 (trace regression −0.44/False; unclear-only → 0.0)
- `tests/test_prompts.py` NEW +3 (disputed-figure rule, contradicts-not-supports rule, summarizer counts/strongest/unclear rule)
- `tests/test_graph_m3.py` +8, ~2 updated: fan-out dedup unit tests (round-1 <2 rule, retry skips seen URLs, retry 0-fresh → summarize), URL dedupe, unclear-high-cred not "credible", summarizer prompt capture (counts + strongest + indices), fetch-error prefix detection on MCPManager, fetch-error branch zero-LLM-calls (exploding fake chat)
- `tests/test_evidence.py`: date tests rewritten for meta-only (body dates/US/EU/slash formats now correctly return None); `_clean_page_text` tests (error marker, link lines)
- **74 passed, 1.5s, zero API.** (Was 60.)

## Spec docs updated (`Docs/MVP.md`)

- §8 `extract_date` row → meta/`<time>` only
- §9 formula → clear-stance denominator
- §10 → credible requires clear stance; retry skips URLs with findings
- §13 → fetch failure keeps domain credibility, zero LLM calls
- Appendix A → deviations #8–#11 recorded

## Live retest (GATED — do not run without a console check)

`samples/probe_extract.py` runs ONLY `extract_claims_llm` on the original Hitler input (one 120b call, separate 200K bucket from the 20b read/critique bucket). Expected: claim carries the disputed figure + contrast. **Next step: user checks the Groq console for remaining budget, runs the probe, and only then one full pipeline run of the skeptic claim — expected False.**
