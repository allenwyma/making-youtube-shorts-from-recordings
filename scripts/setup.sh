#!/bin/sh
# One-time setup: python venv with Whisper (mlx-whisper on Apple silicon, faster-whisper elsewhere), numpy and Pillow.
# Idempotent. Prints the venv python on its last line.
set -e
SK="$(cd "$(dirname "$0")/.." && pwd)"
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
[ -d "$SK/.venv" ] || "$PY" -m venv "$SK/.venv"
if [ "$(uname -s)-$(uname -m)" = "Darwin-arm64" ]; then W=mlx-whisper; else W=faster-whisper; fi
"$SK/.venv/bin/pip" install -q --upgrade "$W" numpy pillow
"$SK/.venv/bin/python" -c "import numpy, PIL; print('venv ok')"
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found (macOS: brew install ffmpeg)"
echo "$SK/.venv/bin/python"
