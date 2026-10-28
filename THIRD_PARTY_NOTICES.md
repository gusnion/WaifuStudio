# Avisos de terceros (THIRD_PARTY_NOTICES)

Estado: 2026-10-26 (v2.x; Wan 2.2 reinstalado + MMAudio; H3/Anima archivados).
Ambito: pesos, LoRAs y componentes consumidos por WAIFU. Los textos de licencias
principales (MIT, Apache-2.0, BSD-3-Clause, GPL-3.0) estan archivados en
`install/manifest/licenses/`; los hashes de cada descarga estan en
`install/manifest/manifest.wan.json` y `manifest.models.json`.

> **Licencia del codigo**: MIT (ver `LICENSE`, © gusnion 2026). Los pesos,
> LoRAs y componentes de terceros conservan sus propias licencias (tablas
> siguientes y campo `license` de los manifiestos).

## Regla general

Los pesos de terceros **no se re-empaquetan** en este repositorio. El installer
(`install/install.ps1`) los descarga desde su origen y verifica hash cuando este
registrado. Este archivo solo inventaria licencias y condiciones de redistribucion.

## Pesos y modelos

> **Archivados 2026-10-26**: H3 y Anima salieron del set oficial; sus pesos viven en
> `G:\IA\WAIFU-personal-archive`. Wan 2.2 vuelve como motor de video activo y el
> LLM único sigue siendo Qwen3.5-9B en CPU.

| Componente | Licencia | ¿Redistribuible en el repo? | Estado |
| --- | --- | --- | --- |
| Anima (circlestone-labs) | circlestone-labs-non-commercial-license v1.2 | No (solo descarga desde origen con Attribution Notice) | `install/manifest/licenses/LICENSE_CIRCLESTONE-ANIMA.md` |
| AniDream TrueHentai v1.0 (Civitai 2895658 / v3273573) | Anima License (CircleStone Labs LLC) — no comercial; built on NVIDIA Cosmos | No (descarga desde Civitai; los pesos no viajan en el repo) | Identificada 2026-10-26 |
| Juggernaut XL Ragnarok (Civitai 133005 / v1759168) | OpenRAIL++-M; flags `allowCommercialUse=Image,RentCivit`, `allowNoCredit=false`; el autor pide shoutout | No (descarga desde Civitai; los pesos no viajan en el repo) | Identificada 2026-10-24 |
| RealVisXL V5.0 BakedVAE (Civitai 139562 / v789646) | OpenRAIL++-M; flags `allowCommercialUse=Image,RentCivit,Rent`, `allowNoCredit=false`; **atribucion requerida** | No (descarga desde Civitai; los pesos no viajan en el repo) | Identificada 2026-10-24 |
| Wan 2.2 (DiT I2V A14B) | Apache-2.0 | Si, con avisos | **Activo**; `manifest.wan.json` |
| umt5 (text encoder) | Apache-2.0 | Si, con avisos | Activo; Q5_K_M en `manifest.wan.json` |
| Wan VAE | Apache-2.0 | Si, con avisos | Activo; `manifest.wan.json` |
| LightX2V (LoRA aceleracion) | Apache-2.0 | Si, con avisos | Activo; `manifest.wan.json` |
| MMAudio (Kijai safetensors) | MIT (repo) | Si, con avisos | Activo; `manifest.wan.json` |
| ComfyUI-VideoHelperSuite | MIT | Si, con avisos | Activo; commit `4d907be` |
| BigVGAN v2 44 kHz (NVIDIA) | NVIDIA license (modelo) | No se redistribuye | Descargado por MMAudio en runtime |
| FFmpeg/FFprobe (9.0.2-essentials_build-www.gyan.dev; SHA256 3256173F...ED8EDEC) | GPL-3.0 (build GPL) | No se redistribuye | Descarga fijada por URL/SHA256; binarios separados |
| Animagine XL 4.0 Opt | Fair AI Public License 1.0-SD | No se redistribuye | Activo; Civitai/HF |
| `lopi999` NSFW LoRAs | Sin licencia declarada | No se redistribuye | Opcional; no usar comercialmente |
| `rzgar` Uncensored 4-step LoRAs | Apache-2.0 | Si, con avisos | Opcional; descargado, no activo por defecto |
| RealESRGAN (upscaler) | BSD-3-Clause | Si, con avisos | Texto archivado (`install/manifest/licenses/BSD-3-CLAUSE.txt`) |
| MiniMax H3 (pesos empaquetados por Comfy-Org) | Licencia community de MiniMax | No se redistribuye (descarga origen) | Identificada |
| Qwen-Image 2.1 (Editor M10, GGUF comunitario) | qwen-research (Qwen License) | No se redistribuye | `install/manifest/licenses/LICENSE_QWEN-IMAGE.txt` |
| LLM M12: Qwen3.5-9B-abliterated (lukey03), texto Q4_K_M | Apache-2.0 | No se redistribuye (descarga origen) | Identificada (Apache-2.0) |
| mmproj-F16 (unsloth/Qwen3.5-9B-GGUF) | Apache-2.0 | No se redistribuye | Identificada (Apache-2.0) |
| llama.cpp stock b11146 (ggml-org) + cudart CUDA | MIT (llama.cpp) / NVIDIA redistribuible | No se redistribuye | Identificada (MIT) |
| ClipProj (NicoLab28) | MIT | Si, con avisos | Identificada (MIT, texto archivado) |
| RIFE (interpolacion, custom node Fannovel16) | **PENDIENTE/VERIFICAR** | No se redistribuye | Identificada |
| sd-scripts kohya-ss (entrenador de LoRA; `tools/kohya`) | Apache-2.0 | No se redistribuye (se clona en local) | Identificada (Apache-2.0) |

### Modelos SDXL de uso comercial (2026-10-24)

- **Juggernaut XL Ragnarok**: https://civitai.com/models/133005?modelVersionId=1759168
  - Uso comercial de imagenes permitido (`Image`, `RentCivit`), derivados permitidos.
  - `allowNoCredit=false`; el autor pide un shoutout. Los pesos no se redistribuyen.
- **RealVisXL V5.0 (BakedVAE)**: https://civitai.com/models/139562?modelVersionId=789646
  - Uso comercial de imagenes permitido (`Image`, `RentCivit`, `Rent`), derivados permitidos.
  - `allowNoCredit=false`; **atribucion requerida**. Los pesos no se redistribuyen.
- **AniDream TrueHentai v1.0**: https://civitai.com/models/2895658?modelVersionId=3273573
  - **Anima License (CircleStone Labs LLC): no comercial**; built on NVIDIA Cosmos.
  - Pesos no redistribuibles; descarga desde Civitai.

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

| Irodori-TTS (servidor y pesos) | MIT (servidor); pesos del autor | No se redistribuyen los pesos | `LICENSE_IRODORI-MIT.txt` |
| Wan 2.2 NSFW AIO v10 (GGUF comunitario) | Apache-2.0 declarada por uploader | No se redistribuye | Identificada |
| POSE-DB-01 (esqueletos derivados) | autorizacion del autor; no redistribuir PNG | Solo datos derivados locales | Identificada |
