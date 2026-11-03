# refi_assist

Consumer-facing educational tool that compares keeping an auto loan,
refinancing now, and waiting under explicit rate scenarios — and checks
every number it shows against its source, with you confirming each one
before anything is computed. Lender calculators show the lower monthly payment
and hide the higher total cost; this tool makes the tradeoff visible,
including how much of the difference comes from the rate, the term, and
fees. Solo hackathon entry. All example loans and scenarios are
synthetic; no real borrower data anywhere.

Hosted app: https://refiassist.streamlit.app/

It is an educational estimator, not financial advice. It does not offer
or broker loans or accept applications, and it stores nothing you enter:
everything stays in session memory.

## How it works

1. Paste or upload your statements. The model extracts the loan terms,
   each with the exact quote it was copied from.
2. A code check confirms every quote really appears in your statement
   text (or its transcript, for photos and scans).
3. You review, edit, and confirm every number on the confirm page. No
   computation runs on unconfirmed inputs.
4. Local code computes the comparison, the rate/term/costs split, and the
   verdict from fixed rules — the model never computes a number.
5. The model explains the verdict in plain language; code checks every
   number in the explanation, and the Baseten claim judge checks its
   meaning. The page states whether you are seeing the verified model
   narrative, a rewrite, or a code-written template.

Waiting is scenario analysis, never a forecast: the page computes what
happens under rate scenarios you can see and change.

## Meta tooling, and where each piece is used

- **Muse Code** — the agentic CLI the project was built with.
- **Muse Spark** via the Meta Model API — statement extraction, the
  verdict explanation, and the transcript read for photos and scans.
- **Muse Spark Open on Baseten** — the independent claim judge, a
  different model from the one that wrote the explanation.

## Results

Full method, history, and caveats: [docs/EVALUATIONS.md](docs/EVALUATIONS.md).

- dev-04 (13 scenarios): 96/98 grounded and correct, 0 wrong values,
  12 verified explanations plus 1 judge-outage template, 0 verdict flips.
- heldout-01 (12 held-out scenarios, recorded once): 89/91 grounded and
  correct with the other 2 correctly cleared, 0 wrong values, 12/12
  verified (judge passed on all twelve), 0 verdict flips.
- Claim judge: 6/6 caught on dev fixtures; on 8 held-out drafts, 3/4 bad
  drafts caught with 0 false flags. The miss was a quiet reversal of the
  verdict at the end of an accurate draft (see EVALUATIONS.md §5, §7).
- Image path: two runs. The first scored 86/99 with 2 wrong; after a
  renderer fix, the second scored 94/99 with 1 wrong, where vision
  misread 46 as 48 and extraction faithfully copied the misread. That
  is why every transcript is editable and every number goes through
  the confirm page.

## Tests and design record

361 tests, offline-only: the suite never touches the network
(`tests/conftest.py` blocks sockets, so any test that tried would fail
instead of spending credit). Run it with `pytest` from the repo root.
Design decisions with reasons live in [docs/DECISIONS.md](docs/DECISIONS.md);
the rules the agent built under live in [AGENTS.md](AGENTS.md).

## Running locally

Needs `MODEL_API_KEY` (Meta Model API) and `BASETEN_API_KEY` (claim
judge) in the environment — names only; values live outside the repo
(see `.env.example`). Then:

```
pip install -r requirements.txt
streamlit run app.py
```

Eval and batch tools need both requirements files:

```
pip install -r requirements.txt -r requirements-eval.txt
```

## Demo samples

`samples/` holds four synthetic statements exercising every page-1
upload path: a text-layer PDF (read locally, no model call), an
image-only scan, a clean screenshot, and a tilted photo. The README
there pins the expected terms and the engine-checked verdict, so a demo
run can be verified digit by digit.

## walkthrough_engine.py

A runnable trace of `engine.py` on a synthetic loan: it calls the real
functions and prints each call with its inputs and outputs — never
hand-filled numbers. Created to keep the math honest during development,
and rerun after every engine change: `python3 walkthrough_engine.py`.

## Batch evaluation on Modal (deferred)

`eval/modal_batch.py` records a scenario suite on Modal: one container
per scenario runs the same `record_scenario` chain as local runs, the
records are gathered into a run folder, and `score_run` writes
`REPORT.md` next to them — a Modal run folder scores identically to a
local one.

Status: **deferred — never live-run.** The wrapper is written and
offline-tested, but no authenticated Modal run has happened yet.

Setup for that run, when it happens:

1. `pip install -r requirements.txt -r requirements-eval.txt` —
   `requirements.txt` holds the app runtime; `requirements-eval.txt`
   adds the test and batch-eval tools (`pytest`, `pillow`, `modal`).
2. Authenticate the Modal CLI (`modal token new`).
3. `modal secret create model-api-key MODEL_API_KEY=$MODEL_API_KEY
   BASETEN_API_KEY=$BASETEN_API_KEY` — one secret holding both keys the
   recording chain needs (the claim judge runs inside it).
4. `modal run eval/modal_batch.py --data <scenario dir> --run-dir <run dir>`
   (`--limit N` bounds the spend; `--overwrite` re-records).

Failure behavior is fail-loud on purpose: no `modal` login gives the CLI's
own auth error; a missing secret raises `RuntimeError` naming the exact
`modal secret create` command instead of failing later as a 401.
