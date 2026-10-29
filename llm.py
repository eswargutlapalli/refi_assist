"""llm.py — the single provider module for ALL model inference.

Why this file exists: every number the user sees is computed by engine.py;
the model only reads messy input, calls tools, and explains. This module is
the only place that talks to a model provider, so retries, caching, usage
logging, and the tool-loop guardrails live here once instead of scattering
across callers.

Stage order (AGENTS.md section 8): the Meta Model API path is live now.
Baseten (claim judge), Modal (batch eval), and Fireworks (fine-tune) are
typed stubs until their stages — calling one raises NotImplementedError
loudly instead of pretending to work.

Key rules honored here: the api_key is passed explicitly (the SDK does not
read MODEL_API_KEY on its own); HTTP 400 is never retried; 429 backs off
with jitter; every call returns its full usage dump including cached tokens;
tool_choice supports only "auto"; and the full assistant message is appended
before each tool result, or the API answers 400.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import openai
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

META_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"  # Standard mode only; never a -contributor ID.
DEFAULT_EFFORT = "minimal"  # Extraction and orchestration stay cheap.
EXPLANATION_EFFORT = "medium"  # Narratives earn reasoning: pass as effort= for the explainer. Raise to "high" if narratives read thin.
DEFAULT_PROMPT_CACHE_KEY = "refi-assistant-v1"  # Stable key: same value, same prefix, real cache hits.
BASETEN_JUDGE_MODEL = "meta-models/muse-spark-open-1026"

MAX_429_RETRIES = 3
MAX_TOOL_TURNS = 8
CLIENT_TIMEOUT_SECONDS = 60.0
ALLOWED_EFFORTS = ("minimal", "low", "medium", "high")
_RETRY_BASE_SECONDS = 1.0

_sleep = time.sleep  # Module alias so tests can patch backoff without touching time.

logger = logging.getLogger(__name__)  # No basicConfig here: the host app owns handler config.


class LlmError(Exception):
    """Base for everything this module raises after local validation."""


class LlmAuthError(LlmError):
    """Missing key or rejected credentials. Never retried."""


class LlmBadRequestError(LlmError):
    """The API refused the request shape (HTTP 400). A caller bug: never retried."""


class LlmRateLimitError(LlmError):
    """Still rate-limited after the retry budget ran out."""


class LlmTransientError(LlmError):
    """5xx, timeout, or connection failure after retries."""


class StrictModel(BaseModel):
    """Base for every model-output schema: no extra properties, ever.

    Subclasses declare each field required-but-nullable (e.g. `total:
    float | None`) so a missing field fails loudly instead of silently
    defaulting.
    """

    model_config = ConfigDict(extra="forbid")


@dataclass
class LlmUsage:
    """Token counts for one call. Cached tokens stay separate so prompt-cache hits are visible."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass
class LlmResponse:
    """One finished turn: the text plus its usage dump. `raw` is the SDK's
    assistant message, kept so the tool loop can read tool_calls."""

    text: str
    usage: LlmUsage = field(default_factory=LlmUsage)
    model: str = DEFAULT_MODEL
    raw: Any = None


def format_usage(usage: LlmUsage) -> str:
    """One-line log summary. Takes only ints, so key material cannot leak through it."""
    return (
        f"prompt={usage.prompt_tokens} completion={usage.completion_tokens} "
        f"reasoning={usage.reasoning_tokens} cached={usage.cached_tokens}"
    )


def _field(raw: Any, name: str) -> Any:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _usage_from(raw: Any) -> LlmUsage:
    # The SDK nests cache/reasoning counts inside *_details objects; accept
    # top-level fields too so fakes and future shapes keep working.
    prompt_details = _field(raw, "prompt_tokens_details")
    completion_details = _field(raw, "completion_tokens_details")
    cached = _as_int(_field(raw, "cached_tokens")) or _as_int(
        _field(prompt_details, "cached_tokens")
    )
    reasoning = _as_int(_field(raw, "reasoning_tokens")) or _as_int(
        _field(completion_details, "reasoning_tokens")
    )
    return LlmUsage(
        prompt_tokens=_as_int(_field(raw, "prompt_tokens")),
        completion_tokens=_as_int(_field(raw, "completion_tokens")),
        reasoning_tokens=reasoning,
        cached_tokens=cached,
    )


def _meta_api_key() -> str:
    # Read at call time, never cached at import: rotation and test patching work.
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise LlmAuthError("MODEL_API_KEY is not set; export it before calling the Meta Model API.")
    return key


def get_meta_client() -> OpenAI:
    """Build a Meta Model API client. The key passes explicitly because the SDK won't read MODEL_API_KEY itself."""
    return OpenAI(
        base_url=META_BASE_URL,
        api_key=_meta_api_key(),
        timeout=CLIENT_TIMEOUT_SECONDS,
        # The SDK retries 429/5xx on its own by default; ours stay off so the
        # one retry policy in complete() is the only one spending the budget.
        max_retries=0,
    )


def _check_messages(messages: Any) -> None:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list.")
    for i, message in enumerate(messages):
        if not _field(message, "role"):
            raise ValueError(f"messages[{i}] needs a role.")
        if _field(message, "content") is None and _field(message, "tool_calls") is None:
            raise ValueError(f"messages[{i}] needs content (or tool_calls).")


def _public_message(name: str, exc: Exception, detail: str) -> str:
    # Same rule as _log_failure: class name and HTTP status only, because SDK
    # text can echo request details or model output. "from exc" at each raise
    # keeps the original attached for local debugging.
    status = getattr(exc, "status_code", None)
    suffix = f" (HTTP {status})" if status is not None else ""
    return f"{name}{suffix}: {detail}"


def _log_failure(name: str, exc: Exception, total: int) -> None:
    # Error class, HTTP status, and attempt count only: never the exception
    # text, which can echo request details or model output.
    line = f"llm call failed error={name} attempts={total}"
    status = getattr(exc, "status_code", None)
    if status is not None:
        line += f" status={status}"
    logger.error(line)


def _is_retryable(exc: Exception) -> bool:
    # 400/auth shapes are caller bugs: retrying them burns budget for nothing.
    if isinstance(exc, (openai.BadRequestError, openai.AuthenticationError)):
        return False
    if isinstance(exc, openai.RateLimitError):
        return True
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", 0) or 0
        return 500 <= status < 600
    return False


def complete(
    messages: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    prompt_cache_key: str = DEFAULT_PROMPT_CACHE_KEY,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    client: Any = None,
    max_retries: int = MAX_429_RETRIES,
) -> LlmResponse:
    """One chat turn against the Meta Model API.

    prompt_cache_key rides in extra_body (the SDK's escape hatch for
    provider-specific params) so the stable prefix stays cacheable without
    fighting the shared schema. Retries only 429/5xx/timeout with jittered
    backoff; 400 and auth errors raise immediately.
    """
    _check_messages(messages)
    # Both guards run before any client is built: caller bugs fail locally,
    # never as billable 400s. "none" effort is unsupported by the API.
    if tool_choice is not None and tool_choice != "auto":
        raise ValueError('tool_choice supports only "auto" on Chat Completions.')
    if effort not in ALLOWED_EFFORTS:
        raise ValueError(
            f"effort must be one of {list(ALLOWED_EFFORTS)}; got {effort!r}."
        )
    if client is None:
        client = get_meta_client()
    attempts = 0
    start = time.monotonic()
    while True:
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "reasoning_effort": effort,
            "extra_body": {"prompt_cache_key": prompt_cache_key},
        }
        if response_format is not None:
            create_kwargs["response_format"] = response_format
        if tools is not None:
            create_kwargs["tools"] = tools
        if tool_choice is not None:
            create_kwargs["tool_choice"] = tool_choice
        try:
            response = client.chat.completions.create(**create_kwargs)
        except openai.BadRequestError as exc:
            _log_failure("LlmBadRequestError", exc, attempts + 1)
            raise LlmBadRequestError(
                _public_message(
                    "LlmBadRequestError", exc, "request rejected, not retried"
                )
            ) from exc
        except openai.AuthenticationError as exc:
            _log_failure("LlmAuthError", exc, attempts + 1)
            raise LlmAuthError(
                _public_message("LlmAuthError", exc, "authentication failed")
            ) from exc
        except Exception as exc:
            if _is_retryable(exc) and attempts < max_retries:
                attempts += 1
                wait = _RETRY_BASE_SECONDS * (2 ** (attempts - 1)) + random.uniform(0, 0.5)
                logger.warning("llm retry attempt=%d wait=%.2fs", attempts, wait)
                _sleep(wait)
                continue
            if isinstance(exc, openai.RateLimitError):
                _log_failure("LlmRateLimitError", exc, attempts + 1)
                raise LlmRateLimitError(
                    _public_message(
                        "LlmRateLimitError",
                        exc,
                        f"still limited after {attempts} retries",
                    )
                ) from exc
            if _is_retryable(exc):
                _log_failure("LlmTransientError", exc, attempts + 1)
                raise LlmTransientError(
                    _public_message(
                        "LlmTransientError",
                        exc,
                        f"call failed after {attempts + 1} attempts",
                    )
                ) from exc
            _log_failure("LlmError", exc, attempts + 1)
            raise LlmError(
                _public_message("LlmError", exc, "call failed")
            ) from exc
        message = response.choices[0].message
        usage = _usage_from(getattr(response, "usage", None))
        effective_model = getattr(response, "model", None) or model
        # One line per call: model, usage (ints only), timing, retry count.
        # Message content and response text never enter a log line.
        logger.info(
            "llm call ok model=%s %s elapsed=%.2fs retries=%d",
            effective_model,
            format_usage(usage),
            time.monotonic() - start,
            attempts,
        )
        return LlmResponse(
            text=message.content or "",
            usage=usage,
            model=effective_model,
            raw=message,
        )


def complete_schema(
    messages: list[dict[str, Any]],
    schema: type[StrictModel],
    **kwargs: Any,
) -> tuple[StrictModel, LlmResponse]:
    """complete() against a StrictModel JSON schema (rule 9: the contract).

    Sends the model's own JSON Schema with strict on, then validates the
    reply with model_validate_json. Keep schemas flat: the API rejects
    recursive schemas with 400. Bad shapes raise LlmError naming the schema,
    field path, and error type only — never the model's output values.
    """
    if not (isinstance(schema, type) and issubclass(schema, StrictModel)):
        raise ValueError("schema must be a StrictModel subclass (strict, no extras).")
    response = complete(
        messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
                "strict": True,
            },
        },
        **kwargs,
    )
    try:
        return schema.model_validate_json(response.text), response
    except ValidationError as exc:
        raise LlmError(_schema_error(schema, exc)) from exc


def _schema_error(schema: type[StrictModel], exc: ValidationError) -> str:
    # Pydantic's messages carry the model's output in `input`; rebuild from
    # path and type only so output values never reach logs or screens.
    parts = []
    for error in exc.errors():
        path = ".".join(str(p) for p in error.get("loc", ())) or "reply"
        parts.append(f"{path}: {error.get('type', 'unknown')}")
    return f"Model reply did not match {schema.__name__}: {'; '.join(parts) or 'invalid reply'}."


ToolRunner = Callable[[str, dict[str, Any]], str]
"""Runs one named tool: returns the result string for the model. Runners must
validate their own arguments and return error strings the model can recover
from — never raise into the loop for a bad argument."""


def _normalize_tool_calls(raw: Any) -> list[tuple[str, str, str]]:
    calls = _field(raw, "tool_calls") or []
    normalized = []
    for call in calls:
        fn = _field(call, "function") or {}
        normalized.append(
            (
                str(_field(call, "id")),
                str(_field(fn, "name")),
                str(_field(fn, "arguments") or "{}"),
            )
        )
    return normalized


def _assistant_echo(raw: Any) -> dict[str, Any]:
    # The FULL assistant message (content plus tool_calls) goes back before
    # any tool result — without it the API answers 400.
    return {
        "role": "assistant",
        "content": _field(raw, "content"),
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
            for call_id, name, arguments in _normalize_tool_calls(raw)
        ],
    }


def complete_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_runner: ToolRunner,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    prompt_cache_key: str = DEFAULT_PROMPT_CACHE_KEY,
    client: Any = None,
    max_retries: int = MAX_429_RETRIES,
    max_turns: int = MAX_TOOL_TURNS,
    tool_choice: str = "auto",
) -> LlmResponse:
    """Run a bounded tool loop. Only "auto" is accepted for tool_choice —
    it is all Chat Completions supports. Raises LlmError if the loop has not
    finished within max_turns instead of spinning forever."""
    if tool_choice != "auto":
        raise ValueError('tool_choice supports only "auto" on Chat Completions.')
    if not tools:
        raise ValueError("tools must be a non-empty list.")
    if not callable(tool_runner):
        raise ValueError("tool_runner must be callable.")
    if client is None:
        client = get_meta_client()
    working = list(messages)
    for _ in range(max_turns):
        response = complete(
            working,
            model=model,
            effort=effort,
            prompt_cache_key=prompt_cache_key,
            tools=tools,
            tool_choice=tool_choice,
            client=client,
            max_retries=max_retries,
        )
        calls = _normalize_tool_calls(response.raw)
        if not calls:
            return response
        working.append(_assistant_echo(response.raw))
        for call_id, name, arguments in calls:
            # Bad arguments go back as an error result the model can recover
            # from — raising here would waste the turns already spent. The
            # max_turns cap above still bounds the loop.
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": (
                            f"Error: arguments for '{name}' were not valid "
                            "JSON. Call it again with a JSON object, or "
                            "answer without tools."
                        ),
                    }
                )
                continue
            if not isinstance(args, dict):
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": (
                            f"Error: arguments for '{name}' must be a JSON "
                            "object. Call it again with a JSON object, or "
                            "answer without tools."
                        ),
                    }
                )
                continue
            result = tool_runner(name, args)
            content = result if isinstance(result, str) else json.dumps(result)
            working.append(
                {"role": "tool", "tool_call_id": call_id, "content": content}
            )
    raise LlmError(f"Tool loop did not finish within {max_turns} turns.")


def baseten_judge(*args: Any, **kwargs: Any) -> LlmResponse:
    """Stage 3: claim judge on Muse Spark Open via Baseten. Not wired yet."""
    raise NotImplementedError(
        "Baseten judge path is not wired yet "
        f"(model would be {BASETEN_JUDGE_MODEL}); see plan Stage 3."
    )


def modal_run_suite(*args: Any, **kwargs: Any) -> Any:
    """Stage 3: batch scenario-suite runs on Modal. Not wired yet."""
    raise NotImplementedError(
        "Modal batch eval is not wired yet; see plan Stage 3."
    )


def fireworks_finetune_job(*args: Any, **kwargs: Any) -> Any:
    """Reserved Fireworks fine-tune path. Last priority — see plan Stage 3."""
    raise NotImplementedError(
        "Fireworks fine-tuning is reserved until everything else is done."
    )
