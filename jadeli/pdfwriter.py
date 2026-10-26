"""A very small PDF writer — stdlib only.

JADELY's preferred PDF engine is a headless browser (Edge/Chrome
``--print-to-pdf``) because it renders the real stylesheet. This module is the
safety net: when no browser is installed, migration still produces a proper,
readable PDF with nothing but Python.

It lays out the block list from :mod:`jadeli.markdown` on A4 pages using the PDF
base-14 fonts, so no font files are needed either. Character widths are the
standard AFM values for Times and Helvetica; the bold and italic faces reuse
their roman metrics, which is accurate enough for line breaking (a fraction of a
percent) and keeps this file small.

What the fallback does not do: images, coloured callout boxes beyond the border,
and right-aligned or justified text. It handles the prose-and-chapters material
JADELY produces.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["PdfWriter", "A4", "write_pdf"]

A4 = (595.276, 841.89)

# --------------------------------------------------------------- font metrics
# Widths for ASCII 32..126, in 1000ths of the font size.
_TIMES = (
    "250 333 408 500 500 833 778 180 333 333 500 564 250 333 250 278 "
    "500 500 500 500 500 500 500 500 500 500 278 278 564 564 564 444 921 "
    "722 667 667 722 611 556 722 722 333 389 722 611 889 722 722 556 722 667 556 611 722 722 944 722 722 611 "
    "333 278 333 469 500 333 "
    "444 500 444 500 444 333 500 500 278 278 500 278 778 500 500 500 500 333 389 278 500 500 722 500 500 444 "
    "480 200 480 541"
)
_HELV = (
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 "
    "556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 1015 "
    "667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778 722 667 611 722 667 944 667 667 611 "
    "278 278 278 469 556 333 "
    "556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556 333 500 278 556 500 722 500 500 500 "
    "334 260 334 584"
)

# A few characters outside ASCII that appear in real prose.
_TIMES_EXTRA = {
    "\u2018": 333, "\u2019": 250, "\u201c": 444, "\u201d": 444, "\u2013": 500,
    "\u2014": 1000, "\u2026": 1000, "\u00e9": 444, "\u00e8": 444, "\u00e0": 444,
    "\u00fc": 500, "\u00f6": 500, "\u00e4": 444, "\u00df": 500, "\u2022": 350,
    "\u20ac": 500, "\u00a0": 250, "\u00ab": 500, "\u00bb": 500, "\u00f1": 500,
    "\u00e7": 444, "\u00cd": 333, "\u00dc": 722,
}
_HELV_EXTRA = {
    "\u2018": 222, "\u2019": 222, "\u201c": 333, "\u201d": 333, "\u2013": 556,
    "\u2014": 1000, "\u2026": 1000, "\u00e9": 556, "\u00e8": 556, "\u00e0": 556,
    "\u00fc": 556, "\u00f6": 556, "\u00e4": 556, "\u00df": 556, "\u2022": 350,
    "\u20ac": 556, "\u00a0": 278, "\u00ab": 556, "\u00bb": 556, "\u00f1": 556,
    "\u00e7": 500, "\u00cd": 278, "\u00dc": 722,
}


def _table(spec: str, extra: dict[str, int]) -> dict[str, int]:
    values = spec.split()
    assert len(values) == 95, f"width table has {len(values)} entries, expected 95"
    table = {chr(32 + index): int(width) for index, width in enumerate(values)}
    table.update(extra)
    return table


WIDTHS = {
    "serif": _table(_TIMES, _TIMES_EXTRA),
    "sans": _table(_HELV, _HELV_EXTRA),
    "mono": {},
}
MONO_WIDTH = 600

BASE_FONTS = {
    "F1": "Times-Roman",
    "F2": "Times-Bold",
    "F3": "Times-Italic",
    "F4": "Times-BoldItalic",
    "F5": "Helvetica",
    "F6": "Helvetica-Bold",
    "F7": "Helvetica-Oblique",
    "F8": "Helvetica-BoldOblique",
    "F9": "Courier",
    "F10": "Courier-Bold",
    "F11": "Courier-Oblique",
    "F12": "Courier-BoldOblique",
}

_FACE = {
    ("serif", ""): "F1", ("serif", "b"): "F2", ("serif", "i"): "F3", ("serif", "bi"): "F4",
    ("sans", ""): "F5", ("sans", "b"): "F6", ("sans", "i"): "F7", ("sans", "bi"): "F8",
    ("mono", ""): "F9", ("mono", "b"): "F10", ("mono", "i"): "F11", ("mono", "bi"): "F12",
}


def face(family: str, style: str) -> str:
    style = style if style in ("b", "i", "bi") else ""
    if family == "mono" and style == "bi":
        style = "b"
    return _FACE.get((family, style), "F1")


def text_width(text: str, family: str, style: str, size: float) -> float:
    if family == "mono":
        unit = MONO_WIDTH
        return len(text) * unit / 1000.0 * size
    table = WIDTHS.get(family) or WIDTHS["serif"]
    bold = "b" in style
    # Bold faces are a touch wider than roman; nudge by 3% rather than carry a
    # second set of tables.
    factor = 1.03 if bold else 1.0
    total = 0
    for character in text:
        total += table.get(character, 500)
    return total / 1000.0 * size * factor


def _pdf_string(text: str) -> bytes:
    """A PDF literal string: cp1252 bytes, with the three specials escaped."""
    raw = text.encode("cp1252", "replace")
    out = bytearray(b"(")
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):
            out.append(0x5C)
            out.append(byte)
        elif byte < 32:
            out.extend(b"\\%03o" % byte)
        else:
            out.append(byte)
    out.append(0x29)
    return bytes(out)


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


class PdfWriter:
    """Lay out blocks on A4 pages and serialise a PDF file."""

    def __init__(
        self,
        *,
        page_width: float = A4[0],
        page_height: float = A4[1],
        margin_x: float = 56.0,
        margin_y: float = 54.0,
        title: str = "",
        author: str = "",
        subject: str = "",
        footer: bool = True,
    ) -> None:
        self.page_width = page_width
        self.page_height = page_height
        self.margin_x = margin_x
        self.margin_y = margin_y
        self.title = title
        self.author = author
        self.subject = subject
        self.footer = footer
        self.content_width = page_width - 2 * margin_x
        self.pages: list[list[str]] = []
        self._y = 0.0
        self._bottom = margin_y + (20.0 if footer else 0.0)
        self._drawn = False
        self._new_page()

    # ------------------------------------------------------------- mechanics
    def _new_page(self) -> None:
        self.pages.append([])
        self._y = self.page_height - self.margin_y

    def _op(self, op: str) -> None:
        self.pages[-1].append(op)
        self._drawn = True

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def _ensure(self, height: float) -> None:
        if self._y - height < self._bottom:
            self._new_page()

    def page_break(self) -> None:
        """Start a new page unless the current one is still empty."""
        if self.pages[-1]:
            self._new_page()

    def space(self, amount: float) -> None:
        self._y -= amount

    # ----------------------------------------------------------------- widths
    @staticmethod
    def width(text: str, family: str = "serif", style: str = "", size: float = 11.0) -> float:
        return text_width(text, family, style, size)

    # ------------------------------------------------------------- primitives
    def _draw_line(
        self,
        line: list[tuple[str, str]],
        x: float,
        size: float,
        family: str,
        color: tuple[float, float, float] | None = None,
    ) -> None:
        pieces = [(text, style) for text, style in line if text.strip()]
        if not pieces:
            return
        parts: list[str] = []
        if color:
            parts.append(f"{color[0]} {color[1]} {color[2]} rg")
        parts.append("BT")
        parts.append(f"1 0 0 1 {_num(x)} {_num(self._y)} Tm")
        current = ""
        for text, style in pieces:
            wanted = face(family, style)
            if wanted != current:
                parts.append(f"/{wanted} {_num(size)} Tf")
                current = wanted
            parts.append(f"{_pdf_string(text).decode('latin-1')} Tj")
        parts.append("ET")
        if color:
            parts.append("0 0 0 rg")
        # Keep the raw cp1252 bytes intact through the join.
        self._op(" ".join(parts).encode("latin-1", "replace").decode("latin-1"))

    def _wrap(
        self,
        runs: list[tuple[str, str]],
        size: float,
        family: str,
        indent: float = 0.0,
    ) -> list[list[tuple[str, str]]]:
        available = self.content_width - indent
        lines: list[list[tuple[str, str]]] = []
        current: list[tuple[str, str]] = []
        x = 0.0
        for text, style in runs:
            for token in re.findall(r"\S+\s*", text):
                token_width = text_width(token, family, style, size)
                if x + token_width > available and current:
                    lines.append(current)
                    current = []
                    x = 0.0
                    token = token.lstrip()
                    if not token:
                        continue
                    token_width = text_width(token, family, style, size)
                while token_width > available and len(token) > 1:
                    # A single unbreakable token (a URL, a long identifier).
                    ratio = available / token_width if token_width else 1.0
                    cut = max(1, min(len(token) - 1, int(len(token) * ratio)))
                    current.append((token[:cut], style))
                    lines.append(current)
                    current = []
                    x = 0.0
                    token = token[cut:]
                    token_width = text_width(token, family, style, size)
                current.append((token, style))
                x += token_width
        if current:
            lines.append(current)
        return lines or [[]]

    def add_text(
        self,
        runs: list[tuple[str, str]],
        *,
        size: float = 11.0,
        leading: float | None = None,
        family: str = "serif",
        indent: float = 0.0,
        space_before: float = 0.0,
        space_after: float = 6.0,
        color: tuple[float, float, float] | None = None,
    ) -> None:
        leading = leading or size * 1.42
        if space_before:
            self.space(space_before)
        for line in self._wrap(runs, size, family, indent):
            self._ensure(leading)
            self._y -= leading
            self._draw_line(line, self.margin_x + indent, size, family, color)
        if space_after:
            self.space(space_after)

    def add_marked_line(
        self,
        marker: str,
        runs: list[tuple[str, str]],
        *,
        size: float = 11.0,
        leading: float | None = None,
        indent: float = 0.0,
        space_after: float = 3.0,
        color: tuple[float, float, float] | None = None,
    ) -> None:
        """A list item: the marker sits in the gutter, the text hangs."""
        leading = leading or size * 1.42
        lines = self._wrap(runs, size, "serif", indent)
        for index, line in enumerate(lines):
            self._ensure(leading)
            self._y -= leading
            if index == 0 and marker:
                self._draw_line([(marker, "")], self.margin_x + indent - 16, size, "serif", color)
            self._draw_line(line, self.margin_x + indent, size, "serif", color)
        if space_after:
            self.space(space_after)

    def add_rule(self, *, space_before: float = 8.0, space_after: float = 10.0) -> None:
        if space_before:
            self.space(space_before)
        self._ensure(4.0)
        self._y -= 4.0
        left = self.margin_x
        right = self.page_width - self.margin_x
        self._op(
            f"0.72 0.74 0.78 RG 0.7 w {_num(left)} {_num(self._y)} m "
            f"{_num(right)} {_num(self._y)} l S 0 0 0 RG"
        )
        if space_after:
            self.space(space_after)

    def add_code(self, text: str, *, size: float = 9.0, indent: float = 10.0,
                 space_before: float = 8.0, space_after: float = 10.0) -> None:
        leading = size * 1.36
        if space_before:
            self.space(space_before)
        rows: list[list[tuple[str, str]]] = []
        for raw in (text or "").split("\n"):
            rows.extend(self._wrap([(raw, "")], size, "mono", indent + 10))
        for row in rows:
            self._ensure(leading)
            self._y -= leading
            top = self._y + leading * 0.78
            self._op(
                f"0.960 0.965 0.975 rg {_num(self.margin_x + indent - 2)} {_num(self._y - leading * 0.28)} "
                f"{_num(self.content_width - indent + 2)} {_num(leading)} re f 0 0 0 rg"
            )
            self._draw_line(row, self.margin_x + indent + 5, size, "mono")
            del top
        if space_after:
            self.space(space_after)

    def add_table(self, header: list[str], rows: list[list[str]], *, size: float = 9.0,
                  space_before: float = 8.0, space_after: float = 10.0) -> None:
        if not header:
            return
        leading = size * 1.5
        columns = len(header)
        natural = []
        for index in range(columns):
            widest = text_width(header[index], "sans", "b", size)
            for row in rows:
                cell = row[index] if index < len(row) else ""
                widest = max(widest, text_width(cell, "serif", "", size))
            natural.append(max(38.0, widest))
        total = sum(natural)
        scale = min(1.0, (self.content_width + 8) / total)
        widths = [value * scale + 8 for value in natural]
        # Distribute rounding so the grid lines up with the right margin.
        widths[-1] += (self.content_width + 8) - sum(widths)

        if space_before:
            self.space(space_before)

        def row(cells: list[str], bold: bool) -> None:
            self._ensure(leading)
            self._y -= leading
            x = self.margin_x - 4
            if bold:
                self._op(
                    f"0.960 0.965 0.975 rg {_num(self.margin_x - 4)} {_num(self._y - leading * 0.3)} "
                    f"{_num(self.content_width + 8)} {_num(leading)} re f 0 0 0 rg"
                )
            for index, width in enumerate(widths):
                cell = cells[index] if index < len(cells) else ""
                family, style = ("sans", "b") if bold else ("serif", "")
                while cell and text_width(cell, family, style, size) > width - 8:
                    cell = cell[:-1]
                self._draw_line([(cell, style)], x + 4, size, family)
                x += width
            left = self.margin_x - 4
            self._op(
                f"0.72 0.74 0.78 RG 0.5 w {_num(left)} {_num(self._y + leading * 0.72)} m "
                f"{_num(left + self.content_width + 8)} {_num(self._y + leading * 0.72)} l S 0 0 0 RG"
            )

        row(header, True)
        for entry in rows:
            row(entry, False)
        # Bottom border.
        left = self.margin_x - 4
        self._op(
            f"0.72 0.74 0.78 RG 0.5 w {_num(left)} {_num(self._y - leading * 0.28)} m "
            f"{_num(left + self.content_width + 8)} {_num(self._y - leading * 0.28)} l S 0 0 0 RG"
        )
        if space_after:
            self.space(space_after)

    # ---------------------------------------------------------------- blocks
    HEADING_SIZE = {1: 21.0, 2: 15.0, 3: 12.5, 4: 11.5, 5: 11.0, 6: 11.0}

    def add_heading(self, text: str, level: int, *, chapter_breaks: bool = True) -> None:
        from .markdown import inline_runs

        level = max(1, min(6, int(level)))
        size = self.HEADING_SIZE[level]
        leading = size * 1.28
        if level == 1:
            if chapter_breaks and self.pages[-1]:
                self._new_page()
            before, after = 10.0 if not self._drawn else 26.0, 10.0
        elif level == 2:
            before, after = 18.0, 6.0
        elif level == 3:
            before, after = 14.0, 5.0
        else:
            before, after = 12.0, 4.0
        if before:
            self.space(before)
        # Do not leave a heading stranded at the foot of a page.
        if self._y - leading * 2 - 20 < self._bottom:
            self._new_page()
        for line in self._wrap(inline_runs(text), size, "serif"):
            self._ensure(leading)
            self._y -= leading
            self._draw_line([(text, "b") for text, _ in line], self.margin_x, size, "sans")
        self.space(after)

    def add_blocks(self, blocks: list[dict], *, chapter_breaks: bool = True,
                    title: str = "", subtitle: str = "") -> None:
        from .markdown import inline_runs

        if title:
            self.add_title(title, subtitle)

        for block in blocks:
            kind = block["kind"]
            if kind == "frontmatter":
                for key, value in block["data"].items():
                    self.add_text(
                        [(f"{key}: ", "b"), (str(value), "")],
                        size=8.5,
                        leading=12.0,
                        family="sans",
                        space_before=0.0,
                        space_after=1.0,
                        color=(0.36, 0.39, 0.45),
                    )
                self.space(6.0)
            elif kind == "heading":
                self.add_heading(block["text"], block["level"], chapter_breaks=chapter_breaks)
            elif kind == "paragraph":
                self.add_text(inline_runs(block["text"]))
            elif kind == "list":
                counters: dict[int, int] = {}
                for item in block["items"]:
                    level = int(item.get("level") or 0)
                    if block["ordered"]:
                        counters[level] = counters.get(level, 0) + 1
                        for deeper in [key for key in counters if key > level]:
                            del counters[deeper]
                        marker = f"{counters[level]}."
                    else:
                        marker = "\u2022" if level == 0 else "\u2013"
                    if item.get("task") is True:
                        marker = "\u2611"
                    elif item.get("task") is False:
                        marker = "\u2610"
                    self.add_marked_line(
                        marker,
                        inline_runs(item["text"]),
                        indent=20.0 + level * 16.0,
                        size=10.5 + (0.5 if level == 0 else 0.0),
                        space_after=2.0,
                    )
                self.space(6.0)
            elif kind == "quote":
                if block.get("callout"):
                    label = block.get("label") or block["callout"].title()
                    self.add_text(
                        [(label.upper(), "b")],
                        size=8.5,
                        leading=12.0,
                        family="sans",
                        indent=14.0,
                        space_before=6.0,
                        space_after=2.0,
                        color=(0.36, 0.39, 0.45),
                    )
                self.add_text(
                    inline_runs(block["text"] or ""),
                    size=10.5,
                    indent=14.0,
                    space_before=2.0 if block.get("callout") else 6.0,
                    space_after=6.0,
                    color=(0.28, 0.31, 0.36),
                )
            elif kind == "code":
                self.add_code(block["text"])
            elif kind == "hr":
                self.add_rule()
            elif kind == "table":
                self.add_table(block["header"], block["rows"])

    def add_title(self, title: str, subtitle: str = "") -> None:
        from .markdown import inline_runs

        self.space(30.0)
        for line in self._wrap(inline_runs(title), 26.0, "serif"):
            self._ensure(32.0)
            self._y -= 32.0
            self._draw_line([(text, "") for text, _ in line], self.margin_x, 26.0, "serif")
        if subtitle:
            self.add_text(
                inline_runs(subtitle),
                size=10.5,
                leading=15.0,
                family="sans",
                space_before=6.0,
                space_after=2.0,
                color=(0.36, 0.39, 0.45),
            )
        self.add_rule(space_before=4.0, space_after=18.0)

    # ------------------------------------------------------------------ build
    def _draw_footer(self, ops: list[str], number: int, total: int) -> None:
        label = f"{number}" if total < 2 else f"{number} / {total}"
        label_width = text_width(label, "sans", "", 8.5)
        x = (self.page_width - label_width) / 2
        ops.append(
            "0.55 0.58 0.63 rg BT 1 0 0 1 "
            f"{_num(x)} {_num(self.margin_y * 0.42)} Tm /F5 8.5 Tf "
            f"{_pdf_string(label).decode('latin-1')} Tj ET 0 0 0 rg"
        )

    def build(self) -> bytes:
        if self.footer:
            total = len(self.pages)
            for index, ops in enumerate(self.pages, start=1):
                self._draw_footer(ops, index, total)

        objects: list[bytes] = []

        def add_object(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_ids: dict[str, int] = {}
        for name, base in BASE_FONTS.items():
            font_ids[name] = add_object(
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode()
            )

        page_ids: list[int] = []
        content_ids: list[int] = []
        # Placeholder for the pages tree; its number is fixed after the fonts.
        pages_id = add_object(b"")  # filled in below
        for ops in self.pages:
            stream = ("\n".join(ops)).encode("latin-1", "replace")
            content_ids.append(
                add_object(
                    f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
                )
            )
            page_ids.append(-1)  # filled in the loop below

        # Page objects reference their content, so add them after the streams.
        for index, content_id in enumerate(content_ids):
            resources = " ".join(f"/{name} {number} 0 R" for name, number in font_ids.items())
            body = (
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {_num(self.page_width)} {_num(self.page_height)}] "
                f"/Resources << /Font << {resources} >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode()
            page_ids[index] = add_object(body)

        kids = " ".join(f"{number} 0 R" for number in page_ids)
        objects[pages_id - 1] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
        )
        catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

        info_bits = []
        if self.title:
            info_bits.append(f"/Title {_pdf_string(self.title).decode('latin-1')}")
        if self.author:
            info_bits.append(f"/Author {_pdf_string(self.author).decode('latin-1')}")
        if self.subject:
            info_bits.append(f"/Subject {_pdf_string(self.subject).decode('latin-1')}")
        info_bits.append("/Producer (JADELY)")
        info_bits.append("/Creator (JADELY)")
        info_id = add_object(("<< " + " ".join(info_bits) + " >>").encode("latin-1", "replace"))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        start_xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{start_xref}\n%%EOF\n"
        ).encode()
        return bytes(out)


def write_pdf(
    path: str | Path,
    blocks: list[dict],
    *,
    title: str = "",
    author: str = "",
    subtitle: str = "",
    subject: str = "",
    chapter_breaks: bool = True,
) -> Path:
    """Render ``blocks`` to a PDF file at ``path``."""
    writer = PdfWriter(title=title, author=author, subject=subject)
    writer.add_blocks(blocks, chapter_breaks=chapter_breaks, title=title, subtitle=subtitle)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(writer.build())
    return target
