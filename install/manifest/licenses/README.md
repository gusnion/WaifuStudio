# Licencias de terceros archivadas (M13-2 / M10-6b)

Este directorio contiene los textos de licencia de las dependencias clave y
modelos que componen WaifuStudio:

- `LICENSE_MIT.txt`: Licencia de WaifuStudio (código de la app).
- `LICENSE_GPL-3.0.txt`: GNU General Public License v3.0 (ComfyUI backend).
- `LICENSE_APACHE-2.0.txt`: Apache License 2.0 (Qwen3.5, WD14 tagger, Wan2.2 bases).
- `LICENSE_BSD-3-Clause.txt`: BSD 3-Clause (Real-ESRGAN upscaler).

## Estado por asset

| Asset | Licencia declarada | Archivo en este directorio |
|---|---|---|
| WaifuStudio App | MIT | `LICENSE_MIT.txt` |
| ComfyUI Engine | GPL-3.0 | `LICENSE_GPL-3.0.txt` |
| Qwen3.5-9B-abliterated / unsloth / WD14 | Apache-2.0 | `LICENSE_APACHE-2.0.txt` |
| RealESRGAN | BSD-3-Clause | `LICENSE_BSD-3-Clause.txt` |
| Anima 2.9B / Official / text encoder / VAE | `circlestone-labs-non-commercial-license v1.2` (no comercial) | No redistribuir; consulta upstream circlestone-labs |

| RIFE ckpts (Fannovel16, release `models`) | Sin verificar por ckpt | Verificar redistribución |
| TIPO-500M | `kohaku-license-1.0` | Solo entrada `obsolete`; no se descarga |
| animagine XL 4.0 | Fair AI Public License 1.0-SD | Solo entrada `obsolete`; no se descarga |
| xinsir controlnet openpose | Apache-2.0 | Solo entrada `obsolete`; no se descarga |
| Qwen-Image 2.1 UC / stock unsloth | `qwen-research` | Archivar LICENSE de `Qwen/Qwen-Image-2.1` |
| LLM M11 Qwen3.8-27B AEON-7 (soyaakinohara) + mmproj (chimingw) | Apache-2.0 declarada (base `Qwen/Qwen3.8-27B`) | **Retirado 2026-09-30** (pesos borrados; sin descarga) |
| LLM legacy Josiefied (QuantFactory, base Qwen2.5-7B) y caption Qwen2.5-VL | Sin verificar (`qwen-research`) | **Retirados 2026-09-30** (pesos borrados; sin descarga) |
| LLM M12 Qwen3.5-9B-abliterated (lukey03) + mmproj-F16 (unsloth) | Apache-2.0 declarada (base `Qwen/Qwen3.5-9B`) | Archivar LICENSE de `Qwen/Qwen3.5-9B`, lukey03 y unsloth antes de redistribuir |
| LoRAs de usuario (Miku, Reika Saimin, Shuuko, Reika_2) | Sin verificar / locales | **No redistribuir**; se piden aparte |

> Nota: el instalador descarga siempre desde el origen y no re-empaqueta pesos.
