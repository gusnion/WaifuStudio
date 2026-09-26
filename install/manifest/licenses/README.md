# Licencias de terceros — pendientes de archivar (M10-6b)

Este directorio guardará los textos de licencia de los pesos y nodos que el
instalador descarga. A 2026-09-26 ninguno está archivado en el repo; el campo
`license` de `manifest.models.json` / `manifest.nodes.json` es la referencia.

## Estado por asset

| Asset | Licencia declarada | Acción |
|---|---|---|
| Anima 2.9B / Official / text encoder / VAE | `circlestone-labs-non-commercial-license v1.2` (no comercial) | Archivar el LICENSE del repo `circlestone-labs/Anima` antes de redistribuir |
| Wan 2.2 GGUF / umt5 / VAE / LightX2V | Apache-2.0 (heredada) | Verificar y archivar LICENSE de QuantStack / Comfy-Org |
| MiniMax H3 (Comfy-Org), Krea-2, Kijai experimental, koongrizzly int4 | Sin verificar (`URL_VERIFICAR`) | Verificar antes de espejar |
| ClipProj (NicoLab28) | Sin verificar | Verificar antes de espejar |
| RealESRGAN | BSD-3-Clause | Bajo riesgo; archivar texto |
| RIFE ckpts (Fannovel16, release `models`) | Sin verificar por ckpt | Verificar redistribución |
| TIPO-500M | `kohaku-license-1.0` | Solo entrada `obsolete`; no se descarga |
| animagine XL 4.0 | Fair AI Public License 1.0-SD | Solo entrada `obsolete`; no se descarga |
| xinsir controlnet openpose | Apache-2.0 | Solo entrada `obsolete`; no se descarga |
| Qwen-Image 2.1 UC / stock unsloth | `qwen-research` | Archivar LICENSE de `Qwen/Qwen-Image-2.1` |
| LLM Josiefied (QuantFactory) | Sin verificar | Verificar (base Qwen2.5, revisar `qwen-research`) |
| LoRAs de usuario (Miku, Reika Saimin, Shuuko, Reika_2) | Sin verificar / locales | **No redistribuir**; se piden aparte |

> Nota: el instalador descarga siempre desde el origen y no re-empaqueta pesos.
