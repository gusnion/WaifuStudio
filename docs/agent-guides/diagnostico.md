# Diagnóstico

- Ejecuta `python -m app.health` y revisa app `:8765`, engine `:8288` y LLM `:8290`.
- `python -m unittest discover -s tests` es la suite offline; no requiere GPU.
- Comprueba `ffmpeg` y `ffprobe` en `tools/ffmpeg/`.
- Si el engine usa la GPU equivocada, revisa `CUDA_DEVICE_ORDER=PCI_BUS_ID` y `/system_stats`.
- No borres modelos, `data/` ni configuraciones para “arreglar” un fallo.
