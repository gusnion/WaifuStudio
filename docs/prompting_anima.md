# Manual de prompting Anima (local)

Guía local del prompt de imagen Anima. Fuentes certificadas: el `SYS_PROMPT` y el `NEGATIVE` del
planner legacy (`E:\IA\VIDEO\local_prompt_planner\local_planner.py`), sus preprompts de calidad
(`QUALITY_PREPROMPTS`) y la guía Anima resumida del usuario. No se documenta nada fuera de esas
fuentes: sin lore, sin parámetros de sampler y sin modelos inventados.

## Orden canónico de tags

`[calidad/meta/safety] [1girl/1boy] [character] [general]`

1. **Calidad/meta**: tags de calidad y metadatos.
2. **Sujeto**: `1girl`, `1boy`, `2girls`, etc.
3. **Character**: identidad/personaje cuando aplique.
4. **General**: ropa, pose, cuerpo, acto y entorno.

## Calidad y metadatos

- Familia `score_`: usar `score_7`, `score_8`, `score_9` para calidad alta.
- Espacios: los tags se separan con `, `; la excepción es `score_X`, que lleva guion bajo
  (`score_8`, nunca `score 8`).
- Normalización de la salida del LLM: en cada tag de «Mejorar prompt» el guion bajo se convierte
  en espacio (`coastal_city` → `coastal city`, `completely_nude` → `completely nude`), salvo
  `score_<N>` (`score_9`, `score_12`), que se conserva intacto.
- Calidad danbooru/anime recomendada por el planner: `masterpiece, best quality, very aesthetic,
  absurdres`.
- PROHIBIDO fotorrealismo: nada de `realistic`, `hyper-realistic`, `cinematic`, `photo`, `lifelike`.
- Estilo: ilustración anime; usar `anime`, `2D`, `cel shading` cuando aporte; nunca fotorrealismo.

## Safety / rating

- Ratings de safety: `safe`, `sensitive`, `nsfw`, `explicit`.
- El planner legacy usa el tag de rating `nsfw` para adulto y `sfw` para seguro; el rating puede
  viajar como línea de contexto y el LLM no debe copiarla a la salida.
- Anti-censura: en `nsfw` el positivo SIEMPRE incluye `uncensored` y NUNCA tags de censura
  (`mosaic censoring`, `bar censor`); la imagen debe salir sin censura.
- Determinismo de rating en «Mejorar prompt» (antes del preprompt, case-insensitive, por tags
  separados por comas y sin duplicar): `nsfw` garantiza `nsfw` y `uncensored` y elimina `sfw`;
  `sfw` garantiza `sfw` y elimina `nsfw` y `uncensored`; sin rating (`None`) no se toca el rating.
- No censurar ni suavizar la petición: nada de eufemismos tipo `seductive`, `confident` o `sensual`
  en lugar del acto o las partes del cuerpo realmente pedidos.
- Regla dura del planner: todos los personajes son adultos (21+); nunca menores, términos
  `child`/`teen`/`loli`, entornos escolares ni contenido que implique menores.

## Sujeto y contenido

- Empezar por el conteo: `1girl` para una mujer; añadir `1boy` y/o `2girls`, etc. si la petición
  implica más gente.
- Un acto o posición sexual SIEMPRE implica dos personas: incluir `1boy`, `hetero` (o `2girls` si
  ambas son mujeres) y los tags del acto cuando el usuario lo pida.
- Contenido con vocabulario danbooru: rasgos, ropa o `nude`/`completely nude`, pose y, si se pide,
  acto explícito y partes del cuerpo (`sex`, `vaginal sex`, `full nelson`).
- Mantener la intención exacta del usuario.

## Estructura del prompt

- Prompts descriptivos de 2+ frases: describir la escena con detalle (sujeto, acción, entorno,
  iluminación, encuadre) en vez de una lista mínima de palabras.
- La salida del planner es EXACTAMENTE UNA línea de tags danbooru en inglés separados por comas;
  sin etiquetas de sección (`quality tags:`, `rating tag:`, `outfit/pose:`, `art style:`), sin
  prosa, sin frases y sin explicaciones.
- Las líneas de contexto internas en español (`rating tag:`, `framing:`, `video:`) son SOLO
  referencia: nunca copiarlas ni traducirlas a la salida.

## Artistas

- Los tags de artista se escriben con `@` (p. ej. `@artist_name`) y van en la zona general/estilo.
- El negativo de `anima_default` rechaza `artist name`; no mezclar tags de artista con fotorrealismo.

## Negativos

- Negativo base del planner (calidad + anti-menores + anti-censura indirecta):
  `worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, blurry, mosaic
  censoring, bar censor`.
- Negativo de anatomía del preprompt `glossy`: `worst quality, low quality, score_1, score_2,
  score_3, blurry, jpeg artifacts, sepia, bad anatomy, bad hands, mutated hands, fused fingers,
  extra fingers, watermark, signature, logo`.

## Preprompts Anima

El LLM NO decide el preprompt: se aplica de forma determinista al positivo (prefijo) y al negativo
(sufijo), con dedup case-insensitive que conserva el orden.

| Nombre | Positivo (prefijo) | Negativo (sufijo) | Uso |
|---|---|---|---|
| `glossy` (default) | `masterpiece, best quality, absurdres, highres, score_7, score_8, score_9` | `worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, bad anatomy, bad hands, mutated hands, fused fingers, extra fingers, watermark, signature, logo` | acabado pulido; default de la familia |
| `anima_default` | `masterpiece, best quality, score_8` | `worst quality, low quality, score_1, score_2, score_3, artist name` | calidad estándar sin `score_9` |
| `not_glossy` | `newest, good quality, score_6, score_5, highres` | `low quality, score_1, score_2` | acabado menos brillante |
| `ninguno` | — | — | sin prefijo ni sufijo |

## Flujo «Mejorar prompt» (F2)

`app/enhancer.py` construye el mensaje (system = `SYS_PROMPT`; user = texto + notas RAG + `rating
tag` si viene), llama al LLM local inyectado y aplica el preprompt elegido con `apply_preprompt`.
Antes del preprompt normaliza la salida del LLM (`_` → espacio salvo `score_<N>`) y fuerza el
rating pedido según el determinismo de `nsfw`/`sfw`; el resultado (`raw` ya normalizado) y el
prompt final se guardan con el store `app/store.py` (prompt, negativo, params y salidas).
