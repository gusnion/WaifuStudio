# Instalación de WAIFU (install.ps1) — F3b / M10-6b

Instalador reproducible para una **máquina limpia** (sin GPU al ejecutar este documento; aquí solo se documenta). Todo lo pesado (pesos, engine, runtime) se descarga en la máquina del usuario: **en git no viaja ningún binario**.

> **Aviso de publicación**: este repo queda preparado para publicarse, pero **crear el remoto y etiquetar V1.0.0 lo hará el usuario**. F3b no hace commits ni push, y el instalador asume que el repo ya está en disco (clonado por el usuario desde donde decida publicarlo).

---

## 1) Requisitos

| Requisito | Detalle |
|---|---|
| SO | **Windows 10/11 x64** (PowerShell 5.1; `curl.exe` incluido desde Win10 1803) |
| GPU | **NVIDIA** (CUDA 13 / backend `cu130`); el instalador aborta si no detecta una |
| Disco | **≥ 124 GB libres** en la unidad de instalación (mínimo que exige el preflight) |
| Herramientas | `git` (clon/checkout pineado); `uv` se instala solo si falta; `curl.exe` para descargas |
| Token | Opcional: `WAIFU_CIVITAI_TOKEN` para los assets de Civitai (Aesthetic/One obsession; Miku solo si se pide) |

Presupuesto real: el manifiesto `required` suma **132.156.175.823 B ≈ 132,2 GB** (incluye el Editor M10: 14,6 GB) y el engine + `.venv` añaden ~6,6 GB, así que para una instalación completa se recomiendan **≥150 GB libres**; el gate del instalador se mantiene en 124 GB según las fuentes.

## 2) Pasos

```powershell
# 1. Clona el repo donde quieras (el remoto lo define el usuario)
git clone <URL_DEL_REMOTO_WAIFU> E:\IA\WAIFU
Set-Location E:\IA\WAIFU

# 2. (Opcional) token de Civitai para Anima Aesthetic / One obsession
$env:WAIFU_CIVITAI_TOKEN = '<tu_token>'

# 3. Instalador idempotente
powershell -ExecutionPolicy Bypass -File .\install\install.ps1
```

Parámetros útiles:

| Parámetro | Efecto |
|---|---|
| `-Root <ruta>` | Raíz del repo (por defecto, el padre de `install\`) |
| `-SkipEngine` | No clona ComfyUI/nodos ni instala torch/triton/Sage |
| `-SkipModels` | No descarga modelos (verifica los existentes) |
| `-IncludeOptional` | Baja también `required=false` no obsoletos (R2V y stock del Editor) |
| `-SkipVerify` | No corre suite ni `app.health` |
| `-NoUserEnv` | No escribe `WAIFU_COMFY_ROOT`/`WAIFU_COMFY_URL` como variables de usuario |

Qué hace, en orden:

1. **Preflight**: Windows x64, GPU NVIDIA y ≥124 GB libres.
2. **uv 0.11.14** (instala si falta) y **CPython 3.12.12** (`uv python install 3.12.12 --no-bin --no-registry`).
3. **`.venv`** + `requirements.txt` + `requirements-dev.txt`.
4. **ComfyUI v0.34.0** @ `12d5279438bfefc058a269eae805ceab6047777f`: clon/checkout verificado por `git rev-parse HEAD`, `uv pip install -r ComfyUI\requirements.txt`, torch `2.11.0+cu130` / torchvision `0.26.0+cu130` / torchaudio `2.11.0+cu130` (índice PyTorch cu130), `triton_windows==3.8.0.post28` y wheel **SageAttention** `2.2.0+cu130torch2.10.0andhigher.post6` (`--no-deps`, sha256 verificado; usa `data\downloads\sage` si existe).
5. **Custom nodes pineados** por commit: GGUF `6ea2651e…`, KJNodes `d3cfe216…`, Frame-Interpolation `26545cc2…`, ClipProj `c01ba8fb…` (+ `requirements.txt` de cada nodo) y los **4 ckpts RIFE**.
6. **Modelos** de `install\manifest\manifest.models.json`: descarga a `ComfyUI\models\<subdir>` (o raíz `ComfyUI` para RIFE) y **verificación sha256 + tamaño** antes de mover el archivo definitivo. `obsolete` no se descarga; `required=false` solo con `-IncludeOptional`.
7. **Entorno**: escribe `install\env.ps1` y, salvo `-NoUserEnv`, `WAIFU_COMFY_ROOT` / `WAIFU_COMFY_URL` de usuario (`http://127.0.0.1:8288`).
8. **Verificación final** (abajo).

Los manifiestos son la fuente de verdad: `install\manifest\manifest.models.json` (asset, bytes, sha256, url, licencia, `required`/`obsolete` y notas) y `install\manifest\manifest.nodes.json` (engine, nodos, Python/uv, torch, triton y wheel Sage).

## 3) Verificación final

```powershell
# Suite completa (base 998 tests; unittest es el runner canonico)
& .\.venv\Scripts\python.exe -m unittest discover -s tests

# Salud de rutas + engine (el engine tarda en cargar en la primera GPU)
& .\.venv\Scripts\python.exe -m app.health
& .\.venv\Scripts\python.exe -m app.health --require-engine

# Arranque real (lo lanza el usuario)
.\scripts\start_engine.ps1      # ComfyUI en 127.0.0.1:8288
.\scripts\start_app.ps1         # webapp en 8765 (o INICIAR_WAIFU.bat)
```

El instalador corre suite y `app.health`; si el engine aún no responde, avisa y termina (arranca el engine y repite `--require-engine`). Si faltan entradas `required` por `URL_VERIFICAR`/aporte manual, sale con código 2 y lista los pendientes.

En un clon limpio sin las LoRAs de usuario, los tests de `tests\test_loras.py` que exigen esos archivos se **saltan solos** (no fallan). Tras aportar las LoRAs, puedes exigir la comprobación de disco con `$env:WAIFU_TEST_ASSETS = '1'` antes de correr la suite.

## 4) LoRAs de usuario y licencias

- **LoRAs de usuario: no redistribuibles.** `Miku_Nakano_Anima_v0.7` (Civitai), `Kurashiki Reika Saimin Seishidou`, `shuuko-komi-s1s2` y `Reika Kurashiki_2` están registradas en `registry\loras.json`, pero **se piden aparte**: el instalador no las descarga por defecto (sus entradas van `required=false`; Miku requiere token + ID de Civitai y las otras dos no tienen fuente pública). Deben copiarse con el nombre y `subdir` exactos del manifiesto.
- **Anima** (2.9B, Official, text encoder y VAE) usa `circlestone-labs-non-commercial-license v1.2`: uso **no comercial**; el instalador descarga desde el origen y **no re-empaqueta** pesos.
- **Wan 2.2 / umt5 / VAE / LightX2V** se documentan como Apache-2.0 (pendiente archivar el LICENSE de QuantStack/Comfy-Org); **RealESRGAN** BSD-3-Clause; **xinsir** Apache-2.0.
- **H3 (Comfy-Org), Krea-2, Kijai experimental, koongrizzly, ClipProj (NicoLab28), turbo LoRAs y RIFE**: `URL_VERIFICAR` — no hay licencia verificada en disco; verificar/archivar antes de espejar o redistribuir.
- **Editor Qwen-Image 2.1 UC / stock unsloth**: `qwen-research`. El VAE UC (`qwen_image_2.1_vae_bf16.safetensors`) es distinto del VAE de Anima (`qwen_image_vae.safetensors`) y **no lo pisa**.
- Los textos de licencia se archivaron/archivarán bajo `install\manifest\licenses\` cuando el repo los incorpore; este entregable solo deja el campo `license` por entrada.

## 5) `URL_VERIFICAR` y huecos declarados

| Ítem | Qué falta | Cómo se resuelve |
|---|---|---|
| `anima_aestheticV11`, `oneObsessionAnima_v40`, (Miku) | URL pública + token | `https://civitai.com/api/download/models/<versionId>?token=$env:WAIFU_CIVITAI_TOKEN` (IDs exactos en el manifiesto: 3126581, 3301424, 3020851) |
| LLM Q3_K_M / Q4_K_M | Revisión exacta del repo QuantFactory | Fijar la revisión al descargar; el sha256 del manifiesto verifica el contenido |
| Licencias H3/Krea-2/Kijai/koongrizzly/ClipProj/turbo/RIFE/QuantFactory | Texto archivado | Verificar y archivar antes de espejar |
| `llama-cpp-python==0.3.35` | Origen/URL no registrado | Se instala desde PyPI vía `requirements.txt`; si la versión no está publicada, el instalador falla de forma visible |
| `obsolete` (TIPO-500M, ClipProj-mlp, animagine, xinsir, controlnet-aux) | Ninguno para instalar | Quedan **fijados con SHA/revisión** en los manifiestos (petición del auditor de limpieza), pero no se descargan |
