---
name: ai-ecommerce-product-images
description: 本地抠图后必做亮度和色彩校正，有参考图时可分区取样调色。精修边缘，保留包装原字，输出配套透明 PNG 和纯白底图。
---

# 本地商品抠图与精修

以本次原照为商品、印字、纹理、角度和边缘的依据。参考图只用于判断各部位的亮度、色相和饱和度。只在本机处理，使用非生成式工具保留包装原有印字。交付配套透明 PNG 和纯白底图。

## 每张图的流程

1. **从原照生成抠图与调色底稿。** 用 `scripts/local_product.py` 加载原照。脚本按原图 SHA-256 自动选用已启用的精修配方，也接受 `--finish-recipe` 指定配方。Vision、rembg、GrabCut 和手工蒙版只提供轮廓。用 `--mask` 重做轮廓时沿用原来的取样配方和调色参数；已使用显式配方的任务继续带上该配方，若配方内含轮廓则先移除 `outline`。

   ```text
   python <技能目录>/scripts/local_product.py <原图> --out <新输出目录>
   ```

2. **每次必做亮度与色彩校正。** 用户只说「输出商品白底图和透明图」时也执行。处理广至德「无藓膏」金黄红框盒时，先读[该款确认标准](references/reference-finishing.md#无藓膏金黄红框盒)。有同商品标准时按对应材质分区校色，核对 `review.json` 的 `tone.method` 为 `reference-palette`，换角度或裁切时按新图取样。缺少参考时，以默认强度对照原照和调色后的原尺寸主体，有可见的过亮、过饱和或印字反差下降时再调低。用户明确要求保留原曝光和原色时使用 `--strength 0`。
3. **在两个底色上验边。** 用 `white.png` 和 `preview_dark.png` 对照原照，放大查看四周，重点看长边台阶、底部桌面阴影、盖角和白色材质。硬盒发生错位时，沿原照实际边界重描长边和转角，把盒盖的真实折角留在轮廓里，再按需对过渡带去灰边。不能靠全局收缩掩盖错位。软管、透明材质、孔洞使用灰度蒙版做局部修补。细节参见[参考调色与修边](references/reference-finishing.md)。
4. **核验再交付。** 在相同底色下对比 `native_original_rgba.png` 和 `native_enhanced_rgba.png`。有标准时另对照主色、深色印刷、侧面和中性细节。若主体仍偏暗或颜色偏离标准，复调后再交付。检查可辨的印字、纹理、轮廓，确认 `white.png` 由调色后的 `transparent.png` 合成。交付简述实际调整和 `tone` 记录。检查通过记 `PASS`，明显残边、缺件、文字损坏或颜色偏离标准记 `REJECTED`，原图小字无法逐项确认记 `UNVERIFIABLE`。未通过的图注明为样张。

## 工具与文件

基本处理需要 Python 3、Pillow 和 NumPy。已有透明图可复用 alpha；macOS 默认 Vision（macOS 14+ 和 Xcode Command Line Tools），也可选已装本地权重的 rembg，或使用 OpenCV GrabCut 和手工蒙版。参考取样调色额外需要 OpenCV，窄边去灰额外需要 SciPy。具体参数和分发样例见[参考调色与修边](references/reference-finishing.md)。

输出 `white.png`、`transparent.png`、`native_original_rgba.png`、`native_enhanced_rgba.png`、`mask.png`、`preview_dark.png` 和 `review.json`。默认方图为 1440 × 1440。保留原件和原尺寸主体，记录蒙版来源、配方、调色及核验结果。
