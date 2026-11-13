"""Regression: a low-detail real-photo route still returns a local PSB preview."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


class LocalOriginalPreviewTests(unittest.TestCase):
    def test_small_rgb_jpeg_with_matching_outline_produces_preview_without_api(self):
        with tempfile.TemporaryDirectory(prefix='原图 本地套版 ') as directory:
            tmp = Path(directory)
            source = tmp / '商品原照.jpg'
            outline = tmp / '轮廓.json'
            copy = tmp / '文案.json'
            output = tmp / '结果'
            original = Image.new('RGB', (440, 300), (210, 209, 200))
            draw = ImageDraw.Draw(original)
            draw.rectangle((72, 126, 368, 239), fill=(220, 167, 33))
            draw.rectangle((100, 91, 345, 127), fill=(242, 236, 220))
            draw.rectangle((109, 155, 251, 207), fill=(129, 47, 18))
            original.save(source, quality=88)
            outline.write_text(json.dumps({
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'source_size': list(original.size),
                'outline': [
                    [[72, 126], [368, 126], [368, 239], [72, 239]],
                    [[100, 91], [345, 91], [345, 127], [100, 127]],
                ],
            }), encoding='utf-8')
            requested = {'header': '买5赠一', 'promo': '双十二特惠', 'badge': '商品\n展示',
                         'tag_1': '盒身展示', 'tag_2': '软管展示', 'tag_3': '包装细节'}
            copy.write_text(json.dumps(requested, ensure_ascii=False), encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith('APIMART_')}
            # Deliberately disable auto-mask for this test: the reviewed matching
            # outline must take precedence, and no model, network or API is needed.
            env.update(PYTHONUTF8='1', PSB_CUTOUT_BACKEND='unsupported')
            result = subprocess.run([
                sys.executable, str(ROOT / 'scripts' / 'render_sku.py'), str(source),
                '--sku', '原图预览-001', '--text-json', str(copy),
                '--photo-profile', str(outline), '--out', str(output),
            ], env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            preview = Path(payload['preview'])
            with Image.open(preview) as image:
                image.load()
                self.assertEqual(image.size, (1440, 1440))
                self.assertEqual(image.format, 'PNG')
            self.assertIn('清晰度未达标_待复核', preview.name)
            review = json.loads((preview.parent / '03_复核说明.json').read_text(encoding='utf-8'))
            self.assertEqual(review, payload['review'])
            self.assertEqual(review['edited_text'], requested)
            self.assertEqual(review['background_removal'], 'verified-outline-original-rgb')
            self.assertEqual(review['detail_review']['status'], 'native-detail-insufficient')
            self.assertIn('仅供套版检查', review['publication'])
            self.assertFalse(review['original_promo_retained'])
            with Image.open(source) as decoded, Image.open(payload['cutout']) as cutout:
                self.assertEqual(cutout.mode, 'RGBA')
                self.assertEqual(cutout.getchannel('A').getextrema(), (0, 255))
                self.assertEqual(cutout.size, (297, 149))
                # JPEG bytes are lossy; compare against the exact decoded source RGB.
                expected = decoded.convert('RGB').crop((72, 91, 369, 240))
                self.assertEqual(cutout.convert('RGB').tobytes(), expected.tobytes())


if __name__ == '__main__':
    unittest.main()
