# Upscaler

- RealESRGAN x2/x4 para imagen y vídeo; RIFE para interpolación de FPS.
- El comparador antes/después usa el original y el resultado, no una miniatura.
- En vídeo se conserva el audio del origen salvo que el flujo indique lo contrario.
- Usa `POST /api/upscale` y revisa el resultado en la galería.
- Verifica que el archivo de salida existe y que el job terminó sin error.
