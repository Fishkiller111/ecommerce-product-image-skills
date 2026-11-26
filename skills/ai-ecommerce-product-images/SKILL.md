---
name: ai-ecommerce-product-images
description: 在本机将真实商品抠成配套纯白底图和透明 PNG。按材质校正曝光和偏色，精修毛边、锯齿和残留背景，保留包装印字及纹理。
---

# 本地商品抠图与精修

从原照保留商品的角度、结构、印字和纹理。用本地非生成式处理完成调色、轮廓精修和导出。用户给出的成品案例用于判定色调、质感和边缘。同款参考可用于对应材质的精准取样。

1. **生成底稿。** 用 `scripts/local_product.py` 生成初版。源图已有真实透明背景时复用 alpha。自动蒙版由 Vision 或本地 rembg 提供，也可用 GrabCut 或 `--mask`。脚本按原图 SHA-256 载入已启用的精修配方。见[运行与复跑说明](references/reference-finishing.md#选择底稿)。

   ```text
   python <技能目录>/scripts/local_product.py <原图> --out <新输出目录>
   ```

2. **逐材质调色。** 核对原照与精修图中的主色、深色印刷、白色部件和折面。默认按主体高光余量提亮，亮色包装减少干预，深色印刷保留反差。确认白盖或灰色材质偏色时，可用 `--neutral-rect` 取样。有同款成品时用 `palette` 按对应材质取样校色。用跨品类成品对照材质表现和边缘质量。同商品换光线或角度需重新取样。具体见[分区调色](references/reference-finishing.md#按参考图取样)。用户要求保留曝光和原色时用 `--strength 0`。
3. **逐段修边。** 在白底和深灰底看最终输出，按原尺寸核对边线，放大确认转角、长斜边、折口、瓶盖、孔洞和实体底沿。先沿原照修正错位、缺口和夹带阴影，再处理窄过渡带。硬盒或不透明瓶身可试 `--edge-mode opaque`，比较修前修后。软边、孔洞和半透明部件用灰度蒙版局部精修。见[精修轮廓](references/reference-finishing.md#精修轮廓)。
4. **验收后交付。** 检查白底、深灰底以及原尺寸导出。核对材质、细字、纹路、边缘完整度和底色一致性。确认 `white.png` 由最终 `transparent.png` 像素一致地合成。仍有可修复的问题就修正并复跑。通过后在 `review.json` 写入 `PASS`。色差明显、漏抠、多抠或印字损坏记 `REJECTED`，原照关键细节无法判读记 `UNVERIFIABLE`。后两种按样张标注并说明部位。参见[成品验收](references/reference-finishing.md#成品验收)。

基本处理需要 Python 3、带 LittleCMS 的 Pillow 和 NumPy。参考取样调色用 OpenCV，已有配方的 `decontaminate_px` 用 SciPy。macOS 自动蒙版需 macOS 14+ 和 Xcode Command Line Tools。

输出 `white.png`、`transparent.png`、`native_original_rgba.png`、`native_enhanced_rgba.png`、`mask.png`、`preview_dark.png` 和 `review.json`。默认方图为 1440 × 1440。白底、透明图和两种原尺寸图统一为 sRGB。
