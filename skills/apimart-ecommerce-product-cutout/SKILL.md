---
name: apimart-ecommerce-product-cutout
description: 用户明确选择 APIMart 时，对真实商品照片进行生成式白底和透明抠图，并严格对照原图检查包装字体、文字和商品外观。
---

# APIMart 商品生成式抠图

处理用户提供的真实商品原图，目标是配套透明 PNG 与纯白底图。用户选择本技能即表示同意为本次任务上传所提供的图片并使用可能计费的 APIMart；无图时不主动调用或计费。无需额外生成场景图。

## 鉴权与调用

使用 `APIMART_API_KEY` 环境变量或安全凭据管理器中的密钥。用户本次明确提供的密钥仅用于本次请求；不得写入技能、仓库、脚本、日志、交付文档或命令历史。不要搜索或冒用其他密钥；未配置时说明如何安全配置。服务和模型参数以 [APIMart 官方文档](https://docs.apimart.ai/llms.txt) 当前接口为准，检查实际图像编辑、上传、异步任务轮询和透明输出支持；模型不可用时说明，不静默更换服务或模型。及时保存生成结果，避免临时链接过期。绝不承诺提示词能锁定像素或文字。

本技能固定使用 `model: gpt-image-2.6-ext`、`version: sunburst`、`quality: xhigh`、`resolution: 2k`、`n: 1`，将每张原图放入 `image_urls`。Sunburst 侧重文字和精细编辑，较高质量可能耗时更长；模型、版本及分辨率可能计费，不得静默降级。尺寸按原图选择最接近的支持比例。此模型文档说明 `background` 参数不生效，因此要求干净纯白背景，再在本机提取蒙版制作透明图；不要把白底图宣称为透明图。调用前以[模型文档](https://docs.apimart.ai/en/api-reference/images/gpt-image-2.6-ext/generation.md)确认参数仍然可用。较高质量可能改善一致性，但无法保证文字不变，验收仍是必需的。

## 操作与验收

1. 将原照作为唯一商品事实来源，保留原件，每张独立处理。使用上述固定模型进行图生图编辑，要求完整主体、纯白背景、适度提亮，保持原照角度和商品数量。候选通过包装核验后，本机提取蒙版生成透明图并再次核对；白底从已通过检查的透明图在本机合成 #FFFFFF，确保两张商品一致。不要自行增加场景、标语、认证或价格。
2. 提示词示例：

   ```text
   Edit the supplied product photo only: remove its background and gently brighten it.
   Preserve the exact original package geometry, colors, typography and every visible
   character, number, logo, barcode and marking. Do not redraw, invent, translate,
   replace, omit or alter any label or printed text; retain the original font, spacing,
   layout and placement. Keep the same product count, angle and proportions. No props,
   new text, claims or decorations. If text cannot be preserved, do not invent it.
   ```

3. 生成结果属于候选。将原图与候选按对应区域放大逐一对照品牌、字体字形、大小、位置、中文英文、数字、规格、二维码、条码、批准号以及包装颜色、角度和结构。检查边缘、残留、穿透、亮度；透明图必须核验 alpha，白底须为纯白。模型可能改字，即使提示要求保留也不能保证。原图或候选文字过小、模糊或不可辨认时，不得宣称一致。
4. 字体或文字有变化、缺失、新增、错误，或主体/轮廓不合格，标记 `REJECTED`；任何必要信息无法核验，标记 `UNVERIFIABLE`；只有所有必要可见项目经核对一致才标记 `PASS`。失败时可针对原因使用同一原图最多再生成一次；仍失败或无法核验则停止，说明具体问题，可请求清晰近拍。仅在用户明确接受时展示标注“生成式参考，勿上架”的候选，不称为保真成品。
5. 报告实际模型、输出文件及核验状态；只报告真实完成的结果，不泄露密钥、临时链接或用户图片的上传地址。
