# Startup Guide

Cold-start sequence for this machine (Windows + PowerShell + conda `mini`). Every command here was verified during the M1–M6 build; see `AGENTS.md` for the quirks behind them.

## 1. Prerequisites

- conda env **`mini`** (Python 3.12) — checked in, not created
- `GROQ_API` in `.env` (never committed). `GROQ_MODEL` defaults to `openai/gpt-oss-20b`
- `uv` (for the fetch MCP server) and Node.js are optional but recommended

## 2. Activate the environment

In an **interactive** PowerShell:

```powershell
conda activate mini
```

In scripts or agent shells, `conda activate` can silently keep base Python. Use the full path instead:

```powershell
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" ...
```

## 3. Install dependencies

```powershell
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" -m pip install -r requirements.txt
```

## 4. Verify install (no API calls, ~5s)

```powershell
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" -m pytest tests -q
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" samples\smoke_mcp.py
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" samples\smoke_evidence.py
```

Expect `51 passed` from pytest.

## 5. CLI fact-check (uses live Groq calls)

```powershell
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" cli.py "Water boils at 100 degrees Celsius at sea level"
```

Prints verdict, score, explanation, and per-source findings. A full run is ~13 LLM calls / ~10–30K tokens.

## 6. Web UI

```powershell
& "C:\Users\IC1807\anaconda3\envs\mini\python.exe" -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000, paste a claim, press Check. Live progress streams per source; each claim gets its own result card.

## Troubleshooting (seen during the build)

| Symptom | Cause / fix |
|---|---|
| `model_not_found` 404 | Model ID changed; check available models via the Groq console and update `GROQ_MODEL` |
| `json_validate_failed` (400, empty generation) | Reasoning tokens ate the budget; `reasoning_effort="low"` + `max_tokens>=600` is already set in `app/llm.py` |
| DDG "anomaly detected" | Free-engine flakiness; search tool retries 3x, or just rerun later |
| `UnicodeEncodeError: charmap` on print | cp1252 console; `cli.py` already reconfigures stdout to UTF-8 |
| anyio "cancel scope in a different task" on shutdown | Don't hand-manage MCP sessions; use `MCPManager` (AsyncExitStack) as one async context |
| Backend starts then requests hang | MCP servers spawn as subprocesses at startup; first start can take ~10s |
| Search returns <2 sources | Pipeline returns Unverifiable by design; retry loop may re-search once |
