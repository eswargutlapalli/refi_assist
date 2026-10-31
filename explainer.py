"""explainer.py — model narrative over the code-written verdict (decision 16).

Why this module exists: the engine compares, code writes the verdict, and
only then may the model speak — narrating fixed numbers in plain language.
Every draft goes through verify_narrative before the user can see it: one
rewrite with the bad numbers named, then the code-written template. The
returned status always says which of the three the user is seeing (rule 3.4).

No math lives here. Figures are copied from the engine result into the
prompt; allowing a value means finding it in that result, never recomputing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine import Comparison, Verdict, WaitComparison
from llm import EXPLANATION_EFFORT, LlmError, complete
from verify import (
    _money,
    build_template,
    rewrite_feedback,
    split_rows,
    verify_narrative,
)

EXPLAINER_PROMPT_CACHE_KEY = "refi-explainer-v1"  # Own key: stable per slice.

STATUS_VERIFIED = "Verified model narrative — every number checked."
STATUS_REWRITTEN = "Rewritten once after a failed check — every number checked."
STATUS_TEMPLATE = "Code-written template — the model narrative did not pass verification."
REASON_FAILED_CHECKS = "failed_checks"
REASON_MODEL_UNAVAILABLE = "model_unavailable"
REASON_LIMIT_REACHED = "limit_reached"
# Model call itself failed (not a bad draft): same template category as
# STATUS_TEMPLATE for eval counts — both start with "Code-written" — but
# honest about the cause. NOTE: AGENTS.md rule 3.4 lists exactly three
# on-screen states; carrying this fourth needs a rule update there.
STATUS_UNAVAILABLE = "Code-written summary — the model explanation wasn't available."
# The limit path reuses STATUS_UNAVAILABLE with the app's limit message.


@dataclass
class ExplainResult:
    """One explained verdict: the text to show plus which of the three it is.

    kind drives eval counts ("verified" | "rewritten" | "template"); reason
    says why a template was used (one of the REASON_* values,
    None otherwise). status is the display text chosen from kind + reason.
    """

    text: str
    status: str  # display text from display_status(kind, reason)
    attempts: int  # model drafts spent: 1, or 2 when a rewrite ran
    kind: str = "verified"  # "verified" | "rewritten" | "template"
    reason: str | None = None  # template only, one of the *_REASON values below


def display_status(kind: str, reason: str | None) -> str:
    """On-screen text for a kind + reason. Template wordings name the reason;
    eval counts the kind, never the string."""
    if kind == "verified":
        return STATUS_VERIFIED
    if kind == "rewritten":
        return STATUS_REWRITTEN
    if kind == "template" and reason == REASON_FAILED_CHECKS:
        return STATUS_TEMPLATE
    if kind == "template" and reason == REASON_MODEL_UNAVAILABLE:
        return STATUS_UNAVAILABLE
    raise ValueError(f"unknown explainer kind/reason: {kind!r}/{reason!r}")


def build_explainer_messages(
    result: Comparison,
    decision: Verdict,
    rates_pct: tuple[float, ...] = (),
    wait: WaitComparison | None = None,
) -> list[dict[str, Any]]:
    """Prompt for one verdict narration. The model gets the headline to quote
    and every figure it may cite — it already holds all allowed values, so
    listing them leaks nothing and leaves invention with no excuse."""
    # Directional, labeled figures only — the shared split_rows wording,
    # never unsigned effects the model could misread the sign of.
    figures = list(split_rows(result))
    if result.total_savings > 0:
        figures.append(
            f"Total difference: refinancing saves {_money(result.total_savings)} in total.")
    elif result.total_savings < 0:
        figures.append(
            f"Total difference: keeping your loan costs {_money(result.total_savings)} less in total.")
    else:
        figures.append("Total difference: both options cost the same in total.")
    if result.monthly_change < 0:
        figures.append(
            f"Payment difference: refinancing lowers your payment by {_money(result.monthly_change)} a month.")
    elif result.monthly_change > 0:
        figures.append(
            f"Payment difference: your current payment is {_money(result.monthly_change)} a month lower.")
    else:
        figures.append("Payment difference: the monthly payment is the same.")
    figures.append(
        f"Payoff: your current loan ends in {result.months_to_payoff_keep} months; "
        f"refinancing ends in {result.months_to_payoff_refi} months.")
    if result.breakeven_month is not None:
        figures.append(f"Breakeven: month {result.breakeven_month}.")
    else:
        figures.append("Breakeven: refinancing never stays ahead within the horizon.")
    for rate in rates_pct:
        figures.append(f"Rate you may cite: {rate}%.")
    if wait is not None:
        figures.append(
            f"Wait scenario: wait {wait.plan.wait_months} months, then "
            f"{_money(wait.plan.monthly)} a month, "
            f"{_money(wait.plan.total)} in total."
        )
    return [
        {"role": "system", "content": (
            "Explain a loan-comparison verdict in plain language in 3-5 "
            "sentences, starting with the headline below word for word. "
            "Explain but never change, soften, or contradict the verdict; "
            "use ONLY the figures listed below — every amount as $X.XX, "
            "every month count as digits, no other numbers in any form, no "
            "years, no spelled-out amounts; never invent a figure."
        )},
        {"role": "user", "content": (
            f"Verdict headline: {decision.headline}\n"
            f"Tradeoff note: {decision.tradeoff_note}\n"
            "Figures you may cite:\n" + "\n".join(f"- {line}" for line in figures)
        )},
    ]


def draft_narrative(
    messages: list[dict[str, Any]], *, client: Any = None
) -> str:
    """One narration draft. Narratives earn reasoning (medium); extraction
    stays minimal — effort is set per slice, never global."""
    return complete(
        messages,
        effort=EXPLANATION_EFFORT,
        prompt_cache_key=EXPLAINER_PROMPT_CACHE_KEY,
        client=client,
    ).text


def explain_verdict(
    result: Comparison,
    decision: Verdict,
    rates_pct: tuple[float, ...] = (),
    wait: WaitComparison | None = None,
    client: Any = None,
) -> ExplainResult:
    """Draft, verify, once rewrite with the bad numbers named, else template.

    At most two model calls: the draft and at most one rewrite. Anything
    still failing falls back to the code-written template, which passes by
    construction — the user never sees an unverified number.
    """
    def done(text: str, kind: str, attempts: int,
             reason: str | None = None) -> ExplainResult:
        return ExplainResult(text, display_status(kind, reason), attempts,
                             kind, reason)

    messages = build_explainer_messages(result, decision, rates_pct, wait)
    try:
        draft = draft_narrative(messages, client=client)
    except LlmError:
        # No draft at all: fail loudly as the template, honestly labeled.
        return done(build_template(result, decision), "template", 0,
                    REASON_MODEL_UNAVAILABLE)
    report = verify_narrative(draft, result, decision, rates_pct, wait)
    if report.ok:
        return done(draft, "verified", 1)
    retry = messages + [
        {"role": "assistant", "content": draft},
        {"role": "user", "content": (
            "Rewrite the explanation fixing this: " + rewrite_feedback(report)
        )},
    ]
    try:
        second = draft_narrative(retry, client=client)
    except LlmError:
        return done(build_template(result, decision), "template", 1,
                    REASON_MODEL_UNAVAILABLE)
    if verify_narrative(second, result, decision, rates_pct, wait).ok:
        return done(second, "rewritten", 2)
    return done(build_template(result, decision), "template", 2,
                REASON_FAILED_CHECKS)
