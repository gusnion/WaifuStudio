#!/usr/bin/env bash
# Diagnostico de rutas, engine, LLM y FFmpeg.
set -euo pipefail
ROOT="${WAIFU_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
exec "$ROOT/.venv/bin/python" -m app.health "$@"
