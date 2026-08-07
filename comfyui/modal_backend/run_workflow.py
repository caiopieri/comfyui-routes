"""Entry point local para enviar um workflow API completo a uma função Modal."""

import json
from pathlib import Path

import modal

from comfyui.modal_backend.app import WORKFLOW_WORKERS, app


@app.local_entrypoint()
def main(workflow_file: str, gpu: str = "L4"):
    workflow = json.loads(Path(workflow_file).read_text(encoding="utf-8"))
    if gpu not in WORKFLOW_WORKERS:
        raise SystemExit(f"GPU inválida: {gpu}")
    # Cls.from_name usa o app deployado (`modal deploy app.py`) — preserva o
    # container quente entre chamadas. Ver mesma nota em dispatch_workflow.py.
    worker_cls = modal.Cls.from_name("casa-amarano-comfyui", f"ComfyWorkflowWorker{gpu.replace('-', '')}")
    result = worker_cls().run.remote(workflow)
    print(json.dumps(result, ensure_ascii=False))
