"""The news portal: programs, segments, playback state, flags and search.

Run: python tests/test_news.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import make_library  # noqa: E402
from jadeli.library import Library  # noqa: E402
from jadeli.news import News, NewsError, program_id_for  # noqa: E402


class NewsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="jadely-news-"))
        self.root = make_library(self.work / "library")
        self.library = Library([str(self.root)])
        self.news = News(self.library)

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    # ------------------------------------------------------------------- feed
    def test_feed_lists_programs_and_hides_marked_shelves(self) -> None:
        feed = self.news.feed()
        titles = [program["title"] for program in feed["programs"]]
        self.assertEqual(set(titles), {"The Reach Report", "Emberwatch Notebook", "Loose files"})
        self.assertEqual(feed["hidden"], [])
        self.assertEqual(feed["continue"], [])
        self.assertEqual(feed["stats"]["items"], 11)

        with_hidden = self.news.feed(include_hidden=True)
        self.assertEqual([program["title"] for program in with_hidden["hidden"]], ["Reference"])

    def test_program_metadata_and_counts(self) -> None:
        program = self.news.program("The Reach Report")["program"]
        self.assertEqual(program["id"], program_id_for("The Reach Report"))
        self.assertEqual(program["title"], "The Reach Report")
        self.assertEqual(program["author"], "The Emberwatch")
        self.assertEqual(program["narrator"], "Wren of the Emberwatch")
        self.assertEqual(program["description"], "A nightly bulletin from the Reach.")
        self.assertEqual(program["counts"]["segments"], 4)
        self.assertEqual(program["counts"]["attachments"], 1)
        self.assertTrue(program["flags"]["favorite"])
        self.assertIn("broadcast", program["tags"])
        self.assertTrue(program["cover"])
        self.assertAlmostEqual(program["seconds"], 1.39, places=1)

    def test_segments_pair_scripts_with_audio_and_keep_order(self) -> None:
        program = self.news.program("The Reach Report")["program"]
        kinds = [(segment["title"], segment["kind"]) for segment in program["segments"]]
        self.assertEqual(
            kinds,
            [
                ("The Lantern Line", "audio+script"),
                ("What the Marked Carry", "audio+script"),
                ("Lines of Flair", "script"),
                ("Ident", "audio"),
            ],
        )
        self.assertEqual([segment["number"] for segment in program["segments"]], [1, 2, 3, 4])
        first = program["segments"][0]
        self.assertTrue(first["audioUrl"].endswith(".wav"))
        self.assertAlmostEqual(first["duration"], 1.0, places=2)
        self.assertEqual(first["durationLabel"], "0:01")
        self.assertGreater(first["words"], 20)
        self.assertEqual([item["name"] for item in program["attachments"]], ["Reference - Bands.pdf"])

    def test_loose_files_form_their_own_program(self) -> None:
        programs = {program["title"]: program for program in self.news.feed()["programs"]}
        loose = programs["Loose files"]
        self.assertEqual(loose["folder"], "")
        self.assertEqual([segment["title"] for segment in loose["segments"]], ["A loose note"])

    def test_program_json_can_order_segments(self) -> None:
        meta_path = self.root / "The Reach Report" / "program.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # Names may be written with or without the extension.
        meta["order"] = ["99 - Ident.mp3", "02 - What the Marked Carry"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.library.index(refresh=True)
        program = News(self.library).program("The Reach Report")["program"]
        self.assertEqual(
            [segment["title"] for segment in program["segments"]][:2], ["Ident", "What the Marked Carry"]
        )
        self.assertEqual([segment["number"] for segment in program["segments"]], [1, 2, 3, 4])

    # -------------------------------------------------------------- segments
    def test_segment_text_and_speech(self) -> None:
        program = self.news.program("The Reach Report")["program"]
        segment = program["segments"][0]
        found = self.news.segment(program["id"], segment["id"])
        self.assertIn("# The Lantern Line", found["text"])
        self.assertIn("## Count", found["text"])
        self.assertEqual(found["segment"]["id"], segment["id"])

        speech = self.news.segment_speech(program["id"], segment["id"])
        self.assertGreaterEqual(len(speech["speech"]), 3)
        self.assertGreater(speech["words"], 20)
        self.assertNotIn("*", "".join(speech["speech"]))
        # The audio-only segment has nothing to read.
        audio_only = program["segments"][3]
        self.assertEqual(self.news.segment_speech(program["id"], audio_only["id"])["speech"], [])

    def test_unknown_program_and_segment(self) -> None:
        with self.assertRaises(NewsError):
            self.news.program("no-such-program")
        with self.assertRaises(NewsError):
            self.news.segment("The Reach Report", "no-such-segment")
        with self.assertRaises(NewsError):
            self.news.save_progress("no-such-segment", position=1)

    # -------------------------------------------------------------- progress
    def test_progress_survives_and_feeds_continue_listening(self) -> None:
        program = self.news.program("The Reach Report")["program"]
        first = program["segments"][0]
        self.news.save_progress(first["id"], position=0.5, duration=1.0)

        feed = self.news.feed()
        self.assertEqual([entry["title"] for entry in feed["continue"]], ["The Reach Report"])
        # The shelf is 0% *finished*...
        self.assertEqual(feed["continue"][0]["progress"]["percent"], 0)
        # ...but the segment you stopped in remembers where you were.
        self.assertEqual(feed["continue"][0]["segments"][0]["percent"], 50)
        self.assertEqual(self.library.continue_listening()[0]["percent"], 50)

        refreshed = self.news.program("The Reach Report")["program"]
        self.assertEqual(refreshed["progress"]["segmentTitle"], "The Lantern Line")
        self.assertEqual(refreshed["progress"]["position"], 0.5)
        self.assertEqual(refreshed["progress"]["total"], 4)
        self.assertEqual(refreshed["progress"]["listened"], 0)
        self.assertEqual(refreshed["segments"][0]["positionLabel"], "0:00")

        # A new News instance (a fresh window) still sees it: it is on disk.
        reopened = News(Library([str(self.root)]))
        self.assertEqual(reopened.program("The Reach Report")["program"]["progress"]["position"], 0.5)

    def test_finishing_a_segment_marks_it_played(self) -> None:
        program = self.news.program("The Reach Report")["program"]
        first = program["segments"][0]
        self.news.save_progress(first["id"], position=1.0, duration=1.0)
        self.news.mark_played(first["id"], True)

        refreshed = self.news.program("The Reach Report")["program"]
        self.assertTrue(refreshed["segments"][0]["flags"]["played"])
        self.assertEqual(refreshed["progress"]["listened"], 1)
        self.assertEqual(refreshed["progress"]["percent"], 25)
        # The flag is in the sidecar, not only in memory.
        sidecar = json.loads(
            (self.root / "The Reach Report" / "01 - The Lantern Line.md.flags.json").read_text(encoding="utf-8")
        )
        self.assertTrue(sidecar["played"])

    # ----------------------------------------------------------------- flags
    def test_program_flags_are_written_to_the_folder(self) -> None:
        result = self.news.toggle_program_flag("Emberwatch Notebook", "favorite")
        self.assertTrue(result["value"])
        stored = json.loads(
            (self.root / "Emberwatch Notebook" / "program.flags.json").read_text(encoding="utf-8")
        )
        self.assertTrue(stored["favorite"])

        saved = self.news.set_program_flags("Emberwatch Notebook", {"tags": "nightly, ledger", "note": "keep"})
        self.assertEqual(saved["flags"]["tags"], ["nightly", "ledger"])
        self.assertEqual(saved["flags"]["note"], "keep")

        with self.assertRaises(NewsError):
            self.news.toggle_program_flag("Emberwatch Notebook", "downloaded")

    def test_segment_flags_reach_the_script(self) -> None:
        program = self.news.program("The Reach Report")["program"]
        segment = program["segments"][2]  # script only
        self.news.set_segment_flags(segment["id"], {"pinned": True})
        refreshed = self.news.program("The Reach Report")["program"]
        self.assertTrue(refreshed["segments"][2]["flags"]["pinned"])

    # ---------------------------------------------------------------- search
    def test_search_finds_segments_and_ignores_empty_queries(self) -> None:
        self.assertEqual(self.news.search("")["results"], [])
        hits = self.news.search("ledger")["results"]
        self.assertEqual(hits[0]["programTitle"], "Emberwatch Notebook")
        self.assertEqual(hits[0]["title"], "The Assessor's Ledger")
        self.assertTrue(hits[0]["score"] >= 4)
        self.assertEqual(self.news.search("nothing-matches")["results"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
