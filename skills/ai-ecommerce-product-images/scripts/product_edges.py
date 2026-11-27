"""Refine automatic masks against the original product photo."""
import math

import numpy as np
from PIL import Image


def _find_cap(rgb, seed):
    """Require a tapered end, two persistent side edges and a separate end edge."""
    import cv2

    widths = np.count_nonzero(seed, axis=1)
    ys = np.flatnonzero(widths >= max(4, widths.max()*.10))
    if not ys.size:
        return None, False
    top, end = ys[[0, -1]]
    length = end-top
    body_width = np.percentile(widths[ys], 85)
    if length < 2.5*body_width or body_width < 22:
        return None, False
    rows = np.arange(max(top, end-round(.34*body_width)), end-round(.13*body_width))
    left = np.argmax(seed[rows], axis=1)
    right = seed.shape[1]-1-np.argmax(seed[rows, ::-1], axis=1)
    width = float(np.median(right-left))
    if width < .40*body_width or width > .89*body_width:
        return None, False
    center = float(np.median((left+right)/2))
    step = max(2, round(width*.035))
    reach = min(round(.98*width), round(.20*length), rgb.shape[0]-end-step-1)
    if reach < .30*width:
        return None, True

    gray = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), 1.15)
    starts = np.arange(end+max(8, round(.24*width)), end+reach+1)
    middle = slice(round(center-.22*width), round(center+.22*width)+1)
    end_change = (gray[starts+step, middle]-gray[starts-step, middle])
    terminal = np.median(end_change, axis=1)
    supported = (np.sign(terminal[:, None])*end_change > 2.4).mean(axis=1)
    candidates = np.argsort(np.abs(terminal)*supported)[::-1]
    for index in candidates[:8]:
        bottom = int(starts[index])
        if abs(terminal[index]) < 4 or supported[index] < .62:
            continue
        span = bottom-end
        probe = np.arange(end+round(.20*span), bottom-round(.20*span)+1)
        edges = []
        strengths = []
        for sign in (-1, 1):
            xs = np.sort(np.rint(center+sign*np.linspace(.21, .51, 36)*width).astype(int))
            xs = np.unique(xs[(xs >= step) & (xs < gray.shape[1]-step)])
            if not xs.size:
                break
            differences = gray[np.ix_(probe, xs+step)]-gray[np.ix_(probe, xs-step)]
            response = np.median(differences, axis=0)
            agreement = (np.sign(response)*differences > 1).mean(axis=0)
            best = int(np.argmax(np.abs(response)*agreement))
            if abs(response[best]) < 1.35 or agreement[best] < .50:
                break
            edges.append(int(xs[best]))
            strengths.append(abs(response[best]))
        if len(edges) != 2 or not .49*width <= edges[1]-edges[0] <= .94*width:
            continue

        if min(strengths) < 3 and (max(strengths) < 3.4 or abs(terminal[index]) < 7):
            continue

        # Allow for the curved end of a cylindrical cap, guided by weaker marks
        # near either side. The subsequent edge pass still uses the photo.
        x0, x1 = edges
        rounding = min(span*.20, (x1-x0)*.14)
        joined = end-max(3, round(.08*width))
        points = [(x0, joined), (x1, joined), (x1, bottom-rounding)]
        for angle in np.linspace(0, np.pi, 17):
            points.append(((x0+x1)/2+(x1-x0)/2*np.cos(angle), bottom-rounding+rounding*np.sin(angle)))
        patch = np.zeros_like(seed, dtype=np.uint8)
        cv2.fillPoly(patch, [np.rint(points).astype(np.int32)], 1)
        return patch.astype(bool), True
    return None, True


def _restore_cap(rgb, seed):
    import cv2

    count, _, stats, _ = cv2.connectedComponentsWithStats(seed.astype(np.uint8), connectivity=8)
    sizes = np.sort(stats[1:, cv2.CC_STAT_AREA])
    if count <= 1 or (len(sizes) > 1 and sizes[-2] > sizes[-1]*.07):
        return seed, 'not-applicable'
    ys, xs = np.where(seed)
    stride = max(1, len(xs)//20_000)
    coords = np.column_stack((xs[::stride], ys[::stride])).astype(np.float32)
    center, axes, variance = cv2.PCACompute2(coords, mean=None)
    if variance[0, 0] < 6*max(.01, variance[1, 0]):
        return seed, 'not-applicable'
    vx, vy = axes[0]
    angle = math.degrees(math.atan2(vy, vx))-90
    angle = (angle+90) % 180-90
    transform = cv2.getRotationMatrix2D(tuple(map(float, center[0])), angle, 1)
    corners = cv2.transform(np.array([[[0., 0.], [rgb.shape[1], 0.], [0., rgb.shape[0]],
                                       [rgb.shape[1], rgb.shape[0]]]], dtype=np.float32), transform)[0]
    origin = np.floor(corners.min(axis=0))
    size = tuple(np.ceil(corners.max(axis=0)-origin).astype(int))
    transform[:, 2] -= origin
    # Low-contrast end analysis only needs moderate resolution. Keep the
    # original resolution for tracing and antialiasing the final contour.
    scale = min(1, 2400/max(size))
    if scale < 1:
        transform *= scale
        size = tuple(math.ceil(value*scale) for value in size)
    aligned = cv2.warpAffine(rgb, transform, size, borderMode=cv2.BORDER_REPLICATE)
    aligned_seed = cv2.warpAffine(seed.astype(np.uint8), transform, size, flags=cv2.INTER_NEAREST).astype(bool)
    patch, tapered = _find_cap(aligned, aligned_seed)
    reverse, reverse_tapered = _find_cap(aligned[::-1], aligned_seed[::-1])
    if patch is None and reverse is None:
        return seed, 'check-tapered-end' if tapered or reverse_tapered else 'not-applicable'
    if patch is None:
        patch = reverse[::-1]
    elif reverse is not None:
        patch |= reverse[::-1]
    restored = cv2.warpAffine(patch.astype(np.uint8), cv2.invertAffineTransform(transform),
                              (seed.shape[1], seed.shape[0]), flags=cv2.INTER_NEAREST).astype(bool)
    return seed | restored, 'recovered-from-edge-evidence'


def _smooth(values, sigma):
    import cv2

    padding = round(3*sigma)+1
    wrapped = np.pad(values, ((padding, padding), (0, 0)), mode='wrap')
    return cv2.GaussianBlur(wrapped[:, None, :], (1, 2*padding+1), sigma)[padding:-padding, 0].reshape(values.shape)


def _guided_contours(rgb, seed, radius):
    import cv2

    # RETR_TREE retains holes and separate items. Approximate only subpixel wiggle.
    contours, _ = cv2.findContours(seed.astype(np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    photo = cv2.GaussianBlur(rgb, (0, 0), .7).astype(np.float32)
    offsets = np.arange(-radius, radius+.25, .5, dtype=np.float32)
    step = max(1.0, radius*.32)
    smooth_contours = []
    for contour in contours:
        if cv2.contourArea(contour) < 5:
            continue
        points = contour[:, 0, :].astype(np.float32)
        sigma = float(np.clip(.033*min(seed.shape), 9, 18))
        base = _smooth(points, 1.35)
        span = max(5, round(sigma*1.4))
        incoming = base-np.roll(base, span, axis=0)
        outgoing = np.roll(base, -span, axis=0)-base
        norms = np.linalg.norm(incoming, axis=1)*np.linalg.norm(outgoing, axis=1)
        straight = np.clip(((incoming*outgoing).sum(axis=1)/np.maximum(norms, 1e-4)-.45)/.5, 0, 1)
        base += (_smooth(points, sigma)-base)*straight[:, None]
        tangent = np.roll(base, -2, axis=0)-np.roll(base, 2, axis=0)
        normals = np.column_stack((-tangent[:, 1], tangent[:, 0]))
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-4)
        # OpenCV follows centers of pixels just inside each foreground boundary.
        base += .44*normals
        responses = []
        for offset in offsets:
            before = base+(offset-step)*normals
            after = base+(offset+step)*normals
            change = []
            for start in range(0, len(base), 16000):
                a, b = before[start:start+16000], after[start:start+16000]
                first = cv2.remap(photo, a[:, :1], a[:, 1:], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                second = cv2.remap(photo, b[:, :1], b[:, 1:], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                change.append(np.linalg.norm(first[:, 0]-second[:, 0], axis=1))
            responses.append(np.concatenate(change))
        strengths = np.column_stack(responses)
        strengths = _smooth(strengths, max(3, radius*1.1))
        middle = int(np.argmin(abs(offsets)))
        winners = np.argmax(strengths-2.6*abs(offsets), axis=1)
        good = (strengths[np.arange(len(base)), winners] > np.maximum(9, strengths[:, middle]*1.10))
        shift = _smooth((offsets[winners]*good)[:, None], max(9, 1.85*radius))
        smooth_contours.append(base+shift*normals)
    return smooth_contours


def refine_product_mask(image, mask, *, recover_caps=True):
    """Conservative contour repair for an automatically masked opaque package."""
    import cv2

    max_alpha = mask.getextrema()[1]
    if max_alpha < 180:
        return mask, {'contour_refined': False, 'cap_check': 'low-alpha-check-source'}
    bounds = mask.point(lambda value: 255 if value >= max(104, round(max_alpha*.50)) else 0).getbbox()
    if not bounds:
        return mask, {'contour_refined': False, 'cap_check': 'empty-seed'}
    x0, y0, x1, y1 = bounds
    short_side = min(x1-x0, y1-y0)
    pad = min(round(short_side*1.1)+8, round(max(x1-x0, y1-y0)*.25)+8) if recover_caps else 8
    box = (max(0, x0-pad), max(0, y0-pad), min(image.width, x1+pad), min(image.height, y1+pad))
    if max(box[2]-box[0], box[3]-box[1]) >= 32767:
        return mask, {'contour_refined': False, 'cap_check': 'source-too-large-for-guided-refinement'}
    rgb = np.asarray(image.crop(box).convert('RGB'))
    seed = np.asarray(mask.crop(box)) >= max(104, round(max_alpha*.50))
    repaired, cap_status = _restore_cap(rgb, seed) if recover_caps else (seed, 'disabled')
    radius = round(float(np.clip(short_side*.009, 2, 6)))
    contours = _guided_contours(rgb, repaired, radius)
    if not contours:
        return mask, {'contour_refined': False, 'cap_check': cap_status}
    height, width = repaired.shape
    scale = max(1, min(4, math.isqrt(40_000_000//(height*width))))
    # Offset to the center of each original pixel for symmetric coverage.
    points = [np.rint((path+.5)*scale-.5).astype(np.int32) for path in contours]
    coverage = np.zeros((height*scale, width*scale), dtype=np.uint8)
    cv2.fillPoly(coverage, points, 255)
    local = Image.fromarray(coverage).resize((width, height), Image.Resampling.BOX)
    result = Image.new('L', image.size)
    result.paste(local, box[:2])
    return result, {'contour_refined': True, 'cap_check': cap_status, 'edge_search_radius_px': radius}
