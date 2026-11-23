#!/usr/bin/env python3
"""Local product extraction and non-generative, color-managed-looking tone adjustments."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from finish_recipe import outline_mask, palette_grade, remove_fringe


def local_mask(source, im, backend, model, rect, supplied, tmp):
    size = im.size
    alpha = im.getchannel('A')
    if supplied:
        with Image.open(supplied) as m:
            if m.size != size:
                raise ValueError('蒙版尺寸须与按 EXIF 方向校正后的原图一致')
            # An alpha-only edited PNG or a grayscale mask are both supported.
            return (m.getchannel('A') if 'A' in m.getbands() else m.convert('L')), 'user-mask'
    if backend == 'auto':
        backend = 'alpha' if alpha.getextrema()[0] < 255 else ('vision' if sys.platform == 'darwin' else 'rembg')
    if backend == 'alpha':
        if alpha.getextrema()[0] == 255:
            raise ValueError('源图没有透明背景，不能使用 alpha 模式')
        return alpha, 'source-alpha'
    if backend == 'vision':
        if sys.platform != 'darwin' or not shutil.which('xcrun'):
            raise RuntimeError('Vision 需要 macOS 14+ 和 Xcode Command Line Tools')
        tool = tmp/'mask-tool'
        cmd = ['xcrun','clang','-fobjc-arc','-Wno-deprecated-declarations','-framework','Foundation','-framework','Vision','-framework','CoreImage','-framework','ImageIO','-framework','CoreGraphics',str(Path(__file__).with_name('macos_subject_mask.m')),'-o',str(tool)]
        subprocess.run(cmd, check=True, capture_output=True)
        oriented = tmp/'oriented.png'
        im.save(oriented)
        result=tmp/'vision.png'
        subprocess.run([str(tool),str(oriented),str(result)],check=True,capture_output=True)
        with Image.open(result) as m:
            if m.size != size: raise ValueError('Vision 蒙版尺寸不匹配')
            return m.convert('RGBA').getchannel('A'), 'macOS Vision'
    if backend == 'rembg':
        model_file = Path(os.environ.get('U2NET_HOME', str(Path.home()/'.u2net')))/f'{model}.onnx'
        if not model_file.is_file():
            raise RuntimeError(f'本机未安装模型权重 {model_file}；请先配置本地权重或选其他后端')
        from rembg import new_session, remove
        from unittest.mock import patch
        if model == 'u2net':
            from rembg.sessions.u2net import U2netSession as session_type
        else:
            from rembg.sessions.u2netp import U2netpSession as session_type
        # Do not let rembg's model helper download even if a local file is corrupt.
        with patch.object(session_type, 'download_models', return_value=str(model_file)):
            session=new_session(model, providers=['CPUExecutionProvider'])
        result = remove(im.convert('RGB'), session=session, only_mask=True)
        return result.convert('L'), f'rembg-{model}'
    if backend == 'grabcut':
        if not rect: raise ValueError('GrabCut 需要 --rect x y width height，使用原图像素坐标')
        try: import cv2
        except ImportError as exc: raise RuntimeError('GrabCut 需要本地 OpenCV: opencv-python-headless') from exc
        x,y,w,h=rect
        if min(x,y)<0 or min(w,h)<2 or x+w>size[0] or y+h>size[1] or w>=size[0] or h>=size[1]:
            raise ValueError('矩形应位于原图范围内、包含完整商品且留有背景')
        scale=min(1.0,1600/max(size)); reduced=im.convert('RGB').resize((round(size[0]*scale),round(size[1]*scale)),Image.Resampling.LANCZOS)
        bgr=cv2.cvtColor(np.array(reduced),cv2.COLOR_RGB2BGR)
        mask=np.zeros(bgr.shape[:2],np.uint8)
        cv2.grabCut(bgr,mask,(round(x*scale),round(y*scale),max(2,round(w*scale)),max(2,round(h*scale))),None,None,5,cv2.GC_INIT_WITH_RECT)
        mask=np.where((mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD),255,0).astype('uint8')
        return Image.fromarray(mask).resize(size,Image.Resampling.LANCZOS), 'OpenCV GrabCut (rectangle)'
    raise ValueError('未知蒙版来源')


def adjust(rgba, strength, sharpness):
    arr=np.array(rgba.convert('RGBA')); rgb=arr[:,:,:3].astype(np.float32)/255.; alpha=arr[:,:,3]
    solid=alpha>=240
    if solid.sum()<16: raise ValueError('蒙版中没有足够的不透明商品区域')
    y=rgb @ np.array([.2126,.7152,.0722],dtype=np.float32)
    med=float(np.median(y[solid])); target=.74
    gamma=float(np.clip(math.log(target)/math.log(max(.03,min(.97,med))),.48,1.0)) if med<target else 1.0
    gamma=max(.42,1+(gamma-1)*strength)
    # Lift luminance with a shared RGB ratio, protecting hue and saturation.
    target_y=np.power(y, gamma)
    ratio=target_y/np.maximum(y,1e-5)
    headroom=np.maximum(1.0,.98/np.maximum(rgb.max(2),1e-5))
    lifted=rgb*np.minimum(ratio,headroom)[:,:,None]
    # Protect dark printing; shift gently rather than reconstruct texture.
    guard=np.clip((y-.13)/.32,0,1)[:,:,None]
    lit=rgb+(lifted-rgb)*guard
    lum=lit @ np.array([.2126,.7152,.0722],dtype=np.float32)
    chroma=lit.max(2)-lit.min(2)
    sat=chroma/np.maximum(lit.max(2),1e-5)
    # Vibrance affects existing chroma only, avoids changing neutral packaging.
    amount=(.32*strength*(1-sat*.65))[:,:,None]
    delta=(lit-lum[:,:,None])*amount
    safe_up=np.where(delta>0,(1-lit)/np.maximum(delta,1e-6),100)
    safe_dn=np.where(delta<0,lit/np.maximum(-delta,1e-6),100)
    limit=np.minimum(1,np.minimum(safe_up.min(2),safe_dn.min(2)))[:,:,None]
    result=np.clip(lit+delta*limit,0,1)
    # Edge pixels retain their colors; only fully opaque interior receives full adjustment.
    blend=np.clip((alpha.astype(np.float32)-16)/180,0,1)[:,:,None]
    arr[:,:,:3]=np.rint((rgb+(result-rgb)*blend)*255).astype('uint8')
    if sharpness:
        # Restrict detail enhancement to the opaque interior and cap changes.
        before=arr[:,:,:3].copy()
        boosted=np.asarray(ImageEnhance.Sharpness(Image.fromarray(before)).enhance(1+sharpness)).astype(np.int16)
        delta=np.clip(boosted-before.astype(np.int16),-8,8)
        safe=np.asarray(Image.fromarray(alpha).filter(ImageFilter.MinFilter(5)))>=250
        arr[:,:,:3]=np.clip(before.astype(np.int16)+delta*safe[:,:,None],0,255).astype('uint8')
    after=arr[:,:,:3].astype(np.float32) @ np.array([.2126,.7152,.0722],dtype=np.float32)
    return Image.fromarray(arr), {'median_luma_before':round(med*255,1),'median_luma_after':round(float(np.median(after[solid])),1),'gamma':round(gamma,3),'strength':strength,'sharpness':sharpness,'alpha_unchanged':True}


def main():
    p=argparse.ArgumentParser(description='在本机抠图、可控修边和非生成式提亮调色。')
    p.add_argument('source',type=Path); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--backend',choices=['auto','alpha','vision','rembg','grabcut'],default='auto')
    p.add_argument('--model',choices=['u2net','u2netp'],default='u2net')
    p.add_argument('--mask',type=Path,help='人工修正的同尺寸灰度或 RGBA 蒙版 PNG')
    p.add_argument('--finish-recipe',type=Path,help='可选的原图专用精修 JSON，可指定描边、取样调色和去灰边')
    p.add_argument('--rect',type=int,nargs=4,metavar=('X','Y','WIDTH','HEIGHT'))
    p.add_argument('--contract',type=int,default=0,help='蒙版向内收缩像素；默认 0，防止缺边')
    p.add_argument('--feather',type=float,default=0,help='蒙版羽化半径；默认 0')
    p.add_argument('--matte-blackpoint',type=int,default=0,help='低于此 alpha 阈值的背景设透明；默认不处理')
    p.add_argument('--matte-whitepoint',type=int,default=255,help='高于此 alpha 阈值的像素设不透明；默认不处理')
    p.add_argument('--strength',type=float,default=1.0,help='调色强度 0–1.5，0 保留原色')
    p.add_argument('--sharpness',type=float,default=.25,help='安全范围内的细节增强 0–1，0 关闭')
    p.add_argument('--size',type=int,default=1440); p.add_argument('--fill',type=float,default=.86)
    p.add_argument('--upscale-limit',type=float,default=2.0,help='插值放大上限 1–3 倍；不创造原图细节')
    a=p.parse_args()
    if not 0<=a.contract<=8 or not 0<=a.feather<=5 or not 0<=a.matte_blackpoint<a.matte_whitepoint<=255 or not 0<=a.strength<=1.5 or not 0<=a.sharpness<=1 or not 256<=a.size<=4096 or not .3<=a.fill<=.95 or not 1<=a.upscale_limit<=3:
        p.error('参数超出允许范围')
    source=a.source.expanduser().resolve(strict=True); out=a.out.expanduser().absolute()
    if out.exists(): p.error('输出目录已存在，不能覆盖')
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    recipe={}
    if a.finish_recipe:
        recipe=json.loads(a.finish_recipe.read_text(encoding='utf-8-sig'))
        if not isinstance(recipe,dict) or recipe.get('source_sha256') != sha:
            p.error('精修配方与本张原图的 SHA-256 不匹配')
    outline=recipe.get('outline')
    samples=recipe.get('palette')
    fringe=recipe.get('decontaminate_px',0)
    if type(fringe) not in (int,float) or not 0<=fringe<=3:
        p.error('decontaminate_px 须介于 0 和 3 之间')
    if outline is not None and a.mask:
        p.error('精修轮廓和 --mask 只能选用一项')
    with Image.open(source) as src:
        im=ImageOps.exif_transpose(src).convert('RGBA')
    if outline is not None:
        mask,mode=outline_mask(im.size,outline),'source-traced-outline'
    else:
        with tempfile.TemporaryDirectory(prefix='local-product-') as d:
            mask,mode=local_mask(source,im,a.backend,a.model,a.rect,a.mask,Path(d))
    if a.matte_blackpoint or a.matte_whitepoint != 255:
        low, high=a.matte_blackpoint,a.matte_whitepoint
        mask=mask.point([max(0,min(255,round((v-low)*255/(high-low)))) for v in range(256)])
    if a.contract: mask=mask.filter(ImageFilter.MinFilter(2*a.contract+1))
    if a.feather: mask=mask.filter(ImageFilter.GaussianBlur(a.feather))
    bbox=mask.getbbox() if outline is not None else mask.point(lambda x:255 if x>8 else 0).getbbox()
    if not bbox or mask.getextrema()[1]<128: raise ValueError('未检测到有效商品蒙版')
    if any(mask.getpixel(pt)>8 for pt in ((0,0),(im.width-1,0),(0,im.height-1),(im.width-1,im.height-1))):
        raise ValueError('蒙版触及画布角落，可能残留背景；请修正蒙版')
    im.putalpha(mask)
    raw=im.crop(bbox)
    enhanced,tone=adjust(raw,a.strength,a.sharpness)
    if samples is not None:
        enhanced=palette_grade(raw,samples,bbox[:2],enhanced)
        tone.update(method='reference-palette',samples=len(samples))
    if fringe:
        enhanced=remove_fringe(enhanced,fringe)
    # Native master preserves source pixels and provides a reliable basis for review.
    scale=min(a.size*a.fill/max(enhanced.size),a.upscale_limit)
    target=enhanced.resize(tuple(max(1,round(v*scale)) for v in enhanced.size),Image.Resampling.LANCZOS)
    trans=Image.new('RGBA',(a.size,a.size),(0,0,0,0)); trans.alpha_composite(target,((a.size-target.width)//2,(a.size-target.height)//2))
    white=Image.new('RGB',trans.size,'white');white.paste(trans,mask=trans.getchannel('A'))
    dark=Image.new('RGB',trans.size,(48,48,48));dark.paste(trans,mask=trans.getchannel('A'))
    out.mkdir(parents=True,exist_ok=False)
    mask.save(out/'mask.png');raw.save(out/'native_original_rgba.png');enhanced.save(out/'native_enhanced_rgba.png')
    trans.save(out/'transparent.png');white.save(out/'white.png');dark.save(out/'preview_dark.png')
    report={'source':str(source),'source_sha256':sha,'source_size':list(im.size),'subject_bbox':list(bbox),'mask_backend':mode,'contract_px':a.contract,'feather_px':a.feather,'matte_blackpoint':a.matte_blackpoint,'matte_whitepoint':a.matte_whitepoint,'tone':tone,'canvas':a.size,'actual_subject_px':list(target.size),'upscale_ratio':round(scale,3),'review_status':'待人工复核','note':'保留原商品像素进行调色；插值不可创造细节。须核对文字、包装边缘及色彩。'}
    if a.finish_recipe:
        report.update(finish_recipe=str(a.finish_recipe.resolve()),decontaminate_px=fringe)
    (out/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'transparent':str(out/'transparent.png'),'white':str(out/'white.png'),'native':str(out/'native_enhanced_rgba.png'),'mask':str(out/'mask.png'),'review':'待人工复核','method':mode},ensure_ascii=False))

if __name__=='__main__': main()
