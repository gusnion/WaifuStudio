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
- «Mejorar prompt (H3)»: escribe los tres bloques del prompt H3 con el LLM gestionado.
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
| Disco | SSD SATA con ~150 GB libres (descarga completa ≈126 GB; ~106 GB son modelos). El paquete LLM incluido añade ~6,5 GB |
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
1) INICIAR_ENGINE.bat     (déjalo abierto; escucha en 127.0.0.1:8288)
2) INICIAR_WAIFU.bat      (abre la app en http://127.0.0.1:8765)
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
**Qwen3.5-9B-abliterated (Q4_K_M) + mmproj-F16**, servido por `llama-server` stock b11146 en
**CPU** (~6,1 GiB, 0 VRAM: no compite con ComfyUI por la GPU). Sin `.bat`: la app arranca el
servidor en el primer uso (~5 s de carga) y lo para al cerrar; el badge «LLM:» de la UI
muestra el estado.

El instalador baja el GGUF y el mmproj por defecto (entradas `required`). Para descargar o
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
