"""The API surface shared by the desktop window, the browser and the tests.

One server, four windows: the launcher, the store, the news portal and the notes
app all talk to the same JSON-over-loopback API through :meth:`Api.call`, and the
browser uses the same routes the tests do.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import markdown as md
from .books import Books
from .config import DEFAULT_LIBRARY, DEFAULT_VAULT, VERSION, save_config
from .convert import (
    ConvertError,
    MIGRATABLE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    convert as convert_file,
    find_browser,
    migrate,
)
from .config import APP_DIR
from .launcher import Launcher, LauncherError
from .library import FLAGS_FIELDS, KIND_BY_EXT, Library, LibraryError
from .news import News, NewsError
from .vault import Vault, VaultError


class ApiError(Exception):
    pass


class Api:
    def __init__(self, config: dict, pick_folder=None, server_url: str = "", app_id: str = ""):
        self.config = config
        self.pick_folder = pick_folder  # injected by app.py when a window exists
        self.server_url = server_url
        self.app_id = app_id
        self._vault: Vault | None = None
        self._books: Books | None = None
        self._library: Library | None = None
        self._news: News | None = None
        self._launcher: Launcher | None = None

    # --------------------------------------------------------------- vault
    @property
    def vault(self) -> Vault:
        if self._vault is None:
            root = self.config.get("vault") or str(DEFAULT_VAULT)
            if not Path(root).is_dir():
                root = str(DEFAULT_VAULT)
                self.config["vault"] = root
            self._vault = Vault(root)
        return self._vault

    @property
    def books(self) -> Books:
        if self._books is None or self._books.vault is not self.vault:
            self._books = Books(self.vault)
        return self._books

    def _swap_vault(self, path: str) -> None:
        root = Path(os.path.expandvars(os.path.expanduser(path))).resolve()
        if not root.is_dir():
            raise ApiError(f"That folder does not exist: {root}")
        self._vault = Vault(root)
        self._books = Books(self._vault)
        self.config["vault"] = str(root)
        save_config(self.config)

    # --------------------------------------------------------------- state
    def state(self) -> dict:
        vault = self.vault
        index = vault.index()
        return {
            "app": "jadeli",
            "version": VERSION,
            "vault": str(vault.root),
            "vaultName": vault.name,
            "theme": self.config.get("theme", "dark"),
            "viewMode": self.config.get("view_mode", "split"),
            "sidebarTab": self.config.get("sidebar_tab", "files"),
            "rightPanel": self.config.get("right_panel", "outline"),
            "lastNote": self.config.get("last_note", ""),
            "counts": {
                "notes": len(index),
                "words": sum(len(entry["content"].split()) for entry in index.values()),
            },
        }

    def save_prefs(self, prefs: dict) -> dict:
        mapping = {
            "theme": "theme",
            "viewMode": "view_mode",
            "sidebarTab": "sidebar_tab",
            "rightPanel": "right_panel",
            "lastNote": "last_note",
        }
        for key, stored in mapping.items():
            if key in prefs and prefs[key] is not None:
                self.config[stored] = prefs[key]
        save_config(self.config)
        return {"prefs": {key: self.config[value] for key, value in mapping.items()}}

    def pick_vault(self) -> dict:
        if not self.pick_folder:
            raise ApiError("Folder picker is only available in the desktop window")
        chosen = self.pick_folder()
        if not chosen:
            return {"cancelled": True}
        path = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        self._swap_vault(str(path))
        return {"vault": str(self.vault.root), "vaultName": self.vault.name}

    def open_vault(self, path: str) -> dict:
        self._swap_vault(path)
        return {"vault": str(self.vault.root), "vaultName": self.vault.name}

    def create_vault(self, path: str) -> dict:
        root = Path(os.path.expandvars(os.path.expanduser(path))).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._swap_vault(str(root))
        return {"vault": str(self.vault.root), "vaultName": self.vault.name}

    def open_external(self, url: str) -> dict:
        if not re.match(r"^https?://", url or "", re.IGNORECASE):
            raise ApiError("Only http(s) links can be opened")
        webbrowser.open(url)
        return {"ok": True}

    def reveal(self, path: str = "") -> dict:
        target = self.vault.resolve(path) if path else self.vault.root
        try:
            if sys.platform == "win32":
                if target.is_dir():
                    os.startfile(str(target))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["explorer", "/select,", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as error:
            raise ApiError(f"Could not open file manager: {error}") from error
        return {"ok": True}

    # ---------------------------------------------------------------- notes
    def tree(self) -> dict:
        return {"tree": self.vault.tree(), "vault": self.vault.name}

    def read_note(self, path: str) -> dict:
        note = self.vault.read(path)
        self.config["last_note"] = note["path"]
        save_config(self.config)
        return note

    def write_note(self, path: str, content: str) -> dict:
        return self.vault.write(path, content)

    def create_note(self, path: str, content: str = "") -> dict:
        created = self.vault.create_note(path, content)
        return self.vault.read(created)

    def create_folder(self, path: str) -> dict:
        return {"path": self.vault.create_folder(path)}

    def rename(self, path: str, name: str) -> dict:
        result = self.vault.rename(path, name)
        if self.config.get("last_note") == path:
            self.config["last_note"] = result["path"]
            save_config(self.config)
        return result

    def move_note(self, path: str, folder: str) -> dict:
        return self.vault.move(path, folder)

    def delete_note(self, path: str) -> dict:
        result = self.vault.delete(path)
        if self.config.get("last_note") == path:
            self.config["last_note"] = ""
            save_config(self.config)
        return result

    def note_titles(self) -> dict:
        index = self.vault.index()
        return {
            "notes": [
                {"path": path, "title": entry["title"]}
                for path, entry in sorted(
                    index.items(), key=lambda item: item[1]["title"].lower()
                )
            ]
        }

    def search(self, query: str, limit: int = 60) -> dict:
        return {"results": self.vault.search(query, int(limit or 60))}

    def links(self, path: str) -> dict:
        return self.vault.backlinks(path)

    def graph(self) -> dict:
        return self.vault.graph()

    def tags(self) -> dict:
        return {"tags": self.vault.tags()}

    def outline(self, content: str) -> dict:
        headings = []
        in_fence = False
        for line in (content or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence or not stripped.startswith("#"):
                continue
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if 1 <= level <= 6 and text:
                headings.append({"level": level, "text": text})
        return {"headings": headings}

    # ---------------------------------------------------------------- books
    def books_list(self) -> dict:
        return {"books": self.books.list_books()}

    def book_get(self, book_id: str) -> dict:
        return {"book": self.books.get_book(book_id)}

    def book_create(self, title: str, description: str = "", target_words: int = 50000, chapter_title: str = "Chapter One") -> dict:
        return {"book": self.books.create_book(title, description, target_words, chapter_title)}

    def book_update(self, book_id: str, patch: dict | None = None, **rest) -> dict:
        patch = dict(patch or {})
        patch.update(rest)
        return {"book": self.books.update_book(book_id, patch)}

    def book_delete(self, book_id: str) -> dict:
        return self.books.delete_book(book_id)

    def book_add_chapter(self, book_id: str, title: str) -> dict:
        return {"book": self.books.add_chapter(book_id, title)}

    def book_attach_chapter(self, book_id: str, path: str) -> dict:
        return {"book": self.books.attach_chapter(book_id, path)}

    def book_remove_chapter(self, book_id: str, path: str) -> dict:
        return {"book": self.books.remove_chapter(book_id, path)}

    def book_move_chapter(self, book_id: str, path: str, direction: int) -> dict:
        book = self.books.move_chapter(book_id, path, direction)
        return {"book": book, "renamed": self.books.last_renamed}

    def book_reorder(self, book_id: str, order: list[str]) -> dict:
        book = self.books.reorder(book_id, order)
        return {"book": book, "renamed": self.books.last_renamed}

    def book_manuscript(self, book_id: str) -> dict:
        return self.books.manuscript(book_id)

    def export_write(self, name: str, text: str) -> dict:
        """Save an export document into <vault>/Exports/."""
        safe = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "export"
        path = self.vault.write(f"Exports/{safe}", text)
        return {"path": path["path"], "absolute": str(self.vault.root / path["path"])}

    # --------------------------------------------------------------- library
    @property
    def library(self) -> Library:
        if self._library is None:
            roots = [root for root in (self.config.get("library") or []) if root]
            if not roots:
                roots = [str(DEFAULT_LIBRARY)]
                self.config["library"] = roots
            self._library = Library(roots)
        return self._library

    @property
    def news(self) -> News:
        if self._news is None or self._news.library is not self.library:
            self._news = News(self.library)
        return self._news

    @property
    def launcher(self) -> Launcher:
        if self._launcher is None:
            self._launcher = Launcher(self.server_url, config=self.config)
        return self._launcher

    def media_roots(self) -> list[Path]:
        """Folders ``/media`` may serve from. Nothing else is reachable."""
        roots: list[Path] = [root for root in self.library.roots]
        vault_root = self.config.get("vault")
        if vault_root and Path(vault_root).is_dir():
            roots.append(Path(vault_root).resolve())
        roots.append(DEFAULT_VAULT.resolve())
        roots.append(DEFAULT_LIBRARY.resolve())
        return roots

    def store_state(self) -> dict:
        return {
            "stats": self.library.stats(),
            "shelves": self.library.programs(),
            "tags": self.library.tag_counts(),
            "recent": self.library.recent(8),
            "continue": self.library.continue_listening(4),
            "flagsFields": list(FLAGS_FIELDS),
            "kinds": KIND_BY_EXT,
        }

    def store_search(self, query: str = "", kind: str = "", tag: str = "", flag: str = "", program: str | None = None, limit: int = 300) -> dict:
        """``program`` is the shelf folder: ``None`` = any shelf, ``""`` = loose files."""
        items = self.library.search(
            query, kind=kind or "", tag=tag or "", flag=flag or "", program=program, limit=int(limit or 300)
        )
        return {"items": items, "count": len(items)}

    def store_item(self, item_id: str) -> dict:
        item = self.library.item(item_id)
        item = dict(item)
        item["progress"] = self.library.progress_for(item_id)
        if item["kind"] in ("note", "document"):
            item["text"] = self.library.text(item["absolute"])
        siblings = [
            other for other in self.library.index()
            if other["program"] == item["program"] and other["id"] != item_id
        ][:12]
        item["siblings"] = siblings
        item["convertible"] = Path(item["absolute"]).suffix.lower() in SUPPORTED_EXTENSIONS
        item["pdf"] = str(Path(item["absolute"]).with_suffix(".pdf"))
        return {"item": item}

    def store_flags(self, item_id: str, patch: dict | None = None, **rest) -> dict:
        merged = dict(patch or {})
        merged.update(rest)
        return self.library.set_flags(item_id, merged)

    def store_toggle(self, item_id: str, flag: str) -> dict:
        return self.library.toggle_flag(item_id, flag)

    def store_import(self, paths=None, folder: str = "Imported", move: bool = False) -> dict:
        if isinstance(paths, str):
            paths = [paths]
        paths = list(paths or [])
        if not paths:
            raise ApiError("Choose at least one file or folder to import")
        return self.library.import_paths(paths, folder=folder or "Imported", move=bool(move))

    def store_import_pick(self, folder: str = "Imported", move: bool = False) -> dict:
        """Import a folder chosen in the native picker (desktop window only)."""
        chosen = self._ask_folder("Choose a folder to bring into the library")
        if not chosen:
            return {"cancelled": True}
        return self.library.import_paths([chosen], folder=folder or "Imported", move=bool(move))

    def store_export(self, item_id: str, folder: str = "") -> dict:
        destination = folder or self._ask_folder("Choose where to export this item")
        if not destination:
            return {"cancelled": True}
        return self.library.export_item(item_id, destination)

    def store_export_program(self, program: str, folder: str = "") -> dict:
        destination = folder or self._ask_folder("Choose where to export this program")
        if not destination:
            return {"cancelled": True}
        return self.library.export_folder(program, destination)

    def store_delete(self, item_id: str) -> dict:
        return self.library.delete(item_id)

    def store_roots(self) -> dict:
        return {"roots": [{"path": str(root), "name": root.name, "exists": root.is_dir()} for root in self.library.roots]}

    def store_add_root(self, path: str = "") -> dict:
        chosen = path or self._ask_folder("Choose a folder to add to the library")
        if not chosen:
            return {"cancelled": True}
        self.library.add_root(chosen, create=False)
        self.config["library"] = [str(root) for root in self.library.roots]
        save_config(self.config)
        self.library.index(refresh=True)
        return self.store_roots()

    def store_remove_root(self, path: str) -> dict:
        target = Path(str(path)).resolve()
        if len(self.library.roots) <= 1:
            raise ApiError("Keep at least one library folder")
        if target not in self.library.roots:
            raise ApiError(f"That folder is not part of the library: {target}")
        self.library.remove_root(path)
        self.config["library"] = [str(root) for root in self.library.roots]
        save_config(self.config)
        self.library.index(refresh=True)
        return self.store_roots()

    def store_reveal(self, item_id: str) -> dict:
        item = self.library.item(item_id)
        return self._reveal_path(Path(item["absolute"]))

    def reveal_path(self, path: str = "") -> dict:
        """Reveal one of JADELY's own folders (library, vault, app) in the file manager."""
        target = Path(str(path)).resolve()
        allowed = [*self.media_roots(), APP_DIR.resolve()]
        if not any(target == root or root in target.parents for root in allowed):
            raise ApiError("That folder is outside JADELY's own folders")
        if not target.exists():
            raise ApiError(f"Not found: {target}")
        return self._reveal_path(target)

    def store_progress(self, item_id: str, position: float | None = None, duration: float | None = None, played: bool | None = None) -> dict:
        entry = self.library.set_progress(item_id, position=position, duration=duration, played=played)
        return {"progress": entry}

    # ------------------------------------------------------------- converting
    def convert_engine(self) -> dict:
        browser = find_browser()
        return {
            "engine": self.config.get("convert_engine") or "auto",
            "browser": str(browser or ""),
            "browserName": browser.name if browser else "",
            "resolved": "edge" if browser else "stdlib",
            "extensions": sorted(SUPPORTED_EXTENSIONS),
        }

    def convert_item(self, item_id: str, engine: str = "") -> dict:
        item = self.library.item(item_id)
        source = Path(item["absolute"])
        if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ApiError(f"{item['name']} cannot be converted to PDF")
        try:
            result = convert_file(source, source.with_suffix(".pdf"), engine=engine or self.config.get("convert_engine") or "auto")
        except ConvertError as error:
            raise ApiError(str(error)) from error
        self.library.index(refresh=True)
        result["item"] = item["name"]
        result["pdfItem"] = self._find_item_for(Path(result["pdf"]))
        return result

    def convert_batch(self, program: str = "", engine: str = "") -> dict:
        sources = [
            Path(item["absolute"])
            for item in self.library.index()
            if Path(item["absolute"]).suffix.lower() in MIGRATABLE_EXTENSIONS
            and (not program or item["program"] == program)
        ]
        if not sources:
            raise ApiError("Nothing in this selection can be converted")
        report = migrate(
            [str(path) for path in sources],
            engine=engine or self.config.get("convert_engine") or "auto",
            overwrite=False,
        )
        self.library.index(refresh=True)
        report["program"] = program
        return report

    def _find_item_for(self, path: Path) -> dict | None:
        try:
            return self.library.item(self.library.item_id(path))
        except LibraryError:
            return None

    # ------------------------------------------------------------------ news
    def news_feed(self, include_hidden: bool = False) -> dict:
        return self.news.feed(include_hidden=bool(include_hidden))

    def news_program(self, program: str) -> dict:
        return self.news.program(program)

    def news_segment(self, program: str, segment: str) -> dict:
        return self.news.segment(program, segment)

    def news_speech(self, program: str, segment: str) -> dict:
        return self.news.segment_speech(program, segment)

    def news_progress(self, segment: str, position: float | None = None, duration: float | None = None, played: bool | None = None) -> dict:
        return self.news.save_progress(segment, position=position, duration=duration, played=played)

    def news_played(self, segment: str, played: bool = True) -> dict:
        return self.news.mark_played(segment, played=bool(played))

    def news_flags(self, program: str, patch: dict | None = None, **rest) -> dict:
        merged = dict(patch or {})
        merged.update(rest)
        return self.news.set_program_flags(program, merged)

    def news_toggle(self, program: str, flag: str) -> dict:
        return self.news.toggle_program_flag(program, flag)

    def news_search(self, query: str, limit: int = 60) -> dict:
        return self.news.search(query, limit=int(limit or 60))

    # -------------------------------------------------------------- launcher
    def launcher_state(self) -> dict:
        state = self.launcher.status()
        state["app"] = self.app_id or "launcher"
        state["version"] = VERSION
        state["library"] = self.library.stats()
        state["paths"] = {
            "app": str(APP_DIR),
            "library": str(self.library.root or DEFAULT_LIBRARY),
            "vault": self.config.get("vault") or str(DEFAULT_VAULT),
        }
        return state

    def launcher_start(self, app: str, force: bool = False) -> dict:
        return self.launcher.start(app, force=bool(force))

    def launcher_stop(self, app: str) -> dict:
        return self.launcher.stop(app)

    def launcher_stop_all(self) -> dict:
        return {"results": self.launcher.stop_all()}

    def launcher_open(self, app: str) -> dict:
        target = self.launcher.get(app)
        if not target.get("page"):
            raise ApiError(f"{target['name']} is not a web app")
        url = (self.server_url or "") + target["page"]
        if not self.server_url:
            raise ApiError("No local server to open")
        webbrowser.open(url)
        return {"url": url}

    def launcher_cli(self, app: str, action: str = "start") -> dict:
        """Build the command line the launcher uses, for display/debugging."""
        target = self.launcher.get(app)
        command, cwd = self.launcher.command_for(target, url=self.server_url)
        return {"app": app, "action": action, "command": command, "cwd": str(cwd)}

    # ------------------------------------------------------------ app shell
    def app_state(self) -> dict:
        """Everything a page needs to draw itself on first paint."""
        return {
            "app": self.app_id or "notes",
            "version": VERSION,
            "server": self.server_url,
            "library": self.library.stats(),
            "convert": self.convert_engine(),
            "flagsFields": list(FLAGS_FIELDS),
        }

    # ------------------------------------------------------------ app help
    def _ask_folder(self, title: str = "") -> str:
        """The native folder picker, or an empty string when there is no window."""
        if not self.pick_folder:
            return ""
        try:
            chosen = self.pick_folder(title)
        except TypeError:
            chosen = self.pick_folder()
        if not chosen:
            return ""
        return str(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)

    def _reveal_path(self, target: Path) -> dict:
        try:
            if sys.platform == "win32":
                if target.is_dir():
                    os.startfile(str(target))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["explorer", "/select,", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as error:
            raise ApiError(f"Could not open the file manager: {error}") from error
        return {"ok": True, "path": str(target)}

    # ------------------------------------------------------------- dispatch
    METHODS = {
        "state": ("",),
        "save_prefs": ("prefs",),
        "pick_vault": (),
        "open_vault": ("path",),
        "create_vault": ("path",),
        "reveal": ("path",),
        "open_external": ("url",),
        "tree": (),
        "read_note": ("path",),
        "write_note": ("path", "content"),
        "create_note": ("path", "content"),
        "create_folder": ("path",),
        "rename": ("path", "name"),
        "move_note": ("path", "folder"),
        "delete_note": ("path",),
        "note_titles": (),
        "search": ("query", "limit"),
        "links": ("path",),
        "graph": (),
        "tags": (),
        "outline": ("content",),
        "books_list": (),
        "book_get": ("book_id",),
        "book_create": ("title", "description", "target_words", "chapter_title"),
        "book_update": ("book_id", "patch"),
        "book_delete": ("book_id",),
        "book_add_chapter": ("book_id", "title"),
        "book_attach_chapter": ("book_id", "path"),
        "book_remove_chapter": ("book_id", "path"),
        "book_move_chapter": ("book_id", "path", "direction"),
        "book_reorder": ("book_id", "order"),
        "book_manuscript": ("book_id",),
        "export_write": ("name", "text"),
        # ------------------------------------------------------------ library
        "store_state": (),
        "store_search": ("query", "kind", "tag", "flag", "program", "limit"),
        "store_item": ("item_id",),
        "store_flags": ("item_id", "patch"),
        "store_toggle": ("item_id", "flag"),
        "store_import": ("paths", "folder", "move"),
        "store_import_pick": ("folder", "move"),
        "store_export": ("item_id", "folder"),
        "store_export_program": ("program", "folder"),
        "store_delete": ("item_id",),
        "store_roots": (),
        "store_add_root": ("path",),
        "store_remove_root": ("path",),
        "store_reveal": ("item_id",),
        "reveal_path": ("path",),
        "store_progress": ("item_id", "position", "duration", "played"),
        # ----------------------------------------------------------- converting
        "convert_engine": (),
        "convert_item": ("item_id", "engine"),
        "convert_batch": ("program", "engine"),
        # ----------------------------------------------------------------- news
        "news_feed": ("include_hidden",),
        "news_program": ("program",),
        "news_segment": ("program", "segment"),
        "news_speech": ("program", "segment"),
        "news_progress": ("segment", "position", "duration", "played"),
        "news_played": ("segment", "played"),
        "news_flags": ("program", "patch"),
        "news_toggle": ("program", "flag"),
        "news_search": ("query", "limit"),
        # ------------------------------------------------------------- launcher
        "launcher_state": (),
        "launcher_start": ("app", "force"),
        "launcher_stop": ("app",),
        "launcher_stop_all": (),
        "launcher_open": ("app",),
        "launcher_cli": ("app", "action"),
        "app_state": (),
    }

    @staticmethod
    def _normalize(payload: dict) -> dict:
        """Accept both bookId and book_id style keys from the UI."""
        normalized = {}
        for key, value in payload.items():
            snake = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).lower()
            normalized[snake] = value
        return normalized

    def call(self, method: str, payload: dict | None = None) -> dict:
        payload = self._normalize(payload or {})
        if method not in self.METHODS:
            return {"ok": False, "error": f"Unknown method: {method}"}
        function = getattr(self, method)
        try:
            result = function(**payload)
            return {"ok": True, "data": result if result is not None else {}}
        except VaultError as error:
            return {"ok": False, "error": str(error), "kind": "vault"}
        except LibraryError as error:
            return {"ok": False, "error": str(error), "kind": "library"}
        except NewsError as error:
            return {"ok": False, "error": str(error), "kind": "news"}
        except LauncherError as error:
            return {"ok": False, "error": str(error), "kind": "launcher"}
        except ConvertError as error:
            return {"ok": False, "error": str(error), "kind": "convert"}
        except ApiError as error:
            return {"ok": False, "error": str(error), "kind": "api"}
        except TypeError as error:
            return {"ok": False, "error": f"Bad arguments: {error}", "kind": "args"}
        except Exception as error:  # noqa: BLE001 - the UI shows the message
            return {"ok": False, "error": f"{type(error).__name__}: {error}", "kind": "unexpected"}
