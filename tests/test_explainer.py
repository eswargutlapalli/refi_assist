"""Suite for explainer.py. Mocked only — no network, no spend, no Streamlit.

Covers decision 16 / rule 3.4: the model narrates the code-written verdict,
code verifies every number, one rewrite names the bad numbers, exhaustion
falls back to the code-written template, and the screen status always says
which of the three the user is seeing.
"""

import types

import pytest

from engine import (
    CurrentLoan,
    RefinanceOffer,
    compare,
    verdict,
)


def _fixture(priority="lowest_total_cost"):
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40,
                          prepayment_penalty=0.0)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60, fees=0.0,
                           fees_financed=False)
    result = compare(current, offer)
    return result, verdict(result, priority)


class _FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("more API calls than scripted")
        message = types.SimpleNamespace(content=self.script.pop(0),
                                        tool_calls=None)
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


def test_clean_draft_passes_first_time():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    draft = f"{decision.headline} {decision.tradeoff_note}"
    fake = _FakeClient([draft])
    out = explainer.explain_verdict(result, decision, client=fake)
    assert out.text == draft
    assert out.status == explainer.STATUS_VERIFIED
    assert len(fake.calls) == 1


def test_bad_draft_rewrites_once_with_named_numbers():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."
    good = f"{decision.headline} {decision.tradeoff_note}"
    fake = _FakeClient([bad, good])
    out = explainer.explain_verdict(result, decision, client=fake)
    assert out.text == good
    assert out.status == explainer.STATUS_REWRITTEN
    assert len(fake.calls) == 2
    retry_messages = fake.calls[1]["messages"]
    assert "$9,999.99" in retry_messages[-1]["content"]


def test_two_bad_drafts_fall_back_to_template():
    explainer = pytest.importorskip("explainer")
    verify = pytest.importorskip("verify")
    result, decision = _fixture()
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."
    fake = _FakeClient([bad, bad])
    out = explainer.explain_verdict(result, decision, client=fake)
    assert out.status == explainer.STATUS_TEMPLATE
    assert decision.headline in out.text
    report = verify.verify_narrative(out.text, result, decision)
    assert report.ok, report.feedback


def test_prompt_carries_no_interest_figures():
    # Rule 4: the allowed set is page-3 only, so the prompt must never list
    # interest internals — a cited interest figure could never verify.
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    assert result.keep_interest > 0 and result.refi_interest > 0
    messages = explainer.build_explainer_messages(result, decision)
    prompt = "\n".join(m["content"] for m in messages)
    assert f"${result.keep_interest:,.2f}" not in prompt
    assert f"${result.refi_interest:,.2f}" not in prompt


def test_wait_forwarded_to_both_passes(monkeypatch):
    explainer = pytest.importorskip("explainer")
    verify_mod = pytest.importorskip("verify")
    from engine import compare_wait
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40,
                          prepayment_penalty=0.0)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60, fees=0.0,
                           fees_financed=False)
    result = compare(current, offer)
    decision = verdict(result, "lowest_total_cost")
    compared = compare_wait(current, offer, 6, 0.045)
    rates = (9.0, 5.0, 4.5)
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."
    good = (
        f"{decision.headline} {decision.tradeoff_note} "
        f"Wait 6 months, then ${compared.plan.monthly:,.2f} a month."
    )
    seen = []
    real = verify_mod.verify_narrative

    def spy(text, res, dec, rates_pct=(), wait=None):
        seen.append((rates_pct, wait))
        return real(text, res, dec, rates_pct, wait)

    monkeypatch.setattr(explainer, "verify_narrative", spy)
    fake = _FakeClient([bad, good])
    out = explainer.explain_verdict(result, decision, rates_pct=rates,
                                    wait=compared, client=fake)
    assert out.status == explainer.STATUS_REWRITTEN
    assert out.text == good
    assert len(seen) == 2
    assert seen[0] == seen[1] == (rates, compared)


def test_empty_draft_rewrites(monkeypatch):
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    good = f"{decision.headline} {decision.tradeoff_note}"
    fake = _FakeClient(["", good])
    out = explainer.explain_verdict(result, decision, client=fake)
    assert out.status == explainer.STATUS_REWRITTEN
    assert out.text == good
    assert out.attempts == 2
    assert len(fake.calls) == 2


def test_explainer_call_uses_medium_effort_and_own_key():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    fake = _FakeClient([f"{decision.headline} {decision.tradeoff_note}"])
    explainer.explain_verdict(result, decision, client=fake)
    kwargs = fake.calls[0]
    assert kwargs["reasoning_effort"] == "medium"
    assert kwargs["extra_body"] == {
        "prompt_cache_key": explainer.EXPLAINER_PROMPT_CACHE_KEY
    }
    assert explainer.EXPLAINER_PROMPT_CACHE_KEY != "refi-assistant-v1"


def test_model_error_falls_back_to_template():
    explainer = pytest.importorskip("explainer")
    verify_mod = pytest.importorskip("verify")
    from llm import LlmError
    result, decision = _fixture()

    class _Boom:
        chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=lambda **kwargs: (_ for _ in ()).throw(
                    LlmError("boom"))))

    out = explainer.explain_verdict(result, decision, client=_Boom())
    assert out.status == explainer.STATUS_UNAVAILABLE
    assert out.status.startswith("Code-written")
    assert decision.headline in out.text
    report = verify_mod.verify_narrative(out.text, result, decision)
    assert report.ok, report.feedback


def test_model_error_on_rewrite_falls_back_to_template():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    from llm import LlmError
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."

    class _FailSecond:
        def __init__(self):
            self.calls = 0
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                message = types.SimpleNamespace(content=bad, tool_calls=None)
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message=message)],
                    usage=None, model="muse-spark-1.3")
            raise LlmError("boom")

    fake = _FailSecond()
    out = explainer.explain_verdict(result, decision, client=fake)
    assert out.status == explainer.STATUS_UNAVAILABLE
    assert decision.headline in out.text
    assert fake.calls == 2


def test_prompt_uses_split_rows_wording():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    messages = explainer.build_explainer_messages(result, decision)
    prompt = "\n".join(m["content"] for m in messages)
    assert "Lower rate: saves $" in prompt
    assert "Longer term: costs $" in prompt
    assert "Rate effect:" not in prompt
    assert "Term effect:" not in prompt
    assert "Costs effect:" not in prompt


def test_prompt_states_differences_payoff_and_breakeven_none():
    explainer = pytest.importorskip("explainer")
    current = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40,
                          prepayment_penalty=5000.0)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60, fees=5000.0,
                           fees_financed=False)
    result = compare(current, offer)
    assert result.breakeven_month is None
    decision = verdict(result, "lowest_total_cost")
    messages = explainer.build_explainer_messages(result, decision)
    prompt = "\n".join(m["content"] for m in messages)
    assert "40 months" in prompt and "60 months" in prompt
    assert "Breakeven: refinancing never stays ahead" in prompt
    assert "Total difference:" in prompt
    assert "Payment difference:" in prompt


def test_verified_kind_has_no_reason():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    fake = _FakeClient([f"{decision.headline} {decision.tradeoff_note}"])
    out = explainer.explain_verdict(result, decision, client=fake)
    assert (out.kind, out.reason) == ("verified", None)
    assert out.status == explainer.STATUS_VERIFIED


def test_rewritten_kind_has_no_reason():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."
    good = f"{decision.headline} {decision.tradeoff_note}"
    out = explainer.explain_verdict(result, decision,
                                    client=_FakeClient([bad, good]))
    assert (out.kind, out.reason) == ("rewritten", None)
    assert out.status == explainer.STATUS_REWRITTEN


def test_template_kind_names_failed_checks():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    bad = f"{decision.headline} {decision.tradeoff_note} Bonus $9,999.99."
    out = explainer.explain_verdict(result, decision,
                                    client=_FakeClient([bad, bad]))
    assert (out.kind, out.reason) == ("template", "failed_checks")
    assert out.status == explainer.STATUS_TEMPLATE


def test_template_kind_names_model_unavailable():
    explainer = pytest.importorskip("explainer")
    from llm import LlmError
    result, decision = _fixture()

    class _Boom:
        chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=lambda **kwargs: (_ for _ in ()).throw(
                    LlmError("boom"))))

    out = explainer.explain_verdict(result, decision, client=_Boom())
    assert (out.kind, out.reason) == ("template", "model_unavailable")
    assert out.status == explainer.STATUS_UNAVAILABLE


def test_display_text_comes_from_kind_and_reason():
    explainer = pytest.importorskip("explainer")
    assert explainer.display_status("verified", None) == explainer.STATUS_VERIFIED
    assert explainer.display_status("rewritten", None) == explainer.STATUS_REWRITTEN
    assert explainer.display_status("template", "failed_checks") == explainer.STATUS_TEMPLATE
    assert explainer.display_status("template", "model_unavailable") == explainer.STATUS_UNAVAILABLE


def test_prompt_asks_short_headline_first_shape():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    messages = explainer.build_explainer_messages(result, decision)
    system = messages[0]["content"]
    assert "3-5 sentences" in system
    assert "starting with the headline" in system


def test_prompt_carries_headline_rates_and_no_interest():
    explainer = pytest.importorskip("explainer")
    result, decision = _fixture()
    messages = explainer.build_explainer_messages(
        result, decision, rates_pct=(9.0, 5.0))
    prompt = "\n".join(m["content"] for m in messages)
    assert decision.headline in prompt
    assert decision.tradeoff_note in prompt
    assert "9.0" in prompt and "5.0" in prompt
    assert f"${result.keep_interest:,.2f}" not in prompt
    assert f"${result.refi_interest:,.2f}" not in prompt
    assert "$9,999.99" not in prompt
