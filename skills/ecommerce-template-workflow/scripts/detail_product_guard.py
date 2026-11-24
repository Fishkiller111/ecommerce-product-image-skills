"""Inspect real product layers after the scene, product and local copy are composited."""
from PIL import Image, ImageChops


def check_product_layers(final, layers):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ValueError('商品 Canny 核验需要本机 opencv-python-headless') from exc

    guide = Image.new('L', final.size)
    later_opacity = Image.new('L', final.size)
    checks = []
    for xy, asset, reference in reversed(layers):
        x, y = xy
        box = (x, y, x+asset.width, y+asset.height)
        alpha = np.asarray(asset.getchannel('A'))
        later = np.asarray(later_opacity.crop(box)) > 0
        # Compare against the original raster after only its declared placement transform
        # and alpha compositing, using the scene that was immediately behind the layer.
        target = np.asarray(reference.convert('RGB'))
        actual = np.asarray(final.crop(box).convert('RGB'))
        visible = (alpha > 0) & ~later
        original_size = int((alpha > 0).sum())
        visible_count = int(visible.sum())
        if not visible_count:
            raise ValueError('商品被完全遮挡，请调整商品摆位后重跑')

        changed = int(np.count_nonzero(np.any(target != actual,axis=2) & visible))

        def edges(rgb):
            gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
            return cv2.Canny(gray,55,140) > 0

        # Restore the reference context under an intentional overlap before edge
        # detection. Canny's hysteresis can follow a changed edge beyond the overlap.
        near_product = cv2.dilate((alpha > 0).astype('uint8'),np.ones((5,5),np.uint8)) > 0
        check_area = near_product & ~later
        reference_edges = edges(target)
        actual_edges = edges(np.where(check_area[:,:,None],actual,target))
        mismatch = int(np.count_nonzero((reference_edges ^ actual_edges) & check_area))
        if changed or mismatch:
            raise ValueError(f'商品完整性核验失败，{changed} 个像素和 {mismatch} 个 Canny 边缘像素变化')

        outline = cv2.Canny(alpha,55,140) > 0
        core = cv2.erode((alpha >= 250).astype('uint8'),np.ones((5,5),np.uint8)) > 0
        detail = edges(np.asarray(asset.convert('RGB'))) & core
        layer_guide = Image.fromarray(((outline | detail) & ~later).astype('uint8')*255)
        guide.paste(ImageChops.lighter(guide.crop(box),layer_guide),xy)
        later_opacity.paste(ImageChops.lighter(later_opacity.crop(box),asset.getchannel('A')),xy)
        checks.append({
            'rect': list(box), 'visible_product_px':visible_count, 'changed_rgb_px':changed,
            'visible_fraction':round(visible_count/original_size,4),
            'compared_edges_px':int(np.count_nonzero(reference_edges & check_area)),
            'changed_edges_px':mismatch, 'canny_thresholds':[55,140],
        })
    return list(reversed(checks)), guide
