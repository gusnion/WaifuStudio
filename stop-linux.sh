#!/usr/bin/env bash
# Detiene la app y el engine arrancados por start-linux.sh.
set -euo pipefail

ROOT="${WAIFU_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
cd "$ROOT"

stop_pid() {
  local name="$1" pidfile="$ROOT/data/run/$1.pid"
  if [ ! -f "$pidfile" ]; then
    echo "$name: sin PID registrado"
    return 0
  fi
  local pid; pid="$(cat "$pidfile" 2>/dev/null || true)"
  rm -f "$pidfile"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "$name: no estaba corriendo"
    return 0
  fi
  echo "Parando $name (PID $pid)..."
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "$name: parado"
      return 0
    fi
    sleep 0.5
  done
  echo "$name: no termino; enviando SIGKILL"
  kill -9 "$pid" 2>/dev/null || true
}

stop_pid app
stop_pid engine

# El LLM es hijo de la app; si quedo vivo, se para solo el de este repo.
if command -v pkill >/dev/null 2>&1; then
  pkill -f "$ROOT/tools/llama.cpp/llama-server" 2>/dev/null || true
fi
echo "Hecho."
