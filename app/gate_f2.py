"""Gate F2: 10 entradas fijas en espanol al LLM local en CPU (M8-21).

CLI: ``python -m app.gate_f2 [--k 3] [--out data\\gates\\f2]``.

Carga el GGUF local UNA vez con ``app.enhancer.load_local_llm`` (CPU, sin GPU ni
red) y pasa cada entrada por ``app.enhancer.enhance(preprompt="glossy", ...)``
con ``rating="nsfw"`` en las entradas adultas y ``rating="sfw"`` en el resto (el
determinismo de rating del enhancer garantiza el tag correcto). Por cada entrada
escribe
``<n>_<slug>.txt`` con positivo, negativo y raw (mas cabecera con la entrada), e
imprime ``n | len(positivo) | ok/warn``. Si ``enhance`` lanza, escribe el error y
lo cuenta como fallo duro. Resumen final en ``summary.txt`` (exit code, duracion
y la misma salida de consola).

Validaciones duras (exit 1): positivo no vacio; sin etiquetas de seccion
(``quality tags:``, ``rating tag:``, ``outfit/pose:``, ``art style:``); sin
``mosaic censoring`` ni ``bar censor`` en el positivo; positivo empieza por
``masterpiece`` (preprompt glossy); entradas nsfw con ``nsfw`` y ``uncensored``
en el positivo; entradas sfw sin ``nsfw`` ni ``uncensored``. Advertencias (no
fallan): tags del positivo con ``_`` que no sean ``score_<N>``; raw del LLM con
menos de 4 tags.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import APP_ROOT
from app.engine import EngineError
from app.enhancer import enhance, load_local_llm

DEFAULT_OUT = "data/gates/f2"
SECTION_LABELS = ("quality tags:", "rating tag:", "outfit/pose:", "art style:")
CENSOR_TAGS = ("mosaic censoring", "bar censor")
RATING_TAGS = ("nsfw", "uncensored")
SCORE_TAG_RE = re.compile(r"^score_\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class Case:
    """Una entrada fija del gate: slug de archivo, texto en espanol y rating."""

    slug: str
    text: str
    rating: str | None = None


CASES: tuple[Case, ...] = (
    Case(
        "sfw_simple",
        "una chica sonriendo mientras camina por un parque",
    ),
    Case(
        "sfw_escena_compleja",
        "una mujer leyendo un libro junto a la ventana de una cafetería mientras "
        "llueve en la calle y varias personas pasan con paraguas",
    ),
    Case(
        "nsfw_acto_dos_personas",
        "un hombre y una mujer teniendo sexo vaginal en la cama, "
        "completamente desnudos",
        "nsfw",
    ),
    Case(
        "pose_accion",
        "una guerrera con armadura ligera saltando en el aire con su espada en alto",
    ),
    Case(
        "retrato",
        "retrato cercano de una mujer de pelo negro largo y ojos verdes con una "
        "sonrisa suave",
    ),
    Case(
        "paisaje_ciudad",
        "vista panorámica de una ciudad costera al atardecer con barcos en el "
        "puerto y luces encendidas",
    ),
    Case(
        "nsfw_pareja",
        "dos mujeres desnudas abrazándose en la ducha bajo el agua",
        "nsfw",
    ),
    Case(
        "detalle_vestuario",
        "primer plano de un vestido de encaje rojo con cintas de satén y botones "
        "dorados",
    ),
    Case(
        "expresion_animo",
        "chica con expresión de sorpresa y alegría, boca abierta y ojos brillantes",
    ),
    Case(
        "video_movimiento",
        "escena de video: una chica corriendo por un campo de flores al atardecer "
        "mientras el viento mueve su pelo y la cámara la sigue",
    ),
)


def tags(text: str) -> list[str]:
    """Tags separados por coma, sin vacios (mismo criterio que el planner)."""
    return [tag.strip() for tag in str(text).split(",") if tag.strip()]


def validate(
    positive: str, raw: str, rating: str | None = None
) -> tuple[list[str], list[str]]:
    """Devuelve ``(errores duros, advertencias)`` de una salida de ``enhance``.

    Los tags de censura, las etiquetas de seccion y los tags de rating se buscan
    en el positivo completo (preprompt + salida del LLM); el minimo de tags se
    mide en el raw del LLM, porque el positivo siempre lleva los 9 tags del
    preprompt glossy. Una entrada se considera sfw si ``rating`` no es ``nsfw``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    text = positive.strip() if isinstance(positive, str) else ""
    if not text:
        errors.append("positivo vacio")
        return errors, warnings
    lowered = text.lower()
    if not lowered.startswith("masterpiece"):
        errors.append("positivo sin prefijo 'masterpiece' (glossy)")
    for label in SECTION_LABELS:
        if label in lowered:
            errors.append(f"etiqueta de seccion en el positivo: {label!r}")
    for tag in CENSOR_TAGS:
        if tag in lowered:
            errors.append(f"tag de censura en el positivo: {tag!r}")
    positive_tags = {tag.lower() for tag in tags(text)}
    if rating == "nsfw":
        for tag in RATING_TAGS:
            if tag not in positive_tags:
                errors.append(f"nsfw sin el tag {tag!r}")
    else:
        for tag in RATING_TAGS:
            if tag in positive_tags:
                errors.append(f"entrada sfw con el tag {tag!r}")
    underscored = [
        tag for tag in tags(text) if "_" in tag and not SCORE_TAG_RE.match(tag)
    ]
    if underscored:
        warnings.append(
            "tags con '_' sin normalizar en el positivo: " + ", ".join(underscored)
        )
    if len(tags(raw)) < 4:
        warnings.append(f"raw con menos de 4 tags ({len(tags(raw))})")
    return errors, warnings


def _header(case: Case) -> str:
    return (
        f"# entrada: {case.slug}\n"
        f"# rating: {case.rating or 'sfw'}\n"
        f"# texto: {case.text}\n"
    )


def write_result(path: Path, case: Case, result: dict[str, str]) -> None:
    """Escribe positivo, negativo y raw en UTF-8."""
    body = (
        f"{_header(case)}\n"
        f"POSITIVE:\n{result['positive']}\n\n"
        f"NEGATIVE:\n{result['negative']}\n\n"
        f"RAW:\n{result['raw']}\n"
    )
    path.write_text(body, encoding="utf-8")


def write_error(path: Path, case: Case, error: str) -> None:
    """Escribe el fallo de la entrada (sin positivo/negativo/raw disponibles)."""
    path.write_text(f"{_header(case)}\nERROR:\n{error}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        prog="python -m app.gate_f2",
        description="Gate F2: 10 entradas fijas al LLM local en CPU (sin GPU ni red).",
    )
    parser.add_argument("--k", type=int, default=3, help="notas RAG por entrada (default 3)")
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="carpeta de salida (default data\\gates\\f2)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = APP_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    report: list[str] = []

    def say(message: str, *, err: bool = False) -> None:
        report.append(message)
        print(message, file=sys.stderr if err else sys.stdout, flush=True)

    def finish(code: int) -> int:
        summary = "\n".join(
            [f"# exit_code={code} elapsed_s={time.monotonic() - started:.0f}", *report]
        )
        (out_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
        return code

    say(f"entradas: {len(CASES)} | RAG k={args.k} | out: {out_dir}")
    say("cargando LLM local (CPU, una vez)...")
    try:
        llm = load_local_llm()
    except EngineError as exc:
        say(f"ERROR: {exc}", err=True)
        return finish(1)
    except Exception as exc:
        say(f"ERROR: {type(exc).__name__}: {exc}", err=True)
        return finish(1)

    failures = 0
    for number, case in enumerate(CASES, start=1):
        path = out_dir / f"{number:02d}_{case.slug}.txt"
        effective_rating = case.rating or "sfw"
        try:
            result = enhance(
                case.text,
                preprompt="glossy",
                rating=effective_rating,
                llm=llm,
                k=args.k,
            )
            write_result(path, case, result)
            errors, warnings = validate(result["positive"], result["raw"], effective_rating)
            length = len(result["positive"])
        except EngineError as exc:
            failures += 1
            write_error(path, case, str(exc))
            say(f"{number:02d} | 0 | FAIL: {exc}")
            continue
        except Exception as exc:
            failures += 1
            write_error(path, case, f"{type(exc).__name__}: {exc}")
            say(f"{number:02d} | 0 | FAIL: {type(exc).__name__}: {exc}")
            continue

        if errors:
            failures += 1
            status = "FAIL"
            detail = "; ".join(errors)
        elif warnings:
            status = "warn"
            detail = "; ".join(warnings)
        else:
            status = "ok"
            detail = ""
        suffix = f" | {detail}" if detail else ""
        say(f"{number:02d} | {length} | {status}{suffix}")

    if failures:
        say(
            f"ERROR: Gate F2 fallo en {failures}/{len(CASES)} entrada(s)",
            err=True,
        )
        return finish(1)
    say(f"OK: {len(CASES)} entrada(s) sin fallos duros")
    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
