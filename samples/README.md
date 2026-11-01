# Demo samples — multimodal statement input

Synthetic borrower statements for exercising the page-1 upload paths.
All people, lenders, and numbers are invented. No real borrower data.

## The files

| File | Upload as | Input path tested |
|---|---|---|
| `loan_statement_text.pdf` | Current loan statement | Text-layer PDF, read locally, no model call |
| `loan_statement_scan.pdf` | Current loan statement | Image-only scan: rasterized, then vision-transcribed |
| `offer_screenshot.png` | Refinance offer | Clean PNG straight to vision |
| `offer_photo.jpg` | Refinance offer | Photo path: slight tilt and grain, still legible |

## How to use

1. Run the app (`streamlit run app.py`) with `MODEL_API_KEY` exported.
2. On page 1, upload a loan file in the "Upload loan statement" box and
   an offer file in the "Upload refinance offer" box.
3. The transcript lands in the editable text box above each uploader.
   Photos show side by side with their transcript; scans show the
   transcript plus a caption.
4. Press Continue, review every number on page 2, Confirm, and read the
   verdict on page 3.

Suggested pairing: `loan_statement_text.pdf` with `offer_photo.jpg`.
That covers the local text-layer path and the vision path in one run.

## What each file tests

`loan_statement_text.pdf` — the free path. Expect source caption "Text
from your PDF" and all four loan terms grounded: balance $16,200.00,
APR 8.9%, 42 payments remaining, $0 penalty.

`loan_statement_scan.pdf` — the rasterize path (1 page, well under the
3-page refusal cap). Expect the vision caption ("check it carefully")
and the same four grounded terms as the text PDF.

`offer_screenshot.png` — clean-image vision. Expect the vision caption
and three grounded terms: 4.79% APR, 60 months, $199 fee paid at
signing (upfront, so the fee radio stays hidden).

`offer_photo.jpg` — degraded-image vision. Expect the same three terms
as the screenshot. If any digit misreads, the transcript shows it next
to the photo: fix it in the box or on page 2 before confirming. That
fix-before-compute loop is the behavior under test.

## Expected end-to-end result

Confirming the loan terms ($16,200.00, 8.9%, 42 months, $0 penalty)
with the offer terms (4.79%, 60 months, $199 upfront) computes:

- Keep: $450.32/mo, $18,913.45 total.
- Refinance: $304.16/mo, $18,448.47 total, $199.00 due today.
- Savings $464.98 in total; payment drops $146.16/mo; breakeven month 2.
- Split: lower rate saves $1,285.33; longer term costs $621.34; fees
  and charges cost $199.00.
- Lowest total cost: "Refinancing saves you $464.98 in total."
- Lowest monthly payment: "Refinancing lowers your payment by $146.16
  a month."
- Earliest payoff: "Your current loan pays off first — 18 months
  sooner."

If any uploaded transcript misreads a digit, the confirmed numbers —
and therefore the verdict above — change accordingly. That is correct
behavior: the app computes from confirmed terms, never from the upload.
