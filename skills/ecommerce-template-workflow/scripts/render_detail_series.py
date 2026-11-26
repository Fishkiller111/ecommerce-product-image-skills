#!/usr/bin/env python3
"""Render an ordered set of mobile product-detail panels from real assets and copy."""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from render_detail import PALETTES, SWAP, cutout, detail_review, digest, fitted, load_font, valid_text
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
from detail_product_guard import check_product_layers
from detail_scene_layout import draw_scene_copy, read_scene_layout, relight_product

PANEL_TITLES = {
    'hero': '商品展示',
    'reasons': '选择它的理由',
    'ingredients': '成分展示',
    'usage': '使用方法',
    'specs': '产品参数',
    'gallery': '产品实拍',
    'documents': '资质展示',
}
MAX_ITEMS = {'hero': 2, 'reasons': 4, 'ingredients': 6, 'usage': 4, 'specs': 7, 'gallery': 3, 'documents': 4}
DEFAULT_HEIGHT = {'hero': 1.68, 'ingredients': 1.68, 'usage': 1.48, 'documents': 1.64}
SECTION_LAYOUTS = {'ingredients': 'grid', 'gallery': 'alternating', 'specs': 'table'}
SCENIC_KINDS = ('hero', 'reasons', 'usage')
SONGTI = Path('/System/Library/Fonts/Supplemental/Songti.ttc')


def fields(data, allowed, name):
    if not isinstance(data, dict) or data.keys() - set(allowed.split()):
        raise ValueError(f'{name} 字段无效，可用字段为 {allowed}')


def asset_path(value, base, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} 需要实物素材的图片路径')
    path = (base / Path(value).expanduser()).resolve(strict=True)
    if not path.is_file():
        raise ValueError(f'{name} 须指向实际文件')
    return path


def placement_layers(raw, base, background, min_height=.15):
    if not isinstance(raw,list) or not 1 <= len(raw) <= 3:
        raise ValueError('product_layers 需要 1–3 件独立的透明实拍商品')
    layers = []
    for item in raw:
        fields(item,'image anchor height angle','商品摆位')
        path = asset_path(item.get('image'),base,'商品图层')
        x_y, height, angle = item.get('anchor'), item.get('height'), item.get('angle',0)
        if not isinstance(x_y,list) or len(x_y) != 2:
            raise ValueError('anchor 须是画布上的 [横向中心, 底端接触点]')
        values = (*x_y,height,angle)
        bounds = ((0,1),(.45,.97),(min_height,.72),(-20,20))
        if not all(type(value) in (int,float) and low <= value <= high
                   for value,(low,high) in zip(values,bounds)):
            raise ValueError('商品摆位超出画布、相对高度或旋转范围')
        if path == background:
            raise ValueError('背景与前景商品必须为独立的图片')
        layers.append({'image':path,'sha256':digest(path),'anchor':x_y,'height':height,'angle':angle})
    return layers


def read_manifest(path):
    spec = json.loads(path.read_text(encoding='utf-8-sig'))
    fields(spec, 'product palette width pages', '详情方案')
    palette = spec.get('palette', 'heritage')
    width = spec.get('width', 790)
    if not isinstance(palette, str) or palette not in (*PALETTES, 'heritage'):
        raise ValueError('palette 须使用 heritage 或现有详情图色系')
    if type(width) is not int or not 600 <= width <= 1600:
        raise ValueError('width 须为 600–1600 像素')
    product = asset_path(spec['product'], path.parent, 'product') if 'product' in spec else None
    raw = spec.get('pages')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError('pages 须包含 1–12 张图')
    pages = []
    for page in raw:
        fields(page, 'kind title subtitle background items product_layers scene_layout layout featured', '页面')
        kind = page.get('kind')
        if not isinstance(kind, str) or kind not in PANEL_TITLES:
            raise ValueError('页面 kind 无效')
        section_layout = page.get('layout')
        if 'layout' in page and (kind not in SECTION_LAYOUTS or section_layout != SECTION_LAYOUTS[kind]):
            raise ValueError('layout 仅支持 ingredients 的 grid、gallery 的 alternating 或 specs 的 table')
        featured = page.get('featured', False)
        if 'featured' in page and (section_layout != 'grid' or type(featured) is not bool):
            raise ValueError('featured 仅用于 ingredients 的 grid，须为布尔值')
        uses_scene_layout = 'scene_layout' in page or (kind == 'reasons' and 'background' in page)
        items = page.get('items', [])
        max_items = MAX_ITEMS[kind] + featured
        if uses_scene_layout and kind == 'hero':
            max_items = 4
        if not isinstance(items, list) or len(items) > max_items:
            raise ValueError(f'{kind} 每屏最多 {max_items} 项，内容超出时拆屏')
        if not items and kind != 'hero':
            raise ValueError(f'{kind} 需要实际展示内容')
        bg = asset_path(page['background'], path.parent, 'background') if 'background' in page else None
        if bg and bg == product:
            raise ValueError('背景须使用独立的空场景')
        if bg and kind in ('specs', 'gallery'):
            raise ValueError(f'{kind} 使用清晰浅底，请省略 background')
        if uses_scene_layout and (not bg or kind not in SCENIC_KINDS):
            raise ValueError('scene_layout 用于有独立背景的 hero、reasons 或 usage')
        layers = []
        if 'product_layers' in page:
            if not bg or not (kind == 'hero' or uses_scene_layout):
                raise ValueError('product_layers 用于场景首屏、选择理由或场景说明屏')
            layers = placement_layers(page['product_layers'], path.parent, bg, .08 if uses_scene_layout else .15)
        needs_product = (kind == 'hero' or (kind == 'ingredients' and not section_layout)
                         or (kind == 'reasons' and uses_scene_layout))
        if needs_product and not (product or layers):
            raise ValueError(f'{kind} 需要真实商品原图或透明商品')
        normalized = []
        for item in items:
            fields(item, 'label text image source', f'{kind} 项目')
            label = valid_text(item.get('label', ''), 'label', kind in ('reasons', 'usage', 'gallery'))
            body = valid_text(item.get('text', ''), 'text', kind != 'specs')
            image = asset_path(item['image'], path.parent, 'image') if 'image' in item else None
            origin = valid_text(item.get('source', ''), 'source', True)
            if kind in ('gallery', 'documents') and not image:
                raise ValueError(f'{kind} 每项都须提供实际图片')
            if section_layout == 'alternating' and not (label or body):
                raise ValueError('alternating 的每张实拍需要对应的 label 或 text')
            if kind in ('hero', 'reasons', 'specs') and image:
                raise ValueError(f'{kind} 的条目使用文字，商品从 product 输入')
            if kind == 'reasons' and not (label or body):
                raise ValueError('reasons 每条需要实际理由')
            if kind == 'usage' and not (label or body or image):
                raise ValueError('usage 至少有说明或实际使用照片')
            if kind == 'usage' and sum(bool(x['image']) for x in normalized) + bool(image) > 1:
                raise ValueError('usage 每屏使用一张实拍，多张实拍请拆屏')
            normalized.append({'label': label, 'text': body, 'image': image, 'source': origin})
        if featured and not normalized[0]['image']:
            raise ValueError('featured 的第一项需要可核对的对应材料图')
        if bg and kind == 'usage' and (not (product or layers) or any(item['image'] for item in normalized)):
            raise ValueError('usage 的独立背景仅用于无使用实拍的商品场景')
        subtitle = valid_text(page.get('subtitle', ''), 'subtitle', True)
        if uses_scene_layout:
            layout = read_scene_layout(page.get('scene_layout', {}), kind, normalized, subtitle)
        pages.append({
            'kind': kind, 'title': valid_text(page.get('title', PANEL_TITLES[kind]), 'title'),
            'subtitle': subtitle,
            'background': bg, 'items': normalized, 'product_layers': layers,
            **({'layout': section_layout} if section_layout else {}),
            **({'featured': True} if featured else {}),
            **({'scene_layout': layout} if uses_scene_layout else {}),
        })
    return width, palette, product, pages


def title_font(role, size):
    if SONGTI.is_file() and not os.environ.get('PSB_FONT_PATH'):
        return ImageFont.truetype(str(SONGTI), size, index=0)
    return load_font(role, size)


def open_asset(path):
    with Image.open(path) as image:
        asset = ImageOps.exif_transpose(image).convert('RGBA')
    if asset.getchannel('A').getextrema()[0] < 255:
        bbox = asset.getchannel('A').getbbox()
        if not bbox:
            raise ValueError(f'素材完全透明：{path.name}')
        asset = asset.crop(bbox)
    return asset


def gradient(size, top, bottom):
    column = Image.new('RGB', (1, size[1]))
    column.putdata([
        tuple(round(a+(b-a)*y/max(1, size[1]-1)) for a, b in zip(top, bottom))
        for y in range(size[1])
    ])
    return column.resize(size).convert('RGBA')


class Panel:
    def __init__(self, size, palette, framed=True):
        self.w, self.h = size
        self.palette = palette
        if palette == 'heritage':
            self.paper, self.shade, self.ink = (252, 246, 235), (237, 220, 195), (35, 74, 64)
        else:
            self.paper, self.shade, self.ink, _ = PALETTES[palette]
        self.gold = (175, 123, 67)
        self.light_gold = (229, 197, 150)
        self.canvas = gradient(size, self.paper, self.shade)
        self.draw = ImageDraw.Draw(self.canvas)
        self.placements = []
        self.layers = []
        if framed:
            self.frame((.025, .016, .975, .984), None, double=True)

    def rect(self, box):
        return tuple(round(n*f) for n, f in zip((self.w, self.h, self.w, self.h), box))

    def frame(self, box, fill, double=False):
        x, y, r, b = self.rect(box)
        border = max(1, round(self.w*.002))
        self.draw.rounded_rectangle((x,y,r,b), radius=round(self.w*.025),
                                    fill=fill, outline=self.gold, width=border)
        if double:
            inset = border*3
            self.draw.rounded_rectangle((x+inset,y+inset,r-inset,b-inset), radius=round(self.w*.019),
                                        outline=self.light_gold, width=border)

    def text(self, value, box, size, minimum=.022, lines=2, color=None, center=True, title=False):
        if value:
            fitted(self.draw, value, self.rect(box), round(self.w*size), round(self.w*minimum),
                   lines, color or self.ink, center=center, role='template' if title else 'hero',
                   font_loader=title_font if title else load_font)

    def title(self, page):
        subtitle = page['subtitle']
        self.text(page['title'], (.075,.047,.925,.188 if subtitle else .198), .086, .038, title=True)
        self.text(subtitle, (.09,.184,.91,.245), .032)
        y = .259 if subtitle else .212
        self.draw.line(self.rect((.405,y,.595,y)), fill=self.gold, width=max(1, round(self.w*.003)))
        self.draw.polygon([self.rect((x,y1,x,y1))[:2] for x,y1 in
                           ((.5,y-.005),(.509,y),(.5,y+.005),(.491,y))], fill=self.gold)
        return .293 if subtitle else .243

    def scene(self, box, background):
        x, y, r, b = self.rect(box)
        size = (r-x,b-y)
        if background:
            scene = ImageOps.fit(open_asset(background),size,method=Image.Resampling.LANCZOS)
        else:
            scene = gradient(size, self.ink, (29, 32, 30))
            w,h = size
            light = Image.new('RGBA', size)
            draw = ImageDraw.Draw(light)
            draw.ellipse((w*.04,-h*.25,w*1.22,h*.82),fill=(220,174,107,165))
            draw.ellipse((w*.24,-h*.21,w*.99,h*.62),fill=(241,218,165,183))
            scene.alpha_composite(light.filter(ImageFilter.GaussianBlur(max(12,round(w*.15)))))
            floor = gradient((w,round(h*.24)), (143,102,70),(54,46,36))
            scene.alpha_composite(floor,(0,h-floor.height))
        self.canvas.alpha_composite(scene,(x,y))
        self.draw.rectangle((x,y,r-1,b-1),outline=self.gold,width=max(1,round(self.w*.003)))

    def place(self, image, box, role, shadow=False):
        x,y,r,b = self.rect(box)
        asset = ImageOps.contain(image,(r-x,b-y),method=Image.Resampling.LANCZOS)
        tw,th = asset.size
        left,top = x+(r-x-tw)//2,y+(b-y-th)//2
        if shadow:
            layer = Image.new('RGBA',self.canvas.size)
            ImageDraw.Draw(layer).ellipse((left+tw*.07,top+th-1,left+tw*.93,top+th+self.w*.026),
                                          fill=(31,24,18,112))
            self.canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(3,round(self.w*.012)))))
        self.add_asset(asset,(left,top),role,image.size,(tw,th))

    def add_asset(self, asset, origin, role, original_size, scaled_size, ungraded=None):
        x,y = origin
        box = (x,y,x+asset.width,y+asset.height)
        if role == 'product':
            reference = Image.alpha_composite(self.canvas.crop(box),asset)
            self.layers.append((origin,asset,reference,ungraded))
        self.canvas.alpha_composite(asset,origin)
        self.placements.append({'role':role,'rect':list(box),
                                'detail':detail_review(original_size,scaled_size,False)})

    def scenic_hero(self, page, product):
        layout = page.get('scene_layout')
        self.canvas = ImageOps.fit(open_asset(page['background']),self.canvas.size,
                                   method=Image.Resampling.LANCZOS,centering=(.5 if layout else .34,.5))
        self.draw = ImageDraw.Draw(self.canvas)
        instructions = page['product_layers']
        assets = [open_asset(line['image']) for line in instructions] if instructions else [product]
        if not instructions:
            if layout:
                position = layout['copy_position']
                x, width, max_height = {'above': (.5,.86,.25), 'left': (.72,.42,.47),
                                        'right': (.28,.42,.47)}[position]
                if page['kind'] == 'reasons' and position != 'above':
                    x, width = (.75 if position == 'left' else .25), .40
                height = min(max_height, width*self.w*product.height/(self.h*product.width))
                ground = .86 if page['kind'] == 'reasons' else .79
                instructions = [{'anchor':[x,ground],'height':height,'angle':0}]
            else:
                instructions = [{'anchor':[.55,.855],'height':.55,'angle':0}]
        prepared = []
        for asset, line in zip(assets,instructions):
            if asset.getchannel('A').getextrema()[0] == 255:
                raise ValueError('场景商品图层须为已经验边的真实透明图')
            height = max(1, round(line['height']*self.h))
            scaled_size = (max(1,round(asset.width*height/asset.height)),height)
            layer = asset.resize(scaled_size,Image.Resampling.LANCZOS)
            if line['angle']:
                layer = layer.rotate(line['angle'],resample=Image.Resampling.BICUBIC,expand=True)
                layer = layer.crop(layer.getchannel('A').getbbox())
            cx,ground = (round(f*n) for f,n in zip(line['anchor'],(self.w,self.h)))
            x,y = cx-layer.width//2,ground-layer.height
            if not (4 <= x and x+layer.width+4 <= self.w and self.h*.225 <= y and ground <= self.h-4):
                raise ValueError('商品碰到画布边缘或标题区，请调整摆位')
            padded = ImageOps.expand(layer,border=4,fill=(0,0,0,0))
            prepared.append((padded,(x-4,y-4),asset.size,scaled_size))
        cast = Image.new('RGBA',self.canvas.size)
        contact = Image.new('RGBA',self.canvas.size)
        cast_draw = ImageDraw.Draw(cast)
        contact_draw = ImageDraw.Draw(contact)
        if layout:
            falloff = layout['light']['falloff']
            spread = (.10,.34) if falloff > 0 else (.34,.10) if falloff < 0 else (.22,.22)
            contact_spread, contact_opacity = (.032, .032), 136
        else:
            spread, contact_spread, contact_opacity = (.8, .24), (.08, .07), 168
        for asset,(x,y),_,_ in prepared:
            alpha = asset.getchannel('A')
            threshold = min(128,alpha.getextrema()[1])
            solid = alpha.point(lambda a: 255 if a >= threshold else 0)
            bottom = solid.getbbox()[3]
            band_top = max(0,bottom-max(4,round(asset.height*.021)))
            left,_,right,_ = solid.crop((0,band_top,solid.width,bottom)).getbbox()
            left,right,foot = x+left,x+right,y+bottom
            span = right-left
            cast_draw.ellipse((left-span*spread[0],foot-self.h*.008,
                               right+span*spread[1],foot+self.h*.017), fill=(49,35,23,92))
            contact_draw.ellipse((left-span*contact_spread[0],foot-self.h*.003,
                                  right+span*contact_spread[1],foot+self.h*.005),
                                 fill=(52,38,24,contact_opacity))
        self.canvas.alpha_composite(cast.filter(ImageFilter.GaussianBlur(max(3,round(self.w*.013)))))
        self.canvas.alpha_composite(contact.filter(ImageFilter.GaussianBlur(max(1,round(self.w*.002)))))
        for asset,xy,source_size,scaled_size in prepared:
            ungraded = asset if layout and any(layout['light'].values()) else None
            if ungraded is not None:
                asset = relight_product(ungraded, xy, self.w, layout['light'])
            self.add_asset(asset,xy,'product',source_size,scaled_size,ungraded)
        if layout:
            for left,top,right,bottom in draw_scene_copy(self, page):
                for (x,y),asset,*_ in self.layers:
                    if right > x and bottom > y and left < x+asset.width and top < y+asset.height:
                        raise ValueError('场景文案区碰到商品，请调整 copy_position 或 product_layers')
            return
        self.text(page['title'],(.21,.072,.96,.171),.116,.039,1,color=(57,47,30),title=True)
        self.text(page['subtitle'],(.25,.176,.92,.218),.032,color=(68,63,41))
        for i,item in enumerate(page['items']):
            width = .70/len(page['items'])
            x = .15+i*width
            self.card(item,(x+.008,.907,x+width-.008,.973),'point')

    def card(self, item, box, role, asset=None):
        x,y,r,b = box
        self.frame(box, (255,255,255) if role in ('gallery-photo','document') else (255,253,248))
        image = item['image']
        label, body = item['label'], item['text']
        note_height = (b-y)*(.30 if role == 'ingredient' else .24) if (label or body) else 0
        if image:
            asset = open_asset(image) if asset is None else asset
            photo_box = (x+.015,y+.012,r-.015,b-.012-note_height)
            if role == 'ingredient' and asset.getchannel('A').getextrema()[0] < 255:
                l,t,right,bottom = self.rect(photo_box)
                diameter = round(min(right-l,bottom-t)*.89)
                left,top = (l+right-diameter)//2,(t+bottom-diameter)//2
                self.draw.ellipse((left,top,left+diameter,top+diameter),
                                  fill=(249,237,206),outline=self.light_gold,width=max(1,self.w//400))
            self.place(asset,photo_box,role)
        text_top = b-note_height if image else y+.01
        split = (text_top+b)*.5 if label and body else b-.009
        if label:
            self.text(label,(x+.021,text_top,r-.021,split),.033,.019,2)
        if body:
            self.text(body,(x+.021,split if label else text_top,r-.021,b-.009),.027,.019,2)

    def section_title(self, page):
        unit = self.w/self.h
        self.text(page['title'], (.087,.040*unit,.913,.130*unit), .068, .040,
                  center=False, title=True)
        self.text(page['subtitle'], (.087,.137*unit,.913,.195*unit), .033, .025, center=False)
        return section_heading_height(page)*unit

    def section_rule(self, y):
        self.draw.line(self.rect((.087,y,.913,y)), fill=self.shade, width=max(1,self.w//600))

    def ingredients_grid(self, groups, top, row_heights, featured):
        y = top
        columns = max(len(group) for group in groups)
        unit = self.w/self.h
        for row, (group, height) in enumerate(zip(groups, row_heights)):
            row_height = height*unit
            primary = featured and row == 0
            cell_width = .52 if primary else .826/columns
            image_share = min(.37 if primary else .235, cell_width-.04)
            for column, item in enumerate(group):
                left = .5 - len(group)*cell_width/2 + column*cell_width
                right = left+cell_width
                label, body, path = item['label'], item['text'], item['image']
                if path:
                    image = open_asset(path)
                    diameter = round(self.w*image_share)
                    tile = ImageOps.fit(image, (diameter, diameter), method=Image.Resampling.LANCZOS)
                    mask = Image.new('L', (2*diameter, 2*diameter))
                    ImageDraw.Draw(mask).ellipse((0,0,mask.width-1,mask.height-1), fill=255)
                    tile.putalpha(ImageChops.multiply(tile.getchannel('A'), mask.resize(tile.size, Image.Resampling.LANCZOS)))
                    cx = round((left+right)*self.w/2)
                    py = round(y*self.h+.018*self.w)
                    self.draw.ellipse((cx-diameter//2-2,py-2,cx-diameter//2+diameter+1,py+diameter+1),
                                      fill=self.paper)
                    self.add_asset(tile, (cx-diameter//2,py), 'ingredient', image.size, tile.size)
                label_top = y+(.036+image_share)*unit if path else y+.19*row_height
                label_bottom = label_top+(.069 if primary else .062)*unit
                inset = .07 if primary else .016
                bounds = (left+inset, label_top, right-inset, label_bottom)
                if path or not body:
                    x0,y0,x1,y1 = self.rect(bounds)
                    self.draw.rounded_rectangle((x0,y0,x1,y1), radius=(y1-y0)//2, fill=self.shade)
                self.text(label, bounds, .040 if primary else .036, .020, title=True)
                self.text(body, (left+.02,label_bottom,right-.02,y+.98*row_height), .026, .019, 2)
            y += row_height

    def alternating_photos(self, items, top, photos, row_heights):
        y = top
        for index, (item, asset, height) in enumerate(zip(items, photos, row_heights)):
            row_height = height*self.w/self.h
            bottom = y+row_height
            photo, copy = ((.087,.541), (.581,.913)) if index % 2 == 0 else ((.459,.913), (.087,.419))
            self.place(asset, (photo[0],y+.05*row_height,photo[1],bottom-.07*row_height),
                       'gallery-photo')
            label, body = item['label'], item['text']
            if label and body:
                self.text(label, (copy[0],y+.22*row_height,copy[1],y+.47*row_height),
                          .045, .029, center=False, title=True)
                self.text(body, (copy[0],y+.49*row_height,copy[1],bottom-.11*row_height),
                          .035, .025, 3, center=False)
            else:
                self.text(label or body, (copy[0],y+.11*row_height,copy[1],bottom-.11*row_height),
                          .040, .025, 3, center=False, title=bool(label))
            if index+1 < len(items):
                self.section_rule(bottom)
            y = bottom

    def specs_table(self, items, top):
        row_height = .13*self.w/self.h
        self.section_rule(top)
        for index, item in enumerate(items):
            y, bottom = top+index*row_height, top+(index+1)*row_height
            padding = .09*row_height
            self.text(item['label'], (.092,y+padding,.320,bottom-padding), .036, .027, 2, center=False)
            self.text(item['text'], (.347,y+padding,.908,bottom-padding), .038, .027, 3, center=False)
            self.section_rule(bottom)


def section_heading_height(page):
    return .22 if page['subtitle'] else .16


def render_section(width, palette, page):
    layout, items = page['layout'], page['items']
    if layout == 'grid':
        featured = page.get('featured', False)
        groups = [items[:1]] if featured else []
        groups += [items[start:start+3] for start in range(int(featured), len(items), 3)]
        row_heights = [.405 if any(item['image'] for item in group) else .18 for group in groups]
        if featured:
            row_heights[0] = .565
    elif layout == 'alternating':
        photos = [open_asset(item['image']) for item in items]
        row_heights = [max(.25, min(.47, .454*p.height/p.width + .075)) for p in photos]
    else:
        row_heights = [.13]*len(items)
    ratio = section_heading_height(page) + sum(row_heights) + .055
    panel = Panel((width, round(width*ratio)), palette, framed=False)
    if page['background']:
        backdrop = ImageOps.fit(open_asset(page['background']), panel.canvas.size, method=Image.Resampling.LANCZOS)
        panel.canvas = Image.blend(backdrop, panel.canvas, .79)
        panel.draw = ImageDraw.Draw(panel.canvas)
    top = panel.section_title(page)
    if layout == 'grid':
        panel.ingredients_grid(groups, top, row_heights, featured)
    elif layout == 'alternating':
        panel.alternating_photos(items, top, photos, row_heights)
    else:
        panel.specs_table(items, top)
    return panel.canvas.convert('RGB'), panel.placements, [], None


def render_panel(width, palette, page, product):
    if 'layout' in page:
        return render_section(width, palette, page)
    kind = page['kind']
    items = page['items']
    scenic = (kind == 'hero' and page['background'] is not None) or 'scene_layout' in page
    if 'scene_layout' in page:
        ratio = 1.25
    elif scenic:
        ratio = 1.35
    elif kind == 'reasons':
        ratio = .58+.20*len(items)
    elif kind == 'gallery':
        gallery = [open_asset(item['image']) for item in items]
        portrait = all(asset.height > 1.2*asset.width for asset in gallery)
        ratio = 1.45 if portrait else {1: 1.04, 2: 1.55, 3: 2.10}[len(items)]
    elif kind == 'specs':
        ratio = .37+.105*len(items)
    else:
        ratio = DEFAULT_HEIGHT[kind]
    panel = Panel((width,round(width*ratio)), palette, framed=kind != 'reasons')
    top = panel.title(page) if not scenic and kind != 'reasons' else None
    bg = page['background']

    if scenic:
        panel.scenic_hero(page,product)
    elif kind == 'reasons':
        draw_scene_copy(panel, page)
    elif kind == 'hero':
        floor = .845 if items else .938
        panel.scene((.060,top,.940,floor),bg)
        panel.place(product,(.095,top+.022,.905,floor-.025),'product',shadow=not bg)
        for i,item in enumerate(items):
            w = .84/len(items)
            x = .08+i*w
            panel.card(item,(x+.010,.866,x+w-.010,.951),'point')
    elif kind == 'ingredients':
        panel.scene((.057,top,.943,.950),bg)
        panel.place(product,(.321,top+.04,.679,.923),'product',shadow=not bg)
        rows = (len(items)+1)//2
        gap = .014
        row_h = min(.245,(.902-top-gap*(rows-1))/rows)
        for i,item in enumerate(items):
            x = .075 if i%2 == 0 else .694
            y = top+(.913-top-rows*row_h-(rows-1)*gap)/2+(i//2)*(row_h+gap)
            panel.card(item,(x,y,x+.231,y+row_h),'ingredient')
    elif kind == 'usage':
        visual = next((item['image'] for item in items if item['image']),None)
        copy = [item for item in items if item['label'] or item['text']]
        edge = (.68 if copy else .94) if visual or product else top
        if visual:
            panel.card({'image':visual,'label':'','text':''},(.07,top,.93,edge),'usage-photo')
        elif product:
            panel.scene((.07,top,.93,edge),bg)
            panel.place(product,(.12,top+.02,.88,edge-.02),'product',shadow=not bg)
        row_h = (.951-edge)/max(1,len(copy))
        for i,item in enumerate(copy):
            y = edge+i*row_h+.008
            panel.card(item | {'image':None},(.08,y,.92,y+row_h-.015),'instruction')
    elif kind == 'specs':
        panel.frame((.067,top,.933,.948),(255,250,240),double=True)
        row_h = (.917-top)/len(items)
        for i,item in enumerate(items):
            y = top+.015+i*row_h
            panel.text(item['label'],(.105,y,.310,y+row_h),.033,.020,2,center=False)
            panel.text(item['text'],(.340,y,.890,y+row_h),.035,.022,3,center=False)
            if i < len(items)-1:
                panel.draw.line(panel.rect((.103,y+row_h,.897,y+row_h)),
                                fill=panel.light_gold,width=max(1,width//640))
    elif kind == 'gallery':
        columns = len(items) if portrait else 1
        rows = (len(items)+columns-1)//columns
        dx,dy = .88/columns,(.950-top)/rows
        for i,(item,asset) in enumerate(zip(items,gallery)):
            row,col = divmod(i,columns)
            x,y = .06+col*dx,top+row*dy
            panel.card(item,(x+.006,y,x+dx-.006,y+dy-.014),'gallery-photo',asset)
    else:
        panel.scene((.055,top-.012,.945,.960),bg)
        cols = 1 if len(items)==1 else 2
        rows = (len(items)+cols-1)//cols
        dx,dy = .86/cols,(.946-top)/rows
        for i,item in enumerate(items):
            row,col = divmod(i,cols)
            x,y = .07+col*dx,top+row*dy
            panel.card(item,(x+.008,y,x+dx-.008,y+dy-.015),'document')
    image = panel.canvas.convert('RGB')
    checks, guide = check_product_layers(image,panel.layers) if panel.layers else ([],None)
    return image, panel.placements, checks, guide


def save_series(root, manifest, long_image):
    width,palette,source,pages = read_manifest(manifest)
    root.mkdir(parents=True,exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='DETAIL-',dir=root)).resolve()
    try:
        product = None
        product_info = None
        if source:
            with tempfile.TemporaryDirectory(prefix='detail-mask-') as temp:
                cutout_path = Path(temp)/'cutout.png'
                backend = cutout(source,cutout_path,SWAP/'scripts'/'macos_subject_mask.m',None)
                product = open_asset(cutout_path)
            product.save(output/'商品透明素材.png')
            product_info = {'file':str(source),'sha256':digest(source),'mask':backend,
                            'cutout':str(output/'商品透明素材.png')}
        records = []
        for i,page in enumerate(pages,1):
            image,placements,checks,guide = render_panel(width,palette,page,product)
            path = output/f'{i:02d}_{page["kind"]}.png'
            image.save(path)
            record = page | {'preview':str(path),'size':list(image.size),'placements':placements}
            if checks:
                guide_path = output/f'Canny_{i:02d}.png'
                guide.save(guide_path)
                record.update(product_integrity=checks,canny_guide=str(guide_path))
            records.append(record)
        report = {'product':product_info,'pages':records,'palette':palette,
                  'publication':'待核对实物包装、成分、用法、参数及资料后再发布'}
        if long_image:
            height = sum(p['size'][1] for p in records)
            if width*height > 65_000_000:
                raise ValueError('拼接后的画布过大，请降低宽度或分批拼接')
            full = Image.new('RGB',(width,height))
            y = 0
            for record in records:
                with Image.open(record['preview']) as screen:
                    full.paste(screen,(0,y))
                    y += screen.height
            full.save(output/'详情长图.png')
            report['long_image'] = str(output/'详情长图.png')
        report_path = output/'详情复核.json'
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
        return {'pages':[p['preview'] for p in records],'report':str(report_path),
                'long_image':report.get('long_image')}
    except BaseException:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path,help='由 Agent 编写的详情方案 JSON')
    parser.add_argument('--out',type=Path,default=Path('outputs/product-detail'))
    parser.add_argument('--long',action='store_true',help='同时按页面顺序拼接长图')
    args = parser.parse_args()
    try:
        result = save_series(args.out,args.manifest.resolve(strict=True),args.long)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2,f'详情图处理停止：{exc}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
