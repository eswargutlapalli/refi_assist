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
