#!/usr/bin/env bash
# Sobe o ComfyUI nativo do projeto Casa Amarano.
# A GPU vive no Modal; este ComfyUI roda em CPU só para montar workflows.
set -euo pipefail

PROJETO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$HOME/ComfyUI/ComfyUI}"
COMFYUI_PYTHON="${COMFYUI_PYTHON:-$HOME/ComfyUI/venv/bin/python}"
COMFYUI_BIND_IP="${COMFYUI_BIND_IP:-192.168.15.73}"

if [ ! -x "$COMFYUI_PYTHON" ]; then
  echo "ERRO: Python do ComfyUI não encontrado em $COMFYUI_PYTHON" >&2
  exit 1
fi
if [ ! -f "$COMFYUI_DIR/main.py" ]; then
  echo "ERRO: ComfyUI não encontrado em $COMFYUI_DIR" >&2
  exit 1
fi

cd "$COMFYUI_DIR"
export CASA_AMARANO_ROOT="${CASA_AMARANO_ROOT:-$PROJETO_DIR}"
export COMFY_SCHEDULER_DB="${COMFY_SCHEDULER_DB:-$HOME/ComfyUI/data/comfy_scheduler.db}"
export OMNIROUTE_BASE_URL="${OMNIROUTE_BASE_URL:-http://192.168.15.73:20128}"
echo "==> ComfyUI nativo em http://${COMFYUI_BIND_IP}:8188 (Ctrl+C para parar)"
exec "$COMFYUI_PYTHON" main.py --cpu --listen "$COMFYUI_BIND_IP" --disable-auto-launch --enable-assets
