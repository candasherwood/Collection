"""Backend tests for jadeli. Run: python tests/test_backend.py"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jadeli.config as config_module  # noqa: E402
from jadeli.api import Api  # noqa: E402
from jadeli.books import Books  # noqa: E402
from jadeli.config import DEFAULTS  # noqa: E402
from jadeli.server import start_server  # noqa: E402
from jadeli.vault import Vault, VaultError, parse_links, parse_tags  # noqa: E402


class VaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jadeli-test-"))
        self.vault = Vault(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_read_write(self) -> None:
        path = self.vault.create_note("notes/First note.md", "# First note\n\nhello\n")
        self.assertEqual(path, "notes/First note.md")
        note = self.vault.read(path)
        self.assertEqual(note["title"], "First note")
        self.assertIn("hello", note["content"])

        self.vault.write(path, "# Renamed heading\n\nnew body\n")
        self.assertEqual(self.vault.read(path)["title"], "Renamed heading")

    def test_duplicate_names_are_made_unique(self) -> None:
        first = self.vault.create_note("Idea.md", "one")
        second = self.vault.create_note("Idea.md", "two")
        self.assertEqual(first, "Idea.md")
        self.assertEqual(second, "Idea 2.md")

    def test_traversal_is_refused(self) -> None:
        with self.assertRaises(VaultError):
            self.vault.read("../../secrets.md")
        with self.assertRaises(VaultError):
            self.vault.write("C:/Windows/System32/x.md", "nope")
        with self.assertRaises(VaultError):
            self.vault.resolve("/etc/passwd")

    def test_delete_goes_to_trash(self) -> None:
        self.vault.create_note("Throwaway.md", "bye")
        result = self.vault.delete("Throwaway.md")
        self.assertFalse((self.root / "Throwaway.md").exists())
        self.assertTrue(result["trashed"].startswith(".jadeli/trash/"))
        self.assertTrue((self.root / result["trashed"]).exists())

    def test_tree_hides_internal_folders(self) -> None:
        self.vault.create_note("visible.md", "hi")
        (self.root / ".jadeli").mkdir(exist_ok=True)
        (self.root / ".jadeli" / "secret.md").write_text("hidden", encoding="utf-8")
        (self.root / ".git").mkdir(exist_ok=True)
        (self.root / ".git" / "config.md").write_text("hidden", encoding="utf-8")
        names = [node["name"] for node in self.vault.tree()]
        self.assertIn("visible.md", names)
        self.assertNotIn(".jadeli", names)
        self.assertNotIn(".git", names)

    def test_rename_keeps_extension(self) -> None:
        self.vault.create_note("Old.md", "x")
        result = self.vault.rename("Old.md", "New name")
        self.assertEqual(result["path"], "New name.md")


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jadeli-test-"))
        self.vault = Vault(self.root)
        self.vault.create_note("Alpha.md", "# Alpha\n\nLinks to [[Beta]] and [[Missing]] #tag/one\n")
        self.vault.create_note("Beta.md", "# Beta\n\nBack to [[Alpha|the start]] #tag/two\n")
        self.vault.create_note("folder/Gamma.md", "# Gamma\n\nA separate note with the word lighthouse.\n")
        self.vault.create_note("Code.md", "# Code\n\n```python\n[[Not a link]] #notatag\n```\n#real\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_links_and_tags(self) -> None:
        self.assertEqual(parse_links("a [[X]] b [[X|alias]] c [[Y#head]]"), ["X", "Y"])
        self.assertEqual(parse_tags("#one #two/three plain #not"), ["one", "two/three", "not"])

    def test_code_blocks_are_ignored(self) -> None:
        index = self.vault.index()
        self.assertEqual(index["Code.md"]["links"], [])
        self.assertEqual(index["Code.md"]["tags"], ["real"])

    def test_backlinks(self) -> None:
        data = self.vault.backlinks("Beta.md")
        self.assertEqual([item["path"] for item in data["backlinks"]], ["Alpha.md"])
        self.assertEqual([link["path"] for link in data["links"]], ["Alpha.md"])

        alpha = self.vault.backlinks("Alpha.md")
        self.assertTrue(
            any(link["target"] == "Missing" and not link["exists"] for link in alpha["links"])
        )

    def test_search_ranks_titles(self) -> None:
        results = self.vault.search("gamma")
        self.assertEqual(results[0]["path"], "folder/Gamma.md")
        self.assertTrue(self.vault.search("lighthouse"))
        self.assertEqual(self.vault.search("zzzz-nothing"), [])

    def test_numbered_chapters_resolve_by_title(self) -> None:
        self.vault.create_note("Book/01 - Chapter One.md", "# Chapter One\n\nopening\n")
        self.vault.create_note("Notes/Plan.md", "# Plan\n\nchapter [[Chapter One]]\n")
        data = self.vault.backlinks("Book/01 - Chapter One.md")
        self.assertEqual([item["path"] for item in data["backlinks"]], ["Notes/Plan.md"])

    def test_graph_has_unique_edges(self) -> None:
        graph = self.vault.graph()
        pairs = {tuple(sorted((edge["source"], edge["target"]))) for edge in graph["edges"]}
        self.assertEqual(len(pairs), len(graph["edges"]))
        self.assertIn(("Alpha.md", "Beta.md"), pairs)
        self.assertEqual(len(graph["nodes"]), 4)

    def test_exports_are_not_indexed(self) -> None:
        self.vault.create_note("Exports/Book.md", "# Book\n\n[[Alpha]] #copied\n")
        self.assertNotIn("Exports/Book.md", self.vault.index())
        self.assertEqual(self.vault.search("copied"), [])
        self.assertNotIn("copied", [tag["tag"] for tag in self.vault.tags()])
        # but the file stays visible in the tree and can still be opened
        self.assertTrue((self.root / "Exports" / "Book.md").exists())
        self.assertEqual(self.vault.read("Exports/Book.md")["title"], "Book")

    def test_tags_counts(self) -> None:
        tags = {tag["tag"]: tag["count"] for tag in self.vault.tags()}
        self.assertEqual(tags["tag/one"], 1)
        self.assertEqual(tags["real"], 1)
        self.assertNotIn("notatag", tags)


class BookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jadeli-test-"))
        self.vault = Vault(self.root)
        self.books = Books(self.vault)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_book_makes_first_chapter(self) -> None:
        book = self.books.create_book("My Novel", "About lighthouses", 20000)
        self.assertEqual(book["title"], "My Novel")
        self.assertEqual(book["chapter_count"], 1)
        self.assertTrue((self.root / book["chapters"][0]["path"]).exists())
        self.assertEqual(book["target_words"], 20000)

    def test_word_counts_and_progress(self) -> None:
        book = self.books.create_book("Words", "", 100)
        path = book["chapters"][0]["path"]
        self.vault.write(path, "# Chapter One\n\n" + "word " * 25)
        refreshed = self.books.get_book(book["id"])
        self.assertEqual(refreshed["words"], 28)  # "# Chapter One" (3) + 25 words
        self.assertEqual(refreshed["progress"], 28)

    def test_add_move_and_renumber(self) -> None:
        book = self.books.create_book("Reorder", "", 1000, "Chapter One")
        self.books.add_chapter(book["id"], "Chapter Two")
        book = self.books.get_book(book["id"])
        self.assertEqual(book["chapter_count"], 2)
        first, second = book["chapters"][0]["path"], book["chapters"][1]["path"]
        self.assertTrue(first.startswith("Books/Reorder/01 - "))
        self.assertTrue(second.startswith("Books/Reorder/02 - "))

        book = self.books.move_chapter(book["id"], second, -1)
        paths = [chapter["path"] for chapter in book["chapters"]]
        self.assertTrue(paths[0].startswith("Books/Reorder/01 - Chapter Two"))
        self.assertTrue(paths[1].startswith("Books/Reorder/02 - Chapter One"))
        # files on disk follow the order and keep their names
        self.assertTrue((self.root / paths[0]).exists())
        self.assertTrue((self.root / paths[1]).exists())

    def test_move_reports_renamed_paths(self) -> None:
        book = self.books.create_book("Map", "", 100, "One")
        self.books.add_chapter(book["id"], "Two")
        book = self.books.get_book(book["id"])
        second = book["chapters"][1]["path"]
        self.books.move_chapter(book["id"], second, -1)
        renamed = self.books.last_renamed
        self.assertIn(second, renamed)
        self.assertTrue(renamed[second].startswith("Books/Map/01 - Two"))
        self.assertTrue((self.root / renamed[second]).exists())

    def test_remove_chapter_keeps_file(self) -> None:
        book = self.books.create_book("Trim", "", 500)
        path = book["chapters"][0]["path"]
        updated = self.books.remove_chapter(book["id"], path)
        self.assertEqual(updated["chapter_count"], 0)
        self.assertTrue((self.root / path).exists())

    def test_attach_existing_note(self) -> None:
        book = self.books.create_book("Attach", "", 500)
        self.vault.create_note("Loose idea.md", "# Loose idea\n\nSomething.\n")
        updated = self.books.attach_chapter(book["id"], "Loose idea.md")
        self.assertEqual(updated["chapter_count"], 2)
        with self.assertRaises(VaultError):
            self.books.attach_chapter(book["id"], "Loose idea.md")

    def test_manuscript_order(self) -> None:
        book = self.books.create_book("Order", "desc", 100, "One")
        self.books.add_chapter(book["id"], "Two")
        manuscript = self.books.manuscript(book["id"])
        titles = [chapter["title"] for chapter in manuscript["chapters"]]
        self.assertEqual(titles, ["One", "Two"])
        self.assertEqual(manuscript["book"]["title"], "Order")

    def test_books_persist_across_instances(self) -> None:
        book = self.books.create_book("Persist", "", 100)
        again = Books(Vault(self.root))
        self.assertEqual([item["id"] for item in again.list_books()], [book["id"]])

    def test_book_folder_can_live_outside_books(self) -> None:
        """A stored folder lets a book live anywhere in the vault."""
        book = self.books.create_book("Lantern", "", 500, "One")
        folder = "The Lantern's Edge"
        self.vault.create_folder(folder)
        source = self.root / book["chapters"][0]["path"]
        moved = self.root / folder / source.name
        source.rename(moved)

        store = json.loads(self.books.store_path.read_text(encoding="utf-8"))
        store["books"][0]["folder"] = folder
        store["books"][0]["chapters"] = [{"path": f"{folder}/{source.name}", "synopsis": ""}]
        self.books.store_path.write_text(json.dumps(store), encoding="utf-8")

        book = self.books.add_chapter(book["id"], "Two")
        self.assertEqual(book["chapter_count"], 2)
        self.assertFalse(book["chapters"][0]["missing"])
        self.assertTrue(book["chapters"][1]["path"].startswith(f"{folder}/02 - Two"))
        self.assertTrue((self.root / book["chapters"][1]["path"]).exists())


class ApiAndServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jadeli-api-"))
        # never let the tests touch the real config.json next to app.py
        self._original_config_path = config_module.CONFIG_PATH
        config_module.CONFIG_PATH = self.root / "config.json"
        config = dict(DEFAULTS)
        config["vault"] = str(self.root)
        self.api = Api(config)

    def tearDown(self) -> None:
        config_module.CONFIG_PATH = self._original_config_path
        shutil.rmtree(self.root, ignore_errors=True)

    def test_unknown_method(self) -> None:
        result = self.api.call("nope")
        self.assertFalse(result["ok"])

    def test_state_and_notes(self) -> None:
        created = self.api.call("create_note", {"path": "Hello.md", "content": "# Hello\n\nworld\n"})
        self.assertTrue(created["ok"])
        read = self.api.call("read_note", {"path": "Hello.md"})
        self.assertEqual(read["data"]["title"], "Hello")
        tree = self.api.call("tree")["data"]["tree"]
        self.assertEqual([node["path"] for node in tree], ["Hello.md"])

    def test_bad_arguments_are_reported(self) -> None:
        result = self.api.call("read_note", {})
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_export_write(self) -> None:
        result = self.api.call("export_write", {"name": "book.html", "text": "<h1>hi</h1>"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["path"], "Exports/book.html")
        self.assertTrue((self.root / "Exports" / "book.html").exists())

    def test_http_endpoints(self) -> None:
        server, port = start_server(self.api)
        try:
            base = f"http://127.0.0.1:{port}"

            with urllib.request.urlopen(f"{base}/healthz", timeout=5) as response:
                self.assertEqual(json.load(response)["app"], "jadeli")

            request = urllib.request.Request(
                f"{base}/api/create_note",
                data=json.dumps({"path": "Http.md", "content": "# Via HTTP\n"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.load(response)
            self.assertTrue(payload["ok"])
            self.assertTrue((self.root / "Http.md").exists())

            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"{base}/api/state", timeout=5)
            self.assertEqual(caught.exception.code, 405)

            with urllib.request.urlopen(f"{base}/index.html", timeout=5) as response:
                self.assertIn(b"jadeli", response.read())
                self.assertTrue(response.headers["Content-Type"].startswith("text/html"))
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
