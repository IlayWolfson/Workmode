import json
import socket
import unittest
import urllib.error
import urllib.request

from focus_guard.server import make_server, make_update_server, serve_in_thread

TOKEN = "0123456789abcdef"


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.sites = ["github.com", "docs.python.org"]
        self.server = make_server(0, TOKEN, lambda: self.sites, lambda kind, detail: self.events.append((kind, detail)))
        serve_in_thread(self.server)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, method, path, body=None):
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def event(self, **fields):
        return {"token": TOKEN, "type": "tab_closed", "detail": "github.com", **fields}


class AllowedEndpointTest(ServerCase):
    def test_lists_sites_with_the_right_token(self):
        self.assertEqual(self.call("GET", f"/allowed?token={TOKEN}"), (200, {"sites": self.sites, "youtube": None}))

    def test_none_means_do_not_enforce(self):
        self.sites = None
        self.assertEqual(self.call("GET", f"/allowed?token={TOKEN}"), (200, {"sites": None, "youtube": None}))

    def youtube_server(self, lists):
        server = make_server(0, TOKEN, lambda: self.sites, lambda kind, detail: None, get_youtube=lambda: lists)
        serve_in_thread(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def test_sends_youtube_lists(self):
        lists = {"handles": ["@a1"], "channel_ids": [], "names": [], "playlists": []}
        self.youtube_server(lists)
        self.assertEqual(self.call("GET", f"/allowed?token={TOKEN}"), (200, {"sites": self.sites, "youtube": lists}))

    def test_no_youtube_when_not_enforcing(self):
        self.youtube_server({"handles": ["@a1"], "channel_ids": [], "names": [], "playlists": []})
        self.sites = None
        self.assertEqual(self.call("GET", f"/allowed?token={TOKEN}"), (200, {"sites": None, "youtube": None}))

    def test_wrong_or_missing_token_is_forbidden(self):
        self.assertEqual(self.call("GET", "/allowed?token=nope")[0], 403)
        self.assertEqual(self.call("GET", "/allowed")[0], 403)

    def test_unknown_paths_are_not_found(self):
        self.assertEqual(self.call("GET", f"/other?token={TOKEN}")[0], 404)
        self.assertEqual(self.call("POST", "/other", self.event())[0], 404)

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


class EventEndpointTest(ServerCase):
    def test_valid_event_reaches_the_callback(self):
        self.assertEqual(self.call("POST", "/event", self.event())[0], 200)
        self.assertEqual(self.events, [("tab_closed", "github.com")])

    def test_detail_is_truncated(self):
        self.call("POST", "/event", self.event(detail="x" * 500))
        self.assertEqual(len(self.events[0][1]), 80)

    def test_wrong_token_is_forbidden_and_ignored(self):
        self.assertEqual(self.call("POST", "/event", self.event(token="nope"))[0], 403)
        self.assertEqual(self.events, [])

    def test_bad_bodies_are_rejected(self):
        for body in [self.event(type="format_disk"), self.event(detail=5), b"not json", b"[1, 2]", b""]:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/event", body)[0], 400)
        self.assertEqual(self.events, [])

    def test_oversized_body_is_rejected(self):
        self.assertEqual(self.call("POST", "/event", b"x" * 5000)[0], 413)
        self.assertEqual(self.events, [])


class ExclusivePortTest(ServerCase):
    def test_second_server_on_same_port_fails(self):
        port = self.server.server_address[1]
        with self.assertRaises(OSError):
            make_server(port, TOKEN, lambda: [], lambda kind, detail: None)

    def test_the_port_can_be_bound_again_right_after_a_used_server_closes(self):
        port = self.server.server_address[1]
        for _ in range(3):
            self.call("GET", f"/allowed?token={TOKEN}")
        self.server.shutdown()
        self.server.server_close()
        again = make_server(port, TOKEN, lambda: [], lambda kind, detail: None)
        again.server_close()

    def test_a_plain_socket_cannot_share_the_port(self):
        port = self.server.server_address[1]
        other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(other.close)
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError):
            other.bind(("127.0.0.1", port))


class UpdateEndpointTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.started: list[tuple] = []
        self.status = {"installed": "1.2.2", "available": "1.3.0", "state": "ready"}
        self.update = make_update_server(0, TOKEN, lambda: self.status, self.start_apply)
        serve_in_thread(self.update)
        self.addCleanup(self.update.server_close)
        self.addCleanup(self.update.shutdown)
        self.base = f"http://127.0.0.1:{self.update.server_address[1]}"

    def start_apply(self, *args, **kwargs):
        self.started.append((args, kwargs))
        return True

    def test_get_returns_the_status(self):
        self.assertEqual(self.call("GET", f"/update?token={TOKEN}"), (200, self.status))

    def test_update_get_without_token_403(self):
        self.assertEqual(self.call("GET", "/update")[0], 403)
        self.assertEqual(self.call("GET", "/update?token=nope")[0], 403)

    def test_get_update_never_calls_start_apply(self):
        for query in ("", "&apply=1", "&start=true", "&cmd=calc"):
            self.call("GET", f"/update?token={TOKEN}{query}")
        self.assertEqual(self.started, [])

    def test_post_starts_the_fixed_update(self):
        self.assertEqual(self.call("POST", "/update", {"token": TOKEN}), (200, {"started": True}))
        self.assertEqual(self.started, [((), {})])

    def test_update_post_extra_fields_ignored(self):
        body = {"token": TOKEN, "cmd": "calc", "url": "https://evil.example", "version": "0.0.1", "path": "C:/"}
        self.assertEqual(self.call("POST", "/update", body)[0], 200)
        self.assertEqual(self.started, [((), {})])

    def test_update_post_wrong_token_403_and_not_started(self):
        self.assertEqual(self.call("POST", "/update", {"token": "nope"})[0], 403)
        self.assertEqual(self.call("POST", "/update", {})[0], 403)
        self.assertEqual(self.started, [])

    def test_update_post_bad_or_huge_body_not_started(self):
        self.assertEqual(self.call("POST", "/update", b"not json")[0], 400)
        self.assertEqual(self.call("POST", "/update", b"x" * 5000)[0], 413)
        self.assertEqual(self.started, [])

    def test_update_server_has_no_allowed_or_event_route(self):
        self.assertEqual(self.call("GET", f"/allowed?token={TOKEN}")[0], 404)
        self.assertEqual(self.call("POST", "/event", self.event())[0], 404)
        self.assertEqual(self.started, [])

    def test_update_server_binds_loopback_only(self):
        self.assertEqual(self.update.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
