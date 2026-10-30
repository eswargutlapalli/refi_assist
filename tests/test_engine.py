"""Suite for engine.py. Synthetic loans only — no real borrower data, ever.

Status per test is reported by pytest; run with `python3 -m pytest tests/ -v`.
The pinned regression: same-rate refinance must yield rate_effect == 0.
"""

import math

import pytest

from engine import (
    STANDARD_AUTO_TERMS,
    Comparison,
    CurrentLoan,
    RefinanceOffer,
    _stay_green_month,
    cashflows,
    compare,
    compare_wait,
    monthly_payment,
    remaining_balance,
    schedule,
    verdict,
    wait_breakeven_rate,
    wait_plan,
)


def test_zero_apr_payment_is_exact():
    # No interest: payment must be exactly principal divided by months.
    assert monthly_payment(12000.0, 0.0, 48) == pytest.approx(250.0)


def test_one_month_term_adds_single_interest_charge():
    assert monthly_payment(10000.0, 0.12, 1) == pytest.approx(10100.0)


def test_schedule_principal_sums_to_principal():
    rows = schedule(20000.0, 0.09, 36)
    assert len(rows) == 36
    assert sum(principal for _, principal, _ in rows) == pytest.approx(20000.0)


def test_schedule_ends_at_zero_balance():
    rows = schedule(15000.0, 0.06, 24)
    assert rows[-1][2] == pytest.approx(0.0, abs=1e-6)


def test_remaining_balance_matches_schedule():
    # Closed form and the month-by-month schedule must agree.
    rows = schedule(18000.0, 0.08, 36)
    assert remaining_balance(18000.0, 0.08, 36, 12) == pytest.approx(rows[11][2])


def test_same_rate_gives_zero_rate_effect():
    # Oracle case: refinancing at the same rate adds no rate-driven cost.
    current = CurrentLoan(balance=20000.0, annual_rate=0.07, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.07, term_months=48))
    assert result.rate_effect == pytest.approx(0.0, abs=1e-6)


def test_split_sums_to_total_savings():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=150.0)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0))
    split = result.rate_effect + result.term_effect + result.costs_effect
    assert split == pytest.approx(result.total_savings)


def test_costs_effect_is_negative_fees_plus_penalty():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=150.0)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0))
    assert result.costs_effect == pytest.approx(-450.0)
    no_fee = compare(CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40),
                     RefinanceOffer(annual_rate=0.06, term_months=60))
    assert result.refi_total - no_fee.refi_total == pytest.approx(450.0)


def test_same_term_split_is_pure_rate_minus_costs():
    # $12k, 9% x 18 mo vs 6% x 18 mo + $100 fee + $50 penalty: no term change,
    # so savings = rate savings minus costs, exactly.
    current = CurrentLoan(balance=12000.0, annual_rate=0.09, remaining_months=18, prepayment_penalty=50.0)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=18, fees=100.0))
    assert result.term_effect == pytest.approx(0.0, abs=1e-6)
    assert result.rate_effect == pytest.approx(295.04, abs=0.01)
    assert result.costs_effect == pytest.approx(-150.0)
    assert result.total_savings == pytest.approx(145.04, abs=0.01)
    assert result.breakeven_month == 10
    assert result.rate_effect + result.term_effect + result.costs_effect == pytest.approx(result.total_savings)


def test_penalty_defaults_to_zero():
    assert CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40).prepayment_penalty == pytest.approx(0.0)


def test_negative_penalty_rejected():
    with pytest.raises(ValueError):
        CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=-1.0)


def test_current_loan_rejects_bad_values_at_construction():
    with pytest.raises(ValueError):
        CurrentLoan(balance=-20000.0, annual_rate=0.09, remaining_months=40)
    with pytest.raises(ValueError):
        CurrentLoan(balance=20000.0, annual_rate=-0.01, remaining_months=40)
    with pytest.raises(ValueError):
        CurrentLoan(balance=20000.0, annual_rate=1.0, remaining_months=40)
    with pytest.raises(ValueError):
        CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=0)


def test_apr_must_be_below_one():
    # 0 (interest-free) is valid; 1 (100%) and above are data-entry errors.
    assert CurrentLoan(balance=20000.0, annual_rate=0.0, remaining_months=40).annual_rate == pytest.approx(0.0)
    assert RefinanceOffer(annual_rate=0.999, term_months=60).annual_rate == pytest.approx(0.999)
    with pytest.raises(ValueError):
        RefinanceOffer(annual_rate=1.0, term_months=60)
    with pytest.raises(ValueError):
        monthly_payment(5000.0, 1.5, 36)


def test_standard_auto_terms_for_dropdown():
    assert STANDARD_AUTO_TERMS == (24, 36, 48, 60, 72, 84)


def test_offer_fees_default_to_zero():
    offer = RefinanceOffer(annual_rate=0.06, term_months=60)
    assert offer.fees == pytest.approx(0.0)
    assert offer.fees_financed is False


def test_offer_rejects_bad_values_at_construction():
    with pytest.raises(ValueError):
        RefinanceOffer(annual_rate=0.06, term_months=60, fees=-10.0)
    with pytest.raises(ValueError):
        RefinanceOffer(annual_rate=-0.01, term_months=60)
    with pytest.raises(ValueError):
        RefinanceOffer(annual_rate=0.06, term_months=0)


def test_financed_fees_roll_into_balance():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0, fees_financed=True))
    assert result.refi_monthly == pytest.approx(monthly_payment(20300.0, 0.06, 60))
    # Costs carry the fee amount PLUS the interest it accrues — strictly worse
    # than paying the same fees upfront.
    assert result.costs_effect < -300.0
    assert result.costs_effect == pytest.approx(
        result.total_savings - result.rate_effect - result.term_effect)


def test_financed_fees_cost_more_than_upfront():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    financed = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0, fees_financed=True))
    upfront = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0))
    assert financed.refi_total > upfront.refi_total
    assert upfront.refi_total == pytest.approx(monthly_payment(20000.0, 0.06, 60) * 60 + 300.0)


def test_financed_split_sums_to_total_savings():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=150.0)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0, fees_financed=True))
    split = result.rate_effect + result.term_effect + result.costs_effect
    assert split == pytest.approx(result.total_savings)


def test_zero_costs_is_positive_zero():
    # Unary minus on a zero sum would give -0.0; the engine must return +0.0.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60))
    assert result.costs_effect == 0.0
    assert math.copysign(1.0, result.costs_effect) > 0


def test_wait_breakeven_baseline_equal_on_tie():
    current = CurrentLoan(balance=12000.0, annual_rate=0.0, remaining_months=24)
    offer = RefinanceOffer(annual_rate=0.0, term_months=24)
    answer = wait_breakeven_rate(current, offer, 6)
    assert answer.baseline == "equal"
    assert answer.rate is not None


def test_reference_trap_exact_numbers():
    # $15k at 7%, 36 left -> 6% for 72 months: longer term buries the win.
    current = CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=72))
    assert result.total_savings == pytest.approx(-1225.09, abs=0.01)
    assert result.breakeven_month is None
    assert result.lowest_total_cost == "keep"


def test_reference_clear_win_exact_numbers():
    # $25k at 11%, 48 left -> 7.5% for 48 months, $300 cash fee.
    current = CurrentLoan(balance=25000.0, annual_rate=0.11, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.075, term_months=48, fees=300.0))
    assert result.total_savings == pytest.approx(1699.94, abs=0.01)
    assert result.breakeven_month == 8
    assert result.lowest_total_cost == "refinance_now"


def test_reference_scenario_b_exact_numbers():
    # $12k at 9%, 18 left, $50 penalty -> 6% for 24 months, $100 fee financed.
    current = CurrentLoan(balance=12000.0, annual_rate=0.09, remaining_months=18, prepayment_penalty=50.0)
    offer = RefinanceOffer(annual_rate=0.06, term_months=24, fees=100.0, fees_financed=True)
    result = compare(current, offer)
    assert result.total_savings == pytest.approx(-47.61, abs=0.01)
    assert result.breakeven_month is None


def test_reference_scenario_c_wait_three_months():
    # Scenario A waited 3 months, then refinanced at 6%.
    current = CurrentLoan(balance=12000.0, annual_rate=0.09, remaining_months=18, prepayment_penalty=50.0)
    offer = RefinanceOffer(annual_rate=0.06, term_months=18, fees=100.0)
    plan = wait_plan(current, offer, 3, 0.06)
    assert plan.balance_at_refi == pytest.approx(10110.38, abs=0.01)
    assert plan.monthly == pytest.approx(588.75, abs=0.01)
    assert plan.total == pytest.approx(12892.93, abs=0.01)


def test_split_sums_on_trap():
    current = CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=72))
    split = result.rate_effect + result.term_effect + result.costs_effect
    assert split == pytest.approx(result.total_savings)


def test_split_sums_on_clear_win():
    current = CurrentLoan(balance=25000.0, annual_rate=0.11, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.075, term_months=48, fees=300.0))
    split = result.rate_effect + result.term_effect + result.costs_effect
    assert split == pytest.approx(result.total_savings)


def test_split_sums_on_financed_scenario_b():
    current = CurrentLoan(balance=12000.0, annual_rate=0.09, remaining_months=18, prepayment_penalty=50.0)
    offer = RefinanceOffer(annual_rate=0.06, term_months=24, fees=100.0, fees_financed=True)
    result = compare(current, offer)
    split = result.rate_effect + result.term_effect + result.costs_effect
    assert split == pytest.approx(result.total_savings)


def test_split_sums_on_financed_fee_case():
    # $18,450 at 8.9%, 41 left -> 5.49% for 48 months, $250 fee financed.
    current = CurrentLoan(balance=18450.0, annual_rate=0.089, remaining_months=41)
    offer = RefinanceOffer(annual_rate=0.0549, term_months=48, fees=250.0, fees_financed=True)
    result = compare(current, offer)
    split = result.rate_effect + result.term_effect + result.costs_effect
    assert split == pytest.approx(result.total_savings)
    assert result.costs_effect == pytest.approx(-279.02, abs=0.01)


def test_total_savings_sign_matches_label():
    cheap = compare(CurrentLoan(balance=25000.0, annual_rate=0.10, remaining_months=48),
                    RefinanceOffer(annual_rate=0.05, term_months=48))
    assert cheap.total_savings == pytest.approx(cheap.keep_total - cheap.refi_total)
    assert cheap.total_savings > 0
    pricey = compare(CurrentLoan(balance=25000.0, annual_rate=0.05, remaining_months=48),
                     RefinanceOffer(annual_rate=0.10, term_months=48))
    assert pricey.total_savings < 0
    tied = compare(CurrentLoan(balance=12000.0, annual_rate=0.0, remaining_months=24),
                   RefinanceOffer(annual_rate=0.0, term_months=24))
    assert tied.total_savings == pytest.approx(0.0)


def test_interest_fields_match_totals_minus_principal():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60))
    assert result.keep_interest == pytest.approx(3224.12, abs=0.01)
    assert result.refi_interest == pytest.approx(3199.36, abs=0.01)
    assert result.keep_interest - result.refi_interest == pytest.approx(result.total_savings)


def test_financed_fees_accrue_as_interest_not_charges():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    financed = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0, fees_financed=True))
    upfront = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0))
    assert financed.refi_interest > upfront.refi_interest
    assert financed.costs_effect < upfront.costs_effect
    assert financed.cash_due_today == pytest.approx(0.0)
    assert upfront.cash_due_today == pytest.approx(300.0)


def test_headline_narrative_metrics():
    # The $12k example: payment drops $16.39/mo, $150 due today, 18 vs 18 mo.
    current = CurrentLoan(balance=12000.0, annual_rate=0.09, remaining_months=18, prepayment_penalty=50.0)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=18, fees=100.0))
    assert result.monthly_change == pytest.approx(result.refi_monthly - result.keep_monthly)
    assert result.monthly_change == pytest.approx(-16.39, abs=0.01)
    assert result.cash_due_today == pytest.approx(150.0)
    assert result.months_to_payoff_keep == 18
    assert result.months_to_payoff_refi == 18


def _expected_breakeven(keep_monthly, keep_months, refi_monthly, refi_months, upfront):
    # Independent oracle for the stay-green rule: last month with negative
    # savings, plus one — None when savings end negative.
    horizon = max(keep_months, refi_months)
    last_negative = 0
    for m in range(1, horizon + 1):
        keep_paid = keep_monthly * min(m, keep_months)
        refi_paid = upfront + refi_monthly * min(m, refi_months)
        if keep_paid - refi_paid < 0:
            last_negative = m
    return last_negative + 1 if last_negative < horizon else None


def test_breakeven_immediate_with_no_upfront_costs():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60))
    assert result.breakeven_month == 1
    assert result.breakeven_month == _expected_breakeven(
        result.keep_monthly, 40, result.refi_monthly, 60, 0.0)


def test_breakeven_small_upfront_cost_stays_green():
    # $20 upfront is recovered in month 1 and savings never reverse.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=20.0))
    assert result.total_savings > 0
    assert result.breakeven_month == 1
    assert result.breakeven_month == _expected_breakeven(
        result.keep_monthly, 40, result.refi_monthly, 60, 20.0)


def test_breakeven_none_when_lead_reverses():
    # $450 upfront breaks even at month 3, but the longer refi term ends up
    # costing more overall — the lead does not stay green, so no breakeven.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=150.0)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0))
    assert result.total_savings < 0
    assert result.breakeven_month is None
    assert result.breakeven_month == _expected_breakeven(
        result.keep_monthly, 40, result.refi_monthly, 60, 450.0)


def test_breakeven_never_for_losing_refinance():
    current = CurrentLoan(balance=25000.0, annual_rate=0.05, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.10, term_months=48, fees=2000.0))
    assert result.breakeven_month is None


def test_breakeven_after_shorter_refi_term_ends():
    # Shorter, cheaper refi: higher payment now, but the keep loan keeps
    # charging after the refi is paid off — the crossing can come late.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=24, fees=500.0))
    assert result.total_savings > 0
    month = result.breakeven_month
    assert month is not None and month > 24
    assert month == _expected_breakeven(result.keep_monthly, 40, result.refi_monthly, 24, 500.0)
    keep_at = result.keep_monthly * month
    refi_at = 500.0 + result.refi_monthly * 24
    assert refi_at <= keep_at
    keep_before = result.keep_monthly * (month - 1)
    refi_before = 500.0 + result.refi_monthly * min(month - 1, 24)
    assert refi_before > keep_before


def test_cashflows_shape_and_endpoints():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0)
    rows = cashflows(current, offer)
    assert len(rows) == 60
    assert [row.month for row in rows] == list(range(1, 61))
    assert rows[-1].keep_cumulative == pytest.approx(compare(current, offer).keep_total)
    assert rows[-1].refi_cumulative == pytest.approx(compare(current, offer).refi_total)
    # Month 41: keep loan is done, refi still charging.
    assert rows[40].keep_payment == pytest.approx(0.0)
    assert rows[40].refi_payment > 0
    # Month 1 refi cumulative already carries the upfront fees.
    assert rows[0].refi_cumulative == pytest.approx(300.0 + rows[0].refi_payment)


def test_cumulative_cashflows_equal_totals():
    # Month-by-month accumulation must reconcile with the headline totals.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=60))
    assert result.keep_monthly * 40 == pytest.approx(result.keep_total)
    assert result.refi_monthly * 60 == pytest.approx(result.refi_total)


def test_cheaper_refinance_wins_lowest_cost_label():
    current = CurrentLoan(balance=25000.0, annual_rate=0.10, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.05, term_months=48))
    assert result.lowest_total_cost == "refinance_now"
    assert result.refi_total < result.keep_total


def test_expensive_refinance_keeps_label():
    current = CurrentLoan(balance=25000.0, annual_rate=0.05, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.10, term_months=48))
    assert result.lowest_total_cost == "keep"


def test_tie_reports_equal_for_verdict():
    # Exact ties are verdict business (rule 6): the engine makes no pick.
    current = CurrentLoan(balance=12000.0, annual_rate=0.0, remaining_months=24)
    result = compare(current, RefinanceOffer(annual_rate=0.0, term_months=24))
    assert result.keep_total == pytest.approx(result.refi_total)
    assert result.total_savings == pytest.approx(0.0)
    assert result.lowest_total_cost == "equal"


def test_wait_scenarios_fall_with_rate():
    current = CurrentLoan(balance=20000.0, annual_rate=0.08, remaining_months=48)
    offer = RefinanceOffer(annual_rate=0.07, term_months=48)
    totals = [wait_plan(current, offer, 0, rate).total for rate in (0.06, 0.05, 0.04)]
    assert totals == sorted(totals, reverse=True)
    assert all(total < compare(current, offer).keep_total for total in totals)


def test_wait_plan_month_zero_carries_fees():
    current = CurrentLoan(balance=20000.0, annual_rate=0.08, remaining_months=48)
    offer = RefinanceOffer(annual_rate=0.07, term_months=48, fees=200.0)
    assert wait_plan(current, offer, 0, 0.07).total == pytest.approx(compare(current, offer).refi_total)


def test_months_must_be_positive_integers():
    # Floats and bools (bool subclasses int) are rejected everywhere a
    # month count is taken: loan terms, offer terms, payments, and waits.
    with pytest.raises(ValueError):
        CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=36.5)
    with pytest.raises(ValueError):
        CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=True)
    with pytest.raises(ValueError):
        RefinanceOffer(annual_rate=0.06, term_months=60.5)
    with pytest.raises(ValueError):
        monthly_payment(20000.0, 0.09, True)
    with pytest.raises(ValueError):
        wait_plan(CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40),
                  RefinanceOffer(annual_rate=0.06, term_months=60), True, 0.05)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        monthly_payment(-5000.0, 0.07, 36)
    with pytest.raises(ValueError):
        monthly_payment(5000.0, -0.01, 36)
    with pytest.raises(ValueError):
        monthly_payment(5000.0, 0.07, 0)
    with pytest.raises(ValueError):
        remaining_balance(5000.0, 0.07, 36, 37)
    with pytest.raises(ValueError):
        RefinanceOffer(annual_rate=0.07, term_months=48, fees=-10.0)
    with pytest.raises(ValueError):
        wait_plan(CurrentLoan(balance=20000.0, annual_rate=0.08, remaining_months=48),
                  RefinanceOffer(annual_rate=0.07, term_months=48), 6, 1.5)


def test_wait_six_month_threshold_for_trap():
    # Trap: $450 upfront, longer 60-mo term. Waiting 6 months only wins in
    # scenarios at or below ~4.21% — the threshold the customer actually needs.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=150.0)
    offer = RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0)
    answer = wait_breakeven_rate(current, offer, 6)
    assert answer.baseline == "keep"
    assert answer.rate == pytest.approx(0.042115, abs=1e-4)
    assert wait_plan(current, offer, 6, answer.rate).total == pytest.approx(answer.baseline_total, abs=0.01)
    assert wait_plan(current, offer, 6, answer.rate - 0.005).total < answer.baseline_total
    assert wait_plan(current, offer, 6, answer.rate + 0.005).total > answer.baseline_total


def test_wait_six_month_threshold_for_15k_trap():
    # $15k at 7%, 36 left -> 6% for 72: waiting 6 months only wins in
    # scenarios at or below ~2.97% — rounded to 2 places per the reference.
    current = CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36)
    offer = RefinanceOffer(annual_rate=0.06, term_months=72)
    answer = wait_breakeven_rate(current, offer, 6)
    assert answer.baseline == "keep"
    assert round(answer.rate * 100, 2) == 2.97
    assert wait_plan(current, offer, 6, answer.rate).total == pytest.approx(answer.baseline_total, abs=0.01)
    assert wait_plan(current, offer, 6, answer.rate - 0.005).total < answer.baseline_total
    assert wait_plan(current, offer, 6, answer.rate + 0.005).total > answer.baseline_total


def test_compare_wait_bundles_plan_baseline_and_difference():
    # One call prices the scenario against today's cheaper total: the plan,
    # the engine's own baseline naming, and the signed difference.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.06, term_months=60)
    compared = compare_wait(current, offer, 6, 0.05)
    assert compared.plan.total == wait_plan(current, offer, 6, 0.05).total
    threshold = wait_breakeven_rate(current, offer, 6)
    assert (compared.baseline, compared.baseline_total, compared.breakeven_rate) == (
        threshold.baseline, threshold.baseline_total, threshold.rate)
    assert compared.savings_vs_baseline == compared.baseline_total - compared.plan.total
    today = compare(current, offer)
    assert compared.baseline_total == min(today.keep_total, today.refi_total)


def test_wait_plan_reports_payoff_months():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.06, term_months=60)
    assert wait_plan(current, offer, 6, 0.05).months_to_payoff == 66


def test_compare_wait_reports_months_vs_baseline():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    wait_later = compare_wait(current, RefinanceOffer(annual_rate=0.06, term_months=60), 6, 0.05)
    assert wait_later.months_vs_baseline == 66 - 60
    pricey = RefinanceOffer(annual_rate=0.06, term_months=24, fees=2000.0)
    wait_earlier = compare_wait(current, pricey, 3, 0.03)
    assert wait_earlier.baseline == "keep"
    assert wait_earlier.months_vs_baseline == 27 - 40
    same = RefinanceOffer(annual_rate=0.06, term_months=48)
    tied = compare_wait(
        CurrentLoan(balance=20000.0, annual_rate=0.06, remaining_months=48),
        same, 6, 0.05)
    assert tied.baseline == "equal"
    assert tied.months_vs_baseline == 54 - 48  # ties fall back to keep's payoff


def test_wait_thresholds_names_baseline_and_rates():
    from engine import wait_thresholds

    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.06, term_months=60)
    thresholds = wait_thresholds(current, offer, [3, 6, 9, 12])
    assert thresholds.baseline == "refinance_now"
    assert thresholds.baseline_total == compare(current, offer).refi_total
    assert thresholds.offer_rate == 0.06
    assert [w for w, _ in thresholds.rates] == [3, 6, 9, 12]
    for months, rate in thresholds.rates:
        assert rate == wait_breakeven_rate(current, offer, months).rate
    with pytest.raises(ValueError):
        wait_thresholds(current, offer, [])
    with pytest.raises(ValueError):
        wait_thresholds(current, offer, [3, 99])


def test_wait_three_month_threshold_against_refinance_now():
    # $20k at 9%, 40 left -> 6% for 60, wait 3 months: beats refinancing now
    # only in scenarios at or below ~5.5536%.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.06, term_months=60)
    answer = wait_breakeven_rate(current, offer, 3)
    assert answer.baseline == "refinance_now"
    assert answer.rate == pytest.approx(0.055536, abs=1e-6)
    assert wait_plan(current, offer, 3, answer.rate).total == pytest.approx(answer.baseline_total, abs=0.01)
    assert wait_plan(current, offer, 3, answer.rate - 0.005).total < answer.baseline_total
    assert wait_plan(current, offer, 3, answer.rate + 0.005).total > answer.baseline_total


def test_compare_prices_today_only():
    # compare() prices keep vs refinance-now; scenarios use wait_plan directly.
    current = CurrentLoan(balance=20000.0, annual_rate=0.08, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.07, term_months=48))
    assert isinstance(result, Comparison)
    assert not hasattr(result, "wait_options")


def test_stay_green_ignores_float_noise():
    assert _stay_green_month((0.0, -1e-9, 0.05)) == 1
    assert _stay_green_month((0.05, -0.02, 0.03)) == 3
    assert _stay_green_month((-0.1, -0.05)) is None
    assert _stay_green_month(()) is None


def test_wait_plan_month_zero_matches_immediate_refi():
    current = CurrentLoan(balance=20000.0, annual_rate=0.08, remaining_months=48)
    plan = wait_plan(current, RefinanceOffer(annual_rate=0.07, term_months=48), 0, 0.06)
    immediate = compare(current, RefinanceOffer(annual_rate=0.06, term_months=48))
    assert plan.balance_at_refi == pytest.approx(current.balance)
    assert plan.paid_while_waiting == pytest.approx(0.0)
    assert plan.monthly == pytest.approx(immediate.refi_monthly)
    assert plan.total == pytest.approx(immediate.refi_total)


def test_wait_plan_amortizes_then_refinances():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60, fees=200.0)
    plan = wait_plan(current, offer, 6, 0.05)
    assert plan.balance_at_refi == pytest.approx(remaining_balance(20000.0, 0.09, 40, 6))
    assert plan.paid_while_waiting == pytest.approx(monthly_payment(20000.0, 0.09, 40) * 6)
    assert plan.interest_while_waiting == pytest.approx(plan.paid_while_waiting - (20000.0 - plan.balance_at_refi))
    assert plan.total == pytest.approx(plan.paid_while_waiting + plan.monthly * 60 + 200.0)


def test_longer_wait_costs_more_at_same_rate():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60)
    assert wait_plan(current, offer, 6, 0.05).total > wait_plan(current, offer, 3, 0.05).total


def test_wait_breakeven_rate_breaks_even():
    current = CurrentLoan(balance=25000.0, annual_rate=0.10, remaining_months=48)
    offer = RefinanceOffer(annual_rate=0.05, term_months=48)
    answer = wait_breakeven_rate(current, offer, 6)
    assert answer.baseline == "refinance_now"
    assert answer.baseline_total == pytest.approx(compare(current, offer).refi_total)
    assert answer.rate is not None and 0.0 <= answer.rate < 1.0
    assert wait_plan(current, offer, 6, answer.rate).total == pytest.approx(answer.baseline_total, abs=0.01)
    if answer.rate > 0.005:
        assert wait_plan(current, offer, 6, answer.rate - 0.005).total < answer.baseline_total
    assert wait_plan(current, offer, 6, min(0.999999, answer.rate + 0.005)).total > answer.baseline_total


def test_wait_breakeven_baseline_is_keep_when_keeping_wins():
    current = CurrentLoan(balance=25000.0, annual_rate=0.05, remaining_months=48)
    offer = RefinanceOffer(annual_rate=0.10, term_months=48)
    answer = wait_breakeven_rate(current, offer, 6)
    assert answer.baseline == "keep"
    assert answer.baseline_total == pytest.approx(compare(current, offer).keep_total)
    assert answer.rate is not None and 0.0 <= answer.rate < 1.0
    assert wait_plan(current, offer, 6, answer.rate).total == pytest.approx(answer.baseline_total, abs=0.01)


def test_wait_breakeven_rate_none_when_nothing_left():
    # 46 of 48 months waited: the wait burns almost the whole loan balance.
    current = CurrentLoan(balance=25000.0, annual_rate=0.10, remaining_months=48)
    offer = RefinanceOffer(annual_rate=0.05, term_months=48)
    answer = wait_breakeven_rate(current, offer, 46)
    assert answer.baseline == "refinance_now"
    assert answer.rate is None


def test_wait_plan_rejects_out_of_range():
    current = CurrentLoan(balance=20000.0, annual_rate=0.08, remaining_months=48)
    offer = RefinanceOffer(annual_rate=0.07, term_months=48)
    with pytest.raises(ValueError):
        wait_plan(current, offer, 48, 0.05)
    with pytest.raises(ValueError):
        wait_plan(current, offer, -1, 0.05)
    with pytest.raises(ValueError):
        wait_plan(current, offer, 6, 1.0)
    with pytest.raises(ValueError):
        wait_breakeven_rate(current, offer, 48)


def test_rate_first_split_on_trap():
    # Rate-first (decision 12): rate over the same 36 months, term at 6%.
    current = CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36)
    result = compare(current, RefinanceOffer(annual_rate=0.06, term_months=72))
    assert result.rate_effect == pytest.approx(245.79, abs=0.01)
    assert result.term_effect == pytest.approx(-1470.87, abs=0.01)
    assert result.costs_effect == pytest.approx(0.0)
    assert result.rate_effect + result.term_effect + result.costs_effect == pytest.approx(result.total_savings)


def test_rate_first_split_on_clear_win():
    current = CurrentLoan(balance=25000.0, annual_rate=0.11, remaining_months=48)
    result = compare(current, RefinanceOffer(annual_rate=0.075, term_months=48, fees=300.0))
    assert result.rate_effect == pytest.approx(1999.94, abs=0.01)
    assert result.term_effect == pytest.approx(0.0, abs=1e-6)
    assert result.costs_effect == pytest.approx(-300.00)
    assert result.rate_effect + result.term_effect + result.costs_effect == pytest.approx(result.total_savings)


def test_rate_first_split_same_rate_longer_term():
    current = CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36)
    result = compare(current, RefinanceOffer(annual_rate=0.07, term_months=72))
    assert result.rate_effect == pytest.approx(0.0, abs=1e-6)
    assert result.term_effect == pytest.approx(-1739.29, abs=0.01)


def test_rate_first_split_cash_fee_with_penalty():
    current = CurrentLoan(balance=12486.20, annual_rate=0.069, remaining_months=22, prepayment_penalty=150.0)
    result = compare(current, RefinanceOffer(annual_rate=0.0499, term_months=24, fees=195.0))
    assert result.rate_effect == pytest.approx(236.44, abs=0.01)
    assert result.term_effect == pytest.approx(-53.57, abs=0.01)
    assert result.costs_effect == pytest.approx(-345.00)
    assert result.rate_effect + result.term_effect + result.costs_effect == pytest.approx(result.total_savings)


def test_rate_first_split_financed_fee_case():
    current = CurrentLoan(balance=18450.0, annual_rate=0.089, remaining_months=41)
    offer = RefinanceOffer(annual_rate=0.0549, term_months=48, fees=250.0, fees_financed=True)
    result = compare(current, offer)
    assert result.rate_effect == pytest.approx(1188.44, abs=0.01)
    assert result.term_effect == pytest.approx(-315.41, abs=0.01)
    assert result.costs_effect == pytest.approx(-279.02, abs=0.01)
    assert result.rate_effect + result.term_effect + result.costs_effect == pytest.approx(result.total_savings)


def _trap_comparison():
    current = CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36)
    return compare(current, RefinanceOffer(annual_rate=0.06, term_months=72))


def _clear_win_comparison():
    current = CurrentLoan(balance=25000.0, annual_rate=0.11, remaining_months=48)
    return compare(current, RefinanceOffer(annual_rate=0.075, term_months=48, fees=300.0))


def _close_call_comparison():
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40)
    return compare(current, RefinanceOffer(annual_rate=0.06, term_months=60))


def _direct_comparison(total_savings, monthly_change, keep_months=40, refi_months=60):
    # Boundary probe: only the margins matter, so the other fields are fixed.
    return Comparison(
        keep_monthly=500.0,
        keep_total=20000.0,
        refi_monthly=500.0 + monthly_change,
        refi_total=20000.0 - total_savings,
        total_savings=total_savings,
        monthly_change=monthly_change,
        cash_due_today=0.0,
        months_to_payoff_keep=keep_months,
        months_to_payoff_refi=refi_months,
        keep_interest=1000.0,
        refi_interest=1000.0 - total_savings,
        breakeven_month=1,
        rate_effect=0.0,
        term_effect=total_savings,
        costs_effect=0.0,
        lowest_total_cost="keep" if total_savings < 0 else "refinance_now" if total_savings > 0 else "equal",
    )


def test_verdict_trap_lowest_total_cost_is_keep():
    result = verdict(_trap_comparison(), "lowest_total_cost")
    assert result.choice == "keep"
    assert result.headline == "Keeping your loan costs $1,225.09 less in total."
    assert result.tradeoff_note == ("Your payment stays $214.56 a month higher, "
                                    "but you pay $1,225.09 less in total. "
                                    "Your current loan pays off 36 months sooner.")


def test_verdict_trap_lowest_monthly_payment_is_refinance():
    result = verdict(_trap_comparison(), "lowest_monthly_payment")
    assert result.choice == "refinance_now"
    assert result.headline == "Refinancing lowers your payment by $214.56 a month."
    assert result.tradeoff_note == ("Refinancing lowers your payment by $214.56 a month, "
                                    "but costs $1,225.09 more in total. "
                                    "The refinance takes 36 months longer to pay off.")


def test_verdict_trap_earliest_payoff_is_keep():
    result = verdict(_trap_comparison(), "earliest_payoff")
    assert result.choice == "keep"
    assert result.headline == "Your current loan pays off first — 36 months sooner."


def test_verdict_clear_win_lowest_total_cost_is_refinance():
    result = verdict(_clear_win_comparison(), "lowest_total_cost")
    assert result.choice == "refinance_now"
    assert result.headline == "Refinancing saves you $1,699.94 in total."
    assert " and " in result.tradeoff_note
    assert " but " not in result.tradeoff_note
    assert "$41.67" in result.tradeoff_note
    assert "pay off" not in result.tradeoff_note


def test_verdict_clear_win_earliest_payoff_falls_back_to_total():
    result = verdict(_clear_win_comparison(), "earliest_payoff")
    assert result.choice == "refinance_now"
    assert result.headline == "Both loans pay off in 48 months; refinancing costs $1,699.94 less in total."


def test_verdict_close_call_on_total_cost_is_too_close_with_note():
    result = verdict(_close_call_comparison(), "lowest_total_cost")
    assert result.choice == "too_close"
    assert result.headline == "Too close to call on total cost — $24.76 apart."
    assert result.tradeoff_note == ("Refinancing lowers your payment by $193.95 a month, "
                                    "and saves you $24.76 in total. "
                                    "The refinance takes 20 months longer to pay off.")


def test_verdict_close_call_earliest_payoff_keep_note_is_keep_framed():
    result = verdict(_close_call_comparison(), "earliest_payoff")
    assert result.choice == "keep"
    assert result.headline == "Your current loan pays off first — 20 months sooner."
    assert result.tradeoff_note == ("Your payment stays $193.95 a month higher, "
                                    "and refinancing saves you $24.76 in total. "
                                    "Your current loan pays off 20 months sooner.")


def test_verdict_payoff_headline_uses_singular_month():
    sooner = verdict(_direct_comparison(500.0, -50.0, 40, 39), "earliest_payoff")
    assert sooner.choice == "refinance_now"
    assert sooner.headline == "Refinancing pays off 1 month sooner."
    first = verdict(_direct_comparison(-500.0, 50.0, 39, 40), "earliest_payoff")
    assert first.choice == "keep"
    assert first.headline == "Your current loan pays off first — 1 month sooner."


def test_verdict_equal_totals_use_and_not_but():
    result = verdict(_direct_comparison(0.0, -50.0, 48, 48), "lowest_total_cost")
    assert result.choice == "too_close"
    assert result.tradeoff_note == ("Refinancing lowers your payment by $50.00 a month, "
                                    "and costs the same in total.")


def test_verdict_keep_side_equal_totals_keep_subject():
    result = verdict(_direct_comparison(0.001, 50.0, 48, 48), "lowest_monthly_payment")
    assert result.choice == "keep"
    assert result.tradeoff_note == ("Your payment is $50.00 a month lower, "
                                    "and the total cost is the same.")


def test_verdict_keep_side_and_path_when_keep_payment_lower():
    result = verdict(_direct_comparison(-500.0, 50.0, 48, 48), "lowest_total_cost")
    assert result.choice == "keep"
    assert result.tradeoff_note == ("Your payment is $50.00 a month lower, "
                                    "and you pay $500.00 less in total.")


def test_verdict_keep_note_when_refinance_pays_off_sooner():
    result = verdict(_direct_comparison(-500.0, 20.0, 60, 48), "lowest_total_cost")
    assert result.choice == "keep"
    assert result.tradeoff_note == ("Your payment is $20.00 a month lower, "
                                    "and you pay $500.00 less in total. "
                                    "Your current loan pays off 12 months later.")


def test_verdict_close_call_on_payment_is_refinance():
    result = verdict(_close_call_comparison(), "lowest_monthly_payment")
    assert result.choice == "refinance_now"
    assert result.headline == "Refinancing lowers your payment by $193.95 a month."


def test_verdict_total_margin_boundary_is_strict():
    assert verdict(_direct_comparison(99.99, -50.0), "lowest_total_cost").choice == "too_close"
    assert verdict(_direct_comparison(100.00, -50.0), "lowest_total_cost").choice == "refinance_now"


def test_verdict_total_margin_uses_cents_rounded_value():
    # 99.996 displays as $100.00, so the headline must name a winner, never
    # "too close ... $100.00 apart".
    result = verdict(_direct_comparison(99.996, -50.0), "lowest_total_cost")
    assert result.choice == "refinance_now"
    assert "Too close" not in result.headline
    assert "$100.00" in result.headline


def test_verdict_payment_margin_boundary_is_strict():
    assert verdict(_direct_comparison(500.0, -9.99), "lowest_monthly_payment").choice == "too_close"
    assert verdict(_direct_comparison(500.0, -10.00), "lowest_monthly_payment").choice == "refinance_now"
    assert verdict(_direct_comparison(-500.0, 10.00), "lowest_monthly_payment").choice == "keep"


def test_verdict_unknown_priority_raises():
    with pytest.raises(ValueError):
        verdict(_trap_comparison(), "lowest_payment")
    with pytest.raises(ValueError):
        verdict(_trap_comparison(), "cheapest")


def test_verdict_defaults_to_lowest_total_cost():
    assert verdict(_trap_comparison()).choice == "keep"
