# refi_assistant

Consumer-facing educational tool that compares keeping an auto loan,
refinancing now, and waiting under explicit rate scenarios. Solo hackathon
entry. All example loans and scenarios are synthetic.

The model API key lives in the `MODEL_API_KEY` environment variable only.
It is never hardcoded, printed, or committed.

## Batch evaluation on Modal (deferred)

`eval/modal_batch.py` records a scenario suite on Modal: one container per
scenario runs the same `record_scenario` chain as local runs, the records
are gathered into a run folder, and `score_run` writes `REPORT.md` next to
them — a Modal run folder scores identically to a local one.

Status: **deferred — never live-run.** The wrapper is written and
offline-tested, but no authenticated Modal run has happened yet.

Setup for that run, when it happens:

1. `pip install -r requirements.txt -r requirements-eval.txt` —
   `requirements.txt` holds the app runtime; `requirements-eval.txt`
   adds the test and batch-eval tools (`pytest`, `pillow`, `modal`).
2. `.venv/bin/modal token new` — logs into the `egutlapalli` workspace.
3. `modal secret create model-api-key MODEL_API_KEY=$MODEL_API_KEY
   BASETEN_API_KEY=$BASETEN_API_KEY` — one secret holding both keys the
   recording chain needs (the claim judge runs inside it).
4. `modal run eval/modal_batch.py --data <scenario dir> --run-dir <run dir>`
   (`--limit N` bounds the spend; `--overwrite` re-records).

Failure behavior is fail-loud on purpose: no `modal` login gives the CLI's
own auth error; a missing secret raises `RuntimeError` naming the exact
`modal secret create` command instead of failing later as a 401.
