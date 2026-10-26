"""Manual smoke test for the desktop windows.

Opens a real pywebview window, inspects the page from inside it, prints what it
found and closes again. The automated suites drive the HTTP API; this is the one
that proves the window itself renders.

    python tests/smoke_window.py                # the launcher
    python tests/smoke_window.py store          # the store
    python tests/smoke_window.py news           # the news portal
    python tests/smoke_window.py notes          # the markdown vault
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

from jadeli.api import Api  # noqa: E402
from jadeli.config import load_config  # noqa: E402
from jadeli.server import start_server  # noqa: E402

# app -> (page, what to count, must be visible)
CHECKS = {
    "launcher": ("/launcher", "document.querySelectorAll('.launch-card').length", "the app cards"),
    "store": ("/store", "document.querySelectorAll('.tile, .rowitem').length", "the item grid"),
    "news": ("/news", "document.querySelectorAll('.seg').length", "the segment list"),
    "notes": ("/", "document.querySelectorAll('[data-path]').length", "the file tree"),
}


def main(argv: list[str]) -> int:
    app = (argv[0] if argv else "launcher").lower()
    if app not in CHECKS:
        print(f"unknown app: {app} (try {', '.join(CHECKS)})")
        return 2
    page, expression, label = CHECKS[app]

    config = load_config()
    config["vault"] = str(ROOT / "vault")
    config["library"] = [str(ROOT / "library")]
    api = Api(config, app_id=app)
    server, port = start_server(api)
    url = f"http://127.0.0.1:{port}{page}"
    window = webview.create_window(f"JADELY {app} smoke test", url, width=1340, height=900)

    results: dict[str, object] = {}

    def inspect() -> None:
        time.sleep(7)  # let the page fetch and paint
        try:
            results["title"] = window.evaluate_js("document.title")
            results["count"] = window.evaluate_js(expression)
            results["errors"] = window.evaluate_js("window.__jadelyErrors || 0")
            results["body"] = window.evaluate_js("document.body.className || 'ok'")
        except Exception as error:  # noqa: BLE001 - a smoke test reports, it does not raise
            results["error"] = str(error)
        finally:
            window.destroy()

    webview.start(inspect, private_mode=False, storage_path=str(ROOT / ".profile"))
    server.shutdown()

    print(f"window:  {results.get('title')}")
    print(f"page:    {url}")
    print(f"{label}: {results.get('count')}")
    if "error" in results:
        print(f"FAILED:  {results['error']}")
        return 1
    print("OK" if results.get("count") else "EMPTY PAGE — check the server log")
    return 0 if results.get("count") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
