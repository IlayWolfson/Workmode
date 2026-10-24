import unittest

from focus_guard import keys


class ParseChordTest(unittest.TestCase):
    def test_modifier_combo(self):
        self.assertEqual(keys.parse_chord("ctrl+alt+shift+q"), (0x11, 0x12, 0x10, 0x51))

    def test_single_keys(self):
        self.assertEqual(keys.parse_chord("del"), (0x2E,))
        self.assertEqual(keys.parse_chord("PageUp"), (0x21,))
        self.assertEqual(keys.parse_chord("pagedown"), (0x22,))

    def test_function_and_digit_keys(self):
        self.assertEqual(keys.parse_chord("f5"), (0x74,))
        self.assertEqual(keys.parse_chord("7"), (0x37,))

    def test_whitespace_and_case_are_ignored(self):
        self.assertEqual(keys.parse_chord(" Ctrl + Q "), (0x11, 0x51))

    def test_rejects_bad_chords(self):
        for bad in ["", "+", "ctrl+", "ctrl+nope", "ctrl+ctrl", "f13", "ctrl alt q"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    keys.parse_chord(bad)


if __name__ == "__main__":
    unittest.main()
