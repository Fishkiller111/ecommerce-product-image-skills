---
name: ai-ecommerce-product-images
description: 在本机抠取真实商品、按参考图取样调色并精修边缘，输出配套透明 PNG 和纯白底图，保留原包装文字。
---

# 本地商品抠图与精修

以本次原照为商品、印字、纹理、角度和边缘的依据。参考图只用于判断各部位的亮度、色相和饱和度。只在本机处理，使用非生成式工具保留包装原有印字。交付配套透明 PNG 和纯白底图。

## 每张图的流程

1. **先出底稿。** 用真实原照运行 `scripts/local_product.py`。有已核验且原照指纹相同的精修配方时，直接带 `--finish-recipe` 重跑，随后检查成图。底稿命令如下，尖括号内替换为实际路径，新输出目录不能已存在。

   ```text
   python <技能目录>/scripts/local_product.py <原图> --out <新输出目录>
   ```

2. **有参考图就分区调色。** 放大对比原照与参考图的同材质区域，分别取样亮度与色彩。例如暖黄提高亮度、暖红恢复层次、金属描边提亮并保留反光。以本次样片为准，按需用 `--finish-recipe` 的 `palette` 定向调整；细字、标识和底纹不能因提亮或锐化失去可辨性。无参考图使用默认自适应调色，根据实际观感调整。
3. **在两个底色上验边。** 用 `white.png` 和 `preview_dark.png` 对照原照，放大查看四周，重点看长边台阶、底部桌面阴影、盖角和白色材质。硬盒发生错位时，沿原照实际边界重描长边和转角，把盒盖的真实折角留在轮廓里，再按需对过渡带去灰边。不能靠全局收缩掩盖错位。软管、透明材质、孔洞使用灰度蒙版做局部修补。细节参见[参考调色与修边](references/reference-finishing.md)。
4. **核验再交付。** 检查可辨的印字、标识和图案，核对轮廓完整、无明显残边、颜色鲜亮且有纹理。透明 PNG 必须有实际 alpha；白底图由同一张透明图合成。仅通过检查的结果记 `PASS`，明显残边、缺件或文字损坏记 `REJECTED`，原图小字无法逐项确认记 `UNVERIFIABLE`。有问题先修再看，未通过的图只能注明为样张。

## 工具与文件

基本处理需要 Python 3、Pillow 和 NumPy。已有透明图可复用 alpha；macOS 默认 Vision（macOS 14+ 和 Xcode Command Line Tools），也可选已装本地权重的 rembg，或使用 OpenCV GrabCut 和手工蒙版。参考取样调色额外需要 OpenCV，窄边去灰额外需要 SciPy。具体参数和分发样例见[参考调色与修边](references/reference-finishing.md)。

输出 `white.png`、`transparent.png`、`native_original_rgba.png`、`native_enhanced_rgba.png`、`mask.png`、`preview_dark.png` 和 `review.json`。默认方图为 1440 × 1440。保留原件和原尺寸主体，记录蒙版来源、配方、调色及核验结果。
