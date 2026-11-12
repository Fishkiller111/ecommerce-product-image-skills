# 商品图处理与模板套版 Agent Skills

从商品原图和文案出发，使用三个 Agent Skills 完成保真处理、抠图与固定 PSB 模板套版：

| 技能 | 用途 |
| --- | --- |
| `ecommerce-template-workflow` | 总领流程：协调商品处理、文字和模板合成 |
| `ai-ecommerce-product-images` | 原图白底处理及商品保真检查 |
| `psb-template-product-swap` | 透明商品素材处理和固定 PSB 母版套版 |

## 安装

需要 Node.js 22.20 或更新版本。在目标项目目录运行：

```bash
npx skills add Fishkiller111/ecommerce-product-image-skills
```

按提示选择三个技能和需要使用的 Agent；需要在 Codex 全局安装时，可使用：

```bash
npx skills add Fishkiller111/ecommerce-product-image-skills --skill '*' --agent codex --global --yes
```

请先检查同名技能，避免误覆盖。安装后在 Agent 会话中调用 `$ecommerce-template-workflow`，提供商品原图和最终文案，例如“主标题买5赠一，底部大字双十二特惠”。

## 运行条件和边界

- 商品图 AI 处理使用 APIMart：需自备 `APIMART_API_KEY` 和服务地址 `APIMART_BASE_URL`，或使用 Agent 中已配置的 APIMart 工具；不得提交密钥。调用会向第三方上传商品图，且可能产生费用。
- macOS：Python 3.11+、`requirements.txt`、系统中文字体；自动抠图需 macOS 14+ Vision 和 Xcode Command Line Tools。Windows 10 64 位：建议 Python 3.12 64 位和 `requirements-windows.txt`，使用 `run.bat` 或直接用 Python 运行。Windows 本地 CPU 抠图基于 rembg/ONNX Runtime，仅生成蒙版；首次使用需联网下载 `u2netp` 模型。Windows 字体缺失、ONNX DLL 缺失或自动抠图失败时应先解决依赖或使用已核对的透明 PNG。模型权重和训练数据许可应另行核对。具体命令见套版 Skill。
- Windows Server CI 测试不代表 Windows 10 真机已经验收；部署前请在目标设备执行真实素材的抠图、中文排版和上架复核。
- 包含固定 PSB 母版及其原有版式和品牌文字；请确认使用场景和授权。模板采用文件哈希与图层配置校验，不能随意替换。
- 商品身份、包装文字、边缘和清晰度需人工核对。AI 重绘导致文字或细节不可靠时，只能制作标记“勿上架”的效果样张，不能当作实拍或可上架成品。
- 流程输出为扁平 PNG，不生成可编辑的 PSB。活动文案和其他声明需由使用者核实。

项目中的 `SKILL.md` 分别保留各技能的详细使用方法与边界。AI 图像服务的可用性、模型和价格可能变化，请以服务商当前配置为准。
