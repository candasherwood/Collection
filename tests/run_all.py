#!/usr/bin/env python
"""Run every JADELY test suite and summarise.

    python tests/run_all.py            # all suites
    python tests/run_all.py convert    # only suites whose name matches

Each suite runs in its own process, because the server suite starts a real HTTP
server and the launcher suite starts real processes.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = [
    "test_backend.py",     # the notes vault and manuscript side
    "test_convert.py",     # markdown → HTML, the built-in PDF writer, Word import
    "test_library.py",     # the store: index, flag files, search, import/export
    "test_news.py",        # the portal: programs, segments, playback state
    "test_launcher.py",    # app registry, start/stop, the foreign-pid guard
    "test_server_api.py",  # the HTTP contract the windows and browser use
]


def main(argv: list[str] | None = None) -> int:
    wanted = (argv if argv is not None else sys.argv[1:]) or [""]
    selected = [name for name in SUITES if any(part in name for part in wanted)]

    results: list[tuple[str, bool, str]] = []
    for name in selected:
        started = time.monotonic()
        finished = subprocess.run(
            [sys.executable, str(ROOT / "tests" / name)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        summary = ""
        for line in reversed(finished.stdout.strip().splitlines()):
            if line.startswith(("Ran ", "OK", "FAILED")):
                summary = line + ((" · " + summary) if summary else "")
        results.append((name, finished.returncode == 0, f"{time.monotonic() - started:.1f}s  {summary}"))

    width = max(len(name) for name in selected)
    failures = 0
    for name, passed, summary in results:
        failures += 0 if passed else 1
        print(f"{'PASS' if passed else 'FAIL'}  {name:<{width}}  {summary}")
    print(f"\n{len(results) - failures}/{len(results)} suites passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
