"""Suite for llm.py. Mocked only — no network, no spend, no key material.

Run with `python3 -m pytest tests/test_llm.py -v`.
"""

import json
import types

import pytest

import llm
from llm import (
    DEFAULT_MODEL,
    DEFAULT_PROMPT_CACHE_KEY,
    LlmAuthError,
    LlmBadRequestError,
    LlmError,
    LlmRateLimitError,
    LlmTransientError,
    StrictModel,
)

SENTINEL_KEY = "test-key-sentinel"
MSGS = [{"role": "user", "content": "Say ok."}]


def _http_error(cls, status, message="boom"):
    # The SDK only reads status_code / headers / request off the response.
    request = types.SimpleNamespace()
    response = types.SimpleNamespace(
        status_code=status, headers={}, request=request
    )
    return cls(message, response=response, body=None)


class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.type = "function"
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeUsage:
    def __init__(self, prompt=0, completion=0, cached=0, reasoning=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = types.SimpleNamespace(cached_tokens=cached)
        self.completion_tokens_details = types.SimpleNamespace(
            reasoning_tokens=reasoning
        )


class _FakeResponse:
    def __init__(self, message, usage=None, model=DEFAULT_MODEL):
        self.choices = [types.SimpleNamespace(message=message)]
        self.usage = usage or _FakeUsage()
        self.model = model


class _FakeCompletions:
    """Replays a script of responses/errors; records every create() call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("more API calls than scripted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, script):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(script))

    @property
    def calls(self):
        return self.chat.completions.calls


def _ok(text="ok", **usage_kw):
    return _FakeResponse(_FakeMessage(text), usage=_FakeUsage(**usage_kw))


def _tool_call_response(call_id="call_1", name="get_loan", arguments=None):
    arguments = arguments if arguments is not None else json.dumps({"x": 1})
    tc = _FakeToolCall(call_id, name, arguments)
    return _FakeResponse(_FakeMessage(None, tool_calls=[tc]))


def test_missing_key_raises_before_any_network(monkeypatch):
    # No client passed and no key set: must fail without touching the network.
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(LlmAuthError):
        llm.complete(MSGS)
    with pytest.raises(LlmAuthError):
        llm.get_meta_client()


def test_api_key_passed_explicitly(monkeypatch):
    # The SDK does not read MODEL_API_KEY on its own, so llm.py passes it.
    monkeypatch.setenv("MODEL_API_KEY", SENTINEL_KEY)
    captured = {}

    class _Recorder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "OpenAI", _Recorder)
    llm.get_meta_client()
    assert captured.get("api_key") == SENTINEL_KEY
    assert captured.get("base_url") == llm.META_BASE_URL


def test_defaults_forwarded():
    fake = _FakeClient([_ok()])
    llm.complete(list(MSGS), client=fake)
    kwargs = fake.calls[0]
    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["reasoning_effort"] == "minimal"
    assert kwargs["extra_body"] == {"prompt_cache_key": DEFAULT_PROMPT_CACHE_KEY}
    assert kwargs["messages"] == MSGS


def test_complete_rejects_non_auto_tool_choice():
    fake = _FakeClient([_ok()])
    with pytest.raises(ValueError, match="auto"):
        llm.complete(
            list(MSGS), client=fake,
            tools=[{"type": "function"}], tool_choice="required",
        )
    assert fake.calls == []


def test_complete_rejects_none_effort():
    # "none" is unsupported by the API (HTTP 400): fail before the network.
    fake = _FakeClient([_ok()])
    with pytest.raises(ValueError, match="effort"):
        llm.complete(list(MSGS), client=fake, effort="none")
    assert fake.calls == []


def test_complete_rejects_unknown_effort():
    fake = _FakeClient([_ok()])
    with pytest.raises(ValueError, match="effort"):
        llm.complete(list(MSGS), client=fake, effort="turbo")
    assert fake.calls == []


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high"])
def test_complete_accepts_known_efforts(effort):
    fake = _FakeClient([_ok()])
    llm.complete(list(MSGS), client=fake, effort=effort)
    assert fake.calls[0]["reasoning_effort"] == effort


def test_key_never_enters_request_payload(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", SENTINEL_KEY)
    fake = _FakeClient([_ok()])
    llm.complete(list(MSGS), client=fake)
    for call in fake.calls:
        assert SENTINEL_KEY not in json.dumps(call, default=str)


def test_empty_messages_rejected_before_network():
    fake = _FakeClient([_ok()])
    with pytest.raises(ValueError):
        llm.complete([], client=fake)
    assert fake.calls == []


def test_bad_request_never_retried():
    import openai

    fake = _FakeClient([_http_error(openai.BadRequestError, 400)])
    with pytest.raises(LlmBadRequestError):
        llm.complete(list(MSGS), client=fake)
    assert len(fake.calls) == 1


def test_auth_failure_maps_without_retry():
    import openai

    fake = _FakeClient([_http_error(openai.AuthenticationError, 401)])
    with pytest.raises(LlmAuthError):
        llm.complete(list(MSGS), client=fake)
    assert len(fake.calls) == 1


def test_rate_limit_retries_then_succeeds(monkeypatch):
    import openai

    sleeps = []
    monkeypatch.setattr(llm, "_sleep", sleeps.append)
    fake = _FakeClient([_http_error(openai.RateLimitError, 429), _ok("recovered")])
    response = llm.complete(list(MSGS), client=fake)
    assert response.text == "recovered"
    assert len(fake.calls) == 2
    assert len(sleeps) == 1


def test_rate_limit_exhaustion_raises(monkeypatch):
    import openai

    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    script = [_http_error(openai.RateLimitError, 429)] * 4
    fake = _FakeClient(script)
    with pytest.raises(LlmRateLimitError):
        llm.complete(list(MSGS), client=fake, max_retries=2)
    assert len(fake.calls) == 3  # first try plus two retries


def test_meta_client_owns_retry_policy(monkeypatch):
    # SDK retries stay OFF: retries live only in complete(). Timeout is 60s.
    monkeypatch.setenv("MODEL_API_KEY", SENTINEL_KEY)
    captured = {}

    class _Recorder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "OpenAI", _Recorder)
    llm.get_meta_client()
    assert captured.get("timeout") == 60.0
    assert captured.get("max_retries") == 0


def _timeout_error():
    import openai

    return openai.APITimeoutError(types.SimpleNamespace())


def test_timeout_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    fake = _FakeClient([_timeout_error(), _ok("recovered")])
    response = llm.complete(list(MSGS), client=fake)
    assert response.text == "recovered"
    assert len(fake.calls) == 2


def test_timeout_exhaustion_is_transient(monkeypatch):
    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    fake = _FakeClient([_timeout_error(), _timeout_error(), _timeout_error()])
    with pytest.raises(LlmTransientError):
        llm.complete(list(MSGS), client=fake, max_retries=2)
    assert len(fake.calls) == 3


def test_usage_parsing_tracks_cached_tokens():
    fake = _FakeClient(
        [_ok("hi", prompt=100, completion=20, cached=30, reasoning=5)]
    )
    response = llm.complete(list(MSGS), client=fake)
    assert response.usage.prompt_tokens == 100
    assert response.usage.completion_tokens == 20
    assert response.usage.cached_tokens == 30
    assert response.usage.reasoning_tokens == 5
    logged = llm.format_usage(response.usage)
    assert "30" in logged and SENTINEL_KEY not in logged


def test_tool_loop_appends_assistant_before_result():
    seen = []
    tools = [
        {
            "type": "function",
            "function": {"name": "get_loan", "parameters": {"type": "object"}},
        }
    ]

    def runner(name, args):
        seen.append((name, args))
        return "tool says hi"

    fake = _FakeClient([_tool_call_response(), _ok("done")])
    response = llm.complete_with_tools(list(MSGS), tools, runner, client=fake)
    assert response.text == "done"
    assert seen == [("get_loan", {"x": 1})]
    second_messages = fake.calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert second_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "tool says hi",
    }


def test_tool_choice_other_than_auto_rejected():
    fake = _FakeClient([_ok()])
    with pytest.raises(ValueError):
        llm.complete_with_tools(
            list(MSGS), [{"type": "function"}], lambda n, a: "",
            client=fake, tool_choice="required",
        )
    assert fake.calls == []


def test_tool_loop_max_turns_cap(monkeypatch):
    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    tools = [{"type": "function", "function": {"name": "get_loan"}}]
    fake = _FakeClient([_tool_call_response()] * 3)
    with pytest.raises(LlmError):
        llm.complete_with_tools(
            list(MSGS), tools, lambda n, a: "again",
            client=fake, max_turns=2,
        )
    assert len(fake.calls) == 2


def test_tool_loop_returns_bad_json_args_to_model():
    seen = []
    tools = [{"type": "function", "function": {"name": "get_loan"}}]
    bad = _tool_call_response(arguments="{not json")
    fake = _FakeClient([bad, _ok("done")])

    def runner(name, args):
        seen.append((name, args))
        return "tool says hi"

    response = llm.complete_with_tools(list(MSGS), tools, runner, client=fake)
    assert response.text == "done"
    assert seen == []  # runner never ran on unparseable arguments
    error_result = fake.calls[1]["messages"][-1]
    assert error_result["role"] == "tool"
    assert error_result["tool_call_id"] == "call_1"
    assert "get_loan" in error_result["content"]
    assert "Error" in error_result["content"]


def test_tool_loop_returns_non_object_args_to_model():
    seen = []
    tools = [{"type": "function", "function": {"name": "get_loan"}}]
    bad = _tool_call_response(arguments="[1, 2]")
    fake = _FakeClient([bad, _ok("done")])
    response = llm.complete_with_tools(
        list(MSGS), tools, lambda n, a: seen.append((n, a)) or "x",
        client=fake,
    )
    assert response.text == "done"
    assert seen == []
    error_result = fake.calls[1]["messages"][-1]
    assert error_result["tool_call_id"] == "call_1"
    assert "Error" in error_result["content"]


def test_tool_loop_recovers_after_arg_error():
    # Bad args go back as an error result; the model retries with good args.
    seen = []
    tools = [{"type": "function", "function": {"name": "get_loan"}}]
    bad = _tool_call_response(call_id="call_1", arguments="nope")
    good = _tool_call_response(call_id="call_2", arguments='{"x": 2}')
    fake = _FakeClient([bad, good, _ok("recovered")])

    def runner(name, args):
        seen.append((name, args))
        return "tool says hi"

    response = llm.complete_with_tools(list(MSGS), tools, runner, client=fake)
    assert response.text == "recovered"
    assert seen == [("get_loan", {"x": 2})]
    assert len(fake.calls) == 3


def test_tool_loop_mixed_good_and_bad_args_same_turn():
    # One turn, two calls: error result for the bad one, real run for the good one.
    seen = []
    tools = [{"type": "function", "function": {"name": "get_loan"}}]
    first = _FakeResponse(
        _FakeMessage(
            None,
            tool_calls=[
                _FakeToolCall("call_1", "get_loan", "{broken"),
                _FakeToolCall("call_2", "get_loan", '{"x": 3}'),
            ],
        )
    )
    fake = _FakeClient([first, _ok("done")])

    def runner(name, args):
        seen.append((name, args))
        return "tool says hi"

    response = llm.complete_with_tools(list(MSGS), tools, runner, client=fake)
    assert response.text == "done"
    assert seen == [("get_loan", {"x": 3})]
    results = fake.calls[1]["messages"][-2:]
    assert [m["tool_call_id"] for m in results] == ["call_1", "call_2"]
    assert "Error" in results[0]["content"]
    assert results[1]["content"] == "tool says hi"


def test_tool_loop_max_turns_cap_counts_arg_errors(monkeypatch):
    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    tools = [{"type": "function", "function": {"name": "get_loan"}}]
    bad = _tool_call_response(arguments="{broken")
    fake = _FakeClient([bad] * 3)
    with pytest.raises(LlmError):
        llm.complete_with_tools(
            list(MSGS), tools, lambda n, a: "never",
            client=fake, max_turns=2,
        )
    assert len(fake.calls) == 2


def test_stage_stubs_raise_not_implemented():
    with pytest.raises(NotImplementedError):
        llm.baseten_judge("anything")
    with pytest.raises(NotImplementedError):
        llm.modal_run_suite("anything")
    with pytest.raises(NotImplementedError):
        llm.fireworks_finetune_job("anything")


def test_caller_effort_reaches_the_api():
    # Extraction/orchestration default to minimal; the explainer passes EXPLANATION_EFFORT.
    fake = _FakeClient([_ok(), _ok()])
    llm.complete(list(MSGS), client=fake)
    assert fake.calls[0]["reasoning_effort"] == "minimal"
    llm.complete(list(MSGS), client=fake, effort=llm.EXPLANATION_EFFORT)
    assert fake.calls[1]["reasoning_effort"] == llm.EXPLANATION_EFFORT
    assert llm.EXPLANATION_EFFORT != "minimal"


class _Payout(StrictModel):
    total: float | None
    months: int | None


def test_complete_schema_validates_typed_reply():
    fake = _FakeClient([_ok('{"total": 42.5, "months": 36}')])
    payout, response = llm.complete_schema(list(MSGS), _Payout, client=fake)
    assert isinstance(payout, _Payout)
    assert (payout.total, payout.months) == (42.5, 36)
    sent = fake.calls[0]["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["name"] == "_Payout"
    assert sent["json_schema"]["strict"] is True
    assert sent["json_schema"]["schema"] == _Payout.model_json_schema()
    assert response.text == '{"total": 42.5, "months": 36}'


def test_complete_schema_rejects_wrong_type():
    fake = _FakeClient([_ok('{"total": "lots", "months": 36}')])
    with pytest.raises(LlmError, match="_Payout"):
        llm.complete_schema(list(MSGS), _Payout, client=fake)


def test_complete_schema_rejects_extra_field():
    fake = _FakeClient([_ok('{"total": 1.0, "months": 36, "surprise": 2}')])
    with pytest.raises(LlmError, match="_Payout"):
        llm.complete_schema(list(MSGS), _Payout, client=fake)


def test_complete_schema_rejects_missing_field():
    fake = _FakeClient([_ok('{"total": 1.0}')])
    with pytest.raises(LlmError, match="_Payout"):
        llm.complete_schema(list(MSGS), _Payout, client=fake)


def test_complete_schema_error_hides_model_output():
    # Pydantic's message carries the model's output in `input`; the LlmError
    # must name schema, field path, and error type only.
    marker = "QUACK_ZIGZAG_123"
    fake = _FakeClient([_ok('{"total": "' + marker + '", "months": 36}')])
    with pytest.raises(LlmError) as excinfo:
        llm.complete_schema(list(MSGS), _Payout, client=fake)
    text = str(excinfo.value)
    assert marker not in text
    assert "_Payout" in text
    assert "total" in text
    assert "float_parsing" in text


def test_complete_schema_rejects_invalid_json():
    fake = _FakeClient([_ok("not json")])
    with pytest.raises(LlmError):
        llm.complete_schema(list(MSGS), _Payout, client=fake)


def test_complete_schema_requires_strict_model():
    from pydantic import BaseModel

    class _Loose(BaseModel):
        total: float | None

    fake = _FakeClient([_ok('{"total": 1.0}')])
    with pytest.raises(ValueError):
        llm.complete_schema(list(MSGS), _Loose, client=fake)
    assert fake.calls == []


def test_strict_model_rejects_extra_properties():
    from pydantic import ValidationError

    class _M(StrictModel):
        total: float | None

    with pytest.raises(ValidationError):
        _M.model_validate({"total": 1.0, "surprise": 2})


def test_success_log_has_model_usage_timing_retries(caplog):
    import logging

    fake = _FakeClient(
        [_ok("hi", prompt=100, completion=20, cached=30, reasoning=5)]
    )
    with caplog.at_level("INFO", logger="llm"):
        llm.complete(list(MSGS), client=fake)
    lines = [
        r.getMessage() for r in caplog.records
        if r.name == "llm" and "llm call ok" in r.getMessage()
    ]
    assert len(lines) == 1
    assert DEFAULT_MODEL in lines[0]
    assert "prompt=100" in lines[0] and "cached=30" in lines[0]
    assert "elapsed=" in lines[0] and "retries=0" in lines[0]


def test_retry_logs_attempt_and_wait(monkeypatch, caplog):
    import logging

    import openai

    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    fake = _FakeClient([_http_error(openai.RateLimitError, 429), _ok()])
    with caplog.at_level("INFO", logger="llm"):
        llm.complete(list(MSGS), client=fake)
    retries = [
        r.getMessage() for r in caplog.records if "llm retry" in r.getMessage()
    ]
    assert len(retries) == 1
    assert "attempt=1" in retries[0] and "wait=" in retries[0]


def test_failure_log_has_class_and_status(monkeypatch, caplog):
    import logging

    import openai

    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    fake = _FakeClient([_http_error(openai.BadRequestError, 400)])
    with caplog.at_level("INFO", logger="llm"):
        with pytest.raises(LlmBadRequestError):
            llm.complete(list(MSGS), client=fake)
    fails = [
        r.getMessage() for r in caplog.records
        if "llm call failed" in r.getMessage()
    ]
    assert len(fails) == 1
    assert "LlmBadRequestError" in fails[0] and "400" in fails[0]


def test_logs_and_errors_never_carry_content(monkeypatch, caplog):
    import logging

    import openai

    marker = "QUACK_ZIGZAG_123"
    monkeypatch.setattr(llm, "_sleep", lambda _: None)
    msgs = [{"role": "user", "content": f"say {marker}"}]
    failures = [
        # (script, kwargs, expected error): SDK text carries the marker each time.
        (
            [_http_error(openai.BadRequestError, 400, f"bad {marker}")],
            {},
            LlmBadRequestError,
        ),
        (
            [_http_error(openai.RateLimitError, 429, f"limited {marker}")] * 2,
            {"max_retries": 1},
            LlmRateLimitError,
        ),
        (
            [_http_error(openai.APIStatusError, 500, f"broken {marker}")] * 2,
            {"max_retries": 1},
            LlmTransientError,
        ),
    ]
    with caplog.at_level("INFO", logger="llm"):
        llm.complete(list(msgs), client=_FakeClient([_ok(f"reply {marker}")]))
        for script, kwargs, error in failures:
            with pytest.raises(error) as excinfo:
                llm.complete(list(msgs), client=_FakeClient(script), **kwargs)
            assert marker not in str(excinfo.value)
    assert caplog.records, "expected log lines"
    for record in caplog.records:
        assert marker not in record.getMessage()
