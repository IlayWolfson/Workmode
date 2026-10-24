import random
import tempfile
import unittest
from pathlib import Path

from focus_guard.config import VIDEO_SUFFIXES
from focus_guard.songs import RecentSongs, library, pick


class PickTest(unittest.TestCase):
    def test_pick_avoids_last_three(self):
        songs = [Path(f"{n}.mp3") for n in "abcd"]
        for seed in range(50):
            self.assertEqual(pick(songs, ["a.mp3", "b.mp3", "c.mp3"], random.Random(seed)).name, "d.mp3")

    def test_pick_with_two_songs_avoids_only_the_last(self):
        songs = [Path("a.mp3"), Path("b.mp3")]
        for seed in range(20):
            self.assertEqual(pick(songs, ["x.mp3", "a.mp3"], random.Random(seed)).name, "b.mp3")

    def test_single_song_is_always_picked(self):
        self.assertEqual(pick([Path("a.mp3")], ["a.mp3"], random.Random(1)).name, "a.mp3")

    def test_pick_uses_every_song_over_time(self):
        songs = [Path(f"{n}.mp3") for n in "abcdef"]
        rng = random.Random(3)
        self.assertEqual({pick(songs, [], rng).name for _ in range(200)}, {s.name for s in songs})

    def test_empty_library_is_an_error(self):
        with self.assertRaises(ValueError):
            pick([], [], random.Random(1))


class LibraryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.bundled = self.dir / "songs"
        self.bundled.mkdir()
        for name in ["one.wav", "two.mp3", "notes.txt"]:
            (self.bundled / name).write_bytes(b"x")
        self.own = self.dir / "mine.mp3"
        self.own.write_bytes(b"x")

    def test_library_falls_back_to_bundled_when_nothing_usable(self):
        expected = [self.bundled / "one.wav", self.bundled / "two.mp3"]
        self.assertEqual(library(self.bundled, []), expected)
        self.assertEqual(library(self.bundled, ["C:/missing.mp3", str(self.dir / "x.txt")]), expected)

    def test_m4a_is_not_used(self):  # MCI cannot play it; see cueplayer
        m4a = self.dir / "other.m4a"
        m4a.write_bytes(b"x")
        self.assertEqual(library(self.bundled, [str(m4a)]), [self.bundled / "one.wav", self.bundled / "two.mp3"])

    def test_configured_files_are_used_alone(self):
        self.assertEqual(library(self.bundled, [str(self.own)]), [self.own])

    def test_bare_name_is_found_in_bundled_dir(self):
        self.assertEqual(library(self.bundled, ["two.mp3", str(self.own)]), [self.bundled / "two.mp3", self.own])

    def test_missing_bundled_dir_gives_empty(self):
        self.assertEqual(library(self.dir / "nope", []), [])


class RecentSongsTest(unittest.TestCase):
    def test_keeps_the_last_three_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            recent = RecentSongs(Path(tmp) / "state" / "recent_songs.json")
            self.assertEqual(recent.load(), [])
            for name in ["a.mp3", "b.mp3", "c.mp3", "d.mp3"]:
                recent.push(Path("C:/x") / name)
            self.assertEqual(recent.load(), ["b.mp3", "c.mp3", "d.mp3"])

    def test_corrupt_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent_songs.json"
            path.write_text('{"a": 1}', encoding="utf-8")
            self.assertEqual(RecentSongs(path).load(), [])


if __name__ == "__main__":
    unittest.main()


class VideoLibraryTest(unittest.TestCase):
    def test_videos_follow_the_song_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            bundled = Path(folder) / "videos"
            bundled.mkdir()
            (bundled / "built.mp4").write_bytes(b"x")
            (bundled / "LICENSES.md").write_text("x")
            mine = Path(folder) / "mine.webm"
            mine.write_bytes(b"x")
            self.assertEqual(library(bundled, [str(mine)], VIDEO_SUFFIXES), [mine])
            self.assertEqual(library(bundled, ["built.mp4"], VIDEO_SUFFIXES), [bundled / "built.mp4"])
            self.assertEqual(library(bundled, [], VIDEO_SUFFIXES), [bundled / "built.mp4"])
            self.assertEqual(library(Path(folder) / "none", [], VIDEO_SUFFIXES), [])
