"""Suite for app.py helpers. Mocked only — no network, no spend, no Streamlit.

Covers the confirm gate that plan step 3 requires: extraction alone never
computes; compute needs every confirmed field present; percent-to-decimal
conversion lives in code; display carries words, never signs.
"""

import types

import pytest

from engine import compare
import app
from app import (
    build_current_loan,
    build_offer,
    default_from_outcome,
    describe_thresholds_heading,
    describe_wait_result,
    field_caption,
    format_money,
    format_rate_floor,
    format_threshold_rate,
    gate_message,
    gate_status,
    is_fresh_upload,
    missing_required,
    needs_extract,
    split_rows,
    _apply_deploy_secret,
)
from extract import FieldOutcome


def test_build_current_loan_converts_percent():
    loan = build_current_loan(20000.0, 7.5, 36, 0.0)
    assert loan.balance == 20000.0
    assert loan.annual_rate == pytest.approx(0.075)
    assert loan.remaining_months == 36
    assert loan.prepayment_penalty == 0.0


def test_build_current_loan_fails_loudly():
    with pytest.raises(ValueError):
        build_current_loan(-100.0, 7.5, 36, 0.0)


def test_build_offer_passes_financed_flag():
    offer = build_offer(6.5, 48, 250.0, True)
    assert offer.annual_rate == pytest.approx(0.065)
    assert offer.term_months == 48
    assert offer.fees == 250.0
    assert offer.fees_financed is True


def test_format_money_never_shows_signs():
    assert format_money(1225.09) == "$1,225.09"
    assert format_money(-0.0) == "$0.00"
    assert "-" not in format_money(-214.56)


def test_gate_status_needs_only_confirmation():
    assert gate_status(False) == ["confirmation"]
    assert gate_status(True) == []


def test_gate_message_names_confirm_button_not_checkbox():
    message = gate_message()
    assert "Confirm" in message
    assert "checkbox" not in message and "tick" not in message


def test_is_fresh_upload_detects_edited_content():
    import types

    first = types.SimpleNamespace(name="stmt.txt", getvalue=lambda: b"balance $10")
    edited = types.SimpleNamespace(name="stmt.txt", getvalue=lambda: b"balance $20")
    assert is_fresh_upload(first, None) is True
    stored = ("stmt.txt", "x" * 64)
    assert is_fresh_upload(first, stored) is True  # unknown fingerprint: reload
    from app import _upload_fingerprint

    assert is_fresh_upload(first, _upload_fingerprint(first)) is False
    assert is_fresh_upload(edited, _upload_fingerprint(first)) is True
    assert is_fresh_upload(None, _upload_fingerprint(first)) is False


def test_inputs_default_to_blank_not_zero():
    from app import INPUT_DEFAULTS

    blank = (
        "loan_balance", "loan_rate_pct", "loan_months", "loan_penalty",
        "offer_rate_pct", "offer_term", "offer_fees", "fees_choice",
    )
    assert all(INPUT_DEFAULTS[key] is None for key in blank)


def test_missing_required_blocks_none_except_nones():
    from app import INPUT_DEFAULTS

    assert missing_required(dict(INPUT_DEFAULTS)) == [
        "loan.balance", "loan.rate", "loan.remaining_months",
        "offer.rate", "offer.term_months",
    ]


def test_missing_required_flag_only_matters_with_fees():
    from app import INPUT_DEFAULTS

    base = dict(INPUT_DEFAULTS)
    base.update({
        "loan_balance": 68713.23, "loan_rate_pct": 6.29, "loan_months": 45,
        "offer_rate_pct": 5.99, "offer_term": 48,
    })
    assert missing_required(dict(base, loan_penalty=None)) == []
    assert missing_required(dict(base, offer_fees=None, fees_choice=None)) == []
    assert missing_required(dict(base, offer_fees=0.0, fees_choice=None)) == []
    assert missing_required(dict(base, offer_fees=250.0, fees_choice=None)) == [
        "offer.fees_financed"
    ]


def test_missing_required_allows_legitimate_zeros():
    from app import INPUT_DEFAULTS

    ok = dict(INPUT_DEFAULTS)
    ok.update({
        "loan_balance": 30000.0, "loan_rate_pct": 0.0, "loan_months": 43,
        "loan_penalty": 0.0, "offer_rate_pct": 0.0, "offer_term": 48,
        "offer_fees": 0.0, "fees_choice": "Paid upfront",
    })
    assert missing_required(ok) == []  # zero rate/penalty/fees are legitimate


def test_wait_options_stay_below_remaining_months():
    from app import wait_options

    assert wait_options(43) == (3, 6, 9, 12)
    assert wait_options(10) == (3, 6, 9)
    assert wait_options(3) == ()
    assert wait_options(2) == ()


def test_start_over_clears_state():
    from app import INPUT_DEFAULTS, reset_all

    state = {
        "page": 3,
        "loan_text": "words",
        "offer_text": "more words",
        "loan_result": object(),
        "loan_error": "boom",
        "extracted_loan_text": "words",
        "applied_loan_file": ("stmt.txt", "abc"),
        "up_loan_file": object(),
        "inputs": {"loan_balance": 30000.0, "confirmed": True},
        "w_loan_balance": 30000.0,
        "wait_months": 12,
    }
    reset_all(state)
    assert state["page"] == 1
    assert state["loan_text"] == "" and state["offer_text"] == ""
    assert "loan_result" not in state
    assert "loan_error" not in state
    assert "extracted_loan_text" not in state
    assert "applied_loan_file" not in state
    assert "up_loan_file" not in state
    assert "w_loan_balance" not in state
    assert "wait_months" not in state
    assert state["inputs"] == INPUT_DEFAULTS


def test_apply_extraction_stores_months_as_int():
    from extract import ExtractionResult, FieldOutcome
    from app import INPUT_DEFAULTS, LOAN_FIELDS, _apply_extraction

    state = {"inputs": dict(INPUT_DEFAULTS)}
    fields = {
        "balance": FieldOutcome("balance", 20000.0, "balance $20,000", "grounded"),
        "annual_rate_pct": FieldOutcome("annual_rate_pct", 7.5, "APR 7.5%", "grounded"),
        "remaining_months": FieldOutcome("remaining_months", 43.0, "43 payments", "grounded"),
        "prepayment_penalty": FieldOutcome("prepayment_penalty", 0.0, "No penalty", "grounded"),
    }
    _apply_extraction(state, "loan", LOAN_FIELDS, ExtractionResult(fields=fields, attempts=1))
    assert state["inputs"]["loan_months"] == 43
    assert isinstance(state["inputs"]["loan_months"], int)


def test_field_caption_covers_all_three_states():
    from extract import ExtractionResult, FieldOutcome
    from app import field_caption

    grounded = ExtractionResult(fields={
        "balance": FieldOutcome("balance", 20000.0, "balance $20,000", "grounded"),
    }, attempts=1)
    assert field_caption("loan", "balance", grounded) == "from: balance $20,000"
    cleared = ExtractionResult(fields={
        "balance": FieldOutcome("balance", None, "no such term", "cleared"),
    }, attempts=2)
    assert field_caption("loan", "balance", cleared) == "couldn't verify, please enter"
    assert field_caption("loan", "balance", None) == "not in your statement, please enter"
    claimed = ExtractionResult(fields={
        "prepayment_penalty": FieldOutcome(
            "prepayment_penalty", None, "2% of the remaining balance", "cleared"),
    }, attempts=2)
    assert field_caption("loan", "prepayment_penalty", claimed, True) == (
        "couldn't verify, please enter"
    )
    wordless = ExtractionResult(fields={
        "prepayment_penalty": FieldOutcome("prepayment_penalty", None, None, "cleared"),
    }, attempts=2)
    assert field_caption("loan", "prepayment_penalty", wordless, True) == (
        "couldn't verify — leave blank for none"
    )
    assert field_caption("loan", "prepayment_penalty", None, True) == (
        "not in your statement — leave blank for none"
    )
    unstated = ExtractionResult(fields={
        "prepayment_penalty": FieldOutcome(
            "prepayment_penalty", None, None, "not_stated"),
    }, attempts=1)
    assert field_caption("loan", "prepayment_penalty", unstated, True) == (
        "not found in your statement — check it, then leave blank for none"
    )
    assert field_caption("loan", "balance", ExtractionResult(fields={
        "balance": FieldOutcome("balance", None, None, "not_stated"),
    }, attempts=1)) == "not found in your statement, please enter"


def test_missing_required_rejects_nonpositive_structurals():
    from app import INPUT_DEFAULTS

    base = dict(INPUT_DEFAULTS)
    base.update({
        "loan_balance": 30000.0, "loan_rate_pct": 5.0, "loan_months": 43,
        "loan_penalty": 0.0, "offer_rate_pct": 4.5, "offer_term": 48,
        "offer_fees": 0.0, "fees_choice": "Paid upfront",
    })
    zero_balance = dict(base, loan_balance=0.0)
    assert missing_required(zero_balance) == ["loan.balance"]
    zero_term = dict(base, offer_term=0)
    assert missing_required(zero_term) == ["offer.term_months"]


def test_default_from_outcome_uses_grounded_only():
    grounded = FieldOutcome(name="balance", value=20000.0, quote="q", status="grounded")
    cleared = FieldOutcome(name="balance", value=None, quote="q", status="cleared")
    assert default_from_outcome(grounded) == 20000.0
    assert default_from_outcome(cleared) is None


def test_split_rows_use_directional_words():
    loan = build_current_loan(20000.0, 9.0, 40, 0.0)
    offer = build_offer(6.0, 60, 0.0, False)
    result = compare(loan, offer)
    rows = split_rows(result)
    assert rows[0].startswith("Lower rate: saves ")
    assert "$" in rows[0] and "-" not in rows[0]
    assert all("-" not in row for row in rows)
    assert len(rows) == 3


def test_apply_deploy_secret_fills_missing_only(monkeypatch):
    import os
    import types

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    _apply_deploy_secret(types.SimpleNamespace(
        secrets={"MODEL_API_KEY": "s3cr3t"}))
    assert os.environ["MODEL_API_KEY"] == "s3cr3t"
    monkeypatch.setenv("MODEL_API_KEY", "exported")
    _apply_deploy_secret(types.SimpleNamespace(
        secrets={"MODEL_API_KEY": "s3cr3t"}))
    assert os.environ["MODEL_API_KEY"] == "exported"


def test_apply_deploy_secret_tolerates_no_secrets(monkeypatch):
    import types

    class NoSecrets(dict):
        def __getitem__(self, key):
            raise KeyError(key)

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    _apply_deploy_secret(types.SimpleNamespace(secrets=NoSecrets()))  # must not raise
    import os

    assert "MODEL_API_KEY" not in os.environ


def test_format_rate_floor_never_rounds_up():
    assert format_rate_floor(0.051068) == "5.10%"
    assert format_rate_floor(0.045) == "4.50%"
    assert format_rate_floor(0.0) == "0.00%"


def test_stated_but_ungrounded_spots_claims_that_never_grounded():
    from extract import ExtractionResult, FieldOutcome
    from app import stated_but_ungrounded

    assert stated_but_ungrounded("loan", "prepayment_penalty", None) is False
    grounded = ExtractionResult(fields={
        "prepayment_penalty": FieldOutcome("prepayment_penalty", 0.0, "No penalty", "grounded"),
    }, attempts=1)
    assert stated_but_ungrounded("loan", "prepayment_penalty", grounded) is False
    claimed = ExtractionResult(fields={
        "prepayment_penalty": FieldOutcome(
            "prepayment_penalty", None, "2% of the remaining balance", "cleared"),
    }, attempts=2)
    assert stated_but_ungrounded("loan", "prepayment_penalty", claimed) is True
    silent = ExtractionResult(fields={
        "prepayment_penalty": FieldOutcome("prepayment_penalty", None, None, "cleared"),
    }, attempts=2)
    assert stated_but_ungrounded("loan", "prepayment_penalty", silent) is False


def test_missing_required_blank_allowed_only_when_unstated():
    from app import INPUT_DEFAULTS

    base = dict(INPUT_DEFAULTS)
    base.update({
        "loan_balance": 68713.23, "loan_rate_pct": 6.29, "loan_months": 45,
        "offer_rate_pct": 5.99, "offer_term": 48,
    })
    assert missing_required(base) == []  # unstated penalty/fees mean none
    must = {("loan", "prepayment_penalty"), ("offer", "fees")}
    assert missing_required(base, must) == ["loan.prepayment_penalty", "offer.fees"]
    assert missing_required(dict(base, loan_penalty=0.0),
                            {("loan", "prepayment_penalty")}) == []
    assert missing_required(base, {("offer", "fees")}) == ["offer.fees"]


def test_reset_wait_rate_copies_offer_apr():
    from app import reset_wait_rate_to_offer

    state = {
        "w_wait_rate_pct": 1.0,
        "inputs": {"offer_rate_pct": 4.5, "wait_rate_pct": 1.0},
    }
    reset_wait_rate_to_offer(state)
    assert state["w_wait_rate_pct"] == 4.5
    assert state["inputs"]["wait_rate_pct"] == 4.5


def test_edited_note_names_the_statement_value():
    from app import edited_note

    assert edited_note(30000.0, 30000.0) == ""
    assert edited_note(None, None) == ""
    assert edited_note(False, False) == ""
    assert edited_note(250.0, 20000.0, "$") == "edited by you (statement said $20,000.00)"
    assert edited_note(None, 30000.0, "$") == "edited by you (statement said $30,000.00)"
    assert edited_note(6.5, 6.29, "%") == "edited by you (statement said 6.29%)"
    assert edited_note(44, 43) == "edited by you (statement said 43)"
    assert edited_note(True, False) == "edited by you (statement said upfront)"


def test_parse_side_failure_clears_result_and_stores_error():
    import contextlib
    from app import INPUT_DEFAULTS, LOAN_FIELDS, _parse_side

    def boom(text):
        raise ValueError("MODEL_API_KEY is not set")

    class FakePage:
        def __init__(self):
            inputs = dict(INPUT_DEFAULTS)
            inputs["loan_balance"] = 20000.0
            self.session_state = {
                "loan_text": "new words",
                "loan_result": object(),
                "extracted": {"loan_balance": 20000.0},
                "inputs": inputs,
                "w_loan_balance": 20000.0,
            }

        def spinner(self, message):
            return contextlib.nullcontext()

    page = FakePage()
    _parse_side(page, "loan", "loan", LOAN_FIELDS, boom)
    assert page.session_state["loan_result"] is None
    assert "MODEL_API_KEY" in page.session_state["loan_error"]
    assert "loan_balance" not in page.session_state["extracted"]
    assert page.session_state["inputs"]["loan_balance"] is None
    assert "w_loan_balance" not in page.session_state


def test_format_threshold_rate_names_unreachable():
    from app import format_threshold_rate

    assert format_threshold_rate(0.051068) == "below 5.10%"
    assert format_threshold_rate(None) == "unreachable — even 0% can't win"


def test_describe_thresholds_heading_names_baseline_not_offer_rate():
    from engine import wait_thresholds
    from app import describe_thresholds_heading

    loan = build_current_loan(20000.0, 9.0, 40, 0.0)
    offer = build_offer(6.0, 60, 0.0, False)
    assert describe_thresholds_heading(wait_thresholds(loan, offer, [3, 6])) == (
        "To beat refinancing now ($23,199.36 in total), you'd need rates below:"
    )
    trap = build_offer(6.0, 24, 2000.0, False)
    assert describe_thresholds_heading(wait_thresholds(loan, trap, [3, 6])) == (
        "To beat keeping your loan ($23,224.12 in total), you'd need rates below:"
    )


def test_today_column_labels_tied_options():
    from app import today_column_label

    assert today_column_label("equal") == (
        "Today: today's tied options (shown: keeping your loan)"
    )
    assert today_column_label("keep") == "Today: keeping your loan"


def test_describe_wait_result_exact_branches():
    from engine import compare_wait
    from app import describe_wait_result

    loan = build_current_loan(20000.0, 9.0, 40, 0.0)
    save_later = compare_wait(loan, build_offer(6.0, 60, 0.0, False), 6, 0.05)
    assert describe_wait_result(save_later) == (
        "At 5.00%, waiting saves $51.03 in total, but you finish 6 months later."
    )
    save_earlier = compare_wait(
        loan, build_offer(6.0, 24, 2000.0, False), 3, 0.03)
    assert describe_wait_result(save_earlier) == (
        "At 3.00%, waiting saves $193.92 in total, and you finish 13 months earlier."
    )
    cost_later = compare_wait(loan, build_offer(6.0, 60, 0.0, False), 6, 0.12)
    assert describe_wait_result(cost_later) == (
        "At 12.00%, waiting costs $3,464.02 more in total, and you finish 6 months later."
    )


def test_describe_wait_result_singular_month():
    from engine import WaitComparison, compare_wait
    from app import describe_wait_result

    loan = build_current_loan(20000.0, 9.0, 40, 0.0)
    offer = build_offer(6.0, 60, 0.0, False)
    base = compare_wait(loan, offer, 6, 0.05)
    later = WaitComparison(
        plan=base.plan, baseline=base.baseline, baseline_total=base.baseline_total,
        savings_vs_baseline=100.0, breakeven_rate=base.breakeven_rate,
        months_vs_baseline=1,
    )
    assert describe_wait_result(later) == (
        "At 5.00%, waiting saves $100.00 in total, but you finish 1 month later."
    )
    earlier = WaitComparison(
        plan=base.plan, baseline=base.baseline, baseline_total=base.baseline_total,
        savings_vs_baseline=100.0, breakeven_rate=base.breakeven_rate,
        months_vs_baseline=-1,
    )
    assert describe_wait_result(earlier) == (
        "At 5.00%, waiting saves $100.00 in total, and you finish 1 month earlier."
    )


def test_needs_extract_skips_empty_and_unchanged():
    assert needs_extract("", None, None) is False
    assert needs_extract("  ", None, None) is False
    assert needs_extract("Balance $20,000.", None, None) is True
    assert needs_extract("same", "same", object()) is False
    assert needs_extract("new words", "old words", object()) is True


def test_fresh_extraction_resets_fields_that_did_not_ground():
    from extract import ExtractionResult, FieldOutcome
    from app import INPUT_DEFAULTS, LOAN_FIELDS, OFFER_FIELDS, _apply_extraction

    state = {"inputs": dict(INPUT_DEFAULTS)}
    statement_a_loan = {
        "balance": FieldOutcome("balance", 20000.0, "balance $20,000", "grounded"),
        "annual_rate_pct": FieldOutcome("annual_rate_pct", 7.5, "APR 7.5%", "grounded"),
        "remaining_months": FieldOutcome("remaining_months", 36.0, "36 payments", "grounded"),
        "prepayment_penalty": FieldOutcome("prepayment_penalty", 0.0, "No penalty", "grounded"),
    }
    statement_a_offer = {
        "annual_rate_pct": FieldOutcome("annual_rate_pct", 6.5, "APR 6.5%", "grounded"),
        "term_months": FieldOutcome("term_months", 48.0, "48 months", "grounded"),
        "fees": FieldOutcome("fees", 250.0, "$250 fees", "grounded"),
        "fees_financed": FieldOutcome("fees_financed", True, "fees financed", "grounded"),
    }
    _apply_extraction(state, "loan", LOAN_FIELDS, ExtractionResult(fields=statement_a_loan, attempts=1))
    _apply_extraction(state, "offer", OFFER_FIELDS, ExtractionResult(fields=statement_a_offer, attempts=1))
    assert state["inputs"]["loan_balance"] == 20000.0
    assert state["inputs"]["fees_choice"] == "Rolled into the new loan"

    statement_b_loan = dict(statement_a_loan)
    statement_b_loan["balance"] = FieldOutcome("balance", None, "no balance stated", "cleared")
    statement_b_offer = dict(statement_a_offer)
    statement_b_offer["fees_financed"] = FieldOutcome("fees_financed", None, "no word", "cleared")
    _apply_extraction(state, "loan", LOAN_FIELDS, ExtractionResult(fields=statement_b_loan, attempts=2))
    _apply_extraction(state, "offer", OFFER_FIELDS, ExtractionResult(fields=statement_b_offer, attempts=2))
    assert state["inputs"]["loan_balance"] is None
    assert state["inputs"]["fees_choice"] is None
    # Widget keys are deleted, not zeroed: re-creation renders blank.
    assert "w_loan_balance" not in state
    assert "w_offer_fees_financed_choice" not in state


def test_split_rows_same_rate_names_no_difference():
    loan = build_current_loan(20000.0, 6.0, 48, 0.0)
    offer = build_offer(6.0, 48, 0.0, False)
    result = compare(loan, offer)
    assert result.rate_effect == 0
    rows = split_rows(result)
    assert rows[0] == "Same rate: no difference."


def test_escape_display_escapes_dollar_pairs_raw_stays_plain():
    from app import escape_display, format_money

    raw = ("Your payment stays $104.68 a month higher, "
           "but you pay $129.54 less in total.")
    assert escape_display(raw) == (
        "Your payment stays \\$104.68 a month higher, "
        "but you pay \\$129.54 less in total."
    )
    assert raw == ("Your payment stays $104.68 a month higher, "
                   "but you pay $129.54 less in total.")
    assert format_money(104.68) == "$104.68"


def test_wait_option_label_names_months():
    from app import wait_option_label

    assert wait_option_label(6) == "6 months"


def _explain_fixture():
    from engine import compare, verdict
    result = compare(build_current_loan(20000.0, 9.0, 40, 0.0),
                     build_offer(5.0, 60, 0.0, False))
    return result, verdict(result, "lowest_total_cost")


class _ExplainFakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls += 1
        message = types.SimpleNamespace(content=self.script.pop(0),
                                        tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=None, model="muse-spark-1.3")


def test_explanation_key_tracks_confirmed_inputs():
    from app import INPUT_DEFAULTS, explanation_key
    first = explanation_key(dict(INPUT_DEFAULTS))
    changed = dict(INPUT_DEFAULTS)
    changed["loan_balance"] = 1.0
    assert explanation_key(changed) != first
    assert explanation_key(dict(INPUT_DEFAULTS)) == first


def test_get_explanation_caches_per_inputs():
    from app import INPUT_DEFAULTS, explanation_key, get_explanation
    result, decision = _explain_fixture()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    state = {"inputs": dict(INPUT_DEFAULTS)}
    fake = _ExplainFakeClient([draft, draft])
    first = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert first.kind == "verified"
    second = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert second is first
    assert fake.calls == 1
    state["inputs"] = dict(INPUT_DEFAULTS, loan_balance=1.0)
    assert explanation_key(state["inputs"]) != explanation_key(INPUT_DEFAULTS)
    get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert fake.calls == 2


def test_narrative_renders_escaped_but_stores_plain():
    from app import INPUT_DEFAULTS, escape_display, get_explanation
    result, decision = _explain_fixture()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    assert draft.count("$") >= 2
    state = {"inputs": dict(INPUT_DEFAULTS)}
    stored = get_explanation(state, result, decision, (9.0, 5.0),
                             client=_ExplainFakeClient([draft]))
    assert stored.text == draft
    shown = escape_display(stored.text)
    assert shown == draft.replace("$", "\\$")
    assert "\\$" in shown


def test_budget_survives_start_over():
    # The narrator cap is per session like the extraction cap: Start over
    # clears the cached text but never refills the budget.
    from app import INPUT_DEFAULTS, get_explanation, reset_all
    result, decision = _explain_fixture()
    state = {
        "inputs": dict(INPUT_DEFAULTS),
        "loan_text": "words",
        "explanation_calls": 5,
        "explanation": {"key": "old", "result": None},
    }
    reset_all(state)
    fake = _ExplainFakeClient([])
    out = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert (out.kind, out.reason) == ("template", "limit_reached")
    assert decision.headline in out.text
    assert fake.calls == 0


def test_limit_shows_unavailable_status_plus_message():
    from explainer import STATUS_UNAVAILABLE
    from app import (
        EXPLANATION_LIMIT,
        EXPLANATION_LIMIT_MESSAGE,
        INPUT_DEFAULTS,
        get_explanation,
        limit_notice,
        record_explanation,
    )
    assert EXPLANATION_LIMIT == 5
    result, decision = _explain_fixture()
    state = {"inputs": dict(INPUT_DEFAULTS)}
    for _ in range(EXPLANATION_LIMIT):
        record_explanation(state)
    fake = _ExplainFakeClient([])
    out = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert out.status == STATUS_UNAVAILABLE
    assert limit_notice(out) == EXPLANATION_LIMIT_MESSAGE
    assert decision.headline in out.text
    assert fake.calls == 0


def test_unavailable_result_not_cached():
    # A failed model call counts against the budget but leaves nothing
    # cached, so the next render retries instead of replaying the outage.
    from llm import LlmError
    from app import INPUT_DEFAULTS, get_explanation
    result, decision = _explain_fixture()
    good = f"{decision.headline} {decision.tradeoff_note}"

    class _FailOnce:
        def __init__(self):
            self.calls = 0
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise LlmError("boom")
            message = types.SimpleNamespace(content=good, tool_calls=None)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=message)],
                usage=None, model="muse-spark-1.3")

    fake = _FailOnce()
    state = {"inputs": dict(INPUT_DEFAULTS)}
    first = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert (first.kind, first.reason) == ("template", "model_unavailable")
    assert "explanation" not in state
    second = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert (second.kind, second.reason) == ("verified", None)
    third = get_explanation(state, result, decision, (9.0, 5.0), client=fake)
    assert third is second
    assert fake.calls == 2


def test_priority_changes_explanation_key():
    from engine import compare, verdict
    from app import INPUT_DEFAULTS, explanation_key, get_explanation
    assert explanation_key(
        dict(INPUT_DEFAULTS, priority="lowest_total_cost")) != explanation_key(
        dict(INPUT_DEFAULTS, priority="lowest_monthly_payment"))
    result = compare(build_current_loan(20000.0, 9.0, 40, 0.0),
                     build_offer(5.0, 60, 0.0, False))
    first_decision = verdict(result, "lowest_total_cost")
    second_decision = verdict(result, "lowest_monthly_payment")
    fake = _ExplainFakeClient([
        f"{first_decision.headline} {first_decision.tradeoff_note}",
        f"{second_decision.headline} {second_decision.tradeoff_note}",
    ])
    state = {"inputs": dict(INPUT_DEFAULTS, priority="lowest_total_cost")}
    get_explanation(state, result, first_decision, (9.0, 5.0), client=fake)
    state["inputs"] = dict(INPUT_DEFAULTS, priority="lowest_monthly_payment")
    out = get_explanation(state, result, second_decision, (9.0, 5.0),
                          client=fake)
    assert fake.calls == 2
    assert out.kind == "verified"


def test_extraction_cap_counts_ten_calls_then_blocks():
    from app import (EXTRACTION_LIMIT, EXTRACTION_LIMIT_MESSAGE,
                     extraction_blocked, extractions_used, record_extraction)

    assert EXTRACTION_LIMIT == 10
    assert EXTRACTION_LIMIT_MESSAGE == (
        "Demo limit reached for this session; you can still enter "
        "numbers by hand on the next page"
    )
    state: dict = {}
    assert extractions_used(state) == 0
    assert not extraction_blocked(state)
    for _ in range(EXTRACTION_LIMIT):
        record_extraction(state)
    assert extractions_used(state) == EXTRACTION_LIMIT
    assert extraction_blocked(state)


def test_parse_side_skips_action_once_cap_reached():
    from app import (EXTRACTION_LIMIT, INPUT_DEFAULTS, LOAN_FIELDS,
                     _parse_side, record_extraction)

    class _Spinner:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    class _St:
        def __init__(self, state):
            self.session_state = state

        def spinner(self, _msg):
            return _Spinner()

    state = {"loan_text": "Balance $20,000.", "inputs": dict(INPUT_DEFAULTS)}
    for _ in range(EXTRACTION_LIMIT):
        record_extraction(state)
    calls: list = []
    _parse_side(_St(state), "loan", "loan", LOAN_FIELDS,
                lambda text: calls.append(text))
    assert calls == []
