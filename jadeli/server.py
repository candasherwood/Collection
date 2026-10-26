"""Loopback HTTP server: JSON API, the library files, and the web assets.

Three kinds of request are served: ``/api/<method>`` (JSON over POST), ``/media``
(the actual content — markdown, PDFs, audio — with Range support so audio can be
scrubbed), and the pages themselves. ``/media`` only ever reads from the folders
the API declares as roots, so it cannot be used to read the rest of the disk.
"""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .api import Api
from .config import WEB_DIR

PAGE_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/launcher": "launcher.html",
    "/store": "store.html",
    "/news": "news.html",
}

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
}


class JadeliHandler(BaseHTTPRequestHandler):
    server_version = "jadeli"
    protocol_version = "HTTP/1.1"
    api: Api
    web_dir: Path
    lock = threading.Lock()

    # ------------------------------------------------------------- helpers
    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- verbs
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            return self._json(200, {"ok": True, "app": "jadeli", "app_id": getattr(self.api, "app_id", "")})
        if path == "/media":
            return self._media(parse_qs(parsed.query))
        if path.startswith("/api/"):
            return self._json(405, {"ok": False, "error": "Use POST for the API"})
        route = PAGE_ROUTES.get(path.rstrip("/") or "/")
        if route:
            return self._static("/" + route)
        return self._static(path)

    def _media(self, query: dict) -> None:
        """Stream a library file, honouring Range so audio can seek."""
        raw = (query.get("path") or [""])[0]
        if not raw:
            return self._bytes(400, b"Missing path", "text/plain; charset=utf-8")
        try:
            target = Path(unquote(raw)).resolve()
        except (OSError, ValueError):
            return self._bytes(400, b"Bad path", "text/plain; charset=utf-8")

        allowed = self.api.media_roots()
        if not any(target == root or root in target.parents for root in allowed):
            return self._bytes(403, b"Outside the library", "text/plain; charset=utf-8")
        if not target.is_file():
            return self._bytes(404, b"Not found", "text/plain; charset=utf-8")

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() in (".md", ".markdown", ".txt"):
            content_type = "text/plain; charset=utf-8"
        size = target.stat().st_size
        start, end, status = 0, max(0, size - 1), 200

        header = self.headers.get("Range") or ""
        if header.startswith("bytes=") and size:
            spec = header[len("bytes=") :].split(",")[0].strip()
            first, _, last = spec.partition("-")
            try:
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                elif last:
                    start = max(0, size - int(last))
                    end = size - 1
            except ValueError:
                start, end = 0, size - 1
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206

        length = end - start + 1 if size else 0
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not length:
            return
        try:
            with target.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(262_144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (OSError, BrokenPipeError, ConnectionResetError):
            return  # the client seeked away or closed the player

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "Not found"})
        method = path[len("/api/"):].strip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return self._json(400, {"ok": False, "error": "Malformed JSON body"})
        if not isinstance(payload, dict):
            return self._json(400, {"ok": False, "error": "Body must be a JSON object"})
        with self.lock:
            result = self.api.call(method, payload)
        return self._json(200, result)

    # -------------------------------------------------------------- static
    def _static(self, url_path: str) -> None:
        relative = unquote(url_path).lstrip("/") or "index.html"
        if relative.endswith("/"):
            relative += "index.html"
        target = (self.web_dir / relative).resolve()
        if self.web_dir not in target.parents and target != self.web_dir:
            return self._bytes(403, b"Forbidden", "text/plain; charset=utf-8")
        if not target.is_file():
            return self._bytes(404, b"Not found", "text/plain; charset=utf-8")
        suffix = target.suffix.lower()
        content_type = STATIC_TYPES.get(suffix) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        try:
            body = target.read_bytes()
        except OSError:
            return self._bytes(500, b"Could not read file", "text/plain; charset=utf-8")
        return self._bytes(200, body, content_type)


class JadeliServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server(api: Api, host: str = "127.0.0.1", port: int = 0) -> tuple[JadeliServer, int]:
    handler = type("BoundJadeliHandler", (JadeliHandler,), {"api": api, "web_dir": WEB_DIR})
    server = JadeliServer((host, port), handler)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="jadeli-http", daemon=True)
    thread.start()
    return server, actual_port
