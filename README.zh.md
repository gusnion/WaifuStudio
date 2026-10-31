# WaifuStudio v2.0 — 本地动漫制作工作室

<p align="center">
  <img src="static/waifustudio-icon.png" width="112" alt="WaifuStudio icon">
</p>

[![Version](https://img.shields.io/badge/version-2.0.0-ff4081.svg)](https://github.com/gusnion/WaifuStudio)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Reference GPU](https://img.shields.io/badge/Reference%20GPU-RTX%203060%2012GB-76b900.svg)](https://www.nvidia.com)
[![Engine](https://img.shields.io/badge/Engine-ComfyUI%20Backend-orange.svg)](https://github.com/comfyanonymous/ComfyUI)
[![Local by default](https://img.shields.io/badge/Local-by%20default-success.svg)]()
[![Patreon](https://img.shields.io/badge/Patreon-gusnion-ff424d.svg)](https://www.patreon.com/gusnion)

> [English](README.md) | [Español](README.es.md) | [日本語](README.ja.md) | 中文 | [Русский](README.ru.md)

WaifuStudio 是一个面向动漫图像与短视频的本地优先制作工作区。它把图像生成、角色参考、视频生成、编辑、放大、Timeline 编排和图库管理汇集到一个 Web 界面中，并以 ComfyUI 作为推理引擎。

## 语言

界面支持 **英语(默认)**、**西班牙语**、**日语**、**简体中文**和**俄语**。使用顶栏的地球按钮切换。技术性的模型名称、prompt 示例、用户内容以及部分后端错误消息仍保留原语言。

应用围绕单块 NVIDIA GPU 和 Windows 桌面环境设计。它不需要账户、云服务或遥测。安装程序把 Python、ComfyUI 和 FFmpeg 放在一个可移植目录中。

> [!WARNING]
> **状态与范围**：这是一个独立项目，按“原样”提供，不附带担保。它的开发和测试围绕下方的参考配置进行。其他 GPU、操作系统和工作流或许可以运行，但未经过官方验证。预计会有粗糙之处，请备份你的项目和生成的媒体。

## 包含内容

| 模块 | 状态 | 功能 |
|---|---|---|
| **Windows 安装程序** | 可用 | 搭建可移植的 Python 环境、ComfyUI、自定义节点、模型、FFmpeg/FFprobe 以及应用快捷方式。 |
| **图像与 OC Maker** | 可用 | 支持 Anima 2.9B 和 SDXL/Illustrious、prompt 区域、LoRA 选择、角色档案、参考图像以及可选的 LoRA 训练。 |
| **prompt 助手** | 可用 | 本地 Danbooru 标签索引，外加可选的 CPU LLM，用于扩展 prompt 和生成图像描述。 |
| **H3 视频** | 可用 | 在 I2V、FLF2V、Ref2VA 和 V2V 模式下进行八步 VideoDeltaNet 生成，支持原生音频和简短 prompt 模板。 |
| **编辑器** | 可用 | 使用 Qwen-Image 2.1 进行基于指令的编辑，最多十张参考图像和 L0–L3 姿态预设。基于蒙版的局部重绘(inpainting)不属于本版本。 |
| **Timeline** | 可用 | 排列片段和静帧、设置时长、应用淡入淡出/缩放、静音片段、添加外部音频、用 I2V/FLF2V 延续片段并导出 MP4。它是一款专注于序列编辑的工具，并非完整的 NLE。 |
| **Upscaler** | 可用 | 以 GAN、Hires Fix 和 Qwen Remaster 模式放大图像，并支持 RCAS/Adaptive USM 锐化和 RIFE 插帧。视频放大每个任务上限为 300 帧。 |
| **图库与队列** | 可用 | 基于 SQLite 的图库、任务历史，以及所有标签页共享的单 GPU FIFO 队列。 |

## 安装(Windows)

### 开始之前

- Windows 10/11 64 位。
- NVIDIA GPU；参考机器使用 12 GB 显存的 RTX 3060。
- NVIDIA 驱动 570 或更高版本(该技术栈使用 CUDA 13)。
- 如果需要自动更新，请安装 Git for Windows。ZIP 安装无需 Git 也能使用。
- 为模型集合留出足够的磁盘空间。安装程序会显示大小，并在下载前询问。
- 较短的本地路径比同步文件夹更稳妥，例如 `C:\AI\WaifuStudio`。
- 如果有旧副本正在运行，请先用 `stop.bat` 停止。

### 方案 A：Git 克隆(推荐)

1. 克隆仓库：

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
```

2. 安装：

```powershell
install.bat
```

安装程序会创建隔离的 Python 环境、ComfyUI、自定义节点、FFmpeg 和快捷方式。它还会询问要下载哪些模型。重复运行是安全的：它会检查已存在的内容，只安装缺失的部分。

3. 启动应用：

```powershell
start.bat
```

它会在专用窗口中打开 `http://127.0.0.1:8765`。

4. 停止或诊断：

```powershell
stop.bat
healthcheck.bat
```

如果模型已在磁盘上，只需要引擎和应用：

```powershell
install.bat -SkipModels
```

首次安装时如果仍需要推荐模型，请不要使用 `-SkipModels`。

### 方案 B：ZIP

1. 下载 ZIP 并解压到新文件夹。不要解压覆盖到旧安装上。
2. 在新文件夹中运行 `install.bat`。
3. 运行 `start.bat`。
4. 继续使用该文件夹。ZIP 安装没有 Git 元数据，因此 `update.bat` 无法更新它们。

### 命令

```text
start.bat        启动应用与引擎
stop.bat         停止应用与引擎
update.bat       更新 Git 安装
healthcheck.bat  检查路径与服务
start_engine.bat 仅启动 ComfyUI
stop_engine.bat  仅停止 ComfyUI
```

默认安装 FFmpeg。最小化安装可以使用 `-SkipFfmpeg`，但 Timeline 导出和拼接将无法工作。`install.bat` 还会创建带应用图标的 `WAIFUSTUDIO.lnk`；如果移动了文件夹，请运行 `scripts\create_shortcut.ps1` 或重新运行安装程序。

## 更新

### Git 安装

`update.bat` 会停止应用，将 `data/` 和 `ComfyUI/user/` 备份到 `%LOCALAPPDATA%\WaifuStudio\backups\update-<date>`，执行 `git pull --ff-only`，重新运行安装程序，然后再次启动应用。

更新之前：

- 完成或取消 ComfyUI 中活动的任务。
- 如果 `git status --short` 显示已跟踪的改动，请提交或保存它们。更新程序会拒绝覆盖这些改动。

常规更新：

```powershell
update.bat
```

先检查，不做任何改动：

```powershell
update.bat -DryRun
```

常用变体：

```powershell
update.bat -NoStart        # 更新但不打开应用
update.bat -InstallModels  # 同时下载缺失的模型
```

默认情况下它不会下载新模型。如果仓库存在已跟踪的本地改动、当前分支不是 `main`，或者 ComfyUI 仍有活动任务，它会拒绝运行。`install.bat -Update` 是 `update.bat` 的别名。

### ZIP 安装

ZIP 安装没有原地更新程序。请手动更新：

1. 用 `stop.bat` 停止应用。
2. 备份 `data/`、`ComfyUI/user/`、`.env` 和 `config.local.json`(如果存在)。除非打算重新下载模型，否则也请备份 `ComfyUI/models/`。
3. 将新的 ZIP 解压到新文件夹。
4. 将旧文件夹中的 `data/`、`ComfyUI/user/`，以及你保留下来的 `ComfyUI/models/`，复制到新文件夹。
5. 在新文件夹中运行 `install.bat`。
6. 启动它，确认图库和项目后再删除旧文件夹。

Git 更新程序会留下一个带时间戳的备份。请保留它，直到新版本经过测试。

当前图标是临时的。源文件是 `waifystudioicon.ico`；应用提供 `static/favicon.ico`，README 使用 `static/waifustudio-icon.png`。

## 添加图像模型与 LoRA

仓库不包含第三方 checkpoint 或 LoRA。安装程序会下载初始模型集；其他文件需要手动复制。目前应用内没有模型浏览器。

### 文件存放位置

| 资源 | 文件夹 | 格式 | 说明 |
|---|---|---|---|
| SDXL checkpoint | `ComfyUI/models/checkpoints/` | `.safetensors` | 包含 CLIP 与 VAE。Illustrious、Pony 和 NoobAI 风格的 SDXL checkpoint 都使用此路径。 |
| Anima 2.9B UNET | `ComfyUI/models/diffusion_models/` | `.safetensors` | 需要下方列出的 Anima 文本编码器与 VAE。 |
| Anima LoRA | `ComfyUI/models/loras/anima/` | `.safetensors` | 子文件夹可选，但有助于识别系列。 |
| SDXL 系 LoRA | `ComfyUI/models/loras/sdxl/` | `.safetensors` | 仅可与 SDXL/Illustrious checkpoint 搭配使用。 |
| Anima 文本编码器 | `ComfyUI/models/text_encoders/` | `.safetensors` | 预期名称：`qwen_3_06b_base.safetensors`。 |
| Anima VAE | `ComfyUI/models/vae/` | `.safetensors` | 预期名称：`qwen_image_vae.safetensors`。 |

请使用 `.safetensors`。自动扫描器只登记 `.safetensors` 文件；`.ckpt` 和 `.pt` 文件不会被识别。

### 下载与安装

1. 从模型的官方页面下载，通常是 Civitai 或 Hugging Face。
   - 在 Civitai 上，使用 **Model** 或 **LoRA** 下载，而不是 workflow、预览图或训练数据。
   - 在 Hugging Face 上，进入 **Files and versions** 并下载 `.safetensors` 文件。
   - 有年龄限制的模型需要账户并接受其条款。
2. 将文件复制到表格中对应的文件夹。
3. 如果使用 Anima，请保持所需的 Anima 编码器/VAE 名称不变。
4. 打开应用，点击图像标签页中的**刷新**按钮，或调用 `GET /api/models?scan=1`。
5. 打开**选择 LoRA → 管理库**注册 LoRA，或让扫描器通过 `POST /api/loras/scan` 找到它。
6. 选择模型，先运行一张小测试图，再在项目中使用。

子文件夹会被递归扫描。将 LoRA 按 `loras/anima/...` 和 `loras/sdxl/...` 组织是可选的，但当文件元数据无法识别其基础模型时会很有用。

### 兼容的图像系列

| 系列 | 兼容 | 说明 |
|---|---|---|
| **Anima 2.9B** | 是 | 主要的原生系列。28-block 模型是稳妥的目标。存在 40-block 变体，但并非每个 28-block LoRA 都能顺利适配。 |
| **SDXL** | 是 | 自带 CLIP 与 VAE 的 checkpoint。 |
| **Illustrious** | 是 | SDXL 架构；按 SDXL checkpoint 处理。 |
| **Pony** | 是 | SDXL 架构；prompt 约定不同。 |
| **NoobAI 风格 SDXL** | 是 | SDXL 架构；prompt 约定不同。 |
| **SD 1.5 / SD 2.1** | 否 | 未验证；应用假定使用 SDXL 的默认值和加载器。 |
| **Flux、Qwen-Image 及其他架构** | 否 | 图像标签页是为 Anima 和 SDXL 构建的。Qwen-Image 属于编辑器，而不是这个标签页。 |

### 兼容的 LoRA

- **Anima LoRA** 搭配 Anima UNET。
- **SDXL/Illustrious/Pony LoRA** 搭配 SDXL checkpoint。
- 不要混用系列。为 Anima 训练的 LoRA 在 SDXL 上无法正常工作，反之亦然。
- H3 和 Wan 的 LoRA 属于视频工作流，而不是图像标签页。
- 应用会尝试从 LoRA 元数据中读取 trigger。如果缺失，请在库中手动输入 trigger。
- 风格 LoRA 的权重可从 `0.6–0.8` 左右起步，角色 LoRA 从 `0.8–1.0` 起步。之后再按需调整。

### 此界面无法添加的内容

- ControlNet、IP-Adapter、textual inversion 和 embeddings 未在图像标签页中开放。
- 没有单独的 VAE 选择器；Anima 使用固定的编码器/VAE 组合，而 SDXL checkpoint 自带 VAE。
- Upscaler 文件是一份独立且固定的清单。将新的 `.pth` 复制到 `upscale_models` 并不会把它加入 Upscaler 下拉菜单。
- H3 视频模型和预设不能通过把文件放进 `checkpoints` 来安装。

发布生成作品前，请检查模型许可。Anima 模型为非商业用途；SDXL 和 Civitai 模型各有自己的条款。

## 参考配置

以下是开发和验证所用的硬件与软件。它们不是最低要求。

| 组件 | 参考 |
|---|---|
| GPU | NVIDIA GeForce RTX 3060，12 GB |
| CPU | AMD Ryzen 7 5700X，8 核 |
| RAM | 32 GB DDR4 |
| 操作系统 | Windows 10 64 位 |
| 引擎 | ComfyUI v0.37.4 |
| Python | CPython 3.12.12，隔离环境 |
| 推理 | PyTorch 2.11.0 + CUDA 13.0 |

这些工作流针对 12 GB 显存预算和单任务运行做了调优。可选的 Qwen3.5-9B 助手运行在 CPU 上，因此不会占用 ComfyUI 的显存。

Windows 和 Linux 均受支持。核心是标准 FastAPI、ComfyUI 和原生 JavaScript；Linux 本地安装：`install-linux.sh`（见 `docs/linux.md`）。Linux 服务器/局域网模式仍在计划中。

## 当前限制

- 单 GPU、FIFO 队列。长任务在完成前会阻塞其他标签页。
- H3 生成的是短片段：每次生成 15 秒，在支持的情况下可链式输出。
- 原生视频放大功能一次处理一批，并拒绝超过 300 帧的视频。长视频需要外部工具。
- Timeline 有意保持精简：目前还没有播放头、裁剪手柄、拖放或波形编辑。
- 本版本没有口型同步(lip-sync)，也没有自动配音。
- 尚未集成云端推理、远程 GPU 租用或模型市场。
- 应用内指南正在修订；可用功能请以 README 和实际 UI 为准。

## 路线图

以下条目处于计划中或评估中。它们不是承诺，也没有时间表；除非明确说明，否则尚不可用。

### 近期

- **按显存划分的模型预设**和经过验证的模型管理器，让安装不再假定使用 12 GB 显卡。
- **Linux Studio 模式**：面向本地网络的无头服务器，与单用户 Windows 应用分离。
- **远程 ComfyUI/GPU 支持**，配合持久化的模型卷，让长任务不再依赖本地 GPU。
- **本地 agent 工具**：可通过 API 驱动应用的 CLI、skill 和 DSH 模式。
- **Timeline 场景队列**，以及支持任务续跑的脚本到场景导演功能。

### 评估中

- **Chatterbox 旁白**，用于西班牙语配音，可选的口型同步作为单独步骤。
- **Video2X 集成**，用于长视频放大，仍作为外部工具保留，而不会并入 ComfyUI。
- **Wan 2.2 工作流配置**，包括归功于 Artelive 的社区工作流库。
- **Civitai 模型浏览器/下载器**，受 API 限制、许可和年龄限制内容规则约束。
- **LTX 2.5**：已评估，但以其当前形态在 12 GB GPU 上并不实用。
- **Timeline NLE 改进**：播放头、裁剪、拖放和波形。

## 开发

2.0 版本是对原始应用的一次稳定性与文档梳理。修复工作、测试工作以及面向 agent 的基础工作，借助 **DSH** 与 **DeepSeek V4.1 Flash 1017** 继续推进。

离线测试套件目前运行 1,614 项测试。README 描述的是应用的现状；仅处于计划中的功能列在路线图下。

## 支持

开发是独立的，应用继续保持 MIT 许可。如果你想支持投入在测试、文档和维护上的时间，可以访问 Patreon 页面：

https://www.patreon.com/gusnion

支持是可选的，不会解锁或限制应用的任何部分。

## 许可证与致谢

- 以 **MIT 许可证**发布。不提供任何担保。
- 构建在 ComfyUI、MiniMax H3 VDN、Anima、Qwen 和 FFmpeg 之上。
- **Wan 2.2 工作流研究与 8 GB 工作流库**：Artelive(社区贡献；集成待定)。
