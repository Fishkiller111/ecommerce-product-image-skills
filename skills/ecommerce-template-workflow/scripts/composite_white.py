#!/usr/bin/env python3
"""Composite a checked GPT transparent PNG onto white without redrawing it."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from PIL import Image


def compose_to_white(image):
    if image.format != 'PNG':
        raise ValueError('输入必须是具有真实透明通道的 PNG')
    if 'A' not in image.getbands() and 'transparency' not in image.info:
        raise ValueError('输入没有 alpha 透明通道；不能生成配套白底图')
    rgba = image.convert('RGBA')
    alpha = rgba.getchannel('A')
    lo, hi = alpha.getextrema()
    if lo != 0 or hi == 0:
        raise ValueError('输入缺少透明背景或非透明商品，不能作为抠图')
    w, h = rgba.size
    if any(alpha.getpixel(xy) != 0 for xy in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]):
        raise ValueError('输入四角不全透明，需先人工检查透明背景')
    white = Image.new('RGB', rgba.size, (255, 255, 255))
    white.paste(rgba, (0, 0), alpha)
    return white


def save_new_atomic(image, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.white-', suffix='.png', dir=destination.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        image.save(tmp, format='PNG')
        try:
            os.link(tmp, destination)
        except FileExistsError:
            raise
        except OSError:
            # Exclusive creation prevents overwriting on filesystems without hardlinks.
            try:
                with destination.open('xb') as dst, tmp.open('rb') as src:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
            except FileExistsError:
                raise
            except Exception:
                destination.unlink(missing_ok=True)
                raise
    finally:
        tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='将已核验的 GPT 透明 PNG 原样铺到纯白底，不重绘商品。')
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    destination = args.out.expanduser().absolute()
    if destination.suffix.lower() != '.png':
        parser.error('输出须为 .png 文件')
    if destination.resolve() == source:
        parser.error('输出不得覆盖输入')
    with Image.open(source) as image:
        result = compose_to_white(image)
    save_new_atomic(result, destination)
    print(json.dumps({'output': str(destination), 'size': list(result.size),
                      'method': 'alpha-composite-on-white; no regeneration',
                      'notice': '透明通道检查不等于商品身份或文字核验'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
