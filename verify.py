"""verify.py — number verification for model narratives (decision 16, rule 3.4).

Why this module exists: the model explains the code-written verdict in plain
language, but the user never sees an unverified number. Every dollar amount
and month count in the narrative must match engine output to the displayed
cent, and the narrative must agree with the verdict (winner, direction, no
softening or contradiction). One rewrite with specific feedback, then the
code-written template — the screen always states which of the three the user
is seeing.

No math lives here beyond cent-rounding for comparison. Allowing a value
means finding it in the engine result, never recomputing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine import Comparison, Verdict, WaitComparison
from extract import word_number_spans

# Narrative contract: amounts render as $X.XX and counts as digits. One
# left-to-right scan finds every digit token ($, commas, decimals, %,
# hyphen-joined "50-month"); spelled-out runs come from extract's word
# parser with spans. Each number is then classified by the word next to it
# and must sit in the matching allowed set — anything else, years
# included, fails as unaccounted.
_MONEY_SHAPE_RE = re.compile(r"^\d[\d,]*(\.\d{1,2})?$")
_NUMBER_SCAN_RE = re.compile(r"""
    (?P<money>\$[\d,.]+)
  | (?P<pct>\d+(?:\.\d+)?\s*%)
  | (?P<numunit>\d[\d,]*(?:\.\d+)?\s*-?\s*(?:dollars?|cents?|percents?|years?|months?)\b)
  | (?P<monthof>\bmonths?\s+(?:is\s+)?\d+)
  | (?P<bare>\d[\d,]*(?:\.\d+)?)
""", re.IGNORECASE | re.VERBOSE)
_NUMUNIT_SPLIT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*-?\s*([a-z]+)", re.IGNORECASE)
_MONTHOF_NUM_RE = re.compile(r"(\d+)\s*$")
# A breakeven claim needs the word nearby: "month 7" alone names a horizon,
# never breakeven.
_BREAKEVEN_WORD_RE = re.compile(r"breakeven|breaks?\s+even", re.IGNORECASE)
_FOLLOW_UNIT_RE = re.compile(
    r"^\s*-?\s*(dollars?|cents?|percents?|years?|months?)\b", re.IGNORECASE)
_SCALE_WORD_RE = re.compile(
    r"\b(?:hundred|thousands?|millions?|billions?)\b", re.IGNORECASE)

# Headline-only phrasing: these sentence shapes never appear in tradeoff
# notes, so finding one from the other side means the narrative argues the
# loser's case. Payment headlines share their opening with notes, so they
# are matched with their terminal period (notes continue with a comma).
_REFI_ONLY = (
    "Refinancing saves you $",
    "Refinancing pays off ",
    "; refinancing costs $",
)
_KEEP_ONLY = (
    "Keeping your loan costs $",
    "Your current loan pays off first",
    "; keeping your loan costs $",
)
_REFI_PAYMENT_HEADLINE_RE = re.compile(
    r"Refinancing (?:lowers|raises) your payment by \$[\d,]+(?:\.\d{1,2})? a month\."
)
_KEEP_PAYMENT_HEADLINE_RE = re.compile(
    r"Your current payment is \$[\d,]+(?:\.\d{1,2})? a month lower\."
)


@dataclass
class VerificationResult:
    """One verification pass over a narrative draft."""

    ok: bool
    bad_amounts: list[str] = field(default_factory=list)
    bad_months: list[str] = field(default_factory=list)
    bad_rates: list[str] = field(default_factory=list)
    agreement_ok: bool = True
    feedback: str = ""


def _cents(value: float) -> float:
    # The displayed-cent value, matching engine-side margin comparisons.
    return round(abs(value), 2)


def _allowed_amounts(result: Comparison) -> list[float]:
    # Page 3 only: interest internals never reach the screen, so citing
    # them fails like any unaccounted number.
    return [_cents(v) for v in (
        result.keep_monthly, result.keep_total,
        result.refi_monthly, result.refi_total,
        result.total_savings, result.monthly_change,
        result.cash_due_today,
        result.rate_effect, result.term_effect, result.costs_effect,
    )]


def split_rows(result: Comparison) -> list[str]:
    """Rate/term/costs split in directional words (decision 12). One source:
    build_template and app.split_rows share this — the engine keeps signed
    numbers; wording here is display only."""
    if result.rate_effect > 0:
        rate = f"Lower rate: saves {_money(result.rate_effect)}."
    elif result.rate_effect < 0:
        rate = f"Higher rate: costs {_money(result.rate_effect)}."
    else:
        rate = "Same rate: no difference."
    if result.months_to_payoff_refi > result.months_to_payoff_keep:
        term = f"Longer term: costs {_money(result.term_effect)}."
    elif result.months_to_payoff_refi < result.months_to_payoff_keep:
        term = f"Shorter term: saves {_money(result.term_effect)}."
    else:
        term = "Same term: no change."
    if result.costs_effect == 0:
        costs = "No fees or charges."
    else:
        costs = f"Fees and charges: cost {_money(result.costs_effect)}."
    return [rate, term, costs]


def _allowed_months(result: Comparison) -> set[int]:
    months = {
        result.months_to_payoff_keep,
        result.months_to_payoff_refi,
        abs(result.months_to_payoff_refi - result.months_to_payoff_keep),
    }
    if result.breakeven_month is not None:
        months.add(result.breakeven_month)
    return months


def _agreement_ok(text: str, decision: Verdict) -> bool:
    # The narrative states the verdict headline verbatim and never states a
    # winner headline from the other side. Too-close narratives keep the
    # refinance framing in their tradeoff note, so payment phrasing is not
    # policed there — only winner-only headlines are.
    # Known limit: verbatim-headline agreement cannot catch softening ("you
    # might consider refinancing"). Hedging detection is Stage-3 claim-judge
    # work on a separate model, not a word list here — see the pinned test.
    if decision.headline not in text:
        return False
    if decision.choice == "refinance_now":
        if "Too close to call" in text:
            return False
        if any(s in text for s in _KEEP_ONLY):
            return False
        if _KEEP_PAYMENT_HEADLINE_RE.search(text):
            return False
    elif decision.choice == "keep":
        if "Too close to call" in text:
            return False
        if any(s in text for s in _REFI_ONLY):
            return False
        if _REFI_PAYMENT_HEADLINE_RE.search(text):
            return False
    else:  # too_close: must say so, and must not declare a winner.
        if "Too close to call" not in text:
            return False
        if any(s in text for s in _REFI_ONLY + _KEEP_ONLY):
            return False
        if _REFI_PAYMENT_HEADLINE_RE.search(text):
            return False
        if _KEEP_PAYMENT_HEADLINE_RE.search(text):
            return False
    return True


def verify_narrative(
    text: str,
    result: Comparison,
    decision: Verdict,
    rates_pct: tuple[float, ...] = (),
    wait: WaitComparison | None = None,
) -> VerificationResult:
    """Check one narrative draft against engine output and the verdict.

    Every number in the text is found (digit tokens plus spelled-out runs
    from extract's word parser) and classified by the word next to it:
    $ before it or "dollars" after it means an allowed amount; "month(s)"
    after it means an allowed month count; % or "percent" after it means a
    rate in rates_pct (caller passes loan APR, offer APR, plus wait
    scenario rates); "month N" counts as breakeven only with a breakeven
    word nearby, otherwise it names a horizon. Anything else, years
    included, fails as unaccounted. The allowed set is only what page 3
    shows: interest internals and paid-while-waiting stay out, so citing
    them fails. Pass wait (a compare_wait output) only when the narrative
    discusses a wait scenario: it adds exactly that scenario's wait
    length, payoff month, payment, total, and savings versus today.
    Feedback names every unaccounted number — the model already holds
    every allowed value, so specificity leaks nothing (decision 16).
    """
    allowed = _allowed_amounts(result)
    months = _allowed_months(result)
    if wait is not None:
        # Displayed scenario figures only: reading the engine's numbers,
        # never recomputing them.
        allowed += [_cents(v) for v in (
            wait.plan.monthly, wait.plan.total,
            wait.savings_vs_baseline, wait.baseline_total,
        )]
        months |= {wait.plan.wait_months, wait.plan.months_to_payoff}
    bad_amounts: list[str] = []
    bad_months: list[str] = []
    bad_rates: list[str] = []
    problems: list[str] = []

    def fail(label: str, bucket: list[str]) -> None:
        bucket.append(label)
        problems.append(f"number not in the results: {label}")

    def check_amount(label: str, value: float) -> None:
        if min(abs(value - a) for a in allowed) > 0.005:
            fail(label, bad_amounts)

    def check_month(label: str, value: float) -> None:
        if value != int(value) or int(value) not in months:
            fail(label, bad_months)

    def check_rate(label: str, value: float) -> None:
        if not rates_pct or min(abs(value - r) for r in rates_pct) > 0.005:
            fail(label, bad_rates)

    digit_spans = []
    for match in _NUMBER_SCAN_RE.finditer(text):
        kind = match.lastgroup
        found = match.group()
        digit_spans.append(match.span())
        if kind == "money":
            # Trailing ".,;:)" is sentence punctuation, never precision.
            shaped = found[1:].rstrip(".,;:)")
            if not _MONEY_SHAPE_RE.match(shaped):
                fail(f"${shaped}", bad_amounts)
            else:
                check_amount(f"${shaped}", float(shaped.replace(",", "")))
        elif kind == "pct":
            check_rate(found, float(found[:-1].strip()))
        elif kind == "numunit":
            num, unit = _NUMUNIT_SPLIT_RE.match(found).groups()  # type: ignore[union-attr]
            value = float(num.replace(",", ""))
            unit = unit.lower()
            if unit.startswith("dollar"):
                check_amount(found, value)
            elif unit.startswith("cent"):
                check_amount(found, value / 100)
            elif unit.startswith("percent"):
                check_rate(found, value)
            elif unit.startswith("month"):
                check_month(found, value)
            else:  # years name no horizon in the results
                fail(found, bad_months)
        elif kind == "monthof":
            number = int(_MONTHOF_NUM_RE.search(found).group(1))  # type: ignore[union-attr]
            window = text[max(0, match.start() - 40):match.start()]
            near = _BREAKEVEN_WORD_RE.search(window)
            claimed = (
                near is not None
                and not re.search(r"\d", window[near.end():])
                and result.breakeven_month is not None
                and number == result.breakeven_month
            )
            if not claimed:
                fail(f"month {number}", bad_months)
        else:  # bare digits with no figure word beside them
            fail(found, bad_amounts)

    for start, end, value in word_number_spans(text):
        if any(s < end and start < e for s, e in digit_spans):
            continue  # digit token owned by this run, e.g. "30 thousands"
        span = text[start:end]
        trailing = re.search(
            r"(dollars?|cents?|percents?)\s*$", span, re.IGNORECASE)
        following = _FOLLOW_UNIT_RE.match(text[end:])
        if trailing is not None:
            unit, label = trailing.group(1).lower(), span
        elif following is not None:
            unit, label = following.group(1).lower(), f"{span} {following.group(1)}"
        elif _SCALE_WORD_RE.search(span) is not None:
            # A bare scale phrase ("thirty thousand") still reads as an amount.
            check_amount(span, value)
            continue
        else:
            continue  # everyday words ("two loans") are not figures
        if unit.startswith("dollar") or unit.startswith("cent"):
            check_amount(label, value)
        elif unit.startswith("percent"):
            check_rate(label, value)
        else:  # months validated as counts, years always fail
            if unit.startswith("month"):
                check_month(label, value)
            else:
                fail(label, bad_months)

    agreement = _agreement_ok(text, decision)
    if not agreement:
        problems.append(
            "does not agree with the verdict — restate this headline exactly: "
            f"'{decision.headline}'"
        )
    feedback = (
        "Narrative failed verification: " + "; ".join(problems) + "."
        if problems else ""
    )
    return VerificationResult(
        ok=not problems,
        bad_amounts=bad_amounts,
        bad_months=bad_months,
        bad_rates=bad_rates,
        agreement_ok=agreement,
        feedback=feedback,
    )


def rewrite_feedback(report: VerificationResult) -> str:
    """The retry instruction for the model: the specific numbers to fix."""
    return report.feedback


def _money(value: float) -> str:
    # Display only; mirrors engine Directional wording (words carry direction).
    return f"${abs(value):,.2f}"


def build_template(result: Comparison, decision: Verdict) -> str:
    """Code-written fallback: headline, note, split, breakeven. Always verifies.

    Every number below comes from the engine result or the verdict, so this
    text passes verify_narrative by construction. Month counts name only
    real horizons; no rates appear, so no scenario context is needed.
    """
    rate, term, costs = split_rows(result)
    if result.breakeven_month is None:
        breakeven = "Breakeven: refinancing never stays ahead within the horizon."
    else:
        breakeven = f"Breakeven: month {result.breakeven_month}."
    return (
        f"{decision.headline} {decision.tradeoff_note} "
        f"Your current loan: {_money(result.keep_monthly)} a month, "
        f"{_money(result.keep_total)} in total. Refinancing now: "
        f"{_money(result.refi_monthly)} a month, {_money(result.refi_total)} "
        f"in total, with {_money(result.cash_due_today)} due today. "
        f"{rate} {term} {costs} {breakeven}"
    )
