# Eval report

| scenario | priority | verdict | correct | wrong | needs_fix | explain | verdict_ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| balance-among-numbers | lowest_monthly_payment | refinance_now | 7/7 | — | — | verified | yes |
| clean | lowest_total_cost | refinance_now | 7/7 | — | — | verified | yes |
| fees-method-unstated | lowest_total_cost | refinance_now | 7/8 | — | offer.fees_financed | rewritten | yes |
| fees-rolled-in | lowest_total_cost | refinance_now | 8/8 | — | — | verified | yes |
| fees-upfront | lowest_total_cost | keep | 8/8 | — | — | verified | yes |
| messy-paste | lowest_total_cost | refinance_now | 7/7 | — | — | verified | yes |
| near-tie | lowest_total_cost | too_close | 8/8 | — | — | verified | yes |
| no-penalty-mentioned | lowest_monthly_payment | refinance_now | 8/8 | — | — | verified | yes |
| payment-trap | lowest_total_cost | keep | 7/7 | — | — | verified | yes |
| percent-penalty | lowest_total_cost | too_close | 6/7 | — | loan.prepayment_penalty | verified | yes |
| spoken-rate | lowest_total_cost | refinance_now | 7/8 | — | offer.annual_rate_pct | verified | yes |
| words-amounts | lowest_monthly_payment | refinance_now | 8/8 | — | — | verified | yes |
| years-remaining | earliest_payoff | keep | 7/8 | — | loan.remaining_months | verified | yes |

## Summary

- grounded and correct / stated fields: 95/98 (96.9%)
- wrong-value rate: 0/99 (0.0%), target zero
- confirmation-edit rate: 4/99 (4.0%)
- explanation outcomes: rewritten/- ×1, verified/- ×12
- verdict flips (extracted vs true): 0
- cached tokens / prompt tokens: 16507/23165 (71.3%)
