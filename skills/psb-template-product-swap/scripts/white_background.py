#!/usr/bin/env python3
"""Non-generative product white background, using original photo pixels."""
import argparse
import json
import tempfile
from pathlib import Path
from PIL import Image
import numpy as np
from render_sku import cutout
from studio_light import studio_light
from hd_product import prepare_hd_product


def lift_deeply_underexposed(product):
    """Lift colored, low-exposure subjects; protect near-black ink and alpha."""
    arr = np.array(product.convert('RGBA'))
    rgb = arr[:, :, :3].astype(np.float32)
    alpha = arr[:, :, 3]
    solid = alpha >= 250
    if not solid.any():
        return product, {'applied': False}
    lum = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
    median = float(np.median(lum[solid]))
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    colorful = float(np.mean(chroma[solid] >= 20))
    applied = 20 <= median < 50 and colorful > .35
    if applied:
        exponent = min(1.55, max(1.0, 65.0 / max(median, 1)))
        bright = 255 * (1 - (1-rgb/255) ** exponent)
        ink_guard = np.clip((lum-16)/26, 0, 1)
        edge_guard = np.clip((alpha.astype(np.float32)-32)/192, 0, 1)
        mix = (ink_guard * edge_guard)[:, :, None]
        arr[:, :, :3] = np.rint(rgb + (bright-rgb)*mix).clip(0,255).astype(np.uint8)
    return Image.fromarray(arr), {'applied': applied, 'median_before': round(median, 1),
                                  'colorful_fraction': round(colorful, 3)}


def make_images(product, size=1440, enhance=True):
    if not 256 <= size <= 4096:
        raise ValueError('画布尺寸须为 256–4096 像素')
    product = product.convert('RGBA')
    alpha = product.getchannel('A')
    bbox = alpha.point(lambda v: 255 if v > 20 else 0).getbbox()
    if not bbox:
        raise ValueError('未找到有效商品，不能输出空白图')
    product = product.crop(bbox)
    if enhance:
        product, deep = lift_deeply_underexposed(product)
        product, light = studio_light(product)
        light['deep_exposure'] = deep
        # No enlargement is required for sharpening: preserve native pixels.
        product, detail = prepare_hd_product(product, product.size)
    else:
        light, detail = {'preset': 'original'}, {'method': 'none'}
    product.thumbnail((round(size * .86), round(size * .86)), Image.Resampling.LANCZOS)
    transparent = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    transparent.alpha_composite(product, ((size-product.width)//2, (size-product.height)//2))
    white = Image.new('RGB', (size, size), (255, 255, 255))
    white.paste(transparent, (0, 0), transparent.getchannel('A'))
    return transparent, white, {'tone': light, 'detail': detail, 'source_bbox': list(bbox),
        'canvas_size': size, 'note': '非生成式调光与有限锐化，不恢复不可辨认文字；须人工复核商品、颜色、文字与边缘。'}


def main():
    parser = argparse.ArgumentParser(description='本地抠图、调光，生成白底图与透明图；不重绘商品。')
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='新建的输出目录；已存在时停止')
    parser.add_argument('--size', type=int, default=1440)
    parser.add_argument('--keep-product-look', action='store_true', help='不调光、不锐化')
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    out = args.out.expanduser().absolute()
    out.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(prefix='cutout-') as temp:
            raw = Path(temp) / 'original.png'
            mode = cutout(source, raw, Path(__file__).with_name('macos_subject_mask.m'), None)
            with Image.open(raw) as im:
                rgba, white, report = make_images(im, args.size, not args.keep_product_look)
        rgba.save(out/'transparent.png')
        white.save(out/'white.png')
        report.update({'source': str(source), 'cutout_method': mode, 'manual_review_required': True})
        (out/'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        # Keep any intermediate files for diagnosis, never report a partial run as success.
        raise
    print(json.dumps({'white':str(out/'white.png'), 'transparent':str(out/'transparent.png'), 'review':str(out/'review.json'), 'cutout_method':mode}, ensure_ascii=False))

if __name__ == '__main__':
    main()
