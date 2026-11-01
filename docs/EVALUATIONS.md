# Evaluation

How the project proves its numbers. Audience: hackathon judges and future
contributors. All scenarios are synthetic. No real borrower data exists
anywhere in this repo.

## 1. Why this eval exists

Lender calculators show the lower monthly payment and hide the higher total
cost. This tool makes the tradeoff visible. That only works if every number
shown is proven. The model never generates a number (all math is local code).
Extraction copies terms with quote proof. Every explanation number is checked
before display. Verdicts come from code rules. The eval measures four things:
copying accuracy, the user's fix burden, story verification, and verdict
stability.

## 2. How it runs

Thirteen dev scenarios live in `eval/scenarios/`. Each holds loan and offer
texts, the true terms (`None` for unstated), and a priority. Expected outputs
are recomputed from the true terms, never stored.

`eval/record.py` runs the live calls per scenario: both extractions on the
pasted texts, plus the explainer ladder on the TRUE terms (what a user would
confirm). Each reply is saved with its usage dump into a run folder. Runs are
capped and resumable. `eval/score.py` replays a run folder offline: no model
calls, no network. It checks extraction against the truth, rechecks drafts
with `verify.py`, and compares the extracted-terms verdict against the true
verdict.

Held-out rule: the hidden set lives outside the repo. Both scripts take
`--data <path>`. The dev set runs from a fresh clone. Reported numbers always
come from a recorded run.

## 3. Metrics

Each metric answers one borrower-facing question.

Grounded-and-correct over stated fields asks: did it copy right? A field
counts when its value is grounded in a quote and equals the truth.

Wrong-value rate asks: did it ever state a wrong number as fact? Grounded but
unequal to the truth counts. Target zero. Every case is listed.

Confirmation-edit rate asks: how much would I have to fix? Wrong, cleared,
and missing fields over all evaluated fields (eight, or seven when $0 fees
mean the flag is never asked).

Explanation kinds ask: did the story check out? Counts verified first-pass,
rewritten once, and template by kind and reason.

Verdict flips ask: did an extraction error change the answer? The verdict
is recomputed from extracted terms, with the true value filled in only
where extraction left a field empty, as a user would on the confirm page.
That verdict is compared to the true verdict. Any mismatch is listed.

Cache ratio asks: is the prompt cache working? Cached tokens over prompt
tokens, summed across the run.

## 4. Run history

| Metric | dev-01 | dev-02 | dev-03 |
|---|---|---|---|
| Grounded + correct | 82/98 (83.7%) | 94/98 (95.9%) | 95/98 (96.9%) |
| Wrong-value | 0/104 (0.0%) | 0/99 (0.0%) | 0/99 (0.0%) |
| Confirm-edit rate | 22/104 (21.2%) | 5/99 (5.1%) | 4/99 (4.0%) |
| Explanation | 10 / 2 / 1 | 10 / 3 / 0 | 12 / 1 / 0 |
| Verdict flips | 0 | 0 | 0 |
| Cache ratio | 21228/30892 (68.7%) | 21906/24900 (88.0%) | 16507/23165 (71.3%) |
| Model calls | 59 | 49 | 46 |

Explanation columns read verified / rewritten / template. Full per-scenario
tables are in `docs/eval/dev-01-REPORT.md`, `dev-02-REPORT.md`, and
`dev-03-REPORT.md`. `dev-01` is the frozen baseline.

dev-01 to dev-02 was driven by quote-only attribution (decision 21) plus
flag counting (decision 22). Adjacent amounts like "APR, 48 months" stopped
vetoing well-quoted copies. dev-02 to dev-03 was driven by single-amount
leniency (decision 24) plus sentence-quoting agreement feedback (decision
23). The long penalty quote grounded live. No run ever produced a wrong
value or a flipped verdict.

## 5. Claim-judge fixtures (Nov 1, decision 26)

Twelve fixed drafts in `tests/fixtures/judge_drafts.json` (invented text
only): 6 clean, 6 known-bad across softening, contradiction, wrong
attribution, and advice beyond the verdict. Judged once live on Baseten
(`meta-models/muse-spark-open-1026`), re-runnable via
`python3 judge.py --fixtures tests/fixtures/judge_drafts.json`:

- catches: 6/6, each with exactly the expected problem kind;
- false flags on clean drafts: 0/6;
- transport/schema errors: 0.

These fixtures were written alongside the judge prompt, so these are dev
results: the prompt author knew every draft's trick. A held-out judge
line (fresh drafts the prompt never saw) gets its own row here:

| Judge set | Catches | False flags | Errors |
|---|---|---|---|
| dev fixtures (12) | 6/6 | 0/6 | 0 |
| held-out drafts | — | — | — |

Descriptive counts, not estimates — and the judge stays meaning-only.
Number verification is unchanged and still runs first.

Thirteen scenarios, one recording per run, and model output varies
between runs. These are descriptive counts, not statistical estimates.

dev-03 is complete: it counted four fixes. Three are by design. The
percent penalty ("2% of the balance") cannot be copied as dollars, so the
user types 280.0. The must-choose flag has stated fees with no stated
method, so the user picks. "3 years" states no month word, so 36 stays
user-entered. The fourth was a known parser gap at the time: the
spoken-word rate ("four point seven nine") parsed to no number for lack
of "point" support. That support has since landed in the parser (strict
decimals; malformed forms parse to nothing); past runs are not re-scored,
and a future run will show whether that fourth fix disappears.

The dev set found and fixed real problems: decisions 21 through 24 came out
of dev-01 and dev-02 results, so dev numbers are optimistic. The held-out
set was written separately and never seen during development. It runs once
at the freeze and gets its own column.

## 6. Vision transcription check (Nov 1)

Each dev scenario text rendered to PNG (`tests/_render.py`, test-only),
transcribed by live vision, extracted by the live calls, scored by the
same grounding check (`python3 -m eval.vision_check --data eval/scenarios`):

- grounded and correct: 86/99 (86.9%) vs 95/98 (96.9%) on text;
- wrong values: 2 — `fees-method-unstated.loan.remaining_months`
  (transcript perfect; extraction misattributed on the rerun) and
  `no-penalty-mentioned.loan.balance` (vision read $19,800.00 as
  $18,800.00, a single-digit misread).

The bar (zero wrong, grounding within 10 points) is not met, so this
section stays as the honest record. Both failures are the exact class
the confirm gate exists to catch: the transcript sits in the editable
box, the quote proves what was copied, and the user fixes the digit
before anything computes. PDFs read their text layer locally with no
vision involved; only photos, screenshots, and scans take the vision path.

Rerun with the wrapping renderer (transcripts saved under `eval/runs/`,
gitignored): 94/99 grounded with 1 wrong. The saved transcript settles
the recurring case — vision read "46 payments remaining" as "48 payments
remaining", and extraction grounded 48 against the quote "48 payments
remaining", a perfect copy of a misread transcript. Every layer after
vision behaved correctly; the digit error sat in plain sight where the
confirm page shows it. The bar still stands unmet at 1 wrong.

## 7. What the eval does not cover

Hedging or softening the verdict passes the word-list check; catching it is
the claim judge's job (§5 above), live on Muse Spark Open via Baseten, as is
right number with wrong meaning. No fine-tuning signal exists yet; the
Fireworks experiment waits on the core build.

## 8. Reproduce it

Recording spends model credit (about 50 calls for 13 scenarios) and needs
`MODEL_API_KEY` in the environment. Scoring is offline and free. Run folders
stay gitignored; copy `REPORT.md` into `docs/eval/` to keep a report.

```
python3 -m eval.record --data eval/scenarios --run-dir eval/runs/dev-04
python3 -m eval.score --data eval/scenarios --run-dir eval/runs/dev-04
```
