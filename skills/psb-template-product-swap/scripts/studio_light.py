"""Selective studio exposure for a product cutout; no rendering of new detail."""

import numpy as np
from PIL import Image


def smooth(a, b, value):
    x = np.clip((value - a) / (b - a), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def studio_light(product):
    rgba = np.asarray(product.convert('RGBA'))
    rgb = rgba[:, :, :3].astype(np.float32)
    alpha = rgba[:, :, 3]
    solid = alpha >= 224
    weights = np.array([.2126, .7152, .0722], dtype=np.float32)
    original_y = rgb @ weights
    shadow_lift = 1.0
    exposure_rgb = rgb
    if solid.any():
        middle, top = np.percentile(original_y[solid], [50, 90])
        # Lift an underlit cutout only when there is highlight headroom and
        # sufficient midtone evidence. Don't wash out genuinely dark products.
        shadow_lift += .91 * float(smooth(45, 72, middle)) * float(1 - smooth(106, 156, top))
        if shadow_lift > 1.001:
            lifted = 255 * (1 - (1 - rgb / 255) ** shadow_lift)
            amount = smooth(30, 76, original_y)[:, :, None]
            exposure_rgb = rgb + (lifted - rgb) * amount
    r, g, b = exposure_rgb.transpose(2, 0, 1)
    peak = exposure_rgb.max(axis=2)
    bottom = exposure_rgb.min(axis=2)
    chroma = peak - bottom
    sat = chroma / np.maximum(1, peak)
    y = .2126 * r + .7152 * g + .0722 * b

    # A restrained exposure curve for colored material. Preserve the toe for
    # dark printed lines and gently roll off the shoulder rather than clipping.
    base_y = np.interp(y, [0, 42, 80, 128, 174, 215, 240, 255],
                       [0, 42, 84, 137, 186, 224, 245, 255]).astype(np.float32)
    base = exposure_rgb + np.minimum(base_y - y, 255 - peak)[:, :, None]

    # Bring whites and light grays forward, without whitening colored ink.
    neutral = (1 - smooth(.055, .19, sat)) * smooth(82, 133, y)
    white_y = np.interp(y, [0, 72, 128, 160, 183, 204, 225, 244, 255],
                        [0, 73, 149, 187, 209, 222, 235, 247, 255]).astype(np.float32)
    white = white_y[:, :, None] + (exposure_rgb - y[:, :, None]) * .60
    lit = base + (white - base) * neutral[:, :, None]

    # Lift yellow label midtones separately. Exclude reds/greens and dark
    # strokes by hue, saturation and luma; bound the red shoulder below 250.
    hue_r = 60 * (g - b) / np.maximum(1, chroma)
    yellow = ((r >= g) & (r >= b)) * smooth(29, 43, hue_r) * (1 - smooth(60, 72, hue_r))
    yellow *= smooth(.28, .63, sat) * smooth(76, 130, y)
    kick = np.minimum(np.maximum(0, 249 - peak) * .94, 59)
    golden = exposure_rgb + kick[:, :, None] * np.array([1.0, 1.08, .045], dtype=np.float32)
    lit += (golden - lit) * yellow[:, :, None]

    # Soft edge blend keeps the original matte and transparent RGB intact.
    blend = smooth(16, 176, alpha.astype(np.float32))
    out = rgba.copy()
    out[:, :, :3] = np.rint(rgb + (lit - rgb) * blend[:, :, None]).clip(0, 255).astype(np.uint8)
    after = out[:, :, :3].astype(np.float32) @ weights
    report = {
        'preset': 'studio-light-v2',
        'shadow_lift': round(shadow_lift, 3),
        'alpha_unchanged': True,
        'median_luma_before': round(float(np.median(original_y[solid])), 1) if solid.any() else None,
        'median_luma_after': round(float(np.median(after[solid])), 1) if solid.any() else None,
    }
    return Image.fromarray(out), report
