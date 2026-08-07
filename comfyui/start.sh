#!/bin/zsh
# Sobe o ComfyUI local do projeto Casa Amarano.
# A GPU vive no Modal; este ComfyUI roda em CPU só para montar workflows.
set -euo pipefail

COMFYUI_DIR="$HOME/ComfyUI/ComfyUI"
PROJETO_DIR="${0:A:h:h}"
NO_ORIGEM="$PROJETO_DIR/comfyui/custom_nodes/comfyui_modal_dispatch"
NO_DESTINO="$COMFYUI_DIR/custom_nodes/comfyui_modal_dispatch"

if [ ! -x "$COMFYUI_DIR/venv/bin/python" ]; then
  echo "ERRO: venv não encontrado em $COMFYUI_DIR/venv"
  echo "  /usr/local/bin/python3.12 -m venv $COMFYUI_DIR/venv"
  echo "  source $COMFYUI_DIR/venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

VERSAO=$("$COMFYUI_DIR/venv/bin/python" --version 2>&1 | awk '{print $2}')
if [[ "$VERSAO" != 3.12.* ]]; then
  echo "ERRO: venv está com Python $VERSAO; PyTorch exige 3.12.x. Recrie o venv."
  exit 1
fi

# Liga o nó customizado ao ComfyUI (link simbólico: atualizações do repositório
# chegam sozinhas, sem precisar copiar arquivo).
if [ ! -e "$NO_DESTINO" ]; then
  echo "==> Ligando o nó customizado ao ComfyUI"
  ln -s "$NO_ORIGEM" "$NO_DESTINO"
fi

echo "==> ComfyUI em http://127.0.0.1:8188 (Ctrl+C para parar)"
cd "$COMFYUI_DIR"
exec "$COMFYUI_DIR/venv/bin/python" main.py --cpu "$@"
