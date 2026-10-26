"""Shared fixtures for the JADELY tests.

Builds a throwaway library on disk with everything the store and the portal have
to cope with: two programs (one with audio, one script-only), a hidden reference
shelf, loose files at the root, real WAV and MP3 audio, generated cover art, a
genuine PDF produced by JADELY's own converter, and flag files in both places.

The audio and image generators come from the same tool that seeds the demo
library, so the tests exercise the same bytes users get.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from jadeli import convert  # noqa: E402
from jadeli.library import flags_path, write_flags  # noqa: E402
from seed_library import write_cover, write_silent_mp3, write_wav  # noqa: E402

BROADCAST_ONE = """\
---
title: The Lantern Line
author: The Emberwatch
---

# The Lantern Line

The line held tonight. Three crews walked it and nobody was lost.

## Count

- stations relit: 41
- keepers who signed: 17

> [!note] For the crews
> Carry your own light.

See also [[The Marked]] and #broadcast.
"""

BROADCAST_TWO = """\
---
title: What the Marked Carry
author: The Emberwatch
---

# What the Marked Carry

Every marked person carries a coat and a story about the night they were marked.
"""

NOTEBOOK_ONE = """\
---
title: The Assessor's Ledger
---

# The Assessor's Ledger

The ledger is bound in grey cloth. The office does not decide who is marked; the
office decides who is *counted*.
"""

REFERENCE_ONE = """\
---
title: Content Guide
---

# Content Guide

A program is a folder. A segment pairs a script with audio of the same name.
"""

LOOSE_NOTE = """\
# A loose note

Sitting at the root of the library, not inside any program folder.
"""

PROGRAM_META = {
    "title": "The Reach Report",
    "author": "The Emberwatch",
    "narrator": "Wren of the Emberwatch",
    "series": "The Reach Report",
    "description": "A nightly bulletin from the Reach.",
}


def make_library(root: Path, *, with_pdf: bool = True) -> Path:
    """Create the fixture library under ``root`` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    report = root / "The Reach Report"
    notebook = root / "Emberwatch Notebook"
    reference = root / "Reference"
    for folder in (report, notebook, reference):
        folder.mkdir(parents=True, exist_ok=True)

    (report / "program.json").write_text(json.dumps(PROGRAM_META, indent=2), encoding="utf-8")
    write_flags(report / "program", {"favorite": True, "tags": ["broadcast"]})

    (report / "01 - The Lantern Line.md").write_text(BROADCAST_ONE, encoding="utf-8")
    (report / "02 - What the Marked Carry.md").write_text(BROADCAST_TWO, encoding="utf-8")
    write_wav(report / "01 - The Lantern Line.wav", seconds=1.0, rate=8000)
    write_silent_mp3(report / "02 - What the Marked Carry.mp3", frames=10)
    write_cover(report / "cover.png", width=48, height=48)
    # A segment with a script but no audio, and one with audio but no script.
    (report / "03 - Lines of Flair.md").write_text(BROADCAST_TWO, encoding="utf-8")
    write_silent_mp3(report / "99 - Ident.mp3", frames=5)

    if with_pdf:
        source = report / "Reference - Bands.md"
        source.write_text("# Bands\n\n| Band | Meaning |\n| --- | --- |\n| Low | short |\n", encoding="utf-8")
        convert.convert(source, report / "Reference - Bands.pdf", engine="stdlib")
        source.unlink()

    (notebook / "program.json").write_text(
        json.dumps({"title": "Emberwatch Notebook", "series": "Notebook"}, indent=2), encoding="utf-8"
    )
    (notebook / "01 - The Assessor's Ledger.md").write_text(NOTEBOOK_ONE, encoding="utf-8")
    write_flags(notebook / "01 - The Assessor's Ledger.md", {"played": True})

    (reference / "program.json").write_text(
        json.dumps({"title": "Reference", "hidden": True, "shelf": "reference"}, indent=2),
        encoding="utf-8",
    )
    (reference / "Content Guide.md").write_text(REFERENCE_ONE, encoding="utf-8")

    (root / "A loose note.md").write_text(LOOSE_NOTE, encoding="utf-8")
    return root


def write_flags_file(path: Path, flags: dict) -> Path:
    """Write a flag file exactly where JADELY would."""
    write_flags(path, flags)
    return flags_path(path)
