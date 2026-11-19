# GPT 内置商品抠图：统一流程 v2026-11-19-gpt-cutout-1

## 适用范围与边界

单独要求商品白底图、透明抠图，或同时要求二者时，默认使用 **当前会话实际可用的 GPT 内置图片编辑工具**处理该张原照。macOS 和 Windows 执行同一流程和固定提示词；不使用 APIMart，不因为操作系统自动切换本地抠图或其他模型。不需另配 API Key；能否使用以当前会话提供的真实工具为准，Skill 本身不安装、提供或保证该工具。素材会交由 GPT 图像服务处理，不是纯本地处理。

一致的流程和提示词只能降低流程差异，不能保证生成完全一致、锁定服务端模型版本或消除随机性；模型可能重绘、改字或新增虚构内容。**图片生成工具的界面预览和最终通过检查的文件不是一回事。**调用前告知“下面如出现生成预览，均为待核验样张，不代表可上架”；只展示明确通过检查的最终路径。不要把被拒绝的预览称为成品。

用户明确要求仅本地或不上传时，不调用 GPT；按其要求使用本地工具并明确说明路径，不冒充统一 GPT 流程。用户明确要求 APIMart 且已配置并授权时才调用该分支，不作为 GPT 的自动降级。工具缺失、调用失败或素材无法读到时停止并说明；不凭截图猜工具可用，不静默改走其他模型、API、第三方服务或本地抠图，不伪造结果。

## 输入和调用

1. 用用户本次提供的**完整原照**作为唯一商品事实来源，核实每个附件与商品对应关系；不要用聊天缩略图、旧生成图或另一角度照片代替。多张原照逐张独立处理，各自输入各自原图；保留原图，不覆盖。
2. 每张用当前会话暴露的 GPT 内置图片编辑工具进行一次编辑，工具名、可传入的参考图机制和透明背景参数以当前环境实际接口为准；不要通过自行编写 API 脚本冒充内置工具。仅提供该张原照，并要求 1:1、完整商品居中和适量留白；不添加场景图、宣传语或多余商品。精确分辨率和模型版本只有工具实际支持并返回时才记录，无法指定则不声称已固定。
3. 固定提示词如下。只替换 `BACKGROUND`：白底单图使用 `a pure white (#FFFFFF) background`；透明图使用 `a genuinely transparent background with an alpha channel`。请求透明图时，同时使用工具实际支持的透明背景参数；不要将白底 PNG 误称透明图。

```text
Use case: background-extraction for an e-commerce product photograph.
Edit the supplied original photograph; this is the only product reference.
Remove the existing surroundings and place the complete product centered on BACKGROUND.
Use a square composition with comfortable margins. Gently improve the product exposure,
contrast and detail while keeping realistic colors and the original camera perspective.
Preserve the exact package geometry, quantity, orientation, edges, panels, colors, logos,
Chinese and English text, numbers, net content, QR code, barcode and every visible marking.
Do not redesign, reinterpret, translate, add, replace or remove packaging text or details.
Do not invent information when text is illegible. Do not add props, people, badges,
medical claims, promotional copy or extra products. Keep the product recognizable as the
same object in the source photo. Background must be clean; no extraneous artifacts.
```

4. **仅白底**：用白底参数，交付通过检查的白底图。**仅透明**：用透明参数并核实真 alpha。**白底和透明同时需要**：只生成一张透明图，核验后再用同技能的 `scripts/composite_white.py` 把同一张透明图铺到 `#FFFFFF` 生成配套白底，不重绘商品、也不再调用另一模型；两张商品内容一致。该脚本使用 Python 与 Pillow，跨系统只执行确定性的 alpha 合成。若缺少依赖、透明输出无效、四角不透明或合成失败，则说明未能生成配套白底，不以别的模型或本机分割静默补做；不得将白底伪装成透明图。合成示例（`PYTHON` 为当前环境可用的 Python，路径为实际绝对路径）：

```text
PYTHON scripts/composite_white.py GPT透明候选.png --out 白底成品.png
```

脚本只检查基本 alpha 和输出文件，不替代包装文字、颜色或商品身份的人工核验。纯白合成不是第二次 GPT 生图。
5. GPT 输出先归类为**待核验候选**，记录实际输出文件；若工具只有界面预览且没有可访问文件，不能虚报保存路径。客户指定输出目录时，将实际通过核验的原始输出复制到该目录，使用新文件名、不覆盖原图和已有成品；只给当次对应文件，不引用旧记录。保留原始 GPT 生成版本，任何透明图转白底的合成需另存。

## 必须逐项对照原照

- 外形与包装：商品数量、姿态、比例、颜色、角度、正反面、侧面、边缘及盖子。
- 身份和文本：品牌、图案、品名、规格数字、净含量、商标、可辨认的中文英文、二维码、条码、批准号及所有可见说明。不能只检查大字；逐项放大比对。对于原片或候选中模糊、太小而不能确认的文字，记录“无法核验”，不得声称一致或已通过。
- 图像：目标背景、尺寸、主体完整性、毛边、原环境残留、亮度过曝和失真；透明版本用实际 alpha 检查，确认边角确为透明而不是黑色或白色背景。
- 禁止凭空添加文字、剂量、效用、认证、价格、标识或其他物件。药品/医疗相关商品尤其不能产生看似真实但未经提供的批准文号和疗效词。

任一可见内容发生改变、增删、缺件或错误，状态为 `REJECTED`；文字/细节无法对照时为 `UNVERIFIABLE`；只有所有必要项目可核实且一致才可记 `PASS`。这只是对可见部分的人工复核，不是平台审核或对商品合法性的保证。失败时可针对问题最多再编辑一次（同一原照与同一内置工具）；若仍失败或无法核验，不将候选文件当保真成品，不进入后续上架或主图制作。说明失败的具体内容，必要时请用户提供清晰近拍；仅在用户明确接受时，才交标注“AI 生成参考 / 勿上架”的效果样张，且不得暗示包装文字真实。

## 记录和交付

为每次任务记录来源文件 SHA-256、提示词版本、请求类型、使用的工具及**仅当工具返回时**的模型版本、实际输出像素、实际输出路径、检查状态与原因、实际尝试次数。版本未暴露时填“未知”，不要猜测、伪报固定参数或种子；记录不含凭据、临时访问链接。相同任务需要复用时优先使用此前已核对通过的实际文件，而不是重新生成并承诺像素一致。对外列出真实交付文件和检查结果，并明说这是 GPT 生成式编辑、商品可能经过重绘；工具不可用、结果不合格或透明不成立时如实说明，没有交付就不能称已交付。
