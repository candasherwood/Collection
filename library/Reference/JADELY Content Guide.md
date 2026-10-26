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
