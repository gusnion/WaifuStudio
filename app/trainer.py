"""Entrenador de LoRA desde el OC (M9-E1): dataset, config y runner externo.

Pipeline CPU/testeable sin GPU ni red: `prepare_dataset` copia imagenes de la
galeria con sus captions (y, con `tagger`, tags WD14 auto-captionados),
`write_config` escribe el TOML del entrenador, `run_training` lanza el comando
externo (`WAIFU_TRAINER_CMD`) volcando el log y `register_lora` copia el
`.safetensors` a `ComfyUI\\models\\loras\\waifu` y lo registra en
`registry\\loras.json`. El entrenador real vive en `tools/kohya` (checkout de
`kohya-ss/sd-scripts` v0.12.0 con `networks.lora_anima`, venv propio y wrapper
`run_waifu_train.py` que consume este TOML); aqui solo se orquesta (el servidor
encola `kind="train"`).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app import loras
from app.characters import prompt_from_tags
from app.engine import EngineError

MIN_IMAGES = 10
MAX_IMAGES = 50
TRAINER_CMD_ENV = "WAIFU_TRAINER_CMD"
DEFAULT_TIMEOUT_S = 4 * 3600
DEFAULT_TAG_THRESHOLD = 0.35
CONFIG_FILENAME = "train_config.toml"
CONFIG_COMMENT = "consumida por tools/kohya/run_waifu_train.py (sd-scripts + networks.lora_anima)"
LORAS_SUBDIR = "waifu"


def _require_char(char: object) -> dict:
    """Valida el OC minimo (dict con id entero positivo)."""
    if not isinstance(char, dict):
        raise EngineError(
            f"OC invalido: se esperaba dict, recibido {type(char).__name__}"
        )
    char_id = char.get("id")
    if isinstance(char_id, bool) or not isinstance(char_id, int) or char_id <= 0:
        raise EngineError(f"OC sin id valido: {char_id!r}")
    return char


def _require_trigger(trigger: object) -> str:
    if not isinstance(trigger, str) or not trigger.strip():
        raise EngineError(f"trigger requerido: {trigger!r}")
    return trigger.strip()


def _require_gen_ids(gen_ids: object) -> list[int]:
    """10..50 enteros unicos no bool; EngineError con el motivo exacto."""
    if not isinstance(gen_ids, list):
        raise EngineError(
            f"gen_ids invalido: se esperaba lista, recibido {type(gen_ids).__name__}"
        )
    cleaned: list[int] = []
    for gen_id in gen_ids:
        if isinstance(gen_id, bool) or not isinstance(gen_id, int):
            raise EngineError(f"gen_id invalido: {gen_id!r}")
        if gen_id in cleaned:
            raise EngineError(f"gen_id duplicado: {gen_id}")
        cleaned.append(gen_id)
    if len(cleaned) < MIN_IMAGES or len(cleaned) > MAX_IMAGES:
        raise EngineError(
            f"se necesitan entre {MIN_IMAGES} y {MAX_IMAGES} imagenes para "
            f"entrenar: {len(cleaned)}"
        )
    return cleaned


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EngineError(f"{label} invalido: {value!r}")
    return value


def _positive_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise EngineError(f"{label} invalido: {value!r}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineError(f"{label} invalido: {value!r}") from exc
    if not math.isfinite(result) or result <= 0:
        raise EngineError(f"{label} invalido: {value!r}")
    return result


def _require_threshold(value: object) -> float:
    """Umbral de tags WD14: float finito en [0.01, 0.99]; EngineError si no."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineError(f"tag_threshold invalido: {value!r}")
    result = float(value)
    if not math.isfinite(result) or not 0.01 <= result <= 0.99:
        raise EngineError(f"tag_threshold invalido: {value!r} (rango 0.01-0.99)")
    return result


def _clean_tags(tags: object) -> list[str]:
    """Tags crudos del tagger -> str limpios, sin vacios y sin repetidos.

    Acepta una lista/tupla o un str (separado por comas); ignora cualquier otro
    elemento que no sea str; deduplica case-insensitive conservando la primera
    aparicion.
    """
    if isinstance(tags, str):
        items: list[object] = tags.split(",")
    elif isinstance(tags, (list, tuple)):
        items = list(tags)
    else:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in items:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if not tag:
            continue
        folded = tag.lower()
        if folded in seen:
            continue
        seen.add(folded)
        cleaned.append(tag)
    return cleaned


def _caption(
    trigger: str, wd14_tags: object = None, oc_tags: object = None
) -> str:
    """``trigger, tags WD14, tags del OC`` deduplicado case-insensitive."""
    parts = [
        trigger,
        prompt_from_tags(_clean_tags(wd14_tags)),
        prompt_from_tags(oc_tags if oc_tags is not None else []),
    ]
    seen: set[str] = set()
    merged: list[str] = []
    for part in parts:
        for tag in part.split(","):
            tag = tag.strip()
            if not tag:
                continue
            folded = tag.lower()
            if folded in seen:
                continue
            seen.add(folded)
            merged.append(tag)
    return ", ".join(merged)


def _output_name(row: dict) -> str:
    """Primer nombre de salida de una fila del store (dict ``{"name"}`` o str)."""
    outputs = row.get("outputs") or []
    first = outputs[0] if outputs else None
    name = first.get("name") if isinstance(first, dict) else first
    return name if isinstance(name, str) else ""


def prepare_dataset(
    char: dict,
    gen_ids: list[int],
    *,
    store: Any,
    gallery_root: Path,
    out_dir: Path,
    trigger: str,
    tagger: Callable[[bytes], list[str]] | None = None,
    tag_threshold: float | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Copia la galeria a ``out_dir/<char_id>/img/NN.png`` con caption ``NN.txt``.

    Valida el OC, 10..50 ``gen_ids`` (enteros unicos), que cada generacion sea
    ``kind="image"`` y ``status="done"`` y que el archivo exista en
    ``gallery_root/<gen_id>/``. Con ``tagger`` (p. ej. ``VisionService.
    tagger_for(...)``) lee los bytes de cada imagen y auto-captiona:
    ``trigger, tags WD14, tags del OC`` con dedup case-insensitive; sin tagger
    el caption es ``trigger, tags del OC``. ``tag_threshold`` (opcional, float
    finito en [0.01, 0.99]) se valida y registra sin filtrar (el tagger ya
    viene configurado); ``progress(step, total)`` recibe ``(0, N)`` al empezar
    y ``(i, N)`` por imagen. Escribe ademas ``manifest.json`` (con
    ``wd14_tags`` por imagen, ``auto_tags`` y ``tag_threshold``) y devuelve
    ``{"dataset_dir", "images", "captions", "trigger", "auto_tags",
    "tag_threshold"}``; EngineError si algo falla.
    """
    char = _require_char(char)
    ids = _require_gen_ids(gen_ids)
    trigger = _require_trigger(trigger)
    threshold = _require_threshold(tag_threshold) if tag_threshold is not None else None
    if tagger is not None and not callable(tagger):
        raise EngineError(f"tagger invalido: {tagger!r}")
    auto_tags = tagger is not None
    char_id = char["id"]
    gallery_root = Path(gallery_root)
    dataset_dir = Path(out_dir) / str(char_id)
    img_dir = dataset_dir / "img"
    sources: list[tuple[int, Path]] = []
    for gen_id in ids:
        row = store.get(gen_id)
        if row is None:
            raise EngineError(f"generacion desconocida: {gen_id}")
        if row.get("kind") != "image":
            raise EngineError(
                f"generacion {gen_id} no es imagen (kind={row.get('kind')!r})"
            )
        if row.get("status") != "done":
            raise EngineError(
                f"generacion {gen_id} sin terminar (status={row.get('status')!r})"
            )
        name = _output_name(row)
        source = gallery_root / str(gen_id) / name if name else None
        if source is None or not source.is_file():
            raise EngineError(
                f"archivo de la generacion {gen_id} no encontrado: {name!r}"
            )
        sources.append((gen_id, source))
    total = len(sources)
    if progress is not None:
        progress(0, total)
    try:
        shutil.rmtree(img_dir, ignore_errors=True)
        img_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EngineError(f"no se pudo preparar el dataset {img_dir}: {exc}") from exc
    manifest: list[dict] = []
    for index, (gen_id, source) in enumerate(sources, start=1):
        wd14_tags: list[str] = []
        if auto_tags:
            try:
                raw_tags = tagger(source.read_bytes())
            except OSError as exc:
                raise EngineError(f"no se pudo leer {source}: {exc}") from exc
            wd14_tags = _clean_tags(raw_tags)
        caption = _caption(trigger, wd14_tags, char.get("tags"))
        stem = f"{index:02d}"
        image_path = img_dir / f"{stem}.png"
        caption_path = img_dir / f"{stem}.txt"
        try:
            shutil.copy2(source, image_path)
            caption_path.write_text(f"{caption}\n", encoding="utf-8")
        except OSError as exc:
            raise EngineError(f"copia de dataset fallo en {image_path}: {exc}") from exc
        manifest.append(
            {
                "gen_id": gen_id,
                "image": f"img/{stem}.png",
                "caption": f"img/{stem}.txt",
                "prompt": caption,
                "wd14_tags": wd14_tags,
            }
        )
        if progress is not None:
            progress(index, total)
    payload = {
        "character_id": char_id,
        "trigger": trigger,
        "auto_tags": auto_tags,
        "tag_threshold": threshold,
        "images": manifest,
    }
    try:
        (dataset_dir / "manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        raise EngineError(
            f"no se pudo escribir el manifest de {dataset_dir}: {exc}"
        ) from exc
    return {
        "dataset_dir": str(dataset_dir),
        "images": len(manifest),
        "captions": len(manifest),
        "trigger": trigger,
        "auto_tags": auto_tags,
        "tag_threshold": threshold,
    }


def _toml_str(value: object) -> str:
    """String TOML literal (sin escapes) para rutas Windows."""
    text = str(value)
    if "'" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"'{text}'"


def write_config(
    dataset_dir: Path,
    out_dir: Path,
    *,
    rank: int = 16,
    epochs: int = 10,
    lr: float = 1e-4,
) -> Path:
    """Escribe ``out_dir/train_config.toml`` para el entrenador externo (M10).

    Incluye ``source_image_dir``, ``output_dir``, ``output_name``, ``rank``,
    ``epochs``, ``lr``, ``resolution=512``, ``batch_size=1``,
    ``gradient_checkpointing=true`` y ``optimizer="AdamW8bit"``: las claves que
    consume ``tools/kohya/run_waifu_train.py`` (sd-scripts + networks.lora_anima).
    """
    dataset_dir = Path(dataset_dir)
    out_dir = Path(out_dir)
    rank = _positive_int(rank, "rank")
    epochs = _positive_int(epochs, "epochs")
    lr = _positive_float(lr, "lr")
    target = out_dir / CONFIG_FILENAME
    lines = [
        "# config de entrenamiento LoRA (M9-E1)",
        f"# {CONFIG_COMMENT}",
        f"source_image_dir = {_toml_str(dataset_dir)}",
        f"output_dir = {_toml_str(out_dir)}",
        f"output_name = {_toml_str(dataset_dir.name)}",
        f"rank = {rank}",
        f"epochs = {epochs}",
        f"lr = {lr:g}",
        "resolution = 512",
        "batch_size = 1",
        "gradient_checkpointing = true",
        f"optimizer = {_toml_str('AdamW8bit')}",
    ]
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise EngineError(f"no se pudo escribir la config {target}: {exc}") from exc
    return target


def _trainer_command(cmd: list[str] | None, env: dict | None) -> list[str]:
    """Comando del entrenador: ``cmd`` explicito o ``WAIFU_TRAINER_CMD``."""
    if cmd is not None:
        if not isinstance(cmd, (list, tuple)) or not cmd:
            raise EngineError(f"cmd de entrenador invalido: {cmd!r}")
        return [str(part) for part in cmd]
    source = env if env is not None else os.environ
    text = source.get(TRAINER_CMD_ENV, "")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise EngineError("entrenador no instalado (M10)")
    return text.split()


def _pump(stream: Any, handle: Any) -> None:
    """Vuelca el stream al log en streaming (si hay handle) y lo cierra."""
    try:
        for line in stream:
            if handle is not None:
                handle.write(line)
                handle.flush()
    finally:
        try:
            stream.close()
        except OSError:
            pass


def run_training(
    config_path: Path,
    *,
    cmd: list[str] | None = None,
    env: dict | None = None,
    log_path: Path | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> int:
    """Ejecuta ``cmd + [config_path]`` volcando stdout+stderr al log (append).

    Sin ``cmd`` usa ``WAIFU_TRAINER_CMD`` (lista separada por espacios);
    EngineError si no hay comando. Devuelve el exit code; si se agota
    ``timeout_s`` mata el proceso y lanza EngineError.
    """
    config_path = Path(config_path)
    if not config_path.is_file():
        raise EngineError(f"config de entrenamiento no encontrada: {config_path}")
    command = _trainer_command(cmd, env)
    timeout_s = _positive_float(timeout_s, "timeout_s")
    process_env = {**os.environ, **env} if env is not None else None
    handle = None
    if log_path is not None:
        log_path = Path(log_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = log_path.open("a", encoding="utf-8")
        except OSError as exc:
            raise EngineError(f"no se pudo abrir el log {log_path}: {exc}") from exc
    try:
        try:
            process = subprocess.Popen(
                [*command, str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=process_env,
            )
        except OSError as exc:
            raise EngineError(
                f"no se pudo lanzar el entrenador {command!r}: {exc}"
            ) from exc
        reader = threading.Thread(
            target=_pump, args=(process.stdout, handle), daemon=True
        )
        reader.start()
        try:
            code = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise EngineError(
                f"entrenamiento excedio {timeout_s:g}s: {config_path}"
            ) from None
        finally:
            reader.join(timeout=10)
        return int(code)
    finally:
        if handle is not None:
            handle.close()


def register_lora(
    char: dict,
    lora_path: Path,
    *,
    comfy_loras_dir: Path,
    trigger: str,
    display_name: str | None = None,
    registry_path: str | Path | None = None,
) -> dict:
    """Copia ``lora_path`` a ``comfy_loras_dir/waifu/<char_id>.safetensors``.

    Crea la entrada (familia ``anima``, peso 0.8, source M9-E, license local,
    notes con fecha) y la añade con ``loras.add_entry``; devuelve la entrada.
    """
    char = _require_char(char)
    trigger = _require_trigger(trigger)
    source = Path(lora_path)
    if source.suffix.lower() != ".safetensors":
        raise EngineError(f"lora no es .safetensors: {source.name!r}")
    if not source.is_file():
        raise EngineError(f"lora entrenada no encontrada: {source}")
    char_id = char["id"]
    directory = Path(comfy_loras_dir) / LORAS_SUBDIR
    target = directory / f"{char_id}.safetensors"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError as exc:
        raise EngineError(f"copia de lora fallo: {exc}") from exc
    name = (
        display_name.strip()
        if isinstance(display_name, str) and display_name.strip()
        else f"OC {char.get('name') or char_id}"
    )
    entry = {
        "id": f"oc-{char_id}",
        "family": "anima",
        "file": str(Path(LORAS_SUBDIR) / f"{char_id}.safetensors"),
        "display_name": name,
        "trigger": trigger,
        "default_weight": 0.8,
        "source": "entrenado local (M9-E)",
        "license": "local",
        "notes": f"entrenado {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    }
    return loras.add_entry(entry, path=registry_path)


def _default_trigger(char: dict) -> str:
    name = char.get("name")
    text = name.strip() if isinstance(name, str) else ""
    return text or f"oc{char['id']}"


def train_character(
    char: dict,
    gen_ids: list[int],
    *,
    store: Any,
    config: Any,
    trigger: str | None = None,
    rank: int = 16,
    epochs: int = 10,
    lr: float = 1e-4,
    cmd: list[str] | None = None,
    env: dict | None = None,
    log_path: Path | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    lora_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    comfy_loras_dir: str | Path | None = None,
    tagger: Callable[[bytes], list[str]] | None = None,
    tag_threshold: float | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Orquestador puro: prepare -> config -> run -> register (sin servidor).

    ``config`` es un ``EngineConfig``: la galeria sale de ``data_dir/gallery`` y
    el trabajo vive en ``data_dir/trainer``. ``tagger``, ``tag_threshold`` y
    ``progress`` se pasan tal cual a `prepare_dataset` (auto-caption WD14).
    Devuelve un dict de resultado con dataset, rutas, exit code y entrada
    registrada.
    """
    char = _require_char(char)
    char_id = char["id"]
    trigger = (
        _require_trigger(trigger) if trigger is not None else _default_trigger(char)
    )
    gallery_root = Path(config.data_dir) / "gallery"
    work_dir = Path(config.data_dir) / "trainer"
    dataset = prepare_dataset(
        char,
        gen_ids,
        store=store,
        gallery_root=gallery_root,
        out_dir=work_dir,
        trigger=trigger,
        tagger=tagger,
        tag_threshold=tag_threshold,
        progress=progress,
    )
    dataset_dir = Path(dataset["dataset_dir"])
    config_path = write_config(dataset_dir, work_dir, rank=rank, epochs=epochs, lr=lr)
    if log_path is None:
        log_path = work_dir / f"{char_id}.log"
    code = run_training(
        config_path, cmd=cmd, env=env, log_path=log_path, timeout_s=timeout_s
    )
    if code != 0:
        raise EngineError(f"entrenador termino con codigo {code}: ver {log_path}")
    trained = (
        Path(lora_path)
        if lora_path is not None
        else work_dir / f"{dataset_dir.name}.safetensors"
    )
    if not trained.is_file():
        raise EngineError(f"lora entrenada no encontrada: {trained}")
    loras_dir = (
        Path(comfy_loras_dir)
        if comfy_loras_dir is not None
        else Path(config.comfy_root) / "models" / "loras"
    )
    entry = register_lora(
        char,
        trained,
        comfy_loras_dir=loras_dir,
        trigger=trigger,
        registry_path=registry_path,
    )
    return {
        "character_id": char_id,
        "trigger": trigger,
        "dataset": dataset,
        "config_path": str(config_path),
        "log_path": str(log_path),
        "lora_path": str(trained),
        "exit_code": code,
        "entry": entry,
    }


__all__ = [
    "CONFIG_FILENAME",
    "DEFAULT_TAG_THRESHOLD",
    "DEFAULT_TIMEOUT_S",
    "MAX_IMAGES",
    "MIN_IMAGES",
    "TRAINER_CMD_ENV",
    "prepare_dataset",
    "register_lora",
    "run_training",
    "train_character",
    "write_config",
]
