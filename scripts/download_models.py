"""Script de descarga verificada de modelos para M15 (VDN-H3 y Ref2VA DiT).

Permite descargar con reanudacion (-C -) y verificacion de tamano:
  - VDN (8-pasos): checkpoint INT8 ConvRot, configs, adapters y adaln_affine (~2.3 GB)
  - Ref2VA (Referencias DiT): minimax_h3_ref2va_pruned_int8_convrot.safetensors (~20.9 GB)

Uso:
  python scripts/download_models.py --vdn
  python scripts/download_models.py --ref2va
  python scripts/download_models.py --all
  python scripts/download_models.py --check
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
COMFY_ROOT = APP_ROOT / "ComfyUI"

VDN_BASE_URL = "https://huggingface.co/drbaph/vdn-minimax-h3-int8-convrot-comfyui"
ADALN_BASE_URL = "https://huggingface.co/multimodalart/MiniMax-H3-Pruned"
REF2VA_DIT_URL = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors"

# Especificacion de archivos VDN (~2.3 GB total)
VDN_TARGET_DIR = COMFY_ROOT / "models" / "vdn" / "vdn-minimax-h3-int8-convrot-comfyui"
VDN_FILES = [
    {
        "id": "model_spec",
        "rel": "model_spec.json",
        "url": f"{VDN_BASE_URL}/raw/main/model_spec.json",
        "min_bytes": 1000,
    },
    {
        "id": "metadata",
        "rel": "metadata.json",
        "url": f"{VDN_BASE_URL}/raw/main/metadata.json",
        "min_bytes": 100,
    },
    {
        "id": "linear_branch_config",
        "rel": "linear_branch/config.json",
        "url": f"{VDN_BASE_URL}/raw/main/linear_branch/config.json",
        "min_bytes": 100,
    },
    {
        "id": "linear_branch_weights",
        "rel": "linear_branch/model_int8_convrot_comfyui.safetensors",
        "url": f"{VDN_BASE_URL}/resolve/main/linear_branch/model_int8_convrot_comfyui.safetensors",
        "expected_bytes": 2304371056,
    },
    {
        "id": "adapter_default_config",
        "rel": "adapters/default/adapter_config.json",
        "url": f"{VDN_BASE_URL}/raw/main/adapters/default/adapter_config.json",
        "min_bytes": 100,
    },
    {
        "id": "adapter_default_weights",
        "rel": "adapters/default/adapter_model.safetensors",
        "url": f"{VDN_BASE_URL}/resolve/main/adapters/default/adapter_model.safetensors",
        "min_bytes": 1000000,
    },
    {
        "id": "adapter_turbo_config",
        "rel": "adapters/turbo/adapter_config.json",
        "url": f"{VDN_BASE_URL}/raw/main/adapters/turbo/adapter_config.json",
        "min_bytes": 100,
    },
    {
        "id": "adapter_turbo_weights",
        "rel": "adapters/turbo/adapter_model.safetensors",
        "url": f"{VDN_BASE_URL}/resolve/main/adapters/turbo/adapter_model.safetensors",
        "min_bytes": 1000000,
    },
    {
        "id": "adaln_affine_fl2va",
        "rel": "adaln_affine.safetensors",
        "url": f"{ADALN_BASE_URL}/resolve/main/transformer/adaln_affine.safetensors",
        "expected_bytes": 96960,
    },
]

# Especificacion de archivos Ref2VA DiT (~20.9 GB)
REF2VA_TARGET_DIR = COMFY_ROOT / "models" / "diffusion_models"
REF2VA_FILES = [
    {
        "id": "ref2va_dit_int8",
        "rel": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        "url": REF2VA_DIT_URL,
        "expected_bytes": 20970379616,
    },
    {
        "id": "adaln_affine_ref2va",
        "rel": "adaln_affine_ref2va.safetensors",
        "target_dir": VDN_TARGET_DIR,
        "url": f"{ADALN_BASE_URL}/resolve/main/transformer_ref/adaln_affine.safetensors",
        "expected_bytes": 96960,
    },
]


def _find_curl() -> str:
    path = shutil.which("curl") or shutil.which("curl.exe")
    if not path:
        cand = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "curl.exe"
        if cand.is_file():
            return str(cand)
    if not path:
        raise SystemExit("Error: curl.exe no encontrado en el sistema.")
    return str(path)


def download_file(curl_bin: str, url: str, dest_path: Path, expected_bytes: int | None = None, min_bytes: int | None = None) -> bool:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.is_file():
        actual = dest_path.stat().st_size
        if expected_bytes and actual == expected_bytes:
            print(f"  [OK] Ya presente: {dest_path.name} ({actual / (1024**2):.1f} MB)")
            return True
        if min_bytes and actual >= min_bytes:
            print(f"  [OK] Ya presente: {dest_path.name} ({actual} bytes)")
            return True

    part_path = dest_path.with_name(dest_path.name + ".part")
    print(f"  --> Descargando {dest_path.name} desde {url}...")
    cmd = [
        curl_bin,
        "-L",
        "--fail",
        "--retry", "3",
        "--retry-delay", "2",
        "-C", "-",
        "-o", str(part_path),
        url,
    ]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"  [ERROR] Fallo la descarga de {dest_path.name} (exit {res.returncode})")
        return False

    if not part_path.is_file():
        print(f"  [ERROR] Archivo parcial no encontrado: {part_path}")
        return False

    actual = part_path.stat().st_size
    if expected_bytes and actual != expected_bytes:
        print(f"  [AVISO] Tamano recibido {actual} != esperado {expected_bytes}")
    elif min_bytes and actual < min_bytes:
        print(f"  [ERROR] Archivo incompleto: {actual} < minimo {min_bytes}")
        return False

    if dest_path.is_file():
        dest_path.unlink()
    part_path.rename(dest_path)
    print(f"  [OK] Completado: {dest_path.name} ({dest_path.stat().st_size / (1024**2):.1f} MB)")
    return True


def check_models():
    print("=== Estado de modelos en disco ===")
    print(f"Directorio VDN: {VDN_TARGET_DIR}")
    vdn_ok = True
    for spec in VDN_FILES:
        target = VDN_TARGET_DIR / spec["rel"]
        if target.is_file():
            print(f"  [OK] {spec['rel']}: {target.stat().st_size / (1024**2):.2f} MB")
        else:
            print(f"  [FALTA] {spec['rel']}")
            vdn_ok = False

    print(f"\nDirectorio Ref2VA DiT: {REF2VA_TARGET_DIR}")
    ref_ok = True
    for spec in REF2VA_FILES:
        base_dir = spec.get("target_dir", REF2VA_TARGET_DIR)
        target = base_dir / spec["rel"]
        if target.is_file():
            print(f"  [OK] {spec['rel']}: {target.stat().st_size / (1024**3):.2f} GB")
        else:
            print(f"  [FALTA] {spec['rel']}")
            ref_ok = False

    return vdn_ok, ref_ok


def download_vdn(curl_bin: str) -> bool:
    print(f"\n=== Descargando pesos y config de VDN-H3 (INT8 ConvRot) ===")
    print(f"Destino: {VDN_TARGET_DIR}")
    all_ok = True
    for spec in VDN_FILES:
        target = VDN_TARGET_DIR / spec["rel"]
        ok = download_file(
            curl_bin,
            spec["url"],
            target,
            expected_bytes=spec.get("expected_bytes"),
            min_bytes=spec.get("min_bytes"),
        )
        if not ok:
            all_ok = False
            break
    return all_ok


def download_ref2va(curl_bin: str) -> bool:
    print(f"\n=== Descargando modelo DiT Ref2VA (INT8 ConvRot ~20.9 GB) ===")
    print(f"Destino: {REF2VA_TARGET_DIR}")
    all_ok = True
    for spec in REF2VA_FILES:
        base_dir = spec.get("target_dir", REF2VA_TARGET_DIR)
        target = base_dir / spec["rel"]
        ok = download_file(
            curl_bin,
            spec["url"],
            target,
            expected_bytes=spec.get("expected_bytes"),
            min_bytes=spec.get("min_bytes"),
        )
        if not ok:
            all_ok = False
            break
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Descargador de pesos VDN-H3 y Ref2VA")
    parser.add_argument("--vdn", action="store_true", help="Descargar pesos de VDN-H3 (~2.3 GB)")
    parser.add_argument("--ref2va", action="store_true", help="Descargar DiT Ref2VA (~20.9 GB)")
    parser.add_argument("--all", action="store_true", help="Descargar VDN y Ref2VA")
    parser.add_argument("--check", action="store_true", help="Verificar presencia de modelos")
    args = parser.parse_args()

    if args.check or (not args.vdn and not args.ref2va and not args.all):
        check_models()
        if not (args.vdn or args.ref2va or args.all):
            return

    curl_bin = _find_curl()
    if args.vdn or args.all:
        if not download_vdn(curl_bin):
            print("\n[ERROR] Descarga de VDN incompleta.")
            sys.exit(1)

    if args.ref2va or args.all:
        if not download_ref2va(curl_bin):
            print("\n[ERROR] Descarga de Ref2VA incompleta.")
            sys.exit(1)

    print("\n=== Verificacion final ===")
    check_models()


if __name__ == "__main__":
    main()
