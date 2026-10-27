# Release checklist — WAIFU STUDIO 2.x

Estado: 2026-10-27. Esta lista separa lo verificado en la sesión de lo que
requiere publicación externa.

## Criterios de terminada

| # | Criterio | Estado | Evidencia / pendiente |
|---|---|---|---|
| 1 | Instalación limpia + primera imagen sin leer nada | **Hecho (G:)** | `G:\IA\WAIFU-clean`, instalador 0.42.5, `/api/first-run ready=true`, imagen 512×768 generada |
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

Resultado esperado actual: **1.641 tests OK, 1 skipped**; tests JS OK.

## Instalación limpia (verificada en G:)

Se instaló con `install.bat -SkipModels -SkipLlm -NoUserEnv -NoShortcut` en
`G:\IA\WAIFU-clean`, se copiaron los tres checkpoints oficiales y se generó
la imagen `G:\IA\WAIFU-clean\data\gallery\2\imagen_00002_.png` (512×768 RGB).
El motor respondió con RTX 3060 y `/api/first-run` quedó `ready=true`.

## Publicación (pendiente)

```powershell
git tag -a v2.1.0 -m "WAIFU STUDIO 2.1.0"
git push origin main --tags
```

No se ejecutó: el encargo prohíbe publicar sin autorización explícita.
