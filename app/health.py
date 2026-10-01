"""Smoke CLI de salud: rutas configuradas, ping al engine ComfyUI y estado del LLM."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request

from app.config import describe, load_config
from app.enhancer import LLM_URL_ENV, server_llm_state

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
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="falla (exit 1) si no hay WAIFU_LLM_URL o el servidor LLM no responde",
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

    llm_url = os.environ.get(LLM_URL_ENV, "").strip()
    llm_ok = False
    if llm_url:
        llm_state, llm_detail = server_llm_state(llm_url)
        llm_ok = llm_state == "ready"
        if llm_state == "ready":
            print("llm: LISTO")
        elif llm_state == "loading":
            print(f"llm: CARGANDO ({llm_detail})")
        else:
            print(f"llm: OFFLINE ({llm_detail})")
    else:
        print("llm: local (llama-cpp)")

    if not critical_ok:
        print("Resultado: FALLO (falta ruta critica)")
        return 1
    if args.require_engine and not engine_ok:
        print("Resultado: FALLO (engine requerido y no responde)")
        return 1
    if args.require_llm and not llm_ok:
        print("Resultado: FALLO (LLM requerido y no responde)")
        return 1
    print("Resultado: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
