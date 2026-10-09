# Instalación de WAIFU (simple)

Instalador por consola, de un solo comando. Descarga todo lo pesado (engine + modelos) a tu PC; en GitHub solo viaja el código.

## 1) Qué necesitas

| | |
|---|---|
| Sistema | **Windows 10/11 x64** |
| GPU | **NVIDIA**. **8 GB** de VRAM: imagen, Editor y Upscaler. **12 GB**: vídeo (H3). Probado en RTX 3060 12 GB |
| Disco | **SSD SATA** (no HDD: los modelos se leen/cargan mucho mejor) con **~150 GB libres**; mínimo de descarga completa ≈ **126 GB** (106,3 GB de modelos + engine/.venv + **~6,5 GB del LLM incluido**) |
| Programas | `git` para clonar; `curl.exe` ya viene con Windows |

## 2) Instalar (3 pasos)

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
INSTALAR.bat
```

- Descarga **~112 GB** de modelos (incluye el LLM) + el engine: tarda bastante (según tu conexión).
- Es **repetible**: si se corta, vuelve a ejecutar `INSTALAR.bat` y continúa donde quedó.
- Verifica cada archivo con SHA256; los ya descargados no se bajan de nuevo.

## 3) Usar

```
1) INICIAR_ENGINE.bat      (déjalo abierto)
2) INICIAR_WAIFU.bat       (abre http://127.0.0.1:8765)
3) ABRIR_APP.bat           (opcional: modo ventana ultraligera dedicada, ~100 MB RAM)
```

El LLM es automático: la app arranca y para sola su servidor de texto/visión (~5 s la primera
carga; CPU, 0 VRAM). No hay que lanzar nada más. Para cerrar: `DETENER_WAIFU.bat` y
`DETENER_ENGINE.bat`. Comprobación rápida: `VERIFICAR_WAIFU.bat` (con `--require-llm` exige el
LLM listo).

## 3b) LLM único (incluido, ~6,5 GB)

Todas las tareas de texto e imagen→texto usan **Qwen3.5-9B NSFW Captioning v5 (Q4_K_M) + mmproj-Q8_0**
(~6,25 GiB), servido por `llama.cpp` stock b11146 en **CPU** (`-ngl 0`: 0 VRAM, no compite con
ComfyUI). El instalador baja el GGUF, el mmproj y el runtime por defecto (ejecutando
`scripts/download_llm.py`); la app los usa solos, sin `.bat`.

Como alternativa (o para completar/reverificar el paquete, incluido el runtime
`tools/llama.cpp/`, que no se versiona) existe el descargador con verificación SHA256:

```powershell
& .\.venv\Scripts\python.exe scripts\download_llm.py
```

- Destinos: `ComfyUI/models/llm/qwen35-9b-nsfw-captioning/` y `tools/llama.cpp/`.
- `WAIFU_LLM_PORT/MODEL/MMPROJ/THREADS` ajustan el servidor gestionado; `WAIFU_LLM_URL` fuerza
  un servidor externo.
- Estado en la UI o `GET /api/llm/status`. Pines y hashes:
  `install/manifest/manifest.llm.json`.

## 4) Qué NO se incluye

- **LoRAs de personajes del autor** (no redistribuibles). Cuando tengas las tuyas, se añaden desde la app: pestaña Imagen → «Elegir LoRAs» → «Gestionar biblioteca».
- **Dos modelos base** (Anima Aesthetic v11 y One Obsession v40) se descargan **a mano**: el instalador te dirá exactamente cuáles faltan y dónde va cada archivo (nombre y carpeta). Ambos están en Civitai y requieren cuenta.
- Los textos de licencia de cada modelo: ver `THIRD_PARTY_NOTICES.md` y el campo `license` del manifiesto.

## 5) Licencia

- **Código: MIT** (ver `LICENSE`).
- **Modelos**: cada uno con su licencia. Destaca **Anima: no comercial** (`circlestone-labs-non-commercial-license v1.2`). Revisa `THIRD_PARTY_NOTICES.md` antes de usos comerciales.

## 6) Avanzado (opcional)

El instalador acepta banderas si sabes lo que haces:

| Bandera | Efecto |
|---|---|
| `-SkipEngine` | No instala ComfyUI/nodos/torch/Sage |
| `-SkipModels` | No descarga modelos (solo verifica los existentes) |
| `-IncludeOptional` | Baja también assets opcionales y el entrenador |
| `-IncludeTrainer` | Clona kohya-ss/sd-scripts y prepara tools\kohya\venv |
| `-SkipVerify` | No corre tests ni `app.health` al final |
| `-NoUserEnv` | No escribe variables de usuario `WAIFU_COMFY_*` |

Ejemplo: `INSTALAR.bat -SkipModels`

Detalle técnico completo (pines de engine/nodos, hashes, revisión del manifiesto): `README.md` (sección M10) y `install/manifest/`.
