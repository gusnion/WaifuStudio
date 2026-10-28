# Addons

- Un addon es un `.zip` con `addon.json`; se importa desactivado.
- Valida `requires_core`, manifiesto y rutas seguras antes de extraer.
- Usa `POST /api/addons/import`, `POST /api/addons/{id}/enable` y `/disable`.
- Los slots exclusivos no pueden coexistir activos; el error debe explicar el motivo.
- `rollback` desactiva el addon; no borra archivos del usuario.
