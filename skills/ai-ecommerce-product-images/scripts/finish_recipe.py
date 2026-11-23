"""Local, source-bound silhouette and palette refinements."""

import math

import numpy as np
from PIL import Image, ImageDraw


def outline_mask(size, points):
    """Rasterize ordered source-space contour points with subpixel coverage."""
    width, height = size
    coords = np.asarray(points, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 2 or not 3 <= len(coords) <= 20000:
        raise ValueError('轮廓须为依次排列的 3–20000 个 [x,y] 点')
    if not np.isfinite(coords).all() or (coords < 0).any() or (coords > [width-1, height-1]).any():
        raise ValueError('轮廓点须位于原图范围内')
    left, top = np.maximum(np.floor(coords.min(axis=0)).astype(int)-2, 0)
    right, bottom = np.minimum(np.ceil(coords.max(axis=0)).astype(int)+3, size)
    bounds_size = (int(right-left), int(bottom-top))
    # Bound temporary memory even when the original product takes up most of a large photo.
    pixels = math.prod(bounds_size)
    factor = max(1, min(6, math.isqrt(64_000_000//pixels)))
    hi = Image.new('L', tuple(v*factor for v in bounds_size))
    xy = [tuple(pt) for pt in (coords-[left, top]+.5)*factor]
    ImageDraw.Draw(hi).polygon(xy, fill=255)
    mask = Image.new('L', size)
    mask.paste(hi.resize(bounds_size, Image.Resampling.BOX), (int(left), int(top)))
    return mask


def palette_grade(image, samples, origin, base_image):
    """Match local colors to representative swatches without moving any pixels."""
    import cv2

    if not isinstance(samples, list) or not 1 <= len(samples) <= 16:
        raise ValueError('palette 须包含 1–16 组取样')
    rgba = np.array(image)
    source_x, source_y = origin
    rgb = rgba[:, :, :3].astype(np.float32)/255
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    base = cv2.cvtColor(np.asarray(base_image)[:, :, :3].astype(np.float32)/255, cv2.COLOR_RGB2LAB)
    total = np.zeros(lab.shape[:2], dtype=np.float32)
    shift = np.zeros_like(lab)
    for sample in samples:
        pair = np.asarray([sample['source'], sample['target']], dtype=np.float32)
        if pair.shape != (2, 3) or not np.isfinite(pair).all() or (pair < 0).any() or (pair > 255).any():
            raise ValueError('色样须为三通道 sRGB 值 0–255')
        radius = np.asarray(sample.get('radius_lab', [23, 14, 14]), dtype=np.float32)
        if radius.shape != (3,) or not np.isfinite(radius).all() or (radius < 1).any() or (radius > 100).any():
            raise ValueError('匹配范围 radius_lab 须为三个 1–100 的值')
        source_lab, target_lab = cv2.cvtColor(pair[None, :, :]/255, cv2.COLOR_RGB2LAB)[0]
        distance = np.sum(((lab-source_lab)/radius)**2, axis=2)
        weight = np.exp(-2*distance)
        if 'region' in sample:
            x0, y0, x1, y1 = sample['region']
            if not all(math.isfinite(v) for v in (x0,y0,x1,y1)) or x0>=x1 or y0>=y1:
                raise ValueError('色样区域须为有效的 [左,上,右,下] 框')
            xs = np.arange(image.width)+source_x
            ys = np.arange(image.height)+source_y
            wx = np.clip(np.minimum(xs-x0,x1-xs)/16,0,1)
            wy = np.clip(np.minimum(ys-y0,y1-ys)/16,0,1)
            weight *= wy[:, None]*wx
        total += weight
        shift += weight[:, :, None]*(target_lab-source_lab)
    # Transition back to the standard grade for colors outside the sampled palette.
    influence = np.clip(total/.8, 0, 1)[:, :, None]
    shift /= np.maximum(total, 1e-6)[:, :, None]
    shift[:, :, 0] = np.minimum(shift[:, :, 0], (100-lab[:, :, 0])*.92)
    corrected = base + ((lab + shift)-base)*influence
    adjusted = cv2.cvtColor(corrected, cv2.COLOR_LAB2RGB)
    visible = rgba[:, :, 3] > 0
    rgba[visible, :3] = np.rint(adjusted[visible]*255).astype(np.uint8)
    return Image.fromarray(rgba)


def remove_fringe(image, radius):
    """Use nearby interior color in a narrow edge band of an opaque subject."""
    from scipy.ndimage import distance_transform_edt

    rgba = np.array(image)
    alpha = rgba[:, :, 3]
    distance = distance_transform_edt(alpha >= 128)
    core = (distance >= radius+.3) & (alpha == 255)
    if not core.any():
        raise ValueError('没有足够的实心区域可修边，请缩小 decontaminate_px')
    near = distance_transform_edt(~core, return_distances=False, return_indices=True)
    weights = np.clip(1-distance/radius, 0, 1)*(alpha > 0)
    band = weights > 0
    core_rgb = rgba[near[0][band], near[1][band], :3]
    mix = weights[band, None]
    rgba[band, :3] = np.rint(rgba[band, :3]*(1-mix) + core_rgb*mix).astype(np.uint8)
    rgba[alpha == 0, :3] = 0
    return Image.fromarray(rgba)
