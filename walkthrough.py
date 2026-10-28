"""Walkthrough harness for engine.py. Convention for the whole build:

- One `walkthrough_<module>.py` per module, kept next to the code.
- It runs the REAL functions on a SYNTHETIC example and prints each call
  with its inputs and outputs — never hand-filled numbers.
- Rerun after every change to the module: `python3 walkthrough.py`.
"""

from engine import (
    CurrentLoan,
    RefinanceOffer,
    cashflows,
    compare,
    monthly_payment,
    remaining_balance,
    schedule,
    verdict,
    wait_breakeven_rate,
    wait_plan,
)

CURRENT = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=0.0)
OFFER = RefinanceOffer(annual_rate=0.06, term_months=60, fees=0.0, fees_financed=False)
WAIT_RATES = (0.055, 0.05)


def money(x: float) -> str:
    if x == 0:
        x = 0.0  # display -$0.00 (negative zero) as $0.00
    return f"${x:,.2f}"


print("== Section 1 — Inputs ==")
print(f"CurrentLoan(balance={CURRENT.balance}, annual_rate={CURRENT.annual_rate}, "
      f"remaining_months={CURRENT.remaining_months}, prepayment_penalty={CURRENT.prepayment_penalty})")
print(f"RefinanceOffer(annual_rate={OFFER.annual_rate}, term_months={OFFER.term_months}, "
      f"fees={OFFER.fees}, fees_financed={OFFER.fees_financed})")
print(f"wait_rates={WAIT_RATES}")
print()

print("== Section 3 — Calculation logic ==")
keep_pay = monthly_payment(CURRENT.balance, CURRENT.annual_rate, CURRENT.remaining_months)
print(f"monthly_payment(balance=20000, rate=0.09, months=40) -> {money(keep_pay)}  [keep payment]")
refi_pay = monthly_payment(CURRENT.balance, OFFER.annual_rate, OFFER.term_months)
print(f"monthly_payment(balance=20000, rate=0.06, months=60) -> {money(refi_pay)}  [refi payment]")
rows = schedule(CURRENT.balance, CURRENT.annual_rate, CURRENT.remaining_months)
print(f"schedule(...) -> {len(rows)} rows; first row interest={money(rows[0][0])} "
      f"principal={money(rows[0][1])} balance={money(rows[0][2])}")
print(f"schedule(...) -> last row interest={money(rows[-1][0])} "
      f"principal={money(rows[-1][1])} balance={money(rows[-1][2])}")
bal12 = remaining_balance(CURRENT.balance, CURRENT.annual_rate, CURRENT.remaining_months, 12)
print(f"remaining_balance(..., paid=12) -> {money(bal12)}  [matches schedule row 12: {money(rows[11][2])}]")
print()

print("== Section 4 — Options evaluation ==")
print("compare(current, offer) calls _total -> monthly_payment internally, then splits:")
result = compare(CURRENT, OFFER)
print(f"keep:    {money(result.keep_monthly)}/mo  total={money(result.keep_total)}")
print(f"refi:    {money(result.refi_monthly)}/mo  total={money(result.refi_total)}  (incl. fees+penalty)")
print(f"split:   rate_effect={money(result.rate_effect)}  term_effect={money(result.term_effect)}  "
      f"costs_effect={money(result.costs_effect)}")
split = result.rate_effect + result.term_effect + result.costs_effect
print(f"check:   split sum={money(split)}  total_savings={money(result.total_savings)}")
print(f"savings: total_savings={money(result.total_savings)}  (positive means refinancing saves)")
print(f"interest: keep={money(result.keep_interest)}  refi={money(result.refi_interest)}")
print(f"change: monthly_change={money(result.monthly_change)}/mo  cash_due_today={money(result.cash_due_today)} "
      f"payoff keep={result.months_to_payoff_keep}mo refi={result.months_to_payoff_refi}mo")
print(f"breakeven: month {result.breakeven_month}  (None means never within the horizon)")
print(f"label:   lowest_total_cost={result.lowest_total_cost}")
for rate in WAIT_RATES:
    plan = wait_plan(CURRENT, OFFER, 0, rate)
    print(f"wait @{plan.annual_rate:.3f}: {money(plan.monthly)}/mo  total={money(plan.total)}")
print()

print("== Cash flows by month (no-fee example) ==")
print(f"{'mo':>3} {'keep_pay':>9} {'keep_cum':>10} {'refi_pay':>9} {'refi_cum':>10}  cheaper_so_far")
for row in cashflows(CURRENT, OFFER):
    leader = "refi" if row.refi_cumulative <= row.keep_cumulative else "keep"
    mark = "  <== breakeven" if row.month == result.breakeven_month else ""
    print(f"{row.month:>3} {money(row.keep_payment):>9} {money(row.keep_cumulative):>10} "
          f"{money(row.refi_payment):>9} {money(row.refi_cumulative):>10}  {leader}{mark}")
print()

print("== Breakeven with fees and penalty (different example) ==")
CURRENT2 = CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40, prepayment_penalty=150.0)
OFFER2 = RefinanceOffer(annual_rate=0.06, term_months=60, fees=300.0, fees_financed=False)
result2 = compare(CURRENT2, OFFER2)
upfront2 = OFFER2.fees + CURRENT2.prepayment_penalty
monthly_save2 = result2.keep_monthly - result2.refi_monthly
print(f"upfront={money(upfront2)}  saves {money(monthly_save2)}/mo  "
      f"total_savings={money(result2.total_savings)}  breakeven_month={result2.breakeven_month}")
print()

print("== Waiting 3 vs 6 months, then refinancing at 5% ==")
for wait_months in (3, 6):
    plan = wait_plan(CURRENT, OFFER, wait_months, 0.05)
    print(f"wait {plan.wait_months}mo @5%: paid_while_waiting={money(plan.paid_while_waiting)} "
          f"balance_at_refi={money(plan.balance_at_refi)} new_payment={money(plan.monthly)} "
          f"total={money(plan.total)}")
    print(f"  of which interest_while_waiting={money(plan.interest_while_waiting)} "
          f"(the rest cut principal)")
for wait_months in (3, 6):
    answer = wait_breakeven_rate(CURRENT, OFFER, wait_months)
    if answer.rate is None:
        print(f"wait {wait_months}mo: no scenario rate beats {answer.baseline} ({money(answer.baseline_total)})")
    else:
        # Conditional only: at-or-below this rate waiting wins; no forecast implied.
        print(f"wait {wait_months}mo: beats {answer.baseline} ({money(answer.baseline_total)}) "
              f"only in scenarios at or below {answer.rate:.4%}")
print()

print("== Section 5 — Summary and verdict gate ==")
try:
    verdict()
except NotImplementedError as exc:
    print(f"verdict() -> NotImplementedError: {exc}")
