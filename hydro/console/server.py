"""Threaded HTTP server exposing the console routes."""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from hydro.console.controller import Controller
from hydro.console.http import Request
from hydro.domain.errors import ControlError

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "unit-control/1.0"
    controller: Controller

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            path = "/web/overview.html"
        if path.startswith("/web/"):
            self._serve_static(path)
            return
        route = self.controller.router.match(method, path)
        if route is None:
            self._send(
                404,
                {"error": "no route for {} {}".format(method, path), "code": "not-found"},
            )
            return
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        try:
            body = self._read_body()
        except (ValueError, json.JSONDecodeError) as error:
            self._send(400, {"error": str(error), "code": "bad-request"})
            return
        request = Request(method=method, path=path, query=query, body=body)
        try:
            status, payload = route.handler(self.controller, request)
        except ControlError as error:
            status, payload = 409, error.as_dict()
        except (KeyError, ValueError, TypeError) as error:
            status, payload = 400, {"error": str(error), "code": "bad-request"}
        self._send(status, payload)

    def _serve_static(self, path: str) -> None:
        relative = path[len("/web/") :]
        target = (WEB_ROOT / relative).resolve()
        if not str(target).startswith(str(WEB_ROOT)) or not target.is_file():
            self._send(404, {"error": "no such page", "code": "not-found"})
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ControlServer:
    """Owns the HTTP listener lifecycle."""

    def __init__(self, host: str, port: int, controller: Controller) -> None:
        self._controller = controller
        handler = type(
            "BoundRequestHandler",
            (_RequestHandler,),
            {"controller": controller},
        )
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._httpd.server_address[0], self._httpd.server_address[1]
        return str(host), int(port)

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def start_background(self) -> "ControlServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
