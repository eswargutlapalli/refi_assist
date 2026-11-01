"""Suite for judge.py. Mocked only — no network, no spend.

Covers decision 26: the Baseten claim judge checks meaning only (the
numbers are already proven), with a fixed problem-kind set, fail-closed
parsing, and transport errors that the ladder maps to the honest
template. The 12 live fixtures live in tests/fixtures/judge_drafts.json;
judge.py runs them once live and EVALUATIONS.md reports the counts.
"""

import json
import types
from pathlib import Path

import pytest

from llm import LlmError

FIXTURES = Path(__file__).with_name("fixtures") / "judge_drafts.json"


def _load():
    return json.loads(FIXTURES.read_text())


class _FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("more API calls than scripted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        message = types.SimpleNamespace(content=item, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=None,
            model="meta-models/muse-spark-open-1026",
        )


class _FakeClient:
    def __init__(self, script):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(script))

    @property
    def calls(self):
        return self.chat.completions.calls


def _ctx(fixture):
    return {
        "headline": fixture["headline"],
        "tradeoff_note": fixture["tradeoff_note"],
        "figures": fixture["figures"],
        "draft": fixture["draft"],
    }


def test_fixtures_are_six_clean_six_bad():
    rows = _load()
    assert len(rows) == 12
    clean = [r for r in rows if r["expected_passed"]]
    bad = [r for r in rows if not r["expected_passed"]]
    assert len(clean) == 6 and len(bad) == 6
    kinds = {k for r in bad for k in r["expected_problems"]}
    assert {"softening", "contradiction", "wrong_attribution",
            "advice_beyond_verdict"} <= kinds
    assert all(r["expected_problems"] == [] for r in clean)


def test_problem_kinds_are_fixed():
    judge = pytest.importorskip("judge")
    assert set(judge.JUDGE_PROBLEMS) == {
        "softening", "contradiction", "wrong_attribution",
        "advice_beyond_verdict",
    }


def test_pass_verdict_returns_clean():
    judge = pytest.importorskip("judge")
    rows = _load()
    row = next(r for r in rows if r["id"] == "clean-keep-total")
    fake = _FakeClient(['{"passed": true, "problems": []}'])
    out = judge.judge_draft(_ctx(row), client=fake)
    assert out.passed is True
    assert out.problems == []
    assert len(fake.calls) == 1


def test_problem_verdict_names_kinds():
    judge = pytest.importorskip("judge")
    rows = _load()
    row = next(r for r in rows if r["id"] == "bad-wrong-attribution")
    fake = _FakeClient(
        ['{"passed": false, "problems": ["wrong_attribution"]}'])
    out = judge.judge_draft(_ctx(row), client=fake)
    assert out.passed is False
    assert out.problems == ["wrong_attribution"]


def test_unknown_kind_fails_loudly():
    judge = pytest.importorskip("judge")
    rows = _load()
    row = next(r for r in rows if r["id"] == "clean-keep-total")
    fake = _FakeClient(['{"passed": true, "problems": ["vibes"]}'])
    with pytest.raises(LlmError):
        judge.judge_draft(_ctx(row), client=fake)


def test_transport_error_propagates_for_ladder_fallback():
    judge = pytest.importorskip("judge")
    from llm import LlmTransientError
    rows = _load()
    row = next(r for r in rows if r["id"] == "clean-keep-total")
    fake = _FakeClient([LlmTransientError("LlmTransientError: boom")])
    with pytest.raises(LlmError):
        judge.judge_draft(_ctx(row), client=fake)


def test_judge_prompt_carries_verdict_figures_draft():
    judge = pytest.importorskip("judge")
    rows = _load()
    row = next(r for r in rows if r["id"] == "clean-keep-total")
    messages = judge.build_judge_messages(**_ctx(row))
    prompt = "\n".join(m["content"] for m in messages)
    assert row["headline"] in prompt
    assert row["tradeoff_note"] in prompt
    assert row["draft"] in prompt
    for figure in row["figures"]:
        assert figure in prompt
    for kind in ("softening", "contradiction", "wrong_attribution",
                 "advice_beyond_verdict"):
        assert kind in prompt


def test_judge_usage_sink_records_call():
    judge = pytest.importorskip("judge")
    rows = _load()
    row = next(r for r in rows if r["id"] == "clean-keep-total")
    sink: list = []
    fake = _FakeClient(['{"passed": true, "problems": []}'])
    judge.judge_draft(_ctx(row), client=fake, usage_sink=sink)
    assert len(sink) == 1
