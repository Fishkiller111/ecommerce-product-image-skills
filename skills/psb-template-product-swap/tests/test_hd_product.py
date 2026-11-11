import sys
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from hd_product import prepare_hd_product


class ProductHDTests(unittest.TestCase):
    def test_sharpens_existing_details_and_keeps_matte(self):
        source = Image.new('RGBA', (160, 80), (212, 18, 200, 0))
        d = ImageDraw.Draw(source)
        d.rectangle((4, 4, 155, 75), fill=(226, 190, 79, 255))
        d.rectangle((50, 20, 69, 58), fill=(116, 66, 18, 255))
        source_bytes = source.tobytes()
        out, audit = prepare_hd_product(source, (256, 128))
        simple = source.resize(out.size, Image.Resampling.LANCZOS)
        self.assertEqual(source_bytes, source.tobytes())
        self.assertEqual(audit['hd_subject_px'], [384, 192])
        self.assertTrue(audit['source_upscaled_in_layout'])
        self.assertEqual(out.getchannel('A').tobytes(), simple.getchannel('A').tobytes())
        self.assertIsNotNone(ImageChops.difference(out.convert('RGB'), simple.convert('RGB')).getbbox())
        self.assertEqual(out.getpixel((10, 40)), simple.getpixel((10, 40)))

    def test_no_unnecessary_upsampling(self):
        image = Image.new('RGBA', (600, 350), (241, 200, 88, 255))
        out, audit = prepare_hd_product(image, (550, 321))
        self.assertEqual(out.size, image.size)
        self.assertFalse(audit['source_upscaled_in_layout'])

    def test_near_opaque_prepared_png_receives_sharpening(self):
        source = Image.new('RGBA', (160, 80), (230, 190, 50, 254))
        ImageDraw.Draw(source).rectangle((50, 20, 69, 58), fill=(116, 66, 18, 254))
        out, audit = prepare_hd_product(source, (120, 60))
        self.assertEqual(out.size, source.size)
        self.assertEqual(out.getchannel('A').tobytes(), source.getchannel('A').tobytes())
        self.assertNotEqual(out.tobytes(), source.tobytes())

    def test_extremely_small_source_stays_capped(self):
        image = Image.new('RGBA', (30, 20), (241, 200, 88, 255))
        out, audit = prepare_hd_product(image, (420, 280))
        self.assertEqual(out.size, (90, 60))
        self.assertTrue(audit['source_upscaled_in_layout'])


if __name__ == '__main__':
    unittest.main()
