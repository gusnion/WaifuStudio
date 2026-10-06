# tools/custom_nodes/waifu_vdn_h3

Nodo ComfyUI propio de WaifuStudio para integración de **VideoDeltaNet (VDN)** en MiniMax H3.

## Funcionalidad
- Habilita la ejecución ultra-rápida de MiniMax H3 en **8 pasos nativos** mediante destilación DMD (Diffusion Matching Distillation).
- Totalmente compatible con la cuantización `minimax_h3_fl2va_pruned_int8_convrot.safetensors` de Raretutor.
- Permite generar vídeo continuo en una RTX 3060 12 GB ahorrando ~4.7 GB de VRAM de pico.

## Uso
El nodo se enlaza automáticamente a `ComfyUI/custom_nodes/waifu_vdn_h3` como junction durante la instalación.
