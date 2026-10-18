import asyncio
import os

import pytest
from pydantic import BaseModel

from meetings.config import ConfigError, Settings, load_settings
from meetings.gemini_client import (
    AuthError,
    GeminiClient,
    MalformedOutputError,
    ModelError,
    QuotaError,
    classify_error,
    extract_json,
    retry_delay_seconds,
)


class Out(BaseModel):
    greeting: str


class FakeAPIError(Exception):
    def __init__(self, code, msg="boom"):
        super().__init__(msg)
        self.code = code


def make_client(replies):
    async def no_sleep(_):
        return None

    c = GeminiClient(Settings(api_key="secret-key", model="m", max_attempts=3), sleep=no_sleep)
    queue = list(replies)

    async def fake_call(prompt, schema, system, stage="", attempt=1):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"prompt_tokens": 1, "output_tokens": 2}

    c._call = fake_call
    c.prompts = []
    return c


def gen(c):
    return asyncio.run(c.generate("p", Out, stage="t"))


def test_extract_json_strips_fences_and_chatter():
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Sure! {"a": {"b": 2}} done') == '{"a": {"b": 2}}'
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_malformed_output_is_retried_then_succeeds():
    c = make_client(["not json", '{"wrong": 1}', '{"greeting": "hi"}'])
    assert gen(c).greeting == "hi" and len(c.usage) == 1


def test_malformed_output_gives_up_after_bounded_attempts():
    with pytest.raises(MalformedOutputError):
        gen(make_client(["x", "y", "z"]))


def test_transient_error_retried():
    assert gen(make_client([FakeAPIError(503), '{"greeting": "ok"}'])).greeting == "ok"


def test_quota_exhaustion_reports_quota_error():
    with pytest.raises(QuotaError):
        gen(make_client([FakeAPIError(429)] * 8))


def test_auth_and_model_errors_are_fatal_and_do_not_leak_key():
    with pytest.raises(AuthError) as e:
        gen(make_client([FakeAPIError(403, "bad secret-key")]))
    assert "secret-key" not in str(e.value)
    with pytest.raises(ModelError):
        gen(make_client([FakeAPIError(404, "model is not found")]))


def test_classify_error():
    assert classify_error(FakeAPIError(500)) == ("transient", True)
    assert classify_error(FakeAPIError(400, "bad")) == ("bad_request", False)
    assert classify_error(TimeoutError())[0] == "transient"


def test_missing_key_fails_early(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        load_settings()


def test_model_prefix_is_normalised_and_key_is_not_in_repr(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("GEMINI_MODEL", "google/gemma-x")
    monkeypatch.chdir(tmp_path)
    s = load_settings()
    assert s.model == "gemma-x" and "abc" not in repr(s)


@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="opt-in live smoke test: set RUN_LIVE=1")
def test_live_structured_call():
    s = load_settings()
    c = GeminiClient(s)
    out = asyncio.run(c.generate("Return a short greeting.", Out, stage="live"))
    assert out.greeting


def test_quota_is_waited_out_then_succeeds_and_emits_events():
    c = make_client([FakeAPIError(429, "Please retry in 34.5s"), '{"greeting": "ok"}'])
    seen = []
    c.observer = seen.append
    assert gen(c).greeting == "ok"
    assert any(e.kind == "retry" and "429" in e.info for e in seen)
    assert seen[-1].kind == "done"


def test_retry_delay_parsing():
    assert retry_delay_seconds("Please retry in 34.5s.") == 34.5
    assert retry_delay_seconds("{'retryDelay': '12s'}") == 12.0
    assert retry_delay_seconds("nothing") is None
