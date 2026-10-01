# Instalación de WAIFU (simple)

Instalador por consola, de un solo comando. Descarga todo lo pesado (engine + modelos) a tu PC; en GitHub solo viaja el código.

## 1) Qué necesitas

| | |
|---|---|
| Sistema | **Windows 10/11 x64** |
| GPU | **NVIDIA**. **8 GB** de VRAM: imagen, Editor y Upscaler. **12 GB**: vídeo (H3). Probado en RTX 3060 12 GB |
| Disco | **SSD SATA** (no HDD: los modelos se leen/cargan mucho mejor) con **~150 GB libres**; mínimo de descarga completa ≈ **120 GB** (106,3 GB de modelos + engine/.venv) + **~14 GB** si añades el LLM opcional |
| Programas | `git` para clonar; `curl.exe` ya viene con Windows |

## 2) Instalar (3 pasos)

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
INSTALAR.bat
```

- Descarga **~106 GB** de modelos + el engine: tarda bastante (según tu conexión).
- Es **repetible**: si se corta, vuelve a ejecutar `INSTALAR.bat` y continúa donde quedó.
- Verifica cada archivo con SHA256; los ya descargados no se bajan de nuevo.

## 3) Usar

```
1) INICIAR_LLM.bat         (opcional, recomendado: modelo único de texto/visión en 127.0.0.1:8290)
2) INICIAR_ENGINE.bat      (déjalo abierto)
3) INICIAR_WAIFU.bat       (abre http://127.0.0.1:8765)
```

Para cerrar: `DETENER_WAIFU.bat`, `DETENER_ENGINE.bat` y `DETENER_LLM.bat`. Comprobación rápida:
`VERIFICAR_WAIFU.bat` (con `--require-llm` exige el servidor arrancado). Sin el paso 1, la app usa
el modo local (llama-cpp en CPU) como siempre.

## 3b) LLM único (opcional y pesado, ~14 GB: pesos ~13,5 GB + runtime ~0,6 GB)

El modelo de todas las tareas de texto e imagen→texto (Qwen3.8-27B uncensored 3,69 bpw + mmproj)
y su runtime `llama.cpp` CUDA se bajan aparte, con verificación SHA256:

```powershell
& .\.venv\Scripts\python.exe scripts\download_llm.py
```

- Destinos: `ComfyUI/models/llm/qwen38-27b-uncensored/` y `tools/llama.cpp/` (no versionado).
- Se arranca con `INICIAR_LLM.bat` (puerto 8290, `CUDA0` = solo la GPU principal, MTP y thinking
  OFF). `WAIFU_LLM_DEVICE/CTX/NGL/DRAFT_NMAX/EXTRA_ARGS` ajustan el arranque.
- Pines y hashes: `install/manifest/manifest.llm.json`. Los dos GGUF también están en
  `manifest.models.json` como opcionales, así que `INSTALAR.bat -IncludeOptional` los baja; el
  runtime CUDA solo lo baja `scripts/download_llm.py`.

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
| `-IncludeOptional` | Baja también assets opcionales |
| `-SkipVerify` | No corre tests ni `app.health` al final |
| `-NoUserEnv` | No escribe variables de usuario `WAIFU_COMFY_*` |

Ejemplo: `INSTALAR.bat -SkipModels`

Detalle técnico completo (pines de engine/nodos, hashes, revisión del manifiesto): `README.md` (sección M10) y `install/manifest/`.
