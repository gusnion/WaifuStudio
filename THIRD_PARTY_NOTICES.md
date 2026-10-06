# Avisos de terceros (THIRD_PARTY_NOTICES)

Estado: 2026-10-06 (M13: v1.3.0 — Anima Patch 28->40, Kohya Installer, Purga Wan).
Ambito: pesos, LoRAs y componentes consumidos por WAIFU. Los textos de licencias
principales (MIT, Apache-2.0, BSD-3-Clause, GPL-3.0) estan archivados en
`install/manifest/licenses/`.

> **Licencia del codigo**: MIT (ver `LICENSE`, © gusnion 2026). Los pesos,
> LoRAs y componentes de terceros conservan sus propias licencias (tablas
> siguientes y campo `license` de los manifiestos).

## Regla general

Los pesos de terceros **no se re-empaquetan** en este repositorio. El installer
(`install/install.ps1`) los descarga desde su origen y verifica hash cuando este
registrado. Este archivo solo inventaria licencias y condiciones de redistribucion.

## Pesos y modelos

> **Retirados 2026-09-27/30**: los pesos de Wan 2.2 y del LLM M11 (Qwen3.8-27B) se borraron de disco.
> El motor actual utiliza MiniMax H3 (perfiles Referencia, Calidad, Ligero) y LLM único Qwen3.5-9B en CPU.

| Componente | Licencia | ¿Redistribuible en el repo? | Estado |
| --- | --- | --- | --- |
| Anima (circlestone-labs) | circlestone-labs-non-commercial-license v1.2 | No (solo descarga desde origen con Attribution Notice) | Identificada |
| Wan 2.2 (DiT) | Apache-2.0 | Si, con avisos | **Retirado 2026-09-27** (`WAN_RETIRADO.md`) |
| umt5 (text encoder) | Apache-2.0 | Si, con avisos | Texto archivado (`install/manifest/licenses/APACHE-2.0.txt`) |
| Wan VAE | Apache-2.0 | Si, con avisos | **Retirado 2026-09-27** |
| LightX2V (LoRA aceleracion) | Apache-2.0 | Si, con avisos | **Retirado 2026-09-27** |
| RealESRGAN (upscaler) | BSD-3-Clause | Si, con avisos | Texto archivado (`install/manifest/licenses/BSD-3-CLAUSE.txt`) |
| MiniMax H3 (pesos empaquetados por Comfy-Org) | Licencia community de MiniMax | No se redistribuye (descarga origen) | Identificada |
| Qwen-Image 2.1 (Editor M10, GGUF comunitario) | qwen-research (Qwen License) | No se redistribuye | Identificada |
| LLM M12: Qwen3.5-9B-abliterated (lukey03), texto Q4_K_M | Apache-2.0 | No se redistribuye (descarga origen) | Identificada (Apache-2.0) |
| mmproj-F16 (unsloth/Qwen3.5-9B-GGUF) | Apache-2.0 | No se redistribuye | Identificada (Apache-2.0) |
| llama.cpp stock b11146 (ggml-org) + cudart CUDA | MIT (llama.cpp) / NVIDIA redistribuible | No se redistribuye | Identificada (MIT) |
| ClipProj (NicoLab28) | MIT | Si, con avisos | Identificada (MIT, texto archivado) |
| RIFE (interpolacion, custom node Fannovel16) | **PENDIENTE/VERIFICAR** | No se redistribuye | Identificada |
| sd-scripts kohya-ss (entrenador de LoRA; `tools/kohya`) | Apache-2.0 | No se redistribuye (se clona en local) | Identificada (Apache-2.0) |

## LoRAs personales del usuario

Las siguientes LoRAs son **personales y NO redistribuibles**: no deben incluirse
en el repo ni en ningun bundle. El installer las solicitara aparte (archivo o
token del usuario):

- Reika Saimin
- Shuuko
- Reika_2
- Miku (Civitai)

## Dependencias Python de la app

Fijadas en `requirements.txt` / `requirements-dev.txt`. Sus textos de licencia
viajan en el `dist-info` de cada paquete instalado y no se archivan aqui:
FastAPI y llama-cpp-python (MIT), uvicorn, Jinja2 y httpx (BSD-3-Clause),
aiohttp (Apache-2.0 AND MIT), Pillow (HPND).

## Acciones pendientes (post-V1.0.0)

1. Archivar los textos de licencia de terceros en `install/manifest/licenses/`
   y enlazarlos aqui (sustituir cada **PENDIENTE/VERIFICAR** por el estado real).
2. ~~Confirmar con el usuario la licencia del codigo propio y crear `LICENSE`.~~
   **HECHO 2026-09-27** (`LICENSE` MIT, © gusnion 2026).
3. ~~Verificar que ningun peso ni LoRA no-redistribuible viaja en el repo.~~
   **VERIFICADO 2026-09-30**: el repo publico solo lleva codigo; los registros de
   usuario viven en `data/` (no versionado) y los pesos se descargan o aportan
   aparte.
