import unittest

from focus_guard.youtube import parse_channel, parse_playlist, parse_video, youtube_lists

PLAYLIST = "PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"


class ParseChannelTest(unittest.TestCase):
    def test_handles_in_every_form(self):
        for text in [
            "@3Blue1Brown",
            " youtube.com/@3blue1brown ",
            "https://www.youtube.com/@3blue1brown/videos",
            "https://m.youtube.com/@3blue1brown?si=x",
        ]:
            self.assertEqual(parse_channel(text), ("handle", "@3blue1brown"), text)

    def test_hebrew_handle_is_decoded(self):
        self.assertEqual(parse_channel("https://www.youtube.com/@%D7%A9%D7%9C%D7%95%D7%9D"), ("handle", "@שלום"))

    def test_channel_ids_keep_case(self):
        for text in ["UCYO_jab_esuFRV4b17AJtAw", "https://www.youtube.com/channel/UCYO_jab_esuFRV4b17AJtAw/about"]:
            self.assertEqual(parse_channel(text), ("id", "UCYO_jab_esuFRV4b17AJtAw"), text)

    def test_names_are_normalized_whole(self):
        self.assertEqual(parse_channel("  3Blue1Brown "), ("name", "3blue1brown"))
        self.assertEqual(parse_channel("3Blue1Brown Shorts"), ("name", "3blue1brown shorts"))

    def test_unusable_channel_links_are_refused(self):
        for text in [
            "",
            "  ",
            "@",
            "youtube.com/c/Numberphile",
            "youtube.com/user/numberphile",
            "https://www.youtube.com/watch?v=aircAruvnKk",
            "https://evil.com/@x",
            "@a b",
        ]:
            with self.assertRaises(ValueError, msg=text):
                parse_channel(text)


class ParsePlaylistTest(unittest.TestCase):
    def test_playlists_from_links_or_ids(self):
        for text in [
            PLAYLIST,
            f" https://www.youtube.com/playlist?list={PLAYLIST} ",
            f"https://www.youtube.com/watch?v=aircAruvnKk&list={PLAYLIST}",
        ]:
            self.assertEqual(parse_playlist(text), PLAYLIST, text)
        for text in ["", "WL", "https://www.youtube.com/watch?v=aircAruvnKk", "PL bad id"]:
            with self.assertRaises(ValueError, msg=text):
                parse_playlist(text)


class ParseVideoTest(unittest.TestCase):
    def test_parse_video_forms(self):
        for text in (
            "aircAruvnKk",
            f"https://www.youtube.com/watch?v=aircAruvnKk&list={PLAYLIST}",
            "youtu.be/aircAruvnKk",
            "https://m.youtube.com/watch?v=aircAruvnKk",
            "https://www.youtube.com/live/aircAruvnKk",
        ):
            self.assertEqual(parse_video(text), "aircAruvnKk", text)
        for text in (
            "https://www.youtube.com/shorts/aircAruvnKk",
            "https://example.com/watch?v=aircAruvnKk",
            "",
            "abc",
        ):
            with self.assertRaises(ValueError, msg=text):
                parse_video(text)


class ListsTest(unittest.TestCase):
    def test_lists_group_and_drop_duplicates(self):
        lists = youtube_lists(["@a1", "youtube.com/@A1", "UCYO_jab_esuFRV4b17AJtAw", "Some Name"], [PLAYLIST])
        self.assertEqual(
            lists.as_json(),
            {
                "handles": ["@a1"],
                "channel_ids": ["UCYO_jab_esuFRV4b17AJtAw"],
                "names": ["some name"],
                "playlists": [PLAYLIST],
                "videos": [],
            },
        )
        self.assertFalse(lists.is_empty())
        self.assertTrue(youtube_lists([], []).is_empty())
