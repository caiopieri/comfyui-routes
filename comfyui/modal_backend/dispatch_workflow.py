"""Despacho automático: resolve dependências, calcula GPU e executa o workflow."""

import base64
import json
import sys
import time
import uuid
from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from comfyui.dispatch.dispatch_plan import build_dispatch_plan
from comfyui.modal_backend.app import app
from comfyui.modal_backend.config import GPU_SPECS
from comfyui.scheduler.budget import BudgetManager
from comfyui.scheduler.db import SchedulerDB
from comfyui.scheduler.router import GPURouter

# Quantas GPUs maiores tentar automaticamente antes de desistir. O roteador
# (router.py) já exclui GPUs que deram OOM nesse modelo antes, então cada
# tentativa nova escolhe naturalmente a próxima opção viável — não é um loop
# às cegas, é limitado pelo próprio catálogo de GPUs (6 tiers no máximo).
MAX_OOM_RETRIES = 3


def _e_oom(error: Exception) -> bool:
    texto = str(error)
    return "OutOfMemoryError" in texto or "out of memory" in texto.lower()


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
    models_metadata = None
    if input_manifest:
        manifest = json.loads(Path(input_manifest).read_text(encoding="utf-8"))
        workflow = manifest.get("workflow", workflow)
        input_files = manifest.get("input_files", {})
        models_metadata = manifest.get("models_metadata")

    db = SchedulerDB()
    router = GPURouter(db=db, budget_manager=BudgetManager(db))

    plan = None
    selected_gpu = None
    result = None
    for attempt in range(1, MAX_OOM_RETRIES + 1):
        plan = build_dispatch_plan(
            workflow,
            router,
            resolution=resolution,
            steps=steps,
            lambda_val=lambda_val,
            local_model_roots=[local_model_root],
            models_metadata=models_metadata,
        )
        if plan["target"] == "local":
            raise SystemExit("Todos os modelos do workflow existem localmente; execute pelo ComfyUI local.")

        selected_gpu = plan["route"]["selected_gpu"]
        # Cls.from_name busca o worker no app JÁ DEPLOYADO (`modal deploy app.py`).
        # Instanciar a classe local aqui rodaria num app efêmero, que desliga o
        # container junto com este processo — perdendo o reaproveitamento quente
        # entre chamadas (medido: veja seed_data.py).
        worker_cls = modal.Cls.from_name("casa-amarano-comfyui", f"ComfyWorkflowWorker{selected_gpu.replace('-', '')}")
        started = time.perf_counter()
        try:
            result = worker_cls().run.remote(workflow, input_files)
        except Exception as error:
            if not _e_oom(error):
                raise
            duration_s = time.perf_counter() - started
            print(
                f"[aviso] OutOfMemoryError na GPU {selected_gpu} — registrando e "
                f"tentando GPU maior (tentativa {attempt}/{MAX_OOM_RETRIES})"
            )
            db.record_execution(
                job_id=f"oom-{uuid.uuid4().hex[:10]}",
                task_type="workflow",
                model=plan["model"],
                gpu=selected_gpu,
                resolution=resolution,
                steps=steps,
                duration_s=duration_s,
                cost_usd=round(duration_s * GPU_SPECS[selected_gpu]["price_per_sec"], 6),
                warm_container=plan["route"]["is_warm"],
                status="OOM",
            )
            continue
        break
    else:
        raise SystemExit(
            f"Esgotou {MAX_OOM_RETRIES} tentativas — nem a maior GPU disponível "
            "comportou esse workflow (torch.OutOfMemoryError em todas)."
        )

    db.record_execution(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        task_type="workflow",
        model=plan["model"],
        gpu=selected_gpu,
        resolution=resolution,
        steps=steps,
        duration_s=result["metrics"]["duration_s"],
        cost_usd=result["metrics"]["actual_cost_usd"],
        warm_container=result["metrics"]["is_warm"],
        status="SUCCESS",
    )

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
