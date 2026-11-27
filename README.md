> 更新：`ai-ecommerce-product-images` 现为纯本地提亮抠图；`apimart-ecommerce-product-cutout` 为独立的 APIMart 生成式抠图技能。总领工作流仍有其自身的 GPT 默认设置。

# 商品图处理与模板套版 Agent Skills

从真实商品原图出发，使用四个 Agent Skills 制作固定 PSB 主图、图文详情图或双商品拼图：

| 技能 | 用途 |
| --- | --- |
| `ecommerce-template-workflow` | 总领流程：GPT 内置白底/透明抠图，本地主图套版、图文详情图和双商品同平面拼图 |
| `ai-ecommerce-product-images` | 本地商品抠图、参考图取样调色、精修边缘，输出配套白底与透明 PNG |
| `apimart-ecommerce-product-cutout` | APIMart 生成式抠图与包装文字核验 |
| `psb-template-product-swap` | 透明商品素材处理和固定 PSB 母版套版 |

## 安装

需要 Node.js 22.20 或更新版本，以及终端可调用的 Git。在目标项目目录运行：

```bash
npx skills add Fishkiller111/ecommerce-product-image-skills
```

按提示选择 `ecommerce-template-workflow` 和 `psb-template-product-swap` 即可使用总领流程；若需要直接点名 `$ai-ecommerce-product-images`，请一并安装该技能。Windows PowerShell 若提示 `npx.ps1` 被执行策略阻止，可改用 `npx.cmd skills add Fishkiller111/ecommerce-product-image-skills`，无需修改执行策略。

需要在 Codex 全局安装时，可使用：

```bash
npx skills add Fishkiller111/ecommerce-product-image-skills --skill '*' --agent codex --global --yes
```

请先检查同名技能，避免误覆盖。安装后在 Agent 会话中调用 `$ecommerce-template-workflow`，提供真实商品原图并说明所需结果：

- **主图**：使用固定 PSB 母版；例如“主标题买5赠一，底部大字双十二特惠”。
- **详情图**：提供标题、卖点或构图参考；例如“做竖版详情图，商品居中，标题写‘商品展示’”。
- **拼图**：提供两张真实商品原图；例如“拼图，图一在上、图二在下”。上下关系用同一地面上的前后错位表达，左右排列时底部对齐；两件商品各自保留接触阴影，不做无支撑的上下堆叠。

## Codex 快速更新

**已安装旧版？先确认 GitHub 已发布所需版本，再把对应系统的一行发给 Codex，让它在原先安装 Skill 的项目根目录执行。** 仓库未发布时，GitHub 安装仍是旧版，应使用本次本地更新包。以下命令更新四个技能目录；有手工改动请先备份。

macOS / Linux：

```bash
npx --yes skills@1.8.1 add Fishkiller111/ecommerce-product-image-skills --skill ecommerce-template-workflow psb-template-product-swap ai-ecommerce-product-images apimart-ecommerce-product-cutout --agent codex --copy --yes
```

Windows PowerShell（用 `npx.cmd`，无需改执行策略）：

```powershell
npx.cmd --yes skills@1.8.1 add Fishkiller111/ecommerce-product-image-skills --skill ecommerce-template-workflow psb-template-product-swap ai-ecommerce-product-images apimart-ecommerce-product-cutout --agent codex --copy --yes
```

- **原来是全局安装**：在同一条命令末尾加 `--global`。否则不要加，以免留下项目级和全局两份。
- 命令包含 `ai-ecommerce-product-images`，以同步直接点名的白底技能。更新不会调用图片服务，也不要求 API Key。若原来有多个同名副本，先确认实际生效位置。
- 安装完成后新开一个 Codex 会话，调用 `$ai-ecommerce-product-images`，提供商品原照及可选参考图。新版安装目录内含 `scripts/finish_recipe.py` 和 `references/reference-finishing.md`。

## 运行条件和边界

- 本地抠图使用 Python 3、Pillow 和 NumPy。参考取样调色需要 OpenCV，边缘去灰需要 SciPy。用保存的蒙版、轮廓和色样复跑时核对原图指纹，步骤见 [参考调色与修边](skills/ai-ecommerce-product-images/references/reference-finishing.md)。
- 直接调用本地抠图技能时，商品图只在本机提亮和抠图；总领工作流的单独白底/透明任务仍按其 GPT 流程执行。
- APIMart 抠图需要上传照片并可能计费；生成结果必须对照核验包装字体和文字，无法核验不能作为保真成品。
- macOS：Python 3.11+、`requirements.txt`、系统中文字体；自动抠图需 macOS 14+ Vision 和 Xcode Command Line Tools。Windows 10 64 位：建议 Python 3.12 64 位和 `requirements-windows.txt`，使用 `run.bat` 或直接用 Python 运行。Windows 本地 CPU 抠图基于 rembg/ONNX Runtime，仅生成蒙版；首次使用需联网下载 `u2netp` 模型。Windows 字体缺失、ONNX DLL 缺失或自动抠图失败时应先解决依赖或使用已核对的透明 PNG。模型权重和训练数据许可应另行核对。具体命令见套版 Skill。
- Windows Server CI 测试不代表 Windows 10 真机已经验收；部署前请在目标设备执行真实素材的抠图、中文排版和上架复核。
- 包含固定 PSB 母版及其原有版式和品牌文字；请确认使用场景和授权。模板采用文件哈希与图层配置校验，不能随意替换。
- 商品身份、包装文字、边缘和清晰度需人工核对。AI 重绘导致文字或细节不可靠时，只能制作标记“勿上架”的效果样张，不能当作实拍或可上架成品。
- 拼图地面与阴影为二维视觉合成，不是物理仿真；旧主图与详情图套版可能额外添加整体阴影，联动产物暂只作版式预览。
- 流程输出为扁平 PNG，不生成可编辑的 PSB。活动文案和其他声明需由使用者核实。

项目中的 `SKILL.md` 分别保留各技能的详细使用方法与边界。AI 图像服务的可用性、模型和价格可能变化，请以服务商当前配置为准。
