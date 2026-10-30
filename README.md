# WaifuStudio 2.5.1 — Local Anime Production Studio

<p align="center">
  <img src="static/waifustudio-icon.png" width="112" alt="WaifuStudio icon">
</p>

[![Version](https://img.shields.io/badge/version-2.5.1-ff4081.svg)](https://github.com/gusnion/WaifuStudio)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Reference GPU](https://img.shields.io/badge/Reference%20GPU-RTX%203060%2012GB-76b900.svg)](https://www.nvidia.com)
[![Engine](https://img.shields.io/badge/Engine-ComfyUI-orange.svg)](https://github.com/comfyanonymous/ComfyUI)

> English | [Español](README.es.md) | [日本語](README.ja.md) | [中文](README.zh.md) | [Русский](README.ru.md)

WaifuStudio is a local-first workspace for anime images, characters, short video, audio and editing. It runs on Windows with one NVIDIA GPU and ComfyUI as the inference engine. There is no account, cloud service, telemetry or remote API.

## What it is

One web app for the full character pipeline:

1. Design a character or image.
2. Keep identity with references and OC profiles.
3. Generate short video, audio or edits.
4. Assemble the result in a timeline and export MP4.
5. Keep everything in a local gallery.

## Current state — 2.5.1

- **OC Maker redesigned:** create or generate an OC in a floating modal, edit traits directly with autosave, add local or gallery references (paginated), generate 4/6/8 multiviews from a chosen base image, duplicate, rename and delete with confirmation.
- **Complete trait catalog:** hair, eyes, face, body, outfit, expression, accessories, setting, action and meta; manual tags can be inserted at any time.
- **Image workflow:** natural-language SDXL models receive the prompt in the general field; tag-based models keep using prompt zones.
- **Offline verification:** `1880` tests OK, `1` skipped. No cloud account, telemetry or remote API.
- **Tag:** `v2.5.1` marks this state. Poses and “create sheet” actions were retired until ControlNet support exists.

## Tabs

| Tab | What it does |
|---|---|
| **Image** | Anima Aesthetic v1.1, Animagine XL 4.0 Opt, RealVisXL V5 and Juggernaut XL Ragnarok; prompt zones, `prompt_profile`, LoRA filtering and model/LoRA cards. |
| **Video** | Wan 2.2 I2V/FLF2V with Fast/Standard/Quality/Manual profiles. **Beta: VIDEO only.** Videos are silent; audio is generated separately. |
| **Editor** | Qwen-Image 2.1 editing with up to 10 references and a floating prompt panel. |
| **Audio** | Three steps: task/input, settings/generate, result. Voice (Irodori) or ambient (MMAudio), with stems and “send to Timeline”. |
| **Studio / Timeline** | Arrange clips and images, trim, fade, audio tracks, projects and MP4 export. |
| **Upscaler** | RealESRGAN image/video upscaling, local video input, chunked video jobs and RIFE interpolation. |
| **Gallery** | SQLite gallery with images, videos and audio; filters, preview, download and lineage. |
| **OC Maker** | Character library with create/generate modal, full trait catalog and manual tags, local/gallery references, 4/6/8 multiviews, duplicate/rename/delete and LoRA training entry. |

**Guide** and **Addons** live in the top bar. **Social** sits between language and Guide.

## Give this repository to your AI agent

The repo includes a complete manual written for agents:

- **[`SKILL.md`](SKILL.md)** — how to use the local HTTP API, install and register models, write LoRA entries, load recommended preprompts, download from Civitai and integrate a model without a workflow.
- **[`docs/agent-guides/`](docs/agent-guides/README.md)** — eight one-page recipes.

Tell your agent:

> “Read `SKILL.md` and `docs/agent-guides/`. Configure and run WaifuStudio following those instructions. Do not invent model names, triggers or paths.”

You can also open **Guide → Connect your AI agent** and use **Download SKILL.md**.

## Requirements

- Windows 10/11 64-bit.
- NVIDIA GPU with 8–12 GB VRAM (reference: RTX 3060 12 GB).
- Driver 570+ (the stack uses CUDA 13).
- Git for Windows (optional for ZIP installs).
- 25 GB free for app + engine + LLM; ~100 GB if you download the recommended model set. Models are downloaded separately.
- A short local path, for example `C:\AI\WaifuStudio`.

## Install in three steps

1. Download or clone the repository.
2. Run `install.bat`. It creates a portable Python environment, ComfyUI, FFmpeg and the app shortcut. Use `-SkipModels` to bring your own checkpoints.
3. Run `start.bat`, open `http://127.0.0.1:8765`, and follow the Guide.

The installer never overwrites `data/`, `ComfyUI/models/` or your gallery.

## Model set and licenses

The recommended set is Anima Aesthetic v1.1, Animagine XL 4.0 Opt, RealVisXL V5 and Juggernaut XL Ragnarok. Anima and some community models are **non-commercial**; Qwen-Image 2.1 is **research-only**; Wan 2.2 is Apache-2.0. The optional Wan NSFW AIO is a community merge with its own license.

**Check the license of every model before commercial use.** Outputs inherit the restrictions of the model that produced them. The app itself is MIT; ComfyUI and FFmpeg keep their own licenses.

## What is beta

Only **VIDEO** is beta. The rest of the tabs are production-ready for local use.

## Safety and scope

This is an independent project provided “as is”, without warranties. It is designed for adults and local, consensual fictional content. Do not expose ports `8765`/`8288` to the network. Keep backups of `data/`.

## Documentation

- [SKILL.md](SKILL.md) — agent manual.
- [docs/agent-guides/](docs/agent-guides/README.md) — short recipes.
- [AGENTS.md](AGENTS.md) — developer/agent rules for this repository.
- [CHANGELOG.md](CHANGELOG.md) — release notes.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — third-party components.
