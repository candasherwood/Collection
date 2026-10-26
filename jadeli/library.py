"""The JADELY library: content on disk, indexed, flagged and searchable.

Same contract as the notes vault — the files *are* the database. A library is a
folder (or several) of markdown, PDFs, audio and Word documents; JADELY only ever
adds small sidecar files next to them:

``<name>.<ext>.flags.json``
    Hand-editable flags for one item: ``favorite``, ``played``, ``pinned``,
    ``downloaded``, plus free ``tags`` and a ``note``. This is the "flag file"
    format: plain JSON, next to the content, safe to edit in any editor.

``<root>/.jadely/state.json``
    Per-machine state that is not part of the content: playback positions, what
    was opened last, play counts. Losing it costs you nothing but progress bars.

Audio durations are read with the standard library only: ``wave`` for WAV, and a
frame-header scan for MP3. Nothing is uploaded and nothing is downloaded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import time
import wave
from pathlib import Path
from urllib.parse import quote

from . import markdown as md

__all__ = ["Library", "LibraryError", "KIND_BY_EXT", "FLAGS_FIELDS", "audio_info", "read_flags"]

KIND_BY_EXT = {
    ".md": "note",
    ".markdown": "note",
    ".txt": "note",
    ".pdf": "pdf",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".svg": "image",
    ".docx": "document",
    ".doc": "document",
    ".rtf": "document",
    ".odt": "document",
}

AUDIO_EXTS = {ext for ext, kind in KIND_BY_EXT.items() if kind == "audio"}
TEXT_EXTS = {".md", ".markdown", ".txt"}
CONVERTIBLE_EXTS = {".md", ".markdown", ".txt", ".docx"}
COVER_NAMES = ("cover", "folder", "poster", "artwork", "album")
SKIP_DIRS = {".jadely", ".git", ".obsidian", "node_modules", "__pycache__", "Exports"}
FLAGS_FIELDS = ("favorite", "played", "pinned", "downloaded", "note", "tags")


class LibraryError(Exception):
    """Anything the user should see as a clear message."""


# ------------------------------------------------------------------- flag files
def flags_path(item_path: Path) -> Path:
    return item_path.with_name(item_path.name + ".flags.json")


def read_flags(item_path: Path) -> dict:
    """Flags for one item, with the defaults filled in."""
    flags = {field: ([] if field == "tags" else False if field != "note" else "") for field in FLAGS_FIELDS}
    path = flags_path(item_path)
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            stored = {}
        if isinstance(stored, dict):
            for field in FLAGS_FIELDS:
                if field in stored and stored[field] is not None:
                    flags[field] = stored[field]
    if not isinstance(flags["tags"], list):
        flags["tags"] = []
    return flags


def write_flags(item_path: Path, flags: dict) -> dict:
    # Always write every field with a real value: this file is meant to be read
    # and edited by hand, so `null` has no business in it.
    defaults = {"favorite": False, "played": False, "pinned": False, "downloaded": False}
    payload: dict = {}
    for field in FLAGS_FIELDS:
        value = flags.get(field)
        if field == "tags":
            payload[field] = [str(tag).lstrip("#") for tag in (value or [])]
        elif field == "note":
            payload[field] = str(value or "")
        else:
            payload[field] = bool(value) if value is not None else defaults.get(field, False)
    payload["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        flags_path(item_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as error:
        raise LibraryError(f"Could not save flags for {item_path.name}: {error}") from error
    return payload


# ----------------------------------------------------------------------- audio
_MP3_BITRATES = {
    # version, layer -> kbps by index
    ("1", 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    ("1", 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0],
    ("1", 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0],
    ("2", 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
    ("2", 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
    ("2", 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0],
}
_MP3_RATES = {
    "1": [44100, 48000, 32000],
    "2": [22050, 24000, 16000],
    "2.5": [11025, 12000, 8000],
}


def _mp3_duration(path: Path) -> float | None:
    """Walk MP3 frame headers to add up playing time. No dependencies."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            start = 0
            header = handle.read(10)
            if header[:3] == b"ID3" and len(header) == 10:
                start = 10 + (
                    ((header[6] & 0x7F) << 21)
                    | ((header[7] & 0x7F) << 14)
                    | ((header[8] & 0x7F) << 7)
                    | (header[9] & 0x7F)
                )
                if header[5] & 0x10:  # footer present
                    start += 10
            if start >= size:
                return None
            handle.seek(start)
            seconds = 0.0
            frames = 0
            sample_rate = None
            while frames < 400_000:
                chunk = handle.read(4)
                if len(chunk) < 4:
                    break
                word = struct.unpack(">I", chunk)[0]
                if (word & 0xFFE00000) != 0xFFE00000:
                    break  # lost sync (or the file ended with a tag)
                version_bits = (word >> 19) & 0x3
                layer_bits = (word >> 17) & 0x3
                bitrate_index = (word >> 12) & 0xF
                rate_index = (word >> 10) & 0x3
                padding = (word >> 9) & 0x1
                if version_bits == 1 or layer_bits == 0 or bitrate_index in (0, 15) or rate_index == 3:
                    break
                version = {0: "2.5", 2: "2", 3: "1"}[version_bits]
                layer = {1: 3, 2: 2, 3: 1}[layer_bits]
                table_version = "1" if version == "1" else "2"
                bitrate = _MP3_BITRATES[(table_version, layer)][bitrate_index] * 1000
                sample_rate = _MP3_RATES[version][rate_index]
                if not bitrate or not sample_rate:
                    break
                samples = (1152 if version == "1" else 576) if layer == 3 else 1152
                seconds += samples / sample_rate
                frame_length = (samples // 8) * bitrate // sample_rate + padding
                if frame_length <= 0:
                    break
                handle.seek(frame_length - 4, os.SEEK_CUR)
                frames += 1
            if frames < 2:
                return None
            return round(seconds, 2)
    except (OSError, struct.error, KeyError):
        return None


def audio_info(path: str | os.PathLike[str]) -> dict:
    """Duration / format / channels for a WAV or MP3 file."""
    target = Path(path)
    suffix = target.suffix.lower()
    info = {
        "format": suffix.lstrip("."),
        "duration": None,
        "sample_rate": None,
        "channels": None,
    }
    if suffix == ".wav":
        try:
            with wave.open(str(target), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate() or 0
                info["channels"] = handle.getnchannels()
                info["sample_rate"] = rate
                info["duration"] = round(frames / rate, 2) if rate else None
        except (wave.Error, OSError, EOFError):
            pass
        return info
    if suffix == ".mp3":
        info["duration"] = _mp3_duration(target)
        return info
    return info


# ------------------------------------------------------------------- the library
def _iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp))


def _human_size(size: int) -> str:
    step = 1024.0
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < step or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} GB"


def _clock(seconds: float | None) -> str:
    if not seconds:
        return ""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class Library:
    """An index over one or more content roots."""

    def __init__(self, roots: list[str | os.PathLike[str]] | None = None) -> None:
        self.roots: list[Path] = []
        for root in roots or []:
            self.add_root(root, create=True)
        self._cache: dict[str, tuple[float, int, dict]] = {}
        self._text_cache: dict[str, tuple[float, int, str]] = {}

    # ------------------------------------------------------------------ roots
    def add_root(self, path: str | os.PathLike[str], *, create: bool = False) -> Path:
        root = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
        if create:
            root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise LibraryError(f"That folder does not exist: {root}")
        if root not in self.roots:
            self.roots.append(root)
        return root

    def remove_root(self, path: str | os.PathLike[str]) -> None:
        target = Path(str(path)).resolve()
        self.roots = [root for root in self.roots if root != target]

    @property
    def root(self) -> Path | None:
        return self.roots[0] if self.roots else None

    def root_label(self, path: Path) -> str:
        for index, root in enumerate(self.roots):
            if path == root or root in path.parents:
                return root.name if index == 0 else f"{root.name}"
        return ""

    # -------------------------------------------------------------- state file
    @property
    def state_path(self) -> Path | None:
        root = self.root
        if root is None:
            return None
        return root / ".jadely" / "state.json"

    def read_state(self) -> dict:
        path = self.state_path
        if path is None or not path.is_file():
            return {"progress": {}, "recent": [], "seq": 0}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("progress", {})
        state.setdefault("recent", [])
        state.setdefault("seq", 0)
        return state

    def write_state(self, state: dict) -> None:
        path = self.state_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------- paths
    def item_id(self, path: Path) -> str:
        return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]

    def resolve(self, item_id: str) -> Path:
        """Find the absolute path behind an item id."""
        for item in self.index():
            if item["id"] == item_id:
                return Path(item["absolute"])
        # Fall back to a path-shaped id so the UI can pass either.
        candidate = Path(str(item_id))
        if candidate.is_file():
            return candidate.resolve()
        raise LibraryError(f"Unknown item: {item_id}")

    @staticmethod
    def _safe_relative(path: Path) -> str:
        return quote(path.as_posix(), safe="/-_. ()[]!',")

    # ------------------------------------------------------------------- index
    def index(self, *, refresh: bool = False) -> list[dict]:
        if refresh:
            self._cache.clear()
            self._text_cache.clear()
        items: list[dict] = []
        for root in self.roots:
            for path in self._walk(root):
                items.append(self._describe(path))
        items.sort(key=lambda item: (item["program"].lower(), item["sort_key"], item["name"].lower()))
        return items

    def _walk(self, root: Path):
        try:
            entries = sorted(root.rglob("*"), key=lambda p: str(p).lower())
        except OSError:
            return
        for path in entries:
            if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
                continue
            name = path.name
            if name.startswith(".") or name.endswith(".flags.json"):
                continue
            if path.suffix.lower() in (".json", ".jadely-tmp"):
                continue
            if path.is_file() and path.suffix.lower() in KIND_BY_EXT:
                yield path

    def _describe(self, path: Path) -> dict:
        try:
            stat = path.stat()
        except OSError:
            stat = None
        # The flag sidecar is part of what this item looks like, so its timestamp
        # belongs in the cache key: someone editing <file>.flags.json by hand (or
        # another JADELY window writing it) must be visible immediately.
        try:
            flags_stamp = flags_path(path).stat().st_mtime
        except OSError:
            flags_stamp = 0.0
        cached = self._cache.get(str(path))
        if cached and cached[0] == (stat.st_mtime if stat else 0.0) and cached[1] == (
            stat.st_size if stat else 0
        ) and cached[2] == flags_stamp:
            return cached[3]

        extension = path.suffix.lower()
        kind = KIND_BY_EXT.get(extension, "file")
        folder = self._folder_of(path)
        item = {
            "id": self.item_id(path),
            "name": path.name,
            "title": path.stem,
            "kind": kind,
            "ext": extension.lstrip("."),
            "size": stat.st_size if stat else 0,
            "sizeLabel": _human_size(stat.st_size if stat else 0),
            "mtime": _iso(stat.st_mtime) if stat else "",
            "mtimeEpoch": stat.st_mtime if stat else 0.0,
            "absolute": str(path),
            "url": self.url_for(path),
            "folder": folder,
            "program": folder.split("/")[0] if folder else "",
            "root": self.root_label(path),
            "sort_key": _natural_key(path.name),
            "flags": read_flags(path),
            "tags": [],
            "words": 0,
            "duration": None,
            "durationLabel": "",
            "audio": None,
            "siblingAudio": None,
            "cover": None,
        }
        if kind == "note":
            text = self.text(path)
            item["title"] = self._title_from_text(text, path.stem)
            item["words"] = md.count_words(text)
            item["excerpt"] = md.plain_text(text)[:240]
            item["tags"] = _find_tags(text)
        elif kind == "document":
            item["tags"] = []
        elif kind == "audio":
            info = audio_info(path)
            item["duration"] = info["duration"]
            item["durationLabel"] = _clock(info["duration"])
            item["audioFormat"] = info["format"]
        elif kind == "pdf":
            item["tags"] = []
        elif kind == "image":
            item["tags"] = []

        item["tags"] = sorted({tag.lower() for tag in (list(item["tags"]) + list(item["flags"].get("tags") or []))})
        item["isCover"] = kind == "image" and path.stem.lower() in COVER_NAMES
        cover = self.folder_cover(path.parent)
        if cover:
            item["cover"] = self.url_for(cover)
        self._cache[str(path)] = (
            stat.st_mtime if stat else 0.0,
            stat.st_size if stat else 0,
            flags_stamp,
            item,
        )
        return item

    def _folder_of(self, path: Path) -> str:
        for root in self.roots:
            if path == root or root in path.parents:
                relative = path.parent.relative_to(root)
                return "" if str(relative) == "." else relative.as_posix()
        return ""

    def url_for(self, path: Path) -> str:
        """A loopback URL the UI can fetch, whichever root the file is in."""
        return f"/media?path={quote(str(path.resolve()), safe='')}"

    @staticmethod
    def _title_from_text(text: str, fallback: str) -> str:
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and len(stripped) > 2:
                return stripped[2:].strip()
        return fallback

    def folder_cover(self, folder: Path) -> Path | None:
        try:
            for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                if child.is_file() and child.suffix.lower() in KIND_BY_EXT and KIND_BY_EXT[child.suffix.lower()] == "image":
                    if child.stem.lower() in COVER_NAMES:
                        return child
        except OSError:
            return None
        return None

    # -------------------------------------------------------------------- text
    def text(self, path: str | os.PathLike[str], *, limit: int | None = None) -> str:
        """Extracted text: markdown/plain directly, .docx via the converter."""
        target = Path(path)
        try:
            stat = target.stat()
        except OSError:
            return ""
        stamp = (stat.st_mtime, stat.st_size)
        cached = self._text_cache.get(str(target))
        if cached and cached[0] == stamp[0] and cached[1] == stamp[1]:
            return cached[2][:limit] if limit else cached[2]

        suffix = target.suffix.lower()
        text = ""
        try:
            if suffix in TEXT_EXTS:
                text = target.read_text(encoding="utf-8", errors="replace")
            elif suffix == ".docx":
                from .convert import ConvertError, docx_to_markdown

                try:
                    text = docx_to_markdown(target)["markdown"]
                except ConvertError:
                    text = ""
        except OSError:
            text = ""
        self._text_cache[str(target)] = (stamp[0], stamp[1], text)
        return text[:limit] if limit else text

    def item(self, item_id: str) -> dict:
        for item in self.index():
            if item["id"] == item_id:
                return item
        raise LibraryError(f"Unknown item: {item_id}")

    # --------------------------------------------------------------- grouping
    def program_flags(self, program: str) -> dict:
        """The ``program.flags.json`` for a program folder (empty when absent)."""
        for item in self.index():
            if item["program"] == program:
                return read_flags(Path(item["absolute"]).parent / "program")
        return {}

    def programs(self) -> list[dict]:
        """Top-level folders, with what they contain. The store's shelf shape."""
        groups: dict[str, dict] = {}
        for item in self.index():
            key = item["program"]
            group = groups.setdefault(
                key,
                {
                    "id": hashlib.sha1(f"program::{key}".encode()).hexdigest()[:12],
                    "title": key or "Loose files",
                    "folder": key,
                    "items": 0,
                    "words": 0,
                    "seconds": 0.0,
                    "kinds": {},
                    "cover": None,
                    "tags": set(),
                    "favorite": False,
                    "updated": 0.0,
                },
            )
            group["items"] += 1
            group["words"] += item.get("words") or 0
            group["seconds"] += item.get("duration") or 0.0
            group["kinds"][item["kind"]] = group["kinds"].get(item["kind"], 0) + 1
            group["tags"].update(item["tags"])
            group["favorite"] = group["favorite"] or bool(item["flags"].get("favorite"))
            group["updated"] = max(group["updated"], item["mtimeEpoch"])
            group["cover"] = group["cover"] or item.get("cover")
        out = []
        for group in groups.values():
            # A program's own flag file counts too, so starring a program in the
            # News portal shows up as a starred shelf in the Store.
            program_flags = self.program_flags(group["folder"]) if group["folder"] else {}
            group["flags"] = program_flags
            group["favorite"] = group["favorite"] or bool(program_flags.get("favorite"))
            group["pinned"] = bool(program_flags.get("pinned"))
            group["tags"] = sorted(group["tags"] | set(program_flags.get("tags") or []))
            group["note"] = program_flags.get("note") or ""
            group["seconds"] = round(group["seconds"], 2)
            group["durationLabel"] = _clock(group["seconds"])
            group["updatedLabel"] = _iso(group["updated"]) if group["updated"] else ""
            out.append(group)
        out.sort(key=lambda group: (-group["items"], group["title"].lower()))
        return out

    def _program_path(self, program: str) -> Path:
        for item in self.index():
            if item["program"] == program:
                return Path(item["absolute"]).parent / "program"
        raise LibraryError(f"Unknown program: {program}")

    def stats(self) -> dict:
        items = self.index()
        kinds: dict[str, int] = {}
        total = 0
        words = 0
        seconds = 0.0
        for item in items:
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
            total += item["size"]
            words += item.get("words") or 0
            seconds += item.get("duration") or 0.0
        return {
            "items": len(items),
            "kinds": kinds,
            "bytes": total,
            "sizeLabel": _human_size(total),
            "words": words,
            "seconds": round(seconds, 2),
            "durationLabel": _clock(seconds),
            "programs": len({item["program"] for item in items}),
            "roots": [{"path": str(root), "name": root.name} for root in self.roots],
        }

    # ----------------------------------------------------------------- search
    def search(
        self,
        query: str = "",
        *,
        kind: str = "",
        tag: str = "",
        flag: str = "",
        program: str | None = None,
        limit: int = 300,
        covers: bool = False,
    ) -> list[dict]:
        """Find items. ``program=None`` means "any shelf"; ``program=""`` means the
        loose files that sit directly in a library root."""
        terms = [term for term in re.split(r"\s+", (query or "").strip().lower()) if term]
        results: list[tuple[int, dict]] = []
        for item in self.index():
            # Cover art belongs to its program, not to the shelf as loose content:
            # it only shows up when you ask for images explicitly.
            if item.get("isCover") and not covers and kind != "image":
                continue
            if kind and item["kind"] != kind:
                continue
            if program is not None and item["program"] != program:
                continue
            if tag and tag.lstrip("#").lower() not in item["tags"]:
                continue
            if flag and not item["flags"].get(flag):
                continue
            score = 0
            if terms:
                haystack_title = item["title"].lower()
                haystack_name = item["name"].lower()
                haystack_tags = " ".join(item["tags"])
                body = ""
                for term in terms:
                    if term in haystack_title:
                        score += 6
                    elif term in haystack_name:
                        score += 4
                    elif term in haystack_tags:
                        score += 3
                    else:
                        if item["kind"] in ("note", "document"):
                            if not body:
                                body = self.text(item["absolute"], limit=200_000).lower()
                            body = body or ""
                        if term in body:
                            score += 1
                        else:
                            score = 0
                            break
            results.append((score, item))
        if terms:
            results = [entry for entry in results if entry[0] > 0]
            results.sort(key=lambda entry: (-entry[0], -entry[1]["mtimeEpoch"]))
        else:
            results.sort(key=lambda entry: (-entry[1]["mtimeEpoch"], entry[1]["name"].lower()))
        return [item for _, item in results][: max(1, int(limit))]

    def tag_counts(self) -> list[dict]:
        counts: dict[str, int] = {}
        for item in self.index():
            for tag in item["tags"]:
                counts[tag] = counts.get(tag, 0) + 1
        return [
            {"tag": tag, "count": count}
            for tag, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]

    # ------------------------------------------------------------------ flags
    def set_flags(self, item_id: str, patch: dict) -> dict:
        path = self.resolve(item_id)
        flags = read_flags(path)
        for field in FLAGS_FIELDS:
            if field in patch and patch[field] is not None:
                flags[field] = patch[field]
        if isinstance(flags["tags"], str):
            flags["tags"] = [tag.strip() for tag in flags["tags"].split(",") if tag.strip()]
        saved = write_flags(path, flags)
        self._cache.pop(str(path), None)
        return {"item": str(path), "flags": saved}

    def toggle_flag(self, item_id: str, flag: str) -> dict:
        if flag not in FLAGS_FIELDS or flag in ("note", "tags"):
            raise LibraryError(f"Cannot toggle {flag}")
        path = self.resolve(item_id)
        flags = read_flags(path)
        flags[flag] = not bool(flags[flag])
        saved = write_flags(path, flags)
        self._cache.pop(str(path), None)
        return {"item": str(path), "flag": flag, "value": saved[flag], "flags": saved}

    # --------------------------------------------------------------- progress
    def progress_for(self, item_id: str) -> dict:
        state = self.read_state()
        return state["progress"].get(item_id, {})

    def set_progress(
        self,
        item_id: str,
        *,
        position: float | None = None,
        duration: float | None = None,
        segment: str = "",
        played: bool | None = None,
        touch: bool = True,
    ) -> dict:
        state = self.read_state()
        entry = state["progress"].get(item_id, {})
        if position is not None:
            entry["position"] = round(float(position), 2)
        if duration is not None:
            entry["duration"] = round(float(duration), 2)
        if segment:
            entry["segment"] = segment
        if played is not None:
            entry["played"] = bool(played)
            entry["count"] = (entry.get("count") or 0) + (1 if played else 0)
        entry["total"] = entry.get("duration") or 0
        entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        # Wall-clock time only has one-second resolution, which is far too coarse to
        # order two saves made a moment apart, so keep a counter as the tiebreaker.
        state["seq"] = int(state.get("seq") or 0) + 1
        entry["seq"] = state["seq"]
        state["progress"][item_id] = entry
        if touch:
            recent = [value for value in state.get("recent", []) if value != item_id]
            recent.insert(0, item_id)
            state["recent"] = recent[:40]
        self.write_state(state)
        return entry

    def recent(self, limit: int = 8) -> list[dict]:
        state = self.read_state()
        index = {item["id"]: item for item in self.index()}
        out = []
        for item_id in state.get("recent", []):
            item = index.get(item_id)
            if item:
                item = dict(item)
                item["progress"] = state["progress"].get(item_id, {})
                out.append(item)
            if len(out) >= limit:
                break
        return out

    def continue_listening(self, limit: int = 6) -> list[dict]:
        state = self.read_state()
        index = {item["id"]: item for item in self.index()}
        out = []
        for item_id, entry in sorted(
            state.get("progress", {}).items(),
            key=lambda pair: (pair[1].get("seq") or 0, pair[1].get("at", "")),
            reverse=True,
        ):
            item = index.get(item_id)
            if not item or not entry.get("position"):
                continue
            if item["kind"] != "audio":
                continue
            item = dict(item)
            item["progress"] = entry
            item["positionLabel"] = _clock(entry.get("position"))
            item["percent"] = round(
                100 * entry["position"] / entry["duration"], 1
            ) if entry.get("duration") else 0
            out.append(item)
            if len(out) >= limit:
                break
        return out

    # ----------------------------------------------------------------- import
    def import_paths(
        self,
        sources: list[str | os.PathLike[str]],
        *,
        folder: str = "Imported",
        move: bool = False,
        into: str | os.PathLike[str] | None = None,
    ) -> dict:
        """Bring outside files into a library folder (copy by default)."""
        destination_root = Path(into).resolve() if into else self.root
        if destination_root is None:
            raise LibraryError("The library has no root folder yet")
        target_dir = destination_root / _safe_name(folder) if folder else destination_root
        target_dir.mkdir(parents=True, exist_ok=True)
        imported: list[dict] = []
        skipped: list[dict] = []
        for raw in sources:
            source = Path(raw)
            if not source.exists():
                skipped.append({"source": str(source), "reason": "not found"})
                continue
            candidates = [source] if source.is_file() else [
                path for path in source.rglob("*") if path.is_file()
            ]
            for candidate in candidates:
                if candidate.suffix.lower() not in KIND_BY_EXT:
                    skipped.append({"source": str(candidate), "reason": "unsupported"})
                    continue
                if self._inside_a_root(candidate):
                    skipped.append({"source": str(candidate), "reason": "already in the library"})
                    continue
                relative = Path(candidate.name) if source.is_file() else candidate.relative_to(source)
                target = target_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target = target.with_name(f"{target.stem} {time.strftime('%H%M%S')}{target.suffix}")
                try:
                    if move:
                        shutil.move(str(candidate), str(target))
                    else:
                        shutil.copy2(candidate, target)
                except OSError as error:
                    skipped.append({"source": str(candidate), "reason": str(error)})
                    continue
                imported.append({"source": str(candidate), "target": str(target)})
        self.index(refresh=True)
        return {"imported": imported, "skipped": skipped, "folder": str(target_dir)}

    def export_item(self, item_id: str, target_dir: str | os.PathLike[str]) -> dict:
        """Copy one item out of the library (and its flag file, so it travels)."""
        source = self.resolve(item_id)
        destination = Path(target_dir)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / source.name
        if target.exists():
            target = target.with_name(f"{target.stem} {time.strftime('%H%M%S')}{target.suffix}")
        try:
            shutil.copy2(source, target)
            sidecar = flags_path(source)
            if sidecar.is_file():
                shutil.copy2(sidecar, flags_path(target))
        except OSError as error:
            raise LibraryError(f"Could not export {source.name}: {error}") from error
        return {"exported": str(target), "source": str(source)}

    def export_folder(self, program: str, target_dir: str | os.PathLike[str]) -> dict:
        """Copy a whole program folder out of the library."""
        target_root = Path(target_dir)
        count = 0
        for item in self.index():
            if item["program"] != program:
                continue
            destination = target_root / program / item["name"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(item["absolute"], destination)
                count += 1
            except OSError as error:
                raise LibraryError(f"Could not export {item['name']}: {error}") from error
        if not count:
            raise LibraryError(f"Nothing to export for {program or 'loose files'}")
        return {"exported": count, "folder": str(target_root / program)}

    def _inside_a_root(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == root or root in resolved.parents for root in self.roots)

    # ----------------------------------------------------------------- delete
    def delete(self, item_id: str) -> dict:
        """Move an item to ``<root>/.jadely/trash/``. Never deletes outright."""
        source = self.resolve(item_id)
        root = self.root
        if root is None:
            raise LibraryError("The library has no root folder")
        if not self._inside_a_root(source) or ".jadely" in source.parts:
            raise LibraryError("That file is outside the library folder, so JADELY will not remove it")
        trash_dir = root / ".jadely" / "trash" / time.strftime("%Y%m%d-%H%M%S")
        trash_dir.mkdir(parents=True, exist_ok=True)
        target = trash_dir / source.name
        try:
            sidecar = flags_path(source)
            shutil.move(str(source), str(target))
            if sidecar.is_file():
                shutil.move(str(sidecar), str(flags_path(target)))
        except OSError as error:
            raise LibraryError(f"Could not delete {source.name}: {error}") from error
        self.index(refresh=True)
        return {"deleted": str(source), "movedTo": str(target)}


# --------------------------------------------------------------------- helpers
def _safe_name(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(text)).strip().strip(".")
    return cleaned[:80] or "Imported"


def _natural_key(text: str) -> tuple:
    """Sort ``02 - Two`` before ``10 - Ten``."""
    parts = re.split(r"(\d+)", text.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _find_tags(text: str) -> list[str]:
    from .vault import parse_tags

    try:
        return parse_tags(text or "")
    except Exception:  # noqa: BLE001 - tags are a nicety, never fail the index
        return []


def format_duration(seconds: float | None) -> str:
    return _clock(seconds)
