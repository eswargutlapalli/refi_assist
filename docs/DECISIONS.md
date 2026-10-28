# DECISIONS.md — settled engine decisions (2026-10-28)

Short record: decision, reason, rejected alternative. Split order is provisional, pending grill decision 16.

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

Provisional: split presentation order (rate, term, costs) is not settled; pending grill decision 16.
