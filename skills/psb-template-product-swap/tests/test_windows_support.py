import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import platform_support
import render_sku


class WindowsSupportTests(unittest.TestCase):
    def test_windows_font_selection_uses_windir(self):
        with tempfile.TemporaryDirectory() as temp:
            fonts = Path(temp) / 'Fonts'
            fonts.mkdir()
            (fonts / 'msyh.ttc').write_bytes(b'fixture-not-a-real-font')
            env = {'WINDIR': temp, 'PSB_FONT_PATH': '', 'PSB_FONT_DIR': ''}
            with mock.patch.object(platform_support, 'sys', types.SimpleNamespace(platform='win32')), mock.patch.dict(os.environ, env):
                self.assertEqual(platform_support.font_descriptor('hero'), (fonts / 'msyh.ttc', 0))
                self.assertEqual(platform_support.font_descriptor('template'), (fonts / 'msyh.ttc', 0))

    def test_missing_windows_font_fails_with_clear_message(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(platform_support, 'sys', types.SimpleNamespace(platform='win32')), mock.patch.dict(os.environ, {'PSB_FONT_PATH': '', 'PSB_FONT_DIR': temp}):
                with self.assertRaisesRegex(ValueError, 'Windows 中文字体'):
                    platform_support.font_descriptor('hero')

    def test_font_index_validation(self):
        with mock.patch.dict(os.environ, {'PSB_FONT_PATH': __file__, 'PSB_FONT_INDEX': '-1'}):
            with self.assertRaisesRegex(ValueError, 'PSB_FONT'):
                platform_support.font_descriptor('hero')

    def test_disallows_remote_rembg_model(self):
        with mock.patch.dict(os.environ, {'PSB_REMBG_MODEL': 'withoutbg'}):
            with self.assertRaisesRegex(ValueError, '不允许隐式调用云端模型'):
                platform_support.local_mask(Image.new('RGB', (4, 4)))

    def test_local_mask_keeps_source_rgb_and_only_changes_alpha(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / '原图.png'; dest = Path(temp) / '透明.png'
            original = Image.new('RGB', (8, 8), (19, 42, 111)); original.save(source)
            mask = Image.new('L', (8, 8), 0); mask.paste(255, (2, 2, 6, 6))
            fake = types.SimpleNamespace(
                new_session=mock.Mock(return_value='fixture'),
                remove=mock.Mock(return_value=mask),
            )
            with mock.patch.dict(sys.modules, {'rembg': fake}), mock.patch.dict(os.environ, {'PSB_CUTOUT_BACKEND': 'rembg', 'PSB_REMBG_MODEL': 'u2netp'}):
                mode = render_sku.cutout(source, dest, ROOT/'scripts'/'macos_subject_mask.m', None)
            out = Image.open(dest).convert('RGBA')
            self.assertEqual(mode, 'rembg-u2netp-mask-original-rgb')
            self.assertEqual(out.convert('RGB').tobytes(), original.tobytes())
            self.assertEqual(out.getchannel('A').tobytes(), mask.tobytes())
            fake.new_session.assert_called_once_with('u2netp', providers=['CPUExecutionProvider'])
            self.assertTrue(fake.remove.call_args.kwargs['only_mask'])

    def test_bad_size_mask_rejected(self):
        fake = types.SimpleNamespace(new_session=lambda *a, **k: 'x', remove=lambda *a, **k: Image.new('L', (2, 2)))
        with mock.patch.dict(sys.modules, {'rembg': fake}), mock.patch.dict(os.environ, {'PSB_REMBG_MODEL': 'u2netp'}):
            with self.assertRaisesRegex(ValueError, '蒙版尺寸'):
                platform_support.local_mask(Image.new('RGBA', (4, 4)))

    def test_windows_auto_selects_local_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.png'; dest = Path(temp) / 'out.png'
            Image.new('RGB', (8, 8), (10, 20, 30)).save(source)
            mask = Image.new('L', (8, 8), 0); mask.paste(255, (2, 2, 6, 6))
            with mock.patch.object(render_sku, 'sys', types.SimpleNamespace(platform='win32')), mock.patch.object(render_sku, 'local_mask', return_value=(mask, 'u2netp')), mock.patch.dict(os.environ, {'PSB_CUTOUT_BACKEND': 'auto'}):
                self.assertEqual(render_sku.cutout(source, dest, None, None), 'rembg-u2netp-mask-original-rgb')
                self.assertTrue(dest.is_file())

    def test_existing_alpha_never_calls_auto_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.png'; dest = Path(temp) / 'out.png'
            Image.new('RGBA', (8, 8), (10, 20, 30, 128)).save(source)
            with mock.patch.object(render_sku, 'local_mask', side_effect=AssertionError('should not call')):
                self.assertEqual(render_sku.cutout(source, dest, None, None), 'provided-alpha')

    def test_full_template_preview_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='商品 图 ') as temp:
            tmp = Path(temp); source = tmp/'素材.png'; copy = tmp/'文案.json'
            image = Image.new('RGBA', (1600, 700), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((50, 50, 1550, 650), fill=(241, 181, 23, 255))
            image.save(source)
            copy.write_text(json.dumps({'hero_title':'买5赠一','promo':'双十二特惠'},ensure_ascii=False),encoding='utf8')
            command=[sys.executable, str(ROOT/'scripts'/'render_sku.py'), str(source), '--sku','测试-001','--text-json',str(copy),'--prepared-cutout','--keep-product-look','--ai-restored-preview','--out',str(tmp/'输出')]
            first=subprocess.run(command, capture_output=True, text=True, encoding='utf8')
            self.assertEqual(first.returncode, 0, first.stderr)
            review=json.loads((tmp/'输出'/'测试-001'/'03_复核说明.json').read_text(encoding='utf8'))
            self.assertEqual(review['publication'], 'AI 修复样张，禁止上架；不可作为实物实拍')
            self.assertEqual(review['edited_text']['promo'],'双十二特惠')
            self.assertTrue((tmp/'输出'/'测试-001'/'测试-001_主图_AI修复样张_勿上架.png').exists())
            second=subprocess.run(command, capture_output=True, text=True, encoding='utf8')
            self.assertNotEqual(second.returncode, 0)

    @unittest.skipUnless(os.environ.get('PSB_RUN_MODEL_TESTS') == '1', 'optional real ONNX model test')
    def test_real_local_model_inference_preserves_original_pixels(self):
        with tempfile.TemporaryDirectory(prefix='本地蒙版 ') as temp:
            root=Path(temp); source=root/'原图.png'; dest=root/'结果.png'
            image=Image.new('RGB',(512,512),'#e9e9e9')
            draw=ImageDraw.Draw(image)
            draw.rounded_rectangle((75,180,437,340),radius=20,fill='#f1b91e',outline='#7e391c',width=8)
            draw.ellipse((160,220,330,290),fill='#941f1f')
            image.save(source)
            with mock.patch.dict(os.environ, {'PSB_CUTOUT_BACKEND':'rembg','PSB_REMBG_MODEL':'u2netp','REMBG_HOME':str(root/'model-cache')}):
                mode=render_sku.cutout(source,dest,ROOT/'scripts'/'macos_subject_mask.m',None)
            self.assertEqual(mode,'rembg-u2netp-mask-original-rgb')
            result=Image.open(dest).convert('RGBA')
            self.assertEqual(result.size,image.size)
            self.assertEqual(result.convert('RGB').tobytes(),image.tobytes())
            self.assertEqual(result.getchannel('A').getextrema(),(0,255))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows-only batch launcher')
    def test_windows_batch_launcher_accepts_unicode_path(self):
        with tempfile.TemporaryDirectory(prefix='产品图 ') as temp:
            env={**os.environ, 'PSB_PYTHON':sys.executable, 'PYTHONUTF8':'1'}
            command=f'""{ROOT / "run.bat"}" --help"'
            result=subprocess.run(command, shell=True, cwd=temp, env=env, capture_output=True, text=True, encoding='utf8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--sku', result.stdout)

if __name__ == '__main__':
    unittest.main()
