# Multi-Agent Fact-Checker

Paste a claim, get a verdict (True / False / Mixed / Unverifiable) with cited sources. LangGraph + MCP + Groq. See `Docs/MVP.md` for the spec and `Docs/reports/` for build logs.

## Setup (Windows PowerShell)

```
conda activate mini
pip install -r requirements.txt
copy .env.example .env   # then set GROQ_API=... in .env
python cli.py "The Great Wall of China is visible from space"
```

## Web UI

```
python -m uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Paste a claim and press **Check claim**, or press **▶ Demo replay** to replay the latest recorded run from `logs/` with zero tokens consumed.

## Tests (no API calls)

```
python -m pytest tests -q
```
