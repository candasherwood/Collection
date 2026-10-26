#!/usr/bin/env python
"""JADELY — a local launcher, store, news portal and notes app.

Run modes:

    python app.py                      # the launcher hub (default)
    python app.py --app store          # just the store, in its own window
    python app.py --app news           # just the news portal
    python app.py --app notes          # the markdown vault / manuscripts
    python app.py --url http://127.0.0.1:7654 --app store
                                       # open a window onto a hub already running
    python app.py --server-only        # the API and pages, no window (prints the URL)
    python app.py --browser            # in your default browser instead of a window
    python app.py --status             # what is running, as JSON (no window)
    python app.py --stop store         # stop an app the launcher started

Everything is served from disk over loopback. Nothing is uploaded, and no account
is needed for anything.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import webbrowser
from pathlib import Path

from jadeli.api import Api
from jadeli.config import APP_DIR, DEFAULT_LIBRARY, DEFAULT_VAULT, VERSION, load_config, save_config
from jadeli.launcher import Launcher, LauncherError
from jadeli.server import start_server

LOG_PATH = APP_DIR / "jadely.log"

# id -> (window title, page, (width, height))
APPS = {
    "launcher": ("JADELY", "/launcher", (1200, 840)),
    "store": ("JADELY Store", "/store", (1340, 920)),
    "news": ("JADELY News", "/news", (1340, 920)),
    "notes": ("Jadeli — notes & books", "/", (1480, 940)),
}
DEFAULT_APP = "launcher"


def setup_logging(verbose: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr and sys.stderr.isatty():
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jadely", description="JADELY — launcher, store, news portal and notes, all local."
    )
    parser.add_argument(
        "--app",
        choices=sorted(APPS),
        default=DEFAULT_APP,
        help="which window to open (default: the launcher)",
    )
    parser.add_argument("--vault", help="folder to open as the notes vault")
    parser.add_argument("--url", help="attach to a hub server already running at this URL")
    parser.add_argument("--port", type=int, default=0, help="fixed port for the local server (0 = random)")
    parser.add_argument("--server-only", action="store_true", help="run the API/pages without opening a window")
    parser.add_argument("--browser", action="store_true", help="open the UI in the default browser")
    parser.add_argument("--devtools", action="store_true", help="open the window with developer tools enabled")
    parser.add_argument("--status", action="store_true", help="print what is running as JSON and exit")
    parser.add_argument("--stop", metavar="APP", help="stop an app the launcher started, then exit")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def prepare_config(args: argparse.Namespace) -> dict:
    config = load_config()
    DEFAULT_VAULT.mkdir(parents=True, exist_ok=True)
    DEFAULT_LIBRARY.mkdir(parents=True, exist_ok=True)

    if args.vault:
        vault_path = Path(args.vault).expanduser().resolve()
        if not vault_path.is_dir():
            print(f"Vault folder not found: {vault_path}", file=sys.stderr)
            raise SystemExit(2)
        config["vault"] = str(vault_path)
        save_config(config)
    if not Path(config.get("vault", "")).is_dir():
        config["vault"] = str(DEFAULT_VAULT)
        save_config(config)

    roots = [root for root in (config.get("library") or []) if root]
    roots = [root for root in roots if Path(root).is_dir()]
    if not roots:
        roots = [str(DEFAULT_LIBRARY)]
    config["library"] = roots
    save_config(config)
    return config


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    log = logging.getLogger("jadely")

    if args.status or args.stop:
        launcher = Launcher("", config=load_config())
        try:
            if args.stop:
                print(launcher.stop(args.stop)["message"])
                return 0
            print(json.dumps(launcher.status(), indent=2))
            return 0
        except LauncherError as error:
            print(str(error), file=sys.stderr)
            return 1

    config = prepare_config(args)
    title, page, size = APPS[args.app]

    api = Api(config, server_url=args.url or "", app_id=args.app)
    server = None
    base = (args.url or "").rstrip("/")
    if not base:
        try:
            server, port = start_server(api, port=args.port)
        except OSError as error:
            print(f"Could not start the local server: {error}", file=sys.stderr)
            return 1
        base = f"http://127.0.0.1:{port}"
        api.server_url = base

    url = base + page
    log.info("jadely %s serving %s (app: %s)", VERSION, url, args.app)
    print(f"JADELY {VERSION}  {title}  {url}")
    print(f"library: {api.library.root}")
    if args.app in ("notes", "launcher"):
        print(f"vault:   {api.vault.root}")

    def finish() -> None:
        if server is not None:
            server.shutdown()

    if args.server_only or args.browser:
        if args.browser:
            webbrowser.open(url)
        if args.server_only:
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                log.info("shutting down")
            finally:
                finish()
        return 0

    try:
        import webview
    except ImportError:
        print(
            "pywebview is not installed. Install it with:\n"
            "  python -m pip install pywebview\n"
            "or run with --browser.",
            file=sys.stderr,
        )
        finish()
        return 1

    window = webview.create_window(
        title,
        url,
        width=size[0],
        height=size[1],
        min_size=(900, 600),
        background_color="#0f1116",
    )

    def pick_folder(prompt: str = "Choose a folder"):
        return window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(APP_DIR)) or None

    api.pick_folder = pick_folder
    try:
        webview.start(debug=args.devtools, private_mode=False, storage_path=str(APP_DIR / ".profile"))
    finally:
        log.info("window closed")
        finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
