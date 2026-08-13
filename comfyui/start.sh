#!/bin/zsh
# Sobe o ComfyUI local do projeto Casa Amarano via Docker.
# A GPU vive no Modal; este ComfyUI roda em CPU só para montar workflows.
# Docker garante uma versão atual do ComfyUI (o venv nativo no Mac Intel
# fica preso numa versão antiga por causa dos wheels do PyTorch).
set -euo pipefail

PROJETO_DIR="${0:A:h:h}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERRO: Docker não encontrado. Instale o Docker Desktop antes de continuar."
  exit 1
fi

cd "$PROJETO_DIR"
echo "==> ComfyUI em http://127.0.0.1:8188 (Ctrl+C para parar)"
echo "==> Para forçar uma versão mais nova do ComfyUI (o build normal reaproveita cache):"
echo "      docker compose -f compose.comfyui.yaml build --no-cache"
exec docker compose -f compose.comfyui.yaml up --build
