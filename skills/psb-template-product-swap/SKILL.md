---
name: psb-template-product-swap
description: 无需 Photoshop，按固定抖音 PSB 母版换品、换文案。默认先做商品调光和细节增强，清晰度不足不作为成品，支持单独输出 AI 修复样张。
---

# 无 Photoshop 抖音主图换 SKU

固定使用 `templates/抖音新店. 拷贝-1440(修改).psb`。不覆盖母版，不重绘商品。只在浅色商品区和指定文案处动手；参考图只借鉴大小、层次和落地阴影，不借用品牌、价格、赠送或功效话术。

## 一条命令

`PSB_SKILL_DIR` 为本技能 `SKILL.md` 所在的绝对目录；先将它设为安装后的真实路径（项目级通常是 `.agents/skills/psb-template-product-swap`，全局安装时以安装结果为准）。

```bash
"$PSB_SKILL_DIR/run.sh" 商品照片.jpg --sku SKU001
"$PSB_SKILL_DIR/run.sh" 商品照片.jpg --sku SKU002 --text-json 文案.json
"$PSB_SKILL_DIR/run.sh" 指定的高清透明素材.png --sku SKU003 --prepared-cutout --text-json 文案.json
"$PSB_SKILL_DIR/run.sh" 指定的高清透明素材.png --sku SKU004 --prepared-cutout --keep-product-look
```

- **默认先调光和高清增强，再入模**：实拍、已有透明图和 `--prepared-cutout` 三种输入都执行同一套商品增强，不需要额外加参数。棚拍曲线按商品的曝光和高光余量处理偏暗区域，保留印字、色相和透明轮廓；不重绘、不对整张模板调光。旧参数 `--studio-light` / `--lift` 均兼容，效果与默认相同，不叠加。只有客户明确要求保留输入原色与锐度时才用 `--keep-product-look`，关闭调光和高清增强；等比套版所需的尺寸调整仍会进行。
- **指定素材不能被替换**：提供成品透明 PNG 并明确指定时用 `--prepared-cutout`，跳过重新抠图，裁掉极低透明度残点，不回退到旧实拍；有效主体不够大时停止并说明。已足尺寸的素材不为凑尺寸而放大。AI 重建的包装只可用于内部效果确认，未与实物核对的印字和声明不得当作上架素材。
- **抠图**：有确认过的透明 PNG 则跳过分割，否则 macOS 使用本机 Vision、Windows 使用本地 CPU 模型，只提取蒙版。先看白色包装、边缘和贴合处；发现漏抠、白边或缺字，先修轮廓再交付。可用 `--photo-profile 路径.json` 重跑；轮廓配置只对指纹匹配的原照片生效。
- **清晰度必须看成图**：抠图后单独调光、去噪和有界锐化，再使用增强素材入模。这是基础增强，不是去模糊重建；透明边缘不参与锐化。脚本比较输入主体与置入尺寸（不是整张源图或插值后的尺寸）；需要放大超过 1% 时实拍路径只输出「清晰度未达标」套版草稿。尺寸足够也要按成图 100% 检查包装品名、细字、边缘和压缩块，模糊则不要交作成品。
- **用户反馈“还是糊”时走修复分支**：不要重复套版或加大锐化。优先使用未压缩的同角度近拍或用户核对过的清晰透明 PNG。若当前只能做 AI 修复试样，把透明商品单独交给可用的图像编辑工具处理，不能把整个 PSB 或模板文字交给它重绘；对照原图检查包装印字、图案、颜色、规格及轮廓。生成结果有改字、细节无法核对或形状变化，只能作为内部效果样张，不能作为实拍或上架。用 `--prepared-cutout --keep-product-look --ai-restored-preview` 将试样套入同一模板：成图和文件均标「勿上架」。这个参数只负责套版与标记，不调用修复模型。
- **构图**：横向商品尽量占画面宽约 84%，保持比例、不拉伸，补柔和接触阴影。`--product-align bottom` 可使无标题版的商品底部贴近底栏。若源主体像素不足，限制放大并提示补拍，不生成假细节。已校对照片配置可指定曝光和白平衡，原像素抠图单独保留。
- **文字**：仅使用客户确认或可从包装核对的描述。`hero_title` / `hero_subtitle` 可在浅色区建立标题层级；不传则该区域只放商品。模板文字键为 `header`、`promo`、`badge`（两行，用 `\n`）、`tag_1`、`tag_2`、`tag_3`。示例见 [文案示例](examples/copy.json)。无新文案保留原文，未确认的模板促销和承诺不可对外发布。
- **输出**：`outputs/psb-template-swap-direct/<SKU>/` 内有透明输入、入模素材、1440×1440 主图和复核 JSON。先看 `detail_review` 与 `publication`，再看 `studio_light`。在成图和原图间核对漏抠、过曝、光晕、包装细字和颜色；任何状态都不代替人工复核。每 SKU 独立目录，不覆盖结果。

## Windows 10 64 位安装与运行

在培训项目根目录的 PowerShell 中执行（`py` 为 Python Launcher；使用 Python 3.12 64 位）：

```powershell
$Skill = Join-Path (Get-Location) '.agents\skills\psb-template-product-swap'
py -3.12 -m venv .venv-product-skills
& '.\.venv-product-skills\Scripts\python.exe' -m pip install -r (Join-Path $Skill 'requirements-windows.txt')
$env:PSB_PYTHON = (Resolve-Path '.\.venv-product-skills\Scripts\python.exe').Path
$env:PSB_SKILL_DIR = $Skill
$env:PYTHONUTF8 = '1'
& (Join-Path $Skill 'run.bat') 'C:\素材\商品.jpg' --sku SKU001 --text-json 'C:\素材\文案.json'
```

`$Skill` 和示例路径按实际安装位置、文件名调整；输入中文及带空格路径须加引号。无需启用 PowerShell 脚本执行策略；退出 PowerShell 后应重新配置当前会话的 `PSB_PYTHON`、`PSB_SKILL_DIR` 和 `PYTHONUTF8`，或让 Codex 直接调用虚拟环境的 Python。

Windows 自动抠图使用本地 CPU 蒙版（rembg + ONNX Runtime，默认 `u2netp`），只对原始商品 RGB 增加 alpha，不将商品图片上传至抠图服务。第一次使用需联网下载对应权重；白色软管、多个商品、边缘及阴影仍须人工检查。可设置 `PSB_REMBG_MODEL=u2net` 使用较大模型；不得使用云端模型冒充本地处理。模型及训练数据许可独立于代码，商业使用前由使用者确认。未联网、缺少运行库或蒙版异常时中止，改用已确认透明 PNG；不可把空白结果当成功。

文字默认优先使用 Windows 系统的微软雅黑、黑体或宋体；如系统未安装，可设置 `PSB_FONT_PATH` 为中文字体文件绝对路径（集合文件可设置从 0 开始的 `PSB_FONT_INDEX`）。只读本机字体，不随包分发微软字体；缺字或不可用应报错，不要交付方框字。ONNX Runtime 如提示 DLL 缺失，请由管理员检查 Visual C++ 运行库。

此分发包不包含 Python 或第三方库。macOS 的套版继续使用 `requirements.txt`；自动抠图使用 macOS 14+ Vision 和 Xcode Command Line Tools。Windows 建议 Python 3.12 64 位并安装 `requirements-windows.txt`。Windows Server CI 不等于 Windows 10 真机验收；用户上架前仍需在自己的设备和素材上复核。结果是 **扁平 PNG，不是可编辑 PSB**。
