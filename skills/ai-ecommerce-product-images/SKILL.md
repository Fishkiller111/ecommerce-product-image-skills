---
name: ai-ecommerce-product-images
description: 本地抠图后必做亮度和色彩校正，有参考图时可分区取样调色。精修边缘，保留包装原字，输出配套透明 PNG 和纯白底图。
---

# 本地商品抠图与精修

以本次原照为商品、印字、纹理、角度和边缘的依据。参考图只用于判断各部位的亮度、色相和饱和度。只在本机处理，使用非生成式工具保留包装原有印字。交付配套透明 PNG 和纯白底图。

## 每张图的流程

1. **从原照生成抠图与调色底稿。** 用 `scripts/local_product.py` 加载原照，脚本默认同时处理亮度和色彩。Vision、rembg、GrabCut 和手工蒙版只负责提供轮廓，交由该脚本继续调色、合成。原照指纹匹配已有精修配方时，带 `--finish-recipe` 重跑。尖括号内替换为实际路径，使用新的输出目录。

   ```text
   python <技能目录>/scripts/local_product.py <原图> --out <新输出目录>
   ```

2. **每次必做亮度与色彩校正。** 用户只说「输出商品白底图和透明图」时也执行。有已确认的同商品标准图时，优先匹配正面主色、深色印刷和侧面的明暗关系，并以该图为校正上限。不同角度重新取样，无参考图用默认温和校正，只处理可见的偏暗和色偏。放大对照 `native_original_rgba.png` 与 `native_enhanced_rgba.png`，检查 `review.json` 中的 `tone`。如果深色发红发亮、黄色偏橙、侧面与正面一样亮，或小字反差变弱，降低强度或缩小色样作用区域。原照已达到目标时只做轻调。用户明确要求保留原曝光和原色时使用 `--strength 0`。
3. **在两个底色上验边。** 用 `white.png` 和 `preview_dark.png` 对照原照，放大查看四周，重点看长边台阶、底部桌面阴影、盖角和白色材质。硬盒发生错位时，沿原照实际边界重描长边和转角，把盒盖的真实折角留在轮廓里，再按需对过渡带去灰边。不能靠全局收缩掩盖错位。软管、透明材质、孔洞使用灰度蒙版做局部修补。细节参见[参考调色与修边](references/reference-finishing.md)。
4. **核验再交付。** 检查可辨的印字、标识和图案，核对轮廓、亮度、色彩和纹理。以调色后的主体输出带 alpha 的 `transparent.png`，再用它合成 `white.png`。交付时简述实际做的亮度与色彩调整；手工处理也要记录具体操作。检查通过记 `PASS`，明显残边、缺件或文字损坏记 `REJECTED`，原图小字无法逐项确认记 `UNVERIFIABLE`。有问题先修再看，未通过的图只能注明为样张。

## 工具与文件

基本处理需要 Python 3、Pillow 和 NumPy。已有透明图可复用 alpha；macOS 默认 Vision（macOS 14+ 和 Xcode Command Line Tools），也可选已装本地权重的 rembg，或使用 OpenCV GrabCut 和手工蒙版。参考取样调色额外需要 OpenCV，窄边去灰额外需要 SciPy。具体参数和分发样例见[参考调色与修边](references/reference-finishing.md)。

输出 `white.png`、`transparent.png`、`native_original_rgba.png`、`native_enhanced_rgba.png`、`mask.png`、`preview_dark.png` 和 `review.json`。默认方图为 1440 × 1440。保留原件和原尺寸主体，记录蒙版来源、配方、调色及核验结果。
