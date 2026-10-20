"""FastAPI backend: serves the UI and streams LangGraph events over SSE."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .graph import build_graph
from .llm import get_client, log_usage
from .mcp_client import MCPManager
from .nodes import extract_claims_llm
from . import trace

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("factchecker.api")

RUN_BUDGET_SECONDS = 180
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_client()
    mcp = MCPManager()
    await mcp.__aenter__()
    app.state.mcp = mcp
    app.state.llm = client
    log.info("MCP servers started")
    yield
    await mcp.__aexit__(None, None, None)
    log.info("MCP servers stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse((Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8"))


@app.post("/check")
async def check(request: Request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'message': 'empty text'})}\n\n"]),
            media_type="text/event-stream",
        )

    graph = build_graph(request.app.state.mcp, request.app.state.llm)

    trace.start_run("api")
    trace.event("user_input", text=text)

    async def event_stream():
        try:
            async with asyncio.timeout(RUN_BUDGET_SECONDS):
                claims, notice = await extract_claims_llm(request.app.state.llm, text)
                if not claims:
                    claims = [text]
                yield _sse({"type": "progress", "node": "extract_claims",
                            "detail": f"Extracted {len(claims)} claim(s)" + (f" - {notice}" if notice else "")})
                if notice:
                    yield _sse({"type": "notice", "message": notice})
                for idx, claim in enumerate(claims, 1):
                    yield _sse({"type": "progress", "node": "search",
                                "detail": f"Claim {idx}/{len(claims)}: checking sources"})
                    summary = {}
                    retries_seen = 0
                    async for chunk in graph.astream({"claim": claim, "retries": 0}, stream_mode="updates"):
                        for node, update in chunk.items():
                            if node == "prep_retry":
                                retries_seen = update.get("retries", retries_seen + 1)
                            elif node == "search":
                                n = len(update.get("sources", []))
                                retries = update.get("retries", 0)
                                label = "Retrying with refined query" if retries else "Found"
                                yield _sse({"type": "progress", "node": node,
                                            "detail": f"{label}: {n} candidate sources"})
                            elif node == "branch":
                                finding = update["findings"][-1]
                                trace.event("finding", finding=finding)
                                yield _sse({"type": "progress", "node": node,
                                            "url": finding["url"],
                                            "detail": f"Checked {finding['title'] or finding['url']}"})
                                yield _sse({"type": "finding", "finding": finding})
                            elif node == "summarize" and update:
                                summary = update
                    trace.event("claim_result", claim=claim, verdict=summary.get("verdict", "Unverifiable"),
                                score=summary.get("score", 0.0), retries=retries_seen,
                                explanation=summary.get("explanation", ""))
                    yield _sse({
                        "type": "result",
                        "claim": claim,
                        "verdict": summary.get("verdict", "Unverifiable"),
                        "score": summary.get("score", 0.0),
                        "explanation": summary.get("explanation", ""),
                        "findings": [],
                        "retries": retries_seen,
                    })
                log_usage()
        except asyncio.TimeoutError:
            trace.event("run_error", error="timeout: exceeded 180s budget")
            yield _sse({"type": "error", "message": "Run exceeded 3 minute budget; aborted with partial results"})
        except Exception as e:
            log.exception("Run failed")
            trace.event("run_error", error=f"{type(e).__name__}: {e}")
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/demo")
async def demo(file: str | None = None):
    """Replay a recorded run from logs/ as SSE — zero tokens consumed."""
    log_dir = LOGS_DIR
    if not log_dir.exists():
        return StreamingResponse(
            iter([_sse({"type": "error", "message": "No recorded runs in logs/. Run a check first."})]),
            media_type="text/event-stream",
        )
    files = sorted(log_dir.glob("*.jsonl"))
    if not files:
        return StreamingResponse(
            iter([_sse({"type": "error", "message": "No recorded runs in logs/. Run a check first."})]),
            media_type="text/event-stream",
        )
    path = log_dir / file if file else files[-1]
    if not path.exists():
        return StreamingResponse(
            iter([_sse({"type": "error", "message": f"Trace file not found: {file}"})]),
            media_type="text/event-stream",
        )

    events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    async def replay_stream():
        for sse in _replay_sse(events):
            yield sse
            await asyncio.sleep(0.3)

    return StreamingResponse(replay_stream(), media_type="text/event-stream")


def _replay_sse(events: list[dict]):
    """Convert trace events to the same SSE shapes the frontend expects."""
    # Extract claims from llm_response (ExtractedClaims schema)
    claims, notice = None, ""
    for e in events:
        if e["kind"] == "llm_response" and "ExtractedClaims" in str(e.get("schema", "")):
            parsed = e.get("parsed") or {}
            claims = parsed.get("claims") or None
            notice = parsed.get("notice") or ""
            break

    if claims is None:
        claims = [e["claim"] for e in events if e["kind"] == "claim_result"] or None
    if not claims:
        yield _sse({"type": "error", "message": "Trace has no claims to replay."})
        return

    ui = next((e.get("text") for e in events if e["kind"] == "user_input"), None)
    yield _sse({"type": "input", "text": ui or claims[0]})

    yield _sse({"type": "progress", "node": "extract_claims",
                "detail": f"Extracted {len(claims)} claim(s)" + (f" - {notice}" if notice else "")})
    if notice:
        yield _sse({"type": "notice", "message": notice})

    # Split events into per-claim segments (ends at claim_result)
    segments = []
    current = []
    for e in events:
        if e["kind"] == "claim_result":
            current.append(e)
            segments.append(current)
            current = []
        elif e["kind"] in ("mcp_search", "mcp_search_result", "mcp_fetch", "llm_attempt", "finding"):
            current.append(e)

    for idx, seg in enumerate(segments, 1):
        cr = seg[-1]
        claim = cr["claim"]
        yield _sse({"type": "progress", "node": "search",
                    "detail": f"Claim {idx}/{len(segments)}: checking sources"})
        search_round = 0
        current_url = None
        for e in seg:
            k = e["kind"]
            if k == "mcp_search":
                search_round += 1
                yield _sse({"type": "progress", "node": "search",
                            "detail": f'Searching: "{e["query"]}"'})
            elif k == "mcp_search_result":
                n = e.get("n", 0)
                label = "Retrying with refined query" if search_round > 1 else "Found"
                yield _sse({"type": "progress", "node": "search",
                            "detail": f"{label}: {n} candidate sources"})
            elif k == "mcp_fetch":
                current_url = e["url"]
                yield _sse({"type": "progress", "node": "read", "url": current_url,
                            "detail": f"Reading {current_url}"})
            elif k == "llm_attempt":
                schema = str(e.get("schema", ""))
                if "Critique" in schema and current_url:
                    yield _sse({"type": "progress", "node": "critique", "url": current_url,
                                "detail": "Independent critique"})
                elif "QueryRewrite" in schema:
                    yield _sse({"type": "progress", "node": "search",
                                "detail": "Rewriting search query for retry"})
                elif "Explanation" in schema:
                    yield _sse({"type": "progress", "node": "summarize",
                                "detail": "Writing verdict"})
            elif k == "finding":
                f_ = e["finding"]
                yield _sse({"type": "progress", "node": "branch", "url": f_.get("url", ""),
                            "detail": f"Checked {f_.get('title') or f_.get('url', '')}"})
                yield _sse({"type": "finding", "finding": f_})
        yield _sse({
            "type": "result", "claim": claim,
            "verdict": cr["verdict"], "score": cr["score"],
            "explanation": cr.get("explanation", ""),
            "findings": [], "retries": cr.get("retries", 0),
        })
    yield _sse({"type": "progress", "node": "done", "detail": "Replay finished (no tokens used)"})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
