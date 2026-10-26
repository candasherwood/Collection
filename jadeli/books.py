"""Books: an ordered manuscript made of ordinary vault notes.

A book is metadata only (title, chapter order, word target). The chapters
themselves stay normal markdown notes, so they are editable, searchable,
linkable and graphable like everything else.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from .vault import Vault, VaultError, note_title

BOOKS_DIR = "Books"
CONFIG_DIR = ".jadeli"
STORE_NAME = "books.json"


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


class Books:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.store_path = vault.root / CONFIG_DIR / STORE_NAME
        self.last_renamed: dict[str, str] = {}

    # ------------------------------------------------------------- storage
    def _load(self) -> dict:
        if not self.store_path.exists():
            return {"books": []}
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"books": []}
        if not isinstance(data, dict) or not isinstance(data.get("books"), list):
            return {"books": []}
        return data

    def _save(self, data: dict) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.store_path)

    def _find(self, book_id: str, data: dict | None = None) -> tuple[dict, dict]:
        data = data if data is not None else self._load()
        for book in data["books"]:
            if book.get("id") == book_id:
                return book, data
        raise VaultError("That book no longer exists")

    # ---------------------------------------------------------------- read
    def _decorate(self, book: dict, index: dict[str, dict]) -> dict:
        chapters = []
        total = 0
        for position, entry in enumerate(book.get("chapters", [])):
            path = entry.get("path") if isinstance(entry, dict) else entry
            note = index.get(path)
            words = word_count(note["content"]) if note else 0
            total += words
            chapters.append(
                {
                    "path": path,
                    "title": note["title"] if note else Path(str(path)).stem,
                    "words": words,
                    "missing": note is None,
                    "position": position,
                    "synopsis": (entry.get("synopsis", "") if isinstance(entry, dict) else ""),
                }
            )
        target = int(book.get("target_words") or 0)
        return {
            "id": book["id"],
            "title": book.get("title", "Untitled book"),
            "description": book.get("description", ""),
            "target_words": target,
            "words": total,
            "chapters": chapters,
            "chapter_count": len(chapters),
            "progress": round(min(total / target, 1) * 100) if target else 0,
            "created_at": book.get("created_at"),
            "folder": book.get("folder", ""),
        }

    def list_books(self) -> list[dict]:
        index = self.vault.index()
        return [
            self._decorate(book, index)
            for book in self._load()["books"]
        ]

    def get_book(self, book_id: str) -> dict:
        book, _ = self._find(book_id)
        return self._decorate(book, self.vault.index())

    # --------------------------------------------------------------- write
    def create_book(
        self,
        title: str,
        description: str = "",
        target_words: int = 50000,
        chapter_title: str = "Chapter One",
    ) -> dict:
        title = (title or "").strip() or "Untitled book"
        data = self._load()
        folder = f"{BOOKS_DIR}/{_safe_name(title)}"
        book = {
            "id": uuid.uuid4().hex[:12],
            "title": title,
            "description": description.strip(),
            "target_words": int(target_words or 0),
            "chapters": [],
            "folder": folder,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        data["books"].append(book)
        self._save(data)
        self.vault.create_folder(folder) if not (self.vault.root / folder).exists() else None
        if chapter_title:
            self.add_chapter(book["id"], chapter_title)
        return self.get_book(book["id"])

    def update_book(self, book_id: str, patch: dict) -> dict:
        book, data = self._find(book_id)
        for key in ("title", "description"):
            if key in patch and patch[key] is not None:
                book[key] = str(patch[key])
        if "target_words" in patch and patch["target_words"] is not None:
            book["target_words"] = int(patch["target_words"] or 0)
        self._save(data)
        return self._decorate(book, self.vault.index())

    def delete_book(self, book_id: str) -> dict:
        book, data = self._find(book_id)
        data["books"] = [b for b in data["books"] if b.get("id") != book_id]
        self._save(data)
        return {"deleted": book_id, "note": "Chapter files were left on disk."}

    def add_chapter(self, book_id: str, title: str, content: str | None = None) -> dict:
        book, data = self._find(book_id)
        title = (title or "").strip() or "New Chapter"
        folder = book.get("folder") or f"{BOOKS_DIR}/{_safe_name(book['title'])}"
        order = len(book.get("chapters", [])) + 1
        filename = f"{order:02d} - {_safe_name(title)}.md"
        body = content if content is not None else f"# {title}\n\n"
        path = self.vault.create_note(f"{folder}/{filename}", body)
        book.setdefault("chapters", []).append({"path": path, "synopsis": ""})
        self._save(data)
        return self.get_book(book_id)

    def attach_chapter(self, book_id: str, path: str) -> dict:
        book, data = self._find(book_id)
        self.vault.resolve(path)
        existing = [c.get("path") if isinstance(c, dict) else c for c in book.get("chapters", [])]
        if path in existing:
            raise VaultError("That note is already a chapter in this book")
        book.setdefault("chapters", []).append({"path": path, "synopsis": ""})
        self._save(data)
        return self.get_book(book_id)

    def remove_chapter(self, book_id: str, path: str) -> dict:
        book, data = self._find(book_id)
        before = len(book.get("chapters", []))
        book["chapters"] = [
            c for c in book.get("chapters", [])
            if (c.get("path") if isinstance(c, dict) else c) != path
        ]
        if len(book["chapters"]) == before:
            raise VaultError("That chapter is not in this book")
        self._save(data)
        return self.get_book(book_id)

    def move_chapter(self, book_id: str, path: str, direction: int) -> dict:
        self.last_renamed = {}
        book, data = self._find(book_id)
        chapters = book.get("chapters", [])
        paths = [c.get("path") if isinstance(c, dict) else c for c in chapters]
        if path not in paths:
            raise VaultError("That chapter is not in this book")
        index = paths.index(path)
        target = index + (1 if direction >= 0 else -1)
        if not 0 <= target < len(chapters):
            return self.get_book(book_id)
        chapters[index], chapters[target] = chapters[target], chapters[index]
        self._save(data)
        self._renumber(book)
        return self.get_book(book_id)

    def reorder(self, book_id: str, order: list[str]) -> dict:
        self.last_renamed = {}
        book, data = self._find(book_id)
        current = {
            (c.get("path") if isinstance(c, dict) else c): c
            for c in book.get("chapters", [])
        }
        ordered = [current[p] for p in order if p in current]
        ordered += [c for p, c in current.items() if p not in order]
        book["chapters"] = ordered
        self._save(data)
        self._renumber(book)
        return self.get_book(book_id)

    def _renumber(self, book: dict) -> None:
        """Keep the numeric filename prefix in step with the manuscript order."""
        changed = False
        renames: dict[str, str] = {}
        paths = [
            (c.get("path") if isinstance(c, dict) else c)
            for c in book.get("chapters", [])
        ]
        for position, path in enumerate(paths, start=1):
            try:
                source = self.vault.resolve(path)
            except VaultError:
                continue
            name = source.name
            match = re.match(r"^(\d+)\s*-\s*(.+)$", name)
            base = match.group(2) if match else name
            wanted = f"{position:02d} - {base}"
            if name == wanted:
                continue
            destination = source.with_name(wanted)
            counter = 2
            while destination.exists() and destination != source:
                destination = source.with_name(f"{position:02d} - {Path(base).stem} ({counter}){source.suffix}")
                counter += 1
            try:
                source.rename(destination)
            except OSError:
                continue
            new_path = self.vault.rel(destination)
            renames[path] = new_path
            for entry in book["chapters"]:
                if isinstance(entry, dict) and entry.get("path") == path:
                    entry["path"] = new_path
            changed = True
        self.last_renamed = dict(renames)
        if changed:
            data = self._load()
            for stored in data["books"]:
                if stored.get("id") == book.get("id"):
                    stored["chapters"] = book["chapters"]
            self._save(data)

    # -------------------------------------------------------------- export
    def manuscript(self, book_id: str) -> dict:
        """Ordered chapter payload for building an export document."""
        book = self.get_book(book_id)
        index = self.vault.index()
        chapters = []
        for chapter in book["chapters"]:
            note = index.get(chapter["path"])
            chapters.append(
                {
                    "title": chapter["title"],
                    "path": chapter["path"],
                    "content": note["content"] if note else "",
                    "words": chapter["words"],
                }
            )
        return {"book": book, "chapters": chapters}


def _safe_name(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip().strip(".")
    return re.sub(r"\s+", " ", cleaned)[:100] or "Untitled"
