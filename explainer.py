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

import time
from dataclasses import dataclass
from typing import Any

from engine import Comparison, Verdict, WaitComparison
from judge import judge_draft
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
REASON_MEANING_FAILED = "failed_meaning_check"
REASON_JUDGE_DOWN = "judge_unavailable"
STATUS_MEANING = "Code-written template — the model narrative did not pass the meaning check."
STATUS_JUDGE_DOWN = "Code-written template — the independent check was unavailable."
# Model call itself failed (not a bad draft): same template category as
# STATUS_TEMPLATE for eval counts — both start with "Code-written" — but
# honest about the cause. Rule 3.4 covers both wordings: failed checks get
# STATUS_TEMPLATE, an unavailable model gets STATUS_UNAVAILABLE.
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
    if kind == "template" and reason == REASON_MEANING_FAILED:
        return STATUS_MEANING
    if kind == "template" and reason == REASON_JUDGE_DOWN:
        return STATUS_JUDGE_DOWN
    raise ValueError(f"unknown explainer kind/reason: {kind!r}/{reason!r}")


def explainer_figures(
    result: Comparison,
    rates_pct: tuple[float, ...] = (),
    wait: WaitComparison | None = None,
) -> list[str]:
    """The labeled figures the narrator may cite. One source: the prompt
    and the claim judge read the same list, so the judge cannot flag a
    figure the model was told it could use."""
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
    return figures


def build_explainer_messages(
    result: Comparison,
    decision: Verdict,
    rates_pct: tuple[float, ...] = (),
    wait: WaitComparison | None = None,
) -> list[dict[str, Any]]:
    """Prompt for one verdict narration. The model gets the headline to quote
    and every figure it may cite — it already holds all allowed values, so
    listing them leaks nothing and leaves invention with no excuse."""
    figures = explainer_figures(result, rates_pct, wait)
    return [
        {"role": "system", "content": (
            "Explain a loan-comparison verdict in plain language in 3-5 "
            "sentences, starting with the headline below word for word. "
            "Explain but never change, soften, or contradict the verdict; "
            "state the other side the way the tradeoff note does "
            "('but costs $X more in total'); "
            "never use the other option's headline wording; "
            "Don't discuss waiting; the page shows wait scenarios separately. "
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
    messages: list[dict[str, Any]], *, client: Any = None,
    usage_sink: list[dict[str, Any]] | None = None,
) -> str:
    """One narration draft. Narratives earn reasoning (medium); extraction
    stays minimal — effort is set per slice, never global. When usage_sink
    is given, the call's usage dump is appended so offline scoring can
    account every call without a second pass. The dump carries elapsed_s,
    like extraction: wall time is a call-site fact."""
    start = time.monotonic()
    response = complete(
        messages,
        effort=EXPLANATION_EFFORT,
        prompt_cache_key=EXPLAINER_PROMPT_CACHE_KEY,
        client=client,
    )
    if usage_sink is not None:
        usage_sink.append({"model": response.model, **response.usage.as_dict(),
                           "elapsed_s": round(time.monotonic() - start, 2)})
    return response.text


def explain_verdict(
    result: Comparison,
    decision: Verdict,
    rates_pct: tuple[float, ...] = (),
    wait: WaitComparison | None = None,
    client: Any = None,
    on_draft: Any = None,
    judge_client: Any = None,
    judge_usage_sink: list[dict[str, Any]] | None = None,
    judge_verdict_sink: list[dict[str, Any]] | None = None,
) -> ExplainResult:
    """Draft, verify, once rewrite with the bad numbers named, else template.

    At most two narrator calls: the draft and at most one rewrite. Anything
    still failing falls back to the code-written template, which passes by
    construction — the user never sees an unverified number. When on_draft
    is given, it is called after each draft's check as
    on_draft(attempt, text, report, usage) — the eval recorder uses it to
    save both drafts, never to change the ladder.

    The accepted draft — first-pass or rewritten, exactly once — then faces
    the claim judge (decision 26), a different model that checks meaning
    only. A failed meaning falls back to the template; a judge timeout or
    error falls back to the template with the unavailable wording. Judge
    calls never count against the narrator budget.
    """
    def done(text: str, kind: str, attempts: int,
             reason: str | None = None) -> ExplainResult:
        return ExplainResult(text, display_status(kind, reason), attempts,
                             kind, reason)

    def once(messages: list[dict[str, Any]], attempt: int) -> tuple[str, Any, Any]:
        sink: list[dict[str, Any]] = []
        text = draft_narrative(messages, client=client, usage_sink=sink)
        checked = verify_narrative(text, result, decision, rates_pct, wait)
        if on_draft is not None:
            on_draft(attempt, text, checked, sink[0])
        return text, checked, sink[0]

    def judged(text: str, kind: str, attempts: int) -> ExplainResult:
        # Meaning check on the accepted draft only — never a number-failed
        # draft, never the template. Failures fall back; they never retry.
        try:
            found = judge_draft(
                {"headline": decision.headline,
                 "tradeoff_note": decision.tradeoff_note,
                 "figures": explainer_figures(result, rates_pct, wait),
                 "draft": text},
                client=judge_client,
                usage_sink=judge_usage_sink,
            )
        except LlmError:
            return done(build_template(result, decision), "template",
                        attempts, REASON_JUDGE_DOWN)
        if judge_verdict_sink is not None:
            judge_verdict_sink.append({"passed": found.passed,
                                       "problems": list(found.problems)})
        if not found.passed:
            return done(build_template(result, decision), "template",
                        attempts, REASON_MEANING_FAILED)
        return done(text, kind, attempts)

    messages = build_explainer_messages(result, decision, rates_pct, wait)
    try:
        draft, report, _ = once(messages, 1)
    except LlmError:
        # No draft at all: fail loudly as the template, honestly labeled.
        return done(build_template(result, decision), "template", 0,
                    REASON_MODEL_UNAVAILABLE)
    if report.ok:
        return judged(draft, "verified", 1)
    retry = messages + [
        {"role": "assistant", "content": draft},
        {"role": "user", "content": (
            "Rewrite the explanation fixing this: " + rewrite_feedback(report)
        )},
    ]
    try:
        second, second_report, _ = once(retry, 2)
    except LlmError:
        return done(build_template(result, decision), "template", 1,
                    REASON_MODEL_UNAVAILABLE)
    if second_report.ok:
        return judged(second, "rewritten", 2)
    return done(build_template(result, decision), "template", 2,
                REASON_FAILED_CHECKS)
