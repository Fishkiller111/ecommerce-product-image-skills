import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from studio_light import studio_light


class StudioLightTests(unittest.TestCase):
    def test_lifts_yellow_and_neutral_without_redrawing_ink_or_alpha(self):
        samples = [(192, 152, 3, 254), (181, 180, 178, 255), (83, 25, 15, 255),
                   (252, 250, 246, 255), (190, 150, 10, 0), (192, 152, 3, 8)]
        src = Image.new('RGBA', (len(samples), 1))
        src.putdata(samples)
        out, report = studio_light(src)
        self.assertEqual(out.getchannel('A').tobytes(), src.getchannel('A').tobytes())
        self.assertEqual(out.getpixel((4, 0)), samples[4])
        self.assertEqual(out.getpixel((5, 0)), samples[5])
        y = out.getpixel((0, 0))
        self.assertTrue(235 <= y[0] <= 249 and y[1] > 197 and y[2] < 20)
        white = out.getpixel((1, 0))
        self.assertTrue(203 <= white[0] <= 222 and max(white[:3]) - min(white[:3]) <= 3)
        self.assertTrue(max(abs(a-b) for a,b in zip(out.getpixel((2, 0)), samples[2])) <= 2)
        self.assertLess(out.getpixel((3, 0))[2], 255)
        self.assertGreater(report['median_luma_after'], report['median_luma_before'])

    def test_underlit_product_gets_extra_lift_but_black_does_not(self):
        dark = Image.new('RGBA', (20, 10), (106, 86, 20, 255))
        dark.putpixel((0, 0), (22, 19, 17, 255))
        out, report = studio_light(dark)
        self.assertGreater(report['shadow_lift'], 1.5)
        self.assertGreater(report['median_luma_after'] - report['median_luma_before'], 35)
        self.assertEqual(out.getpixel((0, 0)), dark.getpixel((0, 0)))
        black = Image.new('RGBA', (10, 10), (31, 30, 28, 255))
        out, report = studio_light(black)
        self.assertEqual(report['shadow_lift'], 1.0)
        self.assertEqual(out.tobytes(), black.tobytes())


if __name__ == '__main__':
    unittest.main()
