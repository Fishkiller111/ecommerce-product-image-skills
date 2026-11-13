#!/usr/bin/env python3
"""在本机将真实商品、独立背景与文字组合为可复核的商品详情图。"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

# Reuse the same local mask and Chinese-font handling as the main-image skill.
SKILL = Path(__file__).absolute().parent.parent
CANDIDATES = (SKILL.parent / 'psb-template-product-swap',
              SKILL.resolve().parent / 'psb-template-product-swap')
SWAP = next((p for p in CANDIDATES if (p / 'scripts' / 'render_sku.py').is_file()), CANDIDATES[0])
if not (SWAP / 'scripts' / 'render_sku.py').is_file():
    raise SystemExit('缺少同级 psb-template-product-swap 技能，无法使用本机抠图和字体。')
sys.path.insert(0, str(SWAP / 'scripts'))
# The included build is for macOS arm64 + CPython 3.12 only. Else install requirements.
if sys.platform == 'darwin' and sys.version_info[:2] == (3, 12):
    import platform
    if platform.machine() == 'arm64':
        sys.path.append(str(SWAP / 'runtime' / 'mac-arm64-cpython312'))
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    from platform_support import load_font, check_glyphs
    from render_sku import checked_photo_profile, cutout, detail_review, mask_diagnostics
    from studio_light import studio_light
except ImportError as exc:
    raise SystemExit('缺少依赖，请按同级 psb-template-product-swap 的说明安装 Python 依赖。') from exc

PALETTES = {
    'lavender': ((248, 244, 255), (220, 207, 247), (102, 61, 159), (232, 220, 255)),
    'sage': ((247, 251, 243), (214, 229, 211), (53, 101, 72), (223, 241, 221)),
    'ocean': ((244, 251, 255), (209, 229, 243), (46, 91, 135), (222, 239, 250)),
    'sand': ((255, 251, 242), (237, 220, 198), (128, 88, 53), (249, 232, 213)),
    'rose': ((255, 247, 249), (245, 215, 224), (143, 73, 96), (252, 226, 233)),
}


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def valid_text(value, label, optional=False):
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise ValueError(f'{label} 必须是非空字符串')
    if len(value) > 120 or any(ord(c) < 32 and c != '\n' for c in value):
        raise ValueError(f'{label} 过长或包含控制字符')
    return value.strip()


def read_copy(path):
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path else {'title': '商品展示'}
    if not isinstance(data, dict) or set(data) - {'title', 'subtitle', 'points', 'palette', 'layout'}:
        raise ValueError('文案只支持 title、subtitle、points、palette、layout 字段')
    result = {'title': valid_text(data.get('title', '商品展示'), 'title'),
              'subtitle': valid_text(data.get('subtitle', ''), 'subtitle', True),
              'palette': data.get('palette', 'lavender'), 'layout': data.get('layout', 'hero')}
    points = data.get('points', [])
    if not isinstance(points, list) or len(points) > 6:
        raise ValueError('points 必须是 0–6 条文字；多于 6 条请拆成多张图')
    result['points'] = [valid_text(p, f'points[{i}]') for i, p in enumerate(points)]
    if not isinstance(result['palette'], str) or not isinstance(result['layout'], str) or result['palette'] not in PALETTES or result['layout'] not in ('hero', 'features'):
        raise ValueError('palette 或 layout 不支持，请按技能说明使用预设')
    return result


def make_background(size, palette, image_path=None):
    w, h = size
    top, bottom, accent, glow_color = PALETTES[palette]
    if image_path:
        with Image.open(image_path) as im:
            base = ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'), size,
                                method=Image.Resampling.LANCZOS).convert('RGBA')
        # Keep text readable even when a supplied background is high-contrast.
        wash = Image.new('RGBA', size, (*top, 65))
        base.alpha_composite(wash)
    else:
        line = Image.new('RGB', (1, h))
        p = line.load()
        for y in range(h):
            t = y / max(1, h - 1)
            p[0, y] = tuple(round(top[i]*(1-t) + bottom[i]*t) for i in range(3))
        base = line.resize(size).convert('RGBA')
    glows = Image.new('RGBA', size)
    d = ImageDraw.Draw(glows)
    d.ellipse((-w*.30, h*.05, w*.45, h*.60), fill=(*glow_color, 125))
    d.ellipse((w*.50, -h*.05, w*1.25, h*.50), fill=(255, 255, 255, 105))
    glows = glows.filter(ImageFilter.GaussianBlur(max(12, round(w*.085))))
    base.alpha_composite(glows)
    deco = Image.new('RGBA', size)
    d = ImageDraw.Draw(deco)
    d.ellipse((w*.44, h*.22, w*1.13, h*.73), outline=(255,255,255,95), width=max(2,w//250))
    d.ellipse((-w*.30, h*.30, w*.35, h*.77), outline=(255,255,255,65), width=max(2,w//300))
    d.line((w*.09,h*.22,w*.09,h*.69), fill=(255,255,255,100), width=max(2,w//400))
    d.line((w*.91,h*.22,w*.91,h*.69), fill=(255,255,255,100), width=max(2,w//400))
    base.alpha_composite(deco)
    return base


def wrap(draw, text, font, width):
    lines=[]
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append(''); continue
        current=''
        for ch in paragraph:
            candidate=current+ch
            if current and draw.textlength(candidate,font=font) > width:
                lines.append(current); current=ch
            else:
                current=candidate
        lines.append(current)
    return lines


def fitted(draw, text, rect, max_size, min_size, max_lines, color, center=True, role='hero'):
    x0,y0,x1,y1 = [round(v) for v in rect]
    width=x1-x0; height=y1-y0
    for size in range(max_size,min_size-1,-1):
        font=load_font(role,size)
        lines=wrap(draw,text,font,width)
        spacing=max(2,round(size*.24))
        # Font bounding boxes may start below the baseline: measure actual bbox.
        boxes=[draw.textbbox((0,0), line or ' ', font=font) for line in lines]
        heights=[max(1,b[3]-b[1]) for b in boxes]
        total=sum(heights)+spacing*(len(lines)-1)
        if len(lines) <= max_lines and total <= height and all(draw.textlength(line,font=font)<=width for line in lines):
            check_glyphs(font,text,'商品详情文案')
            y=y0+(height-total)//2
            for line,box,lh in zip(lines,boxes,heights):
                lw=draw.textlength(line,font=font)
                x=x0+(width-lw)/2 if center else x0
                draw.text((round(x-box[0]),round(y-box[1])),line,font=font,fill=color)
                y+=lh+spacing
            return {'font_size':size,'lines':len(lines),'rect':[x0,y0,x1,y1]}
    raise ValueError(f'文案无法完整放入版面：{text!r}；请缩短、拆页或增大画布')


def compose(size, copy, product, background):
    w,h=size; palette=copy['palette']; accent=PALETTES[palette][2]
    base=background.copy(); overlay=Image.new('RGBA',size)
    d=ImageDraw.Draw(overlay)
    # Three non-overlapping zones: copy header, original product, and optional point list.
    d.rounded_rectangle((w*.055,h*.035,w*.945,h*.208),radius=round(w*.035),fill=(255,255,255,192))
    if copy['layout']=='hero' and copy['points']:
        d.rounded_rectangle((w*.055,h*.80,w*.945,h*.965),radius=round(w*.035),fill=(255,255,255,206))
    elif copy['layout']=='features' and copy['points']:
        d.rounded_rectangle((w*.055,h*.255,w*.49,h*.92),radius=round(w*.03),fill=(255,255,255,190))
    base.alpha_composite(overlay)
    if copy['layout']=='features':
        rect=(w*.50,h*.265,w*.94,h*.80)
    else:
        rect=(w*.09,h*.245,w*.91,h*(.76 if copy['points'] else .90))
    pw,ph=product.size
    scale=min((rect[2]-rect[0])/pw,(rect[3]-rect[1])/ph)
    tw,th=max(1,round(pw*scale)),max(1,round(ph*scale))
    x=round((rect[0]+rect[2]-tw)/2); y=round((rect[1]+rect[3]-th)/2)
    # The shadow follows the product, including wide low-profile packages.
    stage=Image.new('RGBA',size); sd=ImageDraw.Draw(stage)
    sd.ellipse((x+tw*.06,y+th-h*.008,x+tw*.94,y+th+h*.025),fill=(*accent,45))
    stage=stage.filter(ImageFilter.GaussianBlur(max(3,round(w*.012))))
    base.alpha_composite(stage)
    # Resize only; do not rotate, regenerate or rewrite packaging.
    asset=product.resize((tw,th),Image.Resampling.LANCZOS) if (tw,th)!=(pw,ph) else product
    base.alpha_composite(asset,(x,y))
    draw=ImageDraw.Draw(base)
    title_rect=(w*.09,h*.05,w*.91,h*(.134 if copy['subtitle'] else .19))
    text_report={'title':fitted(draw,copy['title'],title_rect,round(w*.072),round(w*.032),2,(*accent,255),role='template')}
    if copy['subtitle']:
        text_report['subtitle']=fitted(draw,copy['subtitle'],(w*.10,h*.14,w*.90,h*.195),round(w*.032),round(w*.019),2,(61,57,69,255))
    reports=[]
    points=copy['points']
    if copy['layout']=='hero' and points:
        cols=2; rows=math.ceil(len(points)/cols)
        for i,p in enumerate(points):
            row,col=divmod(i,cols)
            cell_w=w*.80/cols; cell_h=h*.14/rows
            x0=w*.10+col*cell_w; y0=h*.812+row*cell_h
            reports.append(fitted(draw,p,(x0+w*.015,y0,x0+cell_w-w*.015,y0+cell_h),round(w*.033),round(w*.019),2,(*accent,255)))
    elif points:
        cell_h=h*.62/len(points)
        for i,p in enumerate(points):
            y0=h*.275+i*cell_h
            reports.append(fitted(draw,f'{i+1:02d}',(w*.085,y0,w*.155,y0+cell_h),round(w*.030),round(w*.021),1,(*accent,255)))
            reports.append(fitted(draw,p,(w*.165,y0,w*.46,y0+cell_h),round(w*.030),round(w*.019),3,(*accent,255),center=False))
    if points: text_report['points']=reports
    return base.convert('RGB'), {'rect':[x,y,x+tw,y+th], 'source_subject_px':[pw,ph],
                                'placed_subject_px':[tw,th], 'scale':round(scale,3)}, text_report


def parse_size(s):
    m=re.fullmatch(r'(\d{3,4})[xX×](\d{3,4})',s)
    if not m: raise argparse.ArgumentTypeError('尺寸格式应为 1080x1440')
    w,h=map(int,m.groups())
    if not (480<=w<=3000 and 480<=h<=4000 and .5<=w/h<=1.5):
        raise argparse.ArgumentTypeError('宽 480–3000、高 480–4000，宽高比 0.5–1.5')
    return w,h


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('product',type=Path,help='本次原始商品照片或透明 PNG')
    ap.add_argument('--text-json',type=Path,help='由 Agent 生成的 UTF-8 文案 JSON')
    ap.add_argument('--sku',help='可选唯一编号；省略则自动生成')
    ap.add_argument('--out',type=Path,default=Path('outputs/product-detail'))
    ap.add_argument('--size',type=parse_size,default=(1080,1440),help='默认 1080x1440')
    ap.add_argument('--background',type=Path,help='可选无商品、无文字的背景图')
    ap.add_argument('--photo-profile',type=Path,help='仅用于 SHA-256 和尺寸匹配的已核对原照')
    ap.add_argument('--enhance',action='store_true',help='对商品使用现有本地基础调光；默认保持输入商品观感')
    args=ap.parse_args()
    output=None
    try:
        sku=args.sku or ('DETAIL-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        if not re.fullmatch(r'[\w.-]{1,80}',sku) or sku in ('.','..'):
            raise ValueError('编号只允许字母、数字、中文、下划线、点和连字符')
        source=args.product.expanduser().resolve(strict=True)
        copy=read_copy(args.text_json)
        bgpath=args.background.expanduser().resolve(strict=True) if args.background else None
        if bgpath and bgpath==source: raise ValueError('背景不能使用商品输入图本身')
        spec=checked_photo_profile(args.photo_profile,source)
        candidate=(args.out/sku).resolve()
        candidate.mkdir(parents=True,exist_ok=False)
        output=candidate  # only remove directories this run actually created
        with tempfile.TemporaryDirectory(prefix='detail-cutout-') as temp:
            transparent=Path(temp)/'cutout.png'
            mode=cutout(source,transparent,SWAP/'scripts'/'macos_subject_mask.m',spec)
            with Image.open(transparent) as im:
                rgba=im.convert('RGBA'); bbox=rgba.getchannel('A').getbbox()
                if not bbox: raise ValueError('抠图没有前景')
                original=rgba.crop(bbox)
        mask_info=mask_diagnostics(original.getchannel('A'))
        mask_info['status']='自动检查不等于通过；必须人工对照原图检查轮廓、内部和包装细节'
        working,light=studio_light(original) if args.enhance else (original,None)
        background=make_background(args.size,copy['palette'],bgpath)
        image,placement,text_layout=compose(args.size,copy,working,background)
        detail=detail_review(original.size,tuple(placement['placed_subject_px']),False)
        insufficient=detail['status']=='native-detail-insufficient'
        publication='清晰度未达标，仅看版式，勿上架' if insufficient else '待人工核对原图、包装和文案后方可决定上架'
        preview=output/(sku+'_详情图_'+('清晰度未达标_勿上架' if insufficient else '待复核')+'.png')
        cutout_path=output/'01_原像素商品透明抠图_待复核.png'
        bgout=output/'02_详情背景.png'; copyout=output/'文案.json'; reviewout=output/'03_复核说明.json'
        original.save(cutout_path); background.convert('RGB').save(bgout); image.save(preview)
        copyout.write_text(json.dumps(copy,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        report={'sku':sku,'type':'product-detail','source_file':str(source),'source_sha256':digest(source),
                'background_removal':mode,'background':{'type':'provided' if bgpath else 'local-illustrated',
                'source_sha256':digest(bgpath) if bgpath else None,'palette':copy['palette']},
                'layout':copy['layout'],'canvas_px':list(args.size),'copy':copy,'text_layout':text_layout,
                'placement':placement,'quality':mask_info,'detail_review':detail,'studio_light':light,
                'publication':publication,'note':'非生成式商品合成；抠图、包装文字及文案均需人工核对；扁平 PNG，非可编辑 PSB'}
        reviewout.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'preview':str(preview),'cutout':str(cutout_path),'background':str(bgout),
                          'copy':str(copyout),'review':str(reviewout),'detail_status':detail['status'],
                          'publication':publication},ensure_ascii=False,indent=2))
    except (OSError,ValueError,RuntimeError,json.JSONDecodeError) as exc:
        if output:
            try: output.rmdir()
            except OSError: pass
        ap.exit(2,f'详情图处理停止：{exc}\n')

if __name__=='__main__':
    main()
