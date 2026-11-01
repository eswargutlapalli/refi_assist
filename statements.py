"""statements.py — multimodal statement input as editable text.

Why this module exists: a statement may arrive as pasted text, a photo,
a screenshot, or a PDF. Whatever the shape, what reaches extraction is
plain text in the page-1 boxes the user can edit — extraction, grounding,
and the confirm gate never see anything else, so a vision misread is
always user-visible before compute.

PDFs read their text layer locally first; vision runs only for photos,
screenshots, and scanned PDFs (no extractable text). Transcription is a
copy task: minimal effort, and the transcript is returned, never trusted.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from llm import DEFAULT_MODEL, LlmError, complete

TRANSCRIBE_PROMPT_CACHE_KEY = "refi-transcribe-v1"  # Own key: stable per slice.
TRANSCRIBE_INSTRUCTIONS = (
    "Transcribe all visible text in this statement image exactly as "
    "written, preserving numbers, amounts, and line breaks. "
    "Output only the transcription, no commentary."
)

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

MAX_VISION_PAGES = 3  # vision reads the first pages only; beyond that the
# upload is refused with instructions instead of silently dropping pages.
VISION_LIMIT = 5  # vision calls per session; transcripts are never cached,
# so every fresh upload spends again — the cap keeps a retry loop honest.


def read_pdf_text(data: bytes) -> str | None:
    """Text layer of a PDF, or None when there is none to read.

    A scanned PDF has pages but no extractable text — that None is what
    sends the file down the vision path. A file pypdf cannot parse at
    all raises: a corrupt upload must fail loudly, never as blank input.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"could not read the PDF: {exc}") from exc
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n".join(part for part in pages if part).strip()
    return text or None


def transcribe_image(data: bytes, mime: str, *,
                     client: Any = None,
                     budget: dict[str, int] | None = None) -> str:
    """Vision transcription of one statement photo or screenshot.

    The model copies what it sees; the transcript lands in an editable
    box, so misreads are caught at the confirm page. An empty reply
    raises: blank is the likeliest wrong value for a statement. With no
    budget the call is untracked (eval runs); with a {"used", "limit"}
    budget each call counts first and a spent budget raises before
    anything is sent.
    """
    if budget is not None:
        limit = budget.get("limit", VISION_LIMIT)
        if budget.get("used", 0) >= limit:
            raise ValueError(
                f"vision budget spent for this session ({limit} calls) — "
                "paste the statement text instead")
        budget["used"] = budget.get("used", 0) + 1
    encoded = base64.b64encode(data).decode("ascii")
    try:
        response = complete(
            [{"role": "user", "content": [
                {"type": "text", "text": TRANSCRIBE_INSTRUCTIONS},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]}],
            model=DEFAULT_MODEL,
            effort="minimal",
            prompt_cache_key=TRANSCRIBE_PROMPT_CACHE_KEY,
            client=client,
        )
    except LlmError as exc:
        raise ValueError(f"could not transcribe the image: {exc}") from exc
    if not response.text.strip():
        raise ValueError("the image gave back no text — paste the statement instead")
    return response.text.strip()


def read_statement_upload(data: bytes, filename: str, *,
                          client: Any = None,
                          budget: dict[str, int] | None = None) -> tuple[str, str]:
    """Transcript plus its source for one uploaded statement.

    Sources: "text-file" for .txt/.md, "pdf-text" for a PDF text layer,
    "vision" for photos, screenshots, and scanned PDFs. Anything else
    raises — an unsupported file must say so, never sneak through blank.
    A budget caps vision calls; the free text paths never touch it.
    """
    suffix = "." + (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")
    if suffix in (".txt", ".md"):
        try:
            return data.decode("utf-8"), "text-file"
        except UnicodeDecodeError as exc:
            raise ValueError(f"could not read {filename} as text: {exc}") from exc
    if suffix == ".pdf":
        text = read_pdf_text(data)
        if text is not None:
            return text, "pdf-text"
        pages = rasterize_pdf(data)
        parts = [transcribe_image(page, "image/png", client=client, budget=budget)
                 for page in pages]
        return "\n".join(parts), "vision"
    if suffix in _IMAGE_MIME:
        return (transcribe_image(data, _IMAGE_MIME[suffix], client=client,
                                 budget=budget),
                "vision")
    raise ValueError(f"unsupported file {filename}: upload .txt, .pdf, .png, or .jpg")


def rasterize_pdf(data: bytes, max_pages: int = MAX_VISION_PAGES) -> list[bytes]:
    """Scanned-PDF pages as PNGs, in order. The vision endpoint reads
    images, not PDF bytes, so a scan without a text layer is rasterized
    first. More than max_pages refuses loudly: transcribing a subset
    would silently drop statement terms."""
    import pymupdf

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"could not read the PDF: {exc}") from exc
    with document:
        count = document.page_count
        if count == 0:
            raise ValueError("the PDF has no pages to read")
        if count > max_pages:
            raise ValueError(
                f"the PDF has {count} pages; vision reads the first "
                f"{max_pages} — re-upload just the statement pages")
        return [page.get_pixmap(dpi=150).tobytes("png")
                for page in document]
