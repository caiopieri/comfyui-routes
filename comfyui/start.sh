#!/bin/zsh
set -euo pipefail

COMFYUI_DIR="$HOME/ComfyUI/ComfyUI"
cd "$COMFYUI_DIR"
exec "$COMFYUI_DIR/venv/bin/python" main.py --cpu
