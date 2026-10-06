# tools/custom_nodes/waifu_vdn_h3

Nodo ComfyUI propio de WaifuStudio para integración de **VideoDeltaNet (VDN)** en MiniMax H3.

## Funcionalidad y Arquitectura
- Habilita la ejecución ultra-rápida de MiniMax H3 en **8 pasos nativos** mediante destilación DMD (Diffusion Matching Distillation).
- **Modo actual (LoRA 8-step)**: La aceleración principal opera a través del adaptador LoRA `vdn_minimax_h3_step250_comfyui.safetensors` inyectado mediante `LoraLoaderModelOnly`, compatible con los pipelines y schedulers certificados de ComfyUI.
- **Nodo `WaifuVideoDeltaNetApply`**: Conector arquitectónico preparado para inyectar la atención delta y parámetros de cuantización ConvRot cuando se utilicen checkpoints DiT INT8 directamente (`vdn_minimax_h3_int8_convrot.safetensors`).
- Permite generar vídeo continuo en una RTX 3060 12 GB ahorrando ~4.7 GB de VRAM de pico en resoluciones estándar.

## Uso
El nodo se enlaza automáticamente a `ComfyUI/custom_nodes/waifu_vdn_h3` como junction durante la instalación (`install.ps1`).
