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

print("== Section 5 — Verdict (code rules, fixed templates) ==")
for priority in ("lowest_total_cost", "lowest_monthly_payment", "earliest_payoff"):
    call = verdict(result, priority)
    print(f"verdict(priority={priority}) -> choice={call.choice}")
    print(f"  headline: {call.headline}")
    print(f"  note: {call.tradeoff_note}")
print()


print("== Scenarios — step-by-step trace of compare() + verdict() ==")
SCENARIOS = [
    ("payment trap (longer term buries the win)",
     CurrentLoan(balance=15000.0, annual_rate=0.07, remaining_months=36),
     RefinanceOffer(annual_rate=0.06, term_months=72)),
    ("clear win (same term, lower rate)",
     CurrentLoan(balance=25000.0, annual_rate=0.11, remaining_months=48),
     RefinanceOffer(annual_rate=0.075, term_months=48, fees=300.0)),
    ("too close to call on total ($24.76 apart)",
     CurrentLoan(balance=20000.0, annual_rate=0.09, remaining_months=40),
     RefinanceOffer(annual_rate=0.06, term_months=60)),
    ("financed fee (fee + its interest sit in costs)",
     CurrentLoan(balance=18450.0, annual_rate=0.089, remaining_months=41),
     RefinanceOffer(annual_rate=0.0549, term_months=48, fees=250.0, fees_financed=True)),
]


def trace(name, current, offer):
    print(f"--- {name} ---")
    print(f"inputs: balance={money(current.balance)} rate={current.annual_rate:.4%} "
          f"left={current.remaining_months}mo penalty={money(current.prepayment_penalty)} "
          f"-> offer rate={offer.annual_rate:.4%} term={offer.term_months}mo "
          f"fees={money(offer.fees)} financed={offer.fees_financed}")
    # Step 1: monthly payments straight from the amortization formula.
    keep_pay = monthly_payment(current.balance, current.annual_rate, current.remaining_months)
    new_balance = current.balance + (offer.fees if offer.fees_financed else 0.0)
    refi_pay = monthly_payment(new_balance, offer.annual_rate, offer.term_months)
    print(f"step 1 payments: keep={money(keep_pay)}/mo refi={money(refi_pay)}/mo "
          f"change={money(refi_pay - keep_pay)}/mo")
    # Step 2: headline totals from compare(); savings > 0 means refinancing saves.
    out = compare(current, offer)
    print(f"step 2 totals: keep={money(out.keep_total)} refi={money(out.refi_total)} "
          f"savings={money(out.total_savings)} cash_due_today={money(out.cash_due_today)}")
    # Step 3: rate-first split legs, recomputed here so each leg is visible:
    # rate prices the new rate over the SAME remaining term, term prices the
    # timeline change at the offered rate, costs carry fees/penalty/burden.
    same_term = monthly_payment(current.balance, offer.annual_rate, current.remaining_months)
    same_term_total = same_term * current.remaining_months
    new_term = monthly_payment(current.balance, offer.annual_rate, offer.term_months)
    new_term_total = new_term * offer.term_months
    print(f"step 3 split legs: same-term@{offer.annual_rate:.4%}={money(same_term_total)} "
          f"new-term-unfinanced={money(new_term_total)}")
    print(f"  rate_effect={money(out.rate_effect)} (= keep - same-term)")
    print(f"  term_effect={money(out.term_effect)} (= same-term - new-term)")
    print(f"  costs_effect={money(out.costs_effect)} (= new-term - real offer)")
    print(f"  check: split sum={money(out.rate_effect + out.term_effect + out.costs_effect)} "
          f"== savings={money(out.total_savings)}")
    # Step 4: breakeven and the engine's cheapest-total label (ties -> equal).
    print(f"step 4 breakeven_month={out.breakeven_month} lowest_total_cost={out.lowest_total_cost}")
    # Step 5: code-written verdict per priority — the model only narrates this.
    for priority in ("lowest_total_cost", "lowest_monthly_payment", "earliest_payoff"):
        call = verdict(out, priority)
        print(f"step 5 [{priority}] -> {call.choice}: {call.headline}")
        print(f"  note: {call.tradeoff_note}")


for _name, _current, _offer in SCENARIOS:
    trace(_name, _current, _offer)
    print()
