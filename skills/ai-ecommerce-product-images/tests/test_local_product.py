import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image, ImageChops, ImageDraw

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'local_product.py'
sys.path.insert(0, str(SCRIPT.parent))
import local_product

class LocalProductTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='商品图 测试 '); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def run_tool(self,*args,ok=True,env=None):
        p=subprocess.run([sys.executable,'-X','utf8',str(SCRIPT),*map(str,args)],
                         capture_output=True,encoding='utf-8',env=env)
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
        report=json.loads((out/'review.json').read_text(encoding='utf-8')); self.assertEqual(report['review_status'],'待人工复核');self.assertEqual(report['upscale_ratio'],1)
        self.run_tool(src,'--out',out,ok=False)
    def test_manual_matte_and_mismatched_mask(self):
        src=self.root/'source.png';Image.new('RGB',(100,80),(120,80,50)).save(src)
        mask=Image.new('L',(100,80),0); ImageDraw.Draw(mask).rectangle((25,10,75,70),fill=255); mask.save(self.root/'mask.png')
        self.run_tool(src,'--out',self.root/'good','--mask',self.root/'mask.png','--size','256')
        tone=json.loads((self.root/'good'/'review.json').read_text(encoding='utf-8'))['tone']
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
        report = json.loads((out / 'review.json').read_text(encoding='utf-8'))
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

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'guided contours require OpenCV')
    def test_guided_refinement_restores_omitted_cap_in_both_orientations(self):
        from product_edges import refine_product_mask

        photo = Image.new('RGB', (220, 480), (154, 154, 154))
        seed = Image.new('L', photo.size)
        body = [(57, 30), (158, 30), (143, 350), (133, 360), (84, 360), (74, 350)]
        ImageDraw.Draw(seed).polygon(body, fill=255)
        ImageDraw.Draw(photo).rounded_rectangle((83, 345, 134, 412), radius=9, fill=(167, 166, 164))
        ImageDraw.Draw(photo).polygon(body, fill=(38, 101, 60))
        for rotation in (None, Image.Transpose.ROTATE_90):
            with self.subTest(rotation=rotation):
                src = photo if rotation is None else photo.transpose(rotation)
                mask = seed if rotation is None else seed.transpose(rotation)
                result, report = refine_product_mask(src, mask)
                if rotation is not None:
                    result = result.transpose(Image.Transpose.ROTATE_270)
                self.assertEqual(report['cap_check'], 'recovered-from-edge-evidence')
                self.assertGreater(result.getpixel((108, 405)), 245)
                self.assertEqual(result.getpixel((108, 425)), 0)
                self.assertEqual(result.getpixel((70, 392)), 0)

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'guided contours require OpenCV')
    def test_guided_refinement_does_not_extend_into_a_table_seam(self):
        from product_edges import refine_product_mask

        photo = Image.new('RGB', (220, 480), (154, 154, 154))
        seed = Image.new('L', photo.size)
        body = [(57, 30), (158, 30), (143, 350), (133, 360), (84, 360), (74, 350)]
        ImageDraw.Draw(seed).polygon(body, fill=255)
        ImageDraw.Draw(photo).polygon(body, fill=(38, 101, 60))
        ImageDraw.Draw(photo).rectangle((0, 410, 219, 479), fill=(176, 176, 176))
        result, report = refine_product_mask(photo, seed)
        self.assertEqual(report['cap_check'], 'check-tapered-end')
        self.assertLess(result.getbbox()[3], 366)
        self.assertEqual(result.getpixel((108, 410)), 0)

    def test_windows_prefers_small_cached_model_and_keeps_explicit_choice(self):
        cache = self.root / '权重 目录'
        cache.mkdir()
        small = cache / 'models' / 'u2netp' / 'u2netp.onnx'
        large = cache / 'u2net.onnx'
        with (patch.object(local_product, 'sys', SimpleNamespace(platform='win32')),
              patch.dict(os.environ, {'U2NET_HOME': str(cache)})):
            self.assertEqual(local_product.rembg_model_path(None), ('u2netp', small))
            large.touch()
            self.assertEqual(local_product.rembg_model_path(None), ('u2net', large))
            small.parent.mkdir(parents=True)
            small.touch()
            self.assertEqual(local_product.rembg_model_path(None), ('u2netp', small))
            self.assertEqual(local_product.rembg_model_path('u2net'), ('u2net', large))

    def test_missing_weights_reports_expected_path_without_creating_output(self):
        source = self.root / '商品 原照.png'
        Image.new('RGB', (100, 80), 'white').save(source)
        out = self.root / '白底 输出'
        cache = self.root / '空 模型目录'
        result = self.run_tool(source, '--out', out, '--backend', 'rembg', '--model', 'u2netp',
                               ok=False, env={**os.environ, 'U2NET_HOME': str(cache)})
        self.assertIn(str(cache / 'models' / 'u2netp' / 'u2netp.onnx'), result.stderr)
        self.assertFalse(cache.exists())
        self.assertFalse(out.exists())

    @unittest.skipUnless(os.environ.get('PRODUCT_RUN_MODEL_TESTS') == '1', 'requires prepared u2netp weights')
    def test_cpu_model_exports_matching_white_and_transparent_pngs(self):
        source = self.root / '商品 原照.png'
        out = self.root / '白底 输出'
        original = Image.new('RGB', (512, 512), '#e9e9e9')
        draw = ImageDraw.Draw(original)
        draw.rounded_rectangle((75, 180, 437, 340), radius=20, fill='#f1b91e', outline='#7e391c', width=8)
        draw.ellipse((160, 220, 330, 290), fill='#941f1f')
        original.save(source)
        backend = [] if sys.platform == 'win32' else ['--backend', 'rembg', '--model', 'u2netp']
        result = self.run_tool(source, '--out', out, '--strength', 0, '--sharpness', 0, *backend)
        self.assertEqual(Path(json.loads(result.stdout)['transparent']), out / 'transparent.png')
        report = json.loads((out / 'review.json').read_text(encoding='utf-8'))
        self.assertEqual(report['mask_backend'], 'rembg-u2netp')
        with Image.open(out / 'native_enhanced_rgba.png') as native:
            # Guided refinement can replace mixed-color pixels at the edge.
            # With grading disabled all fully opaque pixels still match the photo.
            difference = ImageChops.difference(native.convert('RGB'), original.crop(report['subject_bbox']))
            opaque = native.getchannel('A').point(lambda value: 255 if value == 255 else 0)
            solid_difference = Image.new('RGB', native.size)
            solid_difference.paste(difference, mask=opaque)
            self.assertIsNone(solid_difference.getbbox())
        with Image.open(out / 'transparent.png') as transparent, Image.open(out / 'white.png') as white:
            self.assertEqual(transparent.size, (1440, 1440))
            alpha = transparent.getchannel('A')
            self.assertEqual(alpha.getpixel((0, 0)), 0)
            self.assertGreater(alpha.getpixel((720, 720)), 245)
            expected = Image.new('RGB', transparent.size, 'white')
            expected.paste(transparent, mask=alpha)
            self.assertEqual(white.tobytes(), expected.tobytes())

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'reference palettes require OpenCV')
    def test_default_run_and_remasking_keep_the_matching_palette(self):
        install = self.root / 'skill'
        scripts = install / 'scripts'
        examples = install / 'examples'
        scripts.mkdir(parents=True)
        examples.mkdir()
        for name in ('local_product.py', 'finish_recipe.py', 'product_edges.py'):
            shutil.copyfile(SCRIPT.with_name(name), scripts / name)
        source = self.root / 'original.png'
        Image.new('RGB', (100, 80), (120, 80, 50)).save(source)
        recipe = examples / 'confirmed.json'
        recipe.write_text(json.dumps({
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'auto_apply': True,
            'outline': [[25, 10], [75, 10], [75, 70], [25, 70]],
            'palette': [{'source': [120, 80, 50], 'target': [222, 170, 80]}],
        }), encoding='utf-8')
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
                    [sys.executable, '-X', 'utf8', str(scripts / SCRIPT.name), str(source), '--out', str(out), *args],
                    capture_output=True, encoding='utf-8',
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads((out / 'review.json').read_text(encoding='utf-8'))
                self.assertEqual(Path(report['finish_recipe']), recipe.resolve())
                self.assertEqual(report['mask_backend'], backend)
                self.assertEqual(report['tone']['method'], method)

if __name__=='__main__': unittest.main()
