import sys
import unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from white_background import make_images, lift_deeply_underexposed

class WhiteBackgroundTests(unittest.TestCase):
    def test_dark_cutout_lift_and_alpha_white(self):
        im=Image.new('RGBA',(120,100),(0,0,0,0))
        for y in range(10,90):
            for x in range(20,100): im.putpixel((x,y),(106,86,20,255))
        im.putpixel((50,50),(22,19,17,255))
        raw, w0, _=make_images(im,256,False)
        enhanced, white, rep=make_images(im,256,True)
        self.assertEqual(raw.getchannel('A').tobytes(),enhanced.getchannel('A').tobytes())
        self.assertEqual(white.getpixel((0,0)),(255,255,255))
        self.assertEqual(enhanced.getpixel((0,0))[3],0)
        self.assertGreater(rep['tone']['median_luma_after'], rep['tone']['median_luma_before'])
        self.assertEqual(enhanced.size,(256,256))
    def test_deep_color_lift_preserves_black_ink_and_alpha(self):
        im=Image.new('RGBA',(40,40),(58,42,9,255))
        im.putpixel((5,5),(10,9,8,255))
        im.putpixel((0,0),(4,5,6,0))
        out, report=lift_deeply_underexposed(im)
        self.assertTrue(report['applied'])
        self.assertGreater(out.getpixel((20,20))[0],58)
        self.assertEqual(out.getpixel((5,5)),im.getpixel((5,5)))
        self.assertEqual(out.getpixel((0,0)),im.getpixel((0,0)))
        black=Image.new('RGBA',(10,10),(27,27,27,255))
        self.assertFalse(lift_deeply_underexposed(black)[1]['applied'])

    def test_empty_fails(self):
        with self.assertRaises(ValueError): make_images(Image.new('RGBA',(20,20)),256)
    def test_invalid_size_fails(self):
        with self.assertRaises(ValueError): make_images(Image.new('RGBA',(20,20)),10)

if __name__=='__main__': unittest.main()
