"""trace.py — page-3 request-trace assembly (decision 27, Step 3.5).

Why this module exists: every run leaves a trace (AGENTS.md §1), and the
UI should show it — which checks ran on this request, what each cost,
and what each saw. Assembly lives here as pure functions so the trail
is testable without Streamlit; app.py only renders what build_trace
returns. Session memory only: entries are never written to disk, and
prompts, outputs, and keys never enter logs (rule 3.11 logs usage
counts only).
"""

from __future__ import annotations

from typing import Any

STEP_ORDER = (
    "extract-loan",
    "extract-offer",
    "grounding",
    "confirm",
    "engine",
    "explainer",
    "number-check",
    "meaning-check",
    "wait",
)

CACHE_LABEL = "from cache, no new calls"
REDACTED = "[REDACTED]"

# Keys never enter trace messages — clients are built far from assembly —
# but a belt-and-braces pass redacts any key-shaped value that ever does,
# so a leak fails closed to a placeholder instead of the log or screen.
_KEY_NAMES = ("MODEL_API_KEY", "BASETEN_API_KEY")


def _redact(text: Any) -> Any:
    import os

    if not isinstance(text, str):
        return text
    for name in _KEY_NAMES:
        secret = os.environ.get(name, "")
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text


def build_trace(entries: list[dict[str, Any]],
                current_key: Any) -> dict[str, Any]:
    """Assemble step records into ordered entries plus request totals.

    Entries priced from older inputs drop: the section never shows stale
    numbers — a new extraction or reconfirmed edit rebuilds downstream.
    current_key is the valid key or the set of them (extraction texts
    plus the confirmed-inputs key live side by side). Cache hits count
    toward the path cost like every shown entry; their label says no new
    calls were spent on them this render.
    """
    valid = ({current_key} if isinstance(current_key, (str, tuple))
             else set(current_key))
    fresh = [dict(entry) for entry in entries
             if entry.get("input_key") is None or entry.get("input_key") in valid]
    ordered = sorted(fresh, key=lambda entry: STEP_ORDER.index(entry["step"]))
    for entry in ordered:
        entry["cache_label"] = (
            CACHE_LABEL if entry.get("cache_hit") else None)
        entry["summary"] = _redact(entry.get("summary"))
        detail = entry.get("detail")
        if isinstance(detail, list):
            entry["detail"] = [_redact(line) for line in detail]
    prompt = sum(_tokens(entry, "prompt") for entry in ordered)
    totals = {
        "calls": sum(1 for entry in ordered if entry.get("model") is not None),
        "prompt": prompt,
        "completion": sum(_tokens(entry, "completion") for entry in ordered),
        "reasoning": sum(_tokens(entry, "reasoning") for entry in ordered),
        "cached": sum(_tokens(entry, "cached") for entry in ordered),
        "cache_ratio": ((sum(_tokens(entry, "cached") for entry in ordered)
                         / prompt) if prompt else None),
        "wall_s": round(sum(float(entry.get("wall_s", 0.0))
                            for entry in ordered), 2),
    }
    return {"entries": ordered, "totals": totals}


def _tokens(entry: dict[str, Any], name: str) -> int:
    try:
        return int((entry.get("tokens") or {}).get(name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def model_entry(step: str, title: str, summary: str,
                usages: list[dict[str, Any]], *,
                effort: str, cache_key: str, input_key: Any,
                detail: Any = None) -> dict[str, Any]:
    """One model step from its usage dumps: tokens and wall time summed
    across calls (initial plus retry), model from the first call."""
    pairs = (("prompt", "prompt_tokens"),
               ("completion", "completion_tokens"),
               ("reasoning", "reasoning_tokens"),
               ("cached", "cached_tokens"))
    tokens = {"prompt": 0, "completion": 0, "reasoning": 0, "cached": 0}
    wall = 0.0
    for usage in usages:
        for short, long in pairs:
            try:
                tokens[short] += int(usage.get(long, 0) or 0)
            except (TypeError, ValueError):
                pass
        try:
            wall += float(usage.get("elapsed_s", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
    return {"step": step, "title": title, "summary": summary,
            "detail": detail,
            "model": usages[0].get("model") if usages else None,
            "effort": effort, "cache_key": cache_key, "tokens": tokens,
            "wall_s": round(wall, 2), "cache_hit": False,
            "input_key": input_key}


def code_entry(step: str, title: str, summary: str, *,
               detail: Any = None, input_key: Any = None) -> dict[str, Any]:
    """One deterministic step: no model, no tokens, still ordered."""
    return {"step": step, "title": title, "summary": summary,
            "detail": detail, "model": None, "effort": None,
            "cache_key": None,
            "tokens": {"prompt": 0, "completion": 0, "reasoning": 0,
                       "cached": 0},
            "wall_s": 0.0, "cache_hit": False, "input_key": input_key}


def margin_line(result: Any, decision: Any, priority: str) -> str:
    """The deciding margin comparison in one line. Reads the verdict's
    own choice and the engine's numbers; no new rule taxonomy — margins
    are the fixed $100 total / $10 monthly from decision 8."""
    if priority == "lowest_monthly_payment":
        apart, margin = abs(result.monthly_change), 10.0
        unit = "a month"
    elif priority == "earliest_payoff":
        apart = abs(result.months_to_payoff_refi
                    - result.months_to_payoff_keep)
        return (f"{apart} months apart, "
                f"same-month ties fall back to total "
                f"-> {decision.choice}")
    else:
        apart, margin = abs(result.total_savings), 100.0
        unit = "in total"
    return (f"${apart:,.2f} apart vs ${margin:,.0f} margin {unit} "
            f"-> {decision.choice}")
