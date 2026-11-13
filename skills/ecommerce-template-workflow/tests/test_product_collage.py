"""Local regression tests for two-source product collages."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'render_collage.py'

class ProductCollageTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name); self.out=self.root/'output'
        self.a=self.root/'图一.png'; self.b=self.root/'图二.png'
        a=Image.new('RGBA',(300,360)); ImageDraw.Draw(a).rectangle((60,40,239,319),fill=(210,50,40,255)); a.save(self.a)
        b=Image.new('RGBA',(280,300)); ImageDraw.Draw(b).rectangle((80,50,199,249),fill=(30,85,210,255)); b.save(self.b)

    def tearDown(self): self.tmp.cleanup()

    def run_cli(self, sku='case', opts=(), a=None, b=None):
        cmd=[sys.executable,str(SCRIPT),str(a or self.a),str(b or self.b),'--out',str(self.out)]
        if sku is not None: cmd+=['--sku',sku]
        return subprocess.run(cmd+list(opts),capture_output=True,text=True)

    def result(self,r):
        self.assertEqual(r.returncode,0,r.stderr)
        v=json.loads(r.stdout); report=json.loads(Path(v['review']).read_text(encoding='utf-8'))
        return v,report

    def test_vertical_order_uses_depth_on_one_floor_and_keeps_original_pixels(self):
        v,report=self.result(self.run_cli())
        self.assertEqual(report['layout'],'vertical'); self.assertEqual(report['order'],[1,2])
        self.assertEqual(Path(v['source_1']).read_bytes(),self.a.read_bytes())
        self.assertEqual(Path(v['source_2']).read_bytes(),self.b.read_bytes())
        self.assertEqual(Path(report['subjects'][0]['local_source_copy']),Path(v['source_1']))
        a,b=report['subjects']; ar=a['placement_rect']; br=b['placement_rect']
        self.assertEqual(report['scene']['type'],'shared-ground-plane')
        self.assertLess(a['contact_point'][1],b['contact_point'][1])
        self.assertLessEqual(ar[2],br[0]); self.assertLess(br[1],ar[3])  # no floating vertical stack
        self.assertLess(report['scene']['floor_start_y'],a['contact_point'][1])
        self.assertEqual(a['source_subject_px'],[180,280]); self.assertEqual(b['source_subject_px'],[120,200])
        self.assertEqual([ar[2]-ar[0],ar[3]-ar[1]],[180,280])
        self.assertEqual([br[2]-br[0],br[3]-br[1]],[120,200])
        with Image.open(v['subject_1']) as img, Image.open(self.a) as src:
            self.assertEqual(img.tobytes(),src.crop(src.getchannel('A').getbbox()).tobytes())
        with Image.open(v['transparent']) as im, Image.open(v['preview']) as flat:
            self.assertEqual(im.getpixel((0,0))[3],0); self.assertEqual(flat.getpixel((0,0)),(255,255,255))
            self.assertEqual(im.getpixel((ar[0]+10,ar[1]+10)),(210,50,40,255))
            self.assertEqual(im.getpixel((br[0]+10,br[1]+10)),(30,85,210,255))
            for item in (a,b):
                cx,cy=item['contact_point']
                self.assertEqual(cy,item['placement_rect'][3]-1)
                self.assertGreater(im.getpixel((cx,cy+1))[3],0)  # contact shadow, not floating
        self.assertTrue(all(x['detail_review']['status']=='visual-review-required' for x in report['subjects']))

    def test_reversed_vertical_and_horizontal_order(self):
        for layout in ('vertical','horizontal'):
            _,report=self.result(self.run_cli(sku=layout,opts=('--layout',layout,'--order','2-1','--gap','0')))
            ar=report['subjects'][0]['placement_rect']; br=report['subjects'][1]['placement_rect']
            self.assertEqual(report['order'],[2,1]); self.assertEqual(report['placed_gap_px'],0)
            self.assertLessEqual(br[2],ar[0])
            if layout=='vertical':
                self.assertLess(report['subjects'][1]['contact_point'][1],report['subjects'][0]['contact_point'][1])
                self.assertLess(ar[1],br[3])
            else:
                self.assertEqual(report['subjects'][1]['contact_point'][1],report['subjects'][0]['contact_point'][1])

    def test_unequal_scale_and_explicit_rotation_are_recorded_per_source(self):
        _,report=self.result(self.run_cli(opts=('--scale-2','0.5','--rotate-1','90')))
        a,b=report['subjects']; ar=a['placement_rect']; br=b['placement_rect']
        self.assertEqual(a['rotation_ccw'],90); self.assertEqual([ar[2]-ar[0],ar[3]-ar[1]],[280,180])
        self.assertEqual(b['requested_scale'],0.5); self.assertEqual([br[2]-br[0],br[3]-br[1]],[60,100])
        self.assertEqual(b['detail_review']['status'],'visual-review-required')

    def test_requested_enlargement_marks_only_preview_and_still_outputs_both(self):
        v,report=self.result(self.run_cli(opts=('--size','800x1200')))
        self.assertIn('勿上架',v['preview']); self.assertIn('勿上架',v['transparent']); self.assertIn('勿上架',v['publication'])
        self.assertEqual(report['canvas_px'],[800,1200])
        self.assertTrue(any(i['detail_review']['status']=='native-detail-insufficient' for i in report['subjects']))
        self.assertTrue(Path(v['subject_1']).is_file()); self.assertTrue(Path(v['subject_2']).is_file())

    def test_never_removes_or_overwrites_existing_output(self):
        existing=self.out/'empty'; existing.mkdir(parents=True)
        self.assertNotEqual(self.run_cli(sku='empty').returncode,0); self.assertTrue(existing.is_dir())
        v,_=self.result(self.run_cli(sku='not-empty'))
        p=Path(v['preview']); before=hashlib.sha256(p.read_bytes()).digest()
        self.assertNotEqual(self.run_cli(sku='not-empty').returncode,0); self.assertEqual(before,hashlib.sha256(p.read_bytes()).digest())

    def test_invalid_inputs_fail_without_fabricating_results(self):
        self.assertNotEqual(self.run_cli(opts=('--gap','-1')).returncode,0)
        self.assertNotEqual(self.run_cli(opts=('--scale-2','nan')).returncode,0)
        self.assertNotEqual(self.run_cli(opts=('--size','9000x9000')).returncode,0)
        self.assertNotEqual(self.run_cli(a=self.root/'missing.png').returncode,0)
        blank=self.root/'blank.png';Image.new('RGBA',(20,20)).save(blank)
        self.assertNotEqual(self.run_cli(a=blank).returncode,0)
        self.assertFalse(self.out.exists())

    def test_wide_subjects_have_room_for_a_nonclipped_contact_shadow(self):
        wide=self.root/'wide.png'; other=self.root/'other.png'
        im=Image.new('RGBA',(1100,160)); ImageDraw.Draw(im).rectangle((20,35,1079,124),fill=(99,80,60,255)); im.save(wide)
        im=Image.new('RGBA',(350,180)); ImageDraw.Draw(im).ellipse((25,25,324,154),fill=(60,90,150,255)); im.save(other)
        value,report=self.result(self.run_cli(a=wide,b=other,opts=('--layout','horizontal','--order','2-1')))
        with Image.open(value['transparent']) as img:
            box=img.getchannel('A').getbbox(); self.assertLess(box[3],img.height-1)
            self.assertGreater(box[0],0); self.assertLess(box[2],img.width-1)
            for subject in report['subjects']:
                x,y=subject['contact_point']; self.assertGreater(img.getpixel((x,y+1))[3],0)
        self.assertEqual(report['scene']['shadow_direction'],'rightward')
        fixed,_=self.result(self.run_cli(sku='fixed',a=wide,b=other,
                                        opts=('--layout','horizontal','--order','2-1','--size','1200x400')))
        with Image.open(fixed['transparent']) as img:
            box=img.getchannel('A').getbbox()
            self.assertGreater(box[0],0); self.assertLess(box[2],img.width-1)
            self.assertLess(box[3],img.height-1)

    def test_contact_estimation_uses_bottom_mask_not_canvas_center(self):
        irregular=self.root/'irregular.png'
        im=Image.new('RGBA',(200,200)); draw=ImageDraw.Draw(im)
        draw.rectangle((30,20,170,150),fill=(80,160,80,255))
        draw.rectangle((30,150,60,185),fill=(80,160,80,255)); im.save(irregular)
        _,report=self.result(self.run_cli(a=irregular))
        item=report['subjects'][0]; x,y=item['contact_point']; rect=item['placement_rect']
        self.assertLess(x, (rect[0]+rect[2])//2)  # contact is at the actual left foot
        self.assertLess(report['scene']['floor_start_y'],y)

    def test_wrong_source_profile_is_not_used(self):
        profile=self.root/'profile.json';profile.write_text('{"source_sha256":"incorrect"}',encoding='utf-8')
        r=self.run_cli(opts=('--photo-profile-2',str(profile)))
        self.assertNotEqual(r.returncode,0);self.assertIn('指纹不匹配',r.stderr);self.assertFalse(self.out.exists())

    def test_unique_ids_and_user_background(self):
        x,_=self.result(self.run_cli(sku=None,opts=('--background','#eddfef')))
        y,r=self.result(self.run_cli(sku=None,opts=('--background','#eddfef')))
        self.assertNotEqual(x['preview'],y['preview']); self.assertEqual(r['background_rgb'],[237,223,239])
        with Image.open(x['preview']) as img: self.assertEqual(img.getpixel((0,0)),(237,223,239))

if __name__=='__main__': unittest.main()
