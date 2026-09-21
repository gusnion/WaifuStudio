"""Smoke CLI de salud: rutas configuradas y ping al engine ComfyUI."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request

from app.config import describe, load_config

ENGINE_TIMEOUT = 2.0


def _check_path(label: str, path, critical: bool = True) -> bool:
    exists = path.exists()
    print(f"  {label}: {'OK' if exists else 'MISSING'}")
    return exists or not critical


def _ping_engine(url: str) -> tuple[bool, str]:
    endpoint = url.rstrip("/") + "/system_stats"
    try:
        with urllib.request.urlopen(endpoint, timeout=ENGINE_TIMEOUT) as response:
            response.read(1)
    except urllib.error.URLError as exc:
        return False, str(exc.reason)[:80]
    except OSError as exc:
        return False, str(exc)[:80]
    except ValueError:
        return False, "URL invalida"
    return True, "OK"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Smoke de salud de WAIFU")
    parser.add_argument(
        "--require-engine",
        action="store_true",
        help="falla (exit 1) si el engine no responde",
    )
    args = parser.parse_args(argv)

    cfg = load_config()

    print("Config:")
    for line in describe(cfg):
        print(f"  {line}")

    print("Rutas:")
    critical_ok = True
    critical_ok &= _check_path("comfy_root", cfg.comfy_root)
    critical_ok &= _check_path("comfy_workflows_dir", cfg.comfy_workflows_dir)
    critical_ok &= _check_path("comfy_output_dir", cfg.comfy_output_dir)
    _check_path("data_dir", cfg.data_dir, critical=False)

    engine_ok, reason = _ping_engine(cfg.comfy_url)
    print(f"engine: {'OK' if engine_ok else f'UNREACHABLE ({reason})'}")

    if not critical_ok:
        print("Resultado: FALLO (falta ruta critica)")
        return 1
    if args.require_engine and not engine_ok:
        print("Resultado: FALLO (engine requerido y no responde)")
        return 1
    print("Resultado: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
