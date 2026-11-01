"""judge.py — independent meaning check on accepted narratives (decision 26).

Why this module exists: verify.py proves every number, but numbers can be
right with the wrong meaning ("the lower rate saves" followed by a term
figure), and a narrative can soften or contradict the verdict it states.
Those are meaning failures, and catching them is a different model's job:
Muse Spark Open via Baseten, never the model that wrote the draft.

Scope is meaning only: softening or contradiction of the verdict, a right
number with the wrong attribution, advice beyond the verdict. The judge
sees the accepted draft only — first-pass or rewritten, exactly once —
never a number-failed draft and never the template. Transport errors,
timeouts, and schema violations raise LlmError; the ladder maps those to
the honest unavailable template, never a pass.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from llm import (
    LlmError,
    LlmUsage,
    StrictModel,
    baseten_judge,
    get_baseten_client,
)

JUDGE_PROBLEMS = (
    "softening",
    "contradiction",
    "wrong_attribution",
    "advice_beyond_verdict",
)


class JudgeResult(StrictModel):
    """Schema-constrained judge output: pass plus fixed problem kinds."""

    passed: bool | None
    problems: list[str] | None


@dataclass
class JudgeVerdict:
    """One judged draft: pass plus the fixed kinds found, if any."""

    passed: bool
    problems: list[str]


def build_judge_messages(headline: str, tradeoff_note: str,
                         figures: list[str], draft: str) -> list[dict[str, Any]]:
    """Judge prompt: the verdict to hold fixed, the figures the explainer
    was allowed, the draft to check. Kind definitions name the fixed set
    so the reply has no other vocabulary for failure."""
    return [
        {"role": "system", "content": (
            "Judge whether a loan-comparison explanation keeps the meaning "
            "of its verdict. The numbers are already proven; check meaning "
            "only. Fail the draft for exactly these problems: softening "
            "(hedging toward the other option, e.g. 'might consider'); "
            "contradiction (declaring the other option the better choice); "
            "wrong_attribution (a right number credited to the wrong cause, "
            "e.g. 'the lower rate saves' followed by a term figure); "
            "advice_beyond_verdict (recommending actions beyond the keep-or-"
            "refinance choice). Anything else passes. "
            "Reply with JSON only: {\"passed\": boolean, "
            "\"problems\": [kinds found]}."
        )},
        {"role": "user", "content": (
            f"Verdict headline: {headline}\n"
            f"Tradeoff note: {tradeoff_note}\n"
            "Figures the explanation was allowed:\n"
            + "\n".join(f"- {line}" for line in figures)
            + f"\nDraft to judge:\n{draft}"
        )},
    ]


def judge_draft(context: dict[str, Any], *, client: Any = None,
                usage_sink: list[dict[str, Any]] | None = None) -> JudgeVerdict:
    """Judge one accepted draft. Unknown problem kinds and null fields
    fail loudly: a judge that disobeys its schema is not a pass. When
    usage_sink is given, the call's usage dump is appended."""
    result, response = _judge_call(context, client)
    if usage_sink is not None:
        # Fakes carry no usage object; zeros keep the key shape intact.
        usage = getattr(response, "usage", None)
        counts = (usage.as_dict() if usage is not None
                  else LlmUsage().as_dict())
        usage_sink.append({"model": response.model, **counts})
    if result.passed is None or result.problems is None:
        raise LlmError("JudgeResult: null field in judge reply")
    unknown = [kind for kind in result.problems
               if kind not in JUDGE_PROBLEMS]
    if unknown:
        raise LlmError(f"JudgeResult: unknown problem kinds {unknown}")
    if result.passed and result.problems:
        raise LlmError("JudgeResult: passed with problems listed")
    if not result.passed and not result.problems:
        raise LlmError("JudgeResult: failed with no problem named")
    return JudgeVerdict(passed=result.passed, problems=list(result.problems))


def _judge_call(context: dict[str, Any], client: Any) -> Any:
    messages = build_judge_messages(
        context["headline"], context["tradeoff_note"],
        list(context["figures"]), context["draft"],
    )
    if client is None:
        client = get_baseten_client()
    response = baseten_judge(
        messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": JudgeResult.__name__,
                "schema": JudgeResult.model_json_schema(),
                "strict": True,
            },
        },
        client=client,
    )
    try:
        result = JudgeResult.model_validate_json(response.text)
    except ValidationError as exc:
        raise LlmError(f"JudgeResult: bad shape ({exc.errors()[0]['loc']})") from exc
    return result, response


def judge_fixtures(path: str | Path, client: Any = None) -> list[dict[str, Any]]:
    """Judge every fixture draft once. Live runs only; tests use fakes."""
    rows = json.loads(Path(path).read_text())
    outcomes = []
    for row in rows:
        try:
            found = judge_draft(row, client=client)
            outcomes.append({"id": row["id"], "error": None,
                             "passed": found.passed,
                             "problems": found.problems,
                             "expected_passed": row["expected_passed"],
                             "expected_problems": row["expected_problems"]})
        except LlmError as exc:
            outcomes.append({"id": row["id"], "error": str(exc)[:120],
                             "passed": None, "problems": None,
                             "expected_passed": row["expected_passed"],
                             "expected_problems": row["expected_problems"]})
    return outcomes


def main(argv: list[str] | None = None) -> list[dict[str, Any]]:
    """CLI: python3 judge.py --fixtures tests/fixtures/judge_drafts.json."""
    parser = argparse.ArgumentParser(
        description="Judge fixed drafts once against the live judge.")
    parser.add_argument("--fixtures", required=True,
                        help="JSON fixture file (invented text only)")
    args = parser.parse_args(argv)
    outcomes = judge_fixtures(args.fixtures)
    print(json.dumps(outcomes, indent=2))
    return outcomes


if __name__ == "__main__":
    main()
