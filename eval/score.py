"""eval/score.py — offline scoring of recorded runs (Stage 2).

Why this file exists: the same checks that gate the live flow run here over
saved runs, producing the framework metrics. No model calls, no network:
expected values are recomputed from the true terms with engine.py, drafts
are rechecked with verify.py, and grounding is re-decided with extract.py.
Kind-only feedback is structural — failure kinds and field names, never
expected values.

Hand-written records are scorer unit-test fixtures only, never reported
numbers: score_run reads a run folder written by eval/record.py.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from engine import compare, verdict
from eval import record as record_mod
from extract import check_field, check_flag
from verify import verify_narrative

MONEY_FIELDS = ("balance", "prepayment_penalty", "fees")
MONTH_FIELDS = ("remaining_months", "term_months")


def flag_counts(scenario: dict[str, Any]) -> bool:
    """The financed flag is a field only when the true fees are above zero:
    with $0 fees the app never asks, so there is nothing to score."""
    fees = scenario["true_offer"]["fees"]
    return fees is not None and fees != 0


def values_equal(field: str, first: Any, second: Any) -> bool:
    """Truth comparison per field: cents for money, exact months, a tight
    tolerance for rates, identity for the financed flag."""
    if field in MONEY_FIELDS:
        return abs(float(first) - float(second)) < 0.005
    if field in MONTH_FIELDS:
        return int(first) == int(second)
    if field == "annual_rate_pct":
        return abs(float(first) - float(second)) < 1e-6
    return bool(first) == bool(second)


def must_choose(scenario: dict[str, Any]) -> bool:
    """Fees are stated but the method is not: the flag is a field the user
    must choose at confirm, so an ungrounded flag counts as missing and a
    grounded one counts as wrong (any claim is a guess)."""
    fees = scenario["true_offer"]["fees"]
    return (fees is not None and fees != 0
            and scenario["true_offer"]["fees_financed"] is None)


def classify(side: str, field: str, truth: Any, status: str, value: Any,
             scenario: dict[str, Any]) -> tuple[str, str]:
    """One field against the truth: correct, wrong, or needs_fix (wrong,
    cleared, or missing — everything a user would have to fix at confirm).
    Returns the category plus a short note naming the failure kind only."""
    label = f"{side}.{field}"
    _ = label
    if status == "grounded":
        if value is None:
            return "needs_fix", "grounded with no value"
        if truth is None:
            if field == "fees_financed" and must_choose(scenario):
                return "wrong", "must-choose flag grounded either way"
            return "wrong", "grounded where truth is unstated"
        if values_equal(field, value, truth):
            return "correct", ""
        return "wrong", "grounded but not equal to the truth"
    if status == "cleared":
        return "needs_fix", "cleared for the user to enter"
    if status == "not_stated":
        if truth is None and not (
                field == "fees_financed" and must_choose(scenario)):
            return "correct", ""
        return "needs_fix", "missing"
    return "needs_fix", f"unexpected status {status!r}"


def recheck_grounding(field: str, status: str, value: Any,
                      quote: Any, text: str) -> bool | None:
    """Re-run the live grounding check offline. Non-grounded fields have
    nothing to recheck (None); a grounded field the check now rejects is a
    live-vs-offline discrepancy worth listing."""
    if status != "grounded":
        return None
    if field == "fees_financed":
        return check_flag(value, quote, text)
    kwargs = {"field": field,
              "whole": field in MONTH_FIELDS} if field in MONTH_FIELDS else {
                  "field": field}
    return check_field(value, quote, text, **kwargs)


def score_extraction(record: dict[str, Any],
                     scenario: dict[str, Any]) -> dict[str, Any]:
    """Per-field scoring against the truth, both sides."""
    fields: dict[str, Any] = {}
    wrong: list[str] = []
    needs_fix: list[str] = []
    mismatches: list[str] = []
    correct = 0
    for side, key, text_key in (("loan", "true_loan", "loan_text"),
                                ("offer", "true_offer", "offer_text")):
        stored = record["extraction"][side]["fields"]
        for field, truth in scenario[key].items():
            if (side, field) == ("offer", "fees_financed") and not flag_counts(
                    scenario):
                continue
            label = f"{side}.{field}"
            entry = stored[field]
            category, note = classify(
                side, field, truth, entry["status"], entry["value"],
                scenario)
            rechecked = recheck_grounding(
                field, entry["status"], entry["value"], entry["quote"],
                scenario[text_key])
            if rechecked is False:
                mismatches.append(label)
            fields[label] = {"truth": truth, "status": entry["status"],
                             "value": entry["value"], "category": category,
                             "note": note, "recheck": rechecked}
            if category == "correct":
                correct += 1
            if category == "wrong":
                wrong.append(label)
            if category == "needs_fix" or category == "wrong":
                if label not in needs_fix:
                    needs_fix.append(label)
    return {"fields": fields, "correct": correct, "wrong": wrong,
            "needs_fix": needs_fix, "recheck_mismatches": mismatches,
            "evaluated": len(fields)}


def score_explanation(record: dict[str, Any],
                      scenario: dict[str, Any]) -> dict[str, Any]:
    """Recheck each stored draft against engine output recomputed from the
    true terms. The first draft decides the first-pass rate; the recorded
    kind must agree with what the drafts show."""
    loan = record_mod.build_true_loan(scenario)
    offer = record_mod.build_true_offer(scenario)
    result = compare(loan, offer)
    decision = verdict(result, priority=scenario["priority"])
    rates = tuple(record["rates_pct"])
    drafts = [verify_narrative(draft["text"], result, decision, rates).ok
              for draft in record["explanation"]["drafts"]]
    if not drafts:
        inferred = "template"
    elif drafts == [True]:
        inferred = "verified"
    elif drafts == [False, True]:
        inferred = "rewritten"
    else:
        inferred = "template"
    return {"first_pass_ok": bool(drafts) and drafts[0],
            "recorded_kind": record["explanation"]["kind"],
            "recorded_reason": record["explanation"]["reason"],
            "drafts_recheck": drafts,
            "kind_match": inferred == record["explanation"]["kind"]}


def verdict_from_extracted(record: dict[str, Any],
                           scenario: dict[str, Any]) -> str:
    """The verdict the extracted terms alone would produce: grounded values
    stand (even wrong ones — that is the danger being measured), true terms
    fill only the fields extraction left empty, the best case the confirm
    gate allows. A mismatch means an extraction error changed the verdict."""
    loan: dict[str, Any] = {}
    for field, truth in scenario["true_loan"].items():
        entry = record["extraction"]["loan"]["fields"][field]
        loan[field] = (entry["value"] if entry["status"] == "grounded"
                       and entry["value"] is not None else truth)
    offer: dict[str, Any] = {}
    for field, truth in scenario["true_offer"].items():
        entry = record["extraction"]["offer"]["fields"][field]
        offer[field] = (entry["value"] if entry["status"] == "grounded"
                        and entry["value"] is not None else truth)
    result = compare(
        record_mod.build_true_loan(
            {"id": scenario["id"], "true_loan": {
                "balance": loan["balance"],
                "annual_rate_pct": loan["annual_rate_pct"],
                "remaining_months": loan["remaining_months"],
                "prepayment_penalty": loan["prepayment_penalty"] or 0.0}}),
        record_mod.build_true_offer(
            {"id": scenario["id"], "true_offer": {
                "annual_rate_pct": offer["annual_rate_pct"],
                "term_months": offer["term_months"],
                "fees": offer["fees"] or 0.0,
                "fees_financed": bool(offer["fees_financed"])}}),
    )
    return verdict(result, priority=scenario["priority"]).choice


def _usage_sums(record: dict[str, Any]) -> dict[str, int]:
    sums = {"prompt_tokens": 0, "completion_tokens": 0,
            "reasoning_tokens": 0, "cached_tokens": 0}
    for entry in record["usage"]:
        for key in sums:
            sums[key] += int(entry.get(key, 0) or 0)
    return sums


def score_scenario(record: dict[str, Any],
                   scenario: dict[str, Any]) -> dict[str, Any]:
    """Full scoring for one recorded run."""
    extraction = score_extraction(record, scenario)
    explanation = score_explanation(record, scenario)
    true_choice = record["engine"]["verdict_choice"]
    extracted_choice = verdict_from_extracted(record, scenario)
    return {
        "id": record["id"],
        "priority": scenario["priority"],
        "extraction": extraction,
        "confirm_edit_rate": (len(extraction["needs_fix"])
                              / extraction["evaluated"]),
        "explanation": explanation,
        "true_verdict_choice": true_choice,
        "extracted_verdict_choice": extracted_choice,
        "verdict_match": extracted_choice == true_choice,
        "usage": _usage_sums(record),
    }


def _stated_count(scenario: dict[str, Any]) -> int:
    count = sum(1 for side in ("true_loan", "true_offer")
                for field, truth in scenario[side].items()
                if truth is not None)
    if must_choose(scenario):
        count += 1
    return count


def score_run(data_dir: str | Path, run_dir: str | Path) -> str:
    """Score every record in a run folder and write REPORT.md next to it.
    Returns the report markdown."""
    run_path = Path(run_dir)
    scenarios = {path.stem: record_mod.load_scenario(path)
                 for path in sorted(Path(data_dir).glob("*.json"))}
    scored = []
    for path in sorted(run_path.glob("*.json")):
        if path.name == "REPORT.md":
            continue
        record = json.loads(path.read_text())
        if record["id"] not in scenarios:
            raise ValueError(
                f"{path.name}: no scenario {record['id']!r} in {data_dir}")
        scored.append(score_scenario(record, scenarios[record["id"]]))

    total_correct = sum(s["extraction"]["correct"] for s in scored)
    total_stated = sum(_stated_count(scenarios[s["id"]]) for s in scored)
    total_wrong = sum(len(s["extraction"]["wrong"]) for s in scored)
    total_fix = sum(len(s["extraction"]["needs_fix"]) for s in scored)
    evaluated = sum(s["extraction"]["evaluated"] for s in scored)
    kinds: dict[str, int] = {}
    for scored_one in scored:
        key = (f"{scored_one['explanation']['recorded_kind']}/"
               f"{scored_one['explanation']['recorded_reason'] or '-'}")
        kinds[key] = kinds.get(key, 0) + 1
    flips = [s["id"] for s in scored if not s["verdict_match"]]
    cached = sum(s["usage"]["cached_tokens"] for s in scored)
    prompt = sum(s["usage"]["prompt_tokens"] for s in scored)

    lines = ["# Eval report", ""]
    lines.append(
        "| scenario | priority | verdict | correct | wrong | needs_fix | "
        "explain | verdict_ok |")
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in scored:
        ext = s["extraction"]
        lines.append(
            f"| {s['id']} | {s['priority']} | {s['true_verdict_choice']} | "
            f"{ext['correct']}/{ext['evaluated']} | "
            f"{', '.join(ext['wrong']) or '—'} | "
            f"{', '.join(ext['needs_fix']) or '—'} | "
            f"{s['explanation']['recorded_kind']} | "
            f"{'yes' if s['verdict_match'] else 'NO (' + s['extracted_verdict_choice'] + ')'} |")
    lines += ["", "## Summary", ""]
    stated_rate = (total_correct / total_stated) if total_stated else 0.0
    lines.append(
        f"- grounded and correct / stated fields: "
        f"{total_correct}/{total_stated} ({stated_rate:.1%})")
    lines.append(
        f"- wrong-value rate: {total_wrong}/{evaluated} "
        f"({(total_wrong / evaluated if evaluated else 0.0):.1%}), "
        f"target zero")
    for s in scored:
        for label in s["extraction"]["wrong"]:
            fields = s["extraction"]["fields"][label]
            lines.append(
                f"  - {s['id']} {label}: extracted {fields['value']!r}, "
                f"{fields['note']}")
    lines.append(
        f"- confirmation-edit rate: {total_fix}/{evaluated} "
        f"({(total_fix / evaluated if evaluated else 0.0):.1%})")
    lines.append(
        "- explanation outcomes: " +
        ", ".join(f"{kind} ×{count}" for kind, count in sorted(kinds.items())))
    lines.append(
        f"- verdict flips (extracted vs true): "
        f"{len(flips)} {flips if flips else ''}".rstrip())
    cache_rate = (cached / prompt) if prompt else 0.0
    lines.append(
        f"- cached tokens / prompt tokens: {cached}/{prompt} "
        f"({cache_rate:.1%})")
    report = "\n".join(lines) + "\n"
    (run_path / "REPORT.md").write_text(report)
    return report


def main(argv: list[str] | None = None) -> str:
    """CLI: python3 eval/score.py --data eval/scenarios --run-dir eval/runs/dev-01."""
    parser = argparse.ArgumentParser(
        description="Score a recorded run offline; write REPORT.md.")
    parser.add_argument("--data", required=True, help="scenario dir")
    parser.add_argument("--run-dir", required=True, help="recorded run folder")
    args = parser.parse_args(argv)
    report = score_run(args.data, args.run_dir)
    print(report)
    return report


if __name__ == "__main__":
    main()
