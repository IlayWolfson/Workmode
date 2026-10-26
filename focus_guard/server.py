"""Local HTTP bridge for the Chrome extension: 127.0.0.1 only, token required."""

import hmac
import json
import socket
import threading
from collections.abc import Callable, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 2048
DISCARD_CAP = 65536  # a refused body up to this size is read first, so the client gets the answer
MAX_DETAIL = 80
EVENT_TYPES = frozenset({"tab_closed", "blocked_site"})


def _same(supplied: object, token: str) -> bool:
    return hmac.compare_digest(str(supplied).encode("utf-8"), token.encode("utf-8"))


class ExclusiveServer(ThreadingHTTPServer):
    """No port sharing: with SO_REUSEADDR another local process could bind the same port and receive the token."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(BaseHTTPRequestHandler):
    timeout = 5
    token = ""

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

    def _discard(self, length: int) -> None:
        """Read (and drop) a body before answering without it: on Windows, closing with unread data resets the
        connection, and the client sees an error instead of the answer. Never more than DISCARD_CAP bytes."""
        if 0 < length <= DISCARD_CAP:
            self.rfile.read(length)

    def _not_found(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        self._discard(length)
        self._send(404, {"error": "not found"})

    def _query_token_ok(self) -> bool:
        supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        if _same(supplied, self.token):
            return True
        self._send(403, {"error": "forbidden"})
        return False

    def _body(self) -> dict | None:
        """The JSON object sent with the right token; None after answering the error."""
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._discard(length)
            self._send(413, {"error": "too large"})
            return None
        if length <= 0:
            self._send(400, {"error": "empty body"})
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            self._send(400, {"error": "bad json"})
            return None
        if not isinstance(data, dict):
            self._send(400, {"error": "bad body"})
            return None
        if not _same(data.get("token", ""), self.token):
            self._send(403, {"error": "forbidden"})
            return None
        return data


def make_server(
    port: int,
    token: str,
    get_sites: Callable[[], Sequence[str] | None],
    on_event: Callable[[str, str], None],
    get_youtube: Callable[[], Mapping[str, list[str]] | None] = lambda: None,
) -> ThreadingHTTPServer:
    class Handler(_Handler):
        def do_GET(self) -> None:
            if urlparse(self.path).path != "/allowed":
                return self._send(404, {"error": "not found"})
            if not self._query_token_ok():
                return None
            sites = get_sites()
            if sites is None:
                return self._send(200, {"sites": None, "youtube": None})
            youtube = get_youtube()
            return self._send(200, {"sites": list(sites), "youtube": None if youtube is None else dict(youtube)})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/event":
                return self._not_found()
            data = self._body()
            if data is None:
                return None
            kind, detail = data.get("type"), data.get("detail", "")
            if kind not in EVENT_TYPES or not isinstance(detail, str):
                return self._send(400, {"error": "bad event"})
            on_event(kind, detail[:MAX_DETAIL])
            return self._send(200, {"ok": True})

    Handler.token = token
    return ExclusiveServer(("127.0.0.1", port), Handler)


def make_update_server(
    port: int, token: str, status: Callable[[], dict], start_apply: Callable[[], bool]
) -> ThreadingHTTPServer:
    """The app's update-only bridge. GET only reads the status; POST starts the fixed update command and takes
    nothing from the request but the token."""

    class Handler(_Handler):
        def do_GET(self) -> None:
            if urlparse(self.path).path != "/update":
                return self._send(404, {"error": "not found"})
            if not self._query_token_ok():
                return None
            return self._send(200, status())

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/update":
                return self._not_found()
            if self._body() is None:
                return None
            return self._send(200, {"started": bool(start_apply())})

    Handler.token = token
    return ExclusiveServer(("127.0.0.1", port), Handler)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread
