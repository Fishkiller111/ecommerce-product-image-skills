#!/usr/bin/env python3
"""Brighten a locally extracted RGBA product and composite a matching white PNG."""
import argparse
from pathlib import Path
from PIL import Image, ImageEnhance
from composite_white import compose_to_white, save_new_atomic


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('--transparent', type=Path, required=True)
    p.add_argument('--white', type=Path, required=True)
    p.add_argument('--brightness', type=float, default=1.1)
    a = p.parse_args()
    if not 1.0 <= a.brightness <= 1.3:
        p.error('brightness must be between 1.0 and 1.3')
    paths = [a.source.expanduser().resolve(strict=True), a.transparent.expanduser().resolve(), a.white.expanduser().resolve()]
    if len(set(paths)) != 3 or any(x.suffix.lower() != '.png' for x in paths[1:]):
        p.error('input and distinct PNG outputs are required')
    if any(x.exists() for x in paths[1:]):
        p.error('output already exists')
    with Image.open(paths[0]) as im:
        if im.format != 'PNG' or ('A' not in im.getbands() and 'transparency' not in im.info):
            p.error('input must be a transparent PNG')
        rgba = im.convert('RGBA')
        alpha = rgba.getchannel('A')
        rgb = ImageEnhance.Brightness(rgba.convert('RGB')).enhance(a.brightness)
        result = rgb.convert('RGBA')
        result.putalpha(alpha)
        # compose_to_white validates alpha and the transparent corners.
        result.format = 'PNG'
        white = compose_to_white(result)
    save_new_atomic(result, paths[1])
    try:
        save_new_atomic(white, paths[2])
    except Exception:
        paths[1].unlink(missing_ok=True)
        raise
    print('透明图:', paths[1], '\n白底图:', paths[2], '\n请逐项对照原图检查细节和抠图。')

if __name__ == '__main__':
    main()
