---
name: ai-ecommerce-product-images
description: 用真实商品原图制作白底抠图和电商商品主图。严格锁定原商品身份、包装文字、颜色、结构和比例；通过 APIMart 的 gpt-image-2.6-flare-ext 完成图像编辑与生成。用户提供商品照片、抠图、白底图、电商图或商品主图时使用。
---

# 电商商品图制作

## 目标

把一张真实商品照片快速处理成两张可交付图片：

1. **白底保真图**：去除原背景，商品置于纯白背景，保留原商品的全部外观与包装信息。
2. **真实电商主图**：以白底保真图为唯一商品事实来源，生成干净、可信、可用于电商展示的场景图。

默认只做必要的光线、构图和背景处理，不把商品“重新设计”。

## 输入

- `SOURCE_IMAGE`：客户提供的真实商品原图，必需。
- `STYLE_REFERENCE`：可选的电商构图参考图。只参考布局、光线、留白和信息层级，不复制其商品、文字、价格、认证或宣传语。
- `OUTPUT_DIR`：输出目录；默认 `./outputs/product-images/`。

收到多张图时，先判断哪张是商品事实图，哪张只是风格参考图。不要把风格参考图里的商品细节覆盖到原商品上。

## 固定流程

### 1. 读取 APIMart 规则

使用当前环境可用的 APIMart 工具，或按 APIMart 官方接口文档的上传、鉴权及异步轮询方式调用。API Key 从 `APIMART_API_KEY` 等用户配置的环境变量或安全凭据管理器读取；服务地址使用 `APIMART_BASE_URL` 或服务商官方配置。不得将密钥、用户文件或临时 URL 写入技能文件、脚本、日志或交付文案。未配置凭据或服务地址时说明需要配置，不冒用或搜索其他用户的密钥。API 可能计费；用户指定或已同意使用 APIMart 处理原图时，按本次任务执行并提示费用，若没有该授权、用户拒绝上传或服务未配置则先说明。

主模型固定为 `gpt-image-2.6-flare-ext`。如果接口明确返回“模型不存在”，再使用 APIMart 中可用的 GPT Image 扩展模型，并在结果中说明发生了回退；不要静默更换模型。

### 2. 上传原图

使用 APIMart 图片上传接口上传 `SOURCE_IMAGE`，得到 `source_url`。如有 `STYLE_REFERENCE`，单独上传得到 `style_url`。上传完成后立即保存任务记录，不把临时 URL 写入客户交付文案。

### 3. 生成白底保真图

调用 APIMart 图片生成/编辑接口，使用 `source_url` 作为唯一商品参考。提示词直接使用下面模板，替换方括号内容：

```text
Edit the provided product photo into a clean e-commerce white-background product cutout.
The product identity is locked to the source image.
Preserve exactly: package shape, front and side panels, dimensions, proportions, colors,
logos, labels, Chinese text, English text, dosage/volume markings, seals, caps, edges,
folds and all visible printed details.
Remove only the original environment and background. Use a pure white background,
soft natural contact shadow, centered product, full product visible, realistic camera
perspective, accurate geometry, high-detail commercial photography.
Do not redesign, beautify into another product, rewrite text, translate text, add text,
remove text, change the package, change the brand, change the logo, change the color,
add props, add people, add medical claims, add badges, add price tags or add decorative
copy. If any printed text is uncertain, preserve the original appearance rather than
inventing a replacement.
```

输出命名：`01_white_bg_preserved.png`。

### 4. 保真检查

在进入电商图前，必须检查白底图：

- 包装正面、侧面、顶部和边角是否与原图一致。
- 商品数量、尺寸比例、颜色、透视和结构是否改变。
- 品牌、商标、批准文号、规格、中文和英文是否被重写或乱码。
- 是否出现额外瓶子、盒子、植物、药片、人物、价格、认证、功效词或装饰。
- 背景是否为白色，商品是否完整，是否存在明显抠图毛边或穿透。

任一项失败：不要交付为成品。用同一原图强化“identity locked / preserve exact packaging / no new text”，最多再尝试一次；仍不通过时明确标记 `REJECTED`，不要假装完成或无限重试。

### 5. 生成真实电商主图

将 `01_white_bg_preserved.png` 作为商品事实图；`STYLE_REFERENCE` 仅作构图参考。提示词使用：

```text
Create one realistic e-commerce product hero image using the provided preserved product cutout.
The supplied cutout is the exact product truth and must remain unchanged.
Keep the same package shape, logo, brand, printed text, colors, proportions, side panel,
volume markings and all visible details. Do not redraw or reinterpret the product.
Build a clean, credible commercial composition with [SCENE], [LIGHTING], [CAMERA_ANGLE]
and generous negative space. Use premium but restrained styling, realistic shadows and
accurate materials. No people, no hands, no extra products, no medical advice, no efficacy
claims, no price, no platform badge, no invented slogan, no invented certification, no
new package text and no visual element that could be mistaken as part of the product.
The final image must look like a real product photograph, not an illustration or a fantasy ad.
```

默认参数：

- `SCENE`：简洁、真实、与商品品类相关的电商场景。
- `LIGHTING`：柔和自然光，避免过度磨皮、过曝和塑料感。
- `CAMERA_ANGLE`：略微三分之四角度，确保正面与必要侧面可读。
- 画幅优先 `1:1`；详情页横图可用 `4:5` 或 `3:4`。
- 默认 `resolution: 2k`；只在客户明确要求时使用更高分辨率。

输出命名：`02_ecommerce_hero.png`。

### 6. 电商图检查

确认：商品仍然是原商品；包装文字未改；场景不制造功效暗示；没有价格、平台角标、虚构认证或夸大宣传；构图适合电商缩略图和详情页；没有明显 AI 生成痕迹。

## 输出契约

只交付：

```text
OUTPUT_DIR/
├── 01_white_bg_preserved.png
└── 02_ecommerce_hero.png
```

如果任一阶段失败，输出失败原因、失败图片路径和下一步修正，不交付不合格图。

结果说明只保留三行：

```text
原图：<文件名>
结果：白底保真图 <路径>；电商主图 <路径>
检查：商品身份/包装文字/结构比例已核对；<通过或需重做原因>
```

## 禁止事项

- 不把原商品美化成另一个商品。
- 不擅自修改或补写包装文字、品牌、商标、批准文号、规格和价格。
- 不把风格参考图当作商品事实图。
- 不为药品、保健品或医疗相关商品添加疗效、治愈、绝对化或未经提供的宣传词。
- 不泄露 APIMart API Key，不把密钥写入 Skill、日志、图片元数据或客户文档。
- 不绕过保真检查；白底图未通过时，不继续生成电商图。
