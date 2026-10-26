"""The launcher: app registry, launch commands, start/stop and the safety guard.

Run: python tests/test_launcher.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jadeli import launcher as launcher_module  # noqa: E402
from jadeli.launcher import BUILTIN_APPS, Launcher, LauncherError, _alive, _image_name  # noqa: E402

SLEEPER = """\
import time
print("started", flush=True)
for _ in range(600):
    time.sleep(0.1)
"""


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="jadely-launcher-"))
        self.state = self.work / "apps.json"
        self.started: list[int] = []
        self.launcher = Launcher("http://127.0.0.1:9999", config={})
        # Never touch the real registry while testing.
        self.launcher.state_path = self.state

    def tearDown(self) -> None:
        # Only ever stop processes this test started — never whatever pid a state
        # file happens to mention.
        for pid in self.started:
            if _alive(pid):
                self.launcher._signal(pid, force=True)
        shutil.rmtree(self.work, ignore_errors=True)

    # ------------------------------------------------------------- discovery
    def test_builtin_apps_are_all_present(self) -> None:
        apps = {app["id"]: app for app in self.launcher.definitions()}
        for builtin in BUILTIN_APPS:
            self.assertIn(builtin["id"], apps)
            self.assertEqual(apps[builtin["id"]]["kind"], "builtin")
            self.assertTrue(apps[builtin["id"]]["page"].startswith("/"))
        self.assertEqual(set(list(apps)[:4]), {"launcher", "store", "news", "notes"})

    def test_legacy_jadeli_is_discovered_when_it_exists(self) -> None:
        legacy = Path(r"D:\Personal\jadeli")
        if not (legacy / "app.py").is_file():
            self.skipTest("the legacy Jadeli folder is not on this machine")
        apps = {app["id"]: app for app in self.launcher.definitions()}
        self.assertIn("jadeli-legacy", apps)
        self.assertEqual(apps["jadeli-legacy"]["kind"], "external")
        self.assertEqual(Path(apps["jadeli-legacy"]["command"][1]), legacy / "app.py")

    def test_status_shape(self) -> None:
        status = self.launcher.status()
        self.assertEqual(status["server"], "http://127.0.0.1:9999")
        self.assertEqual(status["pid"], os.getpid())
        self.assertGreaterEqual(len(status["apps"]), 4)
        self.assertIsInstance(status["running"], int)

    # -------------------------------------------------------------- commands
    def test_launch_command_for_a_builtin_app(self) -> None:
        command, cwd = self.launcher.command_for(self.launcher.get("store"))
        self.assertEqual(command[1:], [str(ROOT / "app.py"), "--app", "store", "--url", "http://127.0.0.1:9999"])
        self.assertEqual(cwd, ROOT)

        # Without a hub to attach to, the app boots its own server instead.
        standalone = Launcher("", config={})
        bare, _ = standalone.command_for(standalone.get("news"))
        self.assertNotIn("--url", bare)
        self.assertEqual(bare[-2:], ["--app", "news"])

    def test_external_app_needs_its_folder(self) -> None:
        missing = {"id": "ghost", "name": "Ghost", "kind": "external", "folder": str(self.work / "nope"), "command": ["python", "app.py"]}
        with mock.patch.object(Launcher, "definitions", lambda self: [missing]):
            with self.assertRaises(LauncherError):
                self.launcher.command_for(missing)
        with self.assertRaises(LauncherError):
            self.launcher.get("ghost")

    # ------------------------------------------------------------ start/stop
    def _dummy_app(self) -> dict:
        folder = self.work / "dummy-app"
        folder.mkdir(exist_ok=True)
        (folder / "app.py").write_text(SLEEPER, encoding="utf-8")
        return {
            "id": "dummy",
            "name": "Dummy app",
            "kind": "external",
            "folder": str(folder),
            "command": [sys.executable, str(folder / "app.py")],
        }

    def test_start_then_stop_a_real_process(self) -> None:
        app = self._dummy_app()
        with mock.patch.object(Launcher, "definitions", lambda self: [app]):
            started = self.launcher.start("dummy")
            self.assertTrue(started["started"])
            pid = started["pid"]
            self.started.append(pid)
            self.assertTrue(_alive(pid))

            # The registry remembers it, and a second open does not spawn again.
            self.assertTrue(self.state.is_file())
            registered = json.loads(self.state.read_text(encoding="utf-8"))
            self.assertEqual(registered["dummy"]["pid"], pid)

            again = self.launcher.start("dummy")
            self.assertTrue(again["alreadyRunning"])
            self.assertEqual(again["pid"], pid)

            running = next(a for a in self.launcher.apps() if a["id"] == "dummy")
            self.assertTrue(running["running"])

            stopped = self.launcher.stop("dummy")
            self.assertTrue(stopped["stopped"])
            self.assertFalse(_alive(pid))
            self.assertNotIn("dummy", json.loads(self.state.read_text(encoding="utf-8")))

            # Stopping something that is no longer running is harmless and says so.
            self.assertIn("not running", self.launcher.stop("dummy")["message"])

    def test_force_start_ignores_a_running_instance(self) -> None:
        app = self._dummy_app()
        with mock.patch.object(Launcher, "definitions", lambda self: [app]):
            first = self.launcher.start("dummy")
            second = self.launcher.start("dummy", force=True)
            self.started.extend([first["pid"], second["pid"]])
            self.assertNotEqual(first["pid"], second["pid"])
            self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["dummy"]["pid"], second["pid"])

    def test_stop_refuses_a_foreign_process(self) -> None:
        """A recycled pid must never get killed: the image name is checked first."""
        self.state.write_text(json.dumps({"dummy": {"pid": 4242, "name": "Dummy app"}}), encoding="utf-8")
        signals: list[tuple[int, bool]] = []
        with mock.patch.object(launcher_module, "_alive", lambda pid: True), mock.patch.object(
            launcher_module, "_image_name", lambda pid: "explorer.exe"
        ), mock.patch.object(Launcher, "_signal", lambda self, pid, force: signals.append((pid, force))):
            with self.assertRaises(LauncherError) as raised:
                self.launcher.stop("dummy")
        self.assertIn("explorer.exe", str(raised.exception))
        self.assertEqual(signals, [])
        # The entry is left alone rather than silently forgotten.
        self.assertIn("dummy", json.loads(self.state.read_text(encoding="utf-8")))

    def test_stop_forces_when_a_gentle_stop_is_ignored(self) -> None:
        self.state.write_text(json.dumps({"dummy": {"pid": 4242, "name": "Dummy app"}}), encoding="utf-8")
        signals: list[tuple[int, bool]] = []
        alive = {"value": True}

        def false_alive(pid: int) -> bool:
            return alive["value"]

        def record(self, pid: int, force: bool) -> None:
            signals.append((pid, force))
            if force:
                alive["value"] = False

        with mock.patch.object(launcher_module, "_alive", false_alive), mock.patch.object(
            launcher_module, "_image_name", lambda pid: "pythonw.exe"
        ), mock.patch.object(Launcher, "_signal", record):
            result = self.launcher.stop("dummy", timeout=0.2)
        self.assertTrue(result["forced"])
        self.assertEqual(signals, [(4242, False), (4242, True)])

    def test_process_probes(self) -> None:
        self.assertTrue(_alive(os.getpid()))
        self.assertFalse(_alive(0))
        self.assertFalse(_alive(999_999_9))
        if sys.platform == "win32":
            self.assertIn("python", _image_name(os.getpid()))

    # ------------------------------------------------------------------- cli
    def test_cli_lists_apps(self) -> None:
        # The CLI builds its own Launcher, so hand it this one (with its temp state
        # file) rather than letting it read the real registry.
        with mock.patch.object(launcher_module, "Launcher", lambda url: self.launcher):
            self.assertEqual(launcher_module.main(["list"]), 0)
            self.assertEqual(launcher_module.main(["status", "--json"]), 0)
            self.assertEqual(launcher_module.main(["stop-all"]), 0)
            self.assertEqual(launcher_module.main(["start", "nope"]), 1)
            self.assertEqual(launcher_module.main(["stop", "nope"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
