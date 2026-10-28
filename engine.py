"""Deterministic math for the auto-refinance decision assistant.

Why this module exists: the model never generates a number. Every figure the
user sees — payments, totals, the rate/term/costs split, the lowest-total-cost
label — is computed here with the standard amortization formula, so results
are reproducible and checkable without the UI or the model.

Scope: one existing auto loan, one refinance offer, explicit wait scenarios.
Verdict rules (keep / refinance now / too close to call, headline, tradeoff
note) live in Section 5, settled by decisions 7-11 in docs/DECISIONS.md. The
Comparison only reports numbers and the lowest-total-cost label.

Layout:
    Section 1 — Inputs (CurrentLoan, RefinanceOffer, Comparison,
                    STANDARD_AUTO_TERMS)
    Section 2 — Validation (all input checks in one place)
    Section 3 — Calculation logic (payments, balances, schedules, cashflows)
    Section 4 — Options evaluation (plain comparisons, wait pricing and
                    breakeven thresholds)
    Section 5 — Verdict (code rules over a Comparison: choice, headline,
                    tradeoff note)
"""

from __future__ import annotations

from dataclasses import dataclass


# ============================================================================
# Section 1 — Inputs: user-confirmed terms and engine output shapes.
# Everything the model reads in, and everything it reads out, is defined here.
# ============================================================================


@dataclass(frozen=True)
class CurrentLoan:
    """The borrower's existing auto loan, as confirmed by the borrower."""

    balance: float  # dollars still owed
    annual_rate: float  # current APR as a decimal, e.g. 0.075
    remaining_months: int  # payments left on the current loan
    prepayment_penalty: float = 0.0  # charged only if refinanced away early

    def __post_init__(self) -> None:
        # Frozen classes skip __init__, so validation runs here instead: bad
        # terms fail at construction, before any math can touch them.
        _validate(self.balance, self.annual_rate, self.remaining_months)
        if self.prepayment_penalty < 0:
            raise ValueError(f"prepayment_penalty cannot be negative, got {self.prepayment_penalty}")


@dataclass(frozen=True)
class RefinanceOffer:
    """The refinance offer under evaluation. Mirrors CurrentLoan for the new loan."""

    annual_rate: float  # offered APR as a decimal
    term_months: int  # offered term in monthly payments
    fees: float = 0.0  # lender origination/closing fees for taking this offer
    fees_financed: bool = False  # True rolls fees into the new balance (they
    # accrue interest); False means paid out of pocket at signing.

    def __post_init__(self) -> None:
        # Same fail-fast rule as CurrentLoan: bad offers fail before any math runs.
        if self.annual_rate < 0 or self.annual_rate >= 1:
            raise ValueError(f"annual_rate must be >= 0 and < 1, got {self.annual_rate}")
        if not isinstance(self.term_months, int) or isinstance(self.term_months, bool) or self.term_months <= 0:
            raise ValueError(f"term_months must be a positive integer, got {self.term_months}")
        if self.fees < 0:
            raise ValueError(f"fees cannot be negative, got {self.fees}")


# Standard auto-loan terms in months. The UI dropdown reads from here so the
# offered choices stay in one place; the engine itself stays permissive
# (any positive term) and does not enforce this list.
STANDARD_AUTO_TERMS = (24, 36, 48, 60, 72, 84)


@dataclass(frozen=True)
class Comparison:
    """Engine output. The model narrates these numbers; it never recomputes them."""

    keep_monthly: float
    keep_total: float
    refi_monthly: float
    refi_total: float  # payments + upfront fees + prepayment penalty (fees join
    # the balance instead when financed)
    total_savings: float  # keep_total - refi_total; positive means refinancing saves
    monthly_change: float  # refi_monthly - keep_monthly; negative means lower payment
    cash_due_today: float  # out of pocket at signing: upfront fees + prepayment penalty
    months_to_payoff_keep: int  # remaining months on the current loan
    months_to_payoff_refi: int  # term months on the offer
    keep_interest: float  # lifetime interest on the current loan
    refi_interest: float  # lifetime interest on the new loan (on the financed
    # balance, so financed fees accrue here; upfront fees and the penalty are
    # charges, not interest, and stay in costs_effect)
    breakeven_month: int | None  # first month after which refi stays ahead
    # of keep for good (upfront fees+penalty counted in month 1); None if
    # savings ever go negative again within the horizon (the longer of the
    # two loan terms)
    rate_effect: float  # savings from the rate change; positive when the refi rate is lower
    term_effect: float  # savings from the term change; negative when the new term costs more
    costs_effect: float  # -(upfront fees + prepayment penalty + financed-fee burden); always <= 0
    lowest_total_cost: str  # which option costs less in total, as a plain fact:
    # "keep", "refinance_now", or "equal" on exact ties. It names the cheaper
    # total and nothing more — near-tie calls like "too close to call" are
    # not engine output.


# ============================================================================
# Section 2 — Validation: every input check in one place.
# Fail loudly so no silent garbage ever reaches the user.
# ============================================================================


def _validate(principal: float, annual_rate: float, months: int) -> None:
    if principal <= 0:
        raise ValueError(f"principal must be positive, got {principal}")
    # APR as a decimal: 0 (interest-free) up to but not including 1 (100%).
    # Anything at or above 1 is a data-entry error, e.g. typing 7.5 for 7.5%.
    if annual_rate < 0 or annual_rate >= 1:
        raise ValueError(f"annual_rate must be >= 0 and < 1, got {annual_rate}")
    if not isinstance(months, int) or isinstance(months, bool) or months <= 0:
        raise ValueError(f"months must be a positive integer, got {months}")


# ============================================================================
# Section 3 — Calculation logic: the amortization core.
# Full precision here; rounding is display-only, never baked into the math.
# ============================================================================


def monthly_payment(principal: float, annual_rate: float, months: int) -> float:
    """Standard amortization payment."""
    _validate(principal, annual_rate, months)
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        # No interest: the payment is exactly principal divided by months.
        return principal / months
    return principal * monthly_rate / (1 - (1 + monthly_rate) ** -months)


def remaining_balance(principal: float, annual_rate: float, months: int, paid: int) -> float:
    """Balance after `paid` payments. Closed form so schedules stay consistent."""
    _validate(principal, annual_rate, months)
    if not isinstance(paid, int) or isinstance(paid, bool) or paid < 0 or paid > months:
        raise ValueError(f"paid must be an integer in 0..{months}, got {paid}")
    payment = monthly_payment(principal, annual_rate, months)
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return principal - payment * paid
    growth = (1 + monthly_rate) ** paid
    return principal * growth - payment * (growth - 1) / monthly_rate


def schedule(principal: float, annual_rate: float, months: int) -> list:
    """Per-month (interest, principal, balance). Lets tests prove every dollar."""
    _validate(principal, annual_rate, months)
    payment = monthly_payment(principal, annual_rate, months)
    monthly_rate = annual_rate / 12
    rows = []
    balance = principal
    for _ in range(months):
        interest = balance * monthly_rate
        principal_paid = payment - interest
        balance -= principal_paid
        rows.append((interest, principal_paid, balance))
    return rows


def _total(principal: float, annual_rate: float, months: int) -> float:
    # Total of payments before fees: the common building block for Section 4.
    return monthly_payment(principal, annual_rate, months) * months


_SAVINGS_TOLERANCE = 1e-6  # dollars; differences below a millionth of a dollar
# are float noise from accumulating rounded-division payments, never signal.


def _stay_green_month(savings: tuple) -> int | None:
    """First month after which savings never go negative again, ignoring float
    noise below $0.000001. None when savings end negative."""
    last_negative = 0
    for month, value in enumerate(savings, 1):
        if value < -_SAVINGS_TOLERANCE:
            last_negative = month
    return last_negative + 1 if last_negative < len(savings) else None


@dataclass(frozen=True)
class CashFlowRow:
    """One month of cumulative cash flows. Refi cumulative includes upfront
    fees+penalty from month 1, so breakeven reads straight off the rows."""

    month: int
    keep_payment: float
    keep_cumulative: float
    refi_payment: float
    refi_cumulative: float


def cashflows(current: CurrentLoan, offer: RefinanceOffer) -> tuple:
    """Per-month cash flows for keep and refi, months 1 through the horizon
    (the longer of the two terms). After a loan's own term ends its payment
    is 0 and its cumulative stays flat."""
    keep_monthly = monthly_payment(current.balance, current.annual_rate, current.remaining_months)
    new_balance = current.balance + (offer.fees if offer.fees_financed else 0.0)
    refi_monthly = monthly_payment(new_balance, offer.annual_rate, offer.term_months)
    upfront = (0.0 if offer.fees_financed else offer.fees) + current.prepayment_penalty
    horizon = max(current.remaining_months, offer.term_months)
    rows = []
    keep_cum = 0.0
    refi_cum = upfront
    for m in range(1, horizon + 1):
        keep_pay = keep_monthly if m <= current.remaining_months else 0.0
        refi_pay = refi_monthly if m <= offer.term_months else 0.0
        keep_cum += keep_pay
        refi_cum += refi_pay
        rows.append(CashFlowRow(m, keep_pay, keep_cum, refi_pay, refi_cum))
    return tuple(rows)


# ============================================================================
# Section 4 — Options evaluation: keep vs refinance-now, plus the cost split.
# The split always satisfies:
#     rate_effect + term_effect + costs_effect == total_savings
# so the explanation can show where every dollar of savings comes from.
# Sign rule: positive helps the borrower, negative hurts. A lower refi rate
# contributes positive rate_effect; a longer term contributes negative
# term_effect; fees and penalty always contribute negative costs_effect.
# Note: the prepayment penalty rides on the CURRENT loan (charged when you
# leave it) while fees ride on the OFFER (charged when you take it). Financed
# fees join the new balance and accrue interest; that whole burden (fee
# amount plus its interest) sits in costs_effect, never in term_effect.
# ============================================================================


def compare(
    current: CurrentLoan,
    offer: RefinanceOffer,
) -> Comparison:
    """Keep vs refinance-now, plus the cost split. Delayed-refinance scenarios
    live in wait_plan, not here — compare() prices acting today only."""
    _validate(current.balance, current.annual_rate, current.remaining_months)
    _validate(current.balance, offer.annual_rate, offer.term_months)

    financed = offer.fees if offer.fees_financed else 0.0
    # The amount the new loan actually finances: what is still owed, plus fees
    # only when the borrower rolls them in. No cash-out, narrow scope.
    new_balance = current.balance + financed
    upfront_fees = 0.0 if offer.fees_financed else offer.fees

    keep_total = _total(current.balance, current.annual_rate, current.remaining_months)
    refi_base_total = _total(new_balance, offer.annual_rate, offer.term_months)
    refi_total = refi_base_total + upfront_fees + current.prepayment_penalty

    # All three effects are computed on the actual current balance, so the
    # financed-fee burden (fee amount plus the interest it accrues) sits
    # entirely in costs_effect instead of leaking into term_effect.
    # Rate-first order (decision 12): the rate leg is priced over the same
    # remaining term, and the term leg prices the timeline change at the
    # offered rate. The old term-first order credited the rate with savings
    # on months the term extension created.
    base_unfinanced = _total(current.balance, offer.annual_rate, offer.term_months)
    financed_extra = refi_base_total - base_unfinanced  # 0 unless fees financed
    same_term_at_offer_rate = _total(current.balance, offer.annual_rate, current.remaining_months)
    # Same balance and term (the remaining months) on both sides, so only
    # the rate can differ here. Positive when the refi rate is lower (it
    # saves money). Exactly 0 when the rates match (the regression the
    # suite pins).
    rate_effect = keep_total - same_term_at_offer_rate
    # Same balance and rate (the offered rate) on both sides, so only the
    # term differs here. Positive when the new term saves money, negative
    # when it costs more.
    term_effect = same_term_at_offer_rate - base_unfinanced
    # Upfront charges plus any financed-fee burden work against savings.
    # Written as 0.0 minus the sum so a zero total is +0.0, never -0.0.
    costs_effect = 0.0 - (upfront_fees + current.prepayment_penalty + financed_extra)

    # Exact ties report "equal".
    if keep_total < refi_total:
        lowest = "keep"
    elif refi_total < keep_total:
        lowest = "refinance_now"
    else:
        lowest = "equal"

    # Breakeven under the stay-green rule: the first month after which
    # cumulative savings (keep minus refi) never go negative again. A lead
    # that later reverses — e.g. a longer refi term outlasting the keep loan
    # — reports None instead of an early, misleading month. Dust-level float
    # wobbles (below $0.000001) count as zero, not as crossings.
    rows = cashflows(current, offer)
    savings = tuple(row.keep_cumulative - row.refi_cumulative for row in rows)
    breakeven_month = _stay_green_month(savings)
    keep_monthly = rows[0].keep_payment
    refi_monthly = rows[0].refi_payment

    return Comparison(
        keep_monthly=keep_monthly,
        keep_total=keep_total,
        refi_monthly=refi_monthly,
        refi_total=refi_total,
        total_savings=keep_total - refi_total,
        monthly_change=refi_monthly - keep_monthly,
        cash_due_today=upfront_fees + current.prepayment_penalty,
        months_to_payoff_keep=current.remaining_months,
        months_to_payoff_refi=offer.term_months,
        keep_interest=keep_total - current.balance,
        refi_interest=refi_base_total - new_balance,
        breakeven_month=breakeven_month,
        rate_effect=rate_effect,
        term_effect=term_effect,
        costs_effect=costs_effect,
        lowest_total_cost=lowest,
    )


# Waiting N months means paying the current loan N more times (the balance
# amortizes down), then refinancing the smaller balance at a future rate.
# WaitPlan prices one such delayed refinance; wait_breakeven_rate answers the
# customer's real question: "if I wait N months, what future rate do I need
# to break even with today's cheaper option?" Waiting at any rate below the
# returned threshold beats that baseline; None means even 0% cannot win.
# The baseline names "keep", "refinance_now", or "equal".


@dataclass(frozen=True)
class WaitPlan:
    """One delayed refinance: wait, then refinance the amortized balance."""

    wait_months: int
    annual_rate: float  # scenario rate available after waiting
    paid_while_waiting: float  # keep payments made during the wait
    interest_while_waiting: float  # the sunk part: keep-loan interest during
    # the wait. Principal repaid in that time is not lost — it lowered the
    # balance owed, so it is excluded here.
    balance_at_refi: float  # what is still owed when refinancing
    monthly: float  # new payment after refinancing
    total: float  # paid_while_waiting + new-loan payments + upfront charges
    # (fees unless financed, plus any prepayment penalty)


def _validate_wait(wait_months: int, remaining_months: int) -> None:
    # Waiting past payoff leaves nothing to refinance, so it is capped below
    # the remaining term. Zero is allowed: it means refinancing immediately.
    if not isinstance(wait_months, int) or isinstance(wait_months, bool):
        raise ValueError(f"wait_months must be an integer, got {wait_months}")
    if wait_months < 0 or wait_months >= remaining_months:
        raise ValueError(
            f"wait_months must be in 0..{remaining_months - 1}, got {wait_months}"
        )


def wait_plan(
    current: CurrentLoan, offer: RefinanceOffer, wait_months: int, annual_rate: float
) -> WaitPlan:
    """Price refinancing after waiting `wait_months` at scenario `annual_rate`."""
    _validate_wait(wait_months, current.remaining_months)
    if annual_rate < 0 or annual_rate >= 1:
        raise ValueError(f"wait scenario rates must be >= 0 and < 1, got {annual_rate}")

    keep_monthly = monthly_payment(current.balance, current.annual_rate, current.remaining_months)
    paid_while_waiting = keep_monthly * wait_months
    balance_at_refi = remaining_balance(
        current.balance, current.annual_rate, current.remaining_months, wait_months
    )
    interest_while_waiting = paid_while_waiting - (current.balance - balance_at_refi)
    financed = offer.fees if offer.fees_financed else 0.0
    new_balance = balance_at_refi + financed
    upfront_costs = (0.0 if offer.fees_financed else offer.fees) + current.prepayment_penalty
    new_monthly = monthly_payment(new_balance, annual_rate, offer.term_months)
    return WaitPlan(
        wait_months=wait_months,
        annual_rate=annual_rate,
        paid_while_waiting=paid_while_waiting,
        interest_while_waiting=interest_while_waiting,
        balance_at_refi=balance_at_refi,
        monthly=new_monthly,
        total=paid_while_waiting + new_monthly * offer.term_months + upfront_costs,
    )


@dataclass(frozen=True)
class WaitBreakeven:
    """Threshold future rate for a delayed refinance, with its baseline named."""

    baseline: str  # "keep", "refinance_now", or "equal" — the cheaper of
    # today's options; "equal" on exact ties
    baseline_total: float
    rate: float | None  # future rate tying the baseline; below it waiting wins


def wait_breakeven_rate(
    current: CurrentLoan,
    offer: RefinanceOffer,
    wait_months: int,
) -> WaitBreakeven:
    """Future rate at which waiting `wait_months` ties today's cheaper option.

    Scenario analysis only — never a forecast. Thresholds always compare
    lifetime totals: a lower monthly payment that costs more overall is the
    payment trap this tool exists to expose, so payment-only thresholds are
    deliberately not offered. Returns the threshold r* against the cheaper of
    keep and refinance-now (named in the answer): waiting then refinancing at
    a rate below r* beats it on total cost; above it loses. No claim is made
    about which rates will actually occur. The rate is None when even 0%
    cannot win. On an exact tie the baseline is "equal".
    """
    _validate_wait(wait_months, current.remaining_months)
    today = compare(current, offer)
    totals = (today.keep_total, today.refi_total)

    def wait_total(rate: float) -> float:
        return wait_plan(current, offer, wait_months, rate).total

    # Exact ties report "equal".
    if totals[0] < totals[1]:
        baseline, baseline_total = "keep", totals[0]
    elif totals[1] < totals[0]:
        baseline, baseline_total = "refinance_now", totals[1]
    else:
        baseline, baseline_total = "equal", totals[0]

    if wait_total(0.0) > baseline_total:
        return WaitBreakeven(baseline, baseline_total, None)
    lo, hi = 0.0, 1.0 - 1e-9
    if wait_total(hi) <= baseline_total:
        return WaitBreakeven(baseline, baseline_total, None)  # degenerate
    # wait_total rises with rate, so exactly one root sits in [lo, hi].
    for _ in range(80):
        mid = (lo + hi) / 2
        if wait_total(mid) <= baseline_total:
            lo = mid
        else:
            hi = mid
    return WaitBreakeven(baseline, baseline_total, (lo + hi) / 2)


# ============================================================================
# Section 5 — Verdict: code rules over a Comparison, never model judgment.
# The model explains the verdict but never changes, softens, or contradicts
# it. Headlines and tradeoff notes are fixed templates (decisions 7-11 in
# docs/DECISIONS.md); waiting is never a verdict, only a condition.
# ============================================================================


@dataclass(frozen=True)
class Verdict:
    """The code-written verdict the model narrates but cannot override."""

    choice: str  # "keep", "refinance_now", or "too_close"
    headline: str  # one of the eleven fixed templates, amounts comma-formatted
    tradeoff_note: str  # payment change + total difference (+ payoff when terms
    # differ), framed from the winner's side — refinance framing when too
    # close, since there is no winner; "and" when both favor one side,
    # "but" when they split


# Margins are compared on the cent-rounded value, so a headline never says
# "too close ... $100.00 apart": 99.996 rounds to $100.00 and names a winner.
_TOTAL_CLOSE_MARGIN = 100.0
_PAYMENT_CLOSE_MARGIN = 10.0

_VALID_PRIORITIES = ("lowest_total_cost", "lowest_monthly_payment", "earliest_payoff")


def _money(value: float) -> str:
    # Display only; the engine never rounds its own math.
    return f"${abs(value):,.2f}"


def _cents(value: float) -> float:
    # The whole-cent value the user would see, for margin comparisons.
    return round(abs(value), 2)


def _tradeoff_note(result: Comparison, choice: str) -> str:
    """Payment change and total difference in one sentence, plus payoff timing
    in its own second sentence when the loans end at different times. Framed
    from the winner's side (decision 10): keep speaks as keep, refinancing
    and too-close verdicts speak as refinancing."""
    from_keep = choice == "keep"
    pay_cents = _cents(result.monthly_change)
    total_cents = _cents(result.total_savings)
    if pay_cents == 0.0 and total_cents == 0.0:
        note = "Both loans charge the same monthly payment and cost the same in total."
    elif pay_cents == 0.0:
        if from_keep:
            total_phrase = (
                f"you pay {_money(result.total_savings)} less in total"
                if result.total_savings < 0
                else f"refinancing saves you {_money(result.total_savings)} in total"
            )
            note = f"Your payment stays the same, and {total_phrase}."
        else:
            total_phrase = (
                f"saves you {_money(result.total_savings)} in total"
                if result.total_savings > 0
                else f"costs {_money(result.total_savings)} more in total"
            )
            note = f"Refinancing leaves your payment unchanged, and {total_phrase}."
    elif total_cents == 0.0:
        if from_keep:
            pay_phrase = (
                f"Your payment is {_money(result.monthly_change)} a month lower"
                if result.monthly_change > 0
                else f"Your payment stays {_money(result.monthly_change)} a month higher"
            )
            note = f"{pay_phrase}, and the total cost is the same."
        else:
            pay_phrase = (
                f"Refinancing lowers your payment by {_money(result.monthly_change)} a month"
                if result.monthly_change < 0
                else f"Refinancing raises your payment by {_money(result.monthly_change)} a month"
            )
            note = f"{pay_phrase}, and costs the same in total."
    else:
        if from_keep:
            pay_phrase = (
                f"Your payment is {_money(result.monthly_change)} a month lower"
                if result.monthly_change > 0
                else f"Your payment stays {_money(result.monthly_change)} a month higher"
            )
            total_phrase = (
                f"refinancing saves you {_money(result.total_savings)} in total"
                if result.total_savings > 0
                else f"you pay {_money(result.total_savings)} less in total"
            )
        else:
            pay_phrase = (
                f"Refinancing lowers your payment by {_money(result.monthly_change)} a month"
                if result.monthly_change < 0
                else f"Refinancing raises your payment by {_money(result.monthly_change)} a month"
            )
            total_phrase = (
                f"saves you {_money(result.total_savings)} in total"
                if result.total_savings > 0
                else f"costs {_money(result.total_savings)} more in total"
            )
        # "and" when payment and total favor the same side, "but" when they
        # point opposite ways; never invents a tradeoff beyond these facts.
        same_side = (result.monthly_change < 0) == (result.total_savings > 0)
        note = f"{pay_phrase}, {'and' if same_side else 'but'} {total_phrase}."
    if result.months_to_payoff_keep != result.months_to_payoff_refi:
        gap = abs(result.months_to_payoff_refi - result.months_to_payoff_keep)
        word = "month" if gap == 1 else "months"
        if from_keep:
            if result.months_to_payoff_keep < result.months_to_payoff_refi:
                note += f" Your current loan pays off {gap} {word} sooner."
            else:
                note += f" Your current loan pays off {gap} {word} later."
        elif result.months_to_payoff_refi < result.months_to_payoff_keep:
            note += f" The refinance pays off {gap} {word} sooner."
        else:
            note += f" The refinance takes {gap} {word} longer to pay off."
    return note


def verdict(result: Comparison, priority: str = "lowest_total_cost") -> Verdict:
    """Pick the winner by code rule and write its headline and tradeoff note.

    Priorities are lowest_total_cost (default), lowest_monthly_payment, and
    earliest_payoff. "Under" is strict on cent-rounded values: exactly $100.00
    total (or $10.00 a month) picks a winner. A payoff-month tie falls back
    to total cost. Anything else for priority raises ValueError.
    """
    if priority not in _VALID_PRIORITIES:
        raise ValueError(
            f"priority must be one of {_VALID_PRIORITIES}, got {priority!r}"
        )
    if priority == "lowest_total_cost":
        total_cents = _cents(result.total_savings)
        if total_cents < _TOTAL_CLOSE_MARGIN:
            choice, headline = "too_close", f"Too close to call on total cost — {_money(result.total_savings)} apart."
        elif result.total_savings > 0:
            choice, headline = "refinance_now", f"Refinancing saves you {_money(result.total_savings)} in total."
        else:
            choice, headline = "keep", f"Keeping your loan costs {_money(result.total_savings)} less in total."
    elif priority == "lowest_monthly_payment":
        pay_cents = _cents(result.monthly_change)
        if pay_cents < _PAYMENT_CLOSE_MARGIN:
            choice, headline = "too_close", f"Too close to call on payment — {_money(result.monthly_change)} a month apart."
        elif result.monthly_change < 0:
            choice, headline = "refinance_now", f"Refinancing lowers your payment by {_money(result.monthly_change)} a month."
        else:
            choice, headline = "keep", f"Your current payment is {_money(result.monthly_change)} a month lower."
    else:
        keep_months = result.months_to_payoff_keep
        refi_months = result.months_to_payoff_refi
        if refi_months < keep_months:
            gap = keep_months - refi_months
            choice, headline = "refinance_now", f"Refinancing pays off {gap} {'month' if gap == 1 else 'months'} sooner."
        elif keep_months < refi_months:
            gap = refi_months - keep_months
            choice, headline = "keep", f"Your current loan pays off first — {gap} {'month' if gap == 1 else 'months'} sooner."
        elif _cents(result.total_savings) < _TOTAL_CLOSE_MARGIN:
            choice, headline = "too_close", f"Too close to call — same payoff month and totals within {_money(result.total_savings)}."
        elif result.total_savings > 0:
            choice, headline = "refinance_now", f"Both loans pay off in {refi_months} months; refinancing costs {_money(result.total_savings)} less in total."
        else:
            choice, headline = "keep", f"Both loans pay off in {refi_months} months; keeping your loan costs {_money(result.total_savings)} less in total."
    return Verdict(choice, headline, _tradeoff_note(result, choice))
