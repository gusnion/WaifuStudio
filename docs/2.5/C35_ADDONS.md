# C-35 — Activador de addons

Verificado el 2026-10-27 con `python -m unittest tests.test_addons`: **8 tests OK**.

- `app/addons.py:148` — `import_addon`: valida ZIP, `addon.json`, rutas seguras y `requires_core`; instala desactivado.
- `app/addons.py:233` — `set_addon_enabled`: activa, desactiva y aplica slots exclusivos.
- `app/routes/addons.py:21` — `POST /api/addons/import`.
- `app/routes/addons.py:40/48` — enable/disable.
- `app/routes/addons.py:56` — rollback (desactiva el addon).
- `tests/test_addons.py:41` — importa desactivado y activa/desactiva.
- `tests/test_addons.py:51/55/60` — rechaza ZIP inválido, ruta insegura y `requires_core` incompatible.

No se borran archivos del usuario: rollback desactiva y conserva el addon.
