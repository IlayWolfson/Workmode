"""Local HTTP bridge for the Chrome extension: 127.0.0.1 only, token required."""

import hmac
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 2048
MAX_DETAIL = 80
EVENT_TYPES = frozenset({"tab_closed", "blocked_site"})


def _same(supplied: object, token: str) -> bool:
    return hmac.compare_digest(str(supplied).encode("utf-8"), token.encode("utf-8"))


def make_server(
    port: int,
    token: str,
    get_sites: Callable[[], Sequence[str] | None],
    on_event: Callable[[str, str], None],
    get_youtube: Callable[[], Mapping[str, list[str]] | None] = lambda: None,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *args: object) -> None:
            pass

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if status == 413:
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parts = urlparse(self.path)
            if parts.path != "/allowed":
                return self._send(404, {"error": "not found"})
            supplied = parse_qs(parts.query).get("token", [""])[0]
            if not _same(supplied, token):
                return self._send(403, {"error": "forbidden"})
            sites = get_sites()
            if sites is None:
                return self._send(200, {"sites": None, "youtube": None})
            youtube = get_youtube()
            return self._send(200, {"sites": list(sites), "youtube": None if youtube is None else dict(youtube)})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/event":
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            if length <= 0:
                return self._send(400, {"error": "empty body"})
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if not isinstance(data, dict):
                return self._send(400, {"error": "bad body"})
            if not _same(data.get("token", ""), token):
                return self._send(403, {"error": "forbidden"})
            kind, detail = data.get("type"), data.get("detail", "")
            if kind not in EVENT_TYPES or not isinstance(detail, str):
                return self._send(400, {"error": "bad event"})
            on_event(kind, detail[:MAX_DETAIL])
            return self._send(200, {"ok": True})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread
