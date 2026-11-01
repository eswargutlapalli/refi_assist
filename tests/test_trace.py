"""Suite for trace.py. Mocked only — no Streamlit, no network, no disk.

The page-3 request trace assembles per-step records into entries plus
totals. app.py only renders; everything asserted here is pure assembly:
entry order, totals math (including the zero-prompt edge), cache labels,
rebuild-on-reconfirm, and the privacy invariants (no prompt/output text
in logs or files, no keys in the trace).
"""

import pytest


def _entry(step, **kw):
    base = {"step": step, "title": step, "summary": "", "detail": None,
            "model": None, "effort": None, "cache_key": None,
            "tokens": {"prompt": 0, "completion": 0, "reasoning": 0,
                       "cached": 0},
            "wall_s": 0.0, "cache_hit": False, "input_key": None}
    base.update(kw)
    return base


def test_entries_keep_step_order():
    trace = pytest.importorskip("trace")
    entries = [_entry("engine"), _entry("extract-loan"), _entry("meaning-check")]
    built = trace.build_trace(entries, current_key="k1")
    assert [e["step"] for e in built["entries"]] == sorted(
        [e["step"] for e in built["entries"]],
        key=trace.STEP_ORDER.index)


def test_totals_count_actual_calls_only():
    trace = pytest.importorskip("trace")
    entries = [
        _entry("extract-loan", model="muse-spark-1.3",
               tokens={"prompt": 100, "completion": 50, "reasoning": 10,
                       "cached": 60},
               wall_s=2.0),
        _entry("meaning-check", model="meta-models/muse-spark-open-1026",
               tokens={"prompt": 200, "completion": 40, "reasoning": 300,
                       "cached": 0},
               wall_s=6.0),
        _entry("engine", wall_s=0.01),
    ]
    totals = trace.build_trace(entries, current_key="k1")["totals"]
    assert totals["calls"] == 2
    assert totals["prompt"] == 300
    assert totals["completion"] == 90
    assert totals["reasoning"] == 310
    assert totals["cached"] == 60
    assert totals["cache_ratio"] == pytest.approx(60 / 300)
    assert totals["wall_s"] == pytest.approx(8.01)


def test_zero_prompt_ratio_is_none_not_crash():
    trace = pytest.importorskip("trace")
    totals = trace.build_trace([_entry("engine", wall_s=0.02)],
                               current_key="k1")["totals"]
    assert totals["calls"] == 0
    assert totals["cache_ratio"] is None


def test_cache_hits_count_with_label():
    trace = pytest.importorskip("trace")
    # The totals are the path cost behind the answer: a cached hit costs
    # no new calls, but it stays in the totals with its label saying so.
    entries = [_entry("extract-loan", cache_hit=True, model="m",
                      tokens={"prompt": 100, "completion": 50,
                              "reasoning": 10, "cached": 60},
                      wall_s=2.0)]
    built = trace.build_trace(entries, current_key="k1")
    assert built["totals"]["calls"] == 1
    assert built["totals"]["prompt"] == 100
    assert len(built["entries"]) == 1
    assert built["entries"][0]["cache_label"] == (
        "from cache, no new calls")


def test_stale_keys_rebuild_downstream():
    trace = pytest.importorskip("trace")
    # Fresh extraction under a new key keeps its entry; everything priced
    # from older inputs drops so the section never shows stale numbers.
    entries = [_entry("extract-loan", input_key="text-v2"),
               _entry("engine", input_key="text-v1"),
               _entry("meaning-check", input_key="text-v1")]
    built = trace.build_trace(entries, current_key="text-v2")
    assert [e["step"] for e in built["entries"]] == ["extract-loan"]


def test_model_entry_sums_calls():
    trace = pytest.importorskip("trace")
    entry = trace.model_entry(
        "extract-loan", "Loan extraction", "2 attempts",
        [{"model": "m", "prompt_tokens": 10, "completion_tokens": 5,
          "reasoning_tokens": 0, "cached_tokens": 6, "elapsed_s": 1.5},
         {"model": "m", "prompt_tokens": 12, "completion_tokens": 6,
          "reasoning_tokens": 0, "cached_tokens": 0, "elapsed_s": 2.5}],
        effort="minimal", cache_key="refi-extract-v1", input_key="t")
    assert entry["tokens"] == {"prompt": 22, "completion": 11,
                               "reasoning": 0, "cached": 6}
    assert entry["wall_s"] == pytest.approx(4.0)
    assert entry["model"] == "m"


def test_key_sets_keep_both_sides():
    trace = pytest.importorskip("trace")
    # Extraction texts and the confirmed-inputs key coexist: neither side
    # drops the other while both are current.
    entries = [_entry("extract-loan", input_key="loan-text"),
               _entry("extract-offer", input_key="offer-text"),
               _entry("explainer", input_key="inputs-key")]
    built = trace.build_trace(entries, {"loan-text", "offer-text",
                                         "inputs-key"})
    assert [e["step"] for e in built["entries"]] == [
        "extract-loan", "extract-offer", "explainer"]


def test_margin_line_states_deciding_comparison():
    trace = pytest.importorskip("trace")
    from engine import CurrentLoan, RefinanceOffer, compare, verdict

    current = CurrentLoan(balance=20000.0, annual_rate=0.09,
                          remaining_months=40)
    offer = RefinanceOffer(annual_rate=0.05, term_months=60)
    result = compare(current, offer)
    decision = verdict(result, "lowest_total_cost")
    line = trace.margin_line(result, decision, "lowest_total_cost")
    assert "$100" in line
    assert "keep" in line or "refinance" in line


def test_trace_redacts_known_keys(monkeypatch, caplog):
    trace = pytest.importorskip("trace")
    import logging

    # A realistic fake key smuggled into a detail must fail closed to the
    # placeholder — never the built trace, never the logs.
    monkeypatch.setenv("MODEL_API_KEY", "sk-fake-XYZ")
    entries = [_entry("extract-loan", cache_key="refi-extract-v1",
                      summary="key sk-fake-XYZ here",
                      detail=["transcript text here",
                              "leaked sk-fake-XYZ there"])]
    with caplog.at_level(logging.INFO):
        built = trace.build_trace(entries, current_key="k1")
    rendered = str(built)
    assert "sk-fake-XYZ" not in rendered
    assert rendered.count("[REDACTED]") == 2
    assert "transcript text here" in rendered
    assert "sk-fake-XYZ" not in caplog.text


def test_build_leaves_caller_entries_untouched():
    trace = pytest.importorskip("trace")
    import copy

    entries = [_entry("extract-loan", cache_hit=True,
                      summary="untouched",
                      detail=["line one"]),
               _entry("engine", summary="plain")]
    frozen = copy.deepcopy(entries)
    trace.build_trace(entries, current_key="k1")
    assert entries == frozen
