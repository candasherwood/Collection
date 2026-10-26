#!/usr/bin/env python
"""Seed the JADELY demo library.

Writes ``library/`` with two programs (one with audio, one script-only), loose
reference documents, a PDF produced by JADELY's own converter, real WAV and MP3
audio, generated cover art and a couple of flag files.

Nothing here is downloaded: the audio is synthesised (a soft chime for WAV, a
valid silent MPEG frame run for MP3), the cover is drawn pixel by pixel, and the
PDF comes from ``jadeli.convert``. Re-running is safe — existing files are kept
unless you pass ``--force``.

    python tools/seed_library.py            # fill in what is missing
    python tools/seed_library.py --force    # rewrite everything
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
import zlib
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from jadeli import convert  # noqa: E402
from jadeli.library import flags_path, write_flags  # noqa: E402

LIBRARY = APP_DIR / "library"

# --------------------------------------------------------------------- audio
def write_wav(path: Path, *, seconds: float = 7.0, rate: int = 22050) -> None:
    """A gentle two-note chime with fades — a stand-in for a narration track."""
    frames = bytearray()
    total = int(rate * seconds)
    notes = [(392.0, 0.0, 1.6), (523.25, 1.5, 2.0), (392.0, 3.4, 3.4)]
    for index in range(total):
        moment = index / rate
        sample = 0.0
        for frequency, start, duration in notes:
            if start <= moment < start + duration:
                local = (moment - start) / duration
                envelope = math.sin(math.pi * local) ** 1.5
                sample += 0.34 * envelope * math.sin(2 * math.pi * frequency * moment)
                sample += 0.10 * envelope * math.sin(2 * math.pi * frequency * 2 * moment)
        sample *= 0.9
        frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32000))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def write_silent_mp3(path: Path, *, frames: int = 150) -> None:
    """A valid MPEG-1 Layer III stream of silence (no encoder needed).

    Frame header 0xFFFB90C4: MPEG-1, Layer III, 128 kbps, 44.1 kHz, mono, no CRC.
    Frame length is floor(144 * 128000 / 44100) = 417 bytes, so every frame is a
    4-byte header followed by 413 bytes of zeroed main data, which decodes to
    silence. 150 frames is about 3.9 seconds — placeholder audio so the player has
    something real to open.
    """
    header = bytes((0xFF, 0xFB, 0x90, 0xC4))
    frame = header + bytes(413)
    path.write_bytes(frame * frames)


# --------------------------------------------------------------------- images
def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def write_cover(path: Path, *, width: int = 480, height: int = 480, accent=(224, 164, 88)) -> None:
    """Draw a small gradient cover with a lantern glow, as a real PNG."""
    rows = bytearray()
    cx, cy = width * 0.5, height * 0.42
    for y in range(height):
        rows.append(0)  # PNG filter type 0
        for x in range(width):
            depth = y / height
            base = (
                int(18 + 26 * depth),
                int(21 + 30 * depth),
                int(30 + 40 * depth),
            )
            distance = math.hypot(x - cx, y - cy) / (width * 0.42)
            glow = max(0.0, 1.0 - distance) ** 2.4
            horizon = 1.0 if abs(y - height * 0.72) < 1.2 else 0.0
            pixel = (
                base[0] + accent[0] * glow * 0.85 + horizon * 40,
                base[1] + accent[1] * glow * 0.85 + horizon * 46,
                base[2] + accent[2] * glow * 0.85 + horizon * 60,
            )
            rows += bytes(min(255, max(0, int(value))) for value in pixel)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


# --------------------------------------------------------------------- content
REACH_REPORT_ONE = """\
---
title: The Lantern Line
author: The Reach Report
narrator: Wren of the Emberwatch
series: The Reach Report
---

# The Lantern Line

Good evening from the Reach. This is the report for the night the fog came in
low, and the line held anyway.

## What happened

Three crews walked the lantern line west of the Emberwatch and re-lit every
station before midnight. That has not happened in eleven years. The crews say the
wind turned *early* — the kind of early that makes an old keeper smile and say
nothing.

> [!tip] If you are walking the line
> Carry your own light. The line is for finding your way back, not for proving
> you were brave.

The count, as filed with the Assessor:

- stations relit: 41
- stations abandoned: 0
- keepers who signed the ledger: 17
- keepers who signed it twice: 1 (a joke)

## What it means

A line that holds is not the same as a line that is safe. The Reach has always
preferred the holding. Tonight we report it plainly: the lantern line is lit,
the fog is sitting low over the water, and the Bands are quiet.
"""

REACH_REPORT_TWO = """\
---
title: What the Marked Carry
author: The Reach Report
narrator: Wren of the Emberwatch
series: The Reach Report
---

# What the Marked Carry

Every marked person carries two things: a coat that has been mended more times
than it has been washed, and a story about the night they were marked.

## The ledger entry

The Assessor's office opened its ledger this week and let us read three pages.
The handwriting changes halfway down the second page. Nobody at the office would
say why.

> [!warning] Careful with the third page
> The third page lists names that the fourth page says were never marked. Both
> pages are signed.

## Heard on the Reach

1. *"The light doesn't choose. It just arrives."* — a keeper at station nine
2. *"I was marked on a Tuesday. I remember because the bread was late."*
3. *"You don't carry the mark. The mark carries you, and it is not careful."*

We asked the Assessor whether the office would publish the full ledger. The
answer was a long pause and then the word *eventually*, which in Reach terms
means *when it suits the light*.
"""

REACH_REPORT_THREE = """\
---
title: Lines of Flair
author: The Reach Report
narrator: Wren of the Emberwatch
series: The Reach Report
---

# Lines of Flair

Tonight's segment is read, not played — there is no recording of this one yet.
The script is here so you can read it yourself, or press **Read aloud** and let
the window speak it.

## A short piece on flair

Flair is what a keeper adds when nobody is watching: a spiral of copper wire
around a wick, a folded paper bird on a sill, a line of chalk along a doorframe
that means *I was here and I meant it*.

The Emberwatch does not record flair. That is the point of it. What the watch
records is whether the light was lit.

> [!note] About this segment
> This is the only report this week with no audio track. It is here to show the
> reader working on its own.

## Closing

The line is lit. The fog is low. The chalk is still on the doorframe.
"""

REACH_ATTACHMENT = """\
---
title: Bands of the Reach
author: The Emberwatch
---

# Bands of the Reach

A reference sheet for the crews who walk the line, converted from markdown to
PDF by JADELY itself.

## The bands

| Band | Colour | Meaning |
| --- | --- | --- |
| Low band | pale amber | the line is short and well kept |
| Middle band | ember | the line crosses water |
| High band | smoke | the line is abandoned but walkable |
| Dead band | none | do not walk it |

## Standing orders

1. A band is a promise about the ground, not about the weather.
2. Two keepers may disagree about a band. Both may be right.
3. If the band is missing, treat the ground as dead.
"""

NOTEBOOK_ONE = """\
---
title: The Assessor's Ledger
author: Emberwatch Notebook
series: Notebook
---

# The Assessor's Ledger

The ledger is bound in grey cloth and sits on a desk that has been repaired
underneath, out of sight, four times.

## Entry, undated

> The office does not decide who is marked. The office decides who is *counted*.

A keeper once asked whether the difference mattered. The Assessor wrote the
question down, which is the office's way of saying yes.
"""

NOTEBOOK_TWO = """\
---
title: The Ladder Below
author: Emberwatch Notebook
series: Notebook
---

# The Ladder Below

Below the Emberwatch there is a ladder that goes down further than the building
goes up. This is recorded here because nobody else will record it.

- The ladder has 24 rungs above the water line and an unknown number below.
- A lamp left on the tenth rung was found lit three days later with no oil spent.
- The eleventh rung is warm, always, even in winter.

## A note on method

We measured the ladder twice. The second measurement was longer than the first.
"""

NOTEBOOK_THREE = """\
---
title: The Coat and the Fire
author: Emberwatch Notebook
series: Notebook
---

# The Coat and the Fire

A marked coat, hung too close to a fire, does not burn. This is not a miracle
and the Emberwatch does not present it as one.

## What is observed

1. The wool chars at the hem, as wool does.
2. The mark on the left shoulder stays white.
3. The smoke smells of rain, which is not a smell a fire produces.

The office keeps one such coat in a cupboard. It is not labelled. It does not
need to be.
"""

CONTENT_GUIDE = """\
---
title: JADELY Content Guide
---

# JADELY Content Guide

Everything JADELY shows you is a file in your library. This document describes
the folder shape the Store and the News portal expect.

## A program folder

```
library/The Reach Report/
  program.json            metadata you write by hand (optional)
  program.flags.json      flags JADELY writes
  cover.png               cover art (optional)
  01 - The Lantern Line.md   a segment script
  01 - The Lantern Line.wav  the same segment's audio
  02 - What the Marked Carry.md
  02 - What the Marked Carry.mp3
  Reference - Bands.pdf      an attachment
```

- A segment's **script** and **audio** are matched by file name: `01 - Title.md`
  beside `01 - Title.mp3` is one segment with both.
- A segment with no audio still reads.
- Numbers at the start of the file name set the order (`02` before `10`).
- `.pdf` files and legacy `.doc`/`.rtf`/`.odt` files are attachments.
- `.md`, `.markdown`, `.txt` and `.docx` are readable scripts.

## Kinds

| Extension | Kind | What JADELY does |
| --- | --- | --- |
| `.md` `.markdown` `.txt` | note | renders, searches, speaks |
| `.docx` | document | converts the text out of it |
| `.pdf` | pdf | shows it in the viewer |
| `.mp3` `.wav` `.m4a` `.ogg` `.flac` | audio | plays it, reads duration |
| `.png` `.jpg` `.webp` `.gif` `.svg` | image | cover art |
"""

FLAG_GUIDE = """\
---
title: Flag Files Explained
---

# Flag Files Explained

JADELY marks what you have listened to, loved or pinned by writing a small JSON
file next to the content. It is called a **flag file**, and it is yours.

## Where it goes

For a file:

```
library/The Reach Report/01 - The Lantern Line.md.flags.json
```

For a whole program:

```
library/The Reach Report/program.flags.json
```

## What is inside

```json
{
  "favorite": true,
  "played": false,
  "pinned": false,
  "downloaded": false,
  "tags": ["broadcast", "reach"],
  "note": "played this on the drive north",
  "updated": "2026-10-26T19:04:00"
}
```

- **favorite** — the star in the Store and the News feed.
- **played** — set when you finish a segment.
- **pinned** — keeps an item at the top of a shelf.
- **downloaded** — you already have it offline (meaningful when a program's audio
  came from somewhere else).
- **tags** — extra tags, added to any `#tags` found in the markdown.
- **note** — free text, shown in the item panel.

Delete the file and the item simply loses its flags: nothing else breaks. Playback
positions live in `library/.jadely/state.json` instead, because they are machine
state rather than content.
"""

PROGRAMS = [
    {
        "folder": "The Reach Report",
        "meta": {
            "title": "The Reach Report",
            "author": "The Emberwatch",
            "narrator": "Wren of the Emberwatch",
            "series": "The Reach Report",
            "description": (
                "A nightly bulletin from the Reach: the lantern line, the marked, "
                "and whatever the Assessor's office will admit to."
            ),
        },
        "cover": True,
        "flags": {"favorite": True, "pinned": True, "tags": ["broadcast", "reach"]},
        "segments": [
            ("01 - The Lantern Line.md", REACH_REPORT_ONE, "01 - The Lantern Line.wav"),
            ("02 - What the Marked Carry.md", REACH_REPORT_TWO, "02 - What the Marked Carry.mp3"),
            ("03 - Lines of Flair.md", REACH_REPORT_THREE, None),
        ],
        "attachment": ("Reference - Bands of the Reach.md", REACH_ATTACHMENT),
        "played": "01 - The Lantern Line.md",
    },
    {
        "folder": "Emberwatch Notebook",
        "meta": {
            "title": "Emberwatch Notebook",
            "author": "The Emberwatch",
            "series": "Notebook",
            "description": "Notes from below the watch: the ledger, the ladder, the coat that will not burn.",
        },
        "cover": False,
        "flags": {"favorite": False, "tags": ["notebook"]},
        "segments": [
            ("01 - The Assessor's Ledger.md", NOTEBOOK_ONE, None),
            ("02 - The Ladder Below.md", NOTEBOOK_TWO, None),
            ("03 - The Coat and the Fire.md", NOTEBOOK_THREE, None),
        ],
        "attachment": None,
        "played": None,
    },
]

REFERENCE = [("JADELY Content Guide.md", CONTENT_GUIDE), ("Flag Files Explained.md", FLAG_GUIDE)]


# ----------------------------------------------------------------------- write
def _write(path: Path, text: str, *, force: bool, created: list, kept: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        kept.append(path)
        return
    path.write_text(text, encoding="utf-8")
    created.append(path)


def seed(*, force: bool = False) -> dict:
    created: list[Path] = []
    kept: list[Path] = []

    import json

    for program in PROGRAMS:
        folder = LIBRARY / program["folder"]
        folder.mkdir(parents=True, exist_ok=True)

        _write(
            folder / "program.json",
            json.dumps(program["meta"], indent=2) + "\n",
            force=force,
            created=created,
            kept=kept,
        )
        if program["flags"]:
            flags_file = folder / "program.flags.json"
            if force or not flags_file.exists():
                write_flags(folder / "program", program["flags"])
                created.append(flags_file)
            else:
                kept.append(flags_file)

        for name, body, audio in program["segments"]:
            _write(folder / name, body, force=force, created=created, kept=kept)
            if not audio:
                continue
            track = folder / audio
            if track.exists() and not force:
                kept.append(track)
                continue
            if track.suffix == ".wav":
                write_wav(track)
            else:
                write_silent_mp3(track)
            created.append(track)

        if program["cover"]:
            cover = folder / "cover.png"
            if force or not cover.exists():
                accent = (224, 164, 88) if program["folder"] == "The Reach Report" else (150, 170, 210)
                write_cover(cover, accent=accent)
                created.append(cover)
            else:
                kept.append(cover)

        if program["played"]:
            item = folder / program["played"]
            sidecar = flags_path(item)
            if force or not sidecar.exists():
                write_flags(item, {"played": True})
                created.append(sidecar)
            else:
                kept.append(sidecar)

        if program["attachment"]:
            name, body = program["attachment"]
            source = folder / name
            _write(source, body, force=force, created=[], kept=[])
            pdf = source.with_suffix(".pdf")
            if force or not pdf.exists():
                # JADELY converts its own reference sheet to PDF — no pandoc here.
                convert.convert(source, pdf, engine="auto")
                created.append(pdf)
            else:
                kept.append(pdf)
            source.unlink(missing_ok=True)  # the PDF is the artefact; the draft goes

    # The reference shelf is documentation rather than a program, so it opts out
    # of the News feed with "hidden": true in its program.json.
    import json

    _write(
        LIBRARY / "Reference" / "program.json",
        json.dumps({"title": "Reference", "hidden": True, "shelf": "reference"}, indent=2) + "\n",
        force=force,
        created=created,
        kept=kept,
    )
    for name, body in REFERENCE:
        _write(LIBRARY / "Reference" / name, body, force=force, created=created, kept=kept)

    return {
        "created": [str(path.relative_to(APP_DIR)) for path in created],
        "kept": [str(path.relative_to(APP_DIR)) for path in kept],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the JADELY demo library.")
    parser.add_argument("--force", action="store_true", help="rewrite files that already exist")
    args = parser.parse_args(argv)

    report = seed(force=args.force)
    for name in report["created"]:
        print(f"  + {name}")
    for name in report["kept"]:
        print(f"  = {name} (kept)")
    print(f"{len(report['created'])} written, {len(report['kept'])} kept in {LIBRARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
