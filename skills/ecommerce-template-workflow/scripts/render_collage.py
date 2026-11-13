#!/usr/bin/env python3
"""将两张真实商品照片的主体按指定方向、顺序在本机合成一张图。"""
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

SKILL = Path(__file__).absolute().parent.parent
CANDIDATES = (SKILL.parent / 'psb-template-product-swap',
              SKILL.resolve().parent / 'psb-template-product-swap')
SWAP = next((p for p in CANDIDATES if (p / 'scripts' / 'render_sku.py').is_file()), CANDIDATES[0])
if not (SWAP / 'scripts' / 'render_sku.py').is_file():
    raise SystemExit('缺少同级 psb-template-product-swap 技能，无法使用本机抠图。')
sys.path.insert(0, str(SWAP / 'scripts'))
if sys.platform == 'darwin' and sys.version_info[:2] == (3, 12):
    import platform
    if platform.machine() == 'arm64':
        sys.path.append(str(SWAP / 'runtime' / 'mac-arm64-cpython312'))
try:
    from PIL import Image, ImageDraw, ImageFilter
    from render_sku import checked_photo_profile, cutout, detail_review, mask_diagnostics
    from studio_light import studio_light
except ImportError as exc:
    raise SystemExit('缺少依赖，请按同级 psb-template-product-swap 的说明安装 Python 依赖。') from exc

MAX_SIDE = 4000
MAX_AREA = 12_000_000


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def parse_size(value):
    match = re.fullmatch(r'(\d{2,4})[xX×](\d{2,4})', value)
    if not match:
        raise argparse.ArgumentTypeError('尺寸格式应为 1080x1440')
    w, h = map(int, match.groups())
    if not (64 <= w <= MAX_SIDE and 64 <= h <= MAX_SIDE and w*h <= MAX_AREA):
        raise argparse.ArgumentTypeError('画布宽高需为 64–4000 像素，且总像素不超过 1200 万')
    return (w, h)


def parse_scale(value):
    try: n = float(value)
    except ValueError: raise argparse.ArgumentTypeError('比例必须为数字')
    if not math.isfinite(n) or not .1 <= n <= 4:
        raise argparse.ArgumentTypeError('单图缩放比例应在 0.1–4 之间')
    return n


def parse_color(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise argparse.ArgumentTypeError('背景色需为 #RRGGBB，例如 #ffffff')
    return tuple(int(value[i:i+2], 16) for i in (1,3,5))


def rotate(image, degree):
    return {0: lambda im: im.copy(),
            90: lambda im: im.transpose(Image.Transpose.ROTATE_90),
            180: lambda im: im.transpose(Image.Transpose.ROTATE_180),
            270: lambda im: im.transpose(Image.Transpose.ROTATE_270)}[degree](image)


def geometry(items, layout, order, gap, canvas):
    """Arrange both upright cutouts on a shared floor, rather than stack them in air.

    In vertical mode, upper means further back on the floor; lower means nearer.
    Product silhouettes remain side by side so neither masks the other's packaging.
    """
    a,b = [items[i] for i in order]
    aw,ah = a['natural']; bw,bh = b['natural']
    natural_gap = gap if gap is not None else max(8, round(min(aw,bw)*.18))
    depth = max(4,round(max(ah,bh)*.06)) if layout == 'vertical' else 0
    cw = aw+bw+natural_gap
    ch = max(ah,bh)+depth
    mx=max(12,round(cw*.12),round(max(aw,bw)*.22)); mt=max(12,round(ch*.06))
    # Leave floor space for wide horizontal packages and their soft shadows.
    mb=max(20,round(ch*.16),round(max(aw,bw)*.18))
    auto_width,auto_height=cw+2*mx,ch+mt+mb
    if canvas is None:
        common=min(1.0,MAX_SIDE/auto_width,MAX_SIDE/auto_height,
                   math.sqrt(MAX_AREA/(auto_width*auto_height)))
        w=max(64,round(auto_width*common)); h=max(64,round(auto_height*common))
        top=round(mt*common)
    else:
        w,h=canvas
        # Fit products and the margins needed by both floor shadows.
        common=min(w/auto_width,h/auto_height)
        top=round((h-ch*common)*mt/(mt+mb))
    dims={i: (max(1,round(items[i]['natural'][0]*common)),
              max(1,round(items[i]['natural'][1]*common))) for i in order}
    final_gap=max(0,round(natural_gap*common)); final_depth=round(depth*common)
    aw,ah=dims[order[0]]; bw,bh=dims[order[1]]
    group_w=aw+bw+final_gap
    left=(w-group_w)//2
    base=top+max(ah,bh)
    rects={order[0]:(left,base-ah,aw,ah),
           order[1]:(left+aw+final_gap,base+final_depth-bh,bw,bh)}
    if any(x<0 or y<0 or x+rw>w or y+rh>=h for x,y,rw,rh in rects.values()):
        raise ValueError('组合超过画布，请增大画布或减小间距')
    return (w,h),rects,natural_gap,final_gap


def contact_for(asset, rect):
    """Find the visible bottom contact of each (possibly irregular) source mask."""
    x,y,w,h=rect
    mask=asset.getchannel('A').point(lambda a: 255 if a>=96 else 0)
    box=mask.getbbox()
    if not box: raise ValueError('主体蒙版没有可见的不透明区域')
    band_h=max(2,round(h*.015))
    band_y=max(box[1],box[3]-band_h)
    band=mask.crop((0,band_y,w,box[3])).getbbox()
    if not band: raise ValueError('无法识别商品底部的接触轮廓')
    left,right=band[0],band[2]
    return {'point':[x+(left+right)//2,y+box[3]-1],
            'width':max(3,right-left),'visible_bottom':y+box[3]-1}


def make_shadows(size, assets, rects, order):
    """Draw soft, similarly directed floor shadows close to each actual contact."""
    w,h=size
    soft=Image.new('L',size,0); crisp=Image.new('L',size,0)
    ds=ImageDraw.Draw(soft); dc=ImageDraw.Draw(crisp); contacts={}
    widths=[]
    for i in order:
        c=contact_for(assets[i],rects[i]); contacts[i]=c
        cx,cy=c['point']; footprint=c['width']; widths.append(footprint)
        # Same rightward shadow direction for both products. No parts are redrawn.
        cast=max(2,round(footprint*.10)); ry=max(2,round(min(footprint*.075,h*.02)))
        ds.ellipse((cx-footprint*.48+cast,cy-ry*.25,
                    cx+footprint*.50+cast,cy+ry*2.0),fill=72)
        dc.ellipse((cx-footprint*.46,cy-1,cx+footprint*.46,cy+max(2,ry*.55)),fill=145)
    blur=max(1,round(min(max(widths,default=1)*.035,h*.02)))
    soft=soft.filter(ImageFilter.GaussianBlur(blur))
    crisp=crisp.filter(ImageFilter.GaussianBlur(max(1,round(blur*.25))))
    layer=Image.new('RGBA',size,(45,42,39,0)); layer.putalpha(soft)
    near=Image.new('RGBA',size,(35,33,31,0)); near.putalpha(crisp)
    layer.alpha_composite(near)
    return layer,contacts


def make_floor(size, color, contacts):
    """Add a subtle studio ground plane in the flat preview, not to source pixels."""
    w,h=size
    first=min(c['point'][1] for c in contacts.values())
    horizon=max(0, min(h-1,round(first-h*.20)))
    line=Image.new('RGB',(1,h)); pixels=line.load()
    for y in range(h):
        t=max(0.0,min(1.0,(y-horizon)/max(1,h-horizon)))
        t=t*t*(3-2*t)
        # Very small change makes a continuous plane without adding a false product.
        multiplier=1.0 if y < horizon else .972-.055*t
        pixels[0,y]=tuple(round(c*multiplier) for c in color)
    return line.resize(size).convert('RGBA'),horizon

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image1',type=Path,help='图一：真实商品原照或透明 PNG')
    ap.add_argument('image2',type=Path,help='图二：真实商品原照或透明 PNG')
    ap.add_argument('--layout',choices=['vertical','horizontal'],default='vertical',help='vertical 为同一平面前后错位，horizontal 为同一平面左右排列')
    ap.add_argument('--order',choices=['1-2','2-1'],default='1-2',help='从上到下或从左到右的图号顺序')
    ap.add_argument('--size',type=parse_size,help='固定画布，例如 1080x1440；默认依据原像素和方向自动计算')
    ap.add_argument('--gap',type=int,help='两主体横向间距（原像素坐标）；最终随画布等比缩放')
    ap.add_argument('--scale-1',type=parse_scale,default=1.0,help='仅在用户指定尺寸关系时调整图一，默认 1')
    ap.add_argument('--scale-2',type=parse_scale,default=1.0,help='仅在用户指定尺寸关系时调整图二，默认 1')
    ap.add_argument('--rotate-1',type=int,choices=[0,90,180,270],default=0,help='显式指定图一逆时针旋转角度')
    ap.add_argument('--rotate-2',type=int,choices=[0,90,180,270],default=0,help='显式指定图二逆时针旋转角度')
    ap.add_argument('--photo-profile-1',type=Path,help='仅用于指纹和尺寸匹配图一的轮廓')
    ap.add_argument('--photo-profile-2',type=Path,help='仅用于指纹和尺寸匹配图二的轮廓')
    ap.add_argument('--background',type=parse_color,default=(255,255,255),help='预览底色，默认白色；另输出透明图')
    ap.add_argument('--enhance',action='store_true',help='对两个主体做本地基础调光；默认保留原图观感')
    ap.add_argument('--sku',help='可选唯一编号；省略自动生成')
    ap.add_argument('--out',type=Path,default=Path('outputs/product-collage'))
    args=ap.parse_args()
    output=None
    try:
        sku=args.sku or ('COLLAGE-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        if not re.fullmatch(r'[\w.-]{1,80}',sku) or sku in ('.','..'):
            raise ValueError('编号只允许字母、数字、中文、下划线、点和连字符')
        if args.gap is not None and not 0<=args.gap<=4000:
            raise ValueError('间距必须在 0–4000 范围内')
        sources=[args.image1.expanduser().resolve(strict=True),args.image2.expanduser().resolve(strict=True)]
        source_hashes=[digest(src) for src in sources]
        profiles=[checked_photo_profile(args.photo_profile_1,sources[0]),
                  checked_photo_profile(args.photo_profile_2,sources[1])]
        requested_scales=[args.scale_1,args.scale_2]
        degrees=[args.rotate_1,args.rotate_2]
        # Validate both inputs before creating the no-overwrite output directory.
        items=[]
        with tempfile.TemporaryDirectory(prefix='collage-cutout-') as temp:
            for i,(src,profile) in enumerate(zip(sources,profiles)):
                workspace=Path(temp)/str(i);workspace.mkdir()
                extracted=workspace/'product.png'
                mode=cutout(src,extracted,SWAP/'scripts'/'macos_subject_mask.m',profile)
                with Image.open(extracted) as im:
                    rgba=im.convert('RGBA'); bbox=rgba.getchannel('A').getbbox()
                    if not bbox: raise ValueError(f'图{i+1} 抠图为空')
                    original=rgba.crop(bbox)
                if digest(src) != source_hashes[i]:
                    raise ValueError(f'图{i+1} 在处理期间发生变化，请重新运行')
                product,light=studio_light(original) if args.enhance else (original,None)
                transformed=rotate(product,degrees[i])
                natural=tuple(max(1,round(v*requested_scales[i])) for v in transformed.size)
                info=mask_diagnostics(original.getchannel('A'))
                info['status']='自动诊断不等于通过；须人工对照原照检查轮廓、白色部件和细字'
                items.append({'source':src,'sha256':source_hashes[i],'mode':mode,'bbox':list(bbox),
                              'original':original,'rotated':transformed,'natural':natural,'light':light,
                              'mask':info,'rotation':degrees[i],'requested_scale':requested_scales[i]})
        order=[0,1] if args.order=='1-2' else [1,0]
        size,rects,native_gap,final_gap=geometry(items,args.layout,order,args.gap,args.size)
        assets={}
        for i in order:
            item=items[i]; x,y,w,h=rects[i]
            assets[i]=item['rotated'].resize((w,h),Image.Resampling.LANCZOS) if item['rotated'].size!=(w,h) else item['rotated']
        # A transparent composition retains shadows but never repaints the source goods.
        canvas,contacts=make_shadows(size,assets,rects,order)
        for i in order:
            x,y,_,_=rects[i]
            canvas.alpha_composite(assets[i],(x,y))
        item_reports=[]
        for i,item in enumerate(items):
            x,y,w,h=rects[i]
            detail=detail_review(item['rotated'].size,(w,h),False)
            item_reports.append({'image':i+1,'source_file':str(item['source']),'source_sha256':item['sha256'],
                                 'background_removal':item['mode'],'source_crop_rect':item['bbox'],
                                 'source_subject_px':list(item['original'].size),'rotation_ccw':item['rotation'],
                                 'requested_scale':item['requested_scale'],'placement_rect':[x,y,x+w,y+h],
                                 'contact_point':contacts[i]['point'], 'contact_width_px':contacts[i]['width'],
                                 'detail_review':detail,'mask_review':item['mask'],'studio_light':item['light']})
        insufficient=any(r['detail_review']['status']=='native-detail-insufficient' for r in item_reports)
        suffix='清晰度未达标_勿上架' if insufficient else '待复核'
        publication='至少一件商品主体被放大，仅供版式预览，勿上架' if insufficient else '未经人工验收，需逐件核对商品、轮廓及包装'
        candidate=(args.out/sku).resolve(); candidate.mkdir(parents=True,exist_ok=False); output=candidate
        source_copies=[]; originals=[]
        for i,item in enumerate(items):
            extension=item['source'].suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,8}',extension): extension='.image'
            source_copy=output/f'00_图{i+1}_原始照片{extension}'
            with item['source'].open('rb') as src,source_copy.open('xb') as dst:
                shutil.copyfileobj(src,dst)
            if digest(source_copy)!=item['sha256']:
                raise ValueError(f'图{i+1} 在处理期间发生变化，原照备份无法通过指纹校验')
            source_copies.append(source_copy)
            item_reports[i]['local_source_copy']=str(source_copy)
            p=output/f'0{i+1}_图{i+1}_原像素透明抠图_待复核.png';item['original'].save(p);originals.append(p)
        transparent=output/f'03_拼图透明素材_{suffix}.png'; canvas.save(transparent)
        preview=output/f'04_拼图背景预览_{suffix}.png'
        flat,horizon=make_floor(size,args.background,contacts);flat.alpha_composite(canvas);flat.convert('RGB').save(preview)
        review=output/'05_复核说明.json'
        report={'sku':sku,'type':'product-collage','layout':args.layout,'order':[i+1 for i in order],
                'canvas_px':list(size),'background_rgb':list(args.background),
                'scene':{'type':'shared-ground-plane','floor_start_y':horizon,
                         'shadow_direction':'rightward','geometry':'2d-visual-approximation'},
                'natural_gap_px':native_gap,
                'placed_gap_px':final_gap,'subjects':item_reports,'enhanced':args.enhance,
                'publication':publication,'note':'两图本地抠图，依统一地面做视觉合成与接触阴影；非真实三维重建，实物比例及边缘需人工核对；非可编辑 PSB'}
        review.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'preview':str(preview),'transparent':str(transparent),
                          'source_1':str(source_copies[0]),'source_2':str(source_copies[1]),
                          'subject_1':str(originals[0]),'subject_2':str(originals[1]),
                          'review':str(review),'publication':publication},ensure_ascii=False,indent=2))
    except (OSError,ValueError,RuntimeError,json.JSONDecodeError) as exc:
        if output is not None:
            try: output.rmdir()
            except OSError: pass
        ap.exit(2,f'拼图处理停止：{exc}\n')

if __name__=='__main__': main()
