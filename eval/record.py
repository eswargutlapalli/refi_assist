"""eval/record.py — record live runs over scenario files (Stage 2).

Why this file exists: reported eval numbers always come from recorded model
replies, never hand-written fixtures. For each scenario this script runs the
same live calls the app makes — both extractions plus the explainer ladder
on the TRUE terms (what a user would confirm) — and saves every reply with
its usage dump into a run folder. Scoring (eval/score.py) replays that
folder offline, spending no credit.

No recorder lives in the app: the app never writes user input to disk.
Recording happens here, over scenario files only. Both this script and
score.py take --data <path>; the held-out set lives outside the repo and
is never opened during development.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from engine import (
    Comparison,
    CurrentLoan,
    RefinanceOffer,
    Verdict,
    compare,
    verdict,
)
from explainer import explain_verdict
from extract import (
    extract_current_loan,
    extract_refinance_offer,
)

REQUIRED_LOAN_FIELDS = ("balance", "annual_rate_pct", "remaining_months")
REQUIRED_OFFER_FIELDS = ("annual_rate_pct", "term_months")

PRIORITIES = ("lowest_total_cost", "lowest_monthly_payment", "earliest_payoff")


def load_scenario(path: str | Path) -> dict[str, Any]:
    """One scenario file: texts, true terms (None for unstated), priority."""
    with open(path) as handle:
        scenario = json.load(handle)
    if scenario["priority"] not in PRIORITIES:
        raise ValueError(
            f"{path}: unknown priority {scenario['priority']!r}")
    return scenario


def load_scenarios(data_dir: str | Path) -> list[dict[str, Any]]:
    """All scenarios in a dir, sorted by filename for stable run order."""
    return [load_scenario(path)
            for path in sorted(Path(data_dir).glob("*.json"))]


def _require(scenario_id: str, side: str, terms: dict[str, Any],
             names: tuple[str, ...]) -> None:
    missing = [name for name in names if terms.get(name) is None]
    if missing:
        raise ValueError(
            f"scenario {scenario_id}: {side} terms missing {missing}; "
            "record the true value before spending model calls")


def build_true_loan(scenario: dict[str, Any]) -> CurrentLoan:
    """True loan terms to engine terms. Blank penalty means none — the same
    confirm-gate rule the app applies (decision 14: unstated means none)."""
    terms = scenario["true_loan"]
    _require(scenario["id"], "loan", terms, REQUIRED_LOAN_FIELDS)
    return CurrentLoan(
        balance=terms["balance"],
        annual_rate=terms["annual_rate_pct"] / 100,
        remaining_months=int(terms["remaining_months"]),
        prepayment_penalty=terms["prepayment_penalty"] or 0.0,
    )


def build_true_offer(scenario: dict[str, Any]) -> RefinanceOffer:
    """True offer terms to engine terms. Blank fees mean none; a blank flag
    means upfront — the same confirm-gate reading the app applies."""
    terms = scenario["true_offer"]
    _require(scenario["id"], "offer", terms, REQUIRED_OFFER_FIELDS)
    return RefinanceOffer(
        annual_rate=terms["annual_rate_pct"] / 100,
        term_months=int(terms["term_months"]),
        fees=terms["fees"] or 0.0,
        fees_financed=bool(terms["fees_financed"]),
    )


def expected_for(scenario: dict[str, Any]) -> tuple[Comparison, Verdict]:
    """Engine output recomputed from the true terms — the expected values,
    never stored in the scenario file."""
    result = compare(build_true_loan(scenario), build_true_offer(scenario))
    return result, verdict(result, priority=scenario["priority"])


def _fields_dict(outcome: Any) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": field.value, "quote": field.quote,
               "status": field.status}
        for name, field in outcome.fields.items()
    }


def _engine_summary(result: Comparison, decision: Verdict) -> dict[str, Any]:
    return {
        "keep_monthly": result.keep_monthly,
        "keep_total": result.keep_total,
        "refi_monthly": result.refi_monthly,
        "refi_total": result.refi_total,
        "total_savings": result.total_savings,
        "monthly_change": result.monthly_change,
        "rate_effect": result.rate_effect,
        "term_effect": result.term_effect,
        "costs_effect": result.costs_effect,
        "months_to_payoff_keep": result.months_to_payoff_keep,
        "months_to_payoff_refi": result.months_to_payoff_refi,
        "breakeven_month": result.breakeven_month,
        "verdict_choice": decision.choice,
        "headline": decision.headline,
        "tradeoff_note": decision.tradeoff_note,
    }


def record_scenario(scenario: dict[str, Any], client: Any,
                    run_dir: str | Path) -> tuple[dict[str, Any], int]:
    """Run the live chain for one scenario and save its record.

    Extraction runs on the pasted texts; the explainer runs on the TRUE
    terms, so explanation quality is scored separately from extraction
    accuracy. Every model reply lands in the record with its usage dump.
    Returns the record and the model-call count.
    """
    # True terms first: a broken fixture fails loudly before any call
    # is spent on it.
    result, decision = expected_for(scenario)
    rates_pct = (scenario["true_loan"]["annual_rate_pct"],
                 scenario["true_offer"]["annual_rate_pct"])

    usage: list[dict[str, Any]] = []

    def label_new(purpose: str, retry_purpose: str, before: int) -> None:
        for entry in usage[before:]:
            entry["purpose"] = purpose
            purpose = retry_purpose

    before = len(usage)
    loan_sink: list[dict[str, Any]] = []
    loan_outcome = extract_current_loan(
        scenario["loan_text"], client=client, usage_sink=loan_sink)
    usage.extend(loan_sink)
    label_new("extract_loan", "extract_loan_retry", before)

    before = len(usage)
    offer_sink: list[dict[str, Any]] = []
    offer_outcome = extract_refinance_offer(
        scenario["offer_text"], client=client, usage_sink=offer_sink)
    usage.extend(offer_sink)
    label_new("extract_offer", "extract_offer_retry", before)

    drafts: list[dict[str, Any]] = []

    def on_draft(attempt: int, text: str, report: Any,
                 call_usage: dict[str, Any]) -> None:
        drafts.append({"text": text, "ok": report.ok})
        purpose = ("explain_draft" if attempt == 1 else "explain_rewrite")
        usage.append({"purpose": purpose, **call_usage})

    explained = explain_verdict(
        result, decision, tuple(rates_pct), client=client, on_draft=on_draft)

    record = {
        "id": scenario["id"],
        "priority": scenario["priority"],
        "loan_text": scenario["loan_text"],
        "offer_text": scenario["offer_text"],
        "true_loan": scenario["true_loan"],
        "true_offer": scenario["true_offer"],
        "rates_pct": list(rates_pct),
        "extraction": {
            "loan": {"attempts": loan_outcome.attempts,
                     "fields": _fields_dict(loan_outcome)},
            "offer": {"attempts": offer_outcome.attempts,
                      "fields": _fields_dict(offer_outcome)},
        },
        "engine": _engine_summary(result, decision),
        "explanation": {
            "drafts": drafts,
            "kind": explained.kind,
            "reason": explained.reason,
            "attempts": explained.attempts,
            "status": explained.status,
            "text": explained.text,
        },
        "usage": usage,
    }
    run_path = Path(run_dir) / f"{scenario['id']}.json"
    run_path.write_text(json.dumps(record, indent=2))
    return record, len(usage)


def record_all(data_dir: str | Path, run_dir: str | Path, client: Any,
               limit: int | None = None, cap: int | None = None,
               overwrite: bool = False) -> dict[str, Any]:
    """Record every scenario missing from the run folder.

    Resumable: scenarios with a record file are skipped, never repeated.
    Capped: recording stops before the scenario that would reach the total
    call budget. Returns recorded/skipped ids plus the call count.
    """
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    recorded: list[str] = []
    skipped: list[str] = []
    calls = 0
    for scenario in load_scenarios(data_dir):
        if limit is not None and len(recorded) >= limit:
            break
        target = run_path / f"{scenario['id']}.json"
        if target.exists() and not overwrite:
            skipped.append(scenario["id"])
            continue
        if cap is not None and calls >= cap:
            break
        _, made = record_scenario(scenario, client, run_path)
        recorded.append(scenario["id"])
        calls += made
    return {"recorded": recorded, "skipped": skipped, "calls": calls}


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """CLI: python3 eval/record.py --data eval/scenarios --run-dir eval/runs/dev-01 [--limit N] [--cap N] [--overwrite]."""
    parser = argparse.ArgumentParser(
        description="Record live extraction + explainer runs over scenarios.")
    parser.add_argument("--data", required=True,
                        help="scenario dir (dev or held-out)")
    parser.add_argument("--run-dir", required=True,
                        help="run folder receiving one JSON record per scenario")
    parser.add_argument("--limit", type=int, default=None,
                        help="record at most this many new scenarios")
    parser.add_argument("--cap", type=int, default=None,
                        help="stop before the scenario reaching this call total")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-record scenarios already in the run folder")
    args = parser.parse_args(argv)
    from llm import get_meta_client
    stats = record_all(args.data, args.run_dir, get_meta_client(),
                       limit=args.limit, cap=args.cap,
                       overwrite=args.overwrite)
    print(json.dumps(stats, indent=2))
    return stats


if __name__ == "__main__":
    main()
