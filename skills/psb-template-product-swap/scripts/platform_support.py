"""Cross-platform font selection and local foreground masks for product templates."""
import os
import sys
from pathlib import Path

from PIL import Image, ImageFont


def font_descriptor(role):
    explicit = os.environ.get('PSB_FONT_PATH')
    if explicit:
        path = Path(explicit).expanduser()
        try:
            index = int(os.environ.get('PSB_FONT_INDEX', '0'))
        except ValueError as exc:
            raise ValueError('PSB_FONT_INDEX 必须为非负整数') from exc
        if index < 0 or not path.is_file():
            raise ValueError('PSB_FONT_PATH 不存在或 PSB_FONT_INDEX 无效')
        return path, index
    if sys.platform == 'darwin':
        return ((Path('/System/Library/Fonts/STHeiti Medium.ttc'), 0) if role == 'template'
                else (Path('/System/Library/Fonts/Hiragino Sans GB.ttc'), 1))
    if sys.platform == 'win32':
        directory = Path(os.environ.get('PSB_FONT_DIR') or
                         (Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'))
        # Bold first for visibility; all indices refer to an actual CJK face.
        for name in ('msyhbd.ttc', 'msyh.ttc', 'simhei.ttf', 'simsun.ttc', 'Deng.ttf'):
            path = directory / name
            if path.is_file():
                return path, 0
        raise ValueError('未找到 Windows 中文字体；请安装微软雅黑或设置 PSB_FONT_PATH')
    raise ValueError('当前系统未配置中文字体；请设置 PSB_FONT_PATH 和可选的 PSB_FONT_INDEX')


def load_font(role, size):
    path, index = font_descriptor(role)
    if not path.is_file():
        raise ValueError(f'缺少中文字体：{path}；请设置 PSB_FONT_PATH')
    try:
        return ImageFont.truetype(str(path), size, index=index)
    except (OSError, ValueError) as exc:
        raise ValueError(f'无法加载字体 {path} 的索引 {index}；请检查 PSB_FONT_PATH/PSB_FONT_INDEX') from exc


def check_glyphs(font, text, context):
    """Fail rather than drawing a missing-glyph box for customer copy."""
    missing = font.getmask('\U0010ffff')
    signature = (missing.size, bytes(missing))
    for char in set(text):
        if char.isspace():
            continue
        glyph = font.getmask(char)
        if (glyph.size, bytes(glyph)) == signature:
            raise ValueError(f'{context} 含字体不支持的字符 {char!r}；请更换中文字体')


def local_mask(original):
    """Produce only an alpha mask; never replace or recolor the source pixels."""
    model = os.environ.get('PSB_REMBG_MODEL', 'u2netp')
    if model not in ('u2netp', 'u2net'):
        raise ValueError('PSB_REMBG_MODEL 只能为 u2netp 或 u2net；不允许隐式调用云端模型')
    try:
        from rembg import new_session, remove
    except (ImportError, OSError, SystemExit) as exc:
        raise RuntimeError('缺少本地抠图依赖；Windows 请使用 Python 3.12 安装 requirements-windows.txt，并检查 VC++ 运行库') from exc
    try:
        session = new_session(model, providers=['CPUExecutionProvider'])
        mask = remove(original.convert('RGB'), session=session, only_mask=True)
    except Exception as exc:
        raise RuntimeError('本地前景分割失败；检查模型下载、网络和运行库，或使用已核对的透明 PNG') from exc
    if not isinstance(mask, Image.Image) or mask.size != original.size:
        raise ValueError('本地抠图蒙版尺寸或类型不匹配')
    mask = mask.convert('L')
    low, high = mask.getextrema()
    if high < 128 or low == 255:
        raise ValueError('本地抠图未得到可用的前景和背景；请检查原图或使用透明 PNG')
    return mask, model
