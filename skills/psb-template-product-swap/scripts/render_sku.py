#!/usr/bin/env python3
"""Render the fixed PSB template directly to PNG. No Photoshop required."""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    from psd_tools import PSDImage
    from hd_product import prepare_hd_product
    from studio_light import studio_light
    from platform_support import load_font, check_glyphs, local_mask
except ImportError as exc:
    raise SystemExit('缺少依赖：请用 python -m pip install -r requirements.txt 安装依赖') from exc

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / 'template.json').read_text(encoding='utf-8'))

def layer_map(psd):
    return {layer.layer_id: layer for layer in psd.descendants()}

def load_edits(path):
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path else {}
    if not isinstance(data, dict):
        raise ValueError('文案必须是 JSON 对象')
    edits = []
    hero = {}
    for key, value in data.items():
        if key in ('hero_title', 'hero_subtitle'):
            limit = 16 if key == 'hero_title' else 24
            if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
                raise ValueError(f'{key} 须为一行非空短文字（最多 {limit} 字）')
            hero[key] = value.strip()
            continue
        if key not in PROFILE['text_layers'] or not isinstance(value, str) or not value.strip():
            raise ValueError(f'无效的文字字段：{key}')
        value = value.replace('\r\n', '\n').replace('\r', '\n')
        ref = PROFILE['text_layers'][key]
        if len(value) > 80 or value.count('\n') != ref['before'].count('\r'):
            raise ValueError(f'{key} 字数过长或行数不符')
        if any(ord(c)<32 and c!='\n' for c in value):
            raise ValueError(f'{key} 包含控制字符')
        if value.replace('\n','\r') != ref['before']:
            edits.append((key, ref, value))
    if 'hero_subtitle' in hero and 'hero_title' not in hero:
        raise ValueError('hero_subtitle 须与 hero_title 一起提供')
    return edits, hero

def checked_photo_profile(path, source):
    if not path: return None
    spec = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(spec, dict): raise ValueError('照片配置须为 JSON 对象')
    with source.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != spec.get('source_sha256'):
            raise ValueError('照片指纹不匹配，不能套用其他照片的手工轮廓')
    return spec

def outline_alpha(size, polygons):
    w, h = size
    if not isinstance(polygons, list) or not 1 <= len(polygons) <= 12:
        raise ValueError('轮廓须包含 1–12 个闭合多边形')
    points = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 400:
            raise ValueError('每条轮廓须包含 3–400 个点')
        for xy in polygon:
            if not isinstance(xy, list) or len(xy) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in xy):
                raise ValueError('轮廓点须为有限的 [x,y] 坐标')
            if not (0 <= xy[0] <= w-1 and 0 <= xy[1] <= h-1):
                raise ValueError('轮廓坐标超出源图')
        points.extend(polygon)
    x0, y0 = max(0, math.floor(min(p[0] for p in points))-3), max(0, math.floor(min(p[1] for p in points))-3)
    x1, y1 = min(w, math.ceil(max(p[0] for p in points))+4), min(h, math.ceil(max(p[1] for p in points))+4)
    if (x1-x0)*(y1-y0) > 8_000_000: raise ValueError('轮廓区域过大，请提供较小照片或透明 PNG')
    ss = 4
    hi = Image.new('L', ((x1-x0)*ss, (y1-y0)*ss))
    pen = ImageDraw.Draw(hi)
    for polygon in polygons:
        pen.polygon([(round((x-x0)*ss),round((y-y0)*ss)) for x,y in polygon], fill=255)
    # Area averaging avoids a bright halo or dark overshoot outside the silhouette.
    alpha = Image.new('L', size)
    alpha.paste(hi.resize((x1-x0,y1-y0),Image.Resampling.BOX), (x0,y0))
    return alpha

def verify_template():
    path=ROOT/'templates'/PROFILE['file']
    with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest != PROFILE['sha256']: raise ValueError('模板指纹不匹配，不能沿用图层配置')
    return path

def cutout(source, dest, mask_tool, spec):
    with Image.open(source) as im:
        rgba=ImageOps.exif_transpose(im).convert('RGBA')
        if spec is not None:
            if list(rgba.size) != spec.get('source_size'): raise ValueError('照片尺寸与轮廓配置不一致')
            rgba.putalpha(outline_alpha(rgba.size, spec.get('outline')))
            rgba.save(dest)
            return 'verified-outline-original-rgb'
        if rgba.getchannel('A').getextrema()[0]<255:
            if not rgba.getchannel('A').getbbox(): raise ValueError('输入图像完全透明')
            rgba.save(dest)
            return 'provided-alpha'
    backend = os.environ.get('PSB_CUTOUT_BACKEND', 'auto').lower()
    if backend == 'auto':
        backend = 'vision' if sys.platform == 'darwin' else ('rembg' if sys.platform == 'win32' else 'unsupported')
    if backend == 'rembg':
        mask, model = local_mask(rgba)
        rgba.putalpha(mask)
        rgba.save(dest)
        return 'rembg-' + model + '-mask-original-rgb'
    if backend != 'vision' or sys.platform != 'darwin':
        raise ValueError('当前环境无可用自动抠图；Windows 请安装 requirements-windows.txt，或提供透明 PNG')
    if not shutil.which('xcrun'):
        raise ValueError('缺少 xcrun 编译器；请提供透明 PNG 或安装 Apple 命令行工具')
    # Build in an isolated temporary directory; no application installation.
    compile_result=subprocess.run(['xcrun','clang','-fobjc-arc','-Wno-deprecated-declarations',
        '-framework','Foundation','-framework','Vision','-framework','CoreImage',
        '-framework','ImageIO','-framework','CoreGraphics',str(mask_tool),'-o',str(dest.parent/'mask-tool')],
        text=True,capture_output=True)
    if compile_result.returncode:
        raise RuntimeError('本机抠图组件编译失败：'+compile_result.stderr[-700:])
    mask_path=dest.parent/'mask.png'
    r=subprocess.run([str(dest.parent/'mask-tool'),str(source),str(mask_path)],text=True,capture_output=True)
    if r.returncode:
        raise RuntimeError('系统前景分割不可用：'+(r.stderr or r.stdout)[-700:])
    # Vision provides only the mask. Restore RGB from the actual input image;
    # never retain any generative or color-altered result as the product.
    with Image.open(source) as src, Image.open(mask_path) as mask:
        original=ImageOps.exif_transpose(src).convert('RGBA')
        if original.size != mask.size: raise ValueError('抠图尺寸不匹配；检查源图方向')
        original.putalpha(mask.getchannel('A'))
        original.save(dest)
    return 'macos-vision-mask-original-rgb'

def read_prepared_product(source):
    """Read the exact supplied asset, trimming only almost-transparent debris."""
    with Image.open(source) as im:
        if im.format != 'PNG' or getattr(im, 'is_animated', False):
            raise ValueError('指定高清素材须为静态透明 PNG')
        rgba = ImageOps.exif_transpose(im).convert('RGBA')
    alpha = rgba.getchannel('A')
    low, high = alpha.getextrema()
    if low >= 8 or high < 128:
        raise ValueError('指定高清素材缺少可用透明背景或主体')
    cleaned = alpha.point(lambda a: a if a >= 8 else 0)
    crop = cleaned.getbbox()
    original = rgba.crop(crop)
    ready = original.copy()
    ready.putalpha(cleaned.crop(crop))
    return original, ready, list(crop)

def draw_text(base, psd_layers, edits, artboard):
    if not edits: return
    d=ImageDraw.Draw(base)
    ax,ay=artboard[:2]
    for key, ref, content in edits:
        layer=psd_layers[ref['id']]
        x1,y1,x2,y2=layer.bbox
        x1-=ax; x2-=ax; y1-=ay; y2-=ay
        # Fit each line within the original text bounding box; do not expand the design.
        lines=content.split('\n'); w=x2-x1; h=y2-y1
        min_size=max(12,int(h/len(lines)*0.48)); max_size=max(min_size,int(h/len(lines)*1.15))
        chosen=None
        for size in range(max_size,min_size-1,-1):
            font=load_font('template',size)
            boxes=[d.textbbox((0,0),line,font=font,stroke_width=0) for line in lines]
            widths=[b[2]-b[0] for b in boxes]
            if max(widths,default=0)<=w and size*len(lines)<=h*1.1:
                chosen=(font,boxes,widths,size);break
        if not chosen: raise ValueError(f'{key} 文案过长，无法放入原文字区域')
        font,boxes,widths,size=chosen
        check_glyphs(font,content,key)
        for i,line in enumerate(lines):
            box=boxes[i]; line_y=y1+(h-size*len(lines))/2+i*size-box[1]
            line_x=x1+(w-widths[i])/2-box[0]
            d.text((round(line_x),round(line_y)),line,font=font,fill=(255,255,255,255))

def mask_diagnostics(alpha):
    # Detect transparent holes enclosed inside the foreground silhouette.
    threshold=alpha.point(lambda p: 255 if p>=64 else 0).convert('L')
    inv=ImageOps.invert(threshold)
    padded=Image.new('L',(inv.width+2,inv.height+2),255)
    padded.paste(inv,(1,1))
    ImageDraw.floodfill(padded,(0,0),0,thresh=0)
    hist=padded.histogram(); holes=hist[255]
    return {'interior_hole_pixels': holes, 'status': '人工复核：可能有内部漏抠' if holes>=100 else '人工复核边缘和细字'}

def grade_product(product, spec, lift):
    tone = spec.get('tone', {}) if spec else {}
    if not isinstance(tone, dict): raise ValueError('照片曝光配置须为 JSON 对象')
    lift = tone.get('lift', 1.55 if lift else 1.0)
    gains = tone.get('gains', [1.0,1.0,1.0])
    if type(lift) not in (int,float) or not 1 <= lift <= 2.3 or not isinstance(gains, list) or len(gains)!=3 or any(type(g) not in (int,float) or not 0.88<=g<=1.18 for g in gains):
        raise ValueError('提亮或白平衡参数超出安全范围')
    if lift == 1 and gains == [1.0,1.0,1.0]: return product, {'lift':lift,'gains':gains}
    lut = [round(255*(1-(1-min(1,(i/255)*g))**lift)) for g in gains for i in range(256)]
    rgb = product.convert('RGB').point(lut)
    rgb.putalpha(product.getchannel('A'))
    return rgb, {'lift':lift,'gains':gains}

def plan_product(canvas_width, product, has_title, align='auto'):
    # Artboard-local placement; protect existing header, border and sale panel.
    layout = PROFILE['hero_layout']
    sx1,sy1,sx2,sy2 = layout['slot_with_title' if has_title else 'slot_without_title']
    w,h=product.size
    scale=min(layout['target_width']/w,(sy2-sy1)/h,layout['max_scale'])
    size=(max(1,round(w*scale)),max(1,round(h*scale)))
    x=(sx1+sx2-size[0])//2
    y=sy2-size[1] if has_title or align == 'bottom' else (sy1+sy2-size[1])//2
    if not (sx1<=x and sy1<=y and x+size[0]<=sx2 and y+size[1]<=sy2):
        raise ValueError('商品超出主视觉区域')
    width_share = round(size[0]/canvas_width,3)
    notes = ['实拍像素偏少，需核对细字'] if scale>1.55 else []
    if w/h >= 1.8 and width_share < 0.68:
        notes.append('横向商品未达到建议画面占比；优先换主体更大的原片，不继续插值硬放大')
    return {'rect':[x,y,x+size[0],y+size[1]],'width_share':width_share,
            'source_subject_px':[w,h],'scale':round(scale,3),'notes':notes}

def place_product(base, hd_product, placement):
    x,y,r,b = placement['rect']
    size = (r-x,b-y)
    product = hd_product.resize(size,Image.Resampling.LANCZOS) if hd_product.size != size else hd_product
    shadow = Image.new('L',base.size)
    d = ImageDraw.Draw(shadow)
    foot=y+size[1]
    d.ellipse((x+size[0]*0.04,foot-14,x+size[0]*0.96,foot+21),fill=69)
    shadow=shadow.filter(ImageFilter.GaussianBlur(13))
    allowed = Image.new('L',base.size)
    area = PROFILE['hero_layout']['shadow_safe_rect']
    allowed.paste(shadow.crop(area),area[:2])
    shade = Image.new('RGBA',base.size,(90,48,20,0))
    shade.putalpha(allowed)
    base.alpha_composite(shade)
    base.alpha_composite(product,(x,y))

def draw_hero(base, hero):
    if not hero: return
    d=ImageDraw.Draw(base)
    for key,box,max_size,min_size,fill,stroke in [
        ('hero_title',(130,212,1310,357),139,62,(142,45,19,255),2),
        ('hero_subtitle',(160,371,1280,424),47,26,(155,75,41,255),0),
    ]:
        if key not in hero: continue
        copy=hero[key]; x1,y1,x2,y2=box
        for size in range(max_size,min_size-1,-1):
            f=load_font('hero',size)
            x,y,r,b=d.textbbox((0,0),copy,font=f,stroke_width=stroke)
            if r-x<=x2-x1 and b-y<=y2-y1:
                check_glyphs(f,copy,key)
                d.text(((x1+x2-r+x)//2-x,(y1+y2-b+y)//2-y),copy,font=f,fill=fill,stroke_width=stroke,stroke_fill=fill)
                break
        else: raise ValueError(f'{key} 文案过长，无法放入主视觉区域')

def detail_review(source_size, placement_size, ai_preview):
    """Screen at the input size, not the interpolated canvas or asset size."""
    ratio=max(dst/src for src,dst in zip(source_size,placement_size))
    if ai_preview:
        status='ai-restored-preview-only'
        reason='生成式结果可能重写包装细节，仅供内部对比，禁止上架'
    elif ratio > 1.01:
        status='native-detail-insufficient'
        reason='输入主体需要放大，基础调光与锐化不能恢复缺失笔画；请换未压缩近拍或经核对的清晰素材'
    else:
        status='visual-review-required'
        reason='像素尺寸满足置入，仅为尺寸检查；仍需在成图100%倍率对照包装印字、轮廓和细节'
    return {'status':status,'reason':reason,'input_subject_px':list(source_size),
            'placed_subject_px':list(placement_size),'input_to_placement_scale':round(ratio,3)}

def label_ai_preview(base):
    # Make the non-production status survive sharing outside the output folder.
    draw=ImageDraw.Draw(base)
    font=load_font('hero',28)
    label='AI 修复样张 · 勿上架'
    check_glyphs(font,label,'AI 样张标记')
    x,y,r,b=draw.textbbox((0,0),label,font=font)
    left,top=base.width-(r-x)-48,169
    draw.rounded_rectangle((left-12,top-7,left+r-x+12,top+b-y+7),
                           radius=8,fill=(115,34,20,255))
    draw.text((left-x,top-y),label,font=font,fill='white')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('product',type=Path)
    ap.add_argument('--sku',required=True)
    ap.add_argument('--text-json',type=Path)
    ap.add_argument('--photo-profile',type=Path,help='仅对指纹匹配的实拍使用已核对的轮廓和曝光参数')
    ap.add_argument('--prepared-cutout',action='store_true',help='使用指定透明 PNG，不重抠、不回退；默认仍进行商品调光与高清增强')
    ap.add_argument('--ai-restored-preview',action='store_true',
                    help='标记外部 AI 修复透明素材，仅供内部对比，须同时传 --prepared-cutout')
    look=ap.add_mutually_exclusive_group()
    look.add_argument('--studio-light','--lift',dest='enhance',action='store_true',default=True,
                      help='商品棚拍调光和高清增强（默认开启；兼容旧参数 --lift）')
    look.add_argument('--keep-product-look',dest='enhance',action='store_false',
                      help='关闭商品调光和高清增强，仅保留抠图和等比套版')
    ap.add_argument('--product-align',choices=['auto','bottom'],default='auto',help='商品区布局；bottom 可在不加大标题时贴近底栏')
    ap.add_argument('--out',type=Path,default=Path('outputs/psb-template-swap-direct'))
    args=ap.parse_args()
    created_output = None
    try:
        if args.ai_restored_preview and not args.prepared_cutout:
            raise ValueError('--ai-restored-preview 必须配合 --prepared-cutout；本脚本不会自行调用生成模型')
        if args.prepared_cutout and args.photo_profile:
            raise ValueError('直接使用指定透明素材时不可再传实拍轮廓')
        if not re.fullmatch(r'[\w.-]{1,80}',args.sku) or args.sku in ('.','..'):
            raise ValueError('SKU 只允许字母、数字、中文、下划线、点、连字符')
        source=args.product.resolve(strict=True); edits,hero=load_edits(args.text_json)
        spec=checked_photo_profile(args.photo_profile,source)
        template=verify_template(); output=(args.out/args.sku).resolve()
        output.mkdir(parents=True,exist_ok=False)
        created_output = output
        psd=PSDImage.open(template); layers=layer_map(psd)
        if psd.size != tuple(PROFILE['canvas']) or any(i not in layers for i in [9,42,79]):
            raise ValueError('模板结构不匹配')
        if layers[42].is_visible(): raise ValueError('模板旧商品图层意外可见')
        art=tuple(PROFILE['artboard']['rect'])
        for key,ref,value in edits:
            layer=layers.get(ref['id'])
            if layer is None or not layer.is_visible() or layer.kind!='type': raise ValueError(f'{key} 不是可见文字层')
            layer.visible=False
        # force=True composes actual layer data and ignores the file's blank merged preview.
        base=psd.composite(viewport=art,force=True,ignore_preview=True,apply_icc=True)
        if base is None or base.size != (1440,1440): raise ValueError('画板合成尺寸异常')
        base=base.convert('RGBA')
        light_report=None
        tone=None
        source_meta={}
        if args.prepared_cutout:
            product,working,crop=read_prepared_product(source)
            mode='supplied-prepared-cutout'
            with source.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
            source_meta={'source_sha256':digest,'alpha_trim_floor':8,'source_crop_rect':crop}
        else:
            with tempfile.TemporaryDirectory(prefix='psb-sku-') as temp:
                tmp=Path(temp); transparent=tmp/'product.png'
                mode=cutout(source,transparent,ROOT/'scripts'/'macos_subject_mask.m',spec)
                with Image.open(transparent) as im:
                    product=im.convert('RGBA'); a=product.getchannel('A'); box=a.getbbox()
                    if not box: raise ValueError('前景为空')
                    product=product.crop(box)
            working=product
        quality=mask_diagnostics(working.getchannel('A'))
        if mode == 'macos-vision-mask-original-rgb' or mode.startswith('rembg-'):
            quality['status']='自动蒙版未验收；白色包装和边缘必须逐像素目视复核'
        placement=plan_product(base.width,working,bool(hero),args.product_align)
        x,y,r,b=placement['rect']
        target=(r-x,b-y)
        detail=detail_review(working.size,target,args.ai_restored_preview)
        if args.prepared_cutout and (target[0]>working.width or target[1]>working.height):
            raise ValueError('指定高清素材的有效主体小于模板置入尺寸；未放大或回退到旧图')
        # Both source paths share the same default pre-composite enhancement.
        if args.enhance:
            if spec and 'tone' in spec:
                working,tone=grade_product(working,spec,False)
            working,light_report=studio_light(working)
            hd,hd_report=prepare_hd_product(working,target)
        else:
            hd=working
            hd_report={'method':'keep-product-look','source_subject_px':list(working.size),
                       'hd_subject_px':list(hd.size),'placed_subject_px':list(target),
                       'source_upscaled_in_layout':target[0]>hd.width or target[1]>hd.height,
                       'detail_status':'显式关闭商品调光和高清增强，仅执行套版所需的缩放'}
        hd_report.update(source_meta)
        place_product(base,hd,placement)
        draw_text(base,layers,edits,art)
        draw_hero(base,hero)
        if args.ai_restored_preview:
            label_ai_preview(base)
            cutout_path=output/'01_AI修复输入素材_勿上架.png'
            hd_path=output/'02_AI修复入模素材_勿上架.png'
            result=output/f'{args.sku}_主图_AI修复样张_勿上架.png'
            publication='AI 修复样张，禁止上架；不可作为实物实拍'
        elif detail['status'] == 'native-detail-insufficient':
            cutout_path=output/'01_原像素商品透明抠图_待复核.png'
            hd_path=output/'02_基础增强商品透明素材_清晰度待复核.png'
            result=output/f'{args.sku}_主图_清晰度未达标_待复核.png'
            publication='清晰度未达标，仅供套版检查；请更换素材后重跑'
            print(f'清晰度未达标：{detail["reason"]}',file=sys.stderr)
        else:
            cutout_path=output/'01_原像素商品透明抠图_待复核.png'
            hd_path=output/'02_处理后商品透明素材_待复核.png'
            result=output/f'{args.sku}_主图_待复核.png'
            publication='未验收；需人工核对抠图、商品包装、文字和促销信息'
        product.save(cutout_path)
        hd.save(hd_path)
        base.convert('RGB').save(result)
        review={'template_sha256':PROFILE['sha256'],'sku':args.sku,'source_file':str(source),
                'background_removal':mode,'edited_text':{**{k:v for k,_,v in edits},**hero},
                'placement':placement,'photo_tone':tone,'studio_light':light_report,'hd_preprocessing':hd_report,
                'product_enhancement':'studio-and-hd' if args.enhance else 'keep-product-look',
                'original_promo_retained':not any(k=='promo' for k,_,_ in edits),
                'size':[1440,1440],'quality':quality,'detail_review':detail,'publication':publication,
                'note':'新增文字为重排像素，字体与原模板不保证一致；未生成可编辑 PSB'}
        (output/'03_复核说明.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'preview':str(result),'cutout':str(cutout_path),
                          'hd_product':str(hd_path),'review':review},ensure_ascii=False,indent=2))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        if created_output is not None:
            try: created_output.rmdir()  # remove only an empty directory created by this run
            except OSError: pass
        ap.exit(2,f'处理停止：{exc}\n')

if __name__=='__main__': main()
