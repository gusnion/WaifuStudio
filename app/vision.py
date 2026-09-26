"""Vision local (M10-4b): tags WD14 y caption Qwen2.5-VL.

WD14 corre con onnxruntime en CPU sobre `ComfyUI/models/wd14`; el caption usa
llama-cpp-python (`Qwen25VLChatHandler`) con el mmproj de
`ComfyUI/models/llm/qwen25vl-7b-abliterated-gguf`. Las cargas son perezosas y
las factorias inyectables para que los tests corran offline (sin onnxruntime ni
llama_cpp reales).
"""

from __future__ import annotations

import base64
import csv
import io
import os
from pathlib import Path
from typing import Any, Callable

from app.engine import EngineError

WD14_DIRNAME = "wd14"
WD14_MODEL = "wd-v1-4-convnext-tagger-v2"
WD14_THRESHOLD = 0.35
WD14_CHARACTER_THRESHOLD = 0.85
VL_DIRNAME = "llm"
VL_SUBDIR = "qwen25vl-7b-abliterated-gguf"
VL_MODEL_FILE = "Qwen2.5-VL-7B-Instruct-abliterated.Q4_K_M.gguf"
VL_MMPROJ_FILE = "Qwen2.5-VL-7B-Instruct-abliterated.mmproj-f16.gguf"
VL_SYSTEM_PROMPT = (
    "Eres un descriptor de imagenes anime para un generador local. "
    "Describe la imagen en INGLES, en una sola frase densa de atributos "
    "(sujeto, rasgos, ropa, pose, fondo, luz), sin intro ni conclusion."
)
VL_USER_PROMPT = "Describe la imagen para usarla como prompt."


class VisionUnavailable(RuntimeError):
    """Falta un modelo o dependencia del componente de vision solicitado."""


def _postprocess(
    rows: list[tuple[str, str]],
    probs: Any,
    threshold: float = WD14_THRESHOLD,
    character_threshold: float = WD14_CHARACTER_THRESHOLD,
) -> list[str]:
    """Filtra probabilidades WD14 como el nodo de ComfyUI (personajes + generales).

    `rows` son pares (nombre ya normalizado, categoria del CSV) en el orden del
    fichero; `probs` la secuencia paralela de probabilidades. La categoria `4`
    (personajes) usa `character_threshold` y la `0` (general) usa `threshold`;
    el resto (p. ej. rating `9`) se ignora. El orden de salida es personajes y
    despues generales, igual que el nodo.
    """
    general: list[str] = []
    character: list[str] = []
    for (name, category), prob in zip(rows, probs):
        score = float(prob)
        if category == "4" and score > character_threshold:
            character.append(name)
        elif category == "0" and score > threshold:
            general.append(name)
    return character + general


def _preprocess(image_bytes: bytes, size: int):
    """Imagen -> tensor BGR con padding blanco al cuadrado `size` (semantica WD14)."""
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as handle:
        image = handle.convert("RGB")
    ratio = float(size) / max(image.size)
    new_size = (
        max(1, int(image.size[0] * ratio)),
        max(1, int(image.size[1] * ratio)),
    )
    resized = image.resize(new_size, Image.LANCZOS)
    square = Image.new("RGB", (size, size), (255, 255, 255))
    square.paste(resized, ((size - new_size[0]) // 2, (size - new_size[1]) // 2))
    array = np.asarray(square, dtype=np.float32)[:, :, ::-1]
    return np.expand_dims(array, 0)


def _load_rows(csv_path: Path) -> list[tuple[str, str]]:
    """Pares (nombre sin `_`, categoria) del `selected_tags.csv` de WD14."""
    rows: list[tuple[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                rows.append((row[1].replace("_", " "), row[2]))
    return rows


def _default_tagger(onnx_path: Path, csv_path: Path) -> Callable[[bytes], list[str]]:
    import onnxruntime

    session = onnxruntime.InferenceSession(
        str(onnx_path), providers=["CPUExecutionProvider"]
    )
    input_meta = session.get_inputs()[0]
    size = int(input_meta.shape[1]) if len(input_meta.shape) > 1 else 448
    rows = _load_rows(csv_path)
    label = session.get_outputs()[0].name

    def tagger(image_bytes: bytes) -> list[str]:
        probs = session.run([label], {input_meta.name: _preprocess(image_bytes, size)})[0][0]
        return _postprocess(rows, probs)

    return tagger


def _default_captioner(
    model_path: Path, mmproj_path: Path, gpu_layers: int
) -> Callable[[bytes], str]:
    from llama_cpp import Llama
    from llama_cpp.llama_chat_format import Qwen25VLChatHandler

    handler = Qwen25VLChatHandler(clip_model_path=str(mmproj_path), verbose=False)
    llama = Llama(
        model_path=str(model_path),
        chat_handler=handler,
        n_ctx=4096,
        n_gpu_layers=int(gpu_layers),
        verbose=False,
    )

    def captioner(image_bytes: bytes) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode(
            "ascii"
        )
        response = llama.create_chat_completion(
            messages=[
                {"role": "system", "content": VL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VL_USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                },
            ],
            max_tokens=180,
            temperature=0.4,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str) or not content.strip():
            raise EngineError("vision: caption vacio")
        return " ".join(content.split())

    return captioner


class VisionService:
    """WD14 + VL con cargas perezosas; estado y descripcion de imagenes."""

    def __init__(
        self,
        comfy_root: str | Path,
        *,
        wd14_dir: str | Path | None = None,
        vl_model: str | Path | None = None,
        vl_mmproj: str | Path | None = None,
        gpu_layers: int | None = None,
        tagger_factory: Callable[[Path, Path], Callable[[bytes], list[str]]] | None = None,
        captioner_factory: Callable[[Path, Path, int], Callable[[bytes], str]] | None = None,
    ) -> None:
        self.comfy_root = Path(comfy_root)
        self.wd14_dir = (
            Path(wd14_dir)
            if wd14_dir is not None
            else self.comfy_root / "models" / WD14_DIRNAME
        )
        model_override = vl_model or os.environ.get("WAIFU_VL_MODEL", "").strip() or None
        mmproj_override = (
            vl_mmproj or os.environ.get("WAIFU_VL_MMPROJ", "").strip() or None
        )
        default_dir = self.comfy_root / "models" / VL_DIRNAME / VL_SUBDIR
        self.vl_model = (
            Path(model_override)
            if model_override is not None
            else default_dir / VL_MODEL_FILE
        )
        self.vl_mmproj = (
            Path(mmproj_override)
            if mmproj_override is not None
            else default_dir / VL_MMPROJ_FILE
        )
        if gpu_layers is None:
            text = os.environ.get("WAIFU_VL_GPU_LAYERS", "").strip()
            gpu_layers = int(text) if text else 0
        self.gpu_layers = int(gpu_layers)
        self._tagger_factory = tagger_factory or _default_tagger
        self._captioner_factory = captioner_factory or _default_captioner
        self._tagger: Callable[[bytes], list[str]] | None = None
        self._captioner: Callable[[bytes], str] | None = None

    @property
    def wd14_model_path(self) -> Path:
        return self.wd14_dir / f"{WD14_MODEL}.onnx"

    @property
    def wd14_csv_path(self) -> Path:
        return self.wd14_dir / f"{WD14_MODEL}.csv"

    def wd14_installed(self) -> bool:
        return self.wd14_model_path.is_file() and self.wd14_csv_path.is_file()

    def vl_installed(self) -> bool:
        return self.vl_model.is_file() and self.vl_mmproj.is_file()

    def status(self) -> dict[str, Any]:
        """Estado real de los dos componentes (sin cargar nada)."""
        return {
            "installed": self.wd14_installed() and self.vl_installed(),
            "wd14": {"installed": self.wd14_installed(), "model": WD14_MODEL},
            "vl": {"installed": self.vl_installed(), "model": self.vl_model.name},
            "note": (
                "WD14 por onnxruntime (CPU); caption Qwen2.5-VL por llama.cpp "
                f"(n_gpu_layers={self.gpu_layers}); usa POST /api/vision/image_to_prompt."
            ),
        }

    def tags(self, image_bytes: bytes) -> list[str]:
        if not self.wd14_installed():
            raise VisionUnavailable(f"WD14 no instalado en {self.wd14_dir}")
        if self._tagger is None:
            self._tagger = self._tagger_factory(self.wd14_model_path, self.wd14_csv_path)
        return list(self._tagger(image_bytes))

    def caption(self, image_bytes: bytes) -> str:
        if not self.vl_installed():
            raise VisionUnavailable(f"VL no instalado: {self.vl_model.name}")
        if self._captioner is None:
            self._captioner = self._captioner_factory(
                self.vl_model, self.vl_mmproj, self.gpu_layers
            )
        return str(self._captioner(image_bytes))

    def describe(
        self, image_bytes: bytes, *, use_tags: bool = True, use_caption: bool = True
    ) -> dict[str, Any]:
        """Tags y/o caption de una imagen; `VisionUnavailable` si falta un componente pedido."""
        result: dict[str, Any] = {
            "tags": None,
            "caption": None,
            "model": {"wd14": WD14_MODEL, "vl": self.vl_model.name},
        }
        if use_tags:
            result["tags"] = self.tags(image_bytes)
        if use_caption:
            result["caption"] = self.caption(image_bytes)
        return result


__all__ = [
    "VL_MMPROJ_FILE",
    "VL_MODEL_FILE",
    "VisionService",
    "VisionUnavailable",
    "WD14_MODEL",
    "_postprocess",
]
