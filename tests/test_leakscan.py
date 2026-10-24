import unittest

from tools.leakscan import Terms, mask, scan_paths, scan_text

PHRASE = "a long enough fake phrase"
TERMS = Terms(secrets=(PHRASE,), personal=("someone@example.com", "Jane Example"))


class ScanTextTest(unittest.TestCase):
    def test_a_secret_is_found_but_never_shown(self):
        hits = scan_text("docs/notes.md", f"line one\nthe phrase is {PHRASE}\n", TERMS)
        self.assertEqual([(hit.kind, hit.line) for hit in hits], [("secret", 2)])
        self.assertNotIn(PHRASE, hits[0].shown)

    def test_key_shaped_strings_are_secrets(self):
        hits = scan_text("x.py", 'key = "AIza' + "B" * 35 + '"\ntoken = "ghp_' + "a" * 36 + '"\n', TERMS)
        self.assertEqual([hit.kind for hit in hits], ["secret", "secret"])

    def test_personal_details(self):
        text = "path C:\\Users\\Someone\\x\nmail SOMEONE@example.com\nby Jane Example\n"
        hits = scan_text("README.md", text, TERMS)
        self.assertEqual([(hit.kind, hit.line) for hit in hits], [("personal", 1), ("personal", 2), ("personal", 3)])

    def test_placeholders_are_not_personal(self):
        text = "C:\\Users\\<name>\\x and C:/Users/Public/y and %USERPROFILE%\n"
        self.assertEqual(scan_text("README.md", text, TERMS), [])

    def test_a_clean_file_has_no_hits(self):
        self.assertEqual(scan_text("focus_guard/x.py", "print('hello')\n", TERMS), [])


class ScanPathsTest(unittest.TestCase):
    def test_private_notes_and_stray_files(self):
        hits = scan_paths(
            ["docs/argon-briefing.md", ".superpowers/x.md", "config.json", "state/events.json", "focus_guard/app.py"]
        )
        self.assertEqual(
            [(hit.where, hit.kind) for hit in hits],
            [
                ("docs/argon-briefing.md", "private-note"),
                (".superpowers/x.md", "private-note"),
                ("config.json", "stray"),
                ("state/events.json", "stray"),
            ],
        )


class MaskTest(unittest.TestCase):
    def test_mask_keeps_two_characters(self):
        self.assertEqual(mask("abcdef"), "ab…")
