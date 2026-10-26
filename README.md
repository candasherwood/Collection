# JADELY

A local-first launcher, store, news portal and notebook that share one library
folder. Nothing is uploaded, no account is needed, and **the files are the
database**: markdown, PDF, audio and flag files on disk are read where they
already are.

JADELY grew out of three things:

- **[OpenAudible](https://github.com/openaudible/openaudible)** — a library you
  browse, flag, search and *listen to*, with per-item progress.
- **[Typora](https://github.com/typora)** — markdown as a first-class document,
  read as a rendered page rather than source.
- **the old Jadeli** at `D:\Personal\jadeli` — the markdown vault and manuscript
  side, which lives on here as the **Notes** app (that folder is untouched; the
  launcher can still open it as an external app if you want it).

```
D:\Personal\Jadely Store\
├─ app.py                    entry point (window / browser / server / status)
├─ jadely.bat                double-click launcher (no console window)
├─ jadeli\                   Python backend — stdlib only, one dependency
│  ├─ api.py                 the API surface, one method per action
│  ├─ config.py              portable config.json + defaults
│  ├─ server.py              loopback HTTP server (pages, /api, /media)
│  ├─ vault.py               notes: files, index, wiki links, tags, search, graph
│  ├─ books.py               manuscripts: chapters, ordering, word targets
│  ├─ library.py             the store: index, flag files, audio info, import/export
│  ├─ news.py                programs and segments (script + audio)
│  ├─ launcher.py            app registry: start, stop, what is running
│  ├─ convert.py             md / txt / docx → PDF (headless Edge, or stdlib)
│  ├─ pdfwriter.py           the dependency-free PDF writer
│  └─ markdown.py            markdown → HTML for the built-in renderer
├─ web\                      the interface (plain HTML/CSS/JS, no build step)
│  ├─ index.html  style.css  app.js  graph.js   the notes app
│  ├─ launcher.html  launcher.js                the hub
│  ├─ store.html     store.js                   the store
│  ├─ news.html      news.js                    the portal
│  ├─ jadely.css  jadely.js  markdown.js        shared style, helpers, renderer
├─ library\                  the library: programs, documents, audio, flags
│  ├─ The Reach Report\      program with audio, cover art and a PDF
│  ├─ Emberwatch Notebook\   program that is script-only (read-aloud)
│  └─ Reference\             "JADELY Content Guide", "Flag Files Explained"
├─ vault\                    the notes vault (markdown; the old demo novel lives here)
├─ tools\seed_library.py     writes the demo library (audio, cover, PDF, flags)
├─ tests\                    6 suites + window smoke test + suite runner
└─ config.json               created on first run (vault, library roots, theme)
```

## Getting started

Requires **Python 3.10+** and the **WebView2 runtime** (already present on
Windows 10/11). One dependency, for the window:

```bat
cd /d "D:\Personal\Jadely Store"
python -m pip install -r requirements.txt
```

Then double-click **jadely.bat** — it opens the JADELY hub window with no console
window (it prefers `pythonw.exe` and falls back to `python.exe`, telling you if
Python was not found). Without the window, everything also runs in a browser:

```bat
python app.py                       :: the launcher hub (default)
python app.py --app store           :: just the store, in its own window
python app.py --app news            :: just the news portal
python app.py --app notes           :: just the notes vault
python app.py --browser             :: in your default browser instead of a window
python app.py --server-only         :: the API and pages only, prints the URL
python app.py --port 7654           :: pin the port (default: a random free one)
python app.py --url http://127.0.0.1:7654 --app store
                                    :: a window onto a hub already running
python app.py --status              :: what is running, as JSON
python app.py --stop store          :: stop an app the launcher started
python app.py --devtools            :: window with the browser DevTools open
```

`--vault` opens a different notes folder; the library roots are set in the Store
(see *The Store* below). `config.json` sits next to `app.py`, so the app stays
portable and nothing is written to the registry or your home folder.

## The four apps

| App | Page | What it does |
| --- | --- | --- |
| **Launcher** | `/launcher` | The hub: cards for every app, what is running, start/stop, open in the browser, the library at a glance. |
| **Store** | `/store` | Everything in the library: shelves, search, flags, audio playback, PDF and markdown reading, import, export, the ⤓ migrate button. |
| **News** | `/news` | Programs of segments, Audible-style: cover art, segment list, per-segment progress, read the script or listen, read-aloud with the system voice. |
| **Notes** | `/` | The markdown vault and manuscript side (from the old Jadeli): tree, editor, wiki links, backlinks, tags, search, graph, books, export. |

The launcher spawns each app as its own detached process and remembers its
process id in `state/apps.json`, so **closing the hub never closes your work**.
Stopping checks that the process id still belongs to a Python process before
touching it, so a recycled id can never kill something unrelated. The older
standalone Jadeli at `D:\Personal\jadeli` shows up as an external app when that
folder exists.

## The library: programs, flag files and audio

A **program** is a folder. A **segment** is a markdown script, an audio file, or
both — matched by file name, in natural order (`02` before `10`):

```
library/The Reach Report/
  program.json                     metadata you write (title, author, description…)
  program.flags.json               flags JADELY writes (favorite / played / pinned / note / tags)
  cover.png                        optional cover art (not an item of its own)
  01 - The Lantern Line.md         segment script
  01 - The Lantern Line.wav        the same segment's audio
  02 - What the Marked Carry.mp3
  03 - Lines of Flair.md
  Reference - Bands of the Reach.pdf   an attachment, shown with the program
```

**Flag files** are hand-editable sidecars next to the content —
`<name>.<ext>.flags.json` — holding `favorite`, `played`, `pinned`,
`downloaded`, free `tags`, and a `note`. Edit them in any editor; the store picks
the change up on the next look. What is *not* content goes in
`<root>/.jadely/state.json`: playback positions and play counts, which are
per-machine and cheap to lose. Both formats are written out in
`library/Reference/` — that pair of documents is part of the demo library, so
the conventions are readable in the app itself.

Audio durations are read with the standard library only (`wave` for WAV, a frame
header scan for MP3). `/media` streams any library file with HTTP Range support,
so audio seeks. Nothing is downloaded and nothing is uploaded.

## Migrating to PDF

`jadeli/convert.py` turns markdown, plain text and Word documents into PDF, using
one of two engines:

- **`edge`** — a headless Microsoft Edge or Chrome (`--print-to-pdf`) prints the
  same stylesheet the app renders, so the PDF matches what you read.
- **`stdlib`** — `jadeli/pdfwriter.py` lays the document out on A4 with the
  base-14 fonts. No browser, no dependency; used automatically when no browser is
  installed, or on request. This is the safety net, not the showcase.

Word (`.docx`) is first reduced to markdown from `word/document.xml` inside the
zip and then follows the *same* path, so a manuscript renders identically
whatever it came from. Legacy `.doc`, `.rtf` and `.odt` cannot be read without
Word itself, and are reported as unsupported rather than guessed at.

In the app: select items in the Store and press **Migrate**, or use the CLI:

```bat
python -m jadeli.convert "library" --engine auto
python -m jadeli.convert "chapter.md" "report.docx" --out "library/Exports" --overwrite
python -m jadeli.convert "library" --json          :: machine-readable report
```

`--engine edge|stdlib|auto`, `--out <folder>`, `--overwrite`, `--no-recursive`,
`--quiet`. `JADELY_BROWSER` overrides which browser binary is used. PDFs land
beside their source unless `--out` says otherwise.

## The demo library

`library/` ships with three programs' worth of content so every screen has
something to show: two programs (one with WAV **and** MP3 audio, cover art and a
PDF; one script-only for read-aloud), loose reference documents, and flag files.
It is all generated locally — the audio is synthesised, the cover is drawn pixel
by pixel, the PDF comes out of JADELY's own converter:

```bat
python tools/seed_library.py            :: fill in what is missing
python tools/seed_library.py --force    :: rewrite everything
```

Delete `library/` and re-run it any time; nothing there is precious.

## How it works

`app.py` starts a small `http.server` bound to `127.0.0.1` on a random free port
and points a pywebview (WebView2) window at one of its pages. The UI is plain
HTML/JS and talks to `/api/<method>` with JSON — `jadeli/api.py` dispatches each
method to `vault.py`, `books.py`, `library.py`, `news.py` or `launcher.py`. GET on
an API route is answered with *Use POST for the API*, and `/media` refuses any
path outside the library roots, so a page cannot wander off the disk.

Because the server is loopback-only and the folders are ones you choose, JADELY
never touches the network on its own. External links open in your default browser
through the backend, not inside the app.

## Tests

```bat
python tests\run_all.py                :: every suite, each in its own process
python tests\run_all.py convert        :: only suites whose name matches
```

| Suite | Covers |
| --- | --- |
| `test_backend.py` | notes vault: file ops, path-traversal refusal, trash, links/tags, backlinks, search ranking, graph, books, export, the API contract |
| `test_convert.py` | markdown → HTML, the stdlib PDF writer, `.docx` import, batch migration reports |
| `test_library.py` | the store: index, flag files, audio info, search, import/export, roots |
| `test_news.py` | programs, segment pairing and order, progress, the feed |
| `test_launcher.py` | app registry, start/stop, the foreign-pid guard |
| `test_server_api.py` | the HTTP contract the windows and the browser use, over real requests |

`python tests\smoke_window.py store` (or `launcher`, `news`, `notes`) opens a real
pywebview window, asks the page from inside it how many items rendered, prints
what it found and closes again — useful after changing the UI.

## Deliberately not here (yet)

- No accounts, sync, cloud or telemetry — by design.
- No reader for legacy `.doc`/`.rtf`/`.odt`; convert them with Word first.
- No EPUB/audiobook container reading (files, not archives).
- The library is not watched while the app is open: reopening a screen (or
  restarting) picks up outside edits.
- No plugin system, and no upload UI for attachments — reference them by path.

These are next steps, not accidents.
