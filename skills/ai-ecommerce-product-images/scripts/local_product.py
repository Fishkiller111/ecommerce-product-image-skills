#!/usr/bin/env python3
"""Local product extraction and non-generative, color-managed-looking tone adjustments."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps
from product_edges import refine_product_mask
from finish_recipe import (
    antialias_opaque_mask, decontaminate_opaque_edge, outline_mask, palette_grade, remove_fringe,
)


LUMA_WEIGHTS = np.array([.2126, .7152, .0722], dtype=np.float32)


def source_rgba(path):
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source)
        image = oriented.convert('RGBA')
        profile = oriented.info.get('icc_profile')
        if not profile:
            return image, 'assumed-sRGB'
        # Normalize tagged source colors before interpreting any sRGB recipe swatches.
        color = oriented if oriented.mode in ('RGB', 'CMYK', 'L') else (
            oriented.getchannel('L') if oriented.mode == 'LA' else image.convert('RGB')
        )
        try:
            srgb = ImageCms.profileToProfile(
                color, io.BytesIO(profile), ImageCms.createProfile('sRGB'), outputMode='RGB',
            )
        except ImageCms.PyCMSError as exc:
            raise ValueError('无法将原图 ICC 转换为 sRGB，请先导出为有正常色彩配置的 sRGB 图像') from exc
        srgb.putalpha(image.getchannel('A'))
        return srgb, 'ICC-to-sRGB'


def rembg_model_path(model):
    data_home = os.environ.get('XDG_DATA_HOME')
    root = Path(data_home).expanduser() if data_home else Path.home()
    model_home = os.environ.get('U2NET_HOME')
    legacy_cache = Path(model_home or root/'.u2net').expanduser()
    default_cache = root/('rembg' if data_home else '.rembg')
    cache = Path(model_home or os.environ.get('REMBG_HOME') or default_cache).expanduser()
    # rembg 2.0.87 uses per-model folders and reads older flat caches as a fallback.
    # Mirror this lookup without invoking the potentially downloading session helper.
    models = ('u2netp', 'u2net') if model is None and sys.platform == 'win32' else (model or 'u2net',)
    for name in models:
        filename = f'{name}.onnx'
        for candidate in (cache/'models'/name/filename, legacy_cache/filename):
            if candidate.is_file():
                return name, candidate
    first = models[0]
    return first, cache/'models'/first/f'{first}.onnx'


def rembg_mask(image, model):
    model, model_file = rembg_model_path(model)
    if not model_file.is_file():
        raise RuntimeError(
            f'缺少本地模型 {model_file}。请先按技能说明准备权重，或使用 --mask / --backend grabcut。'
        )
    try:
        from rembg import new_session, remove
        if model == 'u2net':
            from rembg.sessions.u2net import U2netSession as session_type
        else:
            from rembg.sessions.u2netp import U2netpSession as session_type
    except (ImportError, OSError, SystemExit) as exc:
        hint = 'Windows 请安装本技能的 requirements-windows.txt 并检查 x64 Visual C++ 运行库。' if sys.platform == 'win32' else ''
        raise RuntimeError(f'无法加载 rembg 的 CPU 依赖。{hint} {exc}') from exc
    try:
        # Inference uses the prepared weights even when the network is unavailable.
        with patch.object(session_type, 'download_models', return_value=str(model_file.resolve())):
            session = new_session(model, providers=['CPUExecutionProvider'])
        mask = remove(image.convert('RGB'), session=session, only_mask=True)
    except Exception as exc:
        raise RuntimeError(f'本地 CPU 抠图失败。请检查模型 {model_file}，或使用 --mask。{exc}') from exc
    if not isinstance(mask, Image.Image) or mask.size != image.size:
        raise ValueError('本地 CPU 蒙版尺寸或格式不匹配')
    return mask.convert('L'), f'rembg-{model}'


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
        if alpha.getextrema()[0] <= 8:
            return alpha, 'source-alpha'
        if sys.platform != 'darwin':
            return rembg_mask(im, model)
        try:
            return local_mask(source, im, 'vision', model, rect, supplied, tmp)
        except (RuntimeError, subprocess.CalledProcessError) as vision_error:
            try:
                return rembg_mask(im, model)
            except RuntimeError as rembg_error:
                raise RuntimeError(f'{vision_error} 本地备用模型同样未能生成蒙版：{rembg_error}') from rembg_error
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
        im.convert('RGB').save(oriented)
        result=tmp/'vision.png'
        run = subprocess.run([str(tool), str(oriented), str(result)], capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(f'Vision 无法取得轮廓。可换后端或使用 --mask。{run.stderr.strip()}')
        with Image.open(result) as m:
            if m.size != size: raise ValueError('Vision 蒙版尺寸不匹配')
            return m.convert('RGBA').getchannel('A'), 'macOS Vision'
    if backend == 'rembg':
        return rembg_mask(im, model)
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


def palette_base(rgba, strength):
    """Keep the base curve used by existing source-bound palette recipes."""
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
    # Retain contrast in dark printing as the surrounding stock brightens.
    guard=np.clip((y-.13)/.32,0,1)[:,:,None]
    lit=rgb+(lifted-rgb)*guard
    lum=lit @ np.array([.2126,.7152,.0722],dtype=np.float32)
    chroma=lit.max(2)-lit.min(2)
    sat=chroma/np.maximum(lit.max(2),1e-5)
    amount = .32*strength*(1-sat*.65)
    amount = amount[:,:,None]
    delta=(lit-lum[:,:,None])*amount
    safe_up=np.where(delta>0,(1-lit)/np.maximum(delta,1e-6),100)
    safe_dn=np.where(delta<0,lit/np.maximum(-delta,1e-6),100)
    limit=np.minimum(1,np.minimum(safe_up.min(2),safe_dn.min(2)))[:,:,None]
    result=np.clip(lit+delta*limit,0,1)
    # Edge pixels retain their colors; only fully opaque interior receives full adjustment.
    blend=np.clip((alpha.astype(np.float32)-16)/180,0,1)[:,:,None]
    arr[:,:,:3]=np.rint((rgb+(result-rgb)*blend)*255).astype('uint8')
    return Image.fromarray(arr), {'gamma': round(gamma, 3)}


def subject_pixels(alpha):
    """Use the same reliable foreground pixels for exposure and before/after stats."""
    solid = alpha >= 240
    if np.count_nonzero(solid) >= 16:
        return solid, False
    denser = alpha >= max(16, .9*int(alpha.max()))
    if np.count_nonzero(denser) < 16:
        raise ValueError('蒙版可用于测量的主体像素不足')
    return denser, True


def neutral_sample(image, mask, rect):
    x0, y0, x1, y1 = rect
    if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
        raise ValueError('中性取样框须在 EXIF 校正后的原图内，顺序为左、上、右、下')
    solid = np.asarray(mask.crop(rect)) >= 240
    if np.count_nonzero(solid) < max(16, .9*solid.size):
        raise ValueError('中性取样框须位于完全不透明的中性材质内，避开边缘')
    sample = np.median(np.asarray(image.crop(rect))[solid, :3], axis=0)
    if sample.min() < 45 or sample.max() >= 245 or np.ptp(sample) > .30*sample.max():
        raise ValueError('中性取样须为未过曝、非深影的白色或灰色材质')
    return sample


def exposure_gain(anchor, target, ceiling):
    """Solve the shoulder curve for an exposure anchor with protected highlights."""
    return float(np.clip(target*(1-anchor)/((1-target)*max(anchor, .01)), 1, ceiling))


def inferred_white_sample(rgb, pale, solid, size):
    """Estimate a small cast only when independent light areas agree."""
    candidates = rgb[pale]
    sample = np.median(candidates, axis=0)
    width, height = size
    maximum_spread = .045
    if max(size) >= 2.6*min(size):
        axis = int(width >= height)
        positions = np.nonzero(pale)[axis]
        span = max(size)
        front = candidates[positions < .20*span]
        back = candidates[positions >= .80*span]
        if min(len(front), len(back)) < max(20, len(candidates)*.07):
            return None
        first, last = np.median(front, axis=0), np.median(back, axis=0)
        if np.max(abs(first/first.max()-last/last.max())) >= .085:
            return None
        sample = (first+last)/2
        candidates = np.concatenate([front, back])
        if np.percentile(rgb[solid].max(axis=1), 90) < .59:
            maximum_spread = .085
    residual = candidates-candidates.mean(axis=1, keepdims=True)
    if .008 < np.ptp(sample) <= maximum_spread and np.max(np.std(residual, axis=0)) < .023:
        return sample*255
    return None


def adaptive_grade(rgba, strength, neutral):
    if not strength:
        return rgba, {}
    arr = np.array(rgba)
    alpha = arr[:, :, 3]
    solid, soft = subject_pixels(alpha)
    source = arr[:, :, :3].astype(np.float32)/255
    rgb = source
    peak = rgb.max(axis=2)
    chroma = peak-rgb.min(axis=2)
    luma = rgb @ LUMA_WEIGHTS
    pale = solid & (luma >= .35) & (chroma <= .10) & (peak < .96)
    white_stock = np.count_nonzero(pale) >= max(24, .08*np.count_nonzero(solid))
    inferred_neutral = inferred_white_sample(rgb, pale, solid, rgba.size) if (
        neutral is None and white_stock and not soft
    ) else None
    neutral_reference = neutral if neutral is not None else inferred_neutral
    if neutral_reference is not None:
        correction = min(strength, 1) if neutral is not None else min(strength, 1)*.60
        gains = np.power((neutral_reference @ LUMA_WEIGHTS)/neutral_reference, correction)
        balanced = (rgb*gains).astype(np.float32)
        if neutral is None:
            near_neutral = np.clip((.16-chroma)/.11, 0, 1)
            balanced = rgb + (balanced-rgb)*near_neutral[:, :, None]
        rgb = balanced/np.maximum(1, balanced.max(axis=2, keepdims=True))
        peak = rgb.max(axis=2)
        chroma = peak-rgb.min(axis=2)
        luma = rgb @ LUMA_WEIGHTS

    p90, p98 = np.percentile(peak[solid], [90, 98])
    deep_exposure = float(np.clip((.59-p90)/.16, 0, 1))
    gain = exposure_gain(max(p90, .86*p98), .84, 1.25 if soft else 3.5+.9*deep_exposure)
    colored = solid & (chroma > .105) & (luma > .16)
    color_gain = gain
    if not soft and np.count_nonzero(colored) >= max(24, .035*np.count_nonzero(solid)):
        color_mid, color_high = np.percentile(peak[colored], [72, 92])
        color_gain = exposure_gain(max(color_mid, .80*color_high), .83, 3.8+1.3*deep_exposure)
        color_gain = 1+(color_gain-1)*float(np.clip((.955-p90)/.13, 0, 1))
    white_gain = gain
    if white_stock and not soft:
        white_anchor = np.percentile(peak[pale], 72)
        white_gain = exposure_gain(white_anchor, .89, 4.4+1.0*deep_exposure)
        # Respect package whites with plenty of light already in the source.
        if p90 > .92:
            white_gain = 1+(white_gain-1)*float(np.clip((.98-p90)/.06, 0, 1))

    color_weight = np.clip((chroma-.065)/.16, 0, 1)
    white_weight = np.clip((.145-chroma)/.105, 0, 1)*np.clip((luma-.28)/.19, 0, 1)
    local_gain = ((gain+(color_gain-gain)*color_weight)*(1-white_weight)+white_gain*white_weight)**strength
    ink_guard = np.clip((luma-.085)/.26, 0, 1)
    lift = (local_gain/(1+(local_gain-1)*peak)-1)*ink_guard
    graded = rgb*(1+lift[:, :, None])
    vibrance = min(strength, 1.3)*.44*(1-1/max(color_gain, 1))
    graded_luma = graded @ LUMA_WEIGHTS
    saturation = chroma/np.maximum(peak, 1e-5)
    amount = vibrance * color_weight * (1-.75*saturation) * ink_guard
    delta = (graded-graded_luma[:, :, None])*amount[:, :, None]
    room = np.where(delta > 0, 1-graded, graded)/np.maximum(abs(delta), 1e-6)
    graded += delta*np.minimum(1, room.min(axis=2, keepdims=True))
    weight = np.clip((alpha.astype(np.float32)-16)/180, 0, 1) if soft else alpha > 0
    arr[:, :, :3] = np.rint(np.clip(source+(graded-source)*weight[:, :, None], 0, 1)*255).astype(np.uint8)
    measurements = {
        'highlight_p90': round(float(p90)*255, 1), 'highlight_p98': round(float(p98)*255, 1),
        'exposure_gain': round(gain**strength, 3), 'white_material_gain': round(white_gain**strength, 3),
        'colored_material_gain': round(color_gain**strength, 3), 'vibrance': round(vibrance, 3),
    }
    if neutral_reference is not None:
        measurements.update(neutral_sample=np.round(neutral_reference, 1).tolist(),
                            neutral_gains=np.round(gains, 4).tolist(),
                            neutral_source='manual' if neutral is not None else 'near-neutral-stock')
    return Image.fromarray(arr), measurements


def sharpen_interior(image, sharpness, *, reference_palette=False):
    if not sharpness:
        return image
    arr = np.array(image)
    before = arr[:, :, :3].astype(np.int16)
    rgb = image.convert('RGB')
    if reference_palette:
        boosted = ImageEnhance.Sharpness(rgb).enhance(1+sharpness)
    else:
        boosted = rgb.filter(ImageFilter.UnsharpMask(radius=.8, percent=round(80*sharpness), threshold=3))
    limit = 8 if reference_palette else 6
    delta = np.clip(np.asarray(boosted, dtype=np.int16)-before, -limit, limit)
    safe = np.asarray(image.getchannel('A').filter(ImageFilter.MinFilter(5 if reference_palette else 7))) >= 250
    arr[:, :, :3] = np.clip(before + delta*safe[:, :, None], 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def tone_measurements(raw, enhanced):
    """Measure source and exported tone over the same opaque subject pixels."""
    solid, soft = subject_pixels(np.asarray(raw.getchannel('A')))
    stats = {}
    for name, image in [('before', raw), ('after', enhanced)]:
        colors = np.asarray(image)[solid, :3]
        stats['median_luma_'+name] = round(float(np.median(colors @ LUMA_WEIGHTS)), 1)
        stats['median_chroma_'+name] = round(float(np.median(np.ptp(colors, axis=1))), 1)
    return {**stats, 'measurement_region': 'high-alpha' if soft else 'opaque'}


def load_recipe(source_sha, explicit_path):
    """Resolve a recipe for the exact source, preferring a caller's explicit choice."""
    candidates = [explicit_path] if explicit_path else sorted(
        (Path(__file__).resolve().parents[1] / 'examples').glob('*.json')
    )
    for path in candidates:
        recipe = json.loads(path.read_text(encoding='utf-8-sig'))
        if (
            isinstance(recipe, dict)
            and recipe.get('source_sha256') == source_sha
            and (explicit_path or recipe.get('auto_apply') is True)
        ):
            return recipe, path
    if explicit_path:
        raise ValueError('精修配方与本张原图的 SHA-256 不匹配')
    return {}, None


def main():
    p=argparse.ArgumentParser(description='在本机抠图、可控修边和非生成式提亮调色。')
    p.add_argument('source',type=Path); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--backend',choices=['auto','alpha','vision','rembg','grabcut'],default='auto')
    p.add_argument('--model', choices=['u2net', 'u2netp'],
                   help='本地 CPU 权重。Windows 优先 u2netp，可复用已缓存的 u2net')
    p.add_argument('--mask',type=Path,help='人工修正的同尺寸灰度或 RGBA 蒙版 PNG')
    p.add_argument('--finish-recipe',type=Path,help='指定原图专用精修 JSON；默认按原图 SHA-256 查找内置配方')
    p.add_argument('--rect',type=int,nargs=4,metavar=('X','Y','WIDTH','HEIGHT'))
    p.add_argument('--neutral-rect',type=int,nargs=4,metavar=('LEFT','TOP','RIGHT','BOTTOM'),
                   help='以原图中确认是白色或灰色的材质为偏色取样')
    p.add_argument('--edge-mode',choices=['auto','preserve','opaque','guided'],default='auto',
                   help='auto 精修不透明模型蒙版；guided 显式按原照修边；preserve 保留灰度过渡')
    p.add_argument('--no-cap-recovery', action='store_true', help='关闭软管端部补全，保留原照引导修边')
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
    try:
        recipe, recipe_path = load_recipe(sha, a.finish_recipe)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    outline=recipe.get('outline')
    samples=recipe.get('palette') if a.strength else None
    fringe=recipe.get('decontaminate_px',0)
    if type(fringe) not in (int,float) or not 0<=fringe<=3:
        p.error('decontaminate_px 须介于 0 和 3 之间')
    if not a.finish_recipe and (a.mask or a.backend != 'auto'):
        # Keep the matched color treatment when the caller supplies a new silhouette.
        outline, fringe = None, 0
    if outline is not None and a.mask:
        p.error('精修轮廓和 --mask 只能选用一项')
    im, color_space = source_rgba(source)
    if outline is not None:
        mask,mode=outline_mask(im.size,outline),'source-traced-outline'
    else:
        try:
            with tempfile.TemporaryDirectory(prefix='local-product-') as d:
                mask,mode=local_mask(source,im,a.backend,a.model,a.rect,a.mask,Path(d))
        except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            p.error(str(exc))
    edge_review = {}
    automatic_model = a.backend == 'auto' and mode.startswith(('macOS Vision', 'rembg-'))
    guided_edge = outline is None and (a.edge_mode == 'guided' or (a.edge_mode == 'auto' and automatic_model))
    if guided_edge:
        try:
            mask, edge_review = refine_product_mask(im, mask, recover_caps=not a.no_cap_recovery)
        except ImportError:
            if a.edge_mode == 'guided':
                p.error('原照引导修边需要本地 OpenCV：opencv-python-headless')
            edge_review = {'contour_refined': False, 'cap_check': 'opencv-unavailable'}
    refined = edge_review.get('contour_refined', False)
    opaque_edge = a.edge_mode == 'opaque' or (a.edge_mode == 'auto' and mode.startswith('OpenCV GrabCut'))
    if a.matte_blackpoint or a.matte_whitepoint != 255:
        low, high=a.matte_blackpoint,a.matte_whitepoint
        mask=mask.point([max(0,min(255,round((v-low)*255/(high-low)))) for v in range(256)])
    if a.contract: mask=mask.filter(ImageFilter.MinFilter(2*a.contract+1))
    if a.feather: mask=mask.filter(ImageFilter.GaussianBlur(a.feather))
    if opaque_edge and outline is None:
        mask = antialias_opaque_mask(mask)
    supplied_alpha = mode in ('source-alpha', 'user-mask')
    bbox = (mask.getbbox() if outline is not None or supplied_alpha or opaque_edge or refined
            else mask.point(lambda x: 255 if x>8 else 0).getbbox())
    if not bbox or mask.getextrema()[1] < (16 if supplied_alpha else 128):
        raise ValueError('未检测到有效商品蒙版')
    if any(mask.getpixel(pt)>8 for pt in ((0,0),(im.width-1,0),(0,im.height-1),(im.width-1,im.height-1))):
        raise ValueError('蒙版触及画布角落，可能残留背景；请修正蒙版')
    neutral = neutral_sample(im, mask, tuple(a.neutral_rect)) if a.strength and a.neutral_rect else None
    im.putalpha(mask)
    raw=im.crop(bbox)
    tone = {
        'method': 'adaptive' if a.strength else 'preserve-exposure-and-color',
        'strength': a.strength, 'sharpness': a.sharpness, 'alpha_unchanged': True,
    }
    if samples is not None and neutral is None:
        enhanced, grade = palette_base(raw, a.strength)
    else:
        enhanced, grade = adaptive_grade(raw, a.strength, neutral)
    tone.update(grade)
    enhanced = sharpen_interior(enhanced, a.sharpness, reference_palette=samples is not None and neutral is None)
    if samples is not None:
        enhanced=palette_grade(raw,samples,bbox[:2],enhanced)
        tone.update(method='reference-palette',samples=len(samples))
    if fringe:
        enhanced=remove_fringe(enhanced,fringe)
    recover_edge = (opaque_edge or refined) and not fringe and mode != 'source-alpha'
    if recover_edge:
        enhanced = decontaminate_opaque_edge(enhanced)
    tone.update(tone_measurements(raw,enhanced))
    # Native master preserves source pixels and provides a reliable basis for review.
    scale=min(a.size*a.fill/max(enhanced.size),a.upscale_limit)
    target=enhanced.resize(tuple(max(1,round(v*scale)) for v in enhanced.size),Image.Resampling.LANCZOS)
    trans=Image.new('RGBA',(a.size,a.size),(0,0,0,0)); trans.alpha_composite(target,((a.size-target.width)//2,(a.size-target.height)//2))
    white=Image.new('RGB',trans.size,'white');white.paste(trans,mask=trans.getchannel('A'))
    dark=Image.new('RGB',trans.size,(48,48,48));dark.paste(trans,mask=trans.getchannel('A'))
    out.mkdir(parents=True,exist_ok=False)
    mask.save(out/'mask.png')
    icc_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    for name, image in (
        ('native_original_rgba', raw), ('native_enhanced_rgba', enhanced),
        ('transparent', trans), ('white', white), ('preview_dark', dark),
    ):
        image.save(out/f'{name}.png', icc_profile=icc_profile)
    report={'source':str(source),'source_sha256':sha,'source_size':list(im.size),'subject_bbox':list(bbox),'mask_backend':mode,'contract_px':a.contract,'feather_px':a.feather,'matte_blackpoint':a.matte_blackpoint,'matte_whitepoint':a.matte_whitepoint,'tone':tone,'canvas':a.size,'actual_subject_px':list(target.size),'upscale_ratio':round(scale,3),'review_status':'待人工复核','note':'保留原商品像素进行调色；插值不可创造细节。须核对文字、包装边缘及色彩。'}
    report['color_space'] = color_space
    report['edge'] = {
        'mode': 'guided' if refined else ('opaque' if opaque_edge else 'preserve'),
        'antialias_applied': refined or (opaque_edge and outline is None),
        'edge_rgb_recovery_radius_px': 2 if recover_edge else fringe,
        **edge_review,
    }
    if neutral is not None:
        tone['neutral_rect'] = a.neutral_rect
    if recipe_path:
        report.update(finish_recipe=str(recipe_path.resolve()),decontaminate_px=fringe)
    (out/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'transparent':str(out/'transparent.png'),'white':str(out/'white.png'),'native':str(out/'native_enhanced_rgba.png'),'mask':str(out/'mask.png'),'review':'待人工复核','method':mode,'tone':tone},ensure_ascii=sys.platform == 'win32'))

if __name__=='__main__': main()
