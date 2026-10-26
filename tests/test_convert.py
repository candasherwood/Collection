"""Markdown parsing, the built-in PDF writer and the conversion pipeline.

Run: python tests/test_convert.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from jadeli import convert, markdown as md  # noqa: E402
from jadeli.pdfwriter import PdfWriter, text_width, write_pdf  # noqa: E402

SAMPLE = """\
---
title: The Lantern's Edge
author: Funke
---
# Chapter One

It began with *light* — no, with **the absence of it**, and a `claim`.

## The Bands

- first
- second
  - nested one
  - nested two
- third

1. ordered one
2. ordered two

- [ ] open task
- [x] done task

> [!warning] Careful
> The third page lists names the fourth page denies.

> plain quote

```py
print("fenced")
```

| Name | Value |
| ---- | ----- |
| alpha | 1 |
| beta | 2 |

---
"""

DOCX_DOCUMENT = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Letter to the Assessor</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">Dear </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>Assessor</w:t></w:r>
       <w:r><w:t>, the </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>lantern</w:t></w:r><w:r><w:t> still burns.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Clauses</w:t></w:r></w:p>
  <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>First clause</w:t></w:r></w:p>
  <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>Second clause</w:t></w:r></w:p>
  <w:tbl>
    <w:tr><w:tc><w:p><w:r><w:t>Item</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Count</w:t></w:r></w:p></w:tc></w:tr>
    <w:tr><w:tc><w:p><w:r><w:t>Lamp</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>3</w:t></w:r></w:p></w:tc></w:tr>
  </w:tbl>
</w:body></w:document>"""

DOCX_CORE = """<?xml version="1.0"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>Letter to the Assessor</dc:title><dc:creator>Funke</dc:creator>
</cp:coreProperties>"""


def build_docx(path: Path, document_xml: str = DOCX_DOCUMENT) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        archive.writestr("docProps/core.xml", DOCX_CORE)
        archive.writestr("word/document.xml", document_xml)
    return path


class MarkdownTests(unittest.TestCase):
    def test_blocks(self) -> None:
        kinds = [block["kind"] for block in md.parse(SAMPLE)]
        self.assertEqual(kinds[0], "frontmatter")
        for wanted in ("heading", "paragraph", "list", "quote", "code", "table", "hr"):
            self.assertIn(wanted, kinds)

    def test_headings_get_anchor_ids(self) -> None:
        blocks = md.parse(SAMPLE)
        heading = next(block for block in blocks if block["kind"] == "heading" and block["level"] == 1)
        self.assertEqual(heading["id"], "chapter-one")

    def test_html_subset(self) -> None:
        html = md.to_html(SAMPLE)
        for fragment in (
            '<h1 id="chapter-one">',
            "<strong>the absence of it</strong>",
            "<em>light</em>",
            "<code>claim</code>",
            'class="callout callout-warning"',
            '<input type="checkbox" checked disabled>',
            '<pre><code class="language-py">',
            "<table>",
            "<hr>",
        ):
            self.assertIn(fragment, html, fragment)

    def test_nested_list_html_is_valid(self) -> None:
        html = md.to_html(SAMPLE)
        # A nested list opens inside its parent <li> and closes before the parent's
        # own </li>, so the markup is valid rather than merely tolerated.
        self.assertIn(
            "<ul><li>first</li><li>second<ul><li>nested one</li><li>nested two</li></ul></li><li>third</li></ul>",
            html,
        )

    def test_inline_runs(self) -> None:
        runs = md.inline_runs("plain **bold** and *it* and `x = 1` end")
        self.assertEqual(
            runs,
            [
                ("plain ", ""),
                ("bold", "b"),
                (" and ", ""),
                ("it", "i"),
                (" and ", ""),
                ("x = 1", "code"),
                (" end", ""),
            ],
        )

    def test_plain_text_drops_syntax(self) -> None:
        text = md.plain_text(SAMPLE)
        self.assertIn("Chapter One", text)
        self.assertNotIn("**", text)
        self.assertNotIn("| Name |", text)
        self.assertNotIn("title:", text)

    def test_document_is_print_ready(self) -> None:
        document = md.to_document(SAMPLE, title="Sample", author="Funke", base_href="file:///tmp/x/")
        self.assertIn("@page", document)
        self.assertIn('<base href="file:///tmp/x/">', document)
        self.assertIn("book-title", document)


class PdfWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="jadely-pdf-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def test_structure_is_self_consistent(self) -> None:
        target = self.work / "out.pdf"
        write_pdf(target, md.parse(SAMPLE), title="Sample", author="Funke")
        data = target.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))

        # Every xref offset must point at the object it claims.
        table = re.search(rb"xref\n0 (\d+)\n", data)
        self.assertIsNotNone(table, "no xref table")
        count = int(table.group(1))
        entries = re.findall(rb"(\d{10}) 00000 n", data[table.start() :])
        self.assertEqual(len(entries), count - 1)
        self.assertTrue(data.count(b"/Type /Page ") >= 1)
        for index, offset in enumerate(entries, start=1):
            position = int(offset)
            self.assertEqual(data[position : position + 20].split(b" 0 obj")[0], str(index).encode())

    def test_no_line_exceeds_the_text_column(self) -> None:
        writer = PdfWriter()
        long_word = "a" * 400
        lines = writer._wrap([(f"{'word ' * 60}{long_word}", "")], 11.0, "serif")
        for line in lines:
            width = sum(text_width(text, "serif", style, 11.0) for text, style in line)
            self.assertLessEqual(width, writer.content_width + 0.01, line[:3])

    def test_empty_document_still_valid(self) -> None:
        target = self.work / "empty.pdf"
        write_pdf(target, [])
        self.assertTrue(target.read_bytes().startswith(b"%PDF-"))
        self.assertIn(b"/Count 1", target.read_bytes())

    def test_page_numbers_count_pages(self) -> None:
        blocks = [{"kind": "heading", "level": 1, "text": f"Chapter {n}", "id": f"c{n}"} for n in range(1, 5)]
        target = self.work / "chapters.pdf"
        write_pdf(target, blocks)
        data = target.read_bytes()
        self.assertIn(b"/Count 4", data)
        self.assertIn(b"4 / 4", data)  # the last page's footer


class ConvertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="jadely-convert-"))
        self.source = self.work / "chapter.md"
        self.source.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def test_stdlib_engine(self) -> None:
        result = convert.markdown_to_pdf(self.source, self.work / "chapter.pdf", engine="stdlib")
        self.assertEqual(result["engine"], "stdlib")
        self.assertTrue(Path(result["pdf"]).read_bytes().startswith(b"%PDF-"))
        self.assertGreater(result["bytes"], 1000)

    def test_engine_auto_falls_back(self) -> None:
        result = convert.markdown_to_pdf(self.source, self.work / "auto.pdf", engine="auto")
        expected = "edge" if convert.find_browser() else "stdlib"
        self.assertEqual(result["engine"], expected)

    def test_unknown_engine_is_refused(self) -> None:
        with self.assertRaises(convert.ConvertError):
            convert.markdown_to_pdf(self.source, self.work / "x.pdf", engine="ghostscript")

    def test_missing_browser_is_reported(self) -> None:
        with self.assertRaises(convert.ConvertError) as raised:
            convert.html_to_pdf("<html></html>", self.work / "x.pdf", browser=str(self.work / "no-browser.exe"))
        self.assertIn("No Chromium-based browser", str(raised.exception))

    @unittest.skipUnless(convert.find_browser(), "no browser installed")
    def test_browser_engine(self) -> None:
        result = convert.markdown_to_pdf(self.source, self.work / "edge.pdf", engine="edge")
        data = Path(result["pdf"]).read_bytes()
        self.assertEqual(result["engine"], "edge")
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertGreater(len(data), 5000)

    def test_docx_to_markdown(self) -> None:
        docx = build_docx(self.work / "letter.docx")
        extracted = convert.docx_to_markdown(docx)
        self.assertEqual(extracted["title"], "Letter to the Assessor")
        self.assertEqual(extracted["author"], "Funke")
        body = extracted["markdown"]
        self.assertIn("# Letter to the Assessor", body)
        self.assertIn("**Assessor**", body)
        self.assertIn("*lantern*", body)
        self.assertIn("## Clauses", body)
        self.assertIn("- First clause", body)
        self.assertIn("| Item | Count |", body)

    def test_docx_to_pdf(self) -> None:
        docx = build_docx(self.work / "letter.docx")
        result = convert.docx_to_pdf(docx, self.work / "letter.pdf", engine="stdlib")
        self.assertTrue(Path(result["pdf"]).read_bytes().startswith(b"%PDF-"))

    def test_legacy_doc_is_reported_not_guessed(self) -> None:
        legacy = self.work / "old.doc"
        legacy.write_bytes(b"\xd0\xcf\x11\xe0 nonsense")
        with self.assertRaises(convert.ConvertError) as raised:
            convert.convert(legacy, self.work / "old.pdf")
        self.assertIn("cannot be read without Word", str(raised.exception))

    def test_broken_docx_is_reported(self) -> None:
        broken = self.work / "broken.docx"
        broken.write_bytes(b"not a zip")
        with self.assertRaises(convert.ConvertError):
            convert.docx_to_markdown(broken)

    def test_unsupported_extension(self) -> None:
        image = self.work / "picture.png"
        image.write_bytes(b"\x89PNG")
        with self.assertRaises(convert.ConvertError):
            convert.convert(image, self.work / "picture.pdf")

    def test_batch_migrate_skips_and_reports(self) -> None:
        folder = self.work / "manuscript"
        folder.mkdir()
        (folder / "01 - One.md").write_text("# One\n\ntext\n", encoding="utf-8")
        (folder / "02 - Two.md").write_text("# Two\n\ntext\n", encoding="utf-8")
        (folder / "03 - Old.doc").write_bytes(b"\xd0\xcf\x11\xe0")
        (folder / "notes.txt").write_text("plain text\n", encoding="utf-8")

        first = convert.migrate([str(folder)], engine="stdlib")
        self.assertEqual(first["counts"]["converted"], 3)
        self.assertEqual(first["counts"]["failed"], 1)
        self.assertFalse(first["ok"])
        self.assertTrue((folder / "01 - One.pdf").is_file())

        second = convert.migrate([str(folder)], engine="stdlib")
        self.assertEqual(second["counts"]["converted"], 0)
        self.assertEqual(second["counts"]["skipped"], 3)

        third = convert.migrate([str(folder / "01 - One.md")], engine="stdlib", overwrite=True)
        self.assertEqual(third["counts"]["converted"], 1)

    def test_cli_runs(self) -> None:
        folder = self.work / "cli"
        folder.mkdir()
        (folder / "doc.md").write_text("# Doc\n\nbody\n", encoding="utf-8")
        self.assertEqual(convert.main([str(folder), "--engine", "stdlib", "--quiet"]), 0)
        self.assertTrue((folder / "doc.pdf").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
