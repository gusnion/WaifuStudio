"""Smoke real en CPU del LLM unico (M12): carga, texto y vision con tiempos.

Arranca `tools/llama.cpp/llama-server.exe` con el modelo abliterado 9B + mmproj
(`install/manifest/manifest.llm.json`), espera `/health`, hace una llamada de
texto y otra de vision (image_url base64) y reporta tiempos del servidor. No
usa GPU (`-ngl 0`). Uso:

    python scripts/smoke_llm_cpu.py [--image PATH] [--port 8290] [--keep]

`--keep` deja el servidor arrancado al terminar (para pruebas manuales).
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
SERVER = APP_ROOT / "tools" / "llama.cpp" / "llama-server.exe"
MODEL_DIR = APP_ROOT / "ComfyUI" / "models" / "llm" / "qwen35-9b-abliterated"
MODEL = MODEL_DIR / "Qwen3.5-9B-abliterated-Q4_K_M.gguf"
MMPROJ = MODEL_DIR / "mmproj-F16.gguf"
LOG_PATH = APP_ROOT / "data" / "llm-smoke.log"

TEXT_SYSTEM = "You output danbooru-style tags in English, comma separated, one line."
TEXT_USER = "1girl, sonriendo, pelo largo al viento"


def _post(url: str, payload: dict, timeout: float = 600.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_status(url: str, timeout: float = 5.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:  # 503 = cargando
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def _wait_ready(base: str, proc: subprocess.Popen, limit_s: float = 240.0) -> float:
    began = time.perf_counter()
    while time.perf_counter() - began < limit_s:
        if proc.poll() is not None:
            raise SystemExit(f"llama-server termino con codigo {proc.returncode}")
        status = _get_status(base + "/health")
        if status == 200:
            return time.perf_counter() - began
        time.sleep(1.0)
    raise SystemExit("timeout esperando /health")


def _test_image(explicit: str | None) -> tuple[bytes, str]:
    if explicit:
        path = Path(explicit)
        return path.read_bytes(), str(path)
    gallery = APP_ROOT / "data" / "gallery"
    for folder in sorted(gallery.glob("*")):
        for candidate in sorted(folder.glob("*")):
            if candidate.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                return candidate.read_bytes(), str(candidate)
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (512, 512), (245, 245, 250))
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 80, 432, 432), fill=(220, 60, 60))
    draw.rectangle((0, 440, 512, 512), fill=(30, 30, 30))
    draw.text((40, 460), "TEST 123", fill=(255, 255, 255))
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), "sintetica(PIL)"


def _timings(data: dict) -> str:
    timings = data.get("timings") or {}
    prompt = timings.get("prompt_per_second")
    predict = timings.get("predicted_per_second")
    count = timings.get("predicted_n")
    return (
        f"prefill {prompt:.1f} t/s, gen {predict:.1f} t/s ({count} tokens)"
        if isinstance(prompt, (int, float)) and isinstance(predict, (int, float))
        else str(timings)
    )


def _content(data: dict) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    text = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    return (text or reasoning).strip()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Smoke CPU del LLM unico (M12)")
    parser.add_argument("--image", default=None)
    parser.add_argument("--port", type=int, default=8290)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    for label, path in (("llama-server", SERVER), ("modelo", MODEL), ("mmproj", MMPROJ)):
        if not path.is_file():
            print(f"FALTA {label}: {path}")
            return 2

    base = f"http://127.0.0.1:{args.port}"
    if _get_status(base + "/health") in (200, 503):
        print(f"Ya hay un servidor en {base}; se reutiliza (no se arranca otro).")
        proc = None
        ready_s = 0.0
    else:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = LOG_PATH.open("w", encoding="utf-8")
        command = [
            str(SERVER),
            "-m", str(MODEL),
            "--mmproj", str(MMPROJ),
            "-ngl", "0",
            "-c", "8192",
            "-t", str(args.threads),
            "--jinja",
            "--reasoning", "off",
            "--no-webui",
            "--host", "127.0.0.1",
            "--port", str(args.port),
        ]
        print("Arrancando:", " ".join(command[:6]), "...")
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=creationflags)
        try:
            ready_s = _wait_ready(base, proc)
            print(f"Servidor listo en {ready_s:.1f} s (log: {LOG_PATH.name})")
        except SystemExit as exc:
            print(exc)
            print(f"Ultimas lineas del log ({LOG_PATH}):")
            for line in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]:
                print("  " + line)
            proc.kill()
            return 2

    image_bytes, image_label = _test_image(args.image)
    payload_text = {
        "model": "qwen35-9b-abliterated",
        "messages": [
            {"role": "system", "content": TEXT_SYSTEM},
            {"role": "user", "content": TEXT_USER},
        ],
        "max_tokens": 120,
        "temperature": 0.7,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    began = time.perf_counter()
    data_text = _post(base + "/v1/chat/completions", payload_text)
    text_s = time.perf_counter() - began
    content = _content(data_text)
    print(f"\nTEXTO ({text_s:.1f} s): {content[:300]!r}")
    print("  " + _timings(data_text))

    sys.path.insert(0, str(APP_ROOT))
    from app import tags as tag_catalog
    from app.vision import DESCRIBE_SYSTEM_PROMPT, _parse_describe

    describe_system = DESCRIBE_SYSTEM_PROMPT
    data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    payload_vision = {
        "model": "qwen35-9b-abliterated",
        "messages": [
            {"role": "system", "content": describe_system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe la imagen para usarla como prompt."},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
        "max_tokens": 300,
        "temperature": 0.4,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    began = time.perf_counter()
    data_vision = _post(base + "/v1/chat/completions", payload_vision)
    vision_s = time.perf_counter() - began
    vision = _content(data_vision)
    print(f"\nVISION ({vision_s:.1f} s, imagen: {image_label}): {vision[:400]!r}")
    print("  " + _timings(data_vision))
    caption, tags_text = _parse_describe(vision)
    kept, dropped = tag_catalog.validate_list(tags_text)
    print(f"  validacion app: caption={len(caption)} chars, tags={kept[:12]}... dropped={dropped}")
    vision = vision and caption

    if proc is not None and not args.keep:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\nServidor parado.")
    elif args.keep:
        print(f"\nServidor sigue en {base} (--keep).")

    ok = bool(content) and bool(vision)
    print("RESULTADO:", "OK (texto+vision)" if ok else "FALLO (respuesta vacia)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
