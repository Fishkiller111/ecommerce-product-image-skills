"""Typography and non-destructive lighting for reference-led detail scenes."""
from PIL import Image, ImageDraw

from render_detail import fitted, load_font, valid_text


def read_scene_layout(raw, kind, items):
    if not isinstance(raw, dict) or raw.keys() - {
        'tone', 'header', 'marker', 'highlight', 'copy_position', 'light'
    }:
        raise ValueError('scene_layout 仅支持 tone、header、marker、highlight、copy_position、light')
    tone = raw.get('tone', 'dark' if kind == 'hero' else 'light')
    position = raw.get('copy_position', 'above')
    if tone not in ('dark', 'light') or position not in ('above', 'left', 'right'):
        raise ValueError('scene_layout 的 tone 或 copy_position 无效')
    highlight = raw.get('highlight')
    if highlight is not None:
        if kind != 'hero' or not isinstance(highlight, dict) or highlight.keys() - {'value', 'label', 'source'}:
            raise ValueError('highlight 仅用于首屏，支持 value、label、source')
        highlight = {key: valid_text(highlight.get(key, ''), key, key == 'source')
                     for key in ('value', 'label', 'source')}
    if not (items or highlight):
        raise ValueError('场景图文布局至少需要一条说明或有依据的重点参数')
    light = raw.get('light', {})
    limits = {'exposure': .20, 'warmth': .12, 'falloff': .20}
    if not isinstance(light, dict) or light.keys() - limits.keys():
        raise ValueError('light 仅支持 exposure、warmth、falloff')
    light = {key: light.get(key, 0) for key in limits}
    if any(type(value) not in (int, float) or not -limits[key] <= value <= limits[key]
           for key, value in light.items()):
        raise ValueError('light 超出范围：exposure/falloff ±0.20，warmth ±0.12')
    return {
        'tone': tone, 'copy_position': position, 'highlight': highlight, 'light': light,
        **{key: valid_text(raw.get(key, ''), key, True) for key in ('header', 'marker')},
    }


def relight_product(asset, origin, canvas_width, light):
    """Change reflected light smoothly across the canvas, preserving the source matte."""
    import numpy as np

    rgba = np.array(asset, copy=True)
    rgb = rgba[:, :, :3].astype(np.float32)
    x = (np.arange(asset.width, dtype=np.float32) + origin[0]) / max(1, canvas_width - 1)
    exposure = light['exposure'] + light['falloff'] * (1 - 2 * x)
    warmth = light['warmth'] * np.array([1., .23, -1.], dtype=np.float32)
    headroom = np.minimum(rgb, 255 - rgb)
    opacity = rgba[:, :, 3:4].astype(np.float32) / 255
    rgba[:, :, :3] = np.rint(rgb + headroom * opacity * (exposure[:, None] + warmth))
    return Image.fromarray(rgba)


def draw_scene_copy(panel, page):
    layout = page['scene_layout']
    dark = layout['tone'] == 'dark'
    ink = '#fff0d1' if dark else '#3e231b'
    secondary = '#f1cfa6' if dark else '#6b4433'
    accent = '#f2c17f' if dark else '#955233'
    card_fill, card_border, card_line = (255, 242, 218), (255, 249, 232), '#d9b68d'
    card_label, card_ink = '#754937', '#48271d'
    if panel.palette != 'heritage':
        ink = panel.paper if dark else panel.ink
        secondary = panel.shade if dark else panel.ink
        accent = secondary
        card_fill, card_border, card_line = panel.paper, panel.paper, panel.shade
        card_label = card_ink = panel.ink
    line_width = max(1, round(panel.w / 600))
    copy_regions = []

    def write(value, box, size, minimum, *, color=ink, align=True, bold=False, lines=1):
        if value:
            fitted(panel.draw, value, panel.rect(box), round(size * panel.w),
                   round(minimum * panel.w), lines, color, center=align,
                   role='template' if bold else 'hero', font_loader=load_font)
            copy_regions.append(box)

    def rule(box, color):
        panel.draw.line(panel.rect(box), fill=color, width=line_width)

    def card(box):
        overlay = Image.new('RGBA', panel.canvas.size)
        ImageDraw.Draw(overlay).rounded_rectangle(
            panel.rect(box), radius=round(.023 * panel.w), fill=(*card_fill, 238),
            outline=(*card_border, 247), width=line_width,
        )
        panel.canvas.alpha_composite(overlay)
        copy_regions.append(box)

    header, marker = layout['header'], layout['marker']
    if header or marker:
        write(header, (.066, .036, .68, .083), .031, .022, align=False, bold=True)
        write(marker, (.75, .036, .934, .083), .025, .019, color=secondary)
        rule((.066, .091, .934, .091), secondary)
    top = .127 if header or marker else .068
    write(page['title'], (.055, top, .945, top+.102), .096, .049, bold=True, lines=2)
    if page['subtitle']:
        write(page['subtitle'], (.08, top+.104, .92, top+.151), .036, .024, color=secondary)

    position = layout['copy_position']
    x0, x1 = {'above': (.07, .93), 'left': (.065, .48), 'right': (.52, .935)}[position]
    highlight = layout['highlight']
    if highlight:
        if position == 'above':
            write(highlight['value'], (.085, .322, .49, .495), .204, .073, align=False, bold=True)
            rule((.506, .369, .506, .454), accent)
            write(highlight['label'], (.535, .365, .91, .458), .043, .028,
                  color=secondary, align=False, bold=True, lines=2)
        else:
            write(highlight['value'], (x0, .382, x1, .552), .204, .078, bold=True)
            write(highlight['label'], (x0, .555, x1, .633), .044, .028,
                  color=secondary, bold=True, lines=2)

    items = page['items']
    if items and page['kind'] == 'hero' and (highlight or position == 'above'):
        y = .863 if highlight else .369
        card((.065, y, .935, y+.103))
        span = .87 / len(items)
        for index, item in enumerate(items):
            x = .065 + span * index
            if index:
                rule((x, y+.021, x, y+.082), card_line)
            write(item['label'], (x+.017, y+.013, x+span-.017, y+(.046 if item['text'] else .09)),
                  .025 if item['text'] else .033, .017, color=card_label)
            write(item['text'], (x+.017, y+.047, x+span-.017, y+.09),
                  .034, .020, color=card_ink, bold=True, lines=2)
    elif items:
        if position == 'above':
            x0, x1 = .36, .932
        y0, y1 = (.286, .515) if position == 'above' else (.318, .745)
        card((x0, y0, x1, y1))
        row = (y1-y0-.025) / len(items)
        for index, item in enumerate(items):
            y = y0+.012+index*row
            if index:
                rule((x0+.028, y, x1-.028, y), card_line)
            title = item['label']
            body = item['text']
            if position == 'above' and title and body:
                divider = x0+(x1-x0)*.37
                write(title, (x0+.031, y+.005, divider, y+row-.004),
                      .027, .019, color=card_label, align=False)
                write(body, (divider+.012, y+.005, x1-.024, y+row-.004),
                      .034, .020, color=card_ink, align=False, bold=True, lines=2)
            else:
                split = y+row*.46 if title and body else y
                write(title, (x0+.028, y+.005, x1-.026, split if body else y+row-.004),
                      .030, .018, color=card_label, lines=2)
                write(body, (x0+.028, split+.003, x1-.026, y+row-.004),
                      .037, .021, color=card_ink, bold=True, lines=2)
    return [panel.rect(box) for box in copy_regions]
