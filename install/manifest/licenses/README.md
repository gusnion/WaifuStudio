# Licencias de terceros — pendientes de archivar (M10-6b)

Este directorio guardará los textos de licencia de los pesos y nodos que el
instalador descarga. A 2026-09-26 ninguno está archivado en el repo; el campo
`license` de `manifest.models.json` / `manifest.nodes.json` es la referencia.

> **Retirados 2026-09-30 (M12)**: los pesos del LLM M11 (Qwen3.8-27B abliterado de AEON-7 con
> quant de soyaakinohara y mmproj de chimingw) y el respaldo legacy (Qwen2.5-7B abliterado de
> Josiefied/QuantFactory) y el caption Qwen2.5-VL de vision se borraron de disco y ya no se
> descargan. El LLM vigente es **Qwen3.5-9B-abliterated** (Q4_K_M, lukey03) + **mmproj-F16**
> (unsloth), Apache-2.0 declarada en `manifest.models.json`; sus textos siguen pendientes de
> archivar (no inventar): contrastar los repos `Qwen/Qwen3.5-9B`,
> `lukey03/Qwen3.5-9B-abliterated-GGUF` y `unsloth/Qwen3.5-9B-GGUF` antes de redistribuir.

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
| LLM M11 Qwen3.8-27B AEON-7 (soyaakinohara) + mmproj (chimingw) | Apache-2.0 declarada (base `Qwen/Qwen3.8-27B`) | **Retirado 2026-09-30** (pesos borrados; sin descarga) |
| LLM legacy Josiefied (QuantFactory, base Qwen2.5-7B) y caption Qwen2.5-VL | Sin verificar (`qwen-research`) | **Retirados 2026-09-30** (pesos borrados; sin descarga) |
| LLM M12 Qwen3.5-9B-abliterated (lukey03) + mmproj-F16 (unsloth) | Apache-2.0 declarada (base `Qwen/Qwen3.5-9B`) | Archivar LICENSE de `Qwen/Qwen3.5-9B`, lukey03 y unsloth antes de redistribuir |
| LoRAs de usuario (Miku, Reika Saimin, Shuuko, Reika_2) | Sin verificar / locales | **No redistribuir**; se piden aparte |

> Nota: el instalador descarga siempre desde el origen y no re-empaqueta pesos.
