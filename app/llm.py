"""All LLM access lives here: Groq client, JSON validation, rate limits, usage tracking."""
import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from groq import AsyncGroq, RateLimitError
from pydantic import BaseModel, ValidationError

load_dotenv()

log = logging.getLogger("factchecker.llm")

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_CONCURRENCY = 2
RETRY_AFTER_MAX_TRIES = 3
JSON_RETRIES = 1
RATE_LIMIT_WAIT_THRESHOLD = 5000

_sem = asyncio.Semaphore(MAX_CONCURRENCY)
_usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}


def get_client() -> AsyncGroq:
    api_key = os.environ.get("GROQ_API")
    if not api_key:
        raise RuntimeError(
            "Missing GROQ_API environment variable. Copy .env.example to .env and set it."
        )
    return AsyncGroq(api_key=api_key)


def log_usage() -> None:
    log.info(
        "LLM usage so far: %d requests, %d prompt tokens, %d completion tokens",
        _usage["requests"],
        _usage["prompt_tokens"],
        _usage["completion_tokens"],
    )


def _accumulate(usage) -> None:
    if usage is None:
        return
    _usage["requests"] += 1
    _usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
    _usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0


def _extract(content: str, schema: type[BaseModel]) -> BaseModel | None:
    try:
        data = json.loads(content)
        return schema.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("JSON/validation failed: %s", e)
        return None


async def chat_json(
    client: AsyncGroq,
    messages: list[dict],
    schema: type[BaseModel],
    max_tokens: int = 600,
) -> BaseModel | None:
    backoff = 2.0
    for attempt in range(RETRY_AFTER_MAX_TRIES):
        try:
            async with _sem:
                raw = await client.chat.completions.with_raw_response.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                    reasoning_effort="low",
                    response_format={"type": "json_object"},
                )
            remaining = raw.headers.get("x-ratelimit-remaining-tokens")
            if remaining and remaining.isdigit() and int(remaining) < RATE_LIMIT_WAIT_THRESHOLD:
                log.info("Rate limit budget low (%s tokens left), pausing", remaining)
                await asyncio.sleep(2)
            completion = await raw.parse()
            _accumulate(completion.usage)
            parsed = _extract(completion.choices[0].message.content or "", schema)
            if parsed is not None:
                return parsed
            if len(messages) and attempt < JSON_RETRIES:
                log.info("Retrying with stricter JSON reminder")
                messages = messages + [
                    {
                        "role": "user",
                        "content": "Your previous response was not valid JSON matching the schema. Respond again with ONLY valid JSON, no extra text.",
                    }
                ]
                continue
            return None
        except RateLimitError as e:
            retry_after = None
            if e.response is not None:
                retry_after = e.response.headers.get("retry-after")
            wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else backoff
            log.warning("HTTP 429, waiting %.1fs (attempt %d/%d)", wait, attempt + 1, RETRY_AFTER_MAX_TRIES)
            await asyncio.sleep(wait)
            backoff *= 2
        except Exception as e:
            log.error("LLM call failed: %s: %s", type(e).__name__, e)
            return None
    log.error("LLM still rate limited after %d tries; caller should fall back to unclear", RETRY_AFTER_MAX_TRIES)
    return None
