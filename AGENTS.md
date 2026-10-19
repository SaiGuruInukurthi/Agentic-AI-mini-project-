# AGENTS.md

Rules for any coding agent working in this repo. Read this file and `Docs/MVP.md` before doing anything. `Docs/MVP.md` is the spec; this file is how to work on it.

## 1. Environment (Windows + PowerShell + conda)

- OS shell is **Windows PowerShell**.
- Use the conda environment named **`mini`** for everything (installs, running, tests).
- **Do NOT use `conda run`.** It does not work on this machine.
- Always activate the environment first, then run the command in the same invocation:

  ```powershell
  conda activate mini; python cli.py "some claim"
  ```

  Pattern: `conda activate mini` -> then the command. Use `;` to chain. (`&&` may not work in older PowerShell.)
- **Verified quirk (19-10-2026):** in agent tool shells, `conda activate mini; python ...` can silently keep base Python (3.13) instead of `mini` (3.12). The reliable pattern is the full path:

  ```powershell
  & "C:\Users\IC1807\anaconda3\envs\mini\python.exe" path\to\script.py
  ```

  Use the full path for anything that must run in `mini`; use `conda activate mini` only in interactive shells.
- Install packages with `...envs\mini\python.exe -m pip install ...`, then add them to `requirements.txt`.

## 2. PowerShell quoting (it mangles quotes, be careful)

PowerShell often breaks nested or escaped quotes. To avoid silent corruption:

- **Never** pass multi-line code or JSON through `python -c "..."` or inline shell strings.
- Put code in a file (`.py`, `.json`, `.txt`) and run the file instead.
- For test claims or text with quotes, store them in a file (for example `samples/claims.txt`) and read from it.
- When a command must contain quotes, prefer single quotes outside and double quotes inside (or the reverse), and keep it to one short line.
- If output looks garbled or a quote went missing, stop and fix the quoting. Do not guess and retry in a loop.

## 3. Groq usage: protect the free limits

The Groq free tier is limited and cannot be refilled. Treat every live call as expensive.

- **Keep live testing minimal.** Do not run the full pipeline repeatedly.
- Prefer tests that need **no API calls**: unit tests for `verdict.py`, the quote-in-passages check, credibility rules, passage extraction, and the evidence MCP server.
- For graph and UI work, use **mocked or recorded LLM responses** (fixtures in `tests/fixtures/`) instead of real calls.
- Never put LLM calls inside loops, retries without a cap, or startup code.
- Maximum **one live end-to-end run at a time**, with a single claim and the minimum number of sources needed to check the behavior. Run it only when a milestone's acceptance check requires it.
- Do not "try again to see if it works". If a live run fails, read the error, report it, and wait.
- Never print, log, or commit `GROQ_API`. It lives in `.env` only.
- **Never read the contents of `.env`** (not even with the Read tool). Code loads it via `python-dotenv` at runtime only.
- Log token usage after each live run so the budget is visible.

## 4. Workflow

- Build in the order of the milestones in `Docs/MVP.md` Section 12 (M1 to M6). Do not start the next milestone until the current acceptance check passes.
- **Full-project build authorized (19-10-2026):** the user has OK'd building M1 to M6 in one session. Work milestone by milestone; after each one, write a timestamped report to `Docs/reports/` named `DD-MM-YYYY HH-MM_<M#>_<type>.md` (e.g. `19-10-2026 13-00_M1_report.md`), give the user a brief summary, then continue.
- **Pause and wait for feedback only if** an acceptance check fails, a live run errors, or the token budget is at risk. Do not self-iterate with live API calls to polish results.
- The spec's model `llama-3.1-8b-instant` was retired (verified 404 "model_not_found" on 19-10-2026; Llama 3.x retired for self-serve 2026-08-16). `app/llm.py` routes by role: `openai/gpt-oss-120b` (`reasoning_effort=medium`) for summarizer / query-rewrite / claim-extraction; `openai/gpt-oss-20b` (`low`) for read + critique; `qwen/qwen3.8-27b` as automatic fallback on model errors or an exhausted bucket. Env vars: `GROQ_MODEL`, `GROQ_MODEL_BIG`, `GROQ_MODEL_FALLBACK`. Groq free-tier limits are **per model** (separate 200K TPD buckets — budget math uses 200K/model, NOT the spec's 500K); routing roughly doubles effective daily capacity.
- MCP server choices (verified 19-10-2026): search is our own FastMCP server `mcp_servers/search_server.py` wrapping `ddgs` (the npm `duckduckgo-mcp-server` triggers DDG anomaly detection from this network), fetch via `uvx mcp-server-fetch` (keyless); MCP clients use the official `mcp` Python SDK, pinned `<2` in `requirements.txt` (FastMCP was renamed in mcp 2.x), no `langchain-mcp-adapters`. Free search engines are flaky; the search tool already retries up to 3 times.
- Keep changes small and scoped to the milestone. No extra features outside `Docs/MVP.md` Section 2.
- If something in the spec is unclear or seems wrong, say so in the report rather than silently changing the design.
- All LLM access goes through `app/llm.py` only.
- File paths referenced here (`app/llm.py`, `verdict.py`, `tests/`, `cli.py`) follow the target layout in `Docs/MVP.md` Section 14. Until a milestone creates them, they do not exist yet.
- Commit after each milestone with a clear message. Never commit `.env`.

## 5. Quick reference

| Task | Command |
|---|---|
| List files | `dir` |
| Activate env (interactive only) | `conda activate mini` |
| Run a script in `mini` | `& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" path\to\script.py` |
| Run unit tests (no API) | `& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" -m pytest tests -q` |
| Install a package | `& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" -m pip install <package>` |
| Run backend (M5+) | `& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" -m uvicorn app.main:app --reload` |
| MCP smoke test (no API) | `& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" samples\smoke_mcp.py` |
