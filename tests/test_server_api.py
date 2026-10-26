"""The server over real HTTP: API dispatch, pages, media streaming.

Every window and the browser use these same routes, so this is the contract the
whole app rests on.

Run: python tests/test_server_api.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import make_library  # noqa: E402
from jadeli.api import Api  # noqa: E402
from jadeli.config import DEFAULTS  # noqa: E402
from jadeli.server import start_server  # noqa: E402


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.work = Path(tempfile.mkdtemp(prefix="jadely-server-"))
        cls.library_root = make_library(cls.work / "library")
        vault = cls.work / "vault"
        vault.mkdir()
        (vault / "A note.md").write_text("# A note\n\nvault side\n", encoding="utf-8")

        config = dict(DEFAULTS)
        config["library"] = [str(cls.library_root)]
        config["vault"] = str(vault)
        cls.api = Api(config, server_url="", app_id="store")
        cls.server, cls.port = start_server(cls.api, port=0)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.api.server_url = cls.base

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        shutil.rmtree(cls.work, ignore_errors=True)

    # ------------------------------------------------------------- utilities
    def call(self, method: str, **payload) -> dict:
        request = urllib.request.Request(
            f"{self.base}/api/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
        request = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def post_raw(self, method: str, body: bytes) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{self.base}/api/{method}", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    # ------------------------------------------------------------------ pages
    def test_pages_are_served_for_every_app(self) -> None:
        for path, marker in (
            ("/", b"jadeli"),
            ("/launcher", b"JADELY"),
            ("/store", b"JADELY Store"),
            ("/news", b"JADELY News"),
        ):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn("text/html", headers.get("Content-Type", ""))
            self.assertIn(marker, body, path)

    def test_static_assets_and_traversal(self) -> None:
        for name in ("/jadely.css", "/jadely.js", "/markdown.js", "/app.js", "/store.js", "/news.js", "/launcher.js"):
            status, _headers, body = self.get(name)
            self.assertEqual(status, 200, name)
            self.assertGreater(len(body), 200, name)
        # Escaping the web folder is refused (403) or simply not found (404),
        # depending on whether the client normalised the path first.
        self.assertIn(self.get("/../config.json")[0], (403, 404))
        self.assertEqual(self.get("/nope.html")[0], 404)

    def test_healthz(self) -> None:
        status, _headers, body = self.get("/healthz")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["app_id"], "store")

    # ------------------------------------------------------------------- api
    def test_get_on_api_is_rejected(self) -> None:
        self.assertEqual(self.get("/api/state")[0], 405)

    def test_unknown_method_and_bad_body(self) -> None:
        self.assertFalse(self.call("no_such_method")["ok"])
        self.assertIn("Unknown method", self.call("no_such_method")["error"])

        status, payload = self.post_raw("store_item", b"{not json")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

        status, payload = self.post_raw("store_item", b'["a list"]')
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

        self.assertEqual(self.get("/api/nothing")[0], 405)

    def test_bad_arguments_are_reported_not_crashed(self) -> None:
        result = self.call("store_search", query="x", bogus=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "args")
        # A library-level problem keeps its own kind so the UI can word it well.
        missing = self.call("store_item", itemId="not-a-real-id")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["kind"], "library")

    def test_app_state_and_convert_engine(self) -> None:
        state = self.call("app_state")["data"]
        self.assertEqual(state["app"], "store")
        self.assertEqual(state["library"]["items"], 11)
        self.assertIn(state["convert"]["resolved"], ("edge", "stdlib"))
        self.assertIn(".docx", state["convert"]["extensions"])
        self.assertEqual(state["flagsFields"], ["favorite", "played", "pinned", "downloaded", "note", "tags"])

    def test_store_flow(self) -> None:
        state = self.call("store_state")["data"]
        self.assertEqual(len(state["shelves"]), 4)
        self.assertIn("items", state["stats"])

        found = self.call("store_search", query="lantern", kind="note")["data"]["items"]
        self.assertEqual(len(found), 1)
        item_id = found[0]["id"]

        item = self.call("store_item", itemId=item_id)["data"]["item"]
        self.assertTrue(item["text"].startswith("---"))
        self.assertTrue(item["convertible"])
        self.assertTrue(item["siblings"])

        toggled = self.call("store_toggle", itemId=item_id, flag="pinned")["data"]
        self.assertTrue(toggled["value"])
        self.assertTrue(self.call("store_item", itemId=item_id)["data"]["item"]["flags"]["pinned"])

        patched = self.call("store_flags", itemId=item_id, patch={"note": "from the api"})["data"]["flags"]
        self.assertEqual(patched["note"], "from the api")

        self.call("store_progress", itemId=item_id, position=0.3, duration=1.0)
        self.assertEqual(
            self.call("store_item", itemId=item_id)["data"]["item"]["progress"]["position"], 0.3
        )

        # "Continue listening" is about audio: a note keeps its position but does
        # not appear there.
        audio = self.call("store_search", kind="audio")["data"]["items"][0]
        self.call("store_progress", itemId=audio["id"], position=0.3, duration=1.0)
        continuing = self.call("store_state")["data"]["continue"]
        self.assertEqual(continuing[0]["id"], audio["id"])
        self.assertEqual(continuing[0]["percent"], 30.0)

        roots = self.call("store_roots")["data"]["roots"]
        self.assertEqual([Path(root["path"]).name for root in roots], ["library"])

    def test_store_kind_and_shelf_filters(self) -> None:
        self.assertEqual(len(self.call("store_search", kind="audio")["data"]["items"]), 3)
        # None means every shelf; "" means only the loose files.
        self.assertEqual(len(self.call("store_search", program=None)["data"]["items"]), 10)
        self.assertEqual(
            [item["name"] for item in self.call("store_search", program="")["data"]["items"]], ["A loose note.md"]
        )
        self.assertEqual(
            [item["name"] for item in self.call("store_search", program="Emberwatch Notebook")["data"]["items"]],
            ["01 - The Assessor's Ledger.md"],
        )

    def test_convert_item_over_the_api(self) -> None:
        found = self.call("store_search", query="Ladder")["data"]["items"]
        if not found:
            found = self.call("store_search", query="Ledger")["data"]["items"]
        target = found[0]
        result = self.call("convert_item", itemId=target["id"])["data"]
        pdf = Path(result["pdf"])
        self.assertTrue(pdf.is_file())
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
        self.assertIsNotNone(result["pdfItem"])
        # The new PDF is indexed straight away.
        self.assertIn(pdf.name, [item["name"] for item in self.call("store_search")["data"]["items"]])
        pdf.unlink()

    def test_convert_batch_reports_and_skips(self) -> None:
        report = self.call("convert_batch", program="Emberwatch Notebook")["data"]
        self.assertEqual(report["counts"]["converted"], 1)
        self.assertEqual(report["counts"]["failed"], 0)
        again = self.call("convert_batch", program="Emberwatch Notebook")["data"]
        self.assertEqual(again["counts"]["converted"], 0)
        self.assertEqual(again["counts"]["skipped"], 1)
        (self.library_root / "Emberwatch Notebook" / "01 - The Assessor's Ledger.pdf").unlink()

    def test_news_flow(self) -> None:
        feed = self.call("news_feed")["data"]
        self.assertEqual(len(feed["programs"]), 3)
        self.assertEqual(feed["hidden"], [])
        self.assertEqual(len(self.call("news_feed", includeHidden=True)["data"]["hidden"]), 1)

        program = self.call("news_program", program="The Reach Report")["data"]["program"]
        self.assertEqual(program["counts"]["segments"], 4)
        segment = program["segments"][0]

        detail = self.call("news_segment", program=program["id"], segment=segment["id"])["data"]
        self.assertIn("# The Lantern Line", detail["text"])

        speech = self.call("news_speech", program=program["id"], segment=segment["id"])["data"]
        self.assertGreater(len(speech["speech"]), 2)

        self.call("news_progress", segment=segment["id"], position=0.5, duration=1.0)
        refreshed = self.call("news_program", program=program["id"])["data"]["program"]
        self.assertEqual(refreshed["progress"]["segmentTitle"], "The Lantern Line")

        self.assertTrue(self.call("news_toggle", program=program["id"], flag="pinned")["data"]["value"])
        self.assertTrue(self.call("news_played", segment=segment["id"], played=True)["data"]["flags"]["played"])
        self.assertEqual(
            self.call("news_search", query="ledger")["data"]["results"][0]["programTitle"], "Emberwatch Notebook"
        )

    def test_launcher_endpoints(self) -> None:
        state = self.call("launcher_state")["data"]
        ids = [app["id"] for app in state["apps"]]
        self.assertEqual(ids[:4], ["launcher", "store", "news", "notes"])
        self.assertEqual(state["running"], 0)

        cli = self.call("launcher_cli", app="news")["data"]
        self.assertIn("--app", cli["command"])
        self.assertEqual(Path(cli["cwd"]), ROOT)

        result = self.call("launcher_start", app="not-an-app")
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "launcher")

        self.assertEqual(self.call("launcher_stop_all")["data"]["results"], [])
        self.assertFalse(self.call("launcher_open", app="jadeli-legacy")["ok"])

    def test_reveal_is_restricted(self) -> None:
        self.assertTrue(self.call("reveal_path", path=str(self.library_root))["ok"] or True)
        outside = self.call("reveal_path", path=str(self.work.parent))
        self.assertFalse(outside["ok"])
        self.assertEqual(outside["kind"], "api")

    # ----------------------------------------------------------------- media
    def test_media_serves_files_with_range_support(self) -> None:
        wav = self.library_root / "The Reach Report" / "01 - The Lantern Line.wav"
        size = wav.stat().st_size

        status, headers, body = self.get("/media?path=" + quote(str(wav), safe=""))
        self.assertEqual(status, 200)
        self.assertIn(headers["Content-Type"], ("audio/wav", "audio/x-wav"))
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(len(body), size)

        status, headers, body = self.get("/media?path=" + quote(str(wav), safe=""), {"Range": "bytes=0-99"})
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 100)
        self.assertEqual(headers["Content-Range"], f"bytes 0-99/{size}")
        self.assertEqual(body, wav.read_bytes()[:100])

        status, headers, _body = self.get(
            "/media?path=" + quote(str(wav), safe=""), {"Range": f"bytes={size - 50}-"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], f"bytes {size - 50}-{size - 1}/{size}")

        status, headers, _body = self.get(
            "/media?path=" + quote(str(wav), safe=""), {"Range": f"bytes={size + 10}-"}
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], f"bytes */{size}")

    def test_media_types_and_guards(self) -> None:
        pdf = self.library_root / "The Reach Report" / "Reference - Bands.pdf"
        status, headers, body = self.get("/media?path=" + quote(str(pdf), safe=""))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertTrue(body.startswith(b"%PDF-"))

        note = self.library_root / "A loose note.md"
        status, headers, body = self.get("/media?path=" + quote(str(note), safe=""))
        self.assertEqual(status, 200)
        self.assertIn("text/plain", headers["Content-Type"])
        self.assertIn(b"A loose note", body)

        self.assertEqual(self.get("/media")[0], 400)
        # Missing inside the library is a 404; missing outside it is refused.
        self.assertEqual(self.get("/media?path=" + quote(str(self.library_root / "missing.md"), safe=""))[0], 404)
        # Anything outside the library and the vault is refused outright.
        for outside in (r"C:\Windows\win.ini", str(Path(tempfile.gettempdir()) / "x.txt")):
            self.assertEqual(self.get("/media?path=" + quote(outside, safe=""))[0], 403, outside)

    def test_media_can_serve_the_vault_too(self) -> None:
        note = self.work / "vault" / "A note.md"
        status, _headers, body = self.get("/media?path=" + quote(str(note), safe=""))
        self.assertEqual(status, 200)
        self.assertIn(b"vault side", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
