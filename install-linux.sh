#!/usr/bin/env bash
# WaifuStudio — instalador Linux (Ubuntu 22.04/24.04 + GPU NVIDIA).
#
# Uso:
#   ./install-linux.sh
#   WITH_MODELS=1 WITH_LLM=1 WITH_VISION=1 ./install-linux.sh
#
# Variables:
#   WAIFU_ROOT    raiz del repo (por defecto, el directorio de este script)
#   WITH_MODELS=1 descarga los 3 checkpoints recomendados + RealESRGAN
#   WITH_LLM=1    instala llama.cpp CPU + Qwen3.5-9B + mmproj
#   WITH_VISION=1 instala onnxruntime + WD14 (tags rapidos)
#
# Idempotente: se puede relanzar; solo instala lo que falta. No sobrescribe
# data/ ni ComfyUI/models/.
set -euo pipefail

ROOT="${WAIFU_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
COMFY="$ROOT/ComfyUI"
PY="$ROOT/.venv/bin/python"
TORCH_INDEX="https://download.pytorch.org/whl/cu130"
WITH_LLM="${WITH_LLM:-0}"
WITH_MODELS="${WITH_MODELS:-0}"
WITH_VISION="${WITH_VISION:-0}"

step() { echo; echo "===== [$(date +%H:%M:%S)] $* ====="; }
warn() { echo "WARN: $*"; }

if [ ! -d "$ROOT/app" ]; then
  echo "ERROR: ejecuta este script desde un clon git de WaifuStudio (o define WAIFU_ROOT)." >&2
  exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

step "preflight"
if ! command -v nvidia-smi >/dev/null 2>&1; then
  warn "nvidia-smi no encontrado. torch cu130 necesita un driver NVIDIA reciente (570+/CUDA 13)."
fi
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq git curl rsync tmux ffmpeg libgl1 libglib2.0-0 build-essential >/dev/null
else
  warn "apt-get no encontrado; instala manualmente git curl rsync tmux ffmpeg y las libs de OpenGL."
fi

if ! command -v uv >/dev/null 2>&1; then
  step "uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
UV="$(command -v uv)" || { echo "ERROR: uv no disponible" >&2; exit 1; }

step "repositorio"
if [ ! -d "$ROOT/.git" ]; then
  warn "el repo no tiene .git; se usara el arbol actual (instalacion tipo ZIP)."
else
  git -C "$ROOT" fetch --all --tags --force || true
fi

step "Python + dependencias de la app"
if [ ! -x "$PY" ]; then
  "$UV" python install 3.12.12 || true
  "$UV" venv --python 3.12.12 "$ROOT/.venv" || "$UV" venv --python 3.12 "$ROOT/.venv"
fi
"$UV" pip install --python "$PY" -r "$ROOT/requirements.txt" -r "$ROOT/requirements-dev.txt"

step "ComfyUI v0.42.5 pinneado"
if [ ! -d "$COMFY/.git" ]; then
  git clone --branch v0.42.5 --depth 1 https://github.com/Comfy-Org/ComfyUI.git "$COMFY"
fi
git -C "$COMFY" fetch --all --tags --force
git -C "$COMFY" checkout --force 483dae4326356b81de05d27aca3f433dd323cc25
HEAD="$(git -C "$COMFY" rev-parse HEAD)"
[ "$HEAD" = "483dae4326356b81de05d27aca3f433dd323cc25" ] || { echo "ComfyUI HEAD incorrecto: $HEAD" >&2; exit 1; }
"$UV" pip install --python "$PY" -r "$COMFY/requirements.txt"

step "custom nodes pinneados"
install_node() {
  local id="$1" url="$2" commit="$3" dir="$COMFY/custom_nodes/$1"
  echo "-- $id @ $commit"
  if [ ! -d "$dir/.git" ]; then
    rm -rf "$dir"
    git clone "$url" "$dir"
  fi
  git -C "$dir" fetch --all --tags --force || true
  git -C "$dir" checkout --force "$commit"
  local got; got="$(git -C "$dir" rev-parse HEAD)"
  [ "$got" = "$commit" ] || { echo "ERROR: $id HEAD $got != $commit" >&2; return 1; }
  if [ -f "$dir/requirements.txt" ]; then
    "$UV" pip install --python "$PY" -r "$dir/requirements.txt" || warn "requirements de $id fallaron"
  elif [ -f "$dir/requirements-no-cupy.txt" ]; then
    "$UV" pip install --python "$PY" -r "$dir/requirements-no-cupy.txt" || warn "requirements de $id fallaron"
  fi
}

install_node "ComfyUI-GGUF" "https://github.com/leejet/ComfyUI-GGUF.git" "373048b8403a7820620065210a691263d4da0a61"
install_node "ComfyUI-KJNodes" "https://github.com/kijai/ComfyUI-KJNodes.git" "d3cfe21625e5170126ce06fbfcfe1d88108688c3"
install_node "ComfyUI-Frame-Interpolation" "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git" "26545cc2dd95bc3d27f056016300673bdeee78f5"
install_node "ComfyUI-ClipProj" "https://github.com/nicolab28/ComfyUI-ClipProj.git" "c01ba8fb8f41b4f2094dbd0b185cdc238fb6134c"
install_node "ComfyUI-VDN-H3-Plus" "https://github.com/xmarre/ComfyUI-VDN-H3-Plus.git" "f0dec6c1f64d5e0e96f1fa191ff3e7abba9df3f0"
install_node "ComfyUI-VideoHelperSuite" "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git" "4d907bee61e92c2e65af3bd6383a4e4d356126d1"
install_node "ComfyUI-MMAudio" "https://github.com/kijai/ComfyUI-MMAudio.git" "8eaeb72edc3aaf2059b57f2d96a1f6f689f19ae2"

step "nodo local waifu_anima_patch"
if [ -d "$ROOT/tools/custom_nodes/waifu_anima_patch" ] && [ ! -d "$COMFY/custom_nodes/waifu_anima_patch" ]; then
  cp -a "$ROOT/tools/custom_nodes/waifu_anima_patch" "$COMFY/custom_nodes/"
fi

step "torch 2.11.0 + CUDA 13.0"
"$UV" pip install --python "$PY" \
  "torch==2.11.0+cu130" "torchvision==0.26.0+cu130" "torchaudio==2.11.0+cu130" \
  --index-url "$TORCH_INDEX"

step "verificacion"
"$PY" - <<'PY'
import torch, torchvision, torchaudio
print("torch", torch.__version__)
print("torchvision", torchvision.__version__)
print("torchaudio", torchaudio.__version__)
print("cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0))
    print("vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1))
PY

if [ "$WITH_LLM" = "1" ]; then
  step "LLM local (Qwen3.5-9B + llama.cpp CPU)"
  "$PY" "$ROOT/scripts/download_llm.py"
fi

if [ "$WITH_MODELS" = "1" ]; then
  step "modelos de imagen recomendados + RealESRGAN"
  CKPT="$COMFY/models/checkpoints"
  UP="$COMFY/models/upscale_models"
  mkdir -p "$CKPT" "$UP"
  fetch() {
    local dest="$1" url="$2" sha="$3"
    if [ -f "$dest" ] && echo "$sha  $dest" | sha256sum -c - >/dev/null 2>&1; then
      echo "ya presente: $dest"
      return 0
    fi
    curl -L --fail --retry 5 -C - -o "$dest.part" "$url"
    echo "$sha  $dest.part" | sha256sum -c -
    mv "$dest.part" "$dest"
  }
  fetch "$CKPT/animagine-xl-4.0-opt.safetensors" \
    "https://huggingface.co/cagliostrolab/animagine-xl-4.0/resolve/2b7c1b397761bf5bd3cc42e5b39ec99314a75a96/animagine-xl-4.0-opt.safetensors" \
    "6327eca98bfb6538dd7a4edce22484a1bbc57a8cff6b11d075d40da1afb847ac"
  fetch "$CKPT/realvisxlV50_v50Bakedvae_full_fp16.safetensors" \
    "https://civitai.com/api/download/models/789646" \
    "6A35A7855770AE9820A3C931D4964C3817B6D9E3C6F9C4DABB5B3A94E5643B80"
  fetch "$CKPT/juggernautXL_ragnarok.safetensors" \
    "https://civitai.com/api/download/models/1759168" \
    "DD08FA32F98D05A2443CA1419E46DF1575A0811F6E3B246D9DD47FF20F5EB66A"
  fetch "$UP/RealESRGAN_x2.pth" \
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth" \
    "49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb"
  if [ ! -f "$ROOT/data/registry/models.json" ]; then
    "$PY" - "$ROOT" <<'PY2'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
rec = json.loads((root / "registry" / "recommended-v1.json").read_text(encoding="utf-8"))
ids = {"animagine-xl-4-opt", "realvisxl-v50", "juggernaut-xl-ragnarok"}
models = [m for m in rec["models"] if m.get("id") in ids]
out = root / "data" / "registry" / "models.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"version": 1, "models": models}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"registry de usuario: {len(models)} modelos")
PY2
  fi
fi

if [ "$WITH_VISION" = "1" ]; then
  step "WD14 tagger para Vision"
  "$UV" pip install --python "$PY" onnxruntime
  W="$COMFY/models/wd14"
  mkdir -p "$W"
  fetch_vision() {
    local dest="$1" url="$2" sha="$3"
    if [ -f "$dest" ] && echo "$sha  $dest" | sha256sum -c - >/dev/null 2>&1; then
      echo "ya presente: $dest"
      return 0
    fi
    curl -L --fail --retry 5 -C - -o "$dest.part" "$url"
    echo "$sha  $dest.part" | sha256sum -c -
    mv "$dest.part" "$dest"
  }
  fetch_vision "$W/wd-v1-4-convnext-tagger-v2.onnx" \
    "https://huggingface.co/SmilingWolf/wd-v1-4-convnext-tagger-v2/resolve/main/model.onnx" \
    "71f06ecb7b9df81d8f271da4d43997ea2ed363cdac29aa64fcb256c9631e656a"
  fetch_vision "$W/wd-v1-4-convnext-tagger-v2.csv" \
    "https://huggingface.co/SmilingWolf/wd-v1-4-convnext-tagger-v2/resolve/main/selected_tags.csv" \
    "8c8750600db36233a1b274ac88bd46289e588b338218c2e4c62bbc9f2b516368"
fi

echo
echo "===== INSTALACION COMPLETA ====="
echo "Arranca con:  ./start-linux.sh"
echo "Abre:         http://127.0.0.1:8765"
