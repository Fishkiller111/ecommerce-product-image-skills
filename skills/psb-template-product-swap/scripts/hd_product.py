"""Non-generative, alpha-safe photo preparation before template compositing."""

import numpy as np
from PIL import Image, ImageFilter


def prepare_hd_product(product, placement_size):
    """Return a separately inspectable RGBA asset and its resolution audit.

    Process the product, not the completed layout. Keep the matte untouched by
    luma filters and never infer or redraw packaging glyphs.
    """
    w, h = product.size
    tw, th = placement_size
    required = max(tw / w, th / h)
    target_scale = required * 1.5 if required > 1.01 else 1.0
    scale = min(target_scale, 3.0, 2560 / max(w, h))
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    rgba = product.resize(size, Image.Resampling.LANCZOS) if size != product.size else product.copy()
    # Pillow resamples RGBA in premultiplied form, avoiding transparent-color
    # bleed. The following adjustment is limited to the opaque interior.
    alpha = rgba.getchannel('A')
    guard_size = 2 * max(2, round(1.8 * scale)) + 1
    # Some delivered PNGs have alpha 254 across the entire solid body. Count
    # near-opaque interior pixels, but still erode away all translucent edges.
    safe = np.asarray(alpha.filter(ImageFilter.MinFilter(guard_size))) >= 250
    light = rgba.convert('RGB').convert('L')
    y = np.asarray(light, dtype=np.float32)

    # Denoise only small luminance variations in flat areas; preserve real edges.
    smooth = np.asarray(light.filter(ImageFilter.GaussianBlur(max(0.55, scale * 0.34))), dtype=np.float32)
    texture = y - smooth
    flat = np.clip(1 - np.abs(texture) / 5.0, 0, 1) ** 2
    denoised = y - 0.48 * flat * texture

    # Improve contrast at existing strokes/edges, not new details. The local
    # envelope and per-pixel cap limit haloing and excessive contrast.
    detail_base = Image.fromarray(np.rint(denoised).clip(0, 255).astype(np.uint8))
    low = np.asarray(detail_base.filter(ImageFilter.GaussianBlur(max(0.85, scale * 0.86))), dtype=np.float32)
    detail = denoised - low
    edge_gate = np.clip((np.abs(detail) - 0.75) / 2.4, 0, 1)
    amount = 1.08 if required > 1.10 else 0.62
    win = 2 * max(2, round(scale * 1.15)) + 1
    floor = np.asarray(light.filter(ImageFilter.MinFilter(win)), dtype=np.float32)
    ceil = np.asarray(light.filter(ImageFilter.MaxFilter(win)), dtype=np.float32)
    sharpened = np.clip(denoised + amount * detail * edge_gate, floor - 1, ceil + 1)
    delta = np.where(safe, np.clip(sharpened - y, -15, 15), 0)

    # Shift RGB together (luminance, not recoloring); stay inside the gamut.
    out = np.array(rgba)
    rgb = out[:, :, :3].astype(np.int16)
    delta = np.rint(delta).astype(np.int16)
    delta = np.clip(delta, -rgb.min(axis=2), 255 - rgb.max(axis=2))
    out[:, :, :3] = (rgb + delta[:, :, None]).astype(np.uint8)

    return Image.fromarray(out), {
        'method': 'non-generative-lanczos-flat-denoise-bounded-luma-detail',
        'source_subject_px': [w, h],
        'hd_subject_px': list(size),
        'placed_subject_px': [tw, th],
        'enlarge_ratio': round(scale, 3),
        'source_upscaled_in_layout': required > 1.01,
        'detail_status': '原片小于置入尺寸；改善观感，未恢复不可辨识文字' if required > 1.01 else '原片像素足以覆盖置入尺寸',
    }
