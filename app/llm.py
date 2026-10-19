"""All LLM access lives here: Groq client, model routing, JSON validation, rate limits, usage tracking."""
import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from groq import AsyncGroq, RateLimitError
from pydantic import BaseModel, ValidationError

from . import trace

load_dotenv()

log = logging.getLogger("factchecker.llm")

# Model routing. Groq free-tier limits are PER MODEL (separate ~200K TPD buckets),
# so high-volume per-source calls run on the small model while reasoning-heavy
# calls run on the big one: two buckets instead of one, and stronger judgment
# where it matters. The fallback covers retired/blocked models and exhausted buckets.
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MODEL_BIG = os.getenv("GROQ_MODEL_BIG", "openai/gpt-oss-120b")
MODEL_FALLBACK = os.getenv("GROQ_MODEL_FALLBACK", "qwen/qwen3.8-27b")

MODEL_ROLES = {"small": MODEL, "big": MODEL_BIG}
EFFORT_BY_ROLE = {"big": "medium", "small": "low"}
DEFAULT_ROLE = "small"

MAX_CONCURRENCY = 2
RETRY_AFTER_MAX_TRIES = 3
JSON_RETRIES = 1
RATE_LIMIT_WAIT_THRESHOLD = 5000

_sem = asyncio.Semaphore(MAX_CONCURRENCY)
_usage: dict[str, dict[str, int]] = {}


def get_client() -> AsyncGroq:
    api_key = os.environ.get("GROQ_API")
    if not api_key:
        raise RuntimeError(
            "Missing GROQ_API environment variable. Copy .env.example to .env and set it."
        )
    return AsyncGroq(api_key=api_key)


def log_usage() -> None:
    for model, u in _usage.items():
        log.info(
            "LLM usage so far [%s]: %d requests, %d prompt tokens, %d completion tokens",
            model,
            u["requests"],
            u["prompt_tokens"],
            u["completion_tokens"],
        )


def _accumulate(model: str, usage) -> None:
    u = _usage.setdefault(model, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0})
    u["requests"] += 1
    u["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
    u["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0


def _extract(content: str, schema: type[BaseModel]) -> BaseModel | None:
    try:
        data = json.loads(content)
        return schema.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("JSON/validation failed: %s", e)
        return None


async def _chat_attempt(
    client: AsyncGroq,
    model: str,
    effort: str,
    messages: list[dict],
    schema: type[BaseModel],
    max_tokens: int,
) -> tuple[str, BaseModel | None]:
    """Run against one candidate model. Status: ok (parsed, maybe None) | rate_limited | error."""
    backoff = 2.0
    for attempt in range(RETRY_AFTER_MAX_TRIES):
        try:
            trace.event("llm_attempt", schema=schema.__name__, model=model, attempt=attempt, messages=messages)
            async with _sem:
                raw = await client.chat.completions.with_raw_response.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                    reasoning_effort=effort,
                    response_format={"type": "json_object"},
                )
            remaining = raw.headers.get("x-ratelimit-remaining-tokens")
            if remaining and remaining.isdigit() and int(remaining) < RATE_LIMIT_WAIT_THRESHOLD:
                log.info("Rate limit budget low (%s tokens left), pausing", remaining)
                await asyncio.sleep(2)
            completion = await raw.parse()
            _accumulate(model, completion.usage)
            content = completion.choices[0].message.content or ""
            parsed = _extract(content, schema)
            trace.event(
                "llm_response",
                schema=schema.__name__,
                model=model,
                content=content,
                parsed=parsed.model_dump() if parsed else None,
                usage={
                    "prompt_tokens": getattr(completion.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(completion.usage, "completion_tokens", 0) or 0,
                },
            )
            if parsed is not None:
                return "ok", parsed
            if len(messages) and attempt < JSON_RETRIES:
                log.info("Retrying with stricter JSON reminder")
                messages = messages + [
                    {
                        "role": "user",
                        "content": "Your previous response was not valid JSON matching the schema. Respond again with ONLY valid JSON, no extra text.",
                    }
                ]
                continue
            return "ok", None
        except RateLimitError as e:
            retry_after = None
            if e.response is not None:
                retry_after = e.response.headers.get("retry-after")
            wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else backoff
            log.warning(
                "HTTP 429 on %s, waiting %.1fs (attempt %d/%d)",
                model,
                wait,
                attempt + 1,
                RETRY_AFTER_MAX_TRIES,
            )
            await asyncio.sleep(wait)
            backoff *= 2
        except Exception as e:
            log.error("LLM call failed on %s: %s: %s", model, type(e).__name__, e)
            return "error", None
    return "rate_limited", None


async def chat_json(
    client: AsyncGroq,
    messages: list[dict],
    schema: type[BaseModel],
    max_tokens: int = 600,
    role: str = DEFAULT_ROLE,
) -> BaseModel | None:
    """Structured LLM call with role-based model routing and a fallback model.

    Roles: "small" (high-volume per-source work), "big" (reasoning/judgment work).
    Falls back to MODEL_FALLBACK when the primary errors or its bucket is exhausted;
    invalid JSON is NOT a fallback trigger (callers map None to an unclear finding).
    """
    effort = EFFORT_BY_ROLE.get(role, "low")
    primary = MODEL_ROLES.get(role, MODEL)
    candidates = [primary] + ([MODEL_FALLBACK] if MODEL_FALLBACK != primary else [])
    for i, model in enumerate(candidates):
        status, parsed = await _chat_attempt(client, model, effort, messages, schema, max_tokens)
        trace.event("llm_done", schema=schema.__name__, model=model, status=status, fallback=i > 0)
        if status == "ok":
            if i > 0:
                log.info("Request for %s served by fallback model %s", schema.__name__, model)
            return parsed
        if i + 1 < len(candidates):
            log.warning(
                "%s unavailable on %s (%s); falling back to %s",
                schema.__name__,
                model,
                status,
                candidates[i + 1],
            )
            continue
    log.error("All models failed or rate limited; caller should fall back to unclear")
    return None
