"""Offline tests for model routing in app/llm.py: role -> model mapping, effort, fallback order."""
from types import SimpleNamespace

from pydantic import BaseModel

import app.llm as llm


class Echo(BaseModel):
    query: str


def _stub_client(fail_on=(), content='{"query": "ok"}', calls=None):
    """AsyncGroq stand-in. Fails (generic error) for models listed in fail_on; records every call."""

    class _Raw:
        headers = {}

        async def parse(self):
            return SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            )

    class _WR:
        def __init__(self):
            self.headers = {}

        async def create(self, **kwargs):
            if calls is not None:
                calls.append((kwargs["model"], kwargs["reasoning_effort"]))
            if kwargs["model"] in fail_on:
                raise RuntimeError("model_not_found")
            return _Raw()

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=_WR()))
    )


def _stub_with_role(client, role):
    import asyncio

    return asyncio.run(
        llm.chat_json(client, [{"role": "user", "content": "x"}], Echo, role=role)
    )


def test_big_role_uses_big_model_first_then_fallback():
    calls = []
    client = _stub_client(fail_on=(llm.MODEL_BIG, llm.MODEL_FALLBACK), calls=calls)
    result = _stub_with_role(client, "big")
    assert result is None
    assert [m for m, _ in calls] == [llm.MODEL_BIG, llm.MODEL_FALLBACK]


def test_small_role_is_default():
    calls = []
    client = _stub_client(fail_on=(llm.MODEL, llm.MODEL_FALLBACK), calls=calls)
    result = _stub_with_role(client, "small")
    assert result is None
    assert [m for m, _ in calls] == [llm.MODEL, llm.MODEL_FALLBACK]


def test_fallback_serves_after_primary_model_error():
    calls = []
    client = _stub_client(fail_on=(llm.MODEL,), calls=calls)
    result = _stub_with_role(client, "small")
    assert result is not None and result.query == "ok"
    assert [m for m, _ in calls] == [llm.MODEL, llm.MODEL_FALLBACK]


def test_effort_is_medium_for_big_and_low_for_small():
    calls = []
    _stub_with_role(_stub_client(calls=calls), "big")
    _stub_with_role(_stub_client(calls=calls), "small")
    efforts = {m: e for m, e in calls}
    assert efforts[llm.MODEL_BIG] == "medium"
    assert efforts[llm.MODEL] == "low"


def test_no_fallback_loop_when_fallback_equals_primary(monkeypatch):
    monkeypatch.setattr(llm, "MODEL_FALLBACK", llm.MODEL)
    calls = []
    client = _stub_client(fail_on=(llm.MODEL,), calls=calls)
    result = _stub_with_role(client, "small")
    assert result is None
    assert [m for m, _ in calls] == [llm.MODEL]


def test_invalid_json_does_not_fall_back():
    calls = []
    client = _stub_client(content="not json at all", calls=calls)
    result = _stub_with_role(client, "small")
    assert result is None
    # 2 attempts on the primary (1 JSON retry), no fallback attempt
    assert [m for m, _ in calls] == [llm.MODEL, llm.MODEL]
