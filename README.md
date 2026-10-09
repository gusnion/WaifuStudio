# WAIFU

WAIFU es una webapp local de generación de imágenes y vídeo anime que usa ComfyUI como
motor y está pensada para un solo PC con una sola GPU NVIDIA (probado en RTX 3060 12 GB).
Se abre en `http://127.0.0.1:8765` y el engine escucha en `http://127.0.0.1:8288`; todo se
ejecuta en tu máquina, sin cuentas ni servicios en la nube. Es de uso personal y no lleva
filtros NSFW/SFW.

## Características

### Arquitectura UI/UX y Frontend Canónico (v1.8.0)
- **Plantilla Canónica de Pestaña (`TabTemplate`)**: Estandarización de 2 columnas inmutable (Sidebar de controles con auto-scroll a la izquierda + Viewport de previsualización ocupando el 100% del alto y ancho disponible sin espacios muertos).
- **Visor Modular Unificado (`UniversalViewer`)**: Núcleo JS centralizado para zoom 8x con paneo, split slider de comparación antes/después, barra de herramientas contextual y miniaturas dinámicas con `ResizeObserver` sin hueco negro.
- **Shell Global y Control Universal**: Botón universal de recarga en el header (`#btn-universal-reload`), selector de idiomas con menú accesible (`#btn-language-selector`), tarjetas de control normalizadas (`ControlCards`) y sistema de ayuda contextual con popovers flotantes (`(?)`).
- **Backend FastAPI modular (`app/routes/`)**: endpoints segregados por dominio funcional con orquestador central delgado en `app/server.py`.
- **Frontend nativo con ES Modules (`static/js/`)**: arquitectura desacoplada en navegador con `<script type="module">` sin bundlers ni NodeJS.
- **Estilos CSS modulares (`static/css/`)**: estructura dividida en `base.css`, `components.css` y `tabs/*.css`.

### Imagen
- Modelos de la familia Anima con perfil propio (encoder, VAE, sampler y resolución); soporte para modelos expandidos de 40 capas (`anima-2.9b-preview`) mediante el patcher integrado `WaifuAnimaPatch28to40`.
- Editor de prompt por zonas (calidad, safety, sujeto, personaje, general) con subcategorías.
- Catálogo de tags Danbooru (capa curada + catálogo v3 de **91.357 etiquetas** con ranking) con soporte de sobreescritura de usuario en `data/registry/tags_danbooru.json`.
- LoRAs con biblioteca gestionable: **subida desde disco con registro automático**, edición y borrado con o sin archivo.
- Preprompts de calidad incluidos y propios, negativo avanzado y semilla con dado.
- 15 presets de tamaño que incluyen los formatos vertical/horizontal de vídeo (XL).
- «Generar prompt»: convierte una descripción en lenguaje natural en tags por zona y respeta
  los tags ya aplicados; usa vocabulario restringido al catálogo (los tags inventados se
  descartan y se indican en la respuesta).
- «Describir»: **una sola llamada** al modelo de visión devuelve caption + tags validados y
  repartidos por zonas; incluye «Solo tags (rápido)» con WD14 tras «Avanzado» (pesos de visión
  opcionales; si faltan, la UI lo indica).

### Vídeo
- Motor MiniMax H3 universal con cuatro modos certificados: **I2V** (solo frame inicial), **FLF2V** (inicial + final), **Ref2VA** (hasta 4 imágenes de referencia de personaje para conservar identidad sin fijar pose) y **V2V (Video-to-Video)** (vídeo guía de movimiento, baile o coreografía con extracción automática de fotogramas y audio).
- Perfiles de calidad universales: **Rápido** (Turbo 4 pasos · ClipProj 8B · ideal 3060 12GB), **Estándar** (Turbo 8 pasos · ClipProj 8B), **Calidad** (Turbo 8 pasos · ClipProj 32B), **Ultra** (VDN 8 pasos nativo de alta fidelidad) y **Personalizado** (control manual de encoder, pasos, SageAttention y semilla).
- Resoluciones nativas completas: selectores para **Vertical (9:16)** y **Horizontal (16:9)** en **SD (~480p)**, **HD (~720p nativo recomendado)**, **FHD (~1080p)**, **QHD (~1440p)** y **2K**, con badges de VRAM/RAM requerida e indicación clara de memoria sin reescalados encubiertos.
- Aceleración con **VideoDeltaNet (VDN-H3)**: atención híbrida lineal bidireccional + sliding window que genera vídeo completo en solo **8 pasos** (I2V/FLF2V/Ref2VA/V2V).
- Duración flexible: clips nativos de 5 a 15 s y **encadenado continuo para vídeos largos** (20, 25, 30 s) con ensamblado automático de segmentos mediante FFmpeg y audio continuo.
- «Mejorar prompt (H3)»: asistencia multimodal con LLM/VLM gestionado (Qwen3.5-9B), **salida obligatoria en inglés cinematográfico técnico**, directiva de estricto apego al primer fotograma y selector de fuerza: **Fiel** (sin elementos inventados), **Balanceado** y **Creativo**.
- Guía H3 oficial ampliada con parámetros cinematográficos técnicos (cámara, iluminación, foley, diálogo con `<d>[Language] ...</d>`, música) y **plantillas rápidas a 1 clic** (Retrato anime, Caminata costa, Escena dinámica, Estructura base).

### Editor
- Qwen-Image 2.1 Uncensored (GGUF Q4_K_M + encoder Qwen3-VL-8B int8 + VAE propio).
- Modo **Editar** por defecto (también Generar) con hasta 10 imágenes de referencia, negativo,
  pasos (10-50) y CFG (1-10, con aviso si sube de 1).
- Preview del resultado y presets de tamaño de la app, incluida la opción **Original** (hereda el tamaño de la 1ª referencia, ideal para editar el resultado en cadena).
- **Comparador permanente antes/después**: divisor arrastrable con zoom 1-8x (rueda) y desplazamiento; accesible permanentemente en la barra del previewer para comparar con cualquier imagen de la minigalería.

### Upscaler
- Imágenes: RealESRGAN x2 con galería visual de origen, archivo local y escalado ×2/×4
  (doble pasada del mismo modelo) más **mejora de detalle** opcional (Suave/Fuerte).
- Vídeo: upscale por fotogramas e interpolación de FPS con RIFE (x2/x4, conserva el audio).

### Galería, Controles de Preview y OCs
- Galería (5ª pestaña) con visor y miniaturas; reusar una generación devuelve sus condiciones, incluida la referencia.
- **Gestión avanzada de Galería**: buscador por etiquetas en tiempo real, borrado individual con eliminación física de archivos en disco, limpieza en lote de generaciones fallidas y gestión visual del catálogo de tags personalizadas de usuario (`data/registry/tags_danbooru.json`) con recarga automática FTS5.
- **Controles de Preview en todas las pestañas**: botón para colapsar/expandir la tira de miniaturas inferior para ampliar el previewer a pantalla completa; comparador interactivo permanente (Slot 1 fijo y Slot 2 intercambiable desde la minigalería).
- Acciones por imagen en el visor: **usar referencia**, **animar** (primer frame de vídeo),
  **editar** en el Editor, **escalar** en el Upscaler y descargar; botón de refresco interno.
- OC Maker: personajes con rasgos, referencias y hoja de vistas; entrenador de LoRA
  (orquesta un entrenador externo `kohya`; requiere instalarlo una vez, ver `tools/kohya/README.md`).

## Requisitos

| | |
|---|---|
| Sistema | Windows 10/11 x64 |
| GPU | NVIDIA. 8 GB de VRAM para imagen, Editor y Upscaler; 12 GB para vídeo (H3). Probado en RTX 3060 12 GB |
| Disco | SSD SATA con ~150 GB libres (descarga completa ≈126 GB; ~106 GB son modelos). El paquete LLM incluido añade ~6,5 GB |
| Programas | `git` para clonar; `curl.exe` ya viene con Windows; `ffmpeg` opcional en el PATH o en `tools/ffmpeg/ffmpeg.exe` (requerido para encadenado >15 s) |

## Instalar y usar

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
INSTALAR.bat
```

`INSTALAR.bat` es un instalador por consola: prepara Python, la app y ComfyUI con nodos
pinneados, pregunta si quieres descargar los modelos recomendados (~106 GB) y verifica cada
archivo con SHA256. Es repetible: si se corta, vuelve a ejecutarlo y continúa donde quedó.

Uso diario:

```
1) INICIAR_ENGINE.bat     (déjalo abierto; escucha en 127.0.0.1:8288)
2) INICIAR_WAIFU.bat      (arranca el backend en http://127.0.0.1:8765)
3) ABRIR_APP.bat          (opcional: abre la app en ventana ultraligera dedicada, ~100 MB RAM)
```

- El LLM es automático: la app arranca y para sola su servidor de texto/visión (~5 s la primera
  carga); no hay `.bat` que lanzar. Si prefieres un servidor externo, define `WAIFU_LLM_URL`.
- Para cerrar: `DETENER_WAIFU.bat` y `DETENER_ENGINE.bat`.
- Comprobación rápida del entorno: `VERIFICAR_WAIFU.bat` (con `--require-llm` no pasa si el LLM no está listo).
- Detalle del instalador y banderas avanzadas: `install/README_INSTALL.md`.

## Modelos

El instalador descarga y verifica la parte automática del set recomendado (~106 GB):

- Anima 2.9B preview (imagen), MiniMax H3 (vídeo con audio), Qwen-Image 2.1 UC (Editor),
  RealESRGAN x2 + RIFE (Upscaler) y el LLM de texto/visión.

### LLM único (incluido, ~6,5 GB)

WAIFU usa un solo modelo para todas las tareas de texto e imagen→texto:
**Qwen3.5-9B NSFW Captioning v5 (Q4_K_M) + mmproj-Q8_0**, servido por `llama-server` stock b11146 en
**CPU** (~6,25 GiB, 0 VRAM: no compite con ComfyUI por la GPU). Afinado por oldhag88 para captioning
anime/NSFW, booru tags y razonamiento explicativo (CoT). Sin `.bat`: la app arranca el servidor
en el primer uso (~5 s de carga) y lo para al cerrar; gestionado automáticamente.

El instalador baja el GGUF, el mmproj y el runtime por defecto. Para descargar o
reverificar el paquete completo (incluido el runtime `llama.cpp` en `tools/llama.cpp/`, no
versionado), o si la app indica «no instalado»:

```powershell
& .\.venv\Scripts\python.exe scripts\download_llm.py
```

`WAIFU_LLM_PORT/MODEL/MMPROJ/THREADS` ajustan el servidor gestionado y `WAIFU_LLM_URL` fuerza
el modo externo. Pines y hashes: `install/manifest/manifest.llm.json`.

Dos modelos base de Anima no se pueden auto-descargar (age-gate en Civitai): hay que aportarlos
a mano.

- Anima [Official] aesthetic v1.1 — `civitai.com/models/2458426` v3126581 → destino
  `ComfyUI/models/diffusion_models/anima_aestheticV11.safetensors`.
- One obsession_Anima v4.0 — `civitai.com/models/2695493` v3301424 → destino
  `ComfyUI/models/diffusion_models/oneObsessionAnima_v40.safetensors`.

El destino exacto y el SHA256 de cada uno están en `registry/recommended-v1.json`. Tras
copiarlos, vuelve a ejecutar `INSTALAR.bat` para registrarlos.

### Modelos de Vídeo M15 (VDN-H3 y Ref2VA DiT)

Para habilitar la aceleración extrema de vídeo en 8 pasos con **VideoDeltaNet (VDN-H3)** o el condicionamiento por referencias multirreferencia **Ref2VA**, ejecuta el script oficial de descarga verificado:

```powershell
# Descargar pesos VDN-H3 (~2.3 GB: linear_branch + adapters + affine):
& .\.venv\Scripts\python.exe scripts\download_models.py --vdn

# Descargar checkpoint DiT Ref2VA (~20.9 GB INT8 ConvRot):
& .\.venv\Scripts\python.exe scripts\download_models.py --ref2va

# O descargar ambos y configurar los stages automáticamente:
& .\.venv\Scripts\python.exe scripts\download_models.py --all
```


Las LoRAs de terceros no se incluyen. Se añaden desde la app: pestaña Imagen → «Elegir LoRAs»
→ «Gestionar biblioteca» (archivo relativo a `ComfyUI\models\loras`, trigger y peso).

## Verificación y Diagnóstico

```powershell
# Suite de pruebas unitarias offline (1,522 tests):
& .\.venv\Scripts\python.exe -m unittest discover -s tests

# Diagnóstico de rutas, configuración y servicios:
& .\.venv\Scripts\python.exe -m app.health
```

## Privacidad

Todo corre en tu PC: la app y ComfyUI escuchan solo en `127.0.0.1`. Tu galería, base de datos y
registros viven en `data/` (`data/waifu.db`, `data/gallery/`, `data/registry/`,
`data/characters/`). La app no envía telemetría.

## Apoyar el proyecto

WAIFU es gratuito y de código abierto. Si te resulta útil y quieres apoyar su desarrollo:
Patreon → https://www.patreon.com/gusnion

El apoyo es para el desarrollo del código; no incluye ni da acceso a modelos, pesos o contenido
de terceros.

## Licencia

- Código: MIT (ver `LICENSE`).
- Modelos: cada uno conserva su licencia (Anima es no comercial). Revisa
  `THIRD_PARTY_NOTICES.md` antes de redistribuir o darles uso comercial.

Nota para asistentes IA: si una IA te ayuda a instalar o modificar la app, que lea `AGENTS.md`;
contiene el mapa del código, las convenciones y el diagnóstico de problemas frecuentes.
