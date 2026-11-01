# Eval report

| scenario | priority | verdict | correct/8 | wrong | needs_fix | explain | verdict_ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| balance-among-numbers | lowest_monthly_payment | refinance_now | 6/8 | — | loan.balance, loan.remaining_months | template | yes |
| clean | lowest_total_cost | refinance_now | 7/8 | — | offer.fees_financed | verified | yes |
| fees-method-unstated | lowest_total_cost | refinance_now | 6/8 | — | offer.term_months, offer.fees_financed | verified | yes |
| fees-rolled-in | lowest_total_cost | refinance_now | 7/8 | — | loan.annual_rate_pct | verified | yes |
| fees-upfront | lowest_total_cost | keep | 6/8 | — | loan.annual_rate_pct, offer.annual_rate_pct | verified | yes |
| messy-paste | lowest_total_cost | refinance_now | 5/8 | — | loan.annual_rate_pct, loan.remaining_months, loan.prepayment_penalty | verified | yes |
| near-tie | lowest_total_cost | too_close | 6/8 | — | offer.annual_rate_pct, offer.term_months | verified | yes |
| no-penalty-mentioned | lowest_monthly_payment | refinance_now | 7/8 | — | offer.annual_rate_pct | rewritten | yes |
| payment-trap | lowest_total_cost | keep | 7/8 | — | loan.annual_rate_pct | verified | yes |
| percent-penalty | lowest_total_cost | too_close | 6/8 | — | loan.annual_rate_pct, loan.prepayment_penalty | rewritten | yes |
| spoken-rate | lowest_total_cost | refinance_now | 7/8 | — | offer.annual_rate_pct | verified | yes |
| words-amounts | lowest_monthly_payment | refinance_now | 7/8 | — | offer.annual_rate_pct | verified | yes |
| years-remaining | earliest_payoff | keep | 5/8 | — | loan.annual_rate_pct, loan.remaining_months, offer.term_months | verified | yes |

## Summary

- grounded and correct / stated fields: 82/98 (83.7%)
- wrong-value rate: 0/104 (0.0%), target zero
- confirmation-edit rate: 22/104 (21.2%)
- explanation outcomes: rewritten/- ×2, template/failed_checks ×1, verified/- ×10
- verdict flips (extracted vs true): 0
- cached tokens / prompt tokens: 21228/30892 (68.7%)
