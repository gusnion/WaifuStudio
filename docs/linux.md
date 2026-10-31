# WaifuStudio on Linux

WaifuStudio runs natively on Linux. The Windows `install.bat` is not used; use
`install-linux.sh` from the repository root instead.

The Linux path was validated on Ubuntu 24.04 x86_64 with an NVIDIA RTX 5000 Ada
(32 GB), driver 590 / CUDA 13.1, ComfyUI v0.42.5 and torch 2.11.0+cu130.

## Requirements

- Ubuntu 22.04 or 24.04 x86_64. Other distributions work if you install the
  equivalent packages (`git`, `curl`, `rsync`, `tmux`, `ffmpeg`, OpenGL libs).
- NVIDIA GPU with 8–12 GB VRAM or more (reference: RTX 3060 12 GB).
- NVIDIA driver 570+; the stack uses CUDA 13 (`torch 2.11.0+cu130`).
  CUDA 13.0+ host drivers are recommended.
- 25 GB free for the app + engine + LLM. About 150 GB if you download the full
  recommended model set.
- `sudo` for the system packages, unless you run as root.
- Git clone of this repository. ZIP installs are not supported by the Linux
  script.

## Install

```bash
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
./install-linux.sh
```

This installs the app dependencies, ComfyUI v0.42.5 at the pinned commit, the
pinned custom nodes, FFmpeg and torch cu130. It does not download image models
by default.

Optional components:

```bash
# 3 recommended checkpoints + RealESRGAN x2
WITH_MODELS=1 ./install-linux.sh

# Local LLM: llama.cpp CPU + Qwen3.5-9B + mmproj
WITH_LLM=1 ./install-linux.sh

# WD14 tagger for fast image tags (Vision)
WITH_VISION=1 ./install-linux.sh

# Everything
WITH_MODELS=1 WITH_LLM=1 WITH_VISION=1 ./install-linux.sh
```

The installer is idempotent. It never overwrites `data/`, `ComfyUI/models/` or
your gallery.

If you cloned into a different directory, either run the script from there or
set `WAIFU_ROOT`:

```bash
WAIFU_ROOT=/opt/WaifuStudio ./install-linux.sh
```

## Start and stop

```bash
./start-linux.sh
# open http://127.0.0.1:8765

./stop-linux.sh
```

`start-linux.sh` starts ComfyUI on `127.0.0.1:8288` and the app on
`127.0.0.1:8765`, writes logs to `data/logs/` and PID files to `data/run/`.
Use `./start-linux.sh --no-browser` on a headless machine.

Diagnostics:

```bash
./healthcheck.sh
# or, with the engine required:
./healthcheck.sh --require-engine
```

Logs:

- `data/logs/app.log`
- `data/logs/engine.log`
- `data/llm-server.log` (managed LLM)

## Access from another machine

Both services listen on loopback only. Use an SSH tunnel instead of exposing
the ports:

```bash
ssh -L 8765:127.0.0.1:8765 user@linux-host
# then open http://127.0.0.1:8765 locally
```

Do not expose `8765` or `8288` to the network: the app has no authentication.

## Models

The image checkpoints are not redistributed. `WITH_MODELS=1` downloads the
recommended set from their public sources and verifies SHA256.

Wan 2.2 (video) has a separate helper:

```bash
./download-wan.sh
```

It downloads the Wan 2.2 14B Rapid AllInOne NSFW v10 Q4_K_M GGUF, the UMT5 text
encoders, the Wan 2.1 VAE and the NSFW-22-H-e8 LoRA, verifying size and SHA256.

WD14 tags:

```bash
./download-wd14.sh
```

Check every model license before commercial use. Outputs inherit the
restrictions of the model that produced them.

## Update

```bash
git pull
./install-linux.sh
```

The installer skips what is already installed and keeps `data/` and
`ComfyUI/models/`.

## Troubleshooting

**`torch.cuda.is_available() == False`**
Check `nvidia-smi` and update the NVIDIA driver. The pinned torch build uses
CUDA 13. Host CUDA 12.8 machines need a different torch build.

**Port 8288 or 8765 already in use**
Stop the previous instance with `./stop-linux.sh`, or identify the process with
`ss -ltnp | grep -E '8288|8765'`.

**The app opens but ComfyUI does not answer**
Check `data/logs/engine.log`. A first start can take 10–30 seconds while custom
nodes import.

**Video generation fails with `value_not_in_list`**
The Wan model files are missing or in the wrong directory. Run
`./download-wan.sh` and restart ComfyUI (`./stop-linux.sh && ./start-linux.sh`).

**LLM caption fails or is slow**
The managed LLM is CPU-only (`-ngl 0`). The first caption loads the model and
can take 1–2 minutes; later calls are faster. Check `data/llm-server.log` and
`./healthcheck.sh --require-llm`.

**`WD14 no instalado`**
Run `WITH_VISION=1 ./install-linux.sh` or `./download-wd14.sh`.

## Linux-specific changes

The Linux port keeps the same FastAPI app and ComfyUI engine. The relevant
differences are:

- POSIX path normalization for model and LoRA registry entries.
- `llama-server` (no `.exe`) and a Linux `manifest.llm.linux.json` runtime.
- `ffmpeg`/`ffprobe` are resolved from `PATH` when the portable Windows binaries
  are absent.
- "Open folder" uses `xdg-open` instead of Explorer.
- The Wan AIO workflow stores the LoRA path with `/` separators.
