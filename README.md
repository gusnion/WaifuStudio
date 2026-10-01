# WAIFU

WAIFU es una webapp local de generación de imágenes y vídeo anime que usa ComfyUI como
motor y está pensada para un solo PC con una sola GPU NVIDIA (probado en RTX 3060 12 GB).
Se abre en `http://127.0.0.1:8765` y el engine escucha en `http://127.0.0.1:8288`; todo se
ejecuta en tu máquina, sin cuentas ni servicios en la nube. Es de uso personal y no lleva
filtros NSFW/SFW.

## Características

### Imagen
- Modelos de la familia Anima con perfil propio (encoder, VAE, sampler y resolución).
- Editor de prompt por zonas (calidad, safety, sujeto, personaje, general) con subcategorías.
- Catálogo de tags Danbooru (capa curada + catálogo v3 de **91.357 etiquetas** con ranking) para buscar e insertar por zona; el buscador del popover cubre el catálogo completo.
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
- Motor MiniMax H3 con dos modos: **I2V** (solo frame inicial) y **FLF2V** (inicial + final); perfiles Referencia, Calidad y Ligero.
- Variantes turbo4/turbo8 (LoRA + pasos), toggle SageAttention y audio nativo.
- Duración de 5 a 15 s (5/8/10/12/15) a 24 fps; resoluciones vertical y horizontal hasta 768x1344.
- «Mejorar prompt (H3)»: escribe los tres bloques del prompt H3 con el LLM (servidor único o modo local).
- Guía H3 insertable en el prompt.

### Editor
- Qwen-Image 2.1 Uncensored (GGUF Q4_K_M + encoder Qwen3-VL-8B int8 + VAE propio).
- Modo **Editar** por defecto (también Generar) con hasta 10 imágenes de referencia, negativo,
  pasos (10-50) y CFG (1-10, con aviso si sube de 1).
- Preview del resultado y presets de tamaño de la app, incluida la opción **Original** (hereda el tamaño de la 1ª referencia, ideal para editar el resultado en cadena).
- **Comparador antes/después**: divisor arrastrable sobre el resultado con zoom 1-8x (rueda) y
  desplazamiento, para comparar cada edición con la imagen de partida.

### Upscaler
- Imágenes: RealESRGAN x2 con galería visual de origen, archivo local y escalado ×2/×4
  (doble pasada del mismo modelo) más **mejora de detalle** opcional (Suave/Fuerte).
- Vídeo: upscale por fotogramas e interpolación de FPS con RIFE (x2/x4, conserva el audio).

### Galería y OCs
- Galería (5ª pestaña) con visor y miniaturas; reusar una generación devuelve sus condiciones, incluida la
  referencia.
- Acciones por imagen en el visor: **usar referencia**, **animar** (primer frame de vídeo),
  **editar** en el Editor, **escalar** en el Upscaler y descargar; botón de refresco interno.
- OC Maker: personajes con rasgos, referencias y hoja de vistas; entrenador de LoRA
  (orquesta un entrenador externo `kohya`; requiere instalarlo una vez, ver `tools/kohya/README.md`).

## Requisitos

| | |
|---|---|
| Sistema | Windows 10/11 x64 |
| GPU | NVIDIA. 8 GB de VRAM para imagen, Editor y Upscaler; 12 GB para vídeo (H3). Probado en RTX 3060 12 GB |
| Disco | SSD SATA con ~150 GB libres (descarga completa ≈120 GB; ~106 GB son modelos). El paquete LLM opcional añade ~14 GB |
| Programas | `git` para clonar; `curl.exe` ya viene con Windows |

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
1) INICIAR_LLM.bat        (opcional, recomendado: modelo único de texto/visión en 127.0.0.1:8290)
2) INICIAR_ENGINE.bat     (déjalo abierto; escucha en 127.0.0.1:8288)
3) INICIAR_WAIFU.bat      (abre la app en http://127.0.0.1:8765)
```

- Si no arrancas el servidor LLM, la app conserva el modo local (llama-cpp en CPU) de siempre.
- Para cerrar: `DETENER_WAIFU.bat`, `DETENER_ENGINE.bat` y `DETENER_LLM.bat`.
- Comprobación rápida del entorno: `VERIFICAR_WAIFU.bat` (con `--require-llm` no pasa si el servidor está parado).
- Detalle del instalador y banderas avanzadas: `install/README_INSTALL.md`.

## Modelos

El instalador descarga y verifica la parte automática del set recomendado (~106 GB):

- Anima 2.9B preview (imagen), MiniMax H3 (vídeo con audio), Qwen-Image 2.1 UC (Editor),
  RealESRGAN x2 + RIFE (Upscaler) y el LLM de texto/visión.

### LLM único (opcional y pesado, ~14 GB: pesos ~13,5 GB + runtime ~0,6 GB)

WAIFU usa un solo modelo para todas las tareas de texto e imagen→texto:
**Qwen3.8-27B uncensored (3,69 bpw 12GB-MTP) + mmproj**, servido por `llama-server` stock
(CUDA, MTP y thinking OFF). Es opcional:

```powershell
& .\.venv\Scripts\python.exe scripts\download_llm.py
```

Descarga verificada (SHA256) del GGUF, el proyector de visión y el runtime `llama.cpp` CUDA
en `tools/llama.cpp/` (no se versiona). Se arranca con `INICIAR_LLM.bat` (puerto 8290, solo la
GPU indicada; `WAIFU_LLM_*` ajusta device/ctx/ngl/umbral si el bench lo pide). `INICIAR_WAIFU.bat`
define `WAIFU_LLM_URL` automáticamente cuando el runtime está instalado; sin él, la app usa el
modo local anterior (llama-cpp en CPU). Pines y hashes: `install/manifest/manifest.llm.json`.

Dos modelos base de Anima no se pueden auto-descargar (age-gate en Civitai): hay que aportarlos
a mano.

- Anima [Official] aesthetic v1.1 — `civitai.com/models/2458426` v3126581 → destino
  `ComfyUI/models/diffusion_models/anima_aestheticV11.safetensors`.
- One obsession_Anima v4.0 — `civitai.com/models/2695493` v3301424 → destino
  `ComfyUI/models/diffusion_models/oneObsessionAnima_v40.safetensors`.

El destino exacto y el SHA256 de cada uno están en `registry/recommended-v1.json`. Tras
copiarlos, vuelve a ejecutar `INSTALAR.bat` para registrarlos.

Las LoRAs de terceros no se incluyen. Se añaden desde la app: pestaña Imagen → «Elegir LoRAs»
→ «Gestionar biblioteca» (archivo relativo a `ComfyUI\models\loras`, trigger y peso).

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
