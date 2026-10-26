"""The library: indexing, flag files, search, progress, import and export.

Run: python tests/test_library.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import make_library  # noqa: E402
from jadeli.library import (  # noqa: E402
    Library,
    LibraryError,
    audio_info,
    flags_path,
    read_flags,
    write_flags,
)


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="jadely-library-"))
        self.root = make_library(self.work / "library")
        self.library = Library([str(self.root)])

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    # ------------------------------------------------------------------ index
    def test_index_kinds_and_titles(self) -> None:
        items = self.library.index()
        self.assertEqual(len(items), 11)
        kinds = self.library.stats()["kinds"]
        self.assertEqual(kinds, {"note": 6, "audio": 3, "image": 1, "pdf": 1})

        lantern = next(item for item in items if item["name"] == "01 - The Lantern Line.md")
        self.assertEqual(lantern["kind"], "note")
        self.assertEqual(lantern["title"], "The Lantern Line")  # from the h1, not the file name
        self.assertEqual(lantern["program"], "The Reach Report")
        self.assertGreater(lantern["words"], 20)
        self.assertIn("broadcast", lantern["tags"])  # #broadcast in the body
        self.assertTrue(lantern["url"].startswith("/media?path="))

        loose = next(item for item in items if item["name"] == "A loose note.md")
        self.assertEqual(loose["program"], "")
        self.assertEqual(loose["title"], "A loose note")

    def test_audio_durations_are_read_from_the_files(self) -> None:
        wav = next(item for item in self.library.index() if item["ext"] == "wav")
        self.assertAlmostEqual(wav["duration"], 1.0, places=2)
        self.assertEqual(wav["durationLabel"], "0:01")

        mp3 = next(item for item in self.library.index() if item["name"].endswith("Ident.mp3"))
        self.assertAlmostEqual(mp3["duration"], 0.13, places=2)
        self.assertEqual(audio_info(self.root / "no-such-file.mp3")["duration"], None)

    def test_cover_is_not_loose_content(self) -> None:
        names = [item["name"] for item in self.library.search()]
        self.assertNotIn("cover.png", names)
        covers = self.library.search(kind="image")
        self.assertEqual([item["name"] for item in covers], ["cover.png"])
        self.assertTrue(covers[0]["isCover"])
        # A cover also becomes the program's artwork.
        report = next(shelf for shelf in self.library.programs() if shelf["title"] == "The Reach Report")
        self.assertTrue(report["cover"])

    # ------------------------------------------------------------------ flags
    def test_flag_files_round_trip(self) -> None:
        path = self.root / "Emberwatch Notebook" / "01 - The Assessor's Ledger.md"
        flags = read_flags(path)
        self.assertTrue(flags["played"])
        self.assertFalse(flags["favorite"])
        self.assertEqual(read_flags(path)["tags"], [])

        write_flags(path, {"favorite": True, "tags": ["#notebook", "ledger"], "note": "re-read this"})
        stored = json.loads(flags_path(path).read_text(encoding="utf-8"))
        self.assertTrue(stored["favorite"])
        self.assertEqual(stored["tags"], ["notebook", "ledger"])  # the # is stripped
        self.assertEqual(stored["note"], "re-read this")
        self.assertFalse(stored["downloaded"])
        for field in ("favorite", "played", "pinned", "downloaded"):
            self.assertIsInstance(stored[field], bool)
            self.assertNotIn(None, [stored[field]])

    def test_flag_defaults_without_a_sidecar(self) -> None:
        path = self.root / "A loose note.md"
        self.assertFalse(flags_path(path).exists())
        flags = read_flags(path)
        self.assertEqual(flags["favorite"], False)
        self.assertEqual(flags["tags"], [])

    def test_toggle_through_the_api_and_cache_invalidation(self) -> None:
        item = next(entry for entry in self.library.index() if entry["name"] == "A loose note.md")
        result = self.library.toggle_flag(item["id"], "favorite")
        self.assertTrue(result["value"])
        self.assertTrue(self.library.item(item["id"])["flags"]["favorite"])

        # Editing the flag file by hand (as the docs invite) must be picked up
        # without a restart: the sidecar's timestamp is part of the cache key.
        time.sleep(1.05)
        write_flags(self.root / "A loose note.md", {"favorite": False, "pinned": True})
        refreshed = self.library.item(item["id"])
        self.assertFalse(refreshed["flags"]["favorite"])
        self.assertTrue(refreshed["flags"]["pinned"])

    def test_toggle_refuses_unknown_flags(self) -> None:
        item = self.library.index()[0]
        with self.assertRaises(LibraryError):
            self.library.toggle_flag(item["id"], "note")
        with self.assertRaises(LibraryError):
            self.library.toggle_flag(item["id"], "smuggled")

    def test_set_flags_accepts_a_tag_string(self) -> None:
        item = next(entry for entry in self.library.index() if entry["ext"] == "wav")
        saved = self.library.set_flags(item["id"], {"tags": "one, two"})["flags"]
        self.assertEqual(saved["tags"], ["one", "two"])

    # ----------------------------------------------------------------- search
    def test_search_ranking_and_filters(self) -> None:
        # A title match beats a body-only match, and the script and its audio both
        # count as "The Lantern Line".
        hits = self.library.search("lantern")
        self.assertIn("The Lantern Line", [item["title"] for item in hits])
        self.assertIn("01 - The Lantern Line", [item["title"] for item in hits])

        body_hit = self.library.search("counted")  # only in The Assessor's Ledger body
        self.assertEqual([item["title"] for item in body_hit], ["The Assessor's Ledger"])

        self.assertEqual(len(self.library.search(kind="audio")), 3)
        self.assertEqual([item["name"] for item in self.library.search(tag="broadcast")], ["01 - The Lantern Line.md"])
        self.assertEqual(self.library.search(flag="favorite"), [])
        self.assertEqual(self.library.search(query="nothing-matches-this"), [])
        self.assertEqual(self.library.search(program="Emberwatch Notebook")[0]["title"], "The Assessor's Ledger")
        # None means every shelf; "" means only the loose files at the root.
        self.assertEqual(len(self.library.search(program=None)), 10)  # 11 minus the cover
        self.assertEqual(len(self.library.search(program=None, covers=True)), 11)
        self.assertEqual([item["name"] for item in self.library.search(program="")], ["A loose note.md"])

    def test_tag_counts(self) -> None:
        counts = {entry["tag"]: entry["count"] for entry in self.library.tag_counts()}
        self.assertEqual(counts.get("broadcast"), 1)

    def test_programs_carry_their_own_flags(self) -> None:
        shelves = {shelf["title"]: shelf for shelf in self.library.programs()}
        self.assertEqual(
            set(shelves), {"The Reach Report", "Emberwatch Notebook", "Reference", "Loose files"}
        )
        self.assertEqual(shelves["Loose files"]["folder"], "")
        report = shelves["The Reach Report"]
        self.assertTrue(report["favorite"])
        self.assertEqual(report["tags"], ["broadcast"])
        self.assertEqual(report["items"], 8)
        self.assertAlmostEqual(report["seconds"], 1.39, places=1)
        self.assertEqual(report["durationLabel"], "0:01")
        self.assertFalse(shelves["Emberwatch Notebook"]["favorite"])

    # --------------------------------------------------------------- progress
    def test_progress_and_continue_listening(self) -> None:
        wav = next(entry for entry in self.library.index() if entry["ext"] == "wav")
        self.library.set_progress(wav["id"], position=0.4, duration=1.0)
        entry = self.library.progress_for(wav["id"])
        self.assertEqual(entry["position"], 0.4)

        continuing = self.library.continue_listening()
        self.assertEqual([item["name"] for item in continuing], [wav["name"]])
        self.assertEqual(continuing[0]["percent"], 40.0)
        self.assertEqual(continuing[0]["positionLabel"], "0:00")

        self.library.set_progress(wav["id"], played=True)
        self.assertEqual(self.library.progress_for(wav["id"])["count"], 1)

        self.assertEqual([item["name"] for item in self.library.recent(3)], [wav["name"]])

    def test_state_file_lives_in_the_library(self) -> None:
        wav = next(entry for entry in self.library.index() if entry["ext"] == "wav")
        self.library.set_progress(wav["id"], position=0.2, duration=1.0)
        state = json.loads((self.root / ".jadely" / "state.json").read_text(encoding="utf-8"))
        self.assertIn("progress", state)
        # Playback state is machine state, so it is not inside any flag file.
        self.assertNotIn("position", read_flags(self.root / wav["name"]))

    # ---------------------------------------------------------- import/export
    def test_import_copies_and_skips(self) -> None:
        outside = self.work / "outside"
        outside.mkdir()
        (outside / "New episode.md").write_text("# New episode\n\nfresh\n", encoding="utf-8")
        (outside / "ignore.bin").write_bytes(b"binary")

        report = self.library.import_paths([str(outside)], folder="Imported")
        targets = [Path(entry["target"]).name for entry in report["imported"]]
        self.assertEqual(targets, ["New episode.md"])
        self.assertEqual([Path(entry["source"]).name for entry in report["skipped"]], ["ignore.bin"])
        self.assertTrue((self.root / "Imported" / "New episode.md").is_file())

        # Importing the same outside file twice never overwrites: the second copy
        # gets a timestamp in its name.
        again = self.library.import_paths([str(outside / "New episode.md")], folder="Imported")
        self.assertEqual(len(again["imported"]), 1)
        self.assertNotEqual(Path(again["imported"][0]["target"]).name, "New episode.md")
        self.assertEqual(len(list((self.root / "Imported").glob("New episode*.md"))), 2)

        # A file that already belongs to the library is left where it is.
        already = self.library.import_paths([str(self.root / "A loose note.md")], folder="Imported")
        self.assertEqual(already["imported"], [])
        self.assertEqual(already["skipped"][0]["reason"], "already in the library")

    def test_import_can_move(self) -> None:
        outside = self.work / "to-move.md"
        outside.write_text("# Moved\n\nbody\n", encoding="utf-8")
        self.library.import_paths([str(outside)], folder="Imported", move=True)
        self.assertFalse(outside.exists())
        self.assertTrue((self.root / "Imported" / "to-move.md").is_file())

    def test_export_item_and_program(self) -> None:
        item = next(entry for entry in self.library.index() if entry["name"].startswith("01 - The Lantern Line.md"))
        self.library.set_flags(item["id"], {"favorite": True})
        destination = self.work / "out"
        result = self.library.export_item(item["id"], destination)
        self.assertTrue(Path(result["exported"]).is_file())
        # The flag file travels with the item so its state is not lost.
        self.assertTrue(flags_path(Path(result["exported"])).is_file())
        self.assertTrue(read_flags(Path(result["exported"]))["favorite"])

        program = self.library.export_folder("Emberwatch Notebook", self.work / "program-out")
        self.assertEqual(program["exported"], 1)
        self.assertTrue((self.work / "program-out" / "Emberwatch Notebook" / "01 - The Assessor's Ledger.md").is_file())
        with self.assertRaises(LibraryError):
            self.library.export_folder("Nothing here", self.work / "void")

    def test_delete_moves_to_trash(self) -> None:
        item = next(entry for entry in self.library.index() if entry["name"] == "A loose note.md")
        result = self.library.delete(item["id"])
        self.assertFalse((self.root / "A loose note.md").exists())
        self.assertTrue(Path(result["movedTo"]).is_file())
        self.assertIn(".jadely", result["movedTo"])
        self.assertNotIn("A loose note.md", [entry["name"] for entry in self.library.index()])

    def test_delete_refuses_outside_the_library(self) -> None:
        outside = self.work / "keep-me.md"
        outside.write_text("# Keep\n", encoding="utf-8")
        with self.assertRaises(LibraryError):
            self.library.delete(str(outside))

    # ------------------------------------------------------------------ roots
    def test_roots_and_resolution(self) -> None:
        second = self.work / "second"
        second.mkdir()
        (second / "Extra.md").write_text("# Extra\n\nmore\n", encoding="utf-8")
        self.library.add_root(str(second))
        self.assertEqual(len(self.library.roots), 2)
        self.assertIn("Extra", [entry["title"] for entry in self.library.index()])

        self.library.remove_root(str(second))
        self.assertEqual(len(self.library.roots), 1)
        with self.assertRaises(LibraryError):
            self.library.add_root(str(self.work / "does-not-exist"))

        with self.assertRaises(LibraryError):
            self.library.item("not-an-id")
        with self.assertRaises(LibraryError):
            self.library.resolve("not-an-id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
