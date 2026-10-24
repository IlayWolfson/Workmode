import unittest
from unittest import mock

from focus_guard import audio


class FakeVolume:
    def __init__(self, muted: bool) -> None:
        self.muted = muted

    def GetMute(self) -> int:  # noqa: N802 (pycaw's name)
        return int(self.muted)

    def SetMute(self, muted: int, context: object) -> None:  # noqa: N802 (pycaw's name)
        self.muted = bool(muted)


class FakeSession:
    def __init__(self, muted: bool) -> None:
        self.SimpleAudioVolume = FakeVolume(muted)


class IsMutedTest(unittest.TestCase):
    def check(self, *muted: bool) -> bool:
        sessions = [("discord.exe", FakeSession(state)) for state in muted]
        with (
            mock.patch.object(audio, "_sessions", lambda: iter(sessions)),
            mock.patch.object(audio.comtypes, "CoInitialize"),
        ):
            return audio.Win32Audio().is_muted("Discord.exe")

    def test_a_program_is_muted_only_when_every_session_is_muted(self):
        self.assertTrue(self.check(True, True))
        self.assertFalse(self.check(True, False))  # a new window or call of a muted program is heard

    def test_a_program_without_sessions_is_not_muted(self):
        self.assertFalse(self.check())
