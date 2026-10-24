import copy
import unittest

from focus_guard.allowedit import (
    ALREADY,
    BAD_SITE,
    LAST_APP,
    NOT_YOUTUBE,
    SHORT_WORD,
    SiteChoice,
    YouTubeChoice,
    add_app,
    add_site,
    add_youtube,
    remove_app,
    remove_site,
    remove_youtube,
    site_choice,
    word_entry,
    youtube_choices,
)

PLAYLIST = "PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"
CHROME = {"process": "chrome.exe", "launch": ["C:/chrome.exe", "--profile-directory=Profile 1"]}


def raw() -> dict:
    return {"allowed_apps": [dict(CHROME)], "allowed_sites": ["github.com"], "emergency": {"phrase": "x"}}


class SiteChoiceTest(unittest.TestCase):
    def test_a_link_becomes_its_host_without_www(self):
        self.assertEqual(site_choice("https://www.w3schools.com/python/x"), SiteChoice("w3schools.com", "w3schools"))
        self.assertEqual(site_choice("UNI.ac.il"), SiteChoice("uni.ac.il", "uni"))

    def test_junk_is_refused(self):
        for text in ("hello world", "שלום", "http://", "192.168.1.1", "", "localhost"):
            with self.subTest(text=text), self.assertRaises(ValueError) as caught:
                site_choice(text)
            self.assertEqual(str(caught.exception), BAD_SITE)

    def test_word_entry(self):
        self.assertEqual(word_entry(" Uni "), "*uni*")
        with self.assertRaises(ValueError) as caught:
            word_entry("ai")
        self.assertEqual(str(caught.exception), SHORT_WORD)


class SiteEditTest(unittest.TestCase):
    def test_add_and_remove_without_touching_the_input(self):
        before = raw()
        kept = copy.deepcopy(before)
        after = add_site(before, "uni.ac.il")
        self.assertEqual(before, kept)
        self.assertEqual(after["allowed_sites"], ["github.com", "uni.ac.il"])
        self.assertEqual(after["emergency"], {"phrase": "x"})
        self.assertEqual(remove_site(after, "github.com")["allowed_sites"], ["uni.ac.il"])

    def test_twice_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            add_site(raw(), "GitHub.com")
        self.assertEqual(str(caught.exception), ALREADY)


class AppEditTest(unittest.TestCase):
    def test_add_keeps_existing_entries(self):
        after = add_app(raw(), "Code.exe", "C:/VS Code/Code.exe")
        self.assertEqual(after["allowed_apps"], [CHROME, {"process": "Code.exe", "launch": ["C:/VS Code/Code.exe"]}])
        with self.assertRaises(ValueError) as caught:
            add_app(after, "code.exe", "D:/other/Code.exe")
        self.assertEqual(str(caught.exception), ALREADY)

    def test_the_last_app_stays(self):
        with self.assertRaises(ValueError) as caught:
            remove_app(raw(), "chrome.exe")
        self.assertEqual(str(caught.exception), LAST_APP)
        two = add_app(raw(), "Code.exe", "C:/Code.exe")
        self.assertEqual(
            remove_app(two, "CHROME.EXE")["allowed_apps"], [{"process": "Code.exe", "launch": ["C:/Code.exe"]}]
        )


class YouTubeTest(unittest.TestCase):
    def test_a_video_in_a_playlist_offers_all_three(self):
        self.assertEqual(
            youtube_choices(f"https://www.youtube.com/watch?v=aircAruvnKk&list={PLAYLIST}"),
            (
                YouTubeChoice("channel", ""),
                YouTubeChoice("playlist", PLAYLIST),
                YouTubeChoice("video", "aircAruvnKk"),
            ),
        )

    def test_a_channel_link_offers_the_channel(self):
        self.assertEqual(youtube_choices("youtube.com/@3blue1brown"), (YouTubeChoice("channel", "@3blue1brown"),))
        self.assertEqual(
            youtube_choices(f"https://www.youtube.com/playlist?list={PLAYLIST}"), (YouTubeChoice("playlist", PLAYLIST),)
        )

    def test_other_links_are_refused(self):
        for text in ("https://example.com", "", "https://www.youtube.com/shorts/aircAruvnKk", "@", "@a b"):
            with self.subTest(text=text), self.assertRaises(ValueError) as caught:
                youtube_choices(text)
            self.assertEqual(str(caught.exception), NOT_YOUTUBE)

    def test_add_and_remove(self):
        after = add_youtube(raw(), "video", "aircAruvnKk")
        self.assertEqual(after["youtube"], {"videos": ["aircAruvnKk"]})
        with self.assertRaises(ValueError):
            add_youtube(after, "video", "aircAruvnKk")
        self.assertEqual(remove_youtube(after, "video", "aircAruvnKk")["youtube"], {"videos": []})

    def test_a_hand_written_name_is_removable(self):
        data = {**raw(), "youtube": {"channels": ["3Blue1Brown", "@other"]}}
        self.assertEqual(remove_youtube(data, "channel", "3Blue1Brown")["youtube"], {"channels": ["@other"]})
