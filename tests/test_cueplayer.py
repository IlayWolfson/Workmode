import unittest
from pathlib import Path

from focus_guard.cueplayer import MciPlayer, mci_commands


class MciCommandsTest(unittest.TestCase):
    def test_mci_commands_for_mp3_and_wav(self):
        self.assertEqual(
            mci_commands(Path("C:/s/a.mp3"), "cue"),
            (f'open "{Path("C:/s/a.mp3")}" type mpegvideo alias cue', "play cue from 0", "stop cue", "close cue"),
        )
        self.assertIn("type waveaudio", mci_commands(Path("C:/s/a.WAV"), "cue")[0])

    def test_quote_in_path_is_refused(self):
        with self.assertRaises(ValueError):
            mci_commands(Path('C:/s/a".mp3'), "cue")


class MciPlayerTest(unittest.TestCase):
    def setUp(self):
        self.sent, self.errors, self.fail_on = [], [], None

        def send(command):
            self.sent.append(command)
            return 263 if self.fail_on and command.startswith(self.fail_on) else 0

        self.slept = []
        self.player = MciPlayer(send=send, on_error=self.errors.append, run=lambda job: job(), sleep=self.slept.append)

    def test_each_play_gets_its_own_alias(self):
        self.player.play_clip(Path("C:/s/a.mp3"))
        self.player.play_clip(Path("C:/s/a.mp3"))
        aliases = [command.split()[-1] for command in self.sent if command.startswith("close")]
        self.assertEqual(aliases, ["cue1", "cue2"])

    def test_clip_plays_then_stops_after_the_given_seconds(self):
        self.player.play_clip(Path("C:/s/a.mp3"), seconds=5.0)
        self.assertEqual(self.sent[1:], ["play cue1 from 0", "stop cue1", "close cue1"])
        self.assertEqual(self.slept, [5.0])

    def test_failed_open_is_reported_and_still_closed(self):
        self.fail_on = "open"
        self.player.play_clip(Path("C:/s/a.mp3"))
        self.assertEqual(self.sent[-1], "close cue1")
        self.assertNotIn("play cue1 from 0", self.sent)
        self.assertEqual(self.slept, [])
        self.assertEqual(len(self.errors), 1)
        self.assertIn("263", self.errors[0])

    def test_bad_path_is_reported_not_raised(self):
        self.player.play_clip(Path('C:/s/a".mp3'))
        self.assertEqual((self.sent, len(self.errors)), ([], 1))


if __name__ == "__main__":
    unittest.main()
