"""app.py — Streamlit confirm gate and results (plan step 3).

Why this module exists: extraction copies terms, but the user confirms them
before any calculation runs (rule 3.3). This screen is that gate: paste both
statements, extract, edit every number, then compute.

No math lives here. Building engine objects, compare(), and verdict() do all
the arithmetic; this file only formats engine output for display. Display
carries directional words, never signs (decision 12).

Slice scope: confirm gate + compare/verdict results + wait scenarios
(thresholds table, try-a-rate comparison, tradeoff line) for waits 3/6/9/12
below the remaining months. The model explainer and number verification
arrive in later slices.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

from engine import (
    CurrentLoan,
    RefinanceOffer,
    compare,
    compare_wait,
    verdict,
    wait_thresholds,
)
from extract import ExtractionResult, FieldOutcome, extract_current_loan, extract_refinance_offer
from verify import split_rows  # one source for the split wording (decision 12)

DISCLAIMER = (
    "Educational estimate only — not a loan offer, application, or "
    "personalized financial advice. All numbers are computed locally "
    "from the terms you confirm below."
)

PRIORITIES = (
    ("Lowest total cost (default)", "lowest_total_cost"),
    ("Lowest monthly payment", "lowest_monthly_payment"),
    ("Earliest payoff", "earliest_payoff"),
)

LOAN_FIELDS = ("balance", "annual_rate_pct", "remaining_months", "prepayment_penalty")
OFFER_FIELDS = ("annual_rate_pct", "term_months", "fees", "fees_financed")


def _apply_deploy_secret(st: Any) -> None:
    """Copy the deploy secret into the environment when it is missing there.

    The key comes from the environment; on a hosted deploy there is no
    shell to export it from, so Streamlit secrets fill the gap instead.
    An exported key always wins, and no secrets file means no-op (local
    runs export the key themselves)."""
    try:
        secret = st.secrets["MODEL_API_KEY"]
    except Exception:
        return  # no secrets configured — local run, nothing to copy
    if secret:
        os.environ.setdefault("MODEL_API_KEY", secret)


def format_money(value: float) -> str:
    """Display only: comma-grouped dollars, never a sign (words carry direction)."""
    return f"${abs(value):,.2f}"


def escape_display(text: str) -> str:
    """Escape for Streamlit markdown: `$...$` renders as LaTeX, so a sentence
    with two dollar amounts loses its `$` signs. Escape ONLY here, at display:
    engine strings and format_money stay plain, because verify.py checks the
    plain text."""
    return text.replace("$", "\\$")


def wait_option_label(months: int) -> str:
    """One wait-dropdown option: the count reads as months, not a bare number."""
    return f"{months} months"


def format_rate_floor(rate: float) -> str:
    """Display only: scenario rates round DOWN to two decimals (5.1068% as
    5.10%), never overstating the future. The epsilon rescues float dust
    (4.50% stored as 4.4999999...), never a real fraction."""
    return f"{math.floor(rate * 10000 + 1e-9) / 100:.2f}%"


_BASELINE_NAMES = {
    "keep": "keeping your loan",
    "refinance_now": "refinancing now",
    "equal": "today's tied options (shown: keeping your loan)",
}


def format_threshold_rate(rate: float | None) -> str:
    """One table cell: the future rate a wait needs, or why no rate works."""
    if rate is None:
        return "unreachable — even 0% can't win"
    return f"below {format_rate_floor(rate)}"


def describe_thresholds_heading(thresholds: Any) -> str:
    """The thresholds table in one line: which today it must beat. The
    offer rate gets its own line — naming it here would read as if a keep
    baseline were priced at the offer rate."""
    name = _BASELINE_NAMES[thresholds.baseline]
    return (
        f"To beat {name} ({format_money(thresholds.baseline_total)} in total), "
        "you'd need rates below:"
    )


def today_column_label(baseline: str) -> str:
    """The try-a-rate table's today column: the named cheaper option, with
    ties shown as keeping the loan. No total here — it sits one row down."""
    return f"Today: {_BASELINE_NAMES[baseline]}"


def _months_word(months: int) -> str:
    return f"{abs(months)} month{'s' if abs(months) != 1 else ''}"


def describe_wait_result(compared: Any) -> str:
    """One scenario's bottom line in tradeoff style: what waiting does to
    the total and to the payoff date. 'And' joins directions that agree
    (both favor waiting, or both disfavor it); 'but' marks a real tradeoff."""
    rate = format_rate_floor(compared.plan.annual_rate)
    saved = compared.savings_vs_baseline
    late = compared.months_vs_baseline
    if saved > 0:
        total = f"saves {format_money(saved)} in total"
    elif saved < 0:
        total = f"costs {format_money(saved)} more in total"
    else:
        total = "ties in total"
    if late > 0:
        timing = f"you finish {_months_word(late)} later"
    elif late < 0:
        timing = f"you finish {_months_word(late)} earlier"
    else:
        timing = "you finish at the same time"
    if saved == 0 and late == 0:
        return f"At {rate}, waiting matches {_BASELINE_NAMES[compared.baseline]} exactly."
    connector = "and" if (saved > 0) == (late < 0) else "but"
    return f"At {rate}, waiting {total}, {connector} {timing}."


def build_current_loan(balance: float, rate_pct: float, months: int, penalty: float) -> CurrentLoan:
    """Confirmed inputs to engine terms. Percent-to-decimal is code's job;
    the engine validates ranges last and raises on bad input."""
    return CurrentLoan(
        balance=balance,
        annual_rate=rate_pct / 100,
        remaining_months=int(months),
        prepayment_penalty=penalty,
    )


def build_offer(rate_pct: float, term_months: int, fees: float, fees_financed: bool) -> RefinanceOffer:
    """Confirmed inputs to engine terms for the offer under evaluation."""
    return RefinanceOffer(
        annual_rate=rate_pct / 100,
        term_months=int(term_months),
        fees=fees,
        fees_financed=bool(fees_financed),
    )


def default_from_outcome(outcome: FieldOutcome) -> float | bool | None:
    """Prefill for the confirm fields: grounded values only, never guesses."""
    return outcome.value if outcome.status == "grounded" else None


INPUT_DEFAULTS = {
    # Every confirm field starts blank (None), never 0: the gate decides
    # which blanks may mean none. Grounded values are mirrored separately
    # into state["extracted"] (see _apply_extraction) so captions can name
    # edits; inputs themselves carry only what the boxes hold.
    # wait_months keeps its dropdown default; priority is a preference,
    # not an extracted term, so it keeps its default too.
    "loan_balance": None,
    "loan_rate_pct": None,
    "loan_months": None,
    "loan_penalty": None,
    "offer_rate_pct": None,
    "offer_term": None,
    "offer_fees": None,
    "fees_choice": None,
    "confirmed": False,
    "priority": "lowest_total_cost",
    "wait_months": 6,
    "wait_rate_pct": None,
}

# Widget keys die with their page; these plain keys carry the numbers across.
_WIDGET_TO_INPUT = {
    "w_loan_balance": "loan_balance",
    "w_loan_annual_rate_pct": "loan_rate_pct",
    "w_loan_remaining_months": "loan_months",
    "w_loan_prepayment_penalty": "loan_penalty",
    "w_offer_annual_rate_pct": "offer_rate_pct",
    "w_offer_term_months": "offer_term",
    "w_offer_fees": "offer_fees",
    "w_offer_fees_financed_choice": "fees_choice",
}


def _num_input(st: Any, label: str, widget_key: str, value: float | None, **kwargs: Any) -> None:
    """Declare a confirm box. A brand-new widget renders value (None shows
    blank); a live widget keeps the user's typed number — passing value
    alongside existing widget state warns and loses."""
    create = {} if widget_key in st.session_state else {"value": value}
    st.number_input(label, key=widget_key, **create, **kwargs)

FEE_CHOICES = ("Paid upfront", "Rolled into the new loan")


def gate_status(confirmed: bool) -> list[str]:
    """The confirm gate as a predicate: the user reviewed the numbers and
    pressed Confirm. A missed gate names the blocker; an empty list means
    compute."""
    return [] if confirmed else ["confirmation"]


def gate_message() -> str:
    """The blocked-gate wording: names the Confirm button that unblocks it."""
    return "Not computing yet — review the numbers on page 2 and press Confirm."


_BLANK_MEANS_NONE = {
    "loan_penalty": ("loan", "prepayment_penalty"),
    "offer_fees": ("offer", "fees"),
}

_STRUCTURAL_POSITIVES = ("loan_balance", "loan_months", "offer_term")

_REQUIRED_LABELS = (
    ("loan_balance", "loan.balance"),
    ("loan_rate_pct", "loan.rate"),
    ("loan_months", "loan.remaining_months"),
    ("loan_penalty", "loan.prepayment_penalty"),
    ("offer_rate_pct", "offer.rate"),
    ("offer_term", "offer.term_months"),
    ("offer_fees", "offer.fees"),
    ("fees_choice", "offer.fees_financed"),
)


def stated_but_ungrounded(prefix: str, name: str, result: Any) -> bool:
    """True when extraction ran and the model pointed at words for this
    field, but nothing grounded — e.g. '2% of the remaining balance' for a
    dollar penalty. Blank here is the likeliest wrong value, so the field
    must be entered. A null quote means the model pled absence: unstated."""
    if result is None:
        return False
    outcome = result.fields.get(name)
    return outcome is not None and outcome.status != "grounded" and bool(outcome.quote)


def missing_required(inputs: dict[str, Any], must_enter: frozenset = frozenset()) -> list[str]:
    """Blank loan terms always block; a zero balance, loan term, or offer
    term is structurally invalid, so it blocks too. Blank penalty and fees
    mean none — unless the statement said something unverifiable about them
    (must_enter), when blank is the likeliest wrong value. Pressing Confirm
    is the review. The fee-payment choice only matters when fees exist."""
    missing = []
    for key, label in _REQUIRED_LABELS:
        value = inputs[key]
        if value is None:
            if key in _BLANK_MEANS_NONE and _BLANK_MEANS_NONE[key] not in must_enter:
                continue
            if key == "fees_choice" and not inputs["offer_fees"]:
                continue
            missing.append(label)
        elif key in _STRUCTURAL_POSITIVES and value <= 0:
            missing.append(label)
    return missing





_LOAN_INPUTS = {
    "balance": "loan_balance",
    "annual_rate_pct": "loan_rate_pct",
    "remaining_months": "loan_months",
    "prepayment_penalty": "loan_penalty",
}
_OFFER_INPUTS = {
    "annual_rate_pct": "offer_rate_pct",
    "term_months": "offer_term",
    "fees": "offer_fees",
    "fees_financed": "fees_choice",
}


def _apply_extraction(
    state: Any, prefix: str, names: tuple[str, ...], result: ExtractionResult
) -> None:
    """Copy grounded values into the plain inputs and delete the widgets so
    they re-create from those inputs. A field that did not ground resets to
    empty — a previous statement's value never leaks into this one. Any
    Confirm unticks: fresh numbers always need a fresh review, never a
    stale confirmation. The wait scenario rate also re-defaults to the new
    offer APR."""
    names_inputs = _LOAN_INPUTS if prefix == "loan" else _OFFER_INPUTS
    extracted = state.setdefault("extracted", {})
    for name in names:
        # A field that did not ground resets to empty, so a previous
        # statement's value never leaks into this one. Widget keys are
        # deleted, not zeroed: a None session value coerces back to the
        # widget default, which _remember would copy over the reset.
        # Deletion forces re-creation, and declarations below render
        # value=/index= from inputs (None shows blank / unselected).
        # Month counts land as int: the model reports floats (43.0), and a
        # float value with int min/step crashes the widget as mixed types.
        # Grounded values are also recorded, so an edit names what changed.
        value = default_from_outcome(result.fields[name])
        if value is not None and name in ("remaining_months", "term_months"):
            value = int(value)
        input_key = names_inputs[name]
        if name == "fees_financed":
            # The radio speaks choices, the record keeps the boolean.
            state["inputs"][input_key] = (
                ("Rolled into the new loan" if value else "Paid upfront")
                if value is not None else None
            )
            widget_key = "w_offer_fees_financed_choice"
        else:
            state["inputs"][input_key] = value
            widget_key = f"w_{prefix}_{name}"
        if value is None:
            extracted.pop(input_key, None)
        else:
            extracted[input_key] = value
        if widget_key in state:
            del state[widget_key]
    state["inputs"]["confirmed"] = False
    state["inputs"]["wait_rate_pct"] = None


def needs_extract(text: str, extracted_text: str | None, result: Any) -> bool:
    """Parse on Continue only when there are words to read and they are not
    the ones already parsed — going back and forth never re-spends budget."""
    if not text or not text.strip():
        return False
    return result is None or text != extracted_text


EXTRACTION_LIMIT = 10
EXTRACTION_LIMIT_MESSAGE = (
    "Demo limit reached for this session; you can still enter "
    "numbers by hand on the next page"
)


def extractions_used(state: Any) -> int:
    """How many extraction calls this session has spent. The count lives in
    session state, so a rerun or a new deploy starts a fresh budget."""
    try:
        return int(state.get("extraction_calls", 0) or 0)
    except (TypeError, ValueError):
        return 0


def extraction_blocked(state: Any) -> bool:
    """True once the session's demo budget is spent. Manual entry never
    checks this — only model calls do."""
    return extractions_used(state) >= EXTRACTION_LIMIT


def record_extraction(state: Any) -> None:
    """Spend one extraction call: exactly one model invocation, win or fail."""
    state["extraction_calls"] = extractions_used(state) + 1


def _parse_side(st: Any, label: str, prefix: str, names: tuple[str, ...], action: Any) -> None:
    """Run one side's extraction if its text is new, and record the outcome.
    Failures are stored for page 2 — the manual path below still works."""
    state = st.session_state
    text = state[f"{prefix}_text"]
    if not needs_extract(text, state.get(f"extracted_{prefix}_text"), state.get(f"{prefix}_result")):
        return
    if extraction_blocked(state):
        return  # budget spent: boxes keep what the user typed, no API call
    record_extraction(state)
    try:
        with st.spinner(f"Reading {label} terms…"):
            result = action(text)
    except Exception as exc:  # fail loudly, on page 2, with the manual fallback beside it
        state[f"{prefix}_error"] = f"{label.capitalize()} extraction failed: {exc}"
        # A failed read resets the side like a fresh extraction with nothing
        # grounded: result, recorded values, inputs, and widgets all go, so
        # no old number sits in the boxes under "couldn't read the statement".
        state[f"{prefix}_result"] = None
        side_inputs = _LOAN_INPUTS if prefix == "loan" else _OFFER_INPUTS
        for name, input_key in side_inputs.items():
            state["inputs"][input_key] = None
            state.setdefault("extracted", {}).pop(input_key, None)
            widget_key = (
                "w_offer_fees_financed_choice"
                if name == "fees_financed" else f"w_{prefix}_{name}"
            )
            if widget_key in state:
                del state[widget_key]
    else:
        state[f"{prefix}_result"] = result
        state[f"extracted_{prefix}_text"] = text
        state[f"{prefix}_error"] = None
        _apply_extraction(state, prefix, names, result)


def _upload_fingerprint(upload: Any) -> tuple[str, str]:
    """Name plus content hash: re-uploading an edited file under the same
    name still counts as new."""
    return (upload.name, hashlib.sha256(upload.getvalue()).hexdigest())


def is_fresh_upload(upload: Any, stored: tuple[str, str] | None) -> bool:
    """True when there is a file the screen has not absorbed yet. An unknown
    fingerprint reloads — re-reading text the user already sees is harmless,
    silently dropping an edit is not."""
    if upload is None:
        return False
    return stored is None or _upload_fingerprint(upload) != stored


def _read_upload(upload: Any) -> str | None:
    """Decode an uploaded .txt/.md statement. Binary or undecodable files
    fail loudly instead of silently garbling the source text."""
    if upload is None:
        return None
    try:
        return upload.getvalue().decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"could not read {upload.name} as text: {exc}")


def _page_input(st: Any) -> None:
    """Page 1: statements in — typed, pasted, or uploaded as text files."""
    st.header("1 · Enter your statements")
    st.text_area("Current loan statement", key="loan_text")
    st.text_area("Refinance offer", key="offer_text")
    st.write("Or upload them as `.txt` files — the text lands above, editable.")
    for key, label, target, applied in (
        ("up_loan_file", "Upload loan statement", "loan_text", "applied_loan_file"),
        ("up_offer_file", "Upload refinance offer", "offer_text", "applied_offer_file"),
    ):
        upload = st.file_uploader(label, type=["txt", "md"], key=key)
        if is_fresh_upload(upload, st.session_state.get(applied)):
            try:
                st.session_state[target] = _read_upload(upload) or ""
            except ValueError as exc:
                st.error(f"Upload failed: {exc}")
            else:
                st.session_state[applied] = _upload_fingerprint(upload)
    st.caption("Photos, screenshots, and PDFs arrive in a later slice — "
               "for now, paste their text above or upload a `.txt` file.")
    st.caption("Continuing parses both statements automatically — "
               "you review, edit, and confirm everything on the next page.")
    if extraction_blocked(st.session_state):
        st.write(EXTRACTION_LIMIT_MESSAGE)
    _, center, _ = st.columns([2, 1, 2])
    with center:
        if st.button("Continue", type="primary", key="to_page2",
                     use_container_width=True):
            _parse_side(st, "loan", "loan", LOAN_FIELDS, extract_current_loan)
            _parse_side(st, "offer", "offer", OFFER_FIELDS, extract_refinance_offer)
            st.session_state["page"] = 2
            st.rerun()


def field_caption(prefix: str, name: str, result: Any,
                  blank_means_none: bool = False,
                  read_error: bool = False) -> str:
    """Per-field provenance under its confirm box. A failed read says so.
    Grounded names the quote it came from in plain text; unstated asks for
    typing (or a blank where blank means none); stated-but-ungrounded
    always asks for typing, since blank is the likeliest wrong value."""
    if read_error:
        return "couldn't read the statement"
    if result is None:
        return (
            "not in your statement — leave blank for none"
            if blank_means_none else "not in your statement, please enter"
        )
    outcome = result.fields.get(name)
    if outcome is not None and outcome.status == "grounded" and outcome.quote:
        return f"from: {outcome.quote}"
    if outcome is not None and outcome.status == "not_stated":
        return (
            "not found in your statement — check it, then leave blank for none"
            if blank_means_none else "not found in your statement, please enter"
        )
    if blank_means_none and not stated_but_ungrounded(prefix, name, result):
        return "couldn't verify — leave blank for none"
    return "couldn't verify, please enter"


def _display_amount(value: Any, unit: str = "") -> str:
    """Statement values in plain words with their unit: dollars grouped,
    percents suffixed, month counts bare, financed/upfront for the fee flag."""
    if isinstance(value, bool):
        return "financed" if value else "upfront"
    if unit == "$":
        return format_money(value)
    if unit == "%":
        return f"{value}%"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value}"


def edited_note(current: Any, extracted: Any, unit: str = "") -> str:
    """Names a user edit against what the statement said, with its unit.
    Empty means the box still holds the extracted value (or nothing was
    ever extracted). Callers normalize the fee flag to boolean first."""
    if extracted is None or current == extracted:
        return ""
    return f"edited by you (statement said {_display_amount(extracted, unit)})"


def _page_confirm(st: Any) -> None:
    """Page 2: review the parsed numbers, edit, and confirm."""
    st.header("2 · Confirm the numbers")
    for prefix in ("loan", "offer"):
        error = st.session_state.get(f"{prefix}_error")
        if error:
            st.error(f"{error} — enter the numbers by hand below.")
    st.write(
        "Review each number and edit what is wrong. Pressing Confirm "
        "means these are right — nothing computes before that."
    )
    _remember(st)
    inputs = st.session_state["inputs"]
    _num_input(st, "Balance owed ($)", "w_loan_balance", inputs["loan_balance"],
               min_value=0.0, step=100.0)
    st.caption(f"Balance: {_cap(st, 'loan', 'loan_balance', 'balance')}")
    _num_input(st, "Current APR (%)", "w_loan_annual_rate_pct", inputs["loan_rate_pct"],
               min_value=0.0, step=0.1)
    st.caption(f"Current APR: {_cap(st, 'loan', 'loan_rate_pct', 'annual_rate_pct')}")
    _num_input(st, "Payments remaining (months)", "w_loan_remaining_months", inputs["loan_months"],
               min_value=0, step=1)
    st.caption(f"Payments remaining: {_cap(st, 'loan', 'loan_months', 'remaining_months')}")
    _num_input(st, "Prepayment penalty ($)", "w_loan_prepayment_penalty", inputs["loan_penalty"],
               min_value=0.0, step=10.0)
    st.caption(f"Prepayment penalty: {_cap(st, 'loan', 'loan_penalty', 'prepayment_penalty', True)}")
    _num_input(st, "Offer APR (%)", "w_offer_annual_rate_pct", inputs["offer_rate_pct"],
               min_value=0.0, step=0.1)
    st.caption(f"Offer APR: {_cap(st, 'offer', 'offer_rate_pct', 'annual_rate_pct')}")
    _num_input(st, "Offer term (months)", "w_offer_term_months", inputs["offer_term"],
               min_value=0, step=12)
    st.caption(f"Offer term: {_cap(st, 'offer', 'offer_term', 'term_months')}")
    _num_input(st, "Offer fees ($)", "w_offer_fees", inputs["offer_fees"],
               min_value=0.0, step=25.0)
    st.caption(f"Offer fees: {_cap(st, 'offer', 'offer_fees', 'fees', True)}")
    # The choice only matters when there are fees: with blank or zero fees
    # the radio stays hidden and the flag stays empty (blank means none).
    fees_now = st.session_state.get("w_offer_fees")
    if fees_now is None:
        fees_now = inputs["offer_fees"]
    if fees_now:
        if "w_offer_fees_financed_choice" in st.session_state:
            st.radio("Offer fees", FEE_CHOICES, key="w_offer_fees_financed_choice")
        else:
            choice = inputs["fees_choice"]
            st.radio("Offer fees", FEE_CHOICES,
                     index=None if choice is None else FEE_CHOICES.index(choice),
                     key="w_offer_fees_financed_choice")
        st.caption(f"Fee payment: {_cap(st, 'offer', 'fees_choice', 'fees_financed', True)}")
    else:
        inputs["fees_choice"] = None

    labels = [label for label, _ in PRIORITIES]
    if st.session_state.get("w_priority") not in labels:
        st.session_state["w_priority"] = labels[0]
    st.radio("Your priority", labels, key="w_priority")
    left, _, right = st.columns([1, 2, 1])
    with left:
        if st.button("Back", key="back_to_1", use_container_width=True):
            st.session_state["page"] = 1
            st.rerun()
    with right:
        # Pressing Confirm IS the confirmation: these numbers are right.
        # Blank loan terms cannot confirm; blank unstated penalty and fees
        # mean none — but a statement that said something unverifiable must
        # be typed, since blank is the likeliest wrong value there.
        if st.button("Confirm", type="primary", key="confirm",
                     use_container_width=True):
            state = st.session_state
            must = {
                (prefix, name)
                for prefix, names in (("loan", LOAN_FIELDS), ("offer", OFFER_FIELDS))
                for name in names
                if stated_but_ungrounded(prefix, name, state.get(f"{prefix}_result"))
            }
            missing = missing_required(state["inputs"], must)
            if missing:
                st.warning(
                    "Enter your numbers before confirming — still missing: "
                    + ", ".join(missing) + "."
                )
            else:
                state["inputs"]["confirmed"] = True
                state["page"] = 3
                st.rerun()


WAIT_CHOICES = (3, 6, 9, 12)


def wait_options(remaining_months: int) -> tuple[int, ...]:
    """Wait dropdown entries: only waits shorter than the remaining term.
    Waiting past payoff leaves nothing to refinance (engine _validate_wait)."""
    return tuple(m for m in WAIT_CHOICES if m < remaining_months)


def reset_all(state: Any) -> None:
    """Start over means start over: texts, results, errors, uploads, every
    widget, and the plain inputs all go back to fresh. The next render
    re-creates widgets blank from the fresh inputs."""
    for key in (
        "loan_text", "offer_text", "loan_result", "offer_result",
        "loan_error", "offer_error", "extracted_loan_text",
        "extracted_offer_text", "applied_loan_file", "applied_offer_file",
        "up_loan_file", "up_offer_file", "wait_months", "w_wait_rate_pct",
        "w_priority",
    ):
        if key in state:
            del state[key]
    for widget_key in _WIDGET_TO_INPUT:
        if widget_key in state:
            del state[widget_key]
    for key, default in (("loan_text", ""), ("offer_text", "")):
        state[key] = default
    state["inputs"] = dict(INPUT_DEFAULTS)
    state["extracted"] = {}
    state["page"] = 1


def reset_wait_rate_to_offer(state: Any) -> None:
    """Reset action for the scenario-rate button. Wired as the button's
    on_click callback, which runs before any widget instantiates — assigning
    the widget key in the button body instead crashes as already
    instantiated."""
    state["w_wait_rate_pct"] = state["inputs"]["offer_rate_pct"]
    state["inputs"]["wait_rate_pct"] = state["inputs"]["offer_rate_pct"]


def _remember(st: Any) -> None:
    """Copy page-2 widget values into the plain inputs. Runs first on every
    page-2 render — session values are already updated before the script
    body — so leaving the page never loses a typed number. Absent widgets
    (first visit, hidden fee radio) have nothing to copy."""
    state = st.session_state
    for widget_key, input_key in _WIDGET_TO_INPUT.items():
        if widget_key in state:
            state["inputs"][input_key] = state[widget_key]
    if "w_priority" in state:
        state["inputs"]["priority"] = dict(PRIORITIES)[state["w_priority"]]


_EDIT_UNITS = {
    "loan_balance": "$",
    "loan_rate_pct": "%",
    "loan_penalty": "$",
    "offer_rate_pct": "%",
    "offer_fees": "$",
}


def _cap(st: Any, prefix: str, input_key: str, name: str, blank: bool = False) -> str:
    """The caption under one confirm box: an edit note when the box no
    longer holds the extracted value, else the field's provenance."""
    state = st.session_state
    inputs = state["inputs"]
    current = inputs[input_key]
    if input_key == "fees_choice" and current is not None:
        current = current == "Rolled into the new loan"
    edit = edited_note(current, state.get("extracted", {}).get(input_key),
                       _EDIT_UNITS.get(input_key, ""))
    if edit:
        return edit
    return field_caption(
        prefix, name, state.get(f"{prefix}_result"), blank,
        read_error=bool(state.get(f"{prefix}_error")))


def _build_terms(inputs: dict[str, Any]) -> tuple[CurrentLoan, RefinanceOffer]:
    """Confirmed inputs to engine terms. Blank penalty, fees, and flag mean
    none — the gate guarantees every other field is present. Bad input
    raises from the engine, and the page shows it instead of an empty result."""
    return (
        build_current_loan(
            inputs["loan_balance"], inputs["loan_rate_pct"],
            inputs["loan_months"], inputs["loan_penalty"] or 0.0),
        build_offer(
            inputs["offer_rate_pct"], inputs["offer_term"],
            inputs["offer_fees"] or 0.0,
            inputs["fees_choice"] == "Rolled into the new loan"),
    )


def _page_results(st: Any) -> None:
    """Page 3: the code-written verdict plus wait scenarios under the
    dropdown. Waiting is a condition on future rates, never a verdict."""
    st.header("3 · Results")
    state = st.session_state
    inputs = state["inputs"]
    blockers = gate_status(inputs["confirmed"])
    if blockers:
        st.warning(gate_message())
        return
    try:
        current, proposal = _build_terms(inputs)
        result = compare(current, proposal)
        decision = verdict(result, inputs["priority"])
    except ValueError as exc:
        st.error(f"Could not compare: {exc}")
        return
    st.subheader(escape_display(decision.headline))
    st.write(escape_display(decision.tradeoff_note))
    st.table(
        {
            "Option": ["Keep", "Refinance now"],
            "Monthly": [escape_display(format_money(result.keep_monthly)),
                        escape_display(format_money(result.refi_monthly))],
            "Total": [escape_display(format_money(result.keep_total)),
                      escape_display(format_money(result.refi_total))],
        }
    )
    st.write(escape_display(f"Cash due today: {format_money(result.cash_due_today)}."))
    for row in split_rows(result):
        st.write(escape_display(f"- {row}"))
    if result.breakeven_month is None:
        st.write("Breakeven: refinancing never stays ahead within the horizon.")
    else:
        st.write(f"Breakeven: month {result.breakeven_month}.")

    st.subheader("What if you wait?")
    st.write(
        "Waiting means paying the current loan down first, then refinancing "
        "the smaller balance — never a prediction about future rates."
    )
    # Only waits shorter than the remaining term: waiting past payoff
    # leaves nothing to refinance.
    options = wait_options(int(inputs["loan_months"]))
    if not options:
        st.write(
            "Waiting is off the table: your loan pays off in "
            f"{int(inputs['loan_months'])} months, so there is nothing "
            "left to refinance by waiting."
        )
        compared = None
    else:
        try:
            thresholds = wait_thresholds(current, proposal, list(options))
        except ValueError as exc:
            st.error(f"Could not price waiting: {exc}")
            compared = None
        else:
            st.write(escape_display(describe_thresholds_heading(thresholds)))
            st.write(escape_display(
                f"Today's offer: {format_rate_floor(thresholds.offer_rate)}."))
            st.table({
                "Wait": [f"{months} months" for months, _ in thresholds.rates],
                "Rate needed": [escape_display(format_threshold_rate(rate))
                                for _, rate in thresholds.rates],
            })
            st.write("Try a rate:")
            if inputs["wait_months"] not in options:
                inputs["wait_months"] = options[0]
            if state.get("wait_months") not in options:
                state["wait_months"] = inputs["wait_months"]
            wait_months = st.selectbox("Wait how long?", options, key="wait_months",
                                             format_func=wait_option_label)
            inputs["wait_months"] = int(wait_months)
            if inputs["wait_rate_pct"] is None:
                inputs["wait_rate_pct"] = inputs["offer_rate_pct"]
            if state.get("w_wait_rate_pct") is None:
                state["w_wait_rate_pct"] = inputs["wait_rate_pct"]
            st.number_input("Scenario rate if you wait (%)", min_value=0.0, step=0.05,
                            key="w_wait_rate_pct")
            inputs["wait_rate_pct"] = float(state["w_wait_rate_pct"])
            st.button("Use offer APR as the scenario", key="reset_wait_rate",
                      on_click=reset_wait_rate_to_offer, args=(state,))
            try:
                compared = compare_wait(current, proposal, int(wait_months),
                                        float(inputs["wait_rate_pct"]) / 100)
            except ValueError as exc:
                st.error(f"Could not price waiting: {exc}")
                compared = None
            if compared is not None:
                # Today's side of the table: keep's numbers, or the refi's
                # when refinancing now is cheaper (ties keep the status quo,
                # like the engine baseline).
                if compared.baseline == "refinance_now":
                    today_monthly = result.refi_monthly
                    today_months = result.months_to_payoff_refi
                else:
                    today_monthly = result.keep_monthly
                    today_months = result.months_to_payoff_keep
                today_label = escape_display(today_column_label(compared.baseline))
                wait_label = (
                    f"Wait {compared.plan.wait_months} months, then refinance "
                    f"at {format_rate_floor(compared.plan.annual_rate)}"
                )
                st.table({
                    "": ["Monthly payments", "Total paid", "Paid off in"],
                    today_label: [
                        escape_display(f"{format_money(today_monthly)}/mo"),
                        escape_display(format_money(compared.baseline_total)),
                        f"{today_months} months",
                    ],
                    escape_display(wait_label): [
                        escape_display(
                            f"{format_money(result.keep_monthly)}/mo for "
                            f"{compared.plan.wait_months} months, then "
                            f"{format_money(compared.plan.monthly)}/mo"),
                        escape_display(format_money(compared.plan.total)),
                        f"{compared.plan.months_to_payoff} months",
                    ],
                })
                st.write(escape_display(describe_wait_result(compared)))
    st.caption(
        "Code-written verdict from fixed rules — the model narrative "
        "arrives in a later slice. " + DISCLAIMER
    )
    # Kept: results often send the user back to fix a number or priority,
    # or all the way back to restate the problem. The spacer column pushes
    # Start over flush to the line end.
    left, _, right = st.columns([1, 2, 1])
    with left:
        if st.button("Back", key="back_to_2", use_container_width=True):
            st.session_state["page"] = 2
            st.rerun()
    with right:
        if st.button("Start over", key="back_to_1", use_container_width=True):
            reset_all(st.session_state)
            st.rerun()


def main() -> None:
    """The Streamlit screen. Imported lazily so tests exercise the helpers
    above without a browser stack installed."""
    import streamlit as st

    _apply_deploy_secret(st)
    st.title("Auto-Refinance Decision Assistant")
    st.caption(DISCLAIMER)

    for key, default in (
        ("page", 1),
        ("loan_text", ""),
        ("offer_text", ""),
        ("loan_result", None),
        ("offer_result", None),
        ("applied_loan_file", None),
        ("applied_offer_file", None),
    ):
        if key not in st.session_state:
            st.session_state[key] = default
    if st.session_state.get("inputs") is None:
        st.session_state["inputs"] = dict(INPUT_DEFAULTS)
    if st.session_state.get("extracted") is None:
        st.session_state["extracted"] = {}

    page = st.session_state["page"]
    st.write(f"Step {page} of 3.")
    if page == 1:
        _page_input(st)
    elif page == 2:
        _page_confirm(st)
    else:
        _page_results(st)


if __name__ == "__main__":
    main()
