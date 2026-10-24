import unittest

from focus_guard.emergency import EmergencyDetector, normalize_phrase, phrase_matches

DEL, PGUP, CTRL, ALT, SHIFT, Q = 0x2E, 0x21, 0x11, 0x12, 0x10, 0x51
COMBO = (CTRL, ALT, SHIFT, Q)


def detector(hold_ms=1500):
    return EmergencyDetector(((DEL,), (PGUP,)), hold_ms, (COMBO,))


class DetectorTest(unittest.TestCase):
    def test_combo_triggers_once_per_press(self):
        d = detector()
        self.assertTrue(d.update({CTRL, ALT, SHIFT, Q}, 0))
        self.assertFalse(d.update({CTRL, ALT, SHIFT, Q}, 50))
        self.assertFalse(d.update(set(), 100))
        self.assertTrue(d.update({CTRL, ALT, SHIFT, Q}, 150))

    def test_partial_combo_does_nothing(self):
        self.assertFalse(detector().update({CTRL, ALT, SHIFT}, 0))

    def test_hold_key_needs_the_full_hold_time(self):
        d = detector()
        self.assertFalse(d.update({DEL}, 0))
        self.assertFalse(d.update({DEL}, 1499))
        self.assertTrue(d.update({DEL}, 1500))
        self.assertFalse(d.update({DEL}, 3000))

    def test_releasing_early_resets_the_hold(self):
        d = detector()
        d.update({DEL}, 0)
        d.update(set(), 1000)
        self.assertFalse(d.update({DEL}, 1100))
        self.assertFalse(d.update({DEL}, 2599))
        self.assertTrue(d.update({DEL}, 2600))

    def test_each_hold_key_is_independent(self):
        d = detector()
        d.update({DEL, PGUP}, 0)
        self.assertTrue(d.update({DEL, PGUP}, 1500))
        self.assertFalse(d.update({PGUP}, 1600))

    def test_zero_hold_time_makes_keys_instant(self):
        self.assertTrue(detector(hold_ms=0).update({DEL}, 0))

    def test_unrelated_keys_never_trigger(self):
        self.assertFalse(detector().update({0x41, 0x42}, 5000))


class PhraseTest(unittest.TestCase):
    PHRASE = "אני לוזר מסריח שלא ימצא עבודה"

    def test_exact_phrase_matches_ignoring_outer_whitespace(self):
        self.assertTrue(phrase_matches("  " + self.PHRASE + "\n", self.PHRASE))

    def test_wrong_empty_and_partial_phrases_do_not_match(self):
        for typed in ["", "   ", self.PHRASE[:-1], self.PHRASE + " x", self.PHRASE.upper() + "!"]:
            with self.subTest(typed=typed):
                self.assertFalse(phrase_matches(typed, self.PHRASE))

    def test_unicode_normalization_forms_match(self):
        self.assertTrue(phrase_matches("café phrase", "café phrase"))
        self.assertEqual(normalize_phrase("é"), "é")

    def test_invisible_marks_and_odd_spaces_do_not_break_the_match(self):
        plain = "אני לוזר מסריח"
        for typed in [plain + "‏", "‏" + plain, "אני לוזר מסריח", "אני  לוזר   מסריח", "אני​לוזר מסריח".replace("​", " ​")]:
            with self.subTest(typed=typed):
                self.assertTrue(phrase_matches(typed, plain))
                self.assertTrue(phrase_matches(plain, typed))

    def test_latin_case_matters_and_an_empty_expected_phrase_never_matches(self):
        self.assertFalse(phrase_matches("Phrase", "phrase"))
        self.assertFalse(phrase_matches("", ""))
        self.assertFalse(phrase_matches("   ", "   "))


if __name__ == "__main__":
    unittest.main()
