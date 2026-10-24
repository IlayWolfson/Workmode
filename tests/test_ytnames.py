import json
import tempfile
import unittest
from pathlib import Path

from focus_guard.ytnames import Found, TitleCache, lookup

VIDEO_ANSWER = json.dumps(
    {"title": "But what is a neural network?", "author_url": "https://www.youtube.com/@3blue1brown"}
)


class LookupTest(unittest.TestCase):
    def test_a_video_gives_its_title_and_channel(self):
        asked = []

        def fetch(url: str) -> str:
            asked.append(url)
            return VIDEO_ANSWER

        self.assertEqual(lookup("video", "aircAruvnKk", fetch), Found("But what is a neural network?", "@3blue1brown"))
        self.assertEqual(
            asked,
            ["https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DaircAruvnKk&format=json"],
        )

    def test_a_playlist_gives_its_title(self):
        found = lookup("playlist", "PLx1234567890", lambda url: json.dumps({"title": "Neural networks"}))
        self.assertEqual(found, Found("Neural networks", ""))

    def test_offline_or_bad_answers_give_none(self):
        def offline(url: str) -> str:
            raise OSError("offline")

        self.assertIsNone(lookup("video", "aircAruvnKk", offline))
        self.assertIsNone(lookup("video", "aircAruvnKk", lambda url: "not json"))
        self.assertIsNone(lookup("channel", "@x", lambda url: VIDEO_ANSWER))


class TitleCacheTest(unittest.TestCase):
    def test_round_trip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TitleCache(Path(folder) / "state" / "youtube_names.json")
            self.assertEqual(cache.get("video", "aircAruvnKk"), "")
            cache.put("video", "aircAruvnKk", "But what is a neural network?")
            self.assertEqual(TitleCache(cache.path).get("video", "aircAruvnKk"), "But what is a neural network?")


class ChannelFormsTest(unittest.TestCase):
    def test_a_channel_id_address_gives_the_id(self):
        answer = json.dumps({"title": "T", "author_url": "https://www.youtube.com/channel/UCYO_jab_esuFRV4b17AJtAw"})
        self.assertEqual(lookup("video", "aircAruvnKk", lambda url: answer), Found("T", "UCYO_jab_esuFRV4b17AJtAw"))

    def test_an_old_user_address_gives_no_channel(self):
        answer = json.dumps({"title": "T", "author_url": "https://www.youtube.com/user/someone"})
        self.assertEqual(lookup("video", "aircAruvnKk", lambda url: answer), Found("T", ""))
