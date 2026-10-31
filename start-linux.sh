#!/usr/bin/env bash
# Arranca el engine ComfyUI (8288) y la app (8765) en segundo plano.
# Uso: ./start-linux.sh [--no-browser]
set -euo pipefail

ROOT="${WAIFU_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PY="$ROOT/.venv/bin/python"
cd "$ROOT"

if [ ! -x "$PY" ]; then
  echo "ERROR: no hay .venv. Ejecuta ./install-linux.sh primero." >&2
  exit 1
fi
if [ ! -f "$ROOT/ComfyUI/main.py" ]; then
  echo "ERROR: falta ComfyUI. Ejecuta ./install-linux.sh primero." >&2
  exit 1
fi
mkdir -p "$ROOT/data/run" "$ROOT/data/logs"

if curl -fsS -m 2 http://127.0.0.1:8288/system_stats >/dev/null 2>&1; then
  echo "Engine ya responde en http://127.0.0.1:8288"
else
  echo "Arrancando engine ComfyUI..."
  (
    cd "$ROOT/ComfyUI"
    nohup ../.venv/bin/python -s main.py \
      --listen 127.0.0.1 --port 8288 --offline --disable-auto-launch \
      >> "$ROOT/data/logs/engine.log" 2>&1 &
    echo $! > "$ROOT/data/run/engine.pid"
  )
fi

if curl -fsS -m 2 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
  echo "App ya responde en http://127.0.0.1:8765"
else
  echo "Arrancando WaifuStudio..."
  (
    WAIFU_LLM_TIMEOUT=300 nohup "$PY" -m app.server \
      >> "$ROOT/data/logs/app.log" 2>&1 &
    echo $! > "$ROOT/data/run/app.pid"
  )
  for _ in $(seq 1 40); do
    sleep 1
    if curl -fsS -m 2 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
      break
    fi
  done
fi

if ! curl -fsS -m 3 http://127.0.0.1:8765/api/health; then
  echo
  echo "La app no responde. Revisa $ROOT/data/logs/app.log" >&2
  exit 1
fi
echo
echo "Listo: http://127.0.0.1:8765"
echo "Logs:  $ROOT/data/logs/"

if [ "${1:-}" != "--no-browser" ] && command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:8765" >/dev/null 2>&1 || true
fi
