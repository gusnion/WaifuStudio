# WaifuStudio v2.1 — Local Anime Production Studio

<p align="center">
  <img src="static/waifustudio-icon.png" width="112" alt="WaifuStudio icon">
</p>

[![Version](https://img.shields.io/badge/version-2.1.0-ff4081.svg)](https://github.com/gusnion/WaifuStudio)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Reference GPU](https://img.shields.io/badge/Reference%20GPU-RTX%203060%2012GB-76b900.svg)](https://www.nvidia.com)
[![Engine](https://img.shields.io/badge/Engine-ComfyUI%20Backend-orange.svg)](https://github.com/comfyanonymous/ComfyUI)
[![Local by default](https://img.shields.io/badge/Local-by%20default-success.svg)]()
[![Patreon](https://img.shields.io/badge/Patreon-gusnion-ff424d.svg)](https://www.patreon.com/gusnion)

> English | [Español](README.es.md) | [日本語](README.ja.md) | [中文](README.zh.md) | [Русский](README.ru.md)

WaifuStudio is a local-first production workspace for anime images and short video. It brings image generation, character references, video generation, editing, upscaling, timeline assembly and gallery management into one web interface, with ComfyUI as the inference engine.

## Languages

The interface is available in **English (default)**, **Spanish**, **Japanese**, **Simplified Chinese** and **Russian**. Use the globe button in the top bar to switch. Technical model names, prompt examples, user content and some backend error messages remain in their original language.

The application is designed around a single NVIDIA GPU and a Windows desktop. It does not require an account, a cloud service or telemetry. The installer keeps Python, ComfyUI and FFmpeg in a portable directory.

> [!WARNING]
> **Status and scope**: this is an independent project provided "as is", without warranties. It is developed and tested around the reference configuration below. Other GPUs, operating systems and workflows may work, but are not officially validated. Expect rough edges, and keep backups of your projects and generated media.

## What is included

| Module | Status | What it does |
|---|---|---|
| **Windows installer** | Available | Sets up a portable Python environment, ComfyUI, custom nodes, models, FFmpeg/FFprobe and the app shortcut. |
| **Image and OC Maker** | Available | Animagine XL 4.0 Opt, RealVisXL V5 and Juggernaut XL Ragnarok (SDXL), prompt zones, LoRA selection, character profiles, reference images and optional LoRA training. |
| **Prompt assistant** | Available | Local Danbooru tag index plus an optional CPU LLM for prompt expansion and image captioning. |
| **Wan 2.2 video** | Available | I2V and FLF2V with Wan 2.2 A14B Q4_K_S, LightX2V, Fast (4 steps) and Quality (30 steps) profiles, plus MMAudio audio. |
| **Editor** | Available | Instruction-based editing with Qwen-Image 2.1, up to ten reference images and L0–L3 pose presets. Mask-based inpainting is not part of this version. |
| **Timeline** | Available | Arrange clips and still images, set duration, apply fade/zoom, mute clips, add external audio, continue a clip with I2V/FLF2V and export MP4. It is a focused sequencer, not a full NLE. |
| **Upscaler** | Available | Image upscaling with GAN, Hires Fix and Qwen Remaster modes, plus RCAS/Adaptive USM sharpening and RIFE interpolation. Video upscaling is limited to 300 frames per job. |
| **Gallery and queue** | Available | SQLite-backed gallery, job history and a single-GPU FIFO queue shared by all tabs. |

## Installation (Windows)

### Before starting

- Windows 10/11 64-bit.
- NVIDIA GPU; the reference machine uses an RTX 3060 with 12 GB.
- NVIDIA driver 570 or newer (the stack uses CUDA 13).
- Git for Windows if you want automatic updates. ZIP installs work without Git.
- Enough free disk space for the model set. The installer shows the size and asks before downloading.
- A short local path is safer than a synced folder, for example `C:\AI\WaifuStudio`.
- If an older copy is running, stop it first with `stop.bat`.

### Option A: Git clone (recommended)

1. Clone the repository:

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
```

2. Install:

```powershell
install.bat
```

The installer creates the isolated Python environment, ComfyUI, the custom nodes, FFmpeg and the shortcut. It also asks which models to download. Re-running it is safe: it verifies what already exists and only installs what is missing.

3. Start the app:

```powershell
start.bat
```

It opens `http://127.0.0.1:8765` in a dedicated window.

4. Stop or diagnose it:

```powershell
stop.bat
healthcheck.bat
```

If the models are already on disk and you only need the engine and app:

```powershell
install.bat -SkipModels
```

Do not use `-SkipModels` for a first install if you still need the recommended models.

### Option B: ZIP

1. Download the ZIP and extract it to a new folder. Do not extract it over an old installation.
2. Run `install.bat` inside the new folder.
3. Run `start.bat`.
4. Keep using that folder. ZIP installations do not have Git metadata, so `update.bat` cannot update them.

### Commands

```text
start.bat        start the app and engine
stop.bat         stop the app and engine
update.bat       update a Git installation
healthcheck.bat  check paths and services
start_engine.bat start only ComfyUI
stop_engine.bat  stop only ComfyUI
```

FFmpeg is installed by default. `-SkipFfmpeg` is available for minimal installs, but Timeline export and concatenation will not work. `install.bat` also creates `WAIFUSTUDIO.lnk` with the application icon; if the folder is moved, run `scripts\create_shortcut.ps1` or re-run the installer.

## Updating

### Git installation

`update.bat` stops the app, saves `data/` and `ComfyUI/user/` under `%LOCALAPPDATA%\WaifuStudio\backups\update-<date>`, runs `git pull --ff-only`, re-runs the installer and starts the app again.

Before updating:

- Finish or cancel active ComfyUI jobs.
- If `git status --short` shows tracked changes, commit or save them. The updater refuses to overwrite them.

Normal update:

```powershell
update.bat
```

Check first without changing anything:

```powershell
update.bat -DryRun
```

Useful variants:

```powershell
update.bat -NoStart        # update without opening the app
update.bat -InstallModels  # also download missing models
```

By default it does not download new models. It refuses to run if the repository has tracked local changes, if the current branch is not `main`, or if ComfyUI still has active jobs. `install.bat -Update` is an alias for `update.bat`.

### ZIP installation

There is no in-place updater for ZIP installs. Update manually:

1. Stop the app with `stop.bat`.
2. Back up `data/`, `ComfyUI/user/`, `.env` and `config.local.json` if they exist. Back up `ComfyUI/models/` too unless you plan to download the models again.
3. Extract the new ZIP into a new folder.
4. Copy `data/`, `ComfyUI/user/` and, if you kept them, `ComfyUI/models/` from the old folder into the new one.
5. Run `install.bat` in the new folder.
6. Start it and verify the gallery and projects before removing the old folder.

The Git updater leaves a timestamped backup. Keep it until the new version has been tested.

The current icon is provisional. The source is `waifystudioicon.ico`; the app serves `static/favicon.ico` and the README uses `static/waifustudio-icon.png`.

## Adding image models and LoRAs

The repository does not include third-party checkpoints or LoRAs. The installer downloads the starter set; additional files are copied manually. There is no in-app model browser yet.

### Where files go

| Asset | Folder | Format | Notes |
|---|---|---|---|
| SDXL checkpoint | `ComfyUI/models/checkpoints/` | `.safetensors` | Official set: `animagine-xl-4.0-opt`, `realvisxlV50_v50Bakedvae_full_fp16`, `juggernautXL_ragnarok`. |
| Wan 2.2 DiT | `ComfyUI/models/diffusion_models/` | `.gguf` | High/Low `Q4_K_S`; workflow uses GGUF. |
| Wan text encoder | `ComfyUI/models/text_encoders/` | `.gguf` | `umt5-xxl-encoder-Q5_K_M.gguf`. |
| Wan VAE | `ComfyUI/models/vae/` | `.safetensors` | `wan_2.1_vae.safetensors`. |
| Wan LightX2V LoRA | `ComfyUI/models/loras/` | `.safetensors` | `wan22_lightx2v_high/low.safetensors`. |
| MMAudio | `ComfyUI/models/mmaudio/` | `.safetensors` | Cuatro archivos del manifiesto Wan. |

Use `.safetensors`. The automatic scanner only registers `.safetensors` files; `.ckpt` and `.pt` files are not picked up.

### Download and install

1. Download the model from its official page, normally Civitai or Hugging Face.
   - On Civitai, use the **Model** or **LoRA** download, not the workflow, preview or training data.
   - On Hugging Face, use **Files and versions** and download the `.safetensors` file.
   - Age-gated models require an account and acceptance of their terms.
2. Copy the file into the matching folder from the table.
3. Keep the required Anima encoder/VAE names unchanged if you use Anima.
4. Open the app and press the **reload** button in the Image tab, or call `GET /api/models?scan=1`.
5. Open **Elegir LoRAs → Gestionar biblioteca** to register a LoRA, or let the scanner find it with `POST /api/loras/scan`.
6. Select the model and run a small test image before using it in a project.

Subfolders are scanned recursively. Organizing LoRAs as `loras/anima/...` and `loras/sdxl/...` is optional but useful when the file metadata does not identify its base model.

### Compatible image families

| Family | Compatible | Notes |
|---|---|---|
| **Anima 2.9B** | Yes | The main native family. 28-block models are the safe target. 40-block variants exist, but not every 28-block LoRA transfers cleanly. |
| **SDXL** | Yes | Checkpoint with its own CLIP and VAE. |
| **Illustrious** | Yes | SDXL architecture; treated as an SDXL checkpoint. |
| **Pony** | Yes | SDXL architecture; prompt conventions differ. |
| **NoobAI-style SDXL** | Yes | SDXL architecture; prompt conventions differ. |
| **SD 1.5 / SD 2.1** | No | Not validated; the app assumes SDXL defaults and loaders. |
| **Flux, Qwen-Image and other architectures** | No | The Image tab is built for Anima and SDXL. Qwen-Image belongs to the Editor, not this tab. |

### Compatible LoRAs

- **Anima LoRA** with an Anima UNET.
- **SDXL/Illustrious/Pony LoRA** with an SDXL checkpoint.
- Do not mix families. A LoRA trained for Anima will not work correctly on SDXL, and vice versa.
- Wan LoRAs belong to video workflows, not the Image tab.
- The app tries to read the trigger from the LoRA metadata. If it is missing, enter the trigger manually in the library.
- Start with a weight around `0.6–0.8` for style LoRAs and `0.8–1.0` for character LoRAs. Adjust from there.

### What is not addable from this screen

- ControlNet, IP-Adapter, textual inversion and embeddings are not exposed in the Image tab.
- There is no separate VAE selector; Anima uses its fixed encoder/VAE pair, and SDXL checkpoints carry their own.
- Upscaler files are a separate, fixed catalog. Copying a new `.pth` into `upscale_models` does not add it to the Upscaler dropdown.
- Wan video models (DiT, encoder and VAE) are not installed by dropping files into `checkpoints`; use the paths in the asset table.

Check the model license before publishing generated work. The Anima models are non-commercial; SDXL and Civitai models have their own terms.

## Reference configuration

These are the hardware and software used for development and validation. They are not minimum requirements.

| Component | Reference |
|---|---|
| GPU | NVIDIA GeForce RTX 3060, 12 GB |
| CPU | AMD Ryzen 7 5700X, 8 cores |
| RAM | 32 GB DDR4 |
| OS | Windows 10 64-bit |
| Engine | ComfyUI v0.42.5 |
| Python | CPython 3.12.12, isolated |
| Inference | PyTorch 2.11.0 + CUDA 13.0 |

The workflows are tuned for a 12 GB budget and one job at a time. The optional Qwen3.5-9B assistant runs on CPU so it does not take VRAM from ComfyUI.

Windows is the supported installation path. The core is standard FastAPI, ComfyUI and vanilla JavaScript; a Linux server/LAN mode is planned but not available yet.

## Current limits

- Single GPU, FIFO queue. Long jobs block the other tabs until they finish.
- Wan produces 5-second segments at 16 fps; extend a clip through the Timeline.
- The native video upscaler processes one batch and rejects videos over 300 frames. Long videos need an external tool.
- The Timeline is intentionally small: no playhead, trim handles, drag-and-drop or waveform editing yet.
- No lip-sync and no automatic voice-over in this version.
- No cloud inference, remote GPU rental or model marketplace is integrated yet.
- The in-app Guide is being revised; treat the README and the actual UI as the source of truth for available features.

## Roadmap

The following items are planned or under evaluation. They are not promises, not dates, and not available unless explicitly stated.

### Near term

- **Model presets by VRAM** and a verified model manager, so installations do not assume a 12 GB card.
- **Linux Studio mode**: a headless server for the local network, separate from the single-user Windows app.
- **Remote ComfyUI/GPU support** with persistent model volumes, so long jobs do not depend on the local GPU.
- **Local agent tooling**: a CLI, a skill and a DSH mode that can drive the app through its API.
- **Timeline scene queue** and a script-to-scenes director with resumable jobs.

### Under evaluation

- **Chatterbox narration** for Spanish voice-over, with optional lip-sync as a separate step.
- **Video2X integration** for long video upscaling, kept as an external tool rather than folded into ComfyUI.
- **Wan 2.2 workflow profiles**, including the community workflow bank credited to Artelive.
- **Civitai model browser/downloader**, subject to API limits, licensing and age-gated content rules.
- **LTX 2.5**: evaluated, but not practical on a 12 GB GPU in its current form.
- **Timeline NLE improvements**: playhead, trimming, drag-and-drop and waveforms.

## Development

Version 2.0 is a stabilization and documentation pass over the original application. The remediation, test work and agent-oriented groundwork were continued with **DeepSeek V4.1 Flash 1017** using **DSH**.

The offline suite currently runs 1,641 tests. The README describes the app as it is; features that are only planned are listed under Roadmap.

## Support

Development is independent and the application remains MIT-licensed. If you want to support the time spent on testing, documentation and maintenance, there is a Patreon page:

https://www.patreon.com/gusnion

Support is optional and does not unlock or restrict any part of the application.

## License and credits

- Released under the **MIT License**. No warranties are provided.
- Built on top of ComfyUI, Wan 2.2, Qwen and FFmpeg.
- **Wan 2.2 workflow research and the 8 GB workflow bank**: Artelive (community contribution; Fast/Quality installed).
