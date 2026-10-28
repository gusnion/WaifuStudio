# Galería

- Persistencia en `data/waifu.db` (WAL) y copias en `data/gallery/<id>/`.
- `GET /api/gallery` pagina y filtra por tipo; `GET /media/{id}/{name}` sirve el archivo.
- No borres `data/` ni sobrescribas archivos del usuario.
- Para reutilizar parámetros, lee el manifiesto de la generación; no inventes defaults.
- Los clips con y sin audio conviven; usa `ffprobe` para comprobarlo.
