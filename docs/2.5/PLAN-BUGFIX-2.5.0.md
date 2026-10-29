# Plan de corrección — WAIFU STUDIO 2.5.0_bugfix

Fecha: 2026-10-29. Estado: **plan para revisión**. No se ha modificado código.

Ámbito: corregir la base de 2.5.0. **No es 2.5.1** y no se trabaja en el desarrollo de 2.5.1.
Los recordatorios de 2.5.1 se anotan al final, separados y sin desarrollarse aquí.

## 0. Estado de ejecución (2026-10-29)

| Paquete | Estado | Evidencia |
|---|---|---|
| W13 | [x] | Commits `517731c`, `60ac03e`; focal 82 OK; suite 1853 OK. Audio a demanda, WAV al Timeline y paso 3 revisado. |
| W16b | [x] | Commit `609296c`; focal 85 OK; suite 1856 OK. AUDIO en tres pasos, un motor por modo, visor con pestañas y stems secundarios. |
| W15 | [!] | Commit `a312eff`; focal 132 OK; suite 1868 OK. Vídeo local y tramos implementados; split/concat/remux reales con 10 s 1080p (150+90 frames, audio conservado). Falta validación end-to-end del grafo en ComfyUI/GPU real. |
| W17d | [x] | Commit `fa571b9`; tests server/OC 395 OK; suite final 1869 OK. OC Maker como pestaña real, menú por personaje, i18n y Escape. |

Cierre: `c250cbe` retira “Hoja de contacto” del estado de multivista. Suite final: **1869 OK, 1 skipped**. No hay tag ni release.


## 1. Decisiones de alcance

- Primero se corrige lo que impide usar la app con criterio: modelos, prompts, flujos de Editor, Vídeo, Audio, Estudio, Upscaler y OC Maker.
- La clasificación y los preprompts se resuelven con una **base simple y editable**. La clasificación avanzada multicapa y la curación automática de perfiles quedan para el trabajo con Guía/Skill que hará el agente en 2.5.1.
- La app debe poder clasificar los modelos actuales y uno nuevo razonable, pero no se construirá un motor de inferencia complejo.
- Los datos de modelos se pueden completar desde el registro; el agente de apoyo podrá enriquecerlos después.
- No se tocarán `data/` del usuario, pesos ni configuraciones durante las pruebas.

## 2. Correcciones de premisas

### Animagine sí usa tags

Animagine XL 4.0 Opt es SDXL, pero está entrenado con captioning por tags y tag ordering. Su metadata local declara “trained with tag-based caption and tag ordering method”.

Por tanto:

- No se eliminan los tags de Animagine.
- Lo incorrecto es el perfil genérico `sdxl_tags` compartido con otros SDXL.
- Animagine necesita un perfil propio: `high score`, `great score`, `masterpiece`, `absurdres`, artista sin `@` y enhancement tags al final.

Fuentes: [model card](https://huggingface.co/cagliostrolab/animagine-xl-4.0) y [guía de prompting](https://cagliostrolab.net/posts/optimizing-animagine-xl-40-in-depth-guideline-and-update).

### Anima no carece de preprompt

Existen `anima_default`, `glossy`, `not_glossy`, `ninguno`; Anima usa `glossy` y `prompt_profile: anima`. El defecto es su `subfamily: sin_clasificar` y la falta de claridad en la UI, no la ausencia de preprompt.

### Preprompts de los modelos actuales

- Anima: `glossy`, coherente.
- Animagine: `animagine`, coherente; el perfil genérico es el problema.
- RealVisXL: `ninguno`, coherente con prosa.
- Juggernaut: `ninguno`, coherente; no tiene perfil propio.
- El fallback `sdxl_default` es de tags anime y no debe aplicarse a SDXL natural.

## 3. Fases y paquetes de trabajo

### Fase 0 — Congelar y medir

- Rama `fix/2.5.0_bugfix`.
- Baseline: suite completa, conteo real, capturas claro/oscuro a 1280/1100/1024.
- Inventario de modelos, LoRAs y salidas de audio/vídeo.
- No modificar datos ni pesos.

**Salida:** baseline reproducible.

### Fase 1 — Base de modelos y prompts

#### W1. Clasificación base

Objetivo: que los modelos actuales y un modelo nuevo razonable no queden sin clasificar, sin construir multicapas.

- Leer `modelspec.architecture` y `ss_base_model_version` si existen.
- Si no hay metadata, detectar únicamente el layout grueso:
  - SDXL (`conditioner.embedders` + `first_stage_model` + `input_blocks`) → `sdxl_base`.
  - Anima (`model.diffusion_model.blocks.*`) → `anima`.
- `Animagine` se evalúa antes de `Anima` para evitar la colisión por subcadena.
- Si el layout es desconocido, dejar el modelo como `sin_clasificar` **con acción manual**, no inventar familia.
- Persistir `subfamily` y `prompt_profile` editables en `models.json`.
- Al escanear un modelo ya registrado, no recalcular automáticamente si el usuario lo editó; ofrecer “Reclasificar”.
- El badge trata `sin_clasificar` como vacío y cae a `family`; nunca queda un badge en blanco.
- No se implementa confianza, procedencia ni clasificación por múltiples heurísticas.

**Criterio de aceptación:** los 5 modelos actuales quedan clasificados; un SDXL nuevo con layout estándar cae en `sdxl_base`; un modelo desconocido queda pendiente con acción manual; el badge siempre es legible.

#### W2. Perfiles y preprompts base

Objetivo: que cada modelo tenga su preprompt correcto, sin curación automática avanzada.

- Añadir `subfamily` y `prompt_profile` explícitos a los 5 modelos actuales:
  - `anima_aestheticv11` → `anima` + `anima` + `glossy`.
  - `animagine-xl-4-opt` → `sdxl_base` + `animagine` + `animagine`.
  - `realvisxl-v50` → `sdxl_base` + `sdxl_natural` + `ninguno`.
  - `juggernaut-xl-ragnarok` → `sdxl_base` + `sdxl_natural` + `ninguno`.
  - `vidrohH_v12` → `sdxl_base` + perfil editable; no inventar tags/prosa.
- Eliminar el default `sdxl_default` para modelos natural; el preprompt se elige por modelo/perfil, no por family.
- Crear un perfil mínimo `animagine` con su calidad y orden; no se generaliza a Illustrious/Pony/NoobAI.
- El preprompt se puede elegir/corregir manualmente; mostrar de dónde sale el valor por defecto.
- Pasar `prompt_profile`/`family` a `enhance_zones` para que no inyecte scores de Anima a Animagine.
- El instalador y `recommended-v1.json` deben incluir `subfamily`/`prompt_profile` y deduplicar por `unet_name`, no solo por id.

**Criterio de aceptación:** Anima, Animagine, RealVisXL y Juggernaut generan con su preprompt correcto; un modelo nuevo se puede corregir sin editar código; `enhance_zones` respeta el perfil.

#### W3. Guía de prompt dinámica

- Una sola fuente por perfil para: placeholder, ayuda, calidad, sintaxis de artista, orden y visibilidad de zonas.
- En Imagen, la descripción “tags Danbooru” solo aparece en perfiles de tags.
- En natural se oculta la guía de tags y se muestra guía de prosa.
- Anima muestra scores y `@artista`; Animagine muestra su calidad y orden propios.
- `#enhance-hint` se actualiza al cambiar de modelo.
- No duplicar textos entre `image.js`, `index.html` y backend.

**Criterio de aceptación:** cambiar de modelo cambia placeholder y ayuda; RealVisXL/Juggernaut no muestran “Danbooru”; Animagine no muestra instrucciones de Anima.

### Fase 2 — Consistencia visual

#### W4. Ventana de Defaults

- Migrar a `fieldset.control-card`, `legend`, `btn-help` y botones canónicos.
- Eliminar estilos inline y medidas propias.
- Revisar claro/oscuro, foco y responsive.

**Aceptación:** Defaults se ve como una sección estándar de la app.

#### W5. Botón universal de generación en oscuro

- Corregir `border`, `box-shadow`, `border-color` y estados `hover/focus/disabled` en tema oscuro.
- No duplicar reglas por pestaña; usar el token del componente.

**Aceptación:** borde visible y consistente en claro/oscuro.

#### W6. Aviso de licencia de Vídeo

- Colocarlo en el layout, encima de “Generar” y del visor.
- Revisar `z-index`, posición y solapamiento.
- Debe verse sin abrir nada y en 1280/1024.

**Aceptación:** el aviso no queda detrás de ningún módulo.

### Fase 3 — Editor y Vídeo

#### W7. “Describir”: rápido por defecto

- El botón principal usa el modo rápido; el LLM de visión es una acción secundaria explícita.
- Añadir timeout, cancelación y estado de espera.
- El modo rápido no debe quedar bloqueado si el LLM falla o está ocupado.
- La UI debe indicar qué modo se está usando.

**Aceptación:** “Describir” responde sin colgarse; el LLM solo se lanza si el usuario lo elige.

#### W8. Multivista con botón universal

- Quitar “Generar hoja de contacto” como botón legacy.
- Usar el botón universal de generar; cambia de etiqueta según modo, no crea un CTA paralelo.
- Reducir los paneles “2. Instrucción” y “3. Configuración” a lo útil:
  - Referencias.
  - 4/6/8 vistas.
  - Ángulo/preset.
  - Salida.
- Lo demás, en “Avanzado” plegado o fuera.

**Aceptación:** en multivista solo hay un botón de generar; no aparece “hoja de contacto”.

#### W9. Worktree del Editor: historia por imagen

Problema: el usuario no distingue entre “imagen que estoy mirando” e “imagen desde la que voy a trabajar”, y el Editor hereda el prompt de la última generación.

Propuesta:

- Cada imagen/generación es un nodo con:
  - `gen_id`.
  - `parent_gen_id`.
  - `root_gen_id`.
  - prompt, negativo, seed, pasos, CFG, modelo, referencias.
- En el visor del Editor, un **minipanel derecho** muestra el árbol de esa imagen:
  - raíz → padres → nodo activo;
  - hijos/ramas del nodo;
  - hermanos, si existen;
  - indicador “Trabajando desde: [id]”.
- Al seleccionar una miniatura de la Galería:
  - se resuelve su `gen_id`;
  - se carga su propio historial en el minipanel;
  - se cargan sus metadatos en el Editor;
  - no se hereda nada de la última generación.
- Al seleccionar un nodo del minipanel:
  - se trabaja sobre esa rama;
  - el siguiente “Generar” crea un hijo de ese nodo;
  - se puede retroceder hasta el padre/raíz.
- Las imágenes antiguas sin `parent_gen_id` se tratan como raíz de sí mismas; no se inventa un padre.
- La miniatura y el árbol deben indicar claramente el nodo activo; el árbol no sustituye al visor principal.
- Persistencia: guardar la relación padre/hijo en la generación y exponer `GET /api/gallery/{id}/lineage` (o equivalente). Si no hay datos, devolver raíz única.
- Al generar desde el Editor, registrar como padre el nodo activo; al editar una referencia, registrar también la referencia usada.
- Evitar que un cambio de miniatura pierda el estado sin aviso: si hay cambios sin guardar, confirmar o conservar borrador por nodo.

**Aceptación:**

- Elegir una imagen antigua restaura su prompt, no el de la última generación.
- El minipanel muestra raíz, padre, nodo activo y ramas.
- Generar desde un nodo crea un hijo, no una rama huérfana.
- Se puede volver al padre y trabajar desde allí.
- Cambiar de miniatura no mezcla metadatos entre imágenes.

#### W10. Cargador de LoRAs para Imagen y Editor

- Un componente compartido, visible en Imagen y Editor.
- Flujo:
  - “Cargar LoRA”.
  - Elegir archivo local.
  - Copiar a `ComfyUI/models/loras/` con nombre seguro.
  - Evitar duplicados por hash.
  - Comprobar compatibilidad básica de raíz.
  - Refrescar la biblioteca.
- No se implementa descubrimiento avanzado de toda la información del LoRA.
- El modelo/usuario puede completar metadatos después.
- Si es incompatible de raíz, error claro y no se activa.
- En Imagen, filtrar por familia/subrama del modelo activo.
- En Editor, mostrar solo LoRAs compatibles con Qwen; no mostrar compatibles de Imagen.
- Si no hay LoRAs, el estado vacío debe explicar cómo cargar una.

**Aceptación:** cargar un `.safetensors` local lo deja detectable; uno incompatible se rechaza con motivo; aparece en la pestaña correcta.

#### W11. FLF2V

- Verificar primero que el AIO acepta primer y último frame.
- Añadir modo I2V/FLF2V con dos entradas.
- Reutilizar el mismo botón universal, cola, presets y salida muda.
- Mantener aviso de licencia.
- Probar un clip real de 5 s.

**Aceptación:** FLF2V genera un clip reproducible con primer/último frame; si el AIO no lo soporta, el control no se muestra.

### Fase 4 — Estudio

#### W12. Abrir carpeta de exportación

- La respuesta de export incluye ruta absoluta.
- Botón “Abrir carpeta” junto a “Exportado”.
- Endpoint seguro limitado a `data/gallery`/exports.
- Alternativa “Copiar ruta” si el navegador no puede abrir Explorer.

**Aceptación:** tras exportar se ve y se abre la carpeta real.

#### W13. Paso “3. Generar en…” y audio a demanda

- Auditar cada acción del paso 3 y corregir payloads/estados.
- Añadir “Generar audio para este proyecto”:
  - MMAudio para ambiente.
  - Irodori para voz si está online.
  - Resultado como pista del Timeline.
- Verificar que el audio aparece en el proyecto y se exporta.

**Aceptación:** cada botón del paso 3 hace lo que declara; el audio a demanda se integra en el Timeline.

### Fase 5 — UPSCALER

#### W14. Matriz de modos y modelos reales

- Mostrar solo modelos presentes; marcar/deshabilitar los ausentes.
- Eliminar el fallback silencioso x4→x2.
- Mostrar el factor real (`modelo × pasadas`).
- Hires Fix: apunta a `Anima-2.9B-preview-v1`, que no existe. Decisión base: usar el Anima registrado si el grafo lo permite; si no, desactivar con motivo. No prometer que funciona.
- Qwen Remaster: no entrega 2K. Decisión base: renombrar a “Qwen refine” y no prometer 2048 px, o implementar el 2K real. Se recomienda renombrar en bugfix.
- RIFE: mostrar solo multiplicadores soportados; no ofrecer ×4 si el backend fija ×2.
- Comparador: corregir antes/después; ocultarlo en vídeo.
- Arreglar el label “Interpolar” que se pisa.
- Hint de nitidez: “imagen y vídeo”.
- Denoise UI: 0.25, coherente con backend.
- Limpiar copias de `ComfyUI/input` al terminar.

**Aceptación:** ningún modo produce un resultado distinto al que declara; los modelos ausentes no se pueden elegir.

#### W15. Vídeo local y cola por tramos

- Añadir entrada de vídeo local, no solo Galería.
- Sustituir el límite duro de 300 frames por procesamiento por tramos:
  - corte por frames (150–200 a 1080p);
  - un prompt por tramo dentro del mismo job;
  - progreso “tramo i/N”;
  - concatenación con ffmpeg;
  - remux del audio original;
  - cancelación entre tramos;
  - limpieza de temporales;
  - tope de duración/espacio con aviso.
- Calcular el presupuesto con `frames × multiplier` cuando haya RIFE.
- Validar `fps <= 120`.
- Si el vídeo es muy largo, avisar del tiempo/espacio antes de encolar.

**Aceptación:** un vídeo de 10 s a 1080p se procesa completo por tramos y conserva audio; no hay límite fijo de 300 frames.

### Fase 6 — AUDIO y OC Maker

#### W16. AUDIO en tres pasos

1. **Tarea y entrada:** selector “Voz libre (A)” / “Ambiente desde vídeo (B)”, picker visual con preview; no mostrar “Heredada” antes de seleccionar.
2. **Ajustes y generar:** `fieldset` numerados, CTA contextual sticky; un solo motor por modo; quitar checkboxes falsos; “Mezclar” deshabilitado si el clip es mudo.
3. **Resultado:** un solo visor con toolbar y thumbnails; stems como acción secundaria, no tercer CTA.

Además:

- Modo A asíncrono con job, progreso y cancelación; sin progreso simulado.
- Aviso de japonés/SilentCipher junto a la voz.
- Galería: filtro Audio, `.wav` en `MEDIA_TYPES`, player, descarga y stems.
- “Enviar a Timeline” real, no solo cambio de pestaña.

**Aceptación:** flujo A/B comprensible, un CTA por paso, WAV reproducible desde Galería, stems visibles.

#### W17. OC Maker como pestaña real

- Sacar el contenido de `#oc-modal` y montarlo en `#panel-oc`.
- Eliminar `#btn-oc`, el reparentado y los handlers de modal.
- Cargar referencias al entrar, no solo tras guardar.
- Estado vacío con acciones reales.
- Añadir `input[type=file]`/drag&drop para referencias.
- Corregir layout a ≤1100 px y scrolls anidados.
- Arreglar tokens de tema claro (`--text-bright`, `--panel-hover`, etc.).
- Scoping de pose por pestaña.
- Reducir 7 botones por personaje a “Usar” + menú; “Entrenar LoRA” en cabecera.
- Hojas sin recorte 2:3.
- i18n de botones y modal de poses.
- Barra de progreso real para 8 vistas.
- Escape cierra solo el modal abierto.

**Aceptación:** OC Maker entra sin panel en blanco, permite subir referencias, no se rompe a 1024/1100 px y es legible en claro/oscuro.

## 4. Orden recomendado

```text
W0 baseline
  ↓
W1 clasificación base → W2 perfiles/preprompts → W3 guía dinámica
  ↓
W4 Defaults + W5 botón oscuro + W6 licencia vídeo
  ↓
W7 Describir → W8 multivista → W9 worktree → W10 LoRA → W11 FLF2V
  ↓
W12/W13 Estudio
  ↓
W14/W15 UPSCALER
  ↓
W16 AUDIO
  ↓
W17 OC Maker
  ↓
Regresión y cierre de bugfix
```

W16 y W17 pueden ir en paralelo con W12/W13 si no comparten archivos. W1/W2 antes de W3, W9 y W10.

## 5. Pruebas de aceptación

### Modelos/prompts

1. Los 5 modelos tienen badge/subrama.
2. Un modelo nuevo con layout SDXL cae en `sdxl_base`.
3. Un modelo desconocido queda pendiente con acción manual.
4. Anima usa tags y `glossy`.
5. Animagine usa tags, `high score/great score` y enhancement al final.
6. RealVisXL/Juggernaut usan prosa.
7. El hint cambia al cambiar de modelo.

### UI

8. Defaults se ve estándar.
9. Botón universal visible en oscuro.
10. Aviso de licencia de Vídeo visible.
11. Galería reproduce WAV y stems.

### Editor/Vídeo

12. “Describir” no se cuelga; rápido por defecto.
13. Multivista usa el botón universal.
14. Worktree: seleccionar imagen antigua restaura su historial, no la última.
15. Worktree: generar desde un nodo crea un hijo; se puede volver al padre.
16. LoRA local se copia, se detecta y se rechaza si es incompatible.
17. FLF2V genera clip real con primer/último frame.

### Estudio/UPSCALER

18. Exportar muestra y abre la carpeta.
19. Paso 3 ejecuta el flujo correcto.
20. Audio a demanda aparece en Timeline.
21. UPSCALER no cae silenciosamente a x2.
22. Hires/Qwen/RIFE se comportan como declara la UI.
23. Vídeo local de 10 s se procesa por tramos y conserva audio.

### AUDIO/OC Maker

24. AUDIO tiene tres pasos y un CTA por paso.
25. Modo A tiene cancelación real.
26. OC Maker no arranca en blanco y permite subir referencias.
27. OC Maker no se rompe a 1024 px; claro/oscuro legible.
28. Escape no cambia de pestaña.

### Regresión

29. Suite completa verde; nuevo conteo real.
30. Sin `TODO`/`FIXME` nuevos.
31. Sin diálogos nativos.
32. Sin borrado de datos/modelos.

## 6. Riesgos y decisiones pendientes de aprobación

1. **Nombre:** 2.5.0_bugfix.
2. **Clasificación base:** sin multicapas ni agente; la curación avanzada queda para 2.5.1.
3. **Preprompts:** base editable por modelo; la investigación web/autor queda para el agente de 2.5.1.
4. **Worktree:** requiere guardar `parent_gen_id` y una API de linaje; las imágenes antiguas se tratan como raíz.
5. **Audio asíncrono:** cambia el contrato interno de `/api/audio/voice`; necesario para cancelación real.
6. **UPSCALER por tramos:** requiere cola, concatenación y pruebas con vídeo real.
7. **OC Maker:** refactor de modal a pestaña; hay tests que fijan el markup actual y habrá que actualizarlos.
8. **FLF2V:** solo se integra si el AIO lo soporta; si no, se declara no disponible.
9. **Release:** no habrá tag ni release hasta aprobar el bugfix y repetir las pruebas.

## 6.b Evidencia usada (archivo:línea)

### Modelos y prompts

- `infer_subfamily` solo lee metadata: `app/registry.py:48`, `:70`; colisión Animagine/Anima: `:86`.
- `infer_prompt_profile` y perfiles: `app/registry.py:21`, `:142`; entrada persistida: `:294`.
- Scan que se salta modelos ya registrados: `app/routes/models.py:249`, `:268`; defaults del modelo nuevo: `:329`.
- Badge que no cae a `family`: `static/js/tabs/image.js:150`, `:169`.
- Preprompts Anima/Animagine/RealVis y default: `app/preprompts.py:26`, `:52`, `:59`, `:211`.
- `enhance_zones` sin family: `app/routes/prompt.py:277`; hardcode Anima: `app/enhancer.py:433`, `:564`.
- Placeholder genérico: `static/js/tabs/image.js:66`, `:259`; hints fijos: `templates/index.html:105`, `:125`, `:139`.

### AUDIO

- Layout y CTA al final del sidebar: `templates/index.html:1426`, `:1580`; viewport: `:1626`.
- A/B como pantallas y mezcla fuera: `index.html:1431-1432`, `:1440-1505`, `:1507-1589`, `:1591-1623`; `static/js/tabs/audio.js:636-639`.
- Tres CTA y controles falsos: `index.html:1498`, `:1530-1540`, `:1580`, `:1610`.
- Galería sin audio: `app/routes/gallery.py:18-22`, `:49-52`, `:181-184`; `static/js/tabs/gallery.js:108-139`.
- Voz síncrona y timeout: `static/js/tabs/audio.js:337`, `:563-578`; `app/audio.py:61`.
- Mezcla/truncamiento: `app/audio.py:574-607`, `:630`, `:661`.

### OC Maker

- Modal reparentado y `#panel-oc` vacío: `templates/index.html:1078`, `:1822`; `static/js/components/oc_picker.js:1186-1190`.
- Handlers de modal vivos: `oc_picker.js:1199-1203`; Escape: `static/js/main.js:231`.
- Refs en blanco y sin alta: `oc_picker.js:836-846`, `:852-857`.
- Layout ≤1100 px: `static/css/components.css:985-992`, `:907-916`, `:923-927`.
- Tokens de tema claro inexistentes: `components.css:434-440`, `:478-481`, `:579-590`.
- Fuga de pose: `static/js/components/pose_library.js:307-325`; `oc_picker.js:1019`.

### UPSCALER

- Modelos fantasma y fallback silencioso: `registry/upscalers-v1.json:4-33`; `app/upscale.py:408-421`; `app/routes/upscale.py:319-327`.
- Límite y presupuesto: `app/upscale.py:56`, `:647-653`, `:655-675`.
- Hires con UNET inexistente: `app/upscale.py:815`.
- Qwen 2K engañoso: `app/upscale.py:894`; `templates/index.html:982`.
- RIFE ×2 fijo: `app/upscale.py:1031-1054`.
- Botón Interpolar pisado: `static/js/tabs/upscaler.js:720`, `:891`, `:906`.

## 7. Anexo — recordatorios para 2.5.1

No se desarrolla aquí. Se anota para que el consultor lo tenga en cuenta en el plan de 2.5.1:

1. **Clasificación avanzada y multicapa** de modelos, con agente apoyado por la Guía y `SKILL.md`.
2. **Curación de preprompts por modelo** a partir de la entrada web e indicaciones del autor; la app solo mantiene la base editable.
3. **Módulo PNG de poses**: añadir las poses por PNG, además de los esqueletos, y usarlas como referencia real en Editor/Imagen.
4. Cualquier ampliación de perfiles avanzados (Illustrious/Pony/NoobAI u otros) que requiera investigación del agente.
