"""Test-only PNG renderer for the multimodal validation run.

Renders statement text as a plain image so vision transcription can be
measured against the text-input baseline. Never imported by runtime code:
app.py and statements.py must not depend on Pillow.
"""

from __future__ import annotations

import io


def render_text_png(text: str, width: int = 800, margin: int = 24) -> bytes:
    """Black-on-white PNG lines of text, one PIL default-font row each.
    Long lines wrap to the image width first: silently overflowing the
    margin would test cropping, not transcription."""
    from PIL import Image, ImageDraw

    rows: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
        rows.extend(_wrap(paragraph, width - 2 * margin))
    height = margin * 2 + 18 * len(rows)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(rows):
        draw.text((margin, margin + 18 * i), line, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _wrap(paragraph: str, max_width: int) -> list[str]:
    """Greedy word wrap by pixel width. A single word wider than the
    image stays whole: splitting it would test fragments, not reading."""
    from PIL import ImageFont

    font = ImageFont.load_default()
    rows, row = [], ""
    for word in paragraph.split(" "):
        candidate = word if not row else row + " " + word
        if font.getlength(candidate) <= max_width or not row:
            row = candidate
        else:
            rows.append(row)
            row = word
    rows.append(row)
    return rows
