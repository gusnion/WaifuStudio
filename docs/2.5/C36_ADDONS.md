# C-36 — Slots y namespace de addons

Verificado el 2026-10-27 con `python -m unittest tests.test_addons`: **8 tests OK**.

- `app/addons.py:233` — aplica slots exclusivos y rechaza dos addons activos del mismo slot con motivo.
- `tests/test_addons.py:72` — `test_slots_exclusivos`: dos addons de preset conviven desactivados; al activar el segundo con el primero activo se rechaza; al desactivar el primero, el segundo activa.
- `requires_core` incompatible: `tests/test_addons.py:60`.
- Catálogo externo: `tests/test_addons.py:83/93`.

El namespace y los slots se validan antes de escribir el estado; no se toca `data/` de usuario.
