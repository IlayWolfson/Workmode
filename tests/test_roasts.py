import json
import random
import unittest
import urllib.error

from focus_guard import roasts


class CleanTest(unittest.TestCase):
    def test_strips_numbering_bullets_and_quotes(self):
        self.assertEqual(roasts.clean_line('1. "שוב בורחים?"', 12), "שוב בורחים?")
        self.assertEqual(roasts.clean_line("- hello world", 12), "hello world")
        self.assertEqual(roasts.clean_line("2) keep going", 12), "keep going")

    def test_truncates_to_the_word_limit(self):
        self.assertEqual(roasts.clean_line("a b c d e f", 3), "a b c")

    def test_blank_input_gives_empty_and_only_the_first_line_is_used(self):
        self.assertEqual(roasts.clean_line("", 5), "")
        self.assertEqual(roasts.clean_line("   ", 5), "")
        self.assertEqual(roasts.clean_line("one two\nthree", 5), "one two")

    def test_parse_lines_cleans_drops_blanks_and_duplicates(self):
        raw = "1. aaa bbb\n\n2) aaa bbb\n- ccc ddd eee\n"
        self.assertEqual(roasts.parse_lines(raw, 12), ["aaa bbb", "ccc ddd eee"])


class FallbackTest(unittest.TestCase):
    def test_fallback_lines_are_short_and_non_empty(self):
        self.assertEqual(len(roasts.FALLBACK), 15)
        for line in roasts.FALLBACK:
            with self.subTest(line=line):
                self.assertTrue(1 <= len(line.split()) <= 12)


class RequestTest(unittest.TestCase):
    def test_key_travels_in_a_header_only(self):
        request = roasts.build_request("m1", "SECRET", "be funny", 10, "he")
        self.assertIn("/models/m1:generateContent", request.full_url)
        self.assertNotIn("SECRET", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "SECRET")
        self.assertEqual(request.get_method(), "POST")
        text = json.loads(request.data)["contents"][0]["parts"][0]["text"]
        self.assertIn("be funny", text)
        self.assertIn("10", text)

    def test_parse_response(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "a\nb"}]}}]}
        self.assertEqual(roasts.parse_response(payload), "a\nb")
        for bad in [{}, {"candidates": []}, [], None, {"candidates": [{"content": {}}]}]:
            with self.subTest(bad=bad):
                self.assertEqual(roasts.parse_response(bad), "")


class FakeResponse:
    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class FakeOpener:
    def __init__(self, raw=b"", error=None):
        self.raw, self.error, self.calls = raw, error, []

    def __call__(self, request, timeout=None):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return FakeResponse(self.raw)


def gemini_payload(text):
    return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode("utf-8")


class FetcherTest(unittest.TestCase):
    def make(self, opener, env):
        return roasts.GeminiFetcher("m1", "be funny", "he", 12, env=env, opener=opener, timeout=5)

    def test_returns_cleaned_lines_up_to_the_count(self):
        opener = FakeOpener(gemini_payload("1. one two\n2. three four\n3. five six"))
        lines = self.make(opener, {"GEMINI_API_KEY": "k"})(2)
        self.assertEqual(lines, ["one two", "three four"])
        self.assertEqual(opener.calls[0][1], 5)

    def test_missing_key_makes_no_request(self):
        opener = FakeOpener(gemini_payload("x"))
        self.assertEqual(self.make(opener, {})(5), [])
        self.assertEqual(opener.calls, [])

    def test_network_errors_and_bad_json_give_no_lines(self):
        for opener in [
            FakeOpener(error=urllib.error.URLError("down")),
            FakeOpener(error=TimeoutError()),
            FakeOpener(raw=b"not json"),
        ]:
            with self.subTest(opener=opener.error or "bad json"):
                self.assertEqual(self.make(opener, {"GEMINI_API_KEY": "k"})(5), [])


class StockTest(unittest.TestCase):
    def make(self, fetch, refill_at=1, spawn=lambda function: function()):
        return roasts.RoastStock(fetch, 4, refill_at, rng=random.Random(1), spawn=spawn, fallback=("fb1", "fb2"))

    def test_serves_fetched_lines_then_falls_back(self):
        calls = []

        def fetch(count):
            calls.append(count)
            return ["a", "b"] if len(calls) == 1 else []

        stock = self.make(fetch)
        stock.prime()
        self.assertEqual([stock.next(), stock.next()], ["a", "b"])
        self.assertIn(stock.next(), ("fb1", "fb2"))

    def test_refills_when_the_stock_runs_low(self):
        calls = []

        def fetch(count):
            calls.append(count)
            return ["x1", "x2", "x3"]

        stock = self.make(fetch)
        stock.prime()
        stock.next()
        self.assertEqual(len(calls), 1)
        stock.next()
        self.assertEqual(len(calls), 2)

    def test_only_one_refill_runs_at_a_time(self):
        pending = []
        stock = self.make(lambda count: ["a"], spawn=pending.append)
        stock.next()
        stock.next()
        self.assertEqual(len(pending), 1)
        pending[0]()
        self.assertEqual(stock.next(), "a")

    def test_a_failing_fetch_falls_back_without_crashing(self):
        def fetch(count):
            raise RuntimeError("boom")

        stock = self.make(fetch)
        stock.prime()
        self.assertIn(stock.next(), ("fb1", "fb2"))


if __name__ == "__main__":
    unittest.main()
