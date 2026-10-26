"""Vault: a plain folder of markdown files.

Jadeli never keeps notes in a database. Every note is a real file on disk that
you can open with any editor, sync with any tool, or put in git.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

NOTE_EXTS = {".md", ".markdown", ".txt"}
SKIP_DIRS = {".jadeli", ".git", ".obsidian", "node_modules", "__pycache__"}
# Generated manuscripts live here; they are files you can open, but they should
# not show up twice in search, tags or the graph.
INDEX_SKIP_PREFIXES = ("Exports/",)

WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+)(?:#([^\[\]|]+))?(?:\|([^\[\]]+))?\]\]")
TAG_RE = re.compile(r"(?<![\w/&#])#([A-Za-z][\w/\-]{0,63})")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)


class VaultError(Exception):
    """Raised for anything the user should see as an error message."""


def _slug(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "Untitled"


def strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code so we don't index them."""
    text = FENCE_RE.sub("", text)
    return re.sub(r"`[^`\n]*`", "", text)


def note_title(path: str, content: str) -> str:
    match = HEADING_RE.search(content or "")
    if match and match.group(1) == "#":
        title = match.group(2).strip()
        if title:
            return title
    return Path(path).stem


def parse_links(content: str) -> list[str]:
    """Wiki-link targets, in document order, de-duplicated."""
    seen: list[str] = []
    for match in WIKILINK_RE.finditer(strip_code(content)):
        target = match.group(1).strip()
        if target and target not in seen:
            seen.append(target)
    return seen


def parse_tags(content: str) -> list[str]:
    seen: list[str] = []
    for match in TAG_RE.finditer(strip_code(content)):
        tag = match.group(1).strip().rstrip("/-")
        if tag and tag.lower() not in [t.lower() for t in seen]:
            seen.append(tag)
    return seen


class Vault:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise VaultError(f"Vault folder does not exist: {self.root}")
        self._cache: dict[str, tuple[float, int, dict]] = {}

    # ---------------------------------------------------------------- paths
    @property
    def name(self) -> str:
        return self.root.name

    def resolve(self, relpath: str, *, must_exist: bool = True) -> Path:
        """Turn a vault-relative path into an absolute path, refusing escapes."""
        if relpath is None:
            raise VaultError("Missing path")
        rel = str(relpath).replace("\\", "/").strip()
        if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
            raise VaultError("Paths must be relative to the vault")
        target = (self.root / rel).resolve() if rel else self.root
        if target != self.root and self.root not in target.parents:
            raise VaultError("Path escapes the vault")
        if must_exist and not target.exists():
            raise VaultError(f"Not found: {rel}")
        return target

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    # ----------------------------------------------------------------- tree
    def tree(self) -> list[dict]:
        return self._walk(self.root)

    def _walk(self, folder: Path) -> list[dict]:
        entries: list[dict] = []
        try:
            children = sorted(
                folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError:
            return entries
        for child in children:
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            try:
                stat = child.stat()
            except OSError:
                continue
            if child.is_dir():
                entries.append(
                    {
                        "type": "folder",
                        "name": child.name,
                        "path": self.rel(child),
                        "children": self._walk(child),
                    }
                )
            elif child.suffix.lower() in NOTE_EXTS:
                entries.append(
                    {
                        "type": "note",
                        "name": child.name,
                        "path": self.rel(child),
                        "size": stat.st_size,
                        "mtime": int(stat.st_mtime),
                    }
                )
        return entries

    def notes(self) -> list[str]:
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
            )
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                if path.suffix.lower() in NOTE_EXTS:
                    found.append(self.rel(path))
        return found

    def folders(self) -> list[str]:
        found: list[str] = []
        for dirpath, dirnames, _ in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
            )
            for name in dirnames:
                found.append(self.rel(Path(dirpath) / name))
        return found

    # ------------------------------------------------------------ read/write
    def read(self, relpath: str) -> dict:
        path = self.resolve(relpath)
        if path.is_dir():
            raise VaultError("That is a folder, not a note")
        content = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        return {
            "path": self.rel(path),
            "name": path.name,
            "title": note_title(self.rel(path), content),
            "content": content,
            "mtime": int(stat.st_mtime),
            "size": stat.st_size,
        }

    def write(self, relpath: str, content: str) -> dict:
        path = self.resolve(relpath, must_exist=False)
        if path.is_dir():
            raise VaultError("Cannot write to a folder")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".jadeli-tmp")
        tmp.write_text(content, encoding="utf-8", newline="")
        os.replace(tmp, path)  # atomic-ish save: no half-written notes
        stat = path.stat()
        return {
            "path": self.rel(path),
            "mtime": int(stat.st_mtime),
            "size": stat.st_size,
            "title": note_title(self.rel(path), content),
        }

    def create_note(self, path: str, content: str = "", *, unique: bool = True) -> str:
        rel = path.replace("\\", "/").strip("/")
        if not rel:
            raise VaultError("Missing file name")
        if not Path(rel).suffix:
            rel += ".md"
        if Path(rel).suffix.lower() not in NOTE_EXTS:
            raise VaultError("Only .md, .markdown and .txt notes are supported")
        target = self.resolve(rel, must_exist=False)
        if target.exists() and unique:
            rel = self._unique_name(rel)
            target = self.resolve(rel, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        return self.rel(target)

    def _unique_name(self, rel: str) -> str:
        path = Path(rel)
        stem, suffix, parent = path.stem, path.suffix, path.parent
        counter = 2
        while (self.root / parent / f"{stem} {counter}{suffix}").exists():
            counter += 1
        return (parent / f"{stem} {counter}{suffix}").as_posix()

    def create_folder(self, path: str) -> str:
        rel = path.replace("\\", "/").strip("/")
        if not rel:
            raise VaultError("Missing folder name")
        target = self.resolve(rel, must_exist=False)
        if target.exists():
            raise VaultError("That folder already exists")
        target.mkdir(parents=True)
        return self.rel(target)

    def rename(self, relpath: str, new_name: str) -> dict:
        source = self.resolve(relpath)
        new_name = _slug(Path(str(new_name)).name)
        if source.is_file() and not Path(new_name).suffix:
            new_name += source.suffix
        dest = source.with_name(new_name)
        if dest.exists() and dest != source:
            raise VaultError("Something with that name already exists")
        os.replace(source, dest)
        return {"path": self.rel(dest)}

    def move(self, relpath: str, dest_folder: str) -> dict:
        source = self.resolve(relpath)
        folder = self.resolve(dest_folder) if dest_folder else self.root
        if not folder.is_dir():
            raise VaultError("Destination is not a folder")
        if folder == source.parent:
            return {"path": self.rel(source)}
        dest = folder / source.name
        if dest.exists():
            dest = folder / self._unique_name(
                ((source.parent / source.name).relative_to(self.root)).as_posix()
            ).split("/")[-1]
        shutil.move(str(source), str(dest))
        return {"path": self.rel(Path(dest))}

    def delete(self, relpath: str) -> dict:
        """Delete by moving into the vault's private trash folder."""
        target = self.resolve(relpath)
        if target == self.root:
            raise VaultError("Refusing to delete the vault")
        trash = self.root / ".jadeli" / "trash" / time.strftime("%Y%m%d-%H%M%S")
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / target.name
        counter = 2
        while destination.exists():
            destination = trash / f"{target.stem} {counter}{target.suffix}"
            counter += 1
        shutil.move(str(target), str(destination))
        return {"trashed": self.rel(destination) if destination.exists() else ""}

    # ---------------------------------------------------------------- index
    def _stat_key(self, path: Path) -> tuple[float, int]:
        stat = path.stat()
        return (stat.st_mtime, stat.st_size)

    def index(self) -> dict[str, dict]:
        """path -> {title, content, links, tags, mtime} with an mtime cache."""
        index: dict[str, dict] = {}
        for relpath in self.notes():
            if relpath.startswith(INDEX_SKIP_PREFIXES):
                continue
            path = self.resolve(relpath)
            try:
                key = self._stat_key(path)
            except OSError:
                continue
            cached = self._cache.get(relpath)
            if cached and cached[0] == key[0] and cached[1] == key[1]:
                index[relpath] = cached[2]
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            entry = {
                "title": note_title(relpath, content),
                "content": content,
                "links": parse_links(content),
                "tags": parse_tags(content),
                "mtime": int(key[0]),
            }
            self._cache[relpath] = (key[0], key[1], entry)
            index[relpath] = entry
        # drop cache entries for deleted notes
        for stale in set(self._cache) - set(index):
            del self._cache[stale]
        return index

    def _resolver(self, index: dict[str, dict]):
        by_stem: dict[str, list[str]] = {}
        by_path: dict[str, str] = {}
        by_title: dict[str, list[str]] = {}
        for relpath, entry in index.items():
            stem = Path(relpath).stem
            # "01 - Chapter One" should also answer to "Chapter One"
            for variant in {stem.lower(), re.sub(r"^\d+\s*[-.)]\s*", "", stem).lower()}:
                by_stem.setdefault(variant, []).append(relpath)
            by_path[relpath.lower()] = relpath
            by_path[relpath.rsplit(".", 1)[0].lower()] = relpath
            by_title.setdefault(entry["title"].lower(), []).append(relpath)

        def resolve_link(target: str) -> str | None:
            cleaned = target.strip().replace("\\", "/")
            if cleaned.lower().endswith((".md", ".markdown", ".txt")):
                cleaned = cleaned.rsplit(".", 1)[0]
            key = cleaned.lower()
            if key in by_path:
                return by_path[key]
            for table in (by_title, by_stem):
                matches = table.get(key) or table.get(Path(key).name)
                if matches:
                    return sorted(matches)[0]
            return None

        return resolve_link

    def backlinks(self, relpath: str | None = None, index: dict[str, dict] | None = None) -> dict:
        index = index or self.index()
        resolve = self._resolver(index)
        incoming: dict[str, list[dict]] = {path: [] for path in index}
        outgoing: dict[str, list[dict]] = {}
        for path, entry in index.items():
            targets = []
            for raw in entry["links"]:
                resolved = resolve(raw)
                if resolved != path:
                    targets.append(
                        {
                            "target": raw,
                            "path": resolved or "",
                            "title": index[resolved]["title"] if resolved else raw,
                            "exists": bool(resolved),
                        }
                    )
                if resolved and resolved != path:
                    incoming[resolved].append(
                        {
                            "path": path,
                            "title": entry["title"],
                            "context": _link_context(entry["content"], raw),
                        }
                    )
            outgoing[path] = targets
        if relpath is None:
            return {"incoming": incoming, "outgoing": outgoing}
        return {
            "backlinks": incoming.get(relpath, []),
            "links": outgoing.get(relpath, []),
        }

    def graph(self) -> dict:
        index = self.index()
        resolve = self._resolver(index)
        nodes = [
            {
                "id": path,
                "title": entry["title"],
                "path": path,
                "tags": entry["tags"][:6],
                "words": len(entry["content"].split()),
            }
            for path, entry in index.items()
        ]
        seen: set[tuple[str, str]] = set()
        edges: list[dict] = []
        for path, entry in index.items():
            for raw in entry["links"]:
                target = resolve(raw)
                if not target or target == path:
                    continue
                pair = tuple(sorted((path, target)))
                if pair in seen:
                    continue
                seen.add(pair)
                edges.append({"source": path, "target": target})
        return {"nodes": nodes, "edges": edges}

    def tags(self) -> list[dict]:
        index = self.index()
        counts: dict[str, int] = {}
        for entry in index.values():
            for tag in entry["tags"]:
                counts[tag] = counts.get(tag, 0) + 1
        return [
            {"tag": tag, "count": count}
            for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
        ]

    def search(self, query: str, limit: int = 60) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        index = self.index()
        lowered = query.lower()
        terms = [term for term in lowered.split() if term]
        results: list[dict] = []
        for path, entry in index.items():
            haystack = entry["content"].lower()
            title = entry["title"].lower()
            if not all(term in haystack or term in title for term in terms):
                continue
            score = 0
            if title == lowered:
                score += 200
            elif lowered in title:
                score += 120
            score += min(haystack.count(lowered), 12) * 6
            if path.lower().endswith(lowered):
                score += 40
            results.append(
                {
                    "path": path,
                    "title": entry["title"],
                    "score": score,
                    "snippet": _snippet(entry["content"], terms[0]),
                    "matches": haystack.count(terms[0]),
                }
            )
        results.sort(key=lambda r: (-r["score"], r["title"].lower()))
        return results[:limit]


def _link_context(content: str, raw: str) -> str:
    for line in content.splitlines():
        if f"[[{raw}" in line:
            text = line.strip()
            return text[:160]
    return ""


def _snippet(content: str, term: str, radius: int = 70) -> str:
    flat = re.sub(r"\s+", " ", content)
    position = flat.lower().find(term)
    if position < 0:
        return flat[: radius * 2].strip()
    start = max(0, position - radius)
    end = min(len(flat), position + len(term) + radius)
    return ("…" if start else "") + flat[start:end].strip() + ("…" if end < len(flat) else "")
