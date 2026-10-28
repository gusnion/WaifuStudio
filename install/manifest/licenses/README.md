# Licencias de terceros archivadas (M13-2 / M10-6b)

Este directorio contiene los textos de licencia de las dependencias clave y
modelos que componen WaifuStudio:

- `LICENSE_MIT.txt`: Licencia de WaifuStudio (código de la app).
- `LICENSE_GPL-3.0.txt`: GNU General Public License v3.0 (ComfyUI backend).
- `LICENSE_APACHE-2.0.txt`: Apache License 2.0 (Qwen3.5, WD14 tagger, Wan2.2 bases).
- `LICENSE_BSD-3-Clause.txt`: BSD 3-Clause (Real-ESRGAN upscaler).
- `LICENSE_CIRCLESTONE-ANIMA.md`: licencia no comercial de Anima Aesthetic v1.1.
- `LICENSE_QWEN-IMAGE.txt`: Qwen-Image 2.1 (qwen-research).
- `LICENSE_OPENRAIL-PLUS-PLUS-M.txt`: OpenRAIL++-M (Animagine, RealVisXL, Juggernaut).
- `LICENSE_IRODORI-MIT.txt`: MIT de Irodori-TTS.

## Estado por asset

| Asset | Licencia declarada | Archivo en este directorio |
|---|---|---|
| WaifuStudio App | MIT | `LICENSE_MIT.txt` |
| ComfyUI Engine | GPL-3.0 | `LICENSE_GPL-3.0.txt` |
| Qwen3.5-9B-abliterated / unsloth / WD14 | Apache-2.0 | `LICENSE_APACHE-2.0.txt` |
| RealESRGAN | BSD-3-Clause | `LICENSE_BSD-3-Clause.txt` |
| Anima 2.9B / Official / text encoder / VAE | `circlestone-labs-non-commercial-license v1.2` (no comercial) | `LICENSE_CIRCLESTONE-ANIMA.md` |

| RIFE ckpts (Fannovel16, release `models`) | Sin verificar por ckpt | Verificar redistribución |
| TIPO-500M | `kohaku-license-1.0` | Solo entrada `obsolete`; no se descarga |
| animagine XL 4.0 | OpenRAIL++-M | `LICENSE_OPENRAIL-PLUS-PLUS-M.txt` |
| xinsir controlnet openpose | Apache-2.0 | Solo entrada `obsolete`; no se descarga |
| Qwen-Image 2.1 UC | `qwen-research` | `LICENSE_QWEN-IMAGE.txt` |
| LLM M11 Qwen3.8-27B AEON-7 (soyaakinohara) + mmproj (chimingw) | Apache-2.0 declarada (base `Qwen/Qwen3.8-27B`) | **Retirado 2026-09-30** (pesos borrados; sin descarga) |
| LLM legacy Josiefied (QuantFactory, base Qwen2.5-7B) y caption Qwen2.5-VL | Sin verificar (`qwen-research`) | **Retirados 2026-09-30** (pesos borrados; sin descarga) |
| LLM M12 Qwen3.5-9B-abliterated (lukey03) + mmproj-F16 (unsloth) | Apache-2.0 declarada (base `Qwen/Qwen3.5-9B`) | Archivar LICENSE de `Qwen/Qwen3.5-9B`, lukey03 y unsloth antes de redistribuir |
| LoRAs de usuario (Miku, Reika Saimin, Shuuko, Reika_2) | Sin verificar / locales | **No redistribuir**; se piden aparte |

> Nota: el instalador descarga siempre desde el origen y no re-empaqueta pesos.

| Irodori-TTS | MIT | `LICENSE_IRODORI-MIT.txt` |
| Wan 2.2 NSFW AIO v10 | Apache-2.0 (declarada por uploader) | `LICENSE_APACHE-2.0.txt` |
| FFmpeg 9.0.2 gyan.dev | GPL-3.0 (build GPL) | `LICENSE_GPL-3.0.txt` |
