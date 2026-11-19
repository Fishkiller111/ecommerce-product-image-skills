import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from composite_white import compose_to_white, save_new_atomic


class CompositeWhiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_alpha_composition_and_no_overwrite(self):
        src = self.root/'transparent.png'
        im = Image.new('RGBA', (12, 12), (0, 0, 0, 0))
        im.putpixel((5, 5), (10, 40, 90, 255))
        im.putpixel((6, 5), (200, 100, 50, 128))
        im.save(src)
        with Image.open(src) as loaded:
            out = compose_to_white(loaded)
        self.assertEqual(out.mode, 'RGB')
        self.assertEqual(out.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(out.getpixel((5, 5)), (10, 40, 90))
        self.assertEqual(out.getpixel((6, 5)), (227, 177, 152))
        dest = self.root/'white.png'
        save_new_atomic(out, dest)
        before = dest.read_bytes()
        with self.assertRaises(FileExistsError):
            save_new_atomic(out, dest)
        self.assertEqual(dest.read_bytes(), before)

    def test_white_png_has_no_alpha(self):
        p = self.root/'white.png'
        Image.new('RGB', (8, 8), 'white').save(p)
        with Image.open(p) as im:
            with self.assertRaisesRegex(ValueError, '没有 alpha'):
                compose_to_white(im)

    def test_fake_alpha_is_rejected(self):
        p = self.root/'opaque.png'
        Image.new('RGBA', (8, 8), (10, 20, 30, 255)).save(p)
        with Image.open(p) as im:
            with self.assertRaises(ValueError): compose_to_white(im)
        p2 = self.root/'empty.png'
        Image.new('RGBA', (8, 8), (0, 0, 0, 0)).save(p2)
        with Image.open(p2) as im:
            with self.assertRaises(ValueError): compose_to_white(im)

    def test_nontransparent_corner_rejected(self):
        p = self.root/'border.png'
        im = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
        im.putpixel((0, 0), (1, 1, 1, 255)); im.save(p)
        with Image.open(p) as loaded:
            with self.assertRaisesRegex(ValueError, '四角'): compose_to_white(loaded)

if __name__ == '__main__': unittest.main()
