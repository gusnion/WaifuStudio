#!/usr/bin/env bash
# Descarga verificada de los modelos Wan 2.2 AIO NSFW v10 + VAE + LoRA.
# Uso: ./download-wan.sh [RAIZ_DEL_REPO]
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
M="$ROOT/ComfyUI/models"
mkdir -p "$M/diffusion_models" "$M/text_encoders" "$M/vae" "$M/loras/wan22_uncensored/lopi999"

fetch() {
  local dest="$1" url="$2" sha="$3" size="$4"
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && [ "$(stat -c%s "$dest")" = "$size" ]; then
    echo "[$(basename "$dest")] ya presente"
  else
    echo "[$(date +%H:%M:%S)] descargando $(basename "$dest")"
    curl -L --fail --retry 5 --retry-delay 3 -C - -o "$dest.part" "$url"
    echo "$sha  $dest.part" | sha256sum -c -
    mv "$dest.part" "$dest"
  fi
  ls -lh "$dest"
}

fetch "$M/diffusion_models/wan2.2-i2v-rapid-aio-v10-nsfw-Q4_K_M.gguf" \
  "https://huggingface.co/desirel/WAN2.2-14B-Rapid-AllInOne-GGUF-NSFW-v10/resolve/4502c7f3de51fd728d851b37eda262f2be2a5628/wan2.2-i2v-rapid-aio-v10-nsfw-Q4_K_M.gguf" \
  "126a9f67cf41247981c8d2f1c39cde73f010b0670ce032854bd8c8d6ed746b67" "10849052416"

fetch "$M/text_encoders/nsfw_wan_umt5-xxl_fp8_scaled.safetensors" \
  "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/617a7633e636506f850e043bc4605f290a466a8e/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
  "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68" "6735906897"

fetch "$M/vae/wan_2.1_vae.safetensors" \
  "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/617a7633e636506f850e043bc4605f290a466a8e/split_files/vae/wan_2.1_vae.safetensors" \
  "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b" "253815318"

fetch "$M/loras/wan22_uncensored/lopi999/NSFW-22-H-e8.safetensors" \
  "https://huggingface.co/lopi999/Wan2.2-I2V_General-NSFW-LoRA/resolve/aeef17d7fa51d753ab7d1004ddb4f218a95d756d/NSFW-22-H-e8.safetensors" \
  "34e2144d3cd65360f97d09ccbe03e1c39a096df6c9234af5fe3899d1b63cda39" "613516752"

fetch "$M/text_encoders/umt5-xxl-encoder-Q5_K_M.gguf" \
  "https://huggingface.co/city96/umt5-xxl-encoder-gguf/resolve/b535255bee98c2b0a59ea7c0ae2dcd0c6657b3b7/umt5-xxl-encoder-Q5_K_M.gguf" \
  "eaea358bb438c5d211721a4feecc162000e3636e9cb96f51e216f1f44ebd12ce" "4145878880"

echo "[$(date +%H:%M:%S)] Wan listo"
