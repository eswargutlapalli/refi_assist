# Daily summary — 2026-10-28 (refi_assistant)

Local-only log. Never commit to the GitHub repo.

## Decisions
- Work inside `hackathon_projects/refi_assistant`.
- Stage 1 is text-only input; image/PDF deferred to Stage 4.
- Streamlit entry: `app.py`.
- Engine tests live at `tests/test_engine.py`.
- Reasoning effort: `minimal` for extraction/orchestration, medium/high for explanation.
- Verdict rules deferred to a separate `/grill` session → `docs/DECISIONS.md`.
- Git initialized in `refi_assistant` (fresh repo, `main`, no commits yet).
- Commit workflow: assistant proposes message, waits for approval, never pushes without approval.

## Open
- First commit `1dc131e` pushed to `origin/main` (`refi_assist`) after approval.
- Added `docs/daily_notes/` (local-only log location), `.env` placeholder, `.gitignore`; committed `023c7d7` locally and pushed after approval; `main` in sync with `origin/main`.
- Built `engine.py` (amortization, keep/refinance/wait comparison, rate/term/costs split, lowest-cost label; verdict stubbed pending /grill) and `tests/test_engine.py` (16 tests, all passing). Both uncommitted, awaiting review.
- Moved prepayment penalty into `LoanTerms` (non-negative, validated at construction); sectioned `engine.py` into inputs / validation / calculation / options evaluation / summary-verdict-gate. Suite now 19 tests, all passing. Uncommitted, awaiting review.
- Added `RefinanceOffer` mirroring `LoanTerms` (rate, months, fees; validated at construction); `compare()` now takes `(current, offer)`. Suite now 21 tests, all passing. Uncommitted, awaiting review.
- Validation rules per customer inputs: balance > 0, APR in [0, 1], fees and penalty >= 0, term positive int; added `STANDARD_AUTO_TERMS` (24–84) as the dropdown source. Suite now 23 tests, all passing. Uncommitted, awaiting review.
- Renamed for readability: `CurrentLoan(balance, annual_rate, remaining_months, prepayment_penalty)`, `RefinanceOffer(annual_rate, term_months, fees, fees_financed)`; financed fees roll into the new balance; APR corrected to >= 0 and < 1. Suite now 26 tests, all passing. Uncommitted, awaiting review.
- Added `walkthrough.py` convention (one runnable trace script per module, real code + synthetic example). First engine trace run and shown in chat. Uncommitted, awaiting review.
- Added `Comparison.total_savings` (positive means refinancing saves); simplified walkthrough example to zero penalty/fees. Suite now 27 tests, all passing. Uncommitted, awaiting review.
- Added `Comparison.breakeven_month` (first month cumulative refi cost <= keep cost; None if never). Suite now 31 tests, all passing. Walkthrough shows with-fees variant breaks even at month 3. Uncommitted, awaiting review.
- Added month-by-month keep/refi cash-flow table to `walkthrough.py` plus a cashflow-reconciles-with-totals test. Suite now 32 tests, all passing. Uncommitted, awaiting review.
- Added `Comparison.keep_interest` / `refi_interest` (interest on amount borrowed; financed fees accrue as interest, upfront charges stay in costs). Suite now 34 tests, all passing. Uncommitted, awaiting review.
- Added `cashflows()` (Section 3) returning per-month keep/refi rows; breakeven redefined as stay-green-till-the-end (first month after which savings never go negative). With-fees variant now reports no breakeven instead of misleading month 3. Suite now 36 tests, all passing. Uncommitted, awaiting review.
- Added `WaitPlan` + `wait_plan()` (price a delayed refinance) and `wait_breakeven_rate()` (future-rate threshold vs refinancing now, via bisection; None when unwinnable). `compare()` wait scenarios now reuse `wait_plan`. Suite now 42 tests, all passing. Uncommitted, awaiting review.
- `wait_breakeven_rate()` now baselines against the cheaper of keep / refinance-now and names it (`WaitBreakeven`). Suite now 43 tests, all passing. Uncommitted, awaiting review.
- Added `WaitPlan.interest_while_waiting` (sunk keep-interest during the wait; principal repaid excluded); threshold/doc wording kept strictly scenario-conditional, never forecast. Suite still 44 passing. Uncommitted, awaiting review.
- Flipped the split sign convention: rate/term/costs effects now sum to `total_savings` (positive helps the borrower); your $12k example is pinned as a regression test. Suite now 44 tests, all passing. Uncommitted, awaiting review.
- Added `monthly_change`, `cash_due_today`, `months_to_payoff_keep/refi` to `Comparison`; financed-fee interest now sits in `costs_effect` (all effects computed on the current balance). Suite now 45 tests, all passing. Uncommitted, awaiting review.
- Rule 5 updated in `AGENTS.md` (facts carry no policy; judgments belong to verdict) — committed as `19d85e7` and pushed. Open: `lowest_total_cost` tie-break, `WaitBreakeven` baseline tie-break, and breakeven `<=` vs `<` all need verdict-side resolution after your answers.
- Rule 5 simplified again (engine reports numbers; verdict decides meaning, e.g. near-ties). Agreed: ties report `"equal"` (no pick) in both `lowest_total_cost` and `WaitBreakeven.baseline`; breakeven keeps `<=`. Committed as `22f410a` and pushed. Engine refactor to follow.
- Comment audit + agreed tie behavior implemented: `costs_effect` uses `0.0 - (...)` so zero is +0.0; `"equal"` on ties in `lowest_total_cost` and `WaitBreakeven.baseline`; stale sign-convention and financed-interest comments fixed. Suite caught an inverted branch I wrote (fixed). Suite now 47 tests, all passing. Uncommitted, awaiting review.
- Removed `wait_options` from `compare()` (scenarios use `wait_plan` directly); `wait_breakeven_rate()` takes a `priority` (`total_cost` | `monthly_payment`) so both customer priorities get thresholds; breakeven uses `_stay_green_month` with $1e-6 float tolerance; docstrings layout 1–5 restored; tie comments trimmed. Suite now 51 tests, all passing. Uncommitted, awaiting review.
- Removed the `priority` option (`wait_breakeven_rate` is total-cost only; payment-only thresholds are the trap); trap 6-month threshold pinned at the engine's true 4.2115% (user's 2.97% does not reproduce — flagged); layout de-duplicated; `lowest-cost` naming, breakeven comment, tie wording, and tolerance wording fixed per review. Suite now 49 tests, all passing. Diff shown, NOT committed (standing rule).
- Full engine.py consistency audit per review: fixed the duplicated Layout block (old 2–5 survived under the new 1–5), stale Section 4 header, `upfront` naming collision (fees-only in `compare`, fees+penalty in `wait_plan` — now `upfront_fees`/`upfront_costs`), `penalty` shorthand expanded, `WaitPlan.total` comment for the financed case, vague `present` renamed to `totals`. Suite still 49 passing. NOT committed (standing rule).
- Group 1 reference tests added (trap / clear win / B / C exact numbers; A breakeven month 10). Suite now 53 passing. NOT committed (standing rule).
- Group 2 split-identity tests added (trap, clear win, financed B, $18,450 financed with costs pinned at -279.02). Suite now 57 passing. NOT committed (standing rule).
- Group 3 wait-threshold tests added ($15k trap wait-6 at 2.97% vs keep; $20k wait-3 at 5.5536% vs refinance now). Suite now 59 passing. NOT committed (standing rule).
- Group 4 validation test added (36.5 and True as months rejected everywhere month counts are taken). Suite now 60 passing. NOT committed (standing rule).
- Removed redundant `WaitOption`: `Comparison.wait_options` now holds `WaitPlan` with `wait_months=0` (same type, same math, one path). Suite still 47 passing, walkthrough runs clean. Uncommitted, awaiting review.
- Stage 1 scaffold (`engine.py`, `verify.py`, `app.py`, `tests/test_engine.py`) on hold until go-ahead.
- `/grill` session for verdict rules still pending.
