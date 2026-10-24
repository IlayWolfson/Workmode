import io
import unittest

from focus_guard.uilauncher import SubprocessUi


class FakeProcess:
    def __init__(self, command, output):
        self.command, self.code, self.stdout = command, None, io.BytesIO(output)

    def poll(self):
        return self.code


class Spawner:
    def __init__(self):
        self.processes, self.next_output = [], b""

    def __call__(self, command, **kwargs):
        process = FakeProcess(command, self.next_output)
        self.processes.append(process)
        return process


class SubprocessUiTest(unittest.TestCase):
    def setUp(self):
        self.spawn = Spawner()
        self.ui = SubprocessUi("HINT", "BTN", "PROMPT", popen=self.spawn, python="py")

    def test_popup_command_and_single_instance(self):
        self.ui.show_popup("שורה", 10)
        self.assertEqual(
            self.spawn.processes[0].command,
            ["py", "-m", "focus_guard.ui", "popup", "--text=שורה", "--seconds=10", "--hint=HINT", "--button=BTN"],
        )
        self.ui.show_popup("other", 10)
        self.assertEqual(len(self.spawn.processes), 1)
        self.spawn.processes[0].code = 0
        self.ui.show_popup("again", 10)
        self.assertEqual(len(self.spawn.processes), 2)

    def test_show_note_spawns_one_note_at_a_time(self):
        self.ui.show_note("Steam is waiting", 4)
        self.ui.show_note("Steam is waiting", 4)
        self.assertEqual(len(self.spawn.processes), 1)
        self.assertEqual(
            self.spawn.processes[0].command,
            ["py", "-m", "focus_guard.ui", "note", "--text=Steam is waiting", "--seconds=4"],
        )

    def test_text_starting_with_a_dash_is_passed_safely(self):
        self.ui.show_popup("-x --evil", 5)
        self.assertIn("--text=-x --evil", self.spawn.processes[0].command)

    def test_video_and_summary_commands(self):
        self.ui.show_video("C:/clips/a.mp4", 20)
        self.assertEqual(
            self.spawn.processes[0].command,
            ["py", "-m", "focus_guard.ui", "video", "--media=C:/clips/a.mp4", "--seconds=20", "--hint=HINT"],
        )
        self.ui.show_summary("done")
        self.assertEqual(
            self.spawn.processes[1].command,
            ["py", "-m", "focus_guard.ui", "summary", "--text=done", "--seconds=20"],
        )

    def test_phrase_flow_returns_none_while_open_then_the_decoded_text(self):
        self.spawn.next_output = "שלום עולם".encode()
        self.assertIsNone(self.ui.poll_phrase())
        self.ui.ask_phrase()
        self.ui.ask_phrase()
        self.assertEqual(len(self.spawn.processes), 1)
        self.assertIsNone(self.ui.poll_phrase())
        self.spawn.processes[0].code = 0
        self.assertEqual(self.ui.poll_phrase(), "שלום עולם")
        self.assertIsNone(self.ui.poll_phrase())

    def test_closing_the_input_empty_returns_an_empty_string(self):
        self.ui.ask_phrase()
        self.spawn.processes[0].code = 0
        self.assertEqual(self.ui.poll_phrase(), "")


if __name__ == "__main__":
    unittest.main()
