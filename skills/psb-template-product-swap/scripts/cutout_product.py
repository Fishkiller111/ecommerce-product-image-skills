#!/usr/bin/env python3
"""Extract only the product (macOS Vision, Windows local mask, or existing alpha)."""
import argparse
import os
import shutil
import tempfile
from pathlib import Path

from render_sku import cutout


def main():
    parser = argparse.ArgumentParser(description='生成透明商品 PNG，不进行套版；不覆盖现有文件。')
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    dest = args.destination.expanduser().absolute()
    if dest.suffix.lower() != '.png':
        parser.error('输出须为 .png')
    if source == dest.resolve():
        parser.error('输出不得覆盖输入')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cutout-', dir=dest.parent) as temp:
        result = Path(temp) / 'cutout.png'
        mode = cutout(source, result, Path(__file__).with_name('macos_subject_mask.m'), None)
        try:
            os.link(result, dest)  # Atomic no-overwrite on filesystems supporting hard links.
        except FileExistsError:
            parser.exit(1, f'输出已存在，不覆盖：{dest}\n')
        except OSError:
            # Some Windows/removable filesystems cannot create hardlinks.
            # Exclusive creation still prevents clobbering a concurrent result.
            created = False
            try:
                with dest.open('xb') as out:
                    created = True
                    with result.open('rb') as src:
                        shutil.copyfileobj(src, out)
            except FileExistsError:
                parser.exit(1, f'输出已存在，不覆盖：{dest}\n')
            except Exception:
                if created:
                    dest.unlink(missing_ok=True)
                raise
    print(f'透明商品素材：{dest}\n方式：{mode}\n请对照原图人工检查轮廓、白色包装和细节。')


if __name__ == '__main__':
    main()
