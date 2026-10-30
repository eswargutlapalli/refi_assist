"""Suite for extract.py. Mocked only — no network, no spend.

Covers: quote-in-source + number-in-quote grounding, zero-penalty digit-free
quotes, whole-month rule, one retry then cleared, schema violations, and the
percent-to-decimal handoff to engine.CurrentLoan.
"""

import json
import types

import pytest

import extract
from extract import (
    CurrentLoanTerms,
    ExtractionResult,
    FinancedFlag,
    GroundedValue,
    RefinanceOfferTerms,
    check_field,
    check_flag,
    extract_current_loan,
    extract_refinance_offer,
)

SOURCE = (
    "Statement: current balance $20,000. APR 7.5%. "
    "36 payments remaining. No prepayment penalty."
)


def _terms(balance, balance_q, rate, rate_q, months, months_q, penalty, penalty_q):
    return json.dumps(
        {
            "balance": {"value": balance, "quote": balance_q},
            "annual_rate_pct": {"value": rate, "quote": rate_q},
            "remaining_months": {"value": months, "quote": months_q},
            "prepayment_penalty": {"value": penalty, "quote": penalty_q},
        }
    )


GOOD_TERMS = _terms(
    20000.0, "current balance $20,000",
    7.5, "APR 7.5%",
    36.0, "36 payments remaining",
    0.0, "No prepayment penalty",
)


class _FakeCompletions:
    """Replays response texts; records every create() call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("more API calls than scripted")
        text = self.script.pop(0)
        if isinstance(text, Exception):
            raise text
        message = types.SimpleNamespace(content=text, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=None,
            model="muse-spark-1.3",
        )


class _FakeClient:
    def __init__(self, script):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(script))

    @property
    def calls(self):
        return self.chat.completions.calls


def test_valid_extraction_grounds_all_fields():
    fake = _FakeClient([GOOD_TERMS])
    result = extract_current_loan(SOURCE, client=fake)
    assert isinstance(result, ExtractionResult)
    assert result.attempts == 1
    assert all(f.status == "grounded" for f in result.fields.values())
    loan = result.to_current_loan()
    assert loan.balance == 20000.0
    assert loan.annual_rate == pytest.approx(0.075)
    assert loan.remaining_months == 36
    assert loan.prepayment_penalty == 0.0


def test_quote_not_in_source_retries_then_clears():
    bad = _terms(
        99999.0, "balance $99,999",
        7.5, "APR 7.5%",
        36.0, "36 payments remaining",
        0.0, "No prepayment penalty",
    )
    fake = _FakeClient([bad, bad])
    result = extract_current_loan(SOURCE, client=fake)
    assert len(fake.calls) == 2  # first try plus the one retry
    balance = result.fields["balance"]
    assert balance.status == "cleared" and balance.value is None
    assert result.fields["annual_rate_pct"].status == "grounded"
    with pytest.raises(ValueError, match="balance"):
        result.to_current_loan()


def test_retry_success_grounds_field():
    bad = _terms(
        99999.0, "balance $99,999",
        7.5, "APR 7.5%",
        36.0, "36 payments remaining",
        0.0, "No prepayment penalty",
    )
    fake = _FakeClient([bad, GOOD_TERMS])
    result = extract_current_loan(SOURCE, client=fake)
    assert result.attempts == 2
    assert result.fields["balance"].status == "grounded"
    assert result.fields["balance"].value == 20000.0


def test_number_absent_from_quote_clears():
    # Quote is in the source, but it holds a different number (36, not 7.5).
    mixed = _terms(
        20000.0, "current balance $20,000",
        7.5, "36 payments remaining",
        36.0, "36 payments remaining",
        0.0, "No prepayment penalty",
    )
    fake = _FakeClient([mixed, mixed])
    result = extract_current_loan(SOURCE, client=fake)
    assert result.fields["annual_rate_pct"].status == "cleared"
    assert result.fields["balance"].status == "grounded"


def test_fractional_months_cleared():
    source = "Term: 36.5 months left. Balance $20,000. APR 7.5%. No penalty."
    terms = _terms(
        20000.0, "Balance $20,000",
        7.5, "APR 7.5%",
        36.5, "36.5 months left",
        0.0, "No penalty",
    )
    fake = _FakeClient([terms, terms])
    result = extract_current_loan(source, client=fake)
    assert result.fields["remaining_months"].status == "cleared"


def test_schema_violation_propagates():
    fake = _FakeClient(["not json", "not json"])
    with pytest.raises(extract.LlmError):
        extract_current_loan(SOURCE, client=fake)
    assert len(fake.calls) == 1  # no retry on a broken shape: fail loudly


def test_empty_source_rejected_before_network():
    fake = _FakeClient([GOOD_TERMS])
    with pytest.raises(ValueError):
        extract_current_loan("   ", client=fake)
    assert fake.calls == []


def test_check_field_zero_with_digit_free_quote():
    # "No prepayment penalty" holds no digits: 0.0 still grounds.
    assert check_field(0.0, "No prepayment penalty", SOURCE,
                       field="prepayment_penalty") is True
    assert check_field(50.0, "No prepayment penalty", SOURCE,
                       field="prepayment_penalty") is False


def test_empty_or_blank_quotes_never_ground():
    # "" sits in every string: without this guard a zero would ground thin air.
    assert check_field(0.0, "", SOURCE, field="balance") is False
    assert check_field(0.0, "   ", SOURCE, field="balance") is False
    assert check_field(20000.0, "", SOURCE, field="balance") is False


def test_cents_phrase_suppresses_raw_digits():
    from extract import numbers_in

    # "51 cents" states $0.51: the raw 51 must not validate as $51.
    assert numbers_in("Fee 51 cents") == [0.51]
    assert check_field(51.0, "Fee 51 cents", "Fee 51 cents",
                       field="fees") is False
    assert check_field(0.51, "Fee 51 cents", "Fee 51 cents",
                       field="fees") is True
    assert check_field(51.0, "Fee $51", "Fee $51", field="fees") is True


def test_competing_amount_in_source_clears():
    # Both statements pasted in one box: two rates each attribute to the
    # field, so neither copy is trustworthy — the user must pick.
    source = ("Balance of 68713.23 with rate at 6.29% and remaining 45 months. "
              "Rate 5.99% with 48 months to maturity.")
    assert check_field(5.99, "Rate 5.99%", source, field="annual_rate_pct") is False
    assert check_field(6.29, "rate at 6.29%", source, field="annual_rate_pct") is False
    # Separated, each grounds: the rule only fires on genuine competition.
    assert check_field(6.29, "rate at 6.29%",
                       "Balance of 68713.23 with rate at 6.29%.",
                       field="annual_rate_pct") is True
    assert check_field(5.99, "Rate 5.99%", "Rate 5.99% with 48 months to maturity.",
                       field="annual_rate_pct") is True


def test_digit_before_scale_word_belongs_to_that_amount():
    from extract import numbers_in

    # "30 thousands" states one amount: $30,000. The bare 30 must not validate.
    assert numbers_in("balance 30 thousands") == [30000.0]
    assert numbers_in("balance 30 thousand") == [30000.0]
    assert check_field(30.0, "balance 30 thousands", "balance 30 thousands",
                       field="balance") is False
    assert check_field(30000.0, "balance 30 thousands", "balance 30 thousands",
                       field="balance") is True
    # Regression: digits with no following scale word still count.
    assert check_field(43.0, "43 months", "43 months",
                       whole=True, field="remaining_months") is True


def test_month_fields_require_month_or_payment_word():
    assert check_field(5.0, "5 years", "Term: 5 years",
                       whole=True, field="remaining_months") is False
    assert check_field(60.0, "Term 60 months", "Term 60 months",
                       whole=True, field="term_months") is True
    assert (
        check_field(36.0, "36 payments remaining", "36 payments remaining",
                    whole=True, field="remaining_months") is True
    )


def test_zero_quote_scoped_to_field():
    # Same digit-free quote: grounds the penalty, never a fee.
    assert check_field(0.0, "No penalty", "Balance $5. No penalty.",
                       field="prepayment_penalty") is True
    assert check_field(0.0, "No penalty", "Balance $5. No penalty.",
                       field="fees") is False


def test_offer_zero_fee_without_fee_word_clears():
    source = "Refinance offer: APR 5.9%. Term 60 months. No penalty."
    terms = _offer(
        5.9, "APR 5.9%",
        60.0, "Term 60 months",
        0.0, "No penalty",
        False, "due at signing",
    )
    fake = _FakeClient([terms, terms])
    result = extract_refinance_offer(source, client=fake)
    assert result.fields["fees"].status == "cleared"


def test_bool_value_never_grounds_as_amount():
    assert check_field(True, "1 dollar", "1 dollar", field="fees") is False
    assert check_field(False, "0 dollars", "0 dollars", field="fees") is False


def test_multi_amount_quote_needs_field_word():
    # Two amounts, no rate word: the rate cannot claim this span.
    unattributed = "Balance $20,000, 7.5 for qualified buyers."
    assert check_field(7.5, unattributed, unattributed,
                       field="annual_rate_pct") is False
    # Same shape with attribution grounds.
    attributed = "Balance $20,000, APR 7.5% for qualified buyers."
    assert check_field(7.5, attributed, attributed,
                       field="annual_rate_pct") is True


def test_single_amount_quote_needs_no_keyword():
    assert check_field(20000.0, "$20,000", "Balance $20,000",
                       field="balance") is True


def test_rate_needs_percent_adjacent():
    # "7 years" states no percent: not a rate.
    assert check_field(7.0, "7 years left", "7 years left",
                       field="annual_rate_pct") is False
    assert check_field(7.9, "Rate 7.9% today", "Rate 7.9% today",
                       field="annual_rate_pct") is True


def test_months_rejects_distant_unit():
    # The 3 belongs to "years"; "monthly payments" is four words away.
    quote = "3 years remaining, 36 monthly payments"
    assert check_field(3.0, quote, quote,
                       whole=True, field="remaining_months") is False


def test_crossed_penalty_balance_quotes():
    quote = "balance $17,327, prepayment penalty $200"
    # Each number belongs to its nearer field word; neither crosses.
    assert check_field(17327.0, quote, quote,
                       field="prepayment_penalty") is False
    assert check_field(200.0, quote, quote, field="balance") is False
    assert check_field(17327.0, quote, quote, field="balance") is True
    assert check_field(200.0, quote, quote,
                       field="prepayment_penalty") is True


def test_fee_context_rejects_balance():
    assert check_field(250.0, "$250 in fees", "$250 in fees",
                       field="balance") is False
    assert check_field(250.0, "$250 in fees", "$250 in fees",
                       field="fees") is True


def test_percent_is_not_a_penalty():
    assert check_field(2.0, "2% of the remaining balance",
                       "2% of the remaining balance",
                       field="prepayment_penalty") is False


def test_zero_needs_a_zero_word():
    # "applies" asserts presence: a zero cannot ground here.
    assert check_field(0.0, "A prepayment penalty applies",
                       "A prepayment penalty applies",
                       field="prepayment_penalty") is False
    assert check_field(0.0, "No penalty", "No penalty",
                       field="prepayment_penalty") is True


def test_pronoun_one_is_not_an_amount():
    assert check_field(1.0, "No one told me about a penalty",
                       "No one told me about a penalty",
                       field="prepayment_penalty") is False


def test_flag_negation_flips_polarity():
    quote = "Fees are not financed"
    assert check_flag(True, quote, quote) is False
    assert check_flag(False, quote, quote) is True


def test_flag_negation_within_three_words():
    # Up to three words may stand between the negation and its signal.
    for quote in (
        "fees will not be rolled into the loan",
        "not going to be financed",
        "fees won't be added to the loan",
    ):
        assert check_flag(False, quote, quote) is True
        assert check_flag(True, quote, quote) is False


def test_flag_finance_charge_is_not_financed():
    quote = "Finance charge $1,200"
    assert check_flag(True, quote, quote) is False
    assert check_flag(True, "fees are financed", "fees are financed") is True


def test_digit_sentence_grounds_all_three():
    source = "Offer: $17,327 at 7.9% for 41 months."
    assert check_field(17327.0, "$17,327", source, field="balance") is True
    assert check_field(7.9, "7.9%", source,
                       field="annual_rate_pct") is True
    assert check_field(41.0, "41 months", source,
                       whole=True, field="term_months") is True


def test_rate_grounds_on_rate_word_without_percent():
    assert check_field(7.5, "APR 7.5", "APR 7.5 today",
                       field="annual_rate_pct") is True
    assert check_field(7.5, "rate of 7.5", "rate of 7.5 today",
                       field="annual_rate_pct") is True


def test_window_measured_from_run_edges():
    assert check_field(37.0, "remaining months of thirty seven",
                       "remaining months of thirty seven",
                       whole=True, field="remaining_months") is True
    quote = "thirteen thousand four hundred and fifty one dollars"
    assert check_field(13451.0, quote, quote, field="balance") is True


def test_percent_punctuates_only_what_precedes_it():
    # On the shared sentence the % belongs to 7.5, one slot before 36:
    # proximity must not let the rate claim another field's number.
    quote = "Balance $20,000. APR 7.5%. 36 payments remaining."
    assert check_field(36.0, quote, quote,
                       whole=True, field="annual_rate_pct") is False
    assert check_field(7.5, "APR 7.5%", quote,
                       field="annual_rate_pct") is True
    assert check_field(36.0, "36 payments", quote,
                       whole=True, field="remaining_months") is True


def test_mos_counts_as_months():
    assert check_field(36.0, "36 mos", "36 mos left",
                       whole=True, field="remaining_months") is True


def test_bare_digits_need_dollar_or_word():
    # "$20,000" says dollars; bare "20,000" proves no field.
    assert check_field(20000.0, "$20,000", "Total $20,000",
                       field="balance") is True
    assert check_field(20000.0, "20,000", "Total: 20,000",
                       field="balance") is False
    assert check_field(1.0, "one", "one", field="balance") is False


def test_full_phrase_quote_grounds_each_field():
    quote = "$17,327 at 7.9% for 41 months"
    assert check_field(17327.0, quote, quote, field="balance") is True
    assert check_field(7.9, quote, quote, field="annual_rate_pct") is True
    assert check_field(41.0, quote, quote,
                       whole=True, field="term_months") is True


def test_full_phrase_quote_rejects_swaps():
    quote = "$17,327 at 7.9% for 41 months"
    assert check_field(41.0, quote, quote,
                       whole=True, field="balance") is False
    assert check_field(17327.0, quote, quote, field="term_months") is False


def test_attributed_span_grounds_in_pipeline():
    terms = _offer(
        5.9, "APR 5.9%",
        60.0, "Term 60 months",
        300.0, "Origination fee $300 (was $350)",
        True, "rolled into the new loan",
    )
    source = (
        "Refinance offer: APR 5.9%. Term 60 months. "
        "Origination fee $300 (was $350), rolled into the new loan."
    )
    fake = _FakeClient([terms])
    result = extract_refinance_offer(source, client=fake)
    assert result.fields["fees"].status == "grounded"
    assert result.to_refinance_offer().fees == 300.0


def test_numbers_in_word_forms():
    from extract import numbers_in

    assert numbers_in("thirty seven") == [37]
    assert numbers_in("thirty-seven months") == [37]
    assert numbers_in("one hundred and five") == [105]
    assert numbers_in("fifty cents") == [0.5]
    assert numbers_in("seven percent") == [7]
    assert numbers_in("thirty seven and forty two") == [37, 42]
    assert numbers_in("refinance offer") == []
    # Residual, pinned honestly: lone "one" parses. Quote-in-source plus the
    # confirm gate stay the backstop.
    assert numbers_in("no one here") == [1]


WORDS_SOURCE = (
    "thirteen thousand four hundred and fifty one dollars and 51 cents "
    "with remaining months of thirty seven and an annual interest rate "
    "of 4.79 percentage and no penalty"
)


def test_numbers_in_plural_forms():
    from extract import numbers_in

    assert numbers_in("one thousands two hundreds three tens four ones") == [1234]
    assert numbers_in("four ones") == [4]
    assert numbers_in("two hundreds thirty") == [230]
    assert numbers_in("one months") == [1]
    assert numbers_in("five percent") == [5]


def test_word_form_terms_ground():
    from extract import numbers_in

    assert any(v == pytest.approx(13451.51) for v in numbers_in(WORDS_SOURCE))
    terms = _terms(
        13451.51, "thirteen thousand four hundred and fifty one dollars and 51 cents",
        4.79, "annual interest rate of 4.79 percentage",
        37.0, "remaining months of thirty seven",
        0.0, "no penalty",
    )
    fake = _FakeClient([terms])
    result = extract_current_loan(WORDS_SOURCE, client=fake)
    assert all(f.status == "grounded" for f in result.fields.values())
    loan = result.to_current_loan()
    assert loan.balance == pytest.approx(13451.51)
    assert loan.annual_rate == pytest.approx(0.0479)
    assert loan.remaining_months == 37
    assert loan.prepayment_penalty == 0.0


OFFER_SOURCE = (
    "Refinance offer: APR 5.9%. Term 60 months. Origination fee $300, "
    "rolled into the new loan."
)


def _offer(rate, rate_q, term, term_q, fees, fees_q, fin, fin_q):
    return json.dumps(
        {
            "annual_rate_pct": {"value": rate, "quote": rate_q},
            "term_months": {"value": term, "quote": term_q},
            "fees": {"value": fees, "quote": fees_q},
            "fees_financed": {"financed": fin, "quote": fin_q},
        }
    )


GOOD_OFFER = _offer(
    5.9, "APR 5.9%",
    60.0, "Term 60 months",
    300.0, "Origination fee $300",
    True, "rolled into the new loan",
)


def test_valid_offer_grounds_all_fields():
    fake = _FakeClient([GOOD_OFFER])
    result = extract_refinance_offer(OFFER_SOURCE, client=fake)
    assert result.attempts == 1
    assert all(f.status == "grounded" for f in result.fields.values())
    offer = result.to_refinance_offer()
    assert offer.annual_rate == pytest.approx(0.059)
    assert offer.term_months == 60
    assert offer.fees == 300.0
    assert offer.fees_financed is True


def test_offer_upfront_flag_grounds_false():
    source = (
        "Refinance offer: APR 5.9%. Term 60 months. Origination fee $300, "
        "due at signing."
    )
    terms = _offer(
        5.9, "APR 5.9%",
        60.0, "Term 60 months",
        300.0, "Origination fee $300",
        False, "due at signing",
    )
    fake = _FakeClient([terms])
    result = extract_refinance_offer(source, client=fake)
    assert result.fields["fees_financed"].status == "grounded"
    assert result.to_refinance_offer().fees_financed is False


def test_offer_ambiguous_flag_clears():
    # Quote is in the source but carries neither signal ("fee $300").
    terms = _offer(
        5.9, "APR 5.9%",
        60.0, "Term 60 months",
        300.0, "Origination fee $300",
        True, "Origination fee $300",
    )
    fake = _FakeClient([terms, terms])
    result = extract_refinance_offer(OFFER_SOURCE, client=fake)
    assert result.fields["fees_financed"].status == "cleared"
    with pytest.raises(ValueError, match="fees_financed"):
        result.to_refinance_offer()


def test_offer_bad_numeric_retries_then_clears():
    bad = _offer(
        4.5, "APR 4.5%",
        60.0, "Term 60 months",
        300.0, "Origination fee $300",
        True, "rolled into the new loan",
    )
    fake = _FakeClient([bad, bad])
    result = extract_refinance_offer(OFFER_SOURCE, client=fake)
    assert len(fake.calls) == 2
    assert result.fields["annual_rate_pct"].status == "cleared"


def test_offer_fractional_term_clears():
    source = "Offer: APR 5.9%. Term 60.5 months. Fee $300, due at signing."
    terms = _offer(
        5.9, "APR 5.9%",
        60.5, "60.5 months",
        300.0, "Fee $300",
        False, "due at signing",
    )
    fake = _FakeClient([terms, terms])
    result = extract_refinance_offer(source, client=fake)
    assert result.fields["term_months"].status == "cleared"


def test_check_flag_signals():
    upfront_source = (
        "Refinance offer: APR 5.9%. Term 60 months. Fee $300, due at signing."
    )
    assert check_flag(True, "rolled into the new loan", OFFER_SOURCE) is True
    assert check_flag(False, "due at signing", upfront_source) is True
    # Wrong polarity, both signals, or no signal: all ungrounded.
    assert check_flag(False, "rolled into the new loan", OFFER_SOURCE) is False
    assert check_flag(True, "due at signing", upfront_source) is False
    assert check_flag(True, "Origination fee $300", OFFER_SOURCE) is False
    assert check_flag(True, "a fee invention", OFFER_SOURCE) is False
    both = "Fees rolled into the loan and $300 due at signing."
    assert check_flag(True, both, both) is False
    assert check_flag(False, both, both) is False
