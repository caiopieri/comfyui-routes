"""Entry point local para enviar um workflow API completo a uma função Modal."""

import json
from pathlib import Path

import modal

from comfyui.modal_backend.app import WORKFLOW_FUNCTIONS, app


@app.local_entrypoint()
def main(workflow_file: str, gpu: str = "L4"):
    workflow = json.loads(Path(workflow_file).read_text(encoding="utf-8"))
    if gpu not in WORKFLOW_FUNCTIONS:
        raise SystemExit(f"GPU inválida: {gpu}")
    result = WORKFLOW_FUNCTIONS[gpu].remote(workflow)
    print(json.dumps(result, ensure_ascii=False))
