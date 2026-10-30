"""extract.py — grounded term extraction from borrower text (rule 3.2).

Two schemas ride one mechanism: CurrentLoanTerms (balance, APR, months,
penalty) and RefinanceOfferTerms (APR, term, fees, financed flag). The model
copies each term as written plus the exact quote it came from; it never
calculates. Code then proves grounding per field: a non-empty quote must sit
in the source, and the reported value must match a stated amount in it —
digits ($-and-comma blind, cents folded) or words parsed in code ("thirty
seven" → 37, dollars-and-cents combined). Checks read the matched occurrence
and its neighbors, never the whole quote: the unit must fit the field (rate
takes %/percent or an apr-word, months take month/mo/mos/payments, dollars
refuse %/month/year), and the nearest field word within three tokens must be
the claimed field, with earlier words winning ties and $/dollars defaulting
to balance. Zero grounds only with no digits stated, a zero word (no, none,
without, waived, not charged), and a field word. An ungrounded field gets one
retry with kind-only feedback, then its value is cleared (None) for the user
to type — the confirm gate in app.py will show exactly which fields those are.

Number normalization is code's job, not the model's: the model reports 7.5
for "APR 7.5%" and 20000.0 for "$20,000"; the converters divide percents by
100. Months must be whole; anything fractional is ungrounded. The converters
refuse cleared fields by name, and engine construction validates ranges last
— no number reaches math unproven.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from engine import CurrentLoan, RefinanceOffer
from llm import LlmError, StrictModel, complete_schema  # noqa: F401 (re-exported for callers/tests)

EXTRACT_PROMPT_CACHE_KEY = "refi-extract-v1"  # Own key: different stable prefix from llm's default.

_EXTRACTION_INSTRUCTIONS = (
    "Copy loan terms from the borrower's statement. For each term reply with "
    "the amount as digits and the shortest exact quote naming the term with "
    "its amount ('balance 30 thousands', not '30 thousands'), word-for-word. "
    "Report the full stated amount: 'thirty seven' → 37, "
    "'30 thousands' → 30000 (never the bare 30). Beyond that, never "
    "calculate, convert, or round: percent stays a percent (7.5 for "
    "'APR 7.5%'). If a term is not stated, use null for both value and "
    "quote. Reply with JSON only."
)

_LOAN_EXTRA = (
    " A prepayment penalty the statement says is absent "
    "is 0 with that quote."
)

_OFFER_EXTRA = (
    " fees_financed is true when the statement says fees are financed, "
    "rolled in, or added to the loan; false when they are paid upfront, out "
    "of pocket, or at signing."
)

_FIELD_NAMES = (
    "balance",
    "annual_rate_pct",
    "remaining_months",
    "prepayment_penalty",
)

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?|\d[\d,]*\.?\d*|%")

_BALANCE_WORDS = {"balance", "principal", "owe", "owed", "owes", "payoff"}
_RATE_WORDS = {"apr", "rate", "interest", "apy"}
_FEE_WORDS = {"fee", "fees", "charge", "charges", "origination", "closing"}
_MONTH_FIELDS = ("remaining_months", "term_months")
_DOLLAR_FIELDS = ("balance", "fees", "prepayment_penalty")
_ALL_FIELDS = (
    "balance", "annual_rate_pct", "remaining_months",
    "prepayment_penalty", "term_months", "fees",
)

_UNIT_WINDOW = 2  # unit words must sit this close to the matched number
_ATTR_CAP = 3  # field words are heard this far; ties go to the earlier word

_ZERO_TOKENS = {"no", "none", "without", "waived"}
_ZERO_PHRASE_RE = re.compile(r"\bnot charged\b")

_WORD_VALUES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_MARKERS = {"and", "dollar", "dollars", "cent", "cents", "percent", "percentage"}
_PLURAL_SCALES = {
    "thousands": "thousand", "hundreds": "hundred",
    "millions": "million", "billions": "billion",
}
_TENS_PAIR = {
    "one": "ten", "two": "twenty", "three": "thirty", "four": "forty",
    "five": "fifty", "six": "sixty", "seven": "seventy", "eight": "eighty",
    "nine": "ninety",
}
_VOCAB = (
    set(_WORD_VALUES) | set(_SCALES) | _MARKERS
    | set(_PLURAL_SCALES) | {"tens", "ones"}
)


def _tokenize(text: str) -> list[tuple[str, int, int]]:
    """(token, char start, char end) over lowercased text. Hyphen handling and
    case folding preserve string length, so spans line up with the original."""
    lowered = text.lower().replace("-", " ")
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(lowered)]


def _normalize_plurals(tokens: list[str]) -> list[str]:
    # Plural scales behave as singular ("two hundreds thirty" → 230).
    # "three tens" is a pair: the number word becomes its -ty form (30).
    # "four ones" drops the ones: four units is 4.
    out: list[str] = []
    for token in tokens:
        if token in _PLURAL_SCALES:
            out.append(_PLURAL_SCALES[token])
        elif token == "tens":
            if out and out[-1] in _TENS_PAIR:
                out[-1] = _TENS_PAIR[out[-1]]
            else:
                out.append("ten")
        elif token == "ones":
            if out and out[-1] in _WORD_VALUES:
                continue
            out.append("one")
        else:
            out.append(token)
    return out


def _is_number_token(token: str) -> bool:
    try:
        float(token.replace(",", ""))
        return True
    except ValueError:
        return False


def _glue_and(run: list[str], index: int) -> bool:
    # Keep "and" inside the run after a scale word ("one hundred and five")
    # or ahead of a dollars/cents phrase ("fifty one dollars and 51 cents").
    # Otherwise "and" separates two amounts ("thirty seven and forty two").
    if run[index - 1] in _SCALES:
        return True
    return any(tok in ("dollar", "dollars", "cent", "cents") for tok in run[index + 1:])


def _split_runs(tokens: list[str]) -> list[tuple[int, int]]:
    """Token spans (start inclusive, end exclusive) of each amount run, after
    the and-splitting rule. Same runs as before, with positions attached."""
    spans, cur = [], None
    for i, token in enumerate(tokens):
        if token in _VOCAB or _is_number_token(token):
            cur = [i, i + 1] if cur is None else [cur[0], i + 1]
        elif cur is not None:
            spans.append(tuple(cur))
            cur = None
    if cur is not None:
        spans.append(tuple(cur))
    out = []
    for start, end in spans:
        run = tokens[start:end]
        part = start
        for k, token in enumerate(run):
            if token == "and" and k > 0 and not _glue_and(run, k):
                out.append((part, start + k))
                part = start + k + 1
        out.append((part, end))
    return [(s, e) for s, e in out if e > s]


def _scale_value(tokens: list[str]) -> float:
    total, current = 0.0, 0.0
    for token in tokens:
        if token in _WORD_VALUES:
            current += _WORD_VALUES[token]
        elif token == "hundred":
            current = current * 100 if current else 100
        elif token in _SCALES:
            total += max(current, 1) * _SCALES[token]
            current = 0.0
        elif _is_number_token(token):
            current += float(token.replace(",", ""))
        # Markers (and/dollar/cent/percent) carry no value themselves.
    return total + current


def _run_value(run: list[str]) -> float | None:
    # A run with no value token ("and", "percent" alone) states no amount.
    if not any(token in _WORD_VALUES or _is_number_token(token) for token in run):
        return None
    if "dollar" in run or "dollars" in run:
        marker = run.index("dollar") if "dollar" in run else run.index("dollars")
        dollars = _scale_value(run[:marker])
        after = run[marker + 1:]
        if "cent" in after or "cents" in after:
            return dollars + _scale_value(after) / 100
        return dollars
    if "cent" in run or "cents" in run:
        return _scale_value(run) / 100
    return _scale_value(run)


def _word_amounts(text: str) -> list[float]:
    # Lone everyday words ("one" in "no one") parse too — a known, pinned
    # residual; grounding (not parsing) decides what validates.
    strs = [tok for tok, _, _ in _tokenize(text)]
    norm = _normalize_plurals(strs)
    return [
        value for start, end in _split_runs(norm)
        if (value := _run_value(norm[start:end])) is not None
    ]


# A digit run a scale word owns ("30 thousands") is one amount, stated by
# the word parser as 30000 — the bare 30 is never a second amount, the same
# way a cents phrase owns its digits.
_SCALE_AFTER_RE = re.compile(r"\s*(?:thousands?|millions?|billions?|hundreds?)\b", re.IGNORECASE)


def _digit_hits(text: str) -> list[tuple[float, int, int, bool]]:
    """(value, char start, char end, is_cent) for each digit run. A cents
    phrase yields hundredths ("51 cents" → 0.51); the raw 51 is never emitted
    as dollars. A digit a scale word follows ("30 thousands") is skipped;
    the word run states 30000 instead."""
    hits = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0)
        if re.match(r"\s*cents?\b", text[match.end():], re.IGNORECASE):
            hits.append(
                (float(raw.replace(",", "")) / 100, match.start(), match.end(), True)
            )
        elif _SCALE_AFTER_RE.match(text[match.end():]):
            continue
        else:
            hits.append((float(raw.replace(",", "")), match.start(), match.end(), False))
    return hits


@dataclass
class _Occ:
    """One stated amount: value plus its token span (end exclusive)."""

    value: float
    start: int
    end: int


def _occurrences(quote: str) -> tuple[list[str], list[_Occ]]:
    """Token strings plus every stated amount (digits and word runs) with spans."""
    toks = _tokenize(quote)
    strs = [tok for tok, _, _ in toks]
    occs: list[_Occ] = []
    for value, start, end, _ in _digit_hits(quote):
        index = next(i for i, (_, s, e) in enumerate(toks) if s <= start < e)
        occs.append(_Occ(value, index, index + 1))
    norm = _normalize_plurals(strs)
    for start, end in _split_runs(norm):
        value = _run_value(norm[start:end])
        if value is not None:
            occs.append(_Occ(value, start, end))
    return strs, occs


def _gap(occ: _Occ, index: int) -> int:
    """Tokens strictly between the occurrence span and index (0 adjacent)."""
    if occ.start <= index < occ.end:
        return 0
    return occ.start - index if index < occ.start else index - occ.end + 1


def _is_month_unit(token: str) -> bool:
    return (
        token in ("mo", "mos", "payment", "payments") or token.startswith("month")
    )


def _is_year_unit(token: str) -> bool:
    return token in ("year", "years", "yr", "yrs")


def _is_pct(token: str) -> bool:
    return token == "%" or token in ("percent", "percentage")


def _is_field_word(field: str, token: str) -> bool:
    if field == "balance":
        return token in _BALANCE_WORDS
    if field == "annual_rate_pct":
        return token in _PCT_TOKENS or token in _RATE_WORDS
    if field in _MONTH_FIELDS:
        return _is_month_unit(token)
    if field == "prepayment_penalty":
        return token.startswith("penalt") or token.startswith("prepay")
    if field == "fees":
        return token in _FEE_WORDS
    return False


_PCT_TOKENS = {"%", "percent", "percentage"}


def _nearby(strs: list[str], occ: _Occ, pred: Any, window: int) -> bool:
    return any(pred(tok) for j, tok in enumerate(strs) if _gap(occ, j) <= window)


class GroundedValue(StrictModel):
    """One copied term: the number as written plus its exact source quote."""

    value: float | None
    quote: str | None


class CurrentLoanTerms(StrictModel):
    """The current-loan schema. annual_rate_pct is percent-as-written (7.5)."""

    balance: GroundedValue
    annual_rate_pct: GroundedValue
    remaining_months: GroundedValue
    prepayment_penalty: GroundedValue


class FinancedFlag(StrictModel):
    """Whether fees ride into the new balance: stated in words, not digits."""

    financed: bool | None
    quote: str | None


class RefinanceOfferTerms(StrictModel):
    """The refinance-offer schema. Same percent-as-written convention."""

    annual_rate_pct: GroundedValue
    term_months: GroundedValue
    fees: GroundedValue
    fees_financed: FinancedFlag


# Token phrases: "finance charge" is a fee, not financing — only "financed"
# counts, so "refinance" can never match either.
_FIN_PHRASES = (
    ("financed",),
    ("rolled", "into"),
    ("wrapped", "into"),
    ("added", "to", "the", "loan"),
    ("added", "to", "the", "balance"),
)
_UP_PHRASES = (
    ("upfront",),
    ("up", "front"),
    ("out", "of", "pocket"),
    ("due", "at", "signing"),
    ("paid", "at", "signing"),
    ("cash", "due"),
)
_NEG_TOKENS = {"not", "never"}


@dataclass
class FieldOutcome:
    """One field after checking: grounded, or cleared (value None) for the user."""

    name: str
    value: float | bool | None
    quote: str | None
    status: str  # "grounded", "ungrounded", or "cleared"


@dataclass
class ExtractionResult:
    fields: dict[str, FieldOutcome]
    attempts: int

    def _require_grounded(self, names: tuple[str, ...]) -> None:
        """Cleared fields raise naming themselves: the user must type them at
        the confirm gate, never silently defaulted."""
        missing = sorted(
            name for name in names
            if self.fields[name].status != "grounded"
            or self.fields[name].value is None
        )
        if missing:
            raise ValueError(f"Cleared for the user to enter: {missing}")

    def to_current_loan(self) -> CurrentLoan:
        """Build engine terms for the existing loan (percent → decimal here)."""
        self._require_grounded(
            ("balance", "annual_rate_pct", "remaining_months", "prepayment_penalty")
        )
        return CurrentLoan(
            balance=self.fields["balance"].value or 0.0,
            annual_rate=(self.fields["annual_rate_pct"].value or 0.0) / 100,
            remaining_months=int(self.fields["remaining_months"].value or 0),
            prepayment_penalty=self.fields["prepayment_penalty"].value or 0.0,
        )

    def to_refinance_offer(self) -> RefinanceOffer:
        """Build engine terms for the offer under evaluation."""
        self._require_grounded(
            ("annual_rate_pct", "term_months", "fees", "fees_financed")
        )
        return RefinanceOffer(
            annual_rate=(self.fields["annual_rate_pct"].value or 0.0) / 100,
            term_months=int(self.fields["term_months"].value or 0),
            fees=self.fields["fees"].value or 0.0,
            fees_financed=bool(self.fields["fees_financed"].value),
        )


def numbers_in(text: str | None) -> list[float]:
    """Every number a quote states: digits ($-and-comma blind, cents phrases
    folded to hundredths) plus amounts written as words ("thirty seven" → 37,
    "fifty cents" → 0.5). Verification code may do math; the model may not."""
    found = [v for v, _, _, cent in _digit_hits(text or "") if not cent]
    return found + _word_amounts(text or "")


def _has_zero_word(strs: list[str], quote: str) -> bool:
    if _ZERO_TOKENS.intersection(strs):
        return True
    return _ZERO_PHRASE_RE.search(quote.lower()) is not None


def _dollar_adjacent(quote: str, toks: list[tuple[str, int, int]], occ: _Occ) -> bool:
    start, end = toks[occ.start][1], toks[occ.end - 1][2]
    return (start > 0 and quote[start - 1] == "$") or (
        end < len(quote) and quote[end] == "$"
    )


def _pct_follows(strs: list[str], occ: _Occ) -> bool:
    """% is punctuation, not a word: it marks the amount it follows ("7.5%"),
    never a neighbor ("%. 36"). Percent-words keep the wider window."""
    return occ.end < len(strs) and strs[occ.end] == "%"


def _unit_ok(field: str, strs: list[str], occ: _Occ) -> bool:
    """The unit gate: rate needs a following %/percent or a nearby apr-word;
    months need a month word nearby; dollar fields refuse %/month/year nearby."""
    if field == "annual_rate_pct":
        return _pct_follows(strs, occ) or _nearby(
            strs, occ,
            lambda tok: tok in ("percent", "percentage") or tok in _RATE_WORDS,
            _UNIT_WINDOW,
        )
    if field in _MONTH_FIELDS:
        return _nearby(strs, occ, _is_month_unit, _UNIT_WINDOW)
    return not _nearby(
        strs, occ,
        lambda tok: tok in _PCT_TOKENS or _is_month_unit(tok) or _is_year_unit(tok),
        _UNIT_WINDOW,
    )


def _binds(occ: _Occ, others: list[_Occ], index: int) -> bool:
    """A field word at index counts for occ unless another stated amount sits
    strictly between them ("% in 7.9% belongs to 7.9, not to a $17,327 three
    words away)."""
    return all(_gap(o, index) >= _gap(occ, index) for o in others)


def _attribute(
    strs: list[str],
    toks: list[tuple[str, int, int]],
    quote: str,
    occ: _Occ,
    all_occs: list[_Occ],
) -> set[str]:
    """Fields tied at the nearest word and distance ("months" names both
    month fields). Ties across positions go to the earlier word. A word
    already claimed by a nearer amount does not count. With no field word
    near, a $ or dollars-word defaults to balance."""
    best: tuple[int, int] | None = None
    winners: set[str] = set()
    for j, tok in enumerate(strs):
        # A % token only ever speaks for the amount it follows.
        if tok == "%" and j != occ.end:
            continue
        for name in _ALL_FIELDS:
            if _is_field_word(name, tok):
                dist = _gap(occ, j)
                if (
                    dist <= _ATTR_CAP
                    and _binds(occ, all_occs, j)
                    and (best is None or (dist, j) <= (best[0], best[1]))
                ):
                    if best is None or (dist, j) < (best[0], best[1]):
                        winners = set()
                    best = (dist, j)
                    winners.add(name)
    if winners:
        return winners
    span = strs[occ.start:occ.end]
    if any(tok in ("dollar", "dollars") for tok in span) or _dollar_adjacent(
        quote, toks, occ
    ):
        return {"balance"}
    return set()


def check_field(
    value: float | None,
    quote: str | None,
    source: str,
    *,
    field: str,
    whole: bool = False,
) -> bool:
    """A field grounds when a matching occurrence in its quote passes the
    unit gate and attributes to the field. Windows measure from occurrence
    edges; ties go to the earlier word; a word claimed by a nearer amount
    does not count. Empty quotes never ground: "" sits in every string, so it
    proves nothing. Booleans are never amounts.

    Rules by field — unit needed | claiming words:
    balance: no %/month/year nearby | balance/principal/owe/payoff
      (bare $ or a dollars-word defaults here)
    annual_rate_pct: % immediately after, or percent/apr/rate/interest word
      nearby | same words (% never speaks for a neighbor)
    remaining_months, term_months: whole number + month/mo/payments nearby |
      same words
    prepayment_penalty, fees: no %/month/year nearby | penalt/prepay;
      fee/charge/origination/closing
    zero (any field): zero word (no/none/without/waived/not charged) +
      field word, and no digits stated at all
    """
    if value is None or isinstance(value, bool) or not quote or not quote.strip():
        return False
    if quote not in source:
        return False
    if whole and not float(value).is_integer():
        return False
    toks = _tokenize(quote)
    strs = [tok for tok, _, _ in toks]
    if not numbers_in(quote):
        return (
            value == 0
            and _has_zero_word(strs, quote)
            and any(_is_field_word(field, tok) for tok in strs)
            and not _has_competitor(field, 0.0, source)
        )
    _, all_occs = _occurrences(quote)
    occs = [
        o for o in all_occs if math.isclose(o.value, value, rel_tol=1e-9)
    ]
    for occ in occs:
        if _unit_ok(field, strs, occ) and field in _attribute(
            strs, toks, quote, occ, all_occs
        ):
            return not _has_competitor(field, value, source)
    return False


def _has_competitor(field: str, value: float, source: str) -> bool:
    """A distinct stated amount in the source that also attributes to the
    field: two copies, no trustworthy pick. Both statements pasted in one
    box grounds neither rate — the borrower picks. Equal amounts (digit
    and word runs of one number) never compete."""
    src_toks = _tokenize(source)
    src_strs = [tok for tok, _, _ in src_toks]
    _, src_occs = _occurrences(source)
    for occ in src_occs:
        if math.isclose(occ.value, value, rel_tol=1e-9):
            continue
        if _unit_ok(field, src_strs, occ) and field in _attribute(
            src_strs, src_toks, source, occ, src_occs
        ):
            return True
    return False


def _phrase_hits(strs: list[str]) -> tuple[list[int], list[int]]:
    """Start indices of financed/upfront signal phrases in the token stream."""
    fin, up = [], []
    for i in range(len(strs)):
        for phrase in _FIN_PHRASES:
            if tuple(strs[i:i + len(phrase)]) == phrase:
                fin.append(i)
        for phrase in _UP_PHRASES:
            if tuple(strs[i:i + len(phrase)]) == phrase:
                up.append(i)
    return fin, up


def _negated(strs: list[str], index: int) -> bool:
    # Up to three words may stand between the negation and its signal
    # ("not going to be financed"): look back four positions.
    return any(
        strs[k] in _NEG_TOKENS or strs[k].endswith("n't")
        for k in range(max(0, index - 4), index)
    )


def check_flag(value: bool | None, quote: str | None, source: str) -> bool:
    """A financed flag grounds when its quote sits in the source and carries
    exactly one polarity of signal matching the reported value. A not/never/
    n't within three words before a signal flips it ("not going to be
    financed" proves False). Both polarities, neither, or the wrong polarity:
    ungrounded."""
    if value is None or quote is None:
        return False
    if quote not in source:
        return False
    strs = [tok for tok, _, _ in _tokenize(quote)]
    fin, up = _phrase_hits(strs)
    evidence_financed = any(not _negated(strs, i) for i in fin) or any(
        _negated(strs, i) for i in up
    )
    evidence_upfront = any(not _negated(strs, i) for i in up) or any(
        _negated(strs, i) for i in fin
    )
    if evidence_financed == evidence_upfront:
        return False
    return bool(value) == evidence_financed


def _extraction_messages(source: str, extra: str = "") -> list[dict[str, Any]]:
    # Stable instructions first (the cacheable prefix), the borrower's words last.
    return [
        {"role": "system", "content": _EXTRACTION_INSTRUCTIONS + extra},
        {"role": "user", "content": source},
    ]


def _retry_feedback(bad: list[str]) -> str:
    # Kind of error only: which fields failed and what grounding demands.
    # Never the expected values, or the retry is worthless.
    return (
        "These fields were not grounded (" + ", ".join(bad) + "): each quote "
        "must appear word-for-word in the statement, must name the term, and "
        "must state the value you reported — the number itself, or for "
        "fees_financed the words saying who pays the fees. Copy exact quotes "
        "from the statement; use null for both value and quote when the "
        "statement does not state a term."
    )


def _ground_all(terms: CurrentLoanTerms, source: str) -> dict[str, FieldOutcome]:
    outcomes = {}
    for name in _FIELD_NAMES:
        cell = getattr(terms, name)
        ok = check_field(
            cell.value, cell.quote, source,
            field=name, whole=(name == "remaining_months"),
        )
        outcomes[name] = FieldOutcome(
            name=name, value=cell.value, quote=cell.quote,
            status="grounded" if ok else "ungrounded",
        )
    return outcomes


def _ground_offer(terms: RefinanceOfferTerms, source: str) -> dict[str, FieldOutcome]:
    outcomes = {}
    for name in ("annual_rate_pct", "term_months", "fees"):
        cell = getattr(terms, name)
        ok = check_field(
            cell.value, cell.quote, source,
            field=name, whole=(name == "term_months"),
        )
        outcomes[name] = FieldOutcome(
            name=name, value=cell.value, quote=cell.quote,
            status="grounded" if ok else "ungrounded",
        )
    flag = terms.fees_financed
    ok = check_flag(flag.financed, flag.quote, source)
    outcomes["fees_financed"] = FieldOutcome(
        name="fees_financed", value=flag.financed, quote=flag.quote,
        status="grounded" if ok else "ungrounded",
    )
    return outcomes


def _extract_with_retry(
    schema: type[StrictModel],
    working: list[dict[str, Any]],
    source_text: str,
    ground: Any,
    client: Any,
) -> ExtractionResult:
    """Shared one-retry loop: ground, re-ask the failures once with kind-only
    feedback, then clear what still fails. Round-one grounded fields stand."""
    terms, _ = complete_schema(
        working, schema, client=client, prompt_cache_key=EXTRACT_PROMPT_CACHE_KEY
    )
    outcomes = ground(terms, source_text)
    attempts = 1
    bad = sorted(
        name for name, outcome in outcomes.items() if outcome.status != "grounded"
    )
    if bad:
        attempts = 2
        working.append({"role": "user", "content": _retry_feedback(bad)})
        retry_terms, _ = complete_schema(
            working, schema,
            client=client, prompt_cache_key=EXTRACT_PROMPT_CACHE_KEY,
        )
        fresh = ground(retry_terms, source_text)
        for name in bad:
            if fresh[name].status == "grounded":
                outcomes[name] = fresh[name]
            else:
                outcomes[name] = FieldOutcome(
                    name=name, value=None, quote=fresh[name].quote,
                    status="cleared",
                )
    return ExtractionResult(fields=outcomes, attempts=attempts)


def _checked_source(source_text: str) -> str:
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text must be a non-empty string.")
    return source_text


def extract_current_loan(
    source_text: str, *, client: Any = None
) -> ExtractionResult:
    """Extract current-loan terms from borrower text with grounding proof.

    One retry for ungrounded fields, then cleared (value None) for the user.
    A schema violation raises (fail loudly) with no retry: the shape itself
    is broken, not any one field.
    """
    source = _checked_source(source_text)
    return _extract_with_retry(
        CurrentLoanTerms, _extraction_messages(source, _LOAN_EXTRA),
        source, _ground_all, client,
    )


def extract_refinance_offer(
    source_text: str, *, client: Any = None
) -> ExtractionResult:
    """Extract refinance-offer terms: same proof, same single retry, same
    clearing. Convert with to_refinance_offer()."""
    source = _checked_source(source_text)
    return _extract_with_retry(
        RefinanceOfferTerms, _extraction_messages(source, _OFFER_EXTRA),
        source, _ground_offer, client,
    )
