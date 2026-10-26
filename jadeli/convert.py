"""Migrations to PDF: markdown, plain text and Word (.docx).

Two engines, chosen automatically:

* ``edge`` — a headless Chromium (Microsoft Edge or Chrome) prints the real
  stylesheet from :func:`jadeli.markdown.to_document`. Best typography.
* ``stdlib`` — :mod:`jadeli.pdfwriter` lays the same document out with no
  dependencies at all. Used when no browser is installed, or on request.

Word documents are first reduced to markdown (``word/document.xml`` inside the
``.docx`` zip), then follow the identical path, so a manuscript has one renderer
no matter where it came from. Legacy binary ``.doc`` files cannot be read without
Word itself and are reported as unsupported rather than guessed at.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from . import markdown as md
from .pdfwriter import write_pdf

__all__ = [
    "ConvertError",
    "SUPPORTED_EXTENSIONS",
    "LEGACY_EXTENSIONS",
    "MIGRATABLE_EXTENSIONS",
    "find_browser",
    "html_to_pdf",
    "markdown_to_pdf",
    "docx_to_markdown",
    "convert",
    "migrate",
    "main",
]

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".docx"}
LEGACY_EXTENSIONS = {".doc", ".rtf", ".odt"}
# What a folder sweep will look at. Legacy Word formats are included on purpose:
# they cannot be read here, and the report should say so rather than skip them
# quietly and leave you wondering where the file went.
MIGRATABLE_EXTENSIONS = SUPPORTED_EXTENSIONS | LEGACY_EXTENSIONS

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


class ConvertError(Exception):
    """Anything the user should see as a clear message."""


# ------------------------------------------------------------------- browser
def _browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("JADELY_BROWSER")
    if override:
        candidates.append(Path(override))
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relatives = [
        r"Microsoft\Edge\Application\msedge.exe",
        r"Google\Chrome\Application\chrome.exe",
    ]
    for root in roots:
        if not root:
            continue
        for relative in relatives:
            candidates.append(Path(root) / relative)
    for name in ("msedge", "chrome", "chromium", "google-chrome", "chrome.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def find_browser(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """The first usable headless-capable browser, or ``None``."""
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    for candidate in _browser_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def html_to_pdf(
    html: str,
    target: str | os.PathLike[str],
    *,
    browser: str | os.PathLike[str] | None = None,
    timeout: float = 120.0,
    virtual_time: int = 0,
) -> dict:
    """Print an HTML document to a PDF with a headless browser."""
    binary = find_browser(browser)
    if binary is None:
        raise ConvertError(
            "No Chromium-based browser found for PDF printing. "
            "Set JADELY_BROWSER to msedge.exe/chrome.exe, or use engine='stdlib'."
        )
    # The browser resolves --print-to-pdf against its own working directory, so
    # the target must be absolute before it is handed over.
    target_path = Path(target).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        try:
            target_path.unlink()
        except OSError as error:
            raise ConvertError(f"Could not replace {target_path.name}: {error}") from error

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="jadely-print-") as work:
        work_path = Path(work)
        page = work_path / "document.html"
        page.write_text(html, encoding="utf-8")
        profile = work_path / "profile"
        profile.mkdir()
        command = [
            str(binary),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={target_path}",
        ]
        if virtual_time:
            command.append(f"--virtual-time-budget={int(virtual_time)}")
        command.append(page.resolve().as_uri())
        try:
            finished = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise ConvertError(f"Printing timed out after {int(timeout)}s") from error
        except OSError as error:
            raise ConvertError(f"Could not run {binary.name}: {error}") from error

        # The browser can exit a moment before the file is flushed.
        deadline = time.monotonic() + 10.0
        while not target_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)

        if not target_path.is_file() or target_path.stat().st_size < 400:
            detail = (finished.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            tail = detail[-1] if detail else f"exit code {finished.returncode}"
            raise ConvertError(f"{binary.name} did not produce a PDF ({tail})")

        head = target_path.read_bytes()[:5]
        if head != b"%PDF-":
            raise ConvertError("The printer produced a file that is not a PDF")

    return {
        "engine": "edge",
        "browser": str(binary),
        "pdf": str(target_path),
        "bytes": target_path.stat().st_size,
        "ms": round((time.monotonic() - started) * 1000),
    }


# ------------------------------------------------------------------ markdown
def _title_of(blocks: list[dict], fallback: str) -> tuple[str, str]:
    """Document title, preferring frontmatter, then a leading ``#`` heading."""
    for block in blocks:
        if block["kind"] == "frontmatter":
            for key in ("title", "name"):
                if block["data"].get(key):
                    return block["data"][key], block["data"].get("author", "")
    for block in blocks:
        if block["kind"] == "heading" and block["level"] == 1:
            return block["text"], ""
    return fallback, ""


def markdown_to_pdf(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str] | None = None,
    *,
    engine: str = "auto",
    title: str = "",
    author: str = "",
    subtitle: str = "",
    chapter_breaks: bool = True,
    browser: str | os.PathLike[str] | None = None,
    base_dir: str | os.PathLike[str] | None = None,
    extra_css: str = "",
) -> dict:
    """Convert a markdown (or text) file to PDF."""
    source_path = Path(source)
    if not source_path.is_file():
        raise ConvertError(f"Not a file: {source_path}")
    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ConvertError(f"Cannot convert {source_path.suffix or 'that file'} to PDF")
    target_path = Path(target) if target else source_path.with_suffix(".pdf")

    text = source_path.read_text(encoding="utf-8", errors="replace")
    blocks = md.parse(text)
    document_title, document_author = _title_of(blocks, source_path.stem)
    heading_title = document_title or source_path.stem
    author = author or document_author

    # Do not print the title twice when the document opens with its own heading.
    leading_heading = any(
        block["kind"] == "heading" and block["level"] == 1 for block in blocks[:3]
    )
    body_title = "" if (leading_heading and not title) else (title or heading_title)

    resolved = engine
    if resolved == "auto":
        resolved = "edge" if find_browser(browser) else "stdlib"
    if resolved not in ("edge", "stdlib"):
        raise ConvertError(f"Unknown engine: {engine}")

    if resolved == "edge":
        html = md.to_document(
            text,
            title=body_title,
            subtitle=subtitle,
            author=author,
            wiki=False,
            extra_css=extra_css,
            base_href=_folder_uri(base_dir or source_path.parent),
        )
        result = html_to_pdf(html, target_path, browser=browser)
        result["source"] = str(source_path)
        return result

    write_pdf(
        target_path,
        blocks,
        title=body_title,
        author=author,
        subtitle=subtitle,
        subject=str(source_path.name),
        chapter_breaks=chapter_breaks,
    )
    return {
        "engine": "stdlib",
        "pdf": str(target_path),
        "bytes": target_path.stat().st_size,
        "source": str(source_path),
    }


def _folder_uri(folder: str | os.PathLike[str]) -> str:
    """A ``file://`` URI for the folder the markdown came from."""
    try:
        return Path(folder).resolve().as_uri() + "/"
    except (OSError, ValueError):
        return ""


# ----------------------------------------------------------------------- docx
def _paragraph_markdown(paragraph: ET.Element) -> tuple[str, bool]:
    """``(markdown, is_heading)`` for a ``w:p``."""
    pieces: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{W}t":
            pieces.append(node.text or "")
        elif node.tag == f"{W}br":
            pieces.append("\n")
        elif node.tag == f"{W}tab":
            pieces.append("\t")
    text = "".join(pieces).strip()
    if not text:
        return "", False

    # Emphasise runs that are marked bold or italic in the source.
    rendered: list[str] = []
    for run in paragraph.findall(f"{W}r"):
        run_text = "".join((node.text or "") for node in run.iter(f"{W}t"))
        if not run_text:
            continue
        properties = run.find(f"{W}rPr")
        bold = properties is not None and properties.find(f"{W}b") is not None
        italic = properties is not None and properties.find(f"{W}i") is not None
        body = run_text
        if bold and italic:
            body = f"***{body}***"
        elif bold:
            body = f"**{body}**"
        elif italic:
            body = f"*{body}*"
        rendered.append(body)
    joined = "".join(rendered).strip() or text

    style = paragraph.find(f"{W}pPr/{W}pStyle")
    style_name = (style.get(f"{W}val") if style is not None else "") or ""
    lowered = style_name.lower()

    if lowered.startswith("heading") and lowered[-1:].isdigit():
        level = max(1, min(6, int(lowered[-1])))
        return f"{'#' * level} {joined}", True
    if lowered in ("title", "subtitle"):
        return f"# {joined}", True
    numbering = paragraph.find(f"{W}pPr/{W}numPr")
    if numbering is not None:
        return f"- {joined}", False
    return joined, False


def _table_markdown(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{W}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{W}tc"):
            chunks: list[str] = []
            for paragraph in cell.findall(f"{W}p"):
                text, _ = _paragraph_markdown(paragraph)
                if text:
                    chunks.append(text)
            cells.append(" ".join(chunks).replace("|", "\\|") or " ")
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    for row in rows:
        while len(row) < width:
            row.append(" ")
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def docx_to_markdown(source: str | os.PathLike[str]) -> dict:
    """Reduce a ``.docx`` to markdown. Raises :class:`ConvertError` if unreadable."""
    path = Path(source)
    if not zipfile.is_zipfile(path):
        raise ConvertError(
            f"{path.name} is not a .docx (legacy .doc needs Word itself; save as .docx first)"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            core = None
            if "docProps/core.xml" in archive.namelist():
                core = ET.fromstring(archive.read("docProps/core.xml"))
    except (KeyError, ET.ParseError, OSError) as error:
        raise ConvertError(f"Could not read {path.name}: {error}") from error

    title = ""
    author = ""
    if core is not None:
        title = (core.findtext("{http://purl.org/dc/elements/1.1/}title") or "").strip()
        author = (core.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()

    body = document.find(f"{W}body")
    if body is None:
        raise ConvertError(f"{path.name} has no document body")

    lines: list[str] = []
    for child in body:
        if child.tag == f"{W}p":
            text, _ = _paragraph_markdown(child)
            lines.append(text)
        elif child.tag == f"{W}tbl":
            lines.append(_table_markdown(child))
    markdown = re.sub(r"\n{3,}", "\n\n", "\n\n".join(part for part in lines))
    return {"ok": True, "markdown": markdown.strip(), "title": title, "author": author}


def docx_to_pdf(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str] | None = None,
    *,
    engine: str = "auto",
    **options,
) -> dict:
    extracted = docx_to_markdown(source)
    path = Path(source)
    result = _markdown_text_to_pdf(
        extracted["markdown"],
        Path(target) if target else path.with_suffix(".pdf"),
        engine=engine,
        title=options.pop("title", "") or extracted["title"],
        author=options.pop("author", "") or extracted["author"],
        fallback_title=path.stem,
        **options,
    )
    result["source"] = str(path)
    return result


def _markdown_text_to_pdf(
    text: str,
    target_path: Path,
    *,
    engine: str = "auto",
    title: str = "",
    author: str = "",
    subtitle: str = "",
    chapter_breaks: bool = True,
    browser=None,
    fallback_title: str = "Document",
    extra_css: str = "",
) -> dict:
    blocks = md.parse(text)
    document_title, document_author = _title_of(blocks, fallback_title)
    heading_title = document_title or fallback_title
    author = author or document_author
    leading_heading = any(
        block["kind"] == "heading" and block["level"] == 1 for block in blocks[:3]
    )
    body_title = "" if (leading_heading and not title) else (title or heading_title)

    resolved = engine
    if resolved == "auto":
        resolved = "edge" if find_browser(browser) else "stdlib"
    if resolved not in ("edge", "stdlib"):
        raise ConvertError(f"Unknown engine: {engine}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if resolved == "edge":
        html = md.to_document(
            text,
            title=body_title,
            subtitle=subtitle,
            author=author,
            wiki=False,
            extra_css=extra_css,
            base_href=_folder_uri(target_path.parent),
        )
        return html_to_pdf(html, target_path, browser=browser)
    write_pdf(
        target_path,
        blocks,
        title=body_title,
        author=author,
        subtitle=subtitle,
        subject=target_path.stem,
        chapter_breaks=chapter_breaks,
    )
    return {"engine": "stdlib", "pdf": str(target_path), "bytes": target_path.stat().st_size}


# ---------------------------------------------------------------------- batch
def convert(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str] | None = None,
    *,
    engine: str = "auto",
    **options,
) -> dict:
    """Convert one file to PDF, whichever supported kind it is."""
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_to_pdf(path, target, engine=engine, **options)
    if suffix in SUPPORTED_EXTENSIONS:
        return markdown_to_pdf(path, target, engine=engine, **options)
    if suffix in LEGACY_EXTENSIONS:
        raise ConvertError(
            f"{path.name}: {suffix} files cannot be read without Word. Save it as .docx and try again."
        )
    raise ConvertError(f"{path.name}: {suffix or 'no extension'} is not convertible to PDF")


def collect_sources(root: Path, *, recursive: bool = True) -> list[Path]:
    if root.is_file():
        return [root]
    pattern = "**/*" if recursive else "*"
    found = [
        child
        for child in sorted(root.glob(pattern))
        if child.is_file() and child.suffix.lower() in MIGRATABLE_EXTENSIONS
    ]
    return found


def migrate(
    paths: list[str | os.PathLike[str]],
    *,
    out_dir: str | os.PathLike[str] | None = None,
    recursive: bool = True,
    engine: str = "auto",
    overwrite: bool = False,
    on_progress=None,
) -> dict:
    """Convert many files. Returns a report of what happened to each one."""
    converted: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for raw in paths:
        root = Path(raw)
        if not root.exists():
            failed.append({"source": str(root), "error": "Not found"})
            continue
        for source in collect_sources(root, recursive=recursive):
            if out_dir:
                target = Path(out_dir) / f"{source.stem}.pdf"
            else:
                target = source.with_suffix(".pdf")
            if target.exists() and not overwrite:
                skipped.append({"source": str(source), "target": str(target), "reason": "exists"})
                if on_progress:
                    on_progress(skipped[-1])
                continue
            try:
                result = convert(source, target, engine=engine)
                converted.append(result)
                if on_progress:
                    on_progress(result)
            except ConvertError as error:
                failed.append({"source": str(source), "error": str(error)})
                if on_progress:
                    on_progress(failed[-1])
            except Exception as error:  # noqa: BLE001 - report, never abort the batch
                failed.append({"source": str(source), "error": f"{type(error).__name__}: {error}"})
                if on_progress:
                    on_progress(failed[-1])

    return {
        "ok": not failed,
        "converted": converted,
        "skipped": skipped,
        "failed": failed,
        "counts": {
            "converted": len(converted),
            "skipped": len(skipped),
            "failed": len(failed),
        },
    }


# ------------------------------------------------------------------------ cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jadely-convert",
        description="Convert markdown, text and Word .docx files to PDF.",
    )
    parser.add_argument("paths", nargs="+", help="files or folders to convert")
    parser.add_argument("--out", help="folder for the PDFs (default: beside each source)")
    parser.add_argument("--engine", choices=("auto", "edge", "stdlib"), default="auto")
    parser.add_argument("--overwrite", action="store_true", help="replace existing PDFs")
    parser.add_argument("--no-recursive", action="store_true", help="do not descend into folders")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    browser = find_browser()
    report = migrate(
        args.paths,
        out_dir=args.out,
        recursive=not args.no_recursive,
        engine=args.engine,
        overwrite=args.overwrite,
    )

    if args.json:
        print(json.dumps({"engine": (browser.name if browser else "stdlib"), **report}, indent=2))
    elif not args.quiet:
        print(f"engine: {'edge (' + browser.name + ')' if browser else 'stdlib (no browser found)'}")
        for item in report["converted"]:
            print(f"  + {Path(item['pdf']).name}  ({item['bytes'] / 1024:.0f} KB, {item['engine']})")
        for item in report["skipped"]:
            print(f"  = {Path(item['target']).name}  (already there)")
        for item in report["failed"]:
            print(f"  ! {Path(item['source']).name}: {item['error']}", file=sys.stderr)
        counts = report["counts"]
        print(
            f"{counts['converted']} converted, {counts['skipped']} skipped, {counts['failed']} failed"
        )
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
