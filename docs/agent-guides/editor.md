# Editor Qwen

- Requiere Qwen-Image 2.1 UC y aceptación explícita de la licencia.
- Acepta hasta 10 referencias y `preserve_structure`.
- Usa `POST /api/editor/generate`; consulta el job en `/api/jobs/{id}`.
- No prometas inpaint por máscara si el modelo o el nodo no están disponibles.
- Verifica que el resultado queda en la galería y que el original no se sobrescribe.
