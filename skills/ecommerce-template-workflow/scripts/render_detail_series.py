#!/usr/bin/env python3
"""Render an ordered set of mobile product-detail panels from real assets and copy."""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from render_detail import PALETTES, SWAP, cutout, detail_review, digest, fitted, load_font, valid_text
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from detail_product_guard import check_product_layers

PANEL_TITLES = {
    'hero': '商品展示',
    'ingredients': '成分展示',
    'usage': '使用方法',
    'specs': '产品参数',
    'gallery': '产品实拍',
    'documents': '资质展示',
}
MAX_ITEMS = {'hero': 2, 'ingredients': 6, 'usage': 4, 'specs': 7, 'gallery': 3, 'documents': 4}
DEFAULT_HEIGHT = {'hero': 1.68, 'ingredients': 1.68, 'usage': 1.48, 'documents': 1.64}
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


def placement_layers(raw, base, background):
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
        bounds = ((0,1),(.45,.97),(.15,.72),(-20,20))
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
        fields(page, 'kind title subtitle background items product_layers', '页面')
        kind = page.get('kind')
        if not isinstance(kind, str) or kind not in PANEL_TITLES:
            raise ValueError('页面 kind 无效')
        items = page.get('items', [])
        if not isinstance(items, list) or len(items) > MAX_ITEMS[kind]:
            raise ValueError(f'{kind} 每屏最多 {MAX_ITEMS[kind]} 项，内容超出时拆屏')
        if not items and kind != 'hero':
            raise ValueError(f'{kind} 需要实际展示内容')
        bg = asset_path(page['background'], path.parent, 'background') if 'background' in page else None
        if bg and bg == product:
            raise ValueError('背景须使用独立的空场景')
        if bg and kind in ('specs', 'gallery'):
            raise ValueError(f'{kind} 使用清晰浅底，请省略 background')
        layers = []
        if 'product_layers' in page:
            if kind != 'hero' or not bg:
                raise ValueError('product_layers 用于有独立场景背景的首屏')
            layers = placement_layers(page['product_layers'],path.parent,bg)
        if kind in ('hero', 'ingredients') and not (product or layers):
            raise ValueError(f'{kind} 需要真实商品原图或透明商品')
        normalized = []
        for item in items:
            fields(item, 'label text image source', f'{kind} 项目')
            label = valid_text(item.get('label', ''), 'label', kind in ('usage', 'gallery'))
            body = valid_text(item.get('text', ''), 'text', kind != 'specs')
            image = asset_path(item['image'], path.parent, 'image') if 'image' in item else None
            origin = valid_text(item.get('source', ''), 'source', True)
            if kind in ('gallery', 'documents') and not image:
                raise ValueError(f'{kind} 每项都须提供实际图片')
            if kind in ('hero', 'specs') and image:
                raise ValueError(f'{kind} 的条目使用文字，商品从 product 输入')
            if kind == 'usage' and not (label or body or image):
                raise ValueError('usage 至少有说明或实际使用照片')
            if kind == 'usage' and sum(bool(x['image']) for x in normalized) + bool(image) > 1:
                raise ValueError('usage 每屏使用一张实拍，多张实拍请拆屏')
            normalized.append({'label': label, 'text': body, 'image': image, 'source': origin})
        if bg and kind == 'usage' and (not product or any(item['image'] for item in normalized)):
            raise ValueError('usage 的独立背景仅用于无使用实拍的商品场景')
        pages.append({
            'kind': kind, 'title': valid_text(page.get('title', PANEL_TITLES[kind]), 'title'),
            'subtitle': valid_text(page.get('subtitle', ''), 'subtitle', True),
            'background': bg, 'items': normalized, 'product_layers': layers,
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
    def __init__(self, size, palette):
        self.w, self.h = size
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

    def add_asset(self, asset, origin, role, original_size, scaled_size):
        x,y = origin
        box = (x,y,x+asset.width,y+asset.height)
        if role == 'product':
            reference = Image.alpha_composite(self.canvas.crop(box),asset)
            self.layers.append((origin,asset,reference))
        self.canvas.alpha_composite(asset,origin)
        self.placements.append({'role':role,'rect':list(box),
                                'detail':detail_review(original_size,scaled_size,False)})

    def scenic_hero(self, page, product):
        self.canvas = ImageOps.fit(open_asset(page['background']),self.canvas.size,
                                   method=Image.Resampling.LANCZOS,centering=(.34,.5))
        self.draw = ImageDraw.Draw(self.canvas)
        instructions = page['product_layers']
        assets = [open_asset(line['image']) for line in instructions] if instructions else [product]
        instructions = instructions or [{'anchor':[.55,.855],'height':.55,'angle':0}]
        prepared = []
        for asset, line in zip(assets,instructions):
            if asset.getchannel('A').getextrema()[0] == 255:
                raise ValueError('场景商品图层须为已经验边的真实透明图')
            height = round(line['height']*self.h)
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
        for asset,(x,y),_,_ in prepared:
            alpha = asset.getchannel('A')
            threshold = min(128,alpha.getextrema()[1])
            solid = alpha.point(lambda a: 255 if a >= threshold else 0)
            bottom = solid.getbbox()[3]
            band_top = max(0,bottom-max(4,round(asset.height*.021)))
            left,_,right,_ = solid.crop((0,band_top,solid.width,bottom)).getbbox()
            left,right,foot = x+left,x+right,y+bottom
            span = right-left
            cast_draw.ellipse((left-span*.8,foot-self.h*.008,right+span*.24,foot+self.h*.017),
                              fill=(49,35,23,92))
            contact_draw.ellipse((left-span*.08,foot-self.h*.003,right+span*.07,foot+self.h*.005),
                                 fill=(52,38,24,168))
        self.canvas.alpha_composite(cast.filter(ImageFilter.GaussianBlur(max(3,round(self.w*.013)))))
        self.canvas.alpha_composite(contact.filter(ImageFilter.GaussianBlur(max(1,round(self.w*.002)))))
        for asset,xy,source_size,scaled_size in prepared:
            self.add_asset(asset,xy,'product',source_size,scaled_size)
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


def render_panel(width, palette, page, product):
    kind = page['kind']
    items = page['items']
    scenic = kind == 'hero' and page['background'] is not None
    if scenic:
        ratio = 1.35
    elif kind == 'gallery':
        gallery = [open_asset(item['image']) for item in items]
        portrait = all(asset.height > 1.2*asset.width for asset in gallery)
        ratio = 1.45 if portrait else {1: 1.04, 2: 1.55, 3: 2.10}[len(items)]
    elif kind == 'specs':
        ratio = .37+.105*len(items)
    else:
        ratio = DEFAULT_HEIGHT[kind]
    panel = Panel((width,round(width*ratio)), palette)
    top = panel.title(page) if not scenic else None
    bg = page['background']

    if scenic:
        panel.scenic_hero(page,product)
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
