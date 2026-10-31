#!/usr/bin/env bash
# WD14 tagger para Vision (tags rapidos). Requiere uv y el venv de WaifuStudio.
# Uso: ./download-wd14.sh [RAIZ_DEL_REPO]
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
cd "$ROOT"
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv no esta en PATH (lo instala install-linux.sh)" >&2
  exit 1
fi
uv pip install --python .venv/bin/python onnxruntime
D="$ROOT/ComfyUI/models/wd14"
mkdir -p "$D"
fetch() {
  local dest="$1" url="$2" sha="$3"
  if [ -f "$dest" ] && echo "$sha  $dest" | sha256sum -c - >/dev/null 2>&1; then
    echo "ya presente: $dest"; return 0
  fi
  curl -L --fail --retry 5 -C - -o "$dest.part" "$url"
  echo "$sha  $dest.part" | sha256sum -c -
  mv "$dest.part" "$dest"
}
fetch "$D/wd-v1-4-convnext-tagger-v2.onnx" \
  "https://huggingface.co/SmilingWolf/wd-v1-4-convnext-tagger-v2/resolve/main/model.onnx" \
  "71f06ecb7b9df81d8f271da4d43997ea2ed363cdac29aa64fcb256c9631e656a"
fetch "$D/wd-v1-4-convnext-tagger-v2.csv" \
  "https://huggingface.co/SmilingWolf/wd-v1-4-convnext-tagger-v2/resolve/main/selected_tags.csv" \
  "8c8750600db36233a1b274ac88bd46289e588b338218c2e4c62bbc9f2b516368"
echo "WD14 listo en $D"
