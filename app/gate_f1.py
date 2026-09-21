"""Gate F1: 1 imagen por modelo del registro, end-to-end con el engine (M8-11b).

CLI: ``python -m app.gate_f1 [--model-id ID ...] [--seed 42] [--graph workflows\\anima_base.json]``.

Sin ``--model-id`` recorre todos los modelos del registro en orden. Por cada modelo carga el
grafo certificado, parchea los nodos UNETLoader/CLIPLoader/VAELoader con el ``profile`` de la
entrada (localizados por ``class_type``, no por id fijo) y fija ``--seed`` en todo nodo con
widget ``seed``; envia con ``ComfyEngine.submit``, espera el history (``wait``), extrae los PNG
(``outputs``) e imprime ``id | prompt_id | ruta | bytes``. Exit 0 solo si TODOS los modelos
generaron >=1 PNG de peso > 0; exit 1 con el detalle de cada fallo.

REQUIERE GPU LIBRE: el operador (usuario) confirma que ComfyUI no tiene trabajo en curso. El
runner NO comprueba ``/queue``, no espera y no pide confirmaciones.

``build_graph_for`` y ``run`` son testeables sin GPU (transporte inyectable en ``ComfyEngine``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from app.config import load_config
from app.engine import ComfyEngine, EngineError, load_graph
from app.graphs import patch_model
from app.registry import DEFAULT_PATH, ModelEntry, ModelRegistry

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GRAPH = APP_ROOT / "workflows" / "anima_base.json"


def build_graph_for(graph: dict, entry: ModelEntry, seed: int) -> dict:
    """Copia de ``graph`` con el perfil de ``entry`` y ``seed`` aplicados.

    No muta ``graph``. EngineError si falta UNETLoader, CLIPLoader, VAELoader o
    algun nodo con widget ``seed``.
    """
    return patch_model(graph, entry, seed)


def run(
    engine: ComfyEngine,
    graph: dict,
    entry: ModelEntry,
    seed: int,
    *,
    on_prompt_id: Callable[[str], None] | None = None,
) -> list[Path]:
    """Genera con ``entry``: parchea, ``submit``, ``wait`` y devuelve los PNG.

    ``on_prompt_id`` recibe el prompt_id en cuanto se encola (para logs).
    """
    prompt_id = engine.submit(build_graph_for(graph, entry, seed))
    if on_prompt_id is not None:
        on_prompt_id(prompt_id)
    history = engine.wait(prompt_id)
    return engine.outputs(history, expected_ext=("png",))


def _select_models(registry: ModelRegistry, model_ids: list[str] | None) -> list[ModelEntry]:
    if not model_ids:
        return registry.models
    return [registry.get(model_id) for model_id in model_ids]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        prog="python -m app.gate_f1",
        description="Gate F1: 1 imagen por modelo del registro (requiere GPU libre).",
    )
    parser.add_argument(
        "--model-id",
        action="append",
        default=None,
        help="id del registro a ejecutar (repetible; default: todos)",
    )
    parser.add_argument("--seed", type=int, default=42, help="seed de los samplers (default 42)")
    parser.add_argument(
        "--graph",
        default=str(DEFAULT_GRAPH),
        help="grafo API-format (default workflows\\anima_base.json)",
    )
    args = parser.parse_args(argv)

    print("AVISO: Gate F1 requiere GPU libre (usuario); no se comprueba la cola de ComfyUI.")

    try:
        registry = ModelRegistry.load(DEFAULT_PATH)
        models = _select_models(registry, args.model_id)
        base_graph = load_graph(args.graph)
        engine = ComfyEngine(load_config())
    except EngineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        f"engine: {engine.base_url} | grafo: {args.graph} | seed: {args.seed} "
        f"| modelos: {len(models)}"
    )

    failures = 0
    for entry in models:
        prompt_ids: list[str] = []
        try:
            paths = run(
                engine, base_graph, entry, args.seed, on_prompt_id=prompt_ids.append
            )
        except EngineError as exc:
            failures += 1
            print(f"ERROR: {entry.id}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:
            failures += 1
            print(f"ERROR: {entry.id}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        prompt_id = prompt_ids[0] if prompt_ids else "?"
        ok = [path for path in paths if path.is_file() and path.stat().st_size > 0]
        if not ok:
            failures += 1
            print(
                f"ERROR: {entry.id}: sin PNG de peso > 0 (prompt_id {prompt_id})",
                file=sys.stderr,
            )
            continue
        for path in ok:
            print(f"{entry.id} | {prompt_id} | {path} | {path.stat().st_size} bytes")

    if failures:
        print(
            f"ERROR: Gate F1 fallo en {failures}/{len(models)} modelo(s)",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {len(models)} modelo(s) generaron >=1 PNG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
