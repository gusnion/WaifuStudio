# Avisos de terceros (THIRD_PARTY_NOTICES)

Estado: 2026-09-26 (hito M10 / F3a).
Ambito: pesos, LoRAs y componentes consumidos por WAIFU. Los textos de licencia
aun no estan archivados en el repo (carpeta prevista: `install/manifest/licenses/`),
por lo que cualquier fila marcada como **PENDIENTE/VERIFICAR** debe contrastarse
contra el origen antes de espejar, re-empaquetar o redistribuir.

> **Licencia del codigo**: MIT (ver `LICENSE`, © gusnion 2026). Los pesos,
> LoRAs y componentes de terceros conservan sus propias licencias (tablas
> siguientes y campo `license` de los manifiestos).

## Regla general

Los pesos de terceros **no se re-empaquetan** en este repositorio. El installer
(`install/install.ps1`) los descarga desde su origen y verifica hash cuando este
registrado. Este archivo solo inventaria licencias y condiciones de redistribucion.

## Pesos y modelos

| Componente | Licencia | ¿Redistribuible en el repo? | Estado |
| --- | --- | --- | --- |
| Anima (circlestone-labs) | circlestone-labs-non-commercial-license v1.2 | No (solo descarga desde origen con Attribution Notice) | Identificada; texto **PENDIENTE/VERIFICAR** |
| Wan 2.2 (DiT) | Apache-2.0 | Si, con avisos | Texto **PENDIENTE/VERIFICAR** (archivar) |
| umt5 (text encoder) | Apache-2.0 | Si, con avisos | Texto **PENDIENTE/VERIFICAR** (archivar) |
| Wan VAE | Apache-2.0 | Si, con avisos | Texto **PENDIENTE/VERIFICAR** (archivar) |
| LightX2V (LoRA aceleracion) | Apache-2.0 | Si, con avisos | Texto **PENDIENTE/VERIFICAR** (archivar) |
| RealESRGAN (upscaler) | BSD-3-Clause | Si, con avisos | Texto **PENDIENTE/VERIFICAR** (archivar) |
| MiniMax H3 (pesos empaquetados por Comfy-Org) | Licencia community de MiniMax (sin texto archivado) | **PENDIENTE/VERIFICAR** antes de espejar | **PENDIENTE/VERIFICAR** |
| Qwen-Image 2.1 (Editor M10, GGUF comunitario) | qwen-research (Qwen License) | **PENDIENTE/VERIFICAR**; revisar condiciones de uso/research | **PENDIENTE/VERIFICAR** |
| LLM local (Josiefied / QuantFactory, base Qwen) | qwen-research (derivada de Qwen) | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** |
| ClipProj (NicoLab28) | MIT | Si, con avisos | Identificada como MIT; texto **PENDIENTE/VERIFICAR** (archivar) |
| RIFE (interpolacion, custom node Fannovel16) | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** |
| xinsir ControlNet OpenPose SDXL (legacy) | Apache-2.0 | Si, con avisos | Texto **PENDIENTE/VERIFICAR** (archivar) |
| Krea-2, Kijai experimental, koongrizzly int4 | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** |
| Turbo LoRA H3 | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** | **PENDIENTE/VERIFICAR** |
| TIPO-500M (legacy, nodo retirado) | kohaku-license-1.0 | Revisar antes de reintroducir | **PENDIENTE/VERIFICAR** |
| animagine XL 4.0 (legacy) | Fair AI Public License 1.0-SD | Revisar antes de conservar | **PENDIENTE/VERIFICAR** |

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

## Acciones pendientes antes de publicar

1. Archivar los textos de licencia de terceros en `install/manifest/licenses/`
   y enlazarlos aqui (sustituir cada **PENDIENTE/VERIFICAR** por el estado real).
2. Confirmar con el usuario la licencia del codigo propio y crear `LICENSE`.
3. Verificar que ningun peso ni LoRA no-redistribuible viaja en el repo.
