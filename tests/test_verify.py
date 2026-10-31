"""Suite for verify.py. Mocked only — no network, no spend, no Streamlit.

Covers decision 16: every dollar amount and month count in a narrative must
match engine output to the displayed cent; the narrative must agree with the
code-written verdict; rewrite feedback names the numbers that did not match;
the code-written template always passes.
"""

import pytest

from engine import (
    CurrentLoan,
    RefinanceOffer,
    compare,
    compare_wait,
    verdict,
)


def _fixture(priority="lowest_total_cost"):
    # Priced so refinancing wins on total and payment, keep wins on payoff:
    # lowest_total_cost -> refinance_now, earliest_payoff -> keep.
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40,
                          prepayment_penalty=0.0)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60, fees=0.0,
                           fees_financed=False)
    result = compare(current, offer)
    decision = verdict(result, priority)
    return result, decision


def test_clean_narrative_passes():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        f"Cash due today: ${result.cash_due_today:,.2f}."
    )
    report = verify.verify_narrative(text, result, decision)
    assert report.ok


def test_invented_amount_fails_and_feedback_names_it():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Plus a bonus savings of $9,999.99."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "$9,999.99" in report.feedback


def test_cent_display_rounding_passes():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    # Display rounding is allowed: the raw engine value to the shown cent.
    shown = f"${abs(result.total_savings):,.2f}"
    text = f"{decision.headline} {decision.tradeoff_note} Total gap {shown}."
    report = verify.verify_narrative(text, result, decision)
    assert report.ok


def test_opposing_headline_fails_agreement():
    verify = pytest.importorskip("verify")
    result, keep = _fixture("earliest_payoff")
    assert keep.choice == "keep"
    refi = verdict(result, "lowest_total_cost")
    assert refi.choice == "refinance_now"
    text = f"{refi.headline} {keep.tradeoff_note}"
    report = verify.verify_narrative(text, result, keep)
    assert not report.ok
    assert not report.agreement_ok


def test_wrong_breakeven_month_fails():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    assert result.breakeven_month is not None
    wrong = result.breakeven_month + 5
    text = f"{decision.headline} {decision.tradeoff_note} Breakeven: month {wrong}."
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert str(wrong) in report.feedback


def test_breakeven_paraphrase_wrong_fails():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    assert result.breakeven_month is not None
    wrong = result.breakeven_month + 5
    for text in (
        f"{decision.headline} {decision.tradeoff_note} Breakeven month is {wrong}.",
        f"{decision.headline} {decision.tradeoff_note} You break even by month {wrong}.",
    ):
        report = verify.verify_narrative(text, result, decision)
        assert not report.ok, text
        assert str(wrong) in report.feedback


def test_breakeven_paraphrase_right_passes():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    assert result.breakeven_month is not None
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        f"You break even in month {result.breakeven_month}."
    )
    report = verify.verify_narrative(text, result, decision)
    assert report.ok, report.feedback


def test_payoff_verdict_requires_month_gap():
    verify = pytest.importorskip("verify")
    result, decision = _fixture("earliest_payoff")
    assert "months sooner" in decision.headline
    text = f"{decision.headline} {decision.tradeoff_note}"
    report = verify.verify_narrative(text, result, decision)
    assert report.ok


def test_template_always_passes():
    verify = pytest.importorskip("verify")
    for priority in ("lowest_total_cost", "lowest_monthly_payment", "earliest_payoff"):
        result, decision = _fixture(priority)
        text = verify.build_template(result, decision)
        assert decision.headline in text
        report = verify.verify_narrative(text, result, decision)
        assert report.ok, report.feedback


def test_bare_dollar_amount_is_validated():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Plus a bonus savings of $5000."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "$5000" in report.feedback


def test_one_decimal_amount_is_validated():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Plus a bonus savings of $5000.5."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "$5000.5" in report.feedback


def test_bare_engine_amount_passes():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    assert result.cash_due_today == 0.0
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Cash due today: $0."
    )
    report = verify.verify_narrative(text, result, decision)
    assert report.ok, report.feedback


def test_off_by_two_cents_fails():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    off = abs(result.total_savings) + 0.02
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        f"Total gap ${off:,.2f}."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok


def test_apr_mentions_pass_with_rates():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Your 9% APR drops to a 5% offer rate."
    )
    report = verify.verify_narrative(text, result, decision, rates_pct=(9.0, 5.0))
    assert report.ok, report.feedback


def test_scenario_rate_passes_with_rates():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Waiting then refinancing at 4.5% is the scenario."
    )
    report = verify.verify_narrative(
        text, result, decision, rates_pct=(9.0, 5.0, 4.5))
    assert report.ok, report.feedback


def test_invented_rate_fails():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Waiting then refinancing at 3.25% is the scenario."
    )
    report = verify.verify_narrative(
        text, result, decision, rates_pct=(9.0, 5.0))
    assert not report.ok
    assert "3.25%" in report.feedback


def test_apr_without_rates_fails():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Your 9% APR drops to a 5% offer rate."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "9%" in report.feedback


def _wait_compared(wait_months=6, rate=0.045):
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40,
                          prepayment_penalty=0.0)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60, fees=0.0,
                           fees_financed=False)
    return current, offer, compare_wait(current, offer, wait_months, rate)


def test_wait_months_need_context():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "If you wait 6 months, the picture changes."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "6 months" in report.feedback


def test_wait_context_allows_scenario_figures():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    _, _, compared = _wait_compared()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        f"Wait {compared.plan.wait_months} months, then "
        f"${compared.plan.monthly:,.2f} a month, "
        f"${compared.plan.total:,.2f} in total over "
        f"{compared.plan.months_to_payoff} months."
    )
    report = verify.verify_narrative(text, result, decision, wait=compared)
    assert report.ok, report.feedback


def test_wait_wrong_months_fails():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    _, _, compared = _wait_compared()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "If you wait 9 months, the picture changes."
    )
    report = verify.verify_narrative(text, result, decision, wait=compared)
    assert not report.ok
    assert "9 months" in report.feedback


def test_template_passes_breakeven_none_and_too_close():
    verify = pytest.importorskip("verify")
    heavy = (
        CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40,
                    prepayment_penalty=5000.0),
        RefinanceOffer(annual_rate=0.05, term_months=60, fees=5000.0,
                       fees_financed=False),
    )
    tied = (
        CurrentLoan(balance=20000.0, annual_rate=0.06, remaining_months=48,
                    prepayment_penalty=0.0),
        RefinanceOffer(annual_rate=0.06, term_months=48, fees=50.0,
                       fees_financed=False),
    )
    assert compare(*heavy).breakeven_month is None
    for current, offer in (heavy, tied):
        result = compare(current, offer)
        for priority in ("lowest_total_cost", "lowest_monthly_payment",
                         "earliest_payoff"):
            decision = verdict(result, priority)
            text = verify.build_template(result, decision)
            report = verify.verify_narrative(text, result, decision)
            assert report.ok, (priority, report.feedback)


def test_hedging_passes_verification_documents_judge_gap():
    # Known limitation, pinned not fixed: headline-verbatim agreement cannot
    # catch softening ("might consider"). Catching hedging is Stage-3 judge
    # work (claim judge on a separate model), not this slice — no hedge-word
    # list without a decision entry.
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "You might consider refinancing, perhaps, if it feels right."
    )
    report = verify.verify_narrative(text, result, decision)
    assert report.ok


def test_word_amount_fails_named():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "Plus a bonus savings of five thousand dollars."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "five thousand dollars" in report.feedback


def test_word_month_fails_named():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        "You break even in about six months."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert "six months" in report.feedback


def test_feedback_has_no_double_period():
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    off = abs(result.total_savings) + 0.02
    text = (
        f"{decision.headline} {decision.tradeoff_note} "
        f"Total gap ${off:,.2f}."
    )
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
    assert ".." not in report.feedback
    assert f"${off:,.2f}" in report.feedback


def _case_68k():
    # $68,713.23 at 6.29%, 45 months left; offer 5.99% for 48 months,
    # $129.54 fees upfront. cash_due $129.54, term_effect -$554.13,
    # keep_interest $8,601.25 (removed from the allowed set), breakeven None.
    current = CurrentLoan(balance=68713.23, annual_rate=0.0629,
                          remaining_months=45, prepayment_penalty=0.0)
    offer = RefinanceOffer(annual_rate=0.0599, term_months=48, fees=129.54,
                           fees_financed=False)
    result = compare(current, offer)
    decision = verdict(result, "lowest_total_cost")
    assert decision.choice == "keep"
    base = f"{decision.headline} {decision.tradeoff_note} "
    rates = (6.29, 5.99)
    return result, decision, base, rates


def test_case_keep_129_54_passes():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "You keep $129.54, which matters.", result, decision,
        rates_pct=rates)
    assert report.ok, report.feedback


def test_case_month_7_fails_without_breakeven_word():
    # "in month 7" is not a breakeven claim (no breakeven word), so 7 must
    # name a horizon — and this case has none at 7 months.
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "Payment drops in month 7 of the loan.", result, decision,
        rates_pct=rates)
    assert not report.ok
    assert "number not in the results: month 7" in report.feedback


def test_case_years_digits_fails():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "That is 3 years of payments.", result, decision,
        rates_pct=rates)
    assert not report.ok
    assert "number not in the results: 3 years" in report.feedback


def test_case_years_words_fails():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "About three years.", result, decision, rates_pct=rates)
    assert not report.ok
    assert "number not in the results: three years" in report.feedback


def test_case_word_dollars_fails():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "That is three hundred dollars more.", result, decision,
        rates_pct=rates)
    assert not report.ok
    assert "number not in the results: three hundred dollars" in report.feedback


def test_case_hyphen_month_fails():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "A 50-month loan.", result, decision, rates_pct=rates)
    assert not report.ok
    assert "number not in the results: 50-month" in report.feedback


def test_case_bare_percent_fails():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "The 5 percent rate.", result, decision, rates_pct=rates)
    assert not report.ok
    assert "number not in the results: 5 percent" in report.feedback


def test_known_limit_right_number_wrong_meaning_passes():
    # Pinned, not fixed: code ties each number to an allowed value, never
    # to its meaning, so a term amount attributed to saving passes here.
    # Meaning checks are Stage-3 judge work, like the hedging limitation.
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "The lower rate saves $554.13. "
        "It saves 554.13 dollars on term.", result, decision,
        rates_pct=rates)
    assert report.ok, report.feedback


def test_case_removed_interest_fails():
    verify = pytest.importorskip("verify")
    result, decision, base, rates = _case_68k()
    report = verify.verify_narrative(
        base + "Your interest is $8,601.25.", result, decision,
        rates_pct=rates)
    assert not report.ok
    assert "number not in the results: $8,601.25" in report.feedback


def test_too_close_rejects_winner_headline():
    verify = pytest.importorskip("verify")
    current = CurrentLoan(balance=20000.0, annual_rate=0.06, remaining_months=48,
                          prepayment_penalty=0.0)
    offer = RefinanceOffer(annual_rate=0.06, term_months=48, fees=50.0,
                           fees_financed=False)
    result = compare(current, offer)
    decision = verdict(result, "lowest_total_cost")
    assert decision.choice == "too_close"
    text = f"{decision.headline} Refinancing saves you $5,000.00 in total."
    report = verify.verify_narrative(text, result, decision)
    assert not report.ok
