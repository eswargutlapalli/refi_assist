# DECISIONS.md — settled engine decisions (2026-10-28)

Short record: decision, reason, rejected alternative. Split order was provisional, pending grill decision 16 — settled by decision 12 below.

1. Exact ties report "equal", no pick (cheaper total and wait baseline).
   Reason: the engine reports numbers; any near-tie call is verdict business.
   Rejected: engine picking a winner on ties.

2. Breakeven = first month refinancing stays ahead for good; month 1 when no upfront cost; float noise under $0.000001 ignored.
   Reason: an early crossing that later reverses misleads; month 1 with zero upfront is genuinely ahead from the start.
   Rejected: first-crossing breakeven; treating float dust as crossings.

3. Financed fees and all interest they accrue count in the costs effect.
   Reason: keeps term effect clean (term change only) and shows the full financed-fee burden in one place.
   Rejected: splitting financed-fee interest into term effect.

4. Waiting = pay the current loan down first, then refinance the smaller balance.
   Reason: matches what waiting actually does; wait interest is sunk, repaid principal is not lost.
   Rejected: pricing a wait as today's balance at a future rate.

5. Wait thresholds compare total cost only, against today's cheaper option.
   Reason: payment-only thresholds hide the payment trap this tool exists to expose.
   Rejected: payment-based wait thresholds.

6. Sign convention: positive means refinancing saves (rate + term + costs effects sum to total savings).
   Reason: one consistent reading direction across the split and the headline.
   Rejected: positive-means-costs-more convention.

Resolved: split order settled by grill decision 12 (rate-first over remaining term).

## Verdict rules (Draft — grill in progress, 2026-10-28)

7. Priorities are lowest total cost, lowest monthly payment, earliest payoff; default is lowest total cost.
   Reason: the default matches the tool's thesis (total-cost visibility); payment-first would repeat the lender framing.
   Rejected: defaulting to lowest payment; dropping earliest payoff.

8. "Too close to call" = under $100 total cost, under $10/month payment; fixed dollars. "Under" is strict: exactly $100.00 (or $10.00 a month) picks a winner.
   Reason: a borrower can picture $100; percentages add false precision to a judgment call, and fixed numbers keep the rule one line.
   Rejected: percentage-of-balance margins; combined fixed-plus-percentage tests.

9. Earliest-payoff tie on payoff month falls back to total cost.
   Reason: the payoff priority is satisfied either way, so paying less overall is the next thing that borrower cares about.
   Rejected: falling back to payment; declaring a tie too close to call.

10. Every tradeoff note states the payment change and the total-cost difference; adds the payoff change whenever the loans end at different times; "and" when both metrics favor the same option, "but" when they point opposite ways; never invents a tradeoff; too-close verdicts get the same note. The note is framed from the chosen option's side: a keep verdict speaks as keep ("Your payment stays $214.56 a month higher, but you pay $1,225.09 less in total. Your current loan pays off 36 months sooner."), a refinance verdict speaks as refinancing, and too-close keeps the refinance framing since there is no winner. Both sides use the same two-sentence shape — payment and total in the first sentence, payoff timing in its own second sentence.
    Reason: one-sided notes are the lender behavior this tool counters; the conjunction carries the direction honestly. Framing from the winner's side makes the note explain the verdict instead of relitigating it — a keep headline followed by "Refinancing lowers…" argues the loser's case first.
    Rejected: one fixed refinance-framed note for every outcome; warning only against the priority's spirit; omitting payoff timing; hedging "but" on clean wins.

11. Headlines and tradeoff notes are code-written templates per priority and outcome (eleven wordings); under payoff priority any nonzero month gap wins outright, only equal months fall back.
    Templates (B = total difference, A = monthly difference, N = month gap, M = shared payoff month):
    Total — refinance: "Refinancing saves you $B in total." keep: "Keeping your loan costs $B less in total." close: "Too close to call on total cost — $B apart."
    Payment — refinance: "Refinancing lowers your payment by $A a month." keep: "Your current payment is $A a month lower." close: "Too close to call on payment — $A a month apart."
    Payoff — refinance: "Refinancing pays off N months sooner." keep: "Your current loan pays off first — N months sooner." close: "Too close to call — same payoff month and totals within $B."
    Payoff, same-month fallback to total (M = shared payoff month): "Both loans pay off in M months; refinancing costs $B less in total." / "Both loans pay off in M months; keeping your loan costs $B less in total."
    Reason: fixed wording keeps verdicts explainable and checkable; a sooner payoff is the priority satisfied, no margin needed.
    Rejected: model-worded headlines; small month gaps falling back to total cost.

12. (Resolves provisional split order.) Rate effect is measured first, over the same remaining term; term effect prices the timeline change at the offered rate. Display uses directional labels and words, never signs: "Lower rate: saves $X" / "Higher rate: costs $X", "Longer term: costs $X" / "Shorter term: saves $X", "Fees and charges: costs $X". Engine keeps signed numbers; wording is display only.
    Reason: the current order credits the rate with savings on months the term extension created; rate-first keeps each effect on the timeline it belongs to.
    Rejected: keeping term-first attribution; showing + / − signs to users.

13. Word-form numbers ground, and code parses every number in whatever form before it reaches the engine.
    Statements arrive in digits ("37"), words ("thirty seven"), or mixed ("fifty one dollars and 51 cents"). The model reports digits either way; the quote scanner parses both — ones through billions, hyphenated compounds, dollars-and-cents combined, percent markers — and grounding still demands quote-in-source plus value-among-numbers, with the user confirming the digits at the gate.
    Reason: refusing word forms would clear correctly-read values and push trivial typing onto the borrower; parsing in code keeps the copy-vs-calculate split (rule 3.1) while the confirm gate stays the backstop against misparses.
    Rejected: clearing all word-form terms for the user (safe but punitive); letting the model convert words unchecked (math in the model).
   Addendum (Oct 30, live-verified): digit-plus-scale phrases report the full amount ('30 thousands' → 30000, never the bare 30 — code rejects the bare digit as ungrounded), and quotes name the term with its amount ('balance 30 thousands', not '30 thousands') so attribution holds. Continue on page 1 parses both statements; re-parse runs only when the text changed.

14. Confirm-gate blank rule (Oct 30): a blank penalty/fees field means different things by provenance. Unstated (the statement never mentioned it) — blank means none, Confirm passes. Cleared (the statement said something we couldn't verify, e.g. "2% of the remaining balance") — blank blocks Confirm with "couldn't verify, please enter"; an explicit 0 is accepted.
    Reason: silently treating a cleared value as $0 bakes the likeliest wrong number into the comparison; the user typing 0 keeps the decision visible and the user's own.
    Rejected: blank always means none (hides unverified fees); blank always blocks (punishes the common no-fee case with typing for nothing).

15. Wait section order (Oct 30): thresholds table first ("only if rates fall below X%", against today's cheaper option, offer rate on its own line), then the try-a-rate what-if as a two-column table (today's cheaper option vs "wait N months, then refinance at R%", with old payment during the wait, then the new one, totals, and payoff in N months), closed by one tradeoff line ("saves $A in total, but you finish N months later").
    Reason: the earlier mixed sentences repeated totals, never said $X/mo was the post-wait payment, and hid that waiting extends payoff.
    Rejected: keeping the three-sentence what-if plus threshold blend.

16. Explainer + verify contract (Oct 31): the model narrates the code-written verdict using only engine-provided numbers (headline, tradeoff note, rate/term/costs split, monthly and total figures, breakeven month). The narrative covers verdict, comparison, and split only — never wait scenarios, which the page renders separately; the prompt says so outright, and any wait figure fails verification without wait context. `verify.py` checks every number in the narrative against engine output to the displayed cent, and confirms the narrative agrees with the verdict choice (winner, direction, no softening or contradiction). Rewrite feedback is specific: it names the numbers that did not match and the verdict they must agree with — the model already holds every allowed value, so specificity leaks nothing (kind-only feedback applies only to the eval's hidden ground truth, never to the live rewrite). One rewrite, then the code-written template. The screen always states which of the three the user is seeing, using the §3 rule 4 wording verbatim.
   Effort: extraction runs `minimal` (a copy task); explanation runs `medium` (narrative quality earns the reasoning).
   Reason: the live model needs exact mismatch names to fix its draft in one pass; the eval needs kind-only hints so its checks stay worth measuring.
   Rejected: kind-only live feedback (wastes the single rewrite on guessing); model-worded verdicts; silent fallback.

17. Eval records, never the app (Oct 31): the app never writes user input to disk, so there is no trace recorder in `app.py`. `eval/record.py` runs the live calls — both extractions on the pasted texts, the explainer ladder on the TRUE terms (what a user would confirm) — over scenario files only, saving every reply with its usage dump to a run folder, capped and resumable. Reported numbers always come from a recorded run; hand-written records are scorer unit-test fixtures only.
   Reason: explanation quality is scored separately from extraction accuracy; extraction errors surface in the extraction metrics and the verdict-flip check.
   Rejected: an app-side recorder; explaining extracted terms (mixes the two error sources); hand-written reported numbers.

18. Scenario schema + held-out discipline (Oct 31): dev scenarios in `eval/scenarios/` hold loan/offer texts, TRUE terms (`None` for unstated), and a priority; expected engine outputs and the verdict are recomputed from the true terms, never stored. The held-out set lives outside the repo; `record.py` and `score.py` take `--data <path>`, and the agent never opens the held-out path.
   Reason: hidden-from-model by construction (recompute, not secrecy) while keeping the dev set runnable from a fresh clone.
   Rejected: stored expected outputs (readable at runtime); a gitignored answers file (fresh clones cannot run the eval).

19. Must-choose financed flag (Oct 31): when fees are stated but the method is not, truth `fees_financed` is `None` and the flag is a field the user must choose — ungrounded counts as missing, grounded either way counts as wrong. Percent-stated penalties (e.g. "2% of the balance") hold the dollar value in truth; the extractor is expected to clear them and the scorer counts the user fix.
   Reason: a stated-but-unchoosable method is a confirm-gate decision, not an ignorable blank; a percent penalty states a charge the extractor cannot copy as dollars.
   Rejected: treating must-choose as ignorable `None`; truth `None` for a stated percent penalty (hides the required user math).

20. Eval metrics (Oct 31): per field against the truth — grounded-and-correct over stated fields; wrong-value rate (grounded but unequal, target zero, every case listed); confirmation-edit rate (wrong + cleared + missing over all 8 fields); explanation by `ExplainResult` kind and reason (first-pass verified / rewritten / template); verdict from extracted terms (true filling only empties) vs. from true terms; cached / prompt tokens. Reported as a markdown table (`REPORT.md`) saved next to the run.
   Reason: each metric answers one borrower-facing question — is it copied right, would I have to fix it, does the story check out, does an error change the answer.
   Rejected: aggregate-only scores (hide which field failed); storing verdicts (rot when the engine changes).

21. Quote-only attribution (Oct 31): `check_field` decides from the quote alone — quote in source, value among the quote's numbers, unit and field word inside the quote's windows. The source-wide competitor guard is gone: a second stated amount elsewhere no longer vetoes a well-quoted copy ("6.5% APR" grounds with "48" two slots past the %). A misattributed copy is caught downstream by the wrong-value probes, which compare against the truth. Bare amounts still fail ("$150" names nothing for the penalty; bare $ means balance).
   Reason: the guard punished precise quoting — the better the quote, the more the rest of the text could veto it. The quote is the model's claim about what it copied; judging the claim, not the neighborhood, is the check.
   Rejected: keeping the source-wide veto (real-world adjacencies like "APR, 48 months" cleared relentlessly); model-side disambiguation (math in the model).

22. Financed flag counts only when fees are above zero (Oct 31): with $0 fees the app never asks, so the scorer excludes the flag (seven evaluated fields, not eight). The must-choose rule (decision 19) is unchanged — stated fees with an unstated method still count the flag as missing/wrong.
   Reason: scoring a question the borrower is never asked inflates the fix rate for the cleanest cases.
   Rejected: always counting eight (clean scenarios pay a phantom field).

23. Agreement feedback quotes the sentence (Oct 31): when a narrative fails agreement on an opposing-side phrase, the feedback quotes that sentence ("This sentence states the other option's headline: '<sentence>'. State the tradeoff as the note does instead.") and never says "restate the headline" when the headline is already present. The explainer prompt frames the other side the way the tradeoff note does, never in the other option's headline wording.
   Reason: the old message told the model to redo what it had already done; the sentence quote points at what to change.
   Rejected: headline-only feedback on agreement failures.

24. Single-amount quotes claim without a cap (Oct 31): when a quote holds exactly one digit-stated amount, any field word inside the quote may claim it ("Prepayment penalty if you refinance elsewhere: $150" grounds). Word-form lone numbers stay capped, and multi-amount quotes keep the proximity rule.
   Reason: one amount plus a naming word is a deliberate copy; the cap existed for crowded spans, not for these.
   Rejected: lifting the cap everywhere (crowded-span attribution still needs distance).

25. Eval reports are committed (Oct 31): per-run `REPORT.md` copies live in `docs/eval/` (synthetic scenarios only); the run folders with full records stay gitignored and reproducible via `record.py`.
   Reason: the report is the framework's visible output; the records are regenerable bulk.
   Rejected: committing full run folders; keeping reports local-only.

26. Claim-judge failure behavior (Nov 1): the Baseten judge call has a 20-second timeout with no retries. A meaning failure falls back to the code-written template with "Code-written template — the model narrative did not pass the meaning check." A judge timeout or error falls back to the template with "Code-written template — the independent check was unavailable." Both count as template in eval. The judge sees the accepted draft only — first-pass or rewritten, exactly once — never a number-failed draft and never the template. Judge calls do not count against the 5-run narrator budget.
   Reason: 20 seconds is 3x the observed ~6s call, bounded so one slow call never hangs page 3; distinct wordings keep the failure honest under rule 3.4; judging only accepted drafts leaves no softening hole without re-checking known-bad text; the judge is a checker like `verify.py`, not a narrative.
   Rejected: 30s/60s timeouts; reusing the existing template wordings; judging first-pass drafts only; counting judge calls against the narrator budget.
