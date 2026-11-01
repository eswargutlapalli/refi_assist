"""Suite for the Stage 2 eval harness (eval/record.py, eval/score.py).

Offline except through injected fake clients: recording tests script model
replies, scoring tests replay saved records, so nothing here spends credit
or touches the network (tests/conftest.py blocks sockets).

Hand-built record dicts appear only as scorer unit fixtures, never as
reported numbers: reported metrics always come from record.record_scenario
output, including output produced through fake clients.
"""

import copy
import json
import types
from pathlib import Path

import pytest

record = pytest.importorskip("eval.record")
score = pytest.importorskip("eval.score")

SCENARIOS = Path("eval/scenarios")


def _fake_client(script):
    """Scripted chat client: each create() pops one reply body."""

    def create(**kwargs):
        assert script, "more API calls than scripted"
        message = types.SimpleNamespace(content=script.pop(0), tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=None,
            model="muse-spark-1.3",
        )

    return types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=create)))


def _scenario(sid):
    return json.loads((SCENARIOS / f"{sid}.json").read_text())


def _terms_json(extra_loan=None, extra_offer=None):
    """Scripted extraction replies with natural quotes for clean.json."""
    loan = {
        "balance": {"value": 18500.0,
                    "quote": "Outstanding balance: $18,500.00"},
        "annual_rate_pct": {"value": 9.5,
                            "quote": "Annual percentage rate (APR): 9.5%"},
        "remaining_months": {"value": 48,
                             "quote": "Payments remaining: 48"},
        "prepayment_penalty": {"value": 0.0,
                              "quote": "Prepayment penalty: $0"},
    }
    offer = {
        "annual_rate_pct": {"value": 5.9, "quote": "5.9% APR"},
        "term_months": {"value": 60, "quote": "for 60 months"},
        "fees": {"value": 0.0, "quote": "No origination fees"},
        "fees_financed": {"financed": None, "quote": None},
    }
    loan.update(extra_loan or {})
    offer.update(extra_offer or {})
    return json.dumps(loan), json.dumps(offer)


def _clean_expected():
    """True-terms engine output for clean.json (no model, no network)."""
    from engine import compare, verdict as _verdict
    from eval.record import build_true_loan, build_true_offer
    scenario = _scenario("clean")
    result = compare(build_true_loan(scenario), build_true_offer(scenario))
    return result, _verdict(result, priority=scenario["priority"])


def _record_clean(tmp_path, script, sid="clean"):
    scenario = _scenario(sid)
    fake = _fake_client(script)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rec, calls = record.record_scenario(scenario, fake, run_dir)
    assert calls == len(rec["usage"])
    return rec, run_dir


def test_scenarios_load_with_schema():
    files = sorted(SCENARIOS.glob("*.json"))
    assert len(files) == 13
    for path in files:
        scenario = json.loads(path.read_text())
        assert set(scenario) == {
            "id", "priority", "loan_text", "offer_text",
            "true_loan", "true_offer",
        }, path.name
        assert set(scenario["true_loan"]) == {
            "balance", "annual_rate_pct", "remaining_months",
            "prepayment_penalty",
        }, path.name
        assert set(scenario["true_offer"]) == {
            "annual_rate_pct", "term_months", "fees", "fees_financed",
        }, path.name
        assert scenario["priority"] in (
            "lowest_total_cost", "lowest_monthly_payment",
            "earliest_payoff"), path.name


def test_true_terms_build_engine_objects():
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = json.loads(path.read_text())
        loan = record.build_true_loan(scenario)
        offer = record.build_true_offer(scenario)
        result, decision = record.expected_for(scenario)
        assert result.keep_total > 0
        assert decision.choice in ("keep", "refinance_now", "too_close")


def test_true_terms_reject_missing_required():
    scenario = _scenario("clean")
    scenario["true_loan"]["balance"] = None
    with pytest.raises(ValueError):
        record.build_true_loan(scenario)


def test_record_clean_verified_first_pass(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    rec, _ = _record_clean(tmp_path, [loan_json, offer_json, draft])
    loan_fields = rec["extraction"]["loan"]["fields"]
    assert rec["extraction"]["loan"]["attempts"] == 1
    assert all(f["status"] == "grounded" for f in loan_fields.values())
    assert loan_fields["balance"]["value"] == 18500.0
    offer_fields = rec["extraction"]["offer"]["fields"]
    assert offer_fields["fees_financed"]["status"] == "not_stated"
    expl = rec["explanation"]
    assert expl["kind"] == "verified"
    assert expl["attempts"] == 1
    assert len(expl["drafts"]) == 1
    assert expl["drafts"][0]["ok"] is True
    assert [u["purpose"] for u in rec["usage"]] == [
        "extract_loan", "extract_offer", "explain_draft"]
    for entry in rec["usage"]:
        assert set(entry) == {
            "purpose", "model", "prompt_tokens", "completion_tokens",
            "reasoning_tokens", "cached_tokens",
        }
    assert rec["engine"]["verdict_choice"] == "refinance_now"


def test_record_rewrite_path(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."
    good = f"{decision.headline} {decision.tradeoff_note}"
    rec, _ = _record_clean(tmp_path, [loan_json, offer_json, bad, good])
    expl = rec["explanation"]
    assert expl["kind"] == "rewritten"
    assert expl["attempts"] == 2
    assert [d["ok"] for d in expl["drafts"]] == [False, True]
    assert expl["text"] == good


def test_record_template_on_two_bad_drafts(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    bad = f"{decision.headline} Extra $9,999.99."
    rec, _ = _record_clean(tmp_path, [loan_json, offer_json, bad, bad])
    expl = rec["explanation"]
    assert expl["kind"] == "template"
    assert expl["reason"] == "failed_checks"
    assert len(expl["drafts"]) == 2


def _one_scenario_dir(tmp_path, *sids):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for sid in sids:
        text = (SCENARIOS / "clean.json").read_text()
        if sid != "clean":
            text = text.replace('"id": "clean"', f'"id": "{sid}"')
        (data_dir / f"{sid}.json").write_text(text)
    return data_dir


def test_record_resumable_skips_done(tmp_path):
    data_dir = _one_scenario_dir(tmp_path, "clean")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    done = dict(scenario_id="clean")
    (run_dir / "clean.json").write_text(json.dumps(done))
    stats = record.record_all(
        str(data_dir), str(run_dir), _fake_client([]))
    assert stats["recorded"] == []
    assert stats["skipped"] == ["clean"]
    assert json.loads((run_dir / "clean.json").read_text()) == done


def test_record_cap_stops_before_next(tmp_path):
    data_dir = _one_scenario_dir(tmp_path, "clean", "clean2")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    fake = _fake_client([loan_json, offer_json, draft])
    stats = record.record_all(
        str(data_dir), str(run_dir), fake, cap=3)
    assert stats["recorded"] == ["clean"]
    assert stats["calls"] == 3


def test_scorer_all_correct(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    rec, _ = _record_clean(tmp_path, [loan_json, offer_json, draft])
    scenario = _scenario("clean")
    out = score.score_scenario(rec, scenario)
    # Seven, not eight: clean has $0 fees, so the financed flag is never
    # asked and is not counted as a field.
    assert out["extraction"]["correct"] == 7
    assert out["extraction"]["wrong"] == []
    assert out["extraction"]["needs_fix"] == []
    assert out["confirm_edit_rate"] == 0.0
    assert out["explanation"]["first_pass_ok"] is True
    assert out["explanation"]["recorded_kind"] == "verified"
    assert out["verdict_match"] is True


def test_scorer_cleared_penalty_counts_as_fix(tmp_path):
    scenario = _scenario("percent-penalty")
    loan_reply = {
        "balance": {"value": 14000.0,
                    "quote": "payoff balance $14,000.00"},
        "annual_rate_pct": {"value": 10.5, "quote": "at 10.5% APR"},
        "remaining_months": {"value": 40,
                             "quote": "40 payments remaining"},
        "prepayment_penalty": {
            "value": 2.0,
            "quote": "Early payoff charge: 2% of the remaining balance"},
    }
    offer_reply = {
        "annual_rate_pct": {"value": 7.9, "quote": "7.9% APR"},
        "term_months": {"value": 48, "quote": "for 48 months"},
        "fees": {"value": 0.0, "quote": "No fees"},
        "fees_financed": {"financed": None, "quote": None},
    }
    result, decision = record.expected_for(scenario)
    draft = f"{decision.headline} {decision.tradeoff_note}"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rec, _ = record.record_scenario(
        scenario,
        _fake_client([json.dumps(loan_reply), json.dumps(loan_reply),
                      json.dumps(offer_reply), draft]),
        run_dir,
    )
    assert rec["extraction"]["loan"]["fields"]["prepayment_penalty"][
        "status"] == "cleared"
    out = score.score_scenario(rec, scenario)
    # Quote-only attribution: the rate now grounds from its own quote, so
    # only the percent-form penalty still clears. The $0-fee flag is not
    # counted as a field, leaving seven evaluated.
    assert rec["extraction"]["loan"]["fields"]["annual_rate_pct"][
        "status"] == "grounded"
    assert out["extraction"]["correct"] == 6
    assert out["extraction"]["needs_fix"] == ["loan.prepayment_penalty"]
    assert out["confirm_edit_rate"] == pytest.approx(1 / 7)
    assert decision.choice == "too_close"


def test_scorer_wrong_value_lists_and_flips_verdict(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    rec, _ = _record_clean(tmp_path, [loan_json, offer_json, draft])
    rec["extraction"]["loan"]["fields"] = {
        "balance": {"value": 512.10, "status": "grounded",
                    "quote": "Last payment of $512.10 received Oct 15"},
        "annual_rate_pct": {"value": 11.2, "status": "grounded",
                            "quote": "APR: 11.2% (fixed)"},
        "remaining_months": {"value": 36, "status": "grounded",
                             "quote": "Payments remaining: 36"},
        "prepayment_penalty": {
            "value": 150.0, "status": "grounded",
            "quote": "Prepayment penalty: $150 if"},
    }
    rec["extraction"]["offer"]["fields"] = {
        "annual_rate_pct": {"value": 6.9, "status": "grounded",
                            "quote": "6.9% APR"},
        "term_months": {"value": 48, "status": "grounded",
                        "quote": "over 48 months"},
        "fees": {"value": 0.0, "status": "grounded",
                 "quote": "zero fees"},
        "fees_financed": {"value": None, "status": "not_stated",
                          "quote": None},
    }
    scenario = _scenario("clean")
    scenario["true_loan"] = {
        "balance": 12340.55, "annual_rate_pct": 11.2,
        "remaining_months": 36, "prepayment_penalty": 150.0,
    }
    scenario["true_offer"] = {
        "annual_rate_pct": 6.9, "term_months": 48, "fees": 0.0,
        "fees_financed": None,
    }
    scenario["priority"] = "lowest_total_cost"
    out = score.score_scenario(rec, scenario)
    assert out["extraction"]["wrong"] == ["loan.balance"]
    assert "loan.balance" in out["extraction"]["needs_fix"]
    assert out["extracted_verdict_choice"] == "keep"
    assert out["verdict_match"] is False


def test_scorer_must_choose_flag(tmp_path):
    scenario = _scenario("fees-method-unstated")
    loan_reply = {
        "balance": {"value": 16800.0,
                    "quote": "payoff balance $16,800.00"},
        "annual_rate_pct": {"value": 9.6, "quote": "fixed APR 9.6%"},
        "remaining_months": {"value": 46,
                             "quote": "46 payments remaining"},
        "prepayment_penalty": {"value": 0.0,
                              "quote": "Prepayment penalty: $0"},
    }
    offer_reply = {
        "annual_rate_pct": {"value": 6.4, "quote": "6.4% APR"},
        "term_months": {"value": 60, "quote": "for 60 months"},
        "fees": {"value": 300.0, "quote": "$300 origination fee"},
        "fees_financed": {"financed": None, "quote": None},
    }
    result, decision = record.expected_for(scenario)
    draft = f"{decision.headline} {decision.tradeoff_note}"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rec, _ = record.record_scenario(
        scenario,
        _fake_client([json.dumps(loan_reply), json.dumps(offer_reply),
                      json.dumps(offer_reply), draft]),
        run_dir,
    )
    # Quote-only attribution: the term now grounds from its own quote,
    # leaving only the must-choose flag for the user.
    assert rec["extraction"]["offer"]["fields"]["term_months"][
        "status"] == "grounded"
    out = score.score_scenario(rec, scenario)
    assert out["extraction"]["needs_fix"] == ["offer.fees_financed"]
    assert out["confirm_edit_rate"] == pytest.approx(1 / 8)
    grounded = copy.deepcopy(rec)
    grounded["extraction"]["offer"]["fields"]["fees_financed"] = {
        "value": True, "status": "grounded",
        "quote": "$300 origination fee",
    }
    out2 = score.score_scenario(grounded, scenario)
    assert out2["extraction"]["wrong"] == ["offer.fees_financed"]


def test_scorer_corrupt_draft_fails_recheck(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    rec, _ = _record_clean(tmp_path, [loan_json, offer_json, draft])
    rec["explanation"]["drafts"][0]["text"] += " Plus $1.00."
    out = score.score_scenario(rec, _scenario("clean"))
    assert out["explanation"]["first_pass_ok"] is False


def test_balnum_draft1_feedback_quotes_sentence():
    from engine import compare, verdict as _verdict
    from eval.record import build_true_loan, build_true_offer
    from verify import verify_narrative
    scenario = _scenario("balance-among-numbers")
    result = compare(build_true_loan(scenario), build_true_offer(scenario))
    decision = _verdict(result, priority=scenario["priority"])
    draft1 = (
        "Refinancing lowers your payment by $129.01 a month. "
        "The change from 10.9% to 8.4% saves $526.44, while the longer "
        "payoff costs $712.32 and fees and charges cost $75.00. "
        "Your current loan ends in 34 months while refinancing ends in "
        "48 months. "
        "Keeping your loan costs $260.88 less in total, and refinancing "
        "never stays ahead within the horizon."
    )
    report = verify_narrative(
        draft1, result, decision,
        (scenario["true_loan"]["annual_rate_pct"],
         scenario["true_offer"]["annual_rate_pct"]))
    assert not report.ok and not report.agreement_ok
    assert ("'Keeping your loan costs $260.88 less in total, and "
            "refinancing never stays ahead within the horizon.'"
            in report.feedback)
    assert "State the tradeoff as the note does instead" in report.feedback
    assert "restate this headline" not in report.feedback


def test_report_written_next_to_run(tmp_path):
    loan_json, offer_json = _terms_json()
    result, decision = _clean_expected()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    rec, run_dir = _record_clean(tmp_path, [loan_json, offer_json, draft])
    report = score.score_run(str(SCENARIOS), str(run_dir))
    report_path = run_dir / "REPORT.md"
    assert report_path.read_text() == report
    assert "| clean |" in report
    assert "7/7" in report
    assert "grounded" in report and "verdict" in report.lower()

