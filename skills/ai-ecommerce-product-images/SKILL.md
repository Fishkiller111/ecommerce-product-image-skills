---
name: ai-ecommerce-product-images
description: 本地精修电商软膏软管、纸盒、瓶罐等商品实拍，恢复可辨的管盖和封口边缘，按白色包材、彩印和深色文字调色，导出配套纯白底图和透明 PNG。
---

# 本地商品抠图与精修

用原照保留商品的角度、结构、印字和纹理。全程在本机处理，使用原图像素。同款参考可用于对应材质取样。不同商品的成品案例用于检查亮度、印刷反差和修边质量。

1. **跑默认流程。** 运行 `python <技能目录>/scripts/local_product.py <原图> --out <新输出目录>`。默认保留原图 alpha 或同原图匹配的确认配方。普通照片使用 Vision 或本地 rembg 生成初始蒙版，再用 OpenCV 沿原照细化不透明包装边线，检查软管是否漏掉管盖。默认按包材调色，白盖、彩印和深色文字分别控制。Windows 安装见 [PowerShell 操作](references/windows.md)。
2. **对照原照逐段放大。** 依次看软管封口、两侧、肩位、盖沿和实体底部，盒装检查折角与长边，瓶罐检查曲线、盖沿和接缝。对照 `white.png`、`preview_dark.png` 和原尺寸图。`review.json` 中 `edge.cap_check` 提示是否补回端部或需要重点检查。发现漏件、多抠或投影时，沿实物外沿修正同尺寸灰度 `--mask` 后重跑。透明盖、孔洞、薄膜和软边保留局部灰度，使用 `--edge-mode preserve`。处理方式见[精修轮廓](references/reference-finishing.md#精修轮廓)。
3. **核对包材与印刷。** 白色要能辨出接缝和厚薄，彩印提亮后保留色相、纹路和深字反差。偏色明显时，在确定为白或灰的包材内用 `--neutral-rect`。同款换角度或换光线时重新取样，专用配方只按原图指纹复用。按[分区调色](references/reference-finishing.md#按参考图取样)调整，明确保留原曝光和原色时使用 `--strength 0`。
4. **验收后交付。** 确认 `white.png` 是 `transparent.png` 叠到纯白后的逐像素结果。核对轮廓、文字和调色后，在 `review.json` 写入 `PASS`。明显残边、缺件、色差或印字损坏记 `REJECTED`。原照关键细节无法核验记 `UNVERIFIABLE`，按样张说明具体部位。见[成品验收](references/reference-finishing.md#成品验收)。

需要 Python 3、带 LittleCMS 的 Pillow、NumPy 和 OpenCV（原照引导修边、参考取样）。macOS Vision 需要 macOS 14+ 和 Xcode Command Line Tools。已有配方的 `decontaminate_px` 用 SciPy。

交付默认 1440 × 1440 的 sRGB `white.png` 和 `transparent.png`。同时保存原尺寸主体 `native_original_rgba.png`、`native_enhanced_rgba.png`、`mask.png`、深灰预览 `preview_dark.png` 和 `review.json`。
