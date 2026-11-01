"""eval/vision_check.py — vision transcription quality vs the text baseline.

Why this file exists: multimodal input must meet a bar before it replaces
the "later slice" caption — zero wrong values, and grounding within 10
percentage points of the text run. This script renders each scenario's
texts to PNGs (test-only renderer), transcribes them with live vision,
extracts with the live calls the app makes, and scores grounding with the
same score_extraction the text runs use. All scenarios here are synthetic.

Usage: python3 -m eval.vision_check --data eval/scenarios [--limit N]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.record import load_scenarios
from eval.score import score_extraction
from extract import extract_current_loan, extract_refinance_offer
from llm import get_meta_client
from statements import transcribe_image
from tests._render import render_text_png


def check_scenario(scenario: dict[str, Any],
                   client: Any) -> dict[str, Any]:
    """Transcribe both rendered texts, extract, and score grounding.

    Transcripts are kept in the returned record: a wrong value without
    its transcript is evidence lost, as the fees-method-unstated rerun
    showed.
    """
    fields: dict[str, Any] = {}
    transcripts: dict[str, str] = {}
    for side, text, extract in (
        ("loan", scenario["loan_text"], extract_current_loan),
        ("offer", scenario["offer_text"], extract_refinance_offer),
    ):
        transcript = transcribe_image(render_text_png(text), "image/png",
                                      client=client)
        transcripts[side] = transcript
        outcome = extract(transcript, client=client)
        fields[side] = {
            name: {"value": field.value, "quote": field.quote,
                   "status": field.status}
            for name, field in outcome.fields.items()
        }
    record = {"id": scenario["id"],
              "extraction": {"loan": {"fields": fields["loan"]},
                             "offer": {"fields": fields["offer"]}}}
    scored = score_extraction(record, scenario)
    return {"id": scenario["id"], "correct": scored["correct"],
            "wrong": scored["wrong"], "needs_fix": scored["needs_fix"],
            "evaluated": scored["evaluated"],
            "transcripts": transcripts, "fields": fields}


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """CLI: render, transcribe, extract, and score every scenario."""
    parser = argparse.ArgumentParser(
        description="Vision transcription check over scenario texts.")
    parser.add_argument("--data", required=True, help="scenario dir")
    parser.add_argument("--limit", type=int, default=None,
                        help="check at most this many scenarios")
    parser.add_argument("--run-dir", default=None,
                        help="save per-scenario transcripts and fields here")
    args = parser.parse_args(argv)
    client = get_meta_client()
    rows = []
    for scenario in load_scenarios(args.data):
        if args.limit is not None and len(rows) >= args.limit:
            break
        rows.append(check_scenario(scenario, client))
    if args.run_dir is not None:
        run_path = Path(args.run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        for row in rows:
            (run_path / f"{row['id']}.json").write_text(
                json.dumps(row, indent=2))
    correct = sum(r["correct"] for r in rows)
    evaluated = sum(r["evaluated"] for r in rows)
    wrong = [f"{r['id']}.{w}" for r in rows for w in r["wrong"]]
    summary = {
        "scenarios": len(rows),
        "grounded_correct": f"{correct}/{evaluated}",
        "wrong_values": wrong,
        "rows": rows,
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
