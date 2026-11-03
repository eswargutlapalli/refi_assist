# Eval report

| scenario | priority | verdict | correct | wrong | needs_fix | explain | verdict_ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hold-01 | lowest_total_cost | refinance_now | 7/7 | — | — | verified | yes |
| hold-02 | earliest_payoff | keep | 8/8 | — | — | verified | yes |
| hold-03 | lowest_total_cost | too_close | 6/7 | — | loan.prepayment_penalty | verified | yes |
| hold-04 | lowest_total_cost | keep | 7/8 | — | loan.remaining_months | verified | yes |
| hold-05 | lowest_monthly_payment | refinance_now | 8/8 | — | — | verified | yes |
| hold-06 | lowest_monthly_payment | refinance_now | 7/7 | — | — | verified | yes |
| hold-07 | lowest_total_cost | refinance_now | 8/8 | — | — | verified | yes |
| hold-08 | lowest_total_cost | refinance_now | 8/8 | — | — | verified | yes |
| hold-09 | lowest_total_cost | keep | 7/7 | — | — | verified | yes |
| hold-10 | lowest_total_cost | too_close | 8/8 | — | — | verified | yes |
| hold-11 | lowest_monthly_payment | refinance_now | 7/7 | — | — | verified | yes |
| hold-12 | earliest_payoff | refinance_now | 8/8 | — | — | verified | yes |

## Summary

- grounded and correct / stated fields: 89/91 (97.8%)
- wrong-value rate: 0/91 (0.0%), target zero
- correctly cleared: 2/2 (100.0%)
  - hold-03 loan.prepayment_penalty: cleared as expected
  - hold-04 loan.remaining_months: cleared as expected
- grounded where clear was expected: 0/2 (0.0%)
- confirmation-edit rate: 2/91 (2.2%)
- explanation outcomes: verified/- ×12
- verdict flips (extracted vs true): 0
- cached tokens / prompt tokens: 15972/26125 (61.1%)
