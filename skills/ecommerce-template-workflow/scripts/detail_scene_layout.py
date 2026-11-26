"""Typography and non-destructive lighting for reference-led detail scenes."""
from PIL import Image, ImageDraw, ImageFilter

from render_detail import fitted, load_font, valid_text


def read_scene_layout(raw, kind, items, subtitle):
    if not isinstance(raw, dict) or raw.keys() - {
        'tone', 'header', 'marker', 'highlight', 'copy_position', 'light', 'footer'
    }:
        raise ValueError('scene_layout 仅支持 tone、header、marker、highlight、copy_position、light、footer')
    tone = raw.get('tone', 'dark' if kind == 'hero' else 'light')
    position = raw.get('copy_position', 'left' if kind == 'reasons' else 'above')
    if tone not in ('dark', 'light') or position not in ('above', 'left', 'right'):
        raise ValueError('scene_layout 的 tone 或 copy_position 无效')
    highlight = raw.get('highlight')
    if highlight is not None:
        if kind != 'hero' or not isinstance(highlight, dict) or highlight.keys() - {'value', 'label', 'source'}:
            raise ValueError('highlight 仅用于首屏，支持 value、label、source')
        highlight = {key: valid_text(highlight.get(key, ''), key, key == 'source')
                     for key in ('value', 'label', 'source')}
    footer = raw.get('footer')
    if footer is not None:
        if not isinstance(footer, dict) or footer.keys() - {'text', 'source'}:
            raise ValueError('footer 仅支持 text、source')
        footer = {key: valid_text(footer.get(key, ''), key, key == 'source')
                  for key in ('text', 'source')}
    if not (subtitle or items or highlight or footer):
        raise ValueError('场景图文布局至少需要一条产品介绍或说明')
    light = raw.get('light', {})
    limits = {'exposure': .20, 'warmth': .12, 'falloff': .20}
    if not isinstance(light, dict) or light.keys() - limits.keys():
        raise ValueError('light 仅支持 exposure、warmth、falloff')
    light = {key: light.get(key, 0) for key in limits}
    if any(type(value) not in (int, float) or not -limits[key] <= value <= limits[key]
           for key, value in light.items()):
        raise ValueError('light 超出范围：exposure/falloff ±0.20，warmth ±0.12')
    return {
        'tone': tone, 'copy_position': position, 'highlight': highlight, 'light': light, 'footer': footer,
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


def integrated_surface(canvas, rect, tint):
    """Soften the existing scene locally to make a continuous, readable text surface."""
    patch = canvas.crop(rect)
    scale = max(2, min(round(canvas.width*.016), min(patch.size)//8))
    softened = patch.filter(ImageFilter.GaussianBlur(scale))
    filtered = Image.blend(softened, Image.new('RGBA', patch.size, (*tint, 255)), .24)
    mask = Image.new('L', patch.size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (scale, scale, patch.width-scale-1, patch.height-scale-1),
        radius=scale*2, fill=224,
    )
    canvas.paste(filtered, rect[:2], mask.filter(ImageFilter.GaussianBlur(scale*.85)))


def draw_reasons_copy(panel, page):
    layout = page.get('scene_layout', {})
    dark = layout.get('tone') == 'dark'
    ink = panel.paper if dark else panel.ink
    tint = panel.ink if dark else panel.paper
    header, marker = layout.get('header'), layout.get('marker')
    regions = []

    def write(value, box, size, minimum, *, bold=False, center=False, lines=1):
        if value:
            fitted(panel.draw, value, panel.rect(box), round(size*panel.w),
                   round(minimum*panel.w), lines, ink, center=center,
                   role='template' if bold else 'hero', font_loader=load_font)
            regions.append(box)

    write(header, (.16,.050,.84,.097), .031, .020, center=True)
    write(marker, (.82,.05,.97,.097), .024, .017, center=True)
    write(page['title'], (.075,.108,.925,.215), .083, .049, bold=True, center=True, lines=2)
    write(page['subtitle'], (.10,.219,.90,.266), .034, .022, center=True)

    position = layout.get('copy_position', 'above')
    side = position in ('left', 'right')
    columns = 2 if layout and not side else 1
    span = .435 if side or columns == 2 else .84
    items = page['items']
    row_count = (len(items)+columns-1)//columns
    stack = .28 if columns == 2 else .55
    step = stack/row_count
    cards = Image.new('RGBA', panel.canvas.size)
    shapes = ImageDraw.Draw(cards)
    boxes = []
    for index, item in enumerate(items):
        row, col = divmod(index, columns)
        if side:
            left = .075 if position == 'left' else .535
        elif columns == 2:
            left = .5-span/2 if col == 0 and index == len(items)-1 else .055+col*.455
        else:
            left = .08
        top = .282+row*step
        bottom = top+min(step-.017, .155)
        box = (left, top, left+span, bottom)
        x0,y0,x1,y1 = panel.rect(box)
        shapes.rounded_rectangle((x0,y0,x1,y1), radius=max(4, round(panel.w*.036)),
                                 fill=(*tint, 138), outline=(*ink, 76), width=max(1,panel.w//700))
        boxes.append((item, box))
    panel.canvas.alpha_composite(cards)

    for item, (left, top, right, bottom) in boxes:
        label, body = item['label'], item['text']
        height = bottom-top
        split = top+height*.53
        if label and body:
            write(label, (left+.028,top+.07*height,right-.023,split), .044, .024, bold=True, lines=2)
            write(body, (left+.028,split,right-.023,bottom-.09*height), .031, .019, lines=2)
        else:
            write(label or body, (left+.028,top+.09*height,right-.023,bottom-.09*height),
                  .040, .023, bold=bool(label), lines=2)
        regions.append((left, top, right, bottom))
    footer = layout.get('footer')
    if footer:
        write(footer['text'], (.087,.912,.913,.979), .027, .020, lines=2)
    return [panel.rect(box) for box in regions]


def draw_scene_copy(panel, page):
    if page['kind'] == 'reasons':
        return draw_reasons_copy(panel, page)
    layout = page['scene_layout']
    dark = layout['tone'] == 'dark'
    ink = '#fff0d1' if dark else '#3e231b'
    secondary = '#f1cfa6' if dark else '#6b4433'
    surface_tint = (87, 28, 20) if dark else (255, 231, 198)
    divider_ink = (249, 206, 152, 84) if dark else (99, 49, 24, 63)
    if panel.palette != 'heritage':
        ink = panel.paper if dark else panel.ink
        secondary = panel.shade if dark else panel.ink
        surface_tint = panel.ink if dark else panel.paper
        divider_ink = (*secondary, 72)
    rules = Image.new('RGBA', panel.canvas.size)
    rule_draw = ImageDraw.Draw(rules)
    copy_regions = []

    def write(value, box, size, minimum, *, color=ink, align=True, bold=False, lines=1):
        if value:
            fitted(panel.draw, value, panel.rect(box), round(size * panel.w),
                   round(minimum * panel.w), lines, color, center=align,
                   role='template' if bold else 'hero', font_loader=load_font)
            copy_regions.append(box)

    def rule(box):
        rule_draw.line(panel.rect(box), fill=divider_ink, width=max(1, round(panel.w / 750)))

    def surface(box):
        integrated_surface(panel.canvas, panel.rect(box), surface_tint)
        copy_regions.append(box)

    hero = page['kind'] == 'hero'
    highlight = layout['highlight']
    header, marker = layout['header'], layout['marker']
    simple_hero = hero and not highlight
    left = .087
    if header or marker:
        y = .130 if simple_hero else .049
        write(header, (left, y, .70, y+.046), .036, .022, align=False, bold=True)
        write(marker, (.75, y, .913, y+.046), .025, .019, color=secondary)
    top = (.217 if simple_hero else .122) if header or marker else (.179 if simple_hero else .079)
    write(page['title'], (left, top, .92, top+.106), .102 if hero else .077,
          .047, align=False, bold=True, lines=2)
    if page['subtitle']:
        write(page['subtitle'], (left, top+.111, .92, top+.159), .038, .024,
              color=secondary, align=False)

    position = layout['copy_position']
    x0, x1 = {'above': (.07, .93), 'left': (.065, .48), 'right': (.52, .935)}[position]
    if highlight:
        if position == 'above':
            write(highlight['value'], (left, .315, .49, .493), .134, .069, align=False, bold=True)
            rule((.495, .366, .495, .435))
            write(highlight['label'], (.518, .349, .91, .454), .041, .028,
                  color=secondary, align=False, bold=True, lines=2)
        else:
            write(highlight['value'], (x0, .382, x1, .552), .134, .069, align=False, bold=True)
            write(highlight['label'], (x0, .555, x1, .633), .041, .028,
                  color=secondary, align=False, lines=2)

    items = page['items']
    if items and hero and (highlight or position == 'above'):
        y = .856 if highlight else (.388 if header or marker else .365)
        surface((.066, y, .934, y+.098))
        span = .826 / len(items)
        for index, item in enumerate(items):
            x = left + span * index
            if index:
                rule((x, y+.024, x, y+.076))
            write(item['label'], (x+.017, y+.013, x+span-.017, y+(.046 if item['text'] else .09)),
                  .025 if item['text'] else .033, .017, color=secondary, align=False)
            write(item['text'], (x+.017, y+.047, x+span-.017, y+.09),
                  .034, .020, align=False, bold=True, lines=2)
    elif items:
        if position == 'above':
            x0, x1 = .374, .928
        y0, y1 = ((.288 if header or marker else .251), .518) if position == 'above' else (.318, .745)
        surface((x0, y0, x1, y1))
        row = (y1-y0-.035) / len(items)
        for index, item in enumerate(items):
            y = y0+.017+index*row
            if index:
                rule((x0+.036, y, x1-.032, y))
            title = item['label']
            body = item['text']
            if position == 'above' and title and body:
                divider = x0+(x1-x0)*.34
                write(title, (x0+.038, y+.005, divider, y+row-.004),
                      .024, .019, color=secondary, align=False)
                write(body, (divider+.012, y+.005, x1-.024, y+row-.004),
                      .035, .022, align=False, bold=True, lines=2)
            else:
                split = y+row*.43 if title and body else y
                write(title, (x0+.038, y+.005, x1-.026, split if body else y+row-.004),
                      .030, .018, color=secondary, align=False, bold=not body, lines=2)
                write(body, (x0+.038, split+.003, x1-.026, y+row-.004),
                      .037, .021, align=False, bold=True, lines=2)

    if layout['footer']:
        y = .958 if hero and items and highlight else .902
        rule((left, y, .913, y))
        write(layout['footer']['text'], (left, y+.008, .913, .983),
              .028, .020, align=False, lines=2)
    panel.canvas.alpha_composite(rules)
    return [panel.rect(box) for box in copy_regions]
