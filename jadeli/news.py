"""The JADELY news portal: programs you read *and* listen to.

A **program** is a folder in the library. Inside it, each **segment** is a markdown
script, an audio file, or both — matching by file name:

```
library/The Lantern's Edge Broadcast/
  program.json               optional metadata you write (title, author, description…)
  program.flags.json         flags JADELY writes (favorite / played / pinned / note / tags)
  cover.png                  optional cover art
  01 - The Reach.md          segment script
  01 - The Reach.mp3         the same segment's audio
  02 - The Marked.md
  02 - The Marked.wav
  Notes.pdf                  an attachment shown with the program
```

Order comes from the file names (``02`` before ``10``), the same natural ordering
the notes app uses for chapters. A program with no audio still works: the reader
can speak the script with the system voice.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import markdown as md
from .library import (
    Library,
    LibraryError,
    _natural_key,
    format_duration,
    read_flags,
    write_flags,
)

__all__ = ["News", "NewsError"]

SCRIPT_EXTS = {".md", ".markdown", ".txt", ".docx"}
LEGACY_TEXT_EXTS = {".doc", ".rtf", ".odt"}


class NewsError(Exception):
    """Anything the user should see as a clear message."""


# ----------------------------------------------------------------- programme ids
def program_id_for(folder: str) -> str:
    return hashlib.sha1(f"program::{folder}".encode("utf-8")).hexdigest()[:12]


def _stem_title(name: str) -> str:
    """``07 - Chapter Seven`` → ``Chapter Seven``."""
    stem = Path(name).stem
    cleaned = re.sub(r"^\s*\d{1,4}\s*[-–—.)]\s*", "", stem).strip()
    return cleaned or stem


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


class News:
    def __init__(self, library: Library) -> None:
        self.library = library

    # ------------------------------------------------------------------ grouping
    def _items_by_program(self) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for item in self.library.index():
            groups.setdefault(item["program"], []).append(item)
        for items in groups.values():
            items.sort(key=lambda item: _natural_key(item["name"]))
        return groups

    def program_folder(self, program_id: str) -> str:
        """Accept a program id or a folder name; return the folder key."""
        if not program_id:
            raise NewsError("No program given")
        groups = self._items_by_program()
        if program_id in groups:
            return program_id
        for key in groups:
            if program_id_for(key) == program_id:
                return key
        raise NewsError(f"Unknown program: {program_id}")

    # ------------------------------------------------------------------- shaping
    def _segments(
        self, folder: str, items: list[dict], order: list[str] | None = None
    ) -> tuple[list[dict], list[dict]]:
        """``(segments, attachments)`` for one program folder.

        A ``.docx`` counts as a script (its text can be extracted); a PDF or a
        legacy ``.doc``/``.rtf``/``.odt`` is an attachment you open alongside.
        """
        scripts: dict[str, dict] = {}
        audio: dict[str, dict] = {}
        attachments: list[dict] = []
        for item in items:
            if item["kind"] == "audio":
                audio[Path(item["name"]).stem.lower()] = item
            elif item["kind"] in ("note", "document"):
                scripts[Path(item["name"]).stem.lower()] = item
            elif item["kind"] == "pdf" or item["ext"] in ("doc", "rtf", "odt"):
                attachments.append(item)

        used_audio: set[str] = set()
        segments: list[dict] = []
        for key, script in sorted(scripts.items(), key=lambda pair: _natural_key(pair[1]["name"])):
            track = audio.get(key)
            if track:
                used_audio.add(key)
            segments.append(self._segment(folder, script, track))
        for key, track in sorted(audio.items(), key=lambda pair: _natural_key(pair[1]["name"])):
            if key in used_audio:
                continue
            segments.append(self._segment(folder, None, track))

        if order:
            # ``order`` in program.json lists file names, with or without the
            # extension, so index both forms and match either side of a segment.
            ranking: dict[str, int] = {}
            for position, entry in enumerate(order):
                full = Path(str(entry)).name.lower()
                ranking[full] = position
                ranking[Path(full).stem] = position

            def rank(segment: dict) -> int:
                for key in (segment.get("scriptName"), segment.get("audioName"), segment["name"]):
                    if key and str(key).lower() in ranking:
                        return ranking[str(key).lower()]
                return 10_000

            segments.sort(key=rank)

        for position, segment in enumerate(segments):
            segment["index"] = position
            segment["number"] = position + 1
        return segments, attachments

    def _segment(self, folder: str, script: dict | None, track: dict | None) -> dict:
        source = script or track
        assert source is not None
        name = Path(source["name"]).stem
        segment_id = hashlib.sha1(f"{folder}::{name}".encode("utf-8")).hexdigest()[:12]
        title = _stem_title(source["name"])
        words = (script or {}).get("words") or 0
        if script and not words:
            words = md.count_words(self.library.text(script["absolute"]))
        duration = (track or {}).get("duration")
        flags = dict((script or track)["flags"])
        progress = self.library.progress_for((track or script)["id"])
        return {
            "id": segment_id,
            "name": name,
            "title": title,
            "kind": "audio+script" if script and track else ("audio" if track else "script"),
            "scriptId": (script or {}).get("id"),
            "scriptName": (script or {}).get("name"),
            "scriptUrl": (script or {}).get("url"),
            "audioId": (track or {}).get("id"),
            "audioName": (track or {}).get("name"),
            "audioUrl": (track or {}).get("url"),
            "words": words,
            "duration": duration,
            "durationLabel": format_duration(duration),
            "flags": flags,
            "progress": progress,
            "positionLabel": format_duration(progress.get("position")),
            "percent": round(100 * (progress.get("position") or 0) / duration, 1)
            if duration and progress.get("position")
            else 0,
        }

    def _metadata(self, folder: str, items: list[dict], segments: list[dict]) -> dict:
        folder_path = Path(items[0]["absolute"]).parent if items else None
        stored = _read_json(folder_path / "program.json") if folder_path else {}
        first_script = next((segment for segment in segments if segment["scriptId"]), None)
        frontmatter: dict[str, str] = {}
        body = ""
        if first_script:
            text = self.library.text(self._path_of(first_script["scriptId"]))
            blocks = md.parse(text)
            for block in blocks:
                if block["kind"] == "frontmatter":
                    frontmatter = {key.lower(): value for key, value in block["data"].items()}
                    break
            body = md.plain_text(text)

        description = stored.get("description") or frontmatter.get("description") or ""
        if not description and body:
            description = re.sub(r"\s+", " ", body).strip()[:300]

        # Metadata, then the folder name, then the script's own frontmatter: a
        # folder called "Reference" should not be renamed by the first document
        # that happens to live inside it.
        title = stored.get("title") or folder or frontmatter.get("title") or "Loose files"
        author = stored.get("author") or frontmatter.get("author") or ""
        narrator = stored.get("narrator") or frontmatter.get("narrator") or ""

        seconds = sum(segment["duration"] or 0 for segment in segments)
        words = sum(segment["words"] or 0 for segment in segments)
        cover = next((item.get("cover") for item in items if item.get("cover")), None)
        flags = read_flags(folder_path / "program") if folder_path else {}   # program.flags.json

        listened = [
            segment
            for segment in segments
            if (segment["progress"].get("played") or segment["percent"] >= 90)
        ]
        # "Where you were" is simply the segment you touched last — including a
        # finished one, so the shelf can still name it instead of showing 67% and
        # nothing else.
        positions = [
            (segment["progress"].get("at", ""), segment)
            for segment in segments
            if segment["progress"]
        ]
        current = max(positions, key=lambda pair: pair[0])[1] if positions else None

        return {
            "id": program_id_for(folder),
            "folder": folder,
            "title": title,
            "author": author,
            "narrator": narrator,
            "description": description,
            "series": stored.get("series") or frontmatter.get("series") or "",
            "hidden": bool(stored.get("hidden")),
            "shelf": stored.get("shelf") or "",
            "kinds": sorted({item["kind"] for item in items}),
            "tags": sorted(
                {tag for item in items for tag in item["tags"]} | set(flags.get("tags") or [])
            ),
            "cover": cover,
            "flags": flags,
            "counts": {
                "segments": len(segments),
                "words": words,
                "attachments": len([item for item in items if item["kind"] == "pdf"]),
            },
            "seconds": round(seconds, 2),
            "durationLabel": format_duration(seconds),
            "progress": {
                "listened": len(listened),
                "total": len(segments),
                "percent": round(100 * len(listened) / len(segments)) if segments else 0,
                "segmentId": current["id"] if current else "",
                "segmentTitle": current["title"] if current else "",
                "position": (current["progress"].get("position") if current else 0) or 0,
            },
            "updated": max((item["mtimeEpoch"] for item in items), default=0),
            "updatedLabel": max((item["mtime"] for item in items), default=""),
        }

    def _path_of(self, item_id: str | None) -> str:
        if not item_id:
            return ""
        try:
            return str(self.library.resolve(item_id))
        except LibraryError:
            return ""

    # --------------------------------------------------------------------- api
    def feed(
        self, *, program: str = "", kind: str = "", query: str = "", include_hidden: bool = False
    ) -> dict:
        groups = self._items_by_program()
        programs: list[dict] = []
        hidden: list[dict] = []
        for folder, items in groups.items():
            segments, _attachments = self._segments(folder, items, self._order_for(folder, items))
            summary = self._metadata(folder, items, segments)
            summary["segments"] = segments
            if summary["hidden"]:
                hidden.append(summary)
                continue
            programs.append(summary)

        if program:
            programs = [entry for entry in programs if entry["folder"] == program]
        if kind:
            programs = [entry for entry in programs if kind in entry["kinds"]]
        if query:
            needle = query.lower()

            def matches(entry: dict) -> bool:
                blob = " ".join(
                    [entry["title"], entry["author"], entry["description"], " ".join(entry["tags"])]
                ).lower()
                return needle in blob

            programs = [entry for entry in programs if matches(entry)]

        programs.sort(key=lambda entry: (-entry["updated"], entry["title"].lower()))
        continue_list = sorted(
            [entry for entry in programs if entry["progress"]["position"] or entry["progress"]["listened"]],
            key=lambda entry: entry["progress"]["percent"],
        )
        return {
            "programs": programs,
            "hidden": hidden if include_hidden else [],
            "continue": continue_list[:6],
            "latest": programs[0] if programs else None,
            "stats": self.library.stats(),
        }

    def _order_for(self, folder: str, items: list[dict]) -> list[str]:
        folder_path = Path(items[0]["absolute"]).parent if items else None
        stored = _read_json(folder_path / "program.json") if folder_path else {}
        order = stored.get("order")
        if isinstance(order, list):
            return [str(entry) for entry in order]
        return []

    def program(self, program_id: str) -> dict:
        folder = self.program_folder(program_id)
        groups = self._items_by_program()
        items = groups[folder]
        segments, attachments = self._segments(folder, items, self._order_for(folder, items))
        detail = self._metadata(folder, items, segments)
        detail["segments"] = segments
        detail["attachments"] = [
            {
                "id": item["id"],
                "name": item["name"],
                "title": item["title"],
                "kind": item["kind"],
                "url": item["url"],
                "sizeLabel": item["sizeLabel"],
            }
            for item in sorted(attachments, key=lambda item: _natural_key(item["name"]))
        ]
        detail["files"] = [
            {"id": item["id"], "name": item["name"], "kind": item["kind"], "url": item["url"]}
            for item in items
        ]
        return {"program": detail}

    def segment(self, program_id: str, segment_id: str) -> dict:
        detail = self.program(program_id)["program"]
        for segment in detail["segments"]:
            if segment["id"] == segment_id or segment["name"] == segment_id:
                return {"segment": segment, "program": detail, "text": self.segment_text(segment)}
        raise NewsError(f"Unknown segment: {segment_id}")

    def segment_text(self, segment: dict) -> str:
        """The script as markdown (empty when the segment has no script)."""
        path = self._path_of(segment.get("scriptId"))
        if not path:
            return ""
        return self.library.text(path)

    def segment_speech(self, program_id: str, segment_id: str) -> dict:
        """Plain text plus a split into speakable paragraphs (read-aloud)."""
        found = self.segment(program_id, segment_id)
        text = found["text"]
        paragraphs = [part for part in md.plain_text(text).split("\n\n") if part.strip()]
        return {
            "segment": found["segment"],
            "title": found["segment"]["title"],
            "text": text,
            "speech": paragraphs,
            "words": len(" ".join(paragraphs).split()) if paragraphs else 0,
        }

    def search(self, query: str, *, limit: int = 60) -> dict:
        needle = (query or "").strip().lower()
        if not needle:
            return {"results": []}
        results: list[dict] = []
        for entry in self.feed()["programs"]:
            for segment in entry["segments"]:
                haystack = f"{segment['title']} {entry['title']}".lower()
                if needle in haystack:
                    results.append(
                        {
                            "program": entry["id"],
                            "programTitle": entry["title"],
                            "segment": segment["id"],
                            "title": segment["title"],
                            "kind": segment["kind"],
                            "score": 4 if needle in segment["title"].lower() else 2,
                        }
                    )
                if len(results) >= limit:
                    break
        return {"results": results[:limit]}

    # ------------------------------------------------------------------- flags
    def set_program_flags(self, program_id: str, patch: dict) -> dict:
        folder = self.program_folder(program_id)
        groups = self._items_by_program()
        path = Path(groups[folder][0]["absolute"]).parent
        if not self.library._inside_a_root(path):  # noqa: SLF001 - same package
            raise NewsError("That program is outside the library")
        flags = read_flags(path / "program")
        for field in ("favorite", "played", "pinned"):
            if field in patch and patch[field] is not None:
                flags[field] = bool(patch[field])
        if "note" in patch and patch["note"] is not None:
            flags["note"] = str(patch["note"])
        if "tags" in patch and patch["tags"] is not None:
            value = patch["tags"]
            flags["tags"] = (
                [str(tag).strip() for tag in value.split(",") if tag.strip()]
                if isinstance(value, str)
                else [str(tag) for tag in value]
            )
        saved = write_flags(path / "program", flags)
        self.library.index(refresh=True)
        return {"program": program_id_for(folder), "flags": saved}

    def toggle_program_flag(self, program_id: str, flag: str) -> dict:
        folder = self.program_folder(program_id)
        groups = self._items_by_program()
        path = Path(groups[folder][0]["absolute"]).parent
        flags = read_flags(path / "program")
        if flag not in ("favorite", "played", "pinned"):
            raise NewsError(f"Cannot toggle {flag} on a program")
        flags[flag] = not bool(flags[flag])
        saved = write_flags(path / "program", flags)
        self.library.index(refresh=True)
        return {"program": program_id_for(folder), "flag": flag, "value": saved[flag], "flags": saved}

    def set_segment_flags(self, segment_id: str, patch: dict) -> dict:
        """Flags on a segment are flags on its script (or its audio)."""
        for entry in self.feed()["programs"]:
            for segment in entry["segments"]:
                if segment["id"] == segment_id:
                    target = segment["scriptId"] or segment["audioId"]
                    return self.library.set_flags(target, patch)
        raise NewsError(f"Unknown segment: {segment_id}")

    # ----------------------------------------------------------------- progress
    def save_progress(
        self,
        segment_id: str,
        *,
        position: float | None = None,
        duration: float | None = None,
        played: bool | None = None,
    ) -> dict:
        for entry in self.feed()["programs"]:
            for segment in entry["segments"]:
                if segment["id"] == segment_id:
                    target = segment["audioId"] or segment["scriptId"]
                    if target is None:
                        raise NewsError("That segment has nothing to track")
                    saved = self.library.set_progress(
                        target,
                        position=position,
                        duration=duration,
                        segment=segment["id"],
                        played=played,
                    )
                    return {"segment": segment["id"], "progress": saved}
        raise NewsError(f"Unknown segment: {segment_id}")

    def mark_played(self, segment_id: str, played: bool = True) -> dict:
        """Reach into the sidecar so the flag file shows it too."""
        for entry in self.feed()["programs"]:
            for segment in entry["segments"]:
                if segment["id"] == segment_id:
                    target = segment["scriptId"] or segment["audioId"]
                    self.library.set_progress(target, played=played)
                    return self.library.set_flags(target, {"played": played})
        raise NewsError(f"Unknown segment: {segment_id}")

    # -------------------------------------------------------------------- misc
    def attachments_for(self, program_id: str) -> list[dict]:
        return self.program(program_id)["program"]["attachments"]
