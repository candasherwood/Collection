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
