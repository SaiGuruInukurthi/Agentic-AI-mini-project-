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

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("factchecker.api")

RUN_BUDGET_SECONDS = 180


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

    async def event_stream():
        try:
            async with asyncio.timeout(RUN_BUDGET_SECONDS):
                async for chunk in graph.astream({"claim": text, "retries": 0}, stream_mode="updates"):
                    for node, update in chunk.items():
                        if node == "extract_claims":
                            yield _sse({"type": "progress", "node": node, "detail": "Checking claim"})
                        elif node == "search":
                            n = len(update.get("sources", []))
                            yield _sse({"type": "progress", "node": node, "detail": f"Found {n} candidate sources"})
                        elif node == "branch":
                            finding = update["findings"][-1]
                            yield _sse({"type": "progress", "node": node,
                                        "detail": f"Checked {finding['title'] or finding['url']}"})
                            yield _sse({"type": "finding", "finding": finding})
                        elif node == "summarize" and update:
                            yield _sse({
                                "type": "result",
                                "claim": text,
                                "verdict": update.get("verdict", "Unverifiable"),
                                "score": update.get("score", 0.0),
                                "explanation": update.get("explanation", ""),
                                "findings": [],
                            })
                log_usage()
        except asyncio.TimeoutError:
            yield _sse({"type": "error", "message": "Run exceeded 3 minute budget; aborted with partial results"})
        except Exception as e:
            log.exception("Run failed")
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
