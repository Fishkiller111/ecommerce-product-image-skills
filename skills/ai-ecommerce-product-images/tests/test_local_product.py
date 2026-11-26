import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'local_product.py'

class LocalProductTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def run_tool(self,*args,ok=True):
        p=subprocess.run([sys.executable,str(SCRIPT),*map(str,args)],capture_output=True,text=True)
        if ok: self.assertEqual(p.returncode,0,p.stderr)
        else: self.assertNotEqual(p.returncode,0)
        return p
    def test_alpha_identity_and_white_composition_and_no_overwrite(self):
        image=Image.new('RGBA',(100,80),(0,0,0,0)); draw=ImageDraw.Draw(image)
        draw.rectangle((25,10,75,70),fill=(123,67,34,255));draw.rectangle((40,30,60,36),fill=(15,12,10,255))
        src=self.root/'source.png'; image.save(src); out=self.root/'out'
        self.run_tool(src,'--out',out,'--size','256','--upscale-limit','1','--strength','0','--sharpness','0')
        native=Image.open(out/'native_original_rgba.png'); enhanced=Image.open(out/'native_enhanced_rgba.png')
        self.assertEqual(native.tobytes(),enhanced.tobytes())
        transparent=Image.open(out/'transparent.png').convert('RGBA'); white=Image.open(out/'white.png').convert('RGB')
        self.assertEqual(transparent.getpixel((0,0))[3],0); self.assertEqual(white.getpixel((0,0)),(255,255,255))
        expected=Image.new('RGB',transparent.size,'white'); expected.paste(transparent,mask=transparent.getchannel('A'))
        self.assertEqual(expected.tobytes(),white.tobytes())
        report=json.loads((out/'review.json').read_text()); self.assertEqual(report['review_status'],'待人工复核');self.assertEqual(report['upscale_ratio'],1)
        self.run_tool(src,'--out',out,ok=False)
    def test_manual_matte_and_mismatched_mask(self):
        src=self.root/'source.png';Image.new('RGB',(100,80),(120,80,50)).save(src)
        mask=Image.new('L',(100,80),0); ImageDraw.Draw(mask).rectangle((25,10,75,70),fill=255); mask.save(self.root/'mask.png')
        self.run_tool(src,'--out',self.root/'good','--mask',self.root/'mask.png','--size','256')
        tone=json.loads((self.root/'good'/'review.json').read_text())['tone']
        self.assertGreater(tone['median_luma_after'],tone['median_luma_before']+15)
        self.assertGreater(tone['median_chroma_after'],tone['median_chroma_before'])
        with Image.open(self.root/'good'/'white.png') as white, Image.open(self.root/'good'/'transparent.png') as transparent:
            self.assertEqual(white.getpixel((128,128)),transparent.getpixel((128,128))[:3])
            self.assertNotEqual(white.getpixel((128,128)),(120,80,50))
        bad=self.root/'bad.png'; Image.new('L',(4,4),255).save(bad)
        self.run_tool(src,'--out',self.root/'bad','--mask',bad,ok=False)
        self.assertFalse((self.root/'bad').exists())

    def test_bright_saturated_stock_and_dark_print_keep_their_colors(self):
        source = self.root / 'saturated.png'
        original = Image.new('RGBA', (100, 80))
        draw = ImageDraw.Draw(original)
        draw.rectangle((10, 10, 89, 69), fill=(13, 19, 23, 255))
        draw.rectangle((10, 10, 28, 69), fill=(22, 73, 234, 255))
        original.save(source)
        out = self.root / 'saturated'
        self.run_tool(source, '--out', out, '--sharpness', '0')
        with Image.open(out / 'native_enhanced_rgba.png') as image:
            self.assertEqual(image.tobytes(), original.crop((10, 10, 90, 70)).tobytes())

    def test_neutral_sample_corrects_cast_from_opaque_material(self):
        source = self.root / 'cast.png'
        original = Image.new('RGBA', (100, 80))
        draw = ImageDraw.Draw(original)
        draw.rectangle((10, 10, 89, 69), fill=(108, 111, 94, 255))
        draw.rectangle((30, 25, 69, 54), fill=(169, 113, 40, 255))
        original.save(source)
        out = self.root / 'neutral'
        self.run_tool(source, '--out', out, '--neutral-rect', 12, 12, 26, 22)
        with Image.open(out / 'native_enhanced_rgba.png') as image:
            neutral = image.getpixel((8, 8))[:3]
            self.assertLessEqual(max(neutral) - min(neutral), 1)
            self.assertEqual(image.getchannel('A').getextrema(), (255, 255))
        self.run_tool(source, '--out', self.root / 'invalid-neutral',
                      '--neutral-rect', 35, 29, 65, 50, ok=False)

    def test_soft_source_alpha_is_preserved_even_without_opaque_pixels(self):
        source = self.root / 'soft.png'
        original = Image.new('RGBA', (100, 80))
        draw = ImageDraw.Draw(original)
        draw.ellipse((15, 10, 85, 70), fill=(108, 111, 94, 92))
        draw.ellipse((25, 20, 75, 60), fill=(108, 111, 94, 110))
        original.save(source)
        out = self.root / 'soft'
        self.run_tool(source, '--out', out)
        with Image.open(out / 'mask.png') as matte:
            self.assertEqual(matte.tobytes(), original.getchannel('A').tobytes())
        report = json.loads((out / 'review.json').read_text())
        self.assertEqual(report['tone']['measurement_region'], 'high-alpha')

    def test_opaque_refinement_cleans_the_antialiased_transition(self):
        source = self.root / 'dark-on-white.png'
        mask_path = self.root / 'hard.png'
        mask = Image.new('L', (100, 80))
        ImageDraw.Draw(mask).polygon([(15, 15), (86, 25), (70, 66), (21, 60)], fill=255)
        mask.save(mask_path)
        original = Image.new('RGB', mask.size, 'white')
        original.paste((35, 55, 68), (0, 0, *mask.size), mask)
        original.save(source)
        out = self.root / 'hard'
        self.run_tool(source, '--out', out, '--mask', mask_path, '--edge-mode', 'opaque',
                      '--strength', '0', '--sharpness', '0')
        with Image.open(out / 'native_enhanced_rgba.png') as image:
            partial_rgb = {pixel[:3] for pixel in image.getdata() if 0 < pixel[3] < 255}
            self.assertEqual(partial_rgb, {(35, 55, 68)})
            self.assertEqual(image.getpixel((35, 25)), (35, 55, 68, 255))

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'reference palettes require OpenCV')
    def test_default_run_and_remasking_keep_the_matching_palette(self):
        install = self.root / 'skill'
        scripts = install / 'scripts'
        examples = install / 'examples'
        scripts.mkdir(parents=True)
        examples.mkdir()
        for name in ('local_product.py', 'finish_recipe.py'):
            shutil.copyfile(SCRIPT.with_name(name), scripts / name)
        source = self.root / 'original.png'
        Image.new('RGB', (100, 80), (120, 80, 50)).save(source)
        recipe = examples / 'confirmed.json'
        recipe.write_text(json.dumps({
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'auto_apply': True,
            'outline': [[25, 10], [75, 10], [75, 70], [25, 70]],
            'palette': [{'source': [120, 80, 50], 'target': [222, 170, 80]}],
        }))
        mask_path = self.root / 'updated-mask.png'
        mask = Image.new('L', (100, 80))
        ImageDraw.Draw(mask).rectangle((30, 15, 70, 65), fill=255)
        mask.save(mask_path)

        for name, args, backend, method in (
            ('default', [], 'source-traced-outline', 'reference-palette'),
            ('remasked', ['--mask', str(mask_path)], 'user-mask', 'reference-palette'),
            ('keep-color', ['--strength', '0'], 'source-traced-outline', 'preserve-exposure-and-color'),
        ):
            with self.subTest(name=name):
                out = self.root / name
                result = subprocess.run(
                    [sys.executable, str(scripts / SCRIPT.name), str(source), '--out', str(out), *args],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads((out / 'review.json').read_text())
                self.assertEqual(Path(report['finish_recipe']), recipe.resolve())
                self.assertEqual(report['mask_backend'], backend)
                self.assertEqual(report['tone']['method'], method)

if __name__=='__main__': unittest.main()
