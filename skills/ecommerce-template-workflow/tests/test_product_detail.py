"""Functional checks for local product-detail outputs; no external service required."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'render_detail.py'

class ProductDetailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root/'source.png'
        im = Image.new('RGBA',(800,1000),(0,0,0,0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((170,100,630,900),radius=30,fill=(220,145,60,255))
        d.rectangle((240,250,560,600),fill=(70,30,60,255))
        im.save(self.src)
        self.out = self.root/'out'

    def tearDown(self): self.tmp.cleanup()

    def run_cli(self, copy=None, sku='case', extra=(), source=None):
        cmd=[sys.executable,str(SCRIPT),str(source or self.src),'--out',str(self.out),'--size','480x640']
        if sku is not None: cmd.extend(['--sku',sku])
        if copy is not None:
            cp=self.root/'copy.json'; cp.write_text(json.dumps(copy,ensure_ascii=False),encoding='utf-8')
            cmd.extend(['--text-json',str(cp)])
        cmd.extend(extra)
        return subprocess.run(cmd,text=True,capture_output=True)

    def test_hero_preserves_source_copy_and_produces_detail_not_psb(self):
        copy={'title':'外观展示 5 件','subtitle':'包装细节','points':['正面展示','细节展示'],
              'layout':'hero','palette':'sage'}
        r=self.run_cli(copy); self.assertEqual(r.returncode,0,r.stderr)
        output=json.loads(r.stdout); report=json.loads(Path(output['review']).read_text())
        self.assertEqual(report['type'],'product-detail'); self.assertEqual(report['copy'],copy)
        self.assertEqual(report['detail_review']['status'],'visual-review-required')
        self.assertEqual(report['background_removal'],'provided-alpha')
        self.assertNotIn('template_sha256',report)
        original=Image.open(self.src); out=Image.open(output['cutout'])
        self.assertEqual(out.tobytes(),original.crop(original.getchannel('A').getbbox()).tobytes())
        with Image.open(output['preview']) as preview:
            self.assertEqual(preview.size,(480,640))
        self.assertTrue(Path(output['background']).is_file())
        self.assertIn('待人工',output['publication'])

    def test_features_all_points_kept_and_use_different_regions(self):
        copy={'title':'外观说明','subtitle':'细节展示','points':['一','二','三','四','五','六'],
              'layout':'features','palette':'lavender'}
        r=self.run_cli(copy); self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout); report=json.loads(Path(result['review']).read_text())
        self.assertEqual(report['copy']['points'],copy['points'])
        self.assertEqual(len(report['text_layout']['points']),12)
        point_rect=report['text_layout']['points'][1]['rect']; product_rect=report['placement']['rect']
        self.assertLess(point_rect[2],product_rect[0])

    def test_small_input_is_labeled_preview_and_no_overwrite(self):
        tiny=self.root/'tiny.png'; Image.new('RGBA',(30,45),(120,130,140,255)).save(tiny)
        # A valid tiny transparent foreground rather than a flat opaque image.
        im=Image.new('RGBA',(30,45)); ImageDraw.Draw(im).rectangle((5,5,24,40),fill=(120,130,140,255)); im.save(tiny)
        r=self.run_cli(source=tiny); self.assertEqual(r.returncode,0,r.stderr)
        result=json.loads(r.stdout); p=Path(result['preview']); before=hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(result['detail_status'],'native-detail-insufficient')
        self.assertIn('勿上架',p.name); self.assertIn('勿上架',result['publication'])
        retry=self.run_cli(source=tiny); self.assertNotEqual(retry.returncode,0)
        self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())

    def test_existing_empty_output_directory_is_never_removed(self):
        existing=self.out/'already-there'; existing.mkdir(parents=True)
        r=self.run_cli(sku='already-there')
        self.assertNotEqual(r.returncode,0)
        self.assertTrue(existing.is_dir())

    def test_invalid_or_overflowing_copy_fails_without_silent_truncation(self):
        r=self.run_cli({'title':'测试'*60,'points':[],'layout':'hero'})
        self.assertNotEqual(r.returncode,0); self.assertIn('无法完整放入版面',r.stderr)
        self.assertFalse(any(self.out.rglob('*.png')))
        r=self.run_cli({'title':'测试','palette':[]},sku='bad-palette')
        self.assertNotEqual(r.returncode,0); self.assertIn('palette',r.stderr)
        r=self.run_cli({'title':'测试','points':['一']*7},sku='too-many')
        self.assertNotEqual(r.returncode,0); self.assertIn('拆成多张',r.stderr)

    def test_custom_background_and_automatic_distinct_ids(self):
        bg=self.root/'background.png'; Image.new('RGB',(700,700),(170,200,230)).save(bg)
        r1=self.run_cli(sku=None,extra=('--background',str(bg)))
        r2=self.run_cli(sku=None,extra=('--background',str(bg)))
        self.assertEqual(r1.returncode,0,r1.stderr); self.assertEqual(r2.returncode,0,r2.stderr)
        x,y=json.loads(r1.stdout),json.loads(r2.stdout)
        self.assertNotEqual(x['preview'],y['preview'])
        report=json.loads(Path(x['review']).read_text())
        self.assertEqual(report['background']['type'],'provided')
        self.assertEqual(report['copy']['title'],'商品展示')
        self.assertEqual(report['copy']['points'],[])

    def test_wrong_photo_profile_rejected(self):
        p=self.root/'profile.json'; p.write_text('{"source_sha256":"not-the-source"}')
        r=self.run_cli(extra=('--photo-profile',str(p)))
        self.assertNotEqual(r.returncode,0); self.assertIn('指纹不匹配',r.stderr)
        self.assertFalse(self.out.exists())

if __name__=='__main__': unittest.main()
