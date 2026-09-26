"""OCs guardables con referencias (M9-B1) y rasgos/extras (M9-B3) en la sqlite.

``CharacterStore`` comparte ``data/waifu.db`` con las generaciones: la tabla
``characters`` guarda name unico, tags (JSON, solo rasgos del personaje),
extras (JSON: ropa/entorno/safety...), preprompt de la familia anima, rating y
notes; ``character_refs`` apunta a copias locales bajo
``refs_root/<id>/<uuid>.<ext>``. ``split_character_tags`` separa rasgos de
extras con el catalogo real (``app.prompt_zones``), ``prompt_from_tags`` y
``prompt_from_extras`` componen textos deduplicados y ``profile`` resuelve
trigger vs rasgos buscando el LoRA ``oc-<id>`` en ``app.loras``. Sin red ni GPU.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import loras
from app.engine import EngineError
from app.preprompts import DEFAULT_FAMILY, DEFAULT_PREPROMPT, list_preprompts
from app.prompt_zones import classify_tag, general_subcat

RATINGS = ("sfw", "nsfw")
REF_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

_CHARACTERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    tags TEXT NOT NULL DEFAULT '[]',
    extras TEXT NOT NULL DEFAULT '[]',
    preprompt TEXT NOT NULL DEFAULT 'glossy',
    rating TEXT NOT NULL DEFAULT 'sfw',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

_REFS_SCHEMA = """
CREATE TABLE IF NOT EXISTS character_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    relpath TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CHARACTER_COLUMNS = "id, name, tags, extras, preprompt, rating, notes, created_at"
_REF_COLUMNS = "id, character_id, relpath, created_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise EngineError(f"name de OC requerido: {name!r}")
    return name.strip()


def _validate_tags(tags: object) -> list[str]:
    if not isinstance(tags, (list, tuple)):
        raise EngineError(f"tags de OC debe ser lista de str: {tags!r}")
    cleaned: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise EngineError(f"tag de OC invalido: {tag!r}")
        tag = tag.strip()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _validate_preprompt(preprompt: object) -> str:
    if not isinstance(preprompt, str):
        raise EngineError(f"preprompt de OC invalido: {preprompt!r}")
    if preprompt not in list_preprompts(DEFAULT_FAMILY):
        raise EngineError(f"preprompt de OC desconocido: {preprompt!r}")
    return preprompt


def _validate_rating(rating: object) -> str:
    if rating not in RATINGS:
        raise EngineError(f"rating de OC invalido; usar sfw|nsfw: {rating!r}")
    return rating


def _validate_notes(notes: object) -> str:
    if notes is None:
        return ""
    if not isinstance(notes, str):
        raise EngineError(f"notes de OC invalido: {notes!r}")
    return notes


def _merge_extras(*groups: list[str]) -> list[str]:
    """Une listas de extras deduplicando case-insensitive (primera aparicion)."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for tag in group:
            folded = tag.lower()
            if folded in seen:
                continue
            seen.add(folded)
            merged.append(tag)
    return merged


def _split_for_storage(
    tags: object, extras: object = None
) -> tuple[list[str], list[str]]:
    """Valida ``tags`` y ``extras`` y devuelve ``(traits, extras)`` sin perder nada."""
    split = split_character_tags(tags)
    explicit = _validate_tags(extras) if extras is not None else []
    return split["traits"], _merge_extras(split["extras"], explicit)


def is_sheet(relpath: str | Path) -> bool:
    """True si la ref es una hoja de catalogo (nombre con prefijo `sheet_`)."""
    return Path(str(relpath)).name.startswith("sheet_")


class CharacterStore:
    """Persistencia local de OCs y sus referencias; `init()` antes de usar."""

    def __init__(
        self, db_path: str | Path, *, refs_root: str | Path | None = None
    ) -> None:
        self.db_path = Path(db_path)
        self.refs_root = (
            Path(refs_root) if refs_root is not None else self.db_path.parent / "characters"
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init(self) -> None:
        """Crea el directorio padre y las tablas si faltan (idempotente).

        Migra ``characters.extras`` (M9-B3) con ``ALTER TABLE`` si falta.
        """
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn, conn:
                conn.execute(_CHARACTERS_SCHEMA)
                conn.execute(_REFS_SCHEMA)
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(characters)")
                }
                if "extras" not in columns:
                    conn.execute(
                        "ALTER TABLE characters "
                        "ADD COLUMN extras TEXT NOT NULL DEFAULT '[]'"
                    )
        except (sqlite3.Error, OSError) as exc:
            raise EngineError(f"characters init fallo en {self.db_path}: {exc}") from exc

    def add(
        self,
        name: str,
        tags: list[str],
        preprompt: str = DEFAULT_PREPROMPT,
        rating: str = "sfw",
        notes: str = "",
        extras: list[str] | None = None,
    ) -> int:
        """Inserta un OC y devuelve su id; EngineError si la validacion falla.

        ``tags`` guarda solo rasgos del personaje; el resto (ropa/entorno/
        safety...) pasa a ``extras`` junto con ``extras`` explicito.
        """
        clean_name = _validate_name(name)
        traits, clean_extras = _split_for_storage(tags, extras)
        clean_preprompt = _validate_preprompt(preprompt)
        clean_rating = _validate_rating(rating)
        clean_notes = _validate_notes(notes)
        created_at = _now()
        try:
            with closing(self._connect()) as conn, conn:
                existing = conn.execute(
                    "SELECT id FROM characters WHERE name = ?", (clean_name,)
                ).fetchone()
                if existing is not None:
                    raise EngineError(f"nombre de OC ya existe: {clean_name!r}")
                cursor = conn.execute(
                    "INSERT INTO characters "
                    "(name, tags, extras, preprompt, rating, notes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        clean_name,
                        json.dumps(traits),
                        json.dumps(clean_extras),
                        clean_preprompt,
                        clean_rating,
                        clean_notes,
                        created_at,
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise EngineError(f"nombre de OC ya existe: {clean_name!r}") from exc
        except sqlite3.Error as exc:
            raise EngineError(f"characters add fallo: {exc}") from exc

    def get(self, char_id: int) -> dict | None:
        """OC con tags deserializados, o None si no existe."""
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    f"SELECT {_CHARACTER_COLUMNS} FROM characters WHERE id = ?",
                    (char_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise EngineError(f"characters get {char_id} fallo: {exc}") from exc
        return self._row_to_dict(row) if row is not None else None

    def list(self) -> list[dict]:
        """OCs en orden de id ascendente."""
        try:
            with closing(self._connect()) as conn, conn:
                rows = conn.execute(
                    f"SELECT {_CHARACTER_COLUMNS} FROM characters ORDER BY id"
                ).fetchall()
        except sqlite3.Error as exc:
            raise EngineError(f"characters list fallo: {exc}") from exc
        return [self._row_to_dict(row) for row in rows]

    def profile(self, char_id: int, mode: str = "auto") -> dict:
        """Perfil de prompt del OC (M9-B3): trigger/rasgos, extras y LoRA.

        ``mode`` es ``auto|trigger|traits``: ``auto`` usa el trigger del LoRA
        ``oc-<id>`` si esta registrado y no esta vacio, si no los rasgos;
        ``trigger`` exige LoRA registrado (EngineError si falta); ``traits``
        compone los rasgos. Devuelve ``{"text", "mode", "extras", "lora"}`` con
        el modo resuelto y el LoRA ``{"id", "default_weight"}`` o None.
        EngineError si el OC no existe o el mode es invalido.
        """
        if mode not in ("auto", "trigger", "traits"):
            raise EngineError(
                f"mode de perfil invalido; usar auto|trigger|traits: {mode!r}"
            )
        row = self.get(char_id)
        if row is None:
            raise EngineError(f"OC desconocido: {char_id}")
        try:
            lora = loras.get(f"oc-{char_id}")
        except EngineError:
            lora = None
        resolved = mode
        if mode == "auto":
            resolved = (
                "trigger"
                if lora is not None and lora["trigger"].strip()
                else "traits"
            )
        if resolved == "trigger":
            if lora is None:
                raise EngineError(f"OC sin LoRA entrenado: oc-{char_id}")
            text = lora["trigger"].strip()
            if not text:
                raise EngineError(f"LoRA {lora['id']!r} sin trigger")
        else:
            text = prompt_from_tags(row["tags"])
        return {
            "text": text,
            "mode": resolved,
            "extras": list(row["extras"]),
            "lora": (
                {"id": lora["id"], "default_weight": lora["default_weight"]}
                if lora is not None
                else None
            ),
        }

    def update(
        self,
        char_id: int,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        extras: list[str] | None = None,
        preprompt: str | None = None,
        rating: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Actualiza solo los campos dados; False si el id no existe.

        Con ``tags`` los rasgos reemplazan a los guardados y los extras que
        traiga se suman a los existentes (o a ``extras``, que los reemplaza);
        sin tocar ``tags``/``extras`` los extras se preservan.
        """
        assignments: list[str] = []
        values: list[Any] = []
        if name is not None:
            assignments.append("name = ?")
            values.append(_validate_name(name))
        if tags is not None:
            split = split_character_tags(tags)
            stored = self.get(char_id)
            if extras is not None:
                current_extras = _validate_tags(extras)
            elif stored is not None:
                current_extras = list(stored["extras"])
            else:
                current_extras = []
            assignments.append("tags = ?")
            assignments.append("extras = ?")
            values.append(json.dumps(split["traits"]))
            values.append(json.dumps(_merge_extras(current_extras, split["extras"])))
        elif extras is not None:
            assignments.append("extras = ?")
            values.append(json.dumps(_validate_tags(extras)))
        if preprompt is not None:
            assignments.append("preprompt = ?")
            values.append(_validate_preprompt(preprompt))
        if rating is not None:
            assignments.append("rating = ?")
            values.append(_validate_rating(rating))
        if notes is not None:
            assignments.append("notes = ?")
            values.append(_validate_notes(notes))
        try:
            with closing(self._connect()) as conn, conn:
                if assignments:
                    cursor = conn.execute(
                        f"UPDATE characters SET {', '.join(assignments)} WHERE id = ?",
                        (*values, char_id),
                    )
                    return cursor.rowcount > 0
                row = conn.execute(
                    "SELECT 1 FROM characters WHERE id = ?", (char_id,)
                ).fetchone()
                return row is not None
        except sqlite3.IntegrityError as exc:
            raise EngineError(f"nombre de OC ya existe: {name!r}") from exc
        except sqlite3.Error as exc:
            raise EngineError(f"characters update {char_id} fallo: {exc}") from exc

    def delete(self, char_id: int, *, refs_root: str | Path | None = None) -> bool:
        """Borra el OC, sus refs y su carpeta; False si el id no existe."""
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT 1 FROM characters WHERE id = ?", (char_id,)
                ).fetchone()
                if row is None:
                    return False
                conn.execute(
                    "DELETE FROM character_refs WHERE character_id = ?", (char_id,)
                )
                conn.execute("DELETE FROM characters WHERE id = ?", (char_id,))
        except sqlite3.Error as exc:
            raise EngineError(f"characters delete {char_id} fallo: {exc}") from exc
        directory = self._character_dir(char_id, refs_root=refs_root)
        shutil.rmtree(directory, ignore_errors=True)
        return True

    def add_ref(
        self,
        char_id: int,
        src_path: str | Path,
        *,
        refs_root: str | Path | None = None,
        name: str | None = None,
    ) -> str:
        """Copia `src_path` a `<refs_root>/<id>/<name|uuid>.<ext>`; devuelve relpath.

        Con `name` exige un nombre simple (sin rutas) con la extension del
        origen; si el origen ya esta en esa ruta se registra sin recopiar (asi
        las hojas conservan el prefijo `sheet_`).
        """
        if self.get(char_id) is None:
            raise EngineError(f"OC desconocido: {char_id}")
        src = Path(src_path)
        if not src.is_file():
            raise EngineError(f"referencia no encontrada: {src}")
        extension = src.suffix.lower()
        if extension not in REF_EXTENSIONS:
            raise EngineError(
                f"extension de referencia no soportada: {extension!r}; "
                "usar png/jpg/jpeg/webp"
            )
        if name is None:
            filename = f"{uuid.uuid4().hex}{extension}"
        else:
            provided = Path(str(name))
            if provided.name != str(name) or provided.suffix.lower() != extension:
                raise EngineError(f"nombre de referencia invalido: {name!r}")
            filename = provided.name
        directory = self._character_dir(char_id, refs_root=refs_root)
        target = (directory / filename).resolve()
        if not target.is_relative_to(directory):
            raise EngineError(f"referencia fuera de la carpeta del OC: {filename!r}")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if target != src.resolve():
                shutil.copy2(src, target)
        except OSError as exc:
            raise EngineError(f"copia de referencia fallo: {exc}") from exc
        relpath = f"{char_id}/{filename}"
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO character_refs (character_id, relpath, created_at) "
                    "VALUES (?, ?, ?)",
                    (char_id, relpath, _now()),
                )
        except sqlite3.Error as exc:
            target.unlink(missing_ok=True)
            raise EngineError(f"characters add_ref fallo: {exc}") from exc
        return relpath

    def refs(self, char_id: int) -> list[dict]:
        """Referencias del OC en orden de id; EngineError si el OC no existe."""
        if self.get(char_id) is None:
            raise EngineError(f"OC desconocido: {char_id}")
        try:
            with closing(self._connect()) as conn, conn:
                rows = conn.execute(
                    f"SELECT {_REF_COLUMNS} FROM character_refs "
                    "WHERE character_id = ? ORDER BY id",
                    (char_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise EngineError(f"characters refs {char_id} fallo: {exc}") from exc
        return [
            {
                "id": row[0],
                "character_id": row[1],
                "relpath": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]

    def first_non_sheet_ref(self, char_id: int) -> dict | None:
        """Primera ref que no es hoja (orden de id) o None; EngineError si el OC no existe."""
        for ref in self.refs(char_id):
            if not is_sheet(ref["relpath"]):
                return ref
        return None

    def remove_ref(
        self,
        char_id: int,
        ref_id: int,
        *,
        refs_root: str | Path | None = None,
    ) -> bool:
        """Borra la fila y el archivo de la ref; False si no existe."""
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT relpath FROM character_refs "
                    "WHERE id = ? AND character_id = ?",
                    (ref_id, char_id),
                ).fetchone()
                if row is None:
                    return False
                target = self._resolve_relpath(row[0], refs_root=refs_root)
                conn.execute("DELETE FROM character_refs WHERE id = ?", (ref_id,))
        except sqlite3.Error as exc:
            raise EngineError(f"characters remove_ref fallo: {exc}") from exc
        target.unlink(missing_ok=True)
        return True

    def _resolve_refs_root(self, refs_root: str | Path | None = None) -> Path:
        root = Path(refs_root) if refs_root is not None else self.refs_root
        return Path(root).resolve()

    def _character_dir(
        self, char_id: int, *, refs_root: str | Path | None = None
    ) -> Path:
        root = self._resolve_refs_root(refs_root)
        directory = (root / str(char_id)).resolve()
        if not directory.is_relative_to(root):
            raise EngineError(f"carpeta de referencias fuera de refs_root: {directory}")
        return directory

    def _resolve_relpath(
        self, relpath: str, *, refs_root: str | Path | None = None
    ) -> Path:
        root = self._resolve_refs_root(refs_root)
        target = (root / str(relpath)).resolve()
        if not target.is_relative_to(root):
            raise EngineError(f"referencia fuera de refs_root: {relpath!r}")
        return target

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        """Fila a dict separando rasgos/extras, tambien en filas legacy.

        Las filas guardadas antes de M9-B3 pueden traer extras dentro de
        ``tags``; aqui se separan en la respuesta (sin reescribir la fila) para
        que ``get``/``list`` devuelvan siempre ``tags`` (rasgos) y ``extras``.
        """
        try:
            tags = json.loads(row[2])
            extras = json.loads(row[3])
        except (TypeError, ValueError) as exc:
            raise EngineError(
                f"characters: JSON de tags/extras malformado en {row[0]}: {exc}"
            ) from exc
        if not isinstance(tags, (list, tuple)) or not isinstance(extras, (list, tuple)):
            raise EngineError(f"characters: tags/extras no son listas en {row[0]}")
        split = split_character_tags(tags)
        return {
            "id": row[0],
            "name": row[1],
            "tags": split["traits"],
            "extras": _merge_extras(split["extras"], _validate_tags(extras)),
            "preprompt": row[4],
            "rating": row[5],
            "notes": row[6],
            "created_at": row[7],
        }


def split_character_tags(tags: list[str]) -> dict:
    """Separa tags de OC en ``traits`` (rasgos) y ``extras`` (M9-B3).

    Usa el catalogo real de ``app.prompt_zones``: ``traits`` son los tags de
    subcategoria ``rasgos`` (grupos hair/eyes/face/body); ``extras`` el resto
    de general (ropa/accesorios/accion/poses/expresion/camara/fondo, incluidos
    los desconocidos via ``GENERAL_FALLBACK_SUBCAT``) y tambien
    calidad/safety/sujeto (no definen al personaje). Dedup case-insensitive en
    orden estable; EngineError si ``tags`` no es lista de str.
    """
    traits: list[str] = []
    extras: list[str] = []
    seen: set[str] = set()
    for tag in _validate_tags(tags):
        folded = tag.lower()
        if folded in seen:
            continue
        seen.add(folded)
        if classify_tag(tag) == "general" and general_subcat(tag) == "rasgos":
            traits.append(tag)
        else:
            extras.append(tag)
    return {"traits": traits, "extras": extras}


def prompt_from_tags(tags: list[str]) -> str:
    """Une tags con ', ' deduplicando (case-insensitive) y en orden estable."""
    if not isinstance(tags, (list, tuple)):
        raise EngineError(f"tags debe ser lista de str: {tags!r}")
    merged: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise EngineError(f"tag invalido: {tag!r}")
        tag = tag.strip()
        if not tag:
            continue
        folded = tag.lower()
        if folded in seen:
            continue
        seen.add(folded)
        merged.append(tag)
    return ", ".join(merged)


def prompt_from_extras(extras: list[str]) -> str:
    """Une extras con ', ' deduplicando (case-insensitive) y en orden estable."""
    if not isinstance(extras, (list, tuple)):
        raise EngineError(f"extras debe ser lista de str: {extras!r}")
    return prompt_from_tags(extras)


__all__ = [
    "CharacterStore",
    "is_sheet",
    "prompt_from_extras",
    "prompt_from_tags",
    "split_character_tags",
]
