import struct
import tempfile
import unittest
from pathlib import Path

from focus_guard import icon


class SquareBoxTest(unittest.TestCase):
    def test_landscape_is_cropped_to_the_centered_square(self):
        self.assertEqual(icon.square_box(340, 257), (41, 0, 298, 257))

    def test_portrait_is_cropped_to_the_centered_square(self):
        self.assertEqual(icon.square_box(100, 200), (0, 50, 100, 150))

    def test_square_is_unchanged(self):
        self.assertEqual(icon.square_box(64, 64), (0, 0, 64, 64))


class MakeIconTest(unittest.TestCase):
    def test_writes_a_multi_size_ico_and_creates_the_folder(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "picture.png"
            Image.new("RGB", (340, 257), (30, 120, 200)).save(source)
            target = Path(folder) / "out" / "focus.ico"
            icon.make_icon(source, target)
            header = target.read_bytes()[:6]
        reserved, kind, count = struct.unpack("<HHH", header)
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 4)


if __name__ == "__main__":
    unittest.main()
