"""Markdown, parsed once into blocks.

The browser UI has its own renderer (``web/markdown.js``) so that reading a note
never costs a round trip. This module is the server-side twin: it exists so that
the same document can be turned into print-ready HTML for the PDF pipeline, or
laid out directly by :mod:`jadeli.pdfwriter` when no browser is available, or
reduced to plain text for search and read-aloud.

Everything here is stdlib-only on purpose — JADELY is a local-first app, and the
converter must work on a machine with nothing installed but Python.

The supported subset matches the UI renderer: headings, emphasis, strike,
highlight, inline and fenced code, links, images, wiki links, ``#tags``, task
lists, nested lists, tables, blockquotes, Obsidian-style callouts, horizontal
rules and ``---`` frontmatter.
"""

from __future__ import annotations

import html
import re

__all__ = [
    "parse",
    "to_html",
    "to_document",
    "plain_text",
    "inline_runs",
    "inline_html",
    "slugify",
    "strip_frontmatter",
    "count_words",
]

FENCE_RE = re.compile(r"^\s*(```|~~~)\s*([\w+#-]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
BULLET_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s{0,3}>\s?(.*)$")
CALLOUT_RE = re.compile(r"^\[!(\w+)\][-+]?\s*(.*)$", re.IGNORECASE)
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+(.*)$")
TAG_RE = re.compile(r"(?<![\w/&#])#([A-Za-z][\w/-]{0,63})")

CALLOUTS = {
    "note": "Note",
    "info": "Info",
    "tip": "Tip",
    "hint": "Hint",
    "important": "Important",
    "warning": "Warning",
    "caution": "Caution",
    "danger": "Danger",
    "error": "Error",
    "success": "Success",
    "question": "Question",
    "quote": "Quote",
    "example": "Example",
    "todo": "Todo",
    "abstract": "Abstract",
    "summary": "Summary",
}


# --------------------------------------------------------------------- inline
def slugify(text: str) -> str:
    """Turn a heading into an anchor id (same shape as the UI renderer)."""
    slug = re.sub(r"[`*_~\[\]()#!]", "", str(text).lower())
    slug = re.sub(r"[^a-z0-9\s-]", "", slug).strip()
    return re.sub(r"\s+", "-", slug)


def escape(text: str) -> str:
    return html.escape(str(text), quote=True)


_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
_WIKI_RE = re.compile(r"\[\[([^\[\]|#]+)(?:#([^\[\]|]+))?(?:\|([^\[\]]+))?\]\]")
_STRONG_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_EM_RE = re.compile(r"(\*|_)(?=\S)([^*_]+?)(?<=\S)\1")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_MARK_RE = re.compile(r"==(?=\S)(.+?)(?<=\S)==", re.DOTALL)

# A protected slot holds rendered HTML so later rules cannot touch it.
_SLOT = "\x00"


class _Slots:
    def __init__(self) -> None:
        self.items: list[str] = []

    def hold(self, value: str) -> str:
        self.items.append(value)
        return f"{_SLOT}{len(self.items) - 1}{_SLOT}"

    def restore(self, text: str) -> str:
        def swap(match: re.Match[str]) -> str:
            return self.items[int(match.group(1))]

        return re.sub(r"\x00(\d+)\x00", swap, text)


def inline_html(text: str, *, wiki: bool = True) -> str:
    """Render inline markdown inside a block to HTML."""
    if not text:
        return ""
    slots = _Slots()
    out = escape(text)

    out = _CODE_SPAN_RE.sub(lambda m: slots.hold(f"<code>{m.group(1)}</code>"), out)
    out = _IMAGE_RE.sub(
        lambda m: slots.hold(
            '<img src="{}" alt="{}"{} loading="lazy">'.format(
                m.group(2), m.group(1), f' title="{m.group(3)}"' if m.group(3) else ""
            )
        ),
        out,
    )
    out = _LINK_RE.sub(
        lambda m: slots.hold(
            '<a href="{}" class="external"{} target="_blank" rel="noreferrer">{}</a>'.format(
                m.group(2), f' title="{m.group(3)}"' if m.group(3) else "", m.group(1)
            )
        ),
        out,
    )
    if wiki:
        out = _WIKI_RE.sub(
            lambda m: slots.hold(
                '<a href="#" class="wikilink" data-target="{}">{}</a>'.format(
                    m.group(1).strip(), (m.group(3) or m.group(1)).strip()
                )
            ),
            out,
        )
    out = _MARK_RE.sub(lambda m: slots.hold(f"<mark>{m.group(1)}</mark>"), out)
    out = _STRONG_RE.sub(r"<strong>\2</strong>", out)
    out = _EM_RE.sub(r"<em>\2</em>", out)
    out = _STRIKE_RE.sub(r"<del>\1</del>", out)
    out = TAG_RE.sub(r'<span class="tag">#\1</span>', out)
    out = out.replace("  \n", "<br>\n")
    return slots.restore(out)


# Style names shared with the PDF writer: plain, bold, italic, bolditalic, code.
STYLES = ("", "b", "i", "bi", "code")


def inline_runs(text: str) -> list[tuple[str, str]]:
    """Split inline markdown into ``(text, style)`` runs for the PDF writer.

    Style is one of ``""`` (regular), ``"b"``, ``"i"``, ``"bi"`` or ``"code"``.
    """
    if not text:
        return []
    work = str(text)

    # \x01…\x02 fences a code span so the emphasis rules below cannot touch it.
    work = _CODE_SPAN_RE.sub(lambda m: f"\x01{m.group(1)}\x02", work)
    # Images become their alt text, links their label: a PDF has no click surface.
    work = _IMAGE_RE.sub(lambda m: (m.group(1) or "image"), work)
    work = _LINK_RE.sub(lambda m: m.group(1), work)
    work = _WIKI_RE.sub(lambda m: (m.group(3) or m.group(1)).strip(), work)

    runs: list[tuple[str, str]] = []

    def push(chunk: str, style: str) -> None:
        if not chunk:
            return
        if runs and runs[-1][1] == style:
            runs[-1] = (runs[-1][0] + chunk, style)
        else:
            runs.append((chunk, style))

    def emit(chunk: str, style: str) -> None:
        """Walk a chunk, splitting out protected code spans."""
        for part in re.split(r"(\x01[^\x02]*\x02)", chunk):
            if not part:
                continue
            if part.startswith("\x01") and part.endswith("\x02") and len(part) > 2:
                push(part[1:-1], "code")
            else:
                push(part, style)

    # Bold / italic / strike / highlight, longest markers first.
    pattern = re.compile(
        r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"
        r"|(\*|_)(?=\S)([^*_]+?)(?<=\S)\3"
        r"|~~(?=\S)(.+?)(?<=\S)~~"
        r"|==(?=\S)(.+?)(?<=\S)==",
        re.DOTALL,
    )
    position = 0
    for match in pattern.finditer(work):
        emit(work[position : match.start()], "")
        if match.group(2) is not None:
            emit(match.group(2), "b")
        elif match.group(4) is not None:
            emit(match.group(4), "i")
        elif match.group(5) is not None:
            emit(match.group(5), "")
        elif match.group(6) is not None:
            emit(match.group(6), "")
        position = match.end()
    emit(work[position:], "")

    cleaned: list[tuple[str, str]] = []
    for chunk, style in runs:
        text_only = chunk.replace("\x01", "").replace("\x02", "")
        text_only = re.sub(r"[ \t]+", " ", text_only)
        if text_only:
            cleaned.append((text_only, style))
    return cleaned


def plain_text(markdown: str) -> str:
    """Markdown with the syntax removed — for search, word counts and speech."""
    blocks = parse(markdown or "")
    return blocks_to_text(blocks)


def blocks_to_text(blocks: list[dict]) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "paragraph":
            parts.append("".join(run for run, _ in inline_runs(block["text"])))
        elif kind == "heading":
            parts.append("".join(run for run, _ in inline_runs(block["text"])))
        elif kind == "list":
            for item in block["items"]:
                parts.append("".join(run for run, _ in inline_runs(item["text"])))
        elif kind == "quote":
            parts.append("".join(run for run, _ in inline_runs(block["text"])))
        elif kind == "code":
            parts.append(block["text"].strip())
        elif kind == "table":
            parts.append(" ".join(block["header"]))
            for row in block["rows"]:
                parts.append(" ".join(row))
    text = "\n\n".join(part for part in parts if part and part.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def count_words(markdown: str) -> int:
    text = plain_text(markdown)
    return len(text.split()) if text else 0


# --------------------------------------------------------------------- blocks
def strip_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    """Return ``(frontmatter, body)`` for a leading ``---`` block."""
    text = str(markdown or "")
    match = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", text)
    if not match:
        return {}, text
    data: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        pair = re.match(r"^([\w-]+)\s*:\s*(.*)$", line.strip())
        if pair:
            data[pair.group(1)] = pair.group(2).strip().strip("\"'")
    return data, text[match.end() :]


def _is_block_start(line: str) -> bool:
    if not line.strip():
        return True
    return bool(
        FENCE_RE.match(line)
        or HEADING_RE.match(line)
        or HR_RE.match(line)
        or BULLET_RE.match(line)
        or ORDERED_RE.match(line)
        or QUOTE_RE.match(line)
        or line.lstrip().startswith("|")
    )


def _split_row(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    # A backslash escapes a literal pipe.
    cells = re.split(r"(?<!\\)\|", row)
    return [cell.replace("\\|", "|").strip() for cell in cells]


def _collect_list(lines: list[str], start: int) -> tuple[dict, int]:
    ordered = False
    items: list[dict] = []
    index = start
    base_indent: int | None = None

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            # A blank line only ends the list if the next line is not a continuation.
            look = index + 1
            while look < len(lines) and not lines[look].strip():
                look += 1
            if look >= len(lines):
                index = look
                break
            candidate = lines[look]
            if not (BULLET_RE.match(candidate) or ORDERED_RE.match(candidate)):
                break
            index = look
            continue

        bullet = BULLET_RE.match(line)
        number = ORDERED_RE.match(line)
        match = bullet or number
        if not match:
            # Continuation of the previous item (wrapped source line).
            if items and (line.startswith("  ") or line.startswith("\t")):
                items[-1]["text"] += " " + line.strip()
                index += 1
                continue
            break

        indent = len(match.group(1).replace("\t", "    "))
        if base_indent is None:
            base_indent = indent
            ordered = bool(number)
        elif indent < base_indent:
            break

        level = min(3, max(0, (indent - base_indent) // 2))
        text = match.group(3).strip()
        task: bool | None = None
        task_match = TASK_RE.match(text)
        if task_match:
            task = task_match.group(1).lower() == "x"
            text = task_match.group(2).strip()
        if bool(number) != ordered and level == 0 and items:
            # A different marker at the top level starts a new list.
            break
        items.append({"text": text, "level": level, "task": task})
        index += 1

    return {"kind": "list", "ordered": ordered, "items": items}, index


def _collect_table(lines: list[str], start: int) -> tuple[dict | None, int]:
    if start + 1 >= len(lines) or not TABLE_SEP_RE.match(lines[start + 1]):
        return None, start
    header = _split_row(lines[start])
    index = start + 2
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        rows.append(_split_row(lines[index]))
        index += 1
    width = len(header)
    for row in rows:
        while len(row) < width:
            row.append("")
    return {"kind": "table", "header": header, "rows": rows}, index


def parse(markdown: str) -> list[dict]:
    """Parse markdown into a list of block dictionaries."""
    frontmatter, body = strip_frontmatter(markdown)
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict] = []
    if frontmatter:
        blocks.append({"kind": "frontmatter", "data": frontmatter})

    index = 0
    while index < len(lines):
        line = lines[index]

        if not line.strip():
            index += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            language = fence.group(2) or ""
            index += 1
            collected: list[str] = []
            while index < len(lines) and not re.match(rf"^\s*{re.escape(marker)}\s*$", lines[index]):
                collected.append(lines[index])
                index += 1
            index += 1  # closing fence
            blocks.append({"kind": "code", "lang": language, "text": "\n".join(collected)})
            continue

        heading = HEADING_RE.match(line)
        if heading:
            text = heading.group(2).strip()
            blocks.append(
                {
                    "kind": "heading",
                    "level": len(heading.group(1)),
                    "text": text,
                    "id": slugify(text),
                }
            )
            index += 1
            continue

        if HR_RE.match(line):
            blocks.append({"kind": "hr"})
            index += 1
            continue

        if line.lstrip().startswith("|"):
            table, next_index = _collect_table(lines, index)
            if table:
                blocks.append(table)
                index = next_index
                continue

        if QUOTE_RE.match(line):
            quoted: list[str] = []
            while index < len(lines) and QUOTE_RE.match(lines[index]):
                quoted.append(QUOTE_RE.match(lines[index]).group(1))  # type: ignore[union-attr]
                index += 1
            callout = None
            label = ""
            first = CALLOUT_RE.match(quoted[0]) if quoted else None
            if first:
                kind = first.group(1).lower()
                if kind in CALLOUTS:
                    callout = kind
                    label = first.group(2).strip()
                    quoted = quoted[1:]
                    if quoted and not quoted[0].strip():
                        quoted = quoted[1:]
            blocks.append(
                {
                    "kind": "quote",
                    "text": "\n".join(quoted).strip("\n"),
                    "callout": callout,
                    "label": label,
                }
            )
            continue

        if BULLET_RE.match(line) or ORDERED_RE.match(line):
            listing, next_index = _collect_list(lines, index)
            if listing["items"]:
                blocks.append(listing)
                index = next_index
                continue

        # Paragraph: consecutive lines until a blank line or a new block.
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and not (
            paragraph and _is_block_start(lines[index])
        ):
            paragraph.append(lines[index])
            index += 1
        if not paragraph:
            paragraph.append(lines[index])
            index += 1
        blocks.append({"kind": "paragraph", "text": "\n".join(paragraph)})

    return blocks


# ----------------------------------------------------------------------- html
def _html_list(block: dict) -> str:
    """Nested lists stay inside their parent ``<li>``, so the HTML is valid."""
    tag = "ol" if block["ordered"] else "ul"
    out = [f"<{tag}>"]
    level = 0
    open_item = False
    for item in block["items"]:
        target = item["level"]
        while target > level:
            out.append(f"<{tag}>")  # nested list, still inside the parent <li>
            level += 1
            open_item = False
        while target < level:
            if open_item:
                out.append("</li>")
            out.append(f"</{tag}>")
            level -= 1
            open_item = True  # back inside the parent item
        if open_item:
            out.append("</li>")
        check = ""
        if item["task"] is True:
            check = '<input type="checkbox" checked disabled> '
        elif item["task"] is False:
            check = '<input type="checkbox" disabled> '
        css = ' class="task"' if item["task"] is not None else ""
        out.append(f'<li{css}>{check}{inline_html(item["text"])}')  # closed lazily
        open_item = True
    while level > 0:
        if open_item:
            out.append("</li>")
            open_item = False
        out.append(f"</{tag}>")
        level -= 1
        open_item = True
    if open_item:
        out.append("</li>")
    out.append(f"</{tag}>")
    return "".join(out)


def blocks_to_html(blocks: list[dict], *, wiki: bool = True) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "frontmatter":
            rows = "".join(
                f'<div class="prop"><span class="prop-key">{escape(key)}</span>'
                f'<span class="prop-value">{escape(value)}</span></div>'
                for key, value in block["data"].items()
            )
            out.append(f'<div class="properties">{rows}</div>')
        elif kind == "heading":
            level = block["level"]
            text = inline_html(block["text"], wiki=wiki)
            out.append(f'<h{level} id="{block["id"]}">{text}</h{level}>')
        elif kind == "paragraph":
            out.append(f'<p>{inline_html(block["text"], wiki=wiki)}</p>')
        elif kind == "list":
            out.append(_html_list(block))
        elif kind == "quote":
            text = inline_html(block["text"], wiki=wiki)
            if block.get("callout"):
                font = CALLOUTS.get(block["callout"], block["callout"].title())
                title = block.get("label") or font
                out.append(
                    f'<blockquote class="callout callout-{block["callout"]}">'
                    f'<div class="callout-title">{escape(title)}</div>{text}</blockquote>'
                )
            else:
                out.append(f"<blockquote>{text}</blockquote>")
        elif kind == "code":
            language = block.get("lang") or ""
            klass = f' class="language-{escape(language)}"' if language else ""
            out.append(f"<pre><code{klass}>{escape(block['text'])}</code></pre>")
        elif kind == "hr":
            out.append("<hr>")
        elif kind == "table":
            head = "".join(f"<th>{inline_html(cell, wiki=wiki)}</th>" for cell in block["header"])
            body = "".join(
                "<tr>" + "".join(f"<td>{inline_html(cell, wiki=wiki)}</td>" for cell in row) + "</tr>"
                for row in block["rows"]
            )
            out.append(
                f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead>"
                f"<tbody>{body}</tbody></table></div>"
            )
    return "\n".join(out)


def to_html(markdown: str, *, wiki: bool = True, frontmatter: bool = True) -> str:
    blocks = parse(markdown or "")
    if not frontmatter:
        blocks = [block for block in blocks if block["kind"] != "frontmatter"]
    return blocks_to_html(blocks, wiki=wiki)


PRINT_CSS = """
/* JADELY print stylesheet — used for the PDF pipeline (Edge) and for printing
   from a browser. Kept deliberately serif-and-whitespace: this is for reading. */
@page { size: A4; margin: 20mm 18mm 22mm; }
html { font-size: 11.5pt; }
body {
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.55; color: #14161a; margin: 0;
  hyphens: auto; -webkit-hyphens: auto;
}
.book-title { font-size: 26pt; line-height: 1.15; margin: 0 0 4pt; }
.book-sub { color: #5b6270; font-size: 11pt; margin: 0 0 4pt; }
.book-rule { border: 0; border-top: 1px solid #c8ccd4; margin: 14pt 0 18pt; }
h1, h2, h3, h4, h5, h6 { font-family: "Iowan Old Style", Georgia, serif; line-height: 1.25; }
h1 { font-size: 21pt; margin: 0 0 10pt; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 15pt; margin: 16pt 0 6pt; page-break-after: avoid; }
h3 { font-size: 13pt; margin: 14pt 0 5pt; page-break-after: avoid; }
h4, h5, h6 { font-size: 11.5pt; margin: 12pt 0 4pt; page-break-after: avoid; }
p { margin: 0 0 8pt; orphans: 2; widows: 2; }
em { font-style: italic; } strong { font-weight: 700; }
a { color: #14161a; text-decoration: none; }
mark { background: #ffe9a8; }
code, pre { font-family: "Cascadia Mono", Consolas, "Courier New", monospace; font-size: 9.5pt; }
pre { background: #f4f5f7; border: 1px solid #e2e5ea; border-radius: 3pt; padding: 8pt 10pt;
      white-space: pre-wrap; page-break-inside: avoid; }
blockquote { margin: 0 0 8pt; padding-left: 10pt; border-left: 2pt solid #c8ccd4; color: #3d434f; }
.callout { background: #f6f7f9; border: 1px solid #e2e5ea; border-left: 3pt solid #8b93a3;
           padding: 8pt 10pt; border-radius: 3pt; }
.callout-title { font-weight: 700; font-size: 10pt; text-transform: uppercase;
                 letter-spacing: .06em; color: #5b6270; margin-bottom: 4pt; }
ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
li { margin: 0 0 3pt; }
li.task { list-style: none; margin-left: -14pt; }
hr { border: 0; border-top: 1px solid #c8ccd4; margin: 14pt 0; }
table { border-collapse: collapse; width: 100%; margin: 0 0 10pt; font-size: 10pt; }
th, td { border: 1px solid #d7dbe2; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #f4f5f7; }
.properties { border: 1px solid #e2e5ea; border-radius: 3pt; padding: 6pt 8pt; margin: 0 0 12pt;
              font-size: 9.5pt; color: #3d434f; }
.prop { display: flex; gap: 8pt; }
.prop-key { min-width: 90pt; color: #5b6270; }
img { max-width: 100%; }
"""


def to_document(
    markdown: str,
    *,
    title: str = "",
    subtitle: str = "",
    author: str = "",
    wiki: bool = True,
    extra_css: str = "",
    base_href: str = "",
) -> str:
    """A complete, self-contained print-ready HTML document.

    ``base_href`` lets relative image paths resolve against the folder the
    markdown lives in when a browser prints the document.
    """
    body = to_html(markdown, wiki=wiki)
    heading = f'<h1 class="book-title">{escape(title)}</h1>' if title else ""
    sub = " · ".join(part for part in (author, subtitle) if part)
    subtitle_html = f'<p class="book-sub">{escape(sub)}</p>' if sub else ""
    rule = '<hr class="book-rule">' if heading or subtitle_html else ""
    base = f'<base href="{escape(base_href)}">\n' if base_href else ""
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        f"{base}"
        f"<title>{escape(title or 'Document')}</title>\n"
        f"<style>{PRINT_CSS}{extra_css}</style>\n"
        "</head>\n<body>\n"
        f"<header>{heading}{subtitle_html}{rule}</header>\n"
        f"{body}\n"
        "</body></html>\n"
    )
