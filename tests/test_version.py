import unittest

from focus_guard.version import VERSION, parse_version


class ParseVersionTest(unittest.TestCase):
    def test_compares_numerically(self):
        self.assertGreater(parse_version("1.10.0"), parse_version("1.9.9"))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_the_built_in_version_parses(self):
        parse_version(VERSION)

    def test_refuses_anything_but_three_numbers(self):
        for text in ("1.2", "1.2.3.4", "v1.2.3", " 1.2.3", "1.2.3 ", "1.2.x", "", "1..3", "+1.2.3", "1.2.3\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_version(text)


if __name__ == "__main__":
    unittest.main()
