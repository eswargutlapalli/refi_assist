"""Suite for statements.py. Mocked only — no network, no spend.

Multimodal input transcribes into the same editable page-1 boxes, so
extraction, grounding, and the confirm gate are unchanged: a vision
misread is always user-visible before compute. PDFs read their text
layer locally; vision runs only for photos, screenshots, and scanned
PDFs. The PNG renderer in tests/_render.py is test-only.
"""

import types
from pathlib import Path

import pytest

FIXTURES = Path(__file__).with_name("fixtures")


class _FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("more API calls than scripted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        message = types.SimpleNamespace(content=item, tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=None,
            model="muse-spark-1.3",
        )


class _FakeClient:
    def __init__(self, script):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(script))

    @property
    def calls(self):
        return self.chat.completions.calls


def test_read_pdf_text_layer():
    statements = pytest.importorskip("statements")
    data = (FIXTURES / "statement.pdf").read_bytes()
    text = statements.read_pdf_text(data)
    assert text is not None
    assert "Outstanding balance: $18,500.00" in text
    assert "Payments remaining: 48" in text


def test_scanned_pdf_has_no_text_layer():
    statements = pytest.importorskip("statements")
    assert statements.read_pdf_text(
        (FIXTURES / "scanned.pdf").read_bytes()) is None


def test_transcribe_image_sends_image_part():
    statements = pytest.importorskip("statements")
    from tests._render import render_text_png

    fake = _FakeClient(["Outstanding balance: $18,500.00"])
    text = statements.transcribe_image(
        render_text_png("Outstanding balance: $18,500.00"),
        "image/png", client=fake)
    assert text == "Outstanding balance: $18,500.00"
    parts = fake.calls[0]["messages"][0]["content"]
    kinds = [p["type"] for p in parts]
    assert kinds == ["text", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_transcribe_empty_text_fails_loudly():
    statements = pytest.importorskip("statements")
    fake = _FakeClient(["   "])
    with pytest.raises(ValueError, match="no text"):
        statements.transcribe_image(b"png-bytes", "image/png", client=fake)


def test_transcribe_output_is_stripped():
    statements = pytest.importorskip("statements")
    fake = _FakeClient(["\n  Balance $10.\n"])
    assert statements.transcribe_image(
        b"png-bytes", "image/png", client=fake) == "Balance $10."


def test_vision_budget_blocks_before_spending():
    statements = pytest.importorskip("statements")
    fake = _FakeClient(["never used"])
    budget = {"used": 5, "limit": 5}
    with pytest.raises(ValueError, match="budget"):
        statements.transcribe_image(
            b"png-bytes", "image/png", client=fake, budget=budget)
    assert fake.calls == []
    assert budget["used"] == 5


def test_vision_budget_counts_calls():
    statements = pytest.importorskip("statements")
    fake = _FakeClient(["a", "b"])
    budget = {"used": 0, "limit": 5}
    statements.transcribe_image(b"x", "image/png", client=fake, budget=budget)
    statements.transcribe_image(b"x", "image/png", client=fake, budget=budget)
    assert budget["used"] == 2


def test_upload_routing_by_suffix():
    statements = pytest.importorskip("statements")
    from tests._render import render_text_png

    text, source = statements.read_statement_upload(
        b"Balance $10.", "stmt.txt")
    assert (text, source) == ("Balance $10.", "text-file")
    pdf = (FIXTURES / "statement.pdf").read_bytes()
    text, source = statements.read_statement_upload(pdf, "stmt.pdf")
    assert source == "pdf-text"
    assert "Outstanding balance" in text
    fake = _FakeClient(["scanned words"])
    text, source = statements.read_statement_upload(
        (FIXTURES / "scanned.pdf").read_bytes(), "scan.pdf", client=fake)
    assert (text, source) == ("scanned words", "vision")
    fake = _FakeClient(["photo words"])
    text, source = statements.read_statement_upload(
        render_text_png("photo words"), "shot.png", client=fake)
    assert (text, source) == ("photo words", "vision")
    with pytest.raises(ValueError, match="unsupported"):
        statements.read_statement_upload(b"data", "stmt.exe", client=fake)


def test_render_text_png_is_a_png():
    from tests._render import render_text_png

    data = render_text_png("Balance $10.")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 100


def test_rasterize_scanned_pdf_returns_page_pngs():
    statements = pytest.importorskip("statements")
    pages = statements.rasterize_pdf(
        (FIXTURES / "scanned.pdf").read_bytes())
    assert len(pages) == 1
    assert pages[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_rasterize_refuses_many_page_pdfs():
    statements = pytest.importorskip("statements")
    with pytest.raises(ValueError, match="re-upload"):
        statements.rasterize_pdf(
            (FIXTURES / "scanned.pdf").read_bytes(), max_pages=0)
