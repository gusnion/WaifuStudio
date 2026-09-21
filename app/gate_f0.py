"""Gate F0: 1 imagen real Anima end-to-end por el engine nuevo (M8-03b).

CLI: ``python -m app.gate_f0 [--seed 42] [--graph E:\\IA\\WAIFU\\workflows\\anima_base.json]``.

Envia el grafo API congelado (perfil certificado Anima: Anima-2.9B-preview-v1,
320x576, 20 pasos, cfg 4.0, euler/sgm_uniform, seed 42) con ``ComfyEngine.submit``,
espera con ``wait`` y extrae los PNG con ``outputs``. Imprime prompt_id, rutas
absolutas y tamanos; exit 0 si hay >=1 PNG de peso > 0, exit 1 en cualquier fallo.

REQUIERE GPU LIBRE: el operador (usuario) confirma que ComfyUI no tiene trabajo en
curso. El runner NO comprueba ``/queue``, no espera y no pide confirmaciones.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import load_config
from app.engine import ComfyEngine, EngineError, load_graph

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GRAPH = APP_ROOT / "workflows" / "anima_base.json"


def _apply_seed(graph: dict, seed: int) -> int:
    """Fija ``seed`` en todo nodo que declare ese widget; devuelve cuantos."""
    applied = 0
    for node in graph.values():
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and "seed" in inputs:
            inputs["seed"] = int(seed)
            applied += 1
    return applied


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        prog="python -m app.gate_f0",
        description="Gate F0: 1 imagen Anima end-to-end (requiere GPU libre).",
    )
    parser.add_argument("--seed", type=int, default=42, help="seed del KSampler (default 42)")
    parser.add_argument(
        "--graph",
        default=str(DEFAULT_GRAPH),
        help="grafo API-format (default workflows\\anima_base.json)",
    )
    args = parser.parse_args(argv)

    print("AVISO: Gate F0 requiere GPU libre (usuario); no se comprueba la cola de ComfyUI.")

    try:
        graph = load_graph(args.graph)
        applied = _apply_seed(graph, args.seed)
        if not applied:
            print("AVISO: el grafo no tiene nodos con widget 'seed'; --seed ignorado.")
        engine = ComfyEngine(load_config())
        print(f"engine: {engine.base_url} | grafo: {args.graph} | seed: {args.seed}")
        prompt_id = engine.submit(graph)
        print(f"prompt_id: {prompt_id}", flush=True)
        entry = engine.wait(prompt_id)
        paths = engine.outputs(entry, expected_ext=("png",))
    except EngineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # fallo inesperado: mensaje claro, exit 1
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    ok = [path for path in paths if path.is_file() and path.stat().st_size > 0]
    if not ok:
        print("ERROR: el prompt termino sin PNG de output con peso > 0", file=sys.stderr)
        return 1
    for path in ok:
        print(f"{path} ({path.stat().st_size} bytes)")
    print(f"OK: {len(ok)} PNG generado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
