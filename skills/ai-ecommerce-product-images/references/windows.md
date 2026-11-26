# Windows PowerShell 安装与运行

面向 Windows 10 和 Windows 11 x64，使用 Python 3.12 x64。下面的命令从安装了本技能的项目根目录运行。全局安装时，将 `$Skill` 改为实际安装目录。

## 首次准备

```powershell
$Skill = (Get-Item -LiteralPath '.\.agents\skills\ai-ecommerce-product-images').FullName
py.exe -3.12 -m venv .\.venv-product-cutout
$Python = (Get-Item -LiteralPath '.\.venv-product-cutout\Scripts\python.exe').FullName
& $Python -m pip install -r (Join-Path $Skill 'requirements-windows.txt')
```

若有已安装的 Python 3.12 x64 而命令行里没有 `py.exe`，可使用该解释器的完整路径执行 `-m venv`。直接调用虚拟环境里的 `python.exe` 即可。已有透明 PNG、同尺寸灰度蒙版或轮廓配方时，可跳过模型准备。

对普通 JPG 或白底照片做自动抠图时，先联网准备一次 CPU 模型。商品图片在本机推理，准备步骤只下载权重。

```powershell
& $Python -X utf8 -c "from rembg import new_session; new_session('u2netp', providers=['CPUExecutionProvider'])"
```

默认从当前账户的 `.rembg\models\u2netp\u2netp.onnx` 读取权重，也能读取旧版 `.u2net` 目录的平铺权重。Windows 优先使用已准备的 `u2netp`，仅有 `u2net` 时可复用。若需指定模型目录，在模型准备和抠图时使用同一个 `$env:U2NET_HOME` 绝对路径。显式传 `--model u2net` 或 `--model u2netp` 可指定模型。

## 处理商品图

```powershell
$Script = Join-Path $Skill 'scripts\local_product.py'
& $Python -X utf8 $Script '.\素材\商品 原照.jpg' --out '.\输出\商品 01'
```

`--out` 指向每次新建的输出目录。用同尺寸灰度蒙版重跑时加入 `--mask '.\素材\商品 蒙版.png'`。背景和商品边界清楚时，也可用 `--backend grabcut --rect X Y WIDTH HEIGHT`。矩形使用原照经 EXIF 方向校正后的坐标。调色、配方和验收按[参考调色与修边](reference-finishing.md)执行。

若报缺少权重，检查报错所列目录中的文件名。若报 ONNX Runtime 的 DLL 导入错误，检查 Python 位数和微软的 x64 Visual C++ 运行库。[ONNX Runtime 安装说明](https://onnxruntime.ai/docs/install/)
