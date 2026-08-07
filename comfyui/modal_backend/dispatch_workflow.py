"""Despacho automático: resolve dependências, calcula GPU e executa o workflow."""

import base64
import json
import sys
from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from comfyui.dispatch.dispatch_plan import build_dispatch_plan
from comfyui.modal_backend.app import app
from comfyui.scheduler.budget import BudgetManager
from comfyui.scheduler.db import SchedulerDB
from comfyui.scheduler.router import GPURouter


@app.local_entrypoint()
def main(
    workflow_file: str,
    lambda_val: float = 0.0,
    resolution: str = "1024x1024",
    steps: int = 30,
    local_model_root: str = "~/ComfyUI/ComfyUI/models",
    input_manifest: str = "",
):
    workflow = json.loads(Path(workflow_file).read_text(encoding="utf-8"))
    input_files = {}
    if input_manifest:
        manifest = json.loads(Path(input_manifest).read_text(encoding="utf-8"))
        workflow = manifest.get("workflow", workflow)
        input_files = manifest.get("input_files", {})
    db = SchedulerDB()
    router = GPURouter(db=db, budget_manager=BudgetManager(db))
    plan = build_dispatch_plan(
        workflow,
        router,
        resolution=resolution,
        steps=steps,
        lambda_val=lambda_val,
        local_model_roots=[local_model_root],
    )
    if plan["target"] == "local":
        raise SystemExit("Todos os modelos do workflow existem localmente; execute pelo ComfyUI local.")

    selected_gpu = plan["route"]["selected_gpu"]
    # Cls.from_name busca o worker no app JÁ DEPLOYADO (`modal deploy app.py`).
    # Instanciar a classe local aqui rodaria num app efêmero, que desliga o
    # container junto com este processo — perdendo o reaproveitamento quente
    # entre chamadas (medido: veja seed_data.py).
    worker_cls = modal.Cls.from_name("casa-amarano-comfyui", f"ComfyWorkflowWorker{selected_gpu.replace('-', '')}")
    result = worker_cls().run.remote(workflow, input_files)
    output_dir = Path(workflow_file).parent
    for index, output in enumerate(result["outputs"], start=1):
        suffix = output["format"] or "bin"
        output_path = output_dir / f"remote_result_{index:02d}.{suffix}"
        output_path.write_bytes(base64.b64decode(output["data_base64"]))

    summary = {
        "target": plan["target"],
        "model": plan["model"],
        "missing_files": plan["missing_files"],
        "selected_gpu": selected_gpu,
        "estimated_cost_usd": plan["route"]["estimated_cost_usd"],
        "actual": result["metrics"],
        "outputs": [
            {
                "path": str(output_dir / f"remote_result_{i:02d}.{o['format'] or 'bin'}"),
                "format": o["format"] or "bin",
                "data_base64": o["data_base64"],
            }
            for i, o in enumerate(result["outputs"], start=1)
        ],
    }
    print(json.dumps(summary, ensure_ascii=False))
