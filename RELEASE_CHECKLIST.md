# Release checklist — WAIFU STUDIO 2.x

Estado: 2026-10-26. Esta lista separa lo verificado en la sesión de lo que
requiere una máquina limpia o publicación externa.

## Criterios de terminada

| # | Criterio | Estado | Evidencia / pendiente |
|---|---|---|---|
| 1 | Instalación limpia + primera imagen sin leer nada | **Pendiente** | Requiere una máquina Windows limpia; el `/api/first-run` y el instalador ya existen. |
| 2 | Defaults por modelo con set oficial | **Hecho** | Animagine, RealVisXL y Juggernaut; API `PUT /api/models/{id}/defaults`. |
| 3 | Pestañas funcionan o llevan beta visible | **Hecho** | Imagen, Vídeo, Editor, Upscaler, Timeline, Galería y Addons; badges beta existentes. |
| 4 | Licencia 2.1 aceptada antes del Editor | **Hecho** | `app/editor_license.py`; 403 sin aceptación. |
| 5 | Addon ZIP importado, validado, desactivado y activado | **Hecho** | `/api/addons/import`, slots exclusivos y estado persistido. |
| 6 | Tema claro/oscuro AA | **Hecho** | `tokens.css` + toggle persistido; contraste 14.82/7.80/6.48. |
| 7 | Documentación = código | **Parcial** | README/AGENTS/SKILL/8 guías actualizados; falta auditoría final de cifras. |
| 8 | Avisos completos + hashes fijados | **Parcial** | Manifiestos Wan/modelos y FFmpeg verificado; faltan textos de algunas familias. |

## Verificación local reproducible

```powershell
cd E:\IA\WAIFU
& .\.venv\Scripts\python.exe -m unittest discover -s tests
Get-ChildItem tests\*.mjs | ForEach-Object { node $_.FullName }
& .\.venv\Scripts\python.exe -m app.health
```

Resultado esperado actual: **1.640 tests OK, 1 skipped**; tests JS OK.

## Instalación limpia (pendiente)

En una máquina Windows sin Python/ComfyUI:

```powershell
git clone https://github.com/gusnion/WaifuStudio.git
cd WaifuStudio
.\install.bat -SkipModels -SkipLlm
.\start.bat
```

Después: `GET /api/first-run` debe pasar a `ready=true`; generar una imagen
pequeña, el editor, un upscale y un vídeo Wan de 1 s.

## Publicación (pendiente)

```powershell
git tag -a v2.1.0 -m "WAIFU STUDIO 2.1.0"
git push origin main --tags
```

No se ejecutó: el encargo prohíbe publicar sin autorización explícita.
