"""Launching JADELY applications, and keeping track of what is running.

The launcher is a hub, not a supervisor: it spawns each app as its own detached
process (so closing the hub never closes your work), remembers the process id in
``state/apps.json``, and can stop what it started.

Two flavours of app:

* **built-in** — ``store``, ``news``, ``notes``: a pywebview window pointed at a
  page of the local server. Started from the hub they simply open that page on
  the hub's own server; started directly they boot their own.
* **external** — anything else with a command, including the older standalone
  Jadeli at ``D:\\Personal\\jadeli`` when it is present.

Stopping is deliberately careful: it checks the process id still belongs to a
Python process before touching it, so a recycled id can never kill something
unrelated, and it asks nicely (``taskkill`` without ``/F``) before insisting.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import APP_DIR

__all__ = ["Launcher", "LauncherError", "BUILTIN_APPS", "main"]

STATE_PATH = APP_DIR / "state" / "apps.json"

BUILTIN_APPS: list[dict] = [
    {
        "id": "launcher",
        "name": "JADELY Launcher",
        "short": "Launcher",
        "page": "/launcher",
        "description": "The hub: open, stop and keep an eye on the other apps.",
        "accent": "#e0a458",
        "icon": "hub",
    },
    {
        "id": "store",
        "name": "JADELY Store",
        "short": "Store",
        "page": "/store",
        "description": "Browse, flag, import, play and convert everything in your library.",
        "accent": "#5fb3c9",
        "icon": "store",
    },
    {
        "id": "news",
        "name": "JADELY News",
        "short": "News",
        "page": "/news",
        "description": "Programs of segments — read the script or listen to it.",
        "accent": "#c05f7a",
        "icon": "news",
    },
    {
        "id": "notes",
        "name": "Jadeli — notes & books",
        "short": "Notes",
        "page": "/",
        "description": "The markdown vault: notes, wiki links, manuscripts, export.",
        "accent": "#8fbf6a",
        "icon": "notes",
    },
]

APP_PAGES = {app["id"]: app["page"] for app in BUILTIN_APPS}


class LauncherError(Exception):
    """Anything the user should see as a clear message."""


# ------------------------------------------------------------------ processes
def _alive(pid: int) -> bool:
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259  # STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _image_name(pid: int) -> str:
    """The executable behind a pid, so we never stop the wrong process."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _interpreter() -> str:
    """Prefer pythonw so no console window flashes up with the app."""
    python = Path(sys.executable)
    if sys.platform == "win32":
        windowless = python.with_name("pythonw.exe")
        if windowless.is_file():
            return str(windowless)
    return str(python)


class Launcher:
    """The app registry: what exists, what is running, start and stop."""

    def __init__(self, server_url: str = "", *, config: dict | None = None) -> None:
        self.server_url = server_url.rstrip("/")
        self.config = config or {}
        self.state_path = STATE_PATH

    # -------------------------------------------------------------------- state
    def read_state(self) -> dict:
        if not self.state_path.is_file():
            return {}
        try:
            stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return stored if isinstance(stored, dict) else {}

    def write_state(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as error:
            raise LauncherError(f"Could not save the app registry: {error}") from error

    # --------------------------------------------------------------------- apps
    def definitions(self) -> list[dict]:
        """Built-in apps, plus the legacy Jadeli when it can be found."""
        apps = [dict(app, kind="builtin") for app in BUILTIN_APPS]

        legacy = self.config.get("legacy_jadeli") or ""
        candidates = [Path(legacy)] if legacy else []
        candidates.append(Path(r"D:\Personal\jadeli"))
        for folder in candidates:
            try:
                if folder and (folder / "app.py").is_file():
                    apps.append(
                        {
                            "id": "jadeli-legacy",
                            "name": "Jadeli (legacy)",
                            "short": "Jadeli 0.1",
                            "description": f"The older single-window Jadeli in {folder}.",
                            "accent": "#8a93a6",
                            "icon": "legacy",
                            "kind": "external",
                            "folder": str(folder),
                            "command": [str(Path(sys.executable)), str(folder / "app.py")],
                            "page": None,
                        }
                    )
                    break
            except OSError:
                continue
        return apps

    def get(self, app_id: str) -> dict:
        for app in self.definitions():
            if app["id"] == app_id:
                return app
        raise LauncherError(f"Unknown app: {app_id}")

    def apps(self) -> list[dict]:
        """Every app with its live status merged in."""
        state = self.read_state()
        out: list[dict] = []
        seen: set[int] = set()
        for app in self.definitions():
            entry = state.get(app["id"]) or {}
            pid = int(entry.get("pid") or 0)
            running = _alive(pid)
            if running:
                seen.add(pid)
            out.append(
                {
                    **app,
                    "running": running,
                    "pid": pid if running else 0,
                    "started": entry.get("started", "") if running else "",
                    "url": entry.get("url", "") if running else "",
                    "page": (self.server_url + app["page"]) if app.get("page") else "",
                }
            )
        # Anything else we started (or lost track of) shows as an orphan entry.
        for app_id, entry in state.items():
            if any(item["id"] == app_id for item in out):
                continue
            pid = int(entry.get("pid") or 0)
            if _alive(pid):
                out.append(
                    {
                        "id": app_id,
                        "name": entry.get("name") or app_id,
                        "short": entry.get("name") or app_id,
                        "description": "Registered by an earlier session.",
                        "accent": "#6f7887",
                        "icon": "unknown",
                        "kind": entry.get("kind") or "external",
                        "running": True,
                        "pid": pid,
                        "started": entry.get("started", ""),
                        "url": entry.get("url", ""),
                        "page": "",
                        "orphan": True,
                    }
                )
        return out

    def status(self) -> dict:
        apps = self.apps()
        return {
            "server": self.server_url,
            "pid": os.getpid(),
            "python": sys.executable,
            "running": sum(1 for app in apps if app["running"]),
            "apps": apps,
        }

    # ------------------------------------------------------------------- start
    def command_for(self, app: dict, *, url: str = "") -> tuple[list[str], Path]:
        """The argv and working directory used to launch one app."""
        if app.get("kind") == "external":
            command = app.get("command")
            if not command:
                raise LauncherError(f"{app['name']} has no command configured")
            folder = Path(app.get("folder") or APP_DIR)
            if not folder.is_dir():
                raise LauncherError(f"{app['name']} is not available: {folder} does not exist")
            return [str(part) for part in command], folder

        base = url or self.server_url
        if not base:
            # No hub server to attach to: the app boots its own.
            arguments = [str(APP_DIR / "app.py"), "--app", app["id"]]
        else:
            arguments = [str(APP_DIR / "app.py"), "--app", app["id"], "--url", base]
        return [_interpreter(), *arguments], APP_DIR

    def start(self, app_id: str, *, url: str = "", force: bool = False) -> dict:
        app = self.get(app_id)
        state = self.read_state()
        entry = state.get(app_id) or {}
        if not force and entry.get("pid") and _alive(int(entry["pid"])):
            return {
                "app": app_id,
                "started": False,
                "alreadyRunning": True,
                "pid": int(entry["pid"]),
                "url": entry.get("url", ""),
                "message": f"{app['name']} is already open (pid {int(entry['pid'])}).",
            }

        command, cwd = self.command_for(app, url=url)
        if not Path(command[0]).exists():
            raise LauncherError(f"{app['name']}: {command[0]} is missing")
        flags = 0
        if sys.platform == "win32":
            flags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                close_fds=True,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
            )
        except OSError as error:
            raise LauncherError(f"Could not launch {app['name']}: {error}") from error

        page_url = ((url or self.server_url) + app["page"]) if app.get("page") else ""
        state[app_id] = {
            "pid": process.pid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "name": app["name"],
            "kind": app.get("kind"),
            "url": page_url,
        }
        self.write_state(state)
        return {
            "app": app_id,
            "started": True,
            "alreadyRunning": False,
            "pid": process.pid,
            "command": command,
            "url": page_url,
            "message": f"{app['name']} opened (pid {process.pid}).",
        }

    # -------------------------------------------------------------------- stop
    def stop(self, app_id: str, *, timeout: float = 6.0) -> dict:
        state = self.read_state()
        # An app started in an earlier session may have left the manifest, so the
        # registry counts as known too — but a typo should be reported, not ignored.
        known = {app["id"] for app in self.definitions()} | set(state)
        if app_id not in known:
            raise LauncherError(f"Unknown app: {app_id}")
        entry = state.get(app_id) or {}
        pid = int(entry.get("pid") or 0)
        if not pid:
            return {"app": app_id, "stopped": False, "message": "That app is not running."}
        if not _alive(pid):
            state.pop(app_id, None)
            self.write_state(state)
            return {"app": app_id, "stopped": False, "message": "That app had already closed."}

        image = _image_name(pid)
        if image and not image.startswith(("python", "py")):
            raise LauncherError(
                f"Refusing to stop pid {pid}: it is {image}, not a JADELY process."
            )

        self._signal(pid, force=False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.15)
        forced = False
        if _alive(pid):
            self._signal(pid, force=True)
            forced = True
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _alive(pid):
                time.sleep(0.15)

        still_running = _alive(pid)
        if not still_running:
            state.pop(app_id, None)
            self.write_state(state)
        return {
            "app": app_id,
            "stopped": not still_running,
            "forced": forced,
            "pid": pid,
            "message": (
                f"Stopped pid {pid}." if not still_running
                else f"pid {pid} is still running (it may be elevated)."
            ),
        }

    def stop_all(self) -> list[dict]:
        return [self.stop(app["id"]) for app in self.apps() if app["running"]]

    @staticmethod
    def _signal(pid: int, *, force: bool) -> None:
        if sys.platform == "win32":
            command = ["taskkill", "/PID", str(pid), "/T"]
            if force:
                command.append("/F")
            subprocess.run(
                command,
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        try:
            os.kill(pid, 9 if force else 15)
        except OSError:
            pass

    # -------------------------------------------------------------------- misc
    def url_for(self, app_id: str) -> str:
        app = self.get(app_id)
        if not app.get("page"):
            raise LauncherError(f"{app['name']} does not open a page")
        return (self.server_url or "") + app["page"]


# ------------------------------------------------------------------------ cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jadely-launcher", description="Start and stop JADELY apps.")
    parser.add_argument("action", choices=("list", "status", "start", "stop", "stop-all"))
    parser.add_argument("app", nargs="?", help="app id (store, news, notes, launcher, jadeli-legacy)")
    parser.add_argument("--url", default="", help="hub server URL the app should attach to")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    launcher = Launcher(args.url)
    try:
        if args.action in ("list", "status"):
            payload = launcher.status()
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                for app in payload["apps"]:
                    mark = f"pid {app['pid']}" if app["running"] else "not running"
                    print(f"  {app['id']:14} {app['name']:26} {mark}")
            return 0
        if args.action == "stop-all":
            results = launcher.stop_all()
            print(json.dumps(results, indent=2) if args.json else "\n".join(r["message"] for r in results))
            return 0
        if not args.app:
            parser.error("an app id is required")
        result = launcher.start(args.app) if args.action == "start" else launcher.stop(args.app)
        print(json.dumps(result, indent=2) if args.json else result["message"])
        return 0
    except LauncherError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
