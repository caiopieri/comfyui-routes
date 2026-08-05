"""
Nó Customizado do ComfyUI: Modal Subgraph Dispatch.
Empacota um subgrafo pesado e dispara a execução remota no Modal com roteamento inteligente de GPU.
"""

import json
import time
import uuid
import os
import sys
import subprocess
import tempfile
from typing import Dict, Any, Tuple

# Adiciona o diretório do projeto Casa Amarano ao sys.path se necessário
CASA_AMARANO_ROOT = os.environ.get(
    "CASA_AMARANO_ROOT", "/Users/caioamaraldepieri/Projetos/Casa Amarano"
)
if CASA_AMARANO_ROOT not in sys.path:
    sys.path.insert(0, CASA_AMARANO_ROOT)

from comfyui.scheduler.router import GPURouter
from comfyui.modal_backend.config import MODEL_PROFILES
from comfyui.dispatch.workflow_resolver import resolve_workflow
from comfyui.scheduler.db import SchedulerDB
from comfyui.custom_nodes.comfyui_modal_dispatch.utils import (
    compute_subgraph_hash,
    base64_to_tensor,
    create_video_reference_payload,
)


class ModalSubgraphDispatch:
    """
    Nó customizado para a interface local do ComfyUI.
    Empacota subgrafos pesados e envia ao Modal com otimização de custo/tempo e cache.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_name": (
                    list(MODEL_PROFILES),
                    {"default": "sdxl"},
                ),
                "task_type": (
                    ["txt2img", "img2img", "txt2video", "img2video"],
                    {"default": "txt2img"},
                ),
                "resolution": (
                    ["1024x1024", "1280x720", "512x512", "1920x1080"],
                    {"default": "1024x1024"},
                ),
                "steps": ("INT", {"default": 30, "min": 1, "max": 150}),
                "seed": ("INT", {"default": 42, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "lambda_time_value": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 200.0, "step": 1.0},
                ),
                "bypass_cache": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "subgraph_json_override": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "FLOAT", "FLOAT")
    RETURN_NAMES = ("media_output", "result_info_json", "duration_seconds", "cost_usd")
    FUNCTION = "dispatch_subgraph"
    CATEGORY = "Casa Amarano / Modal"

    def __init__(self):
        self.db = SchedulerDB()
        self.router = GPURouter(db=self.db)

    def _send_progress_update(self, current_step: int, total_steps: int):
        """Envia atualização de progresso para a barra de progresso nativa do ComfyUI se disponível."""
        try:
            from server import PromptServer
            PromptServer.instance.send_sync(
                "progress",
                {"value": current_step, "max": total_steps}
            )
        except Exception:
            # Silencioso se estiver rodando fora do servidor web do ComfyUI
            pass

    def dispatch_subgraph(
        self,
        model_name: str,
        task_type: str,
        resolution: str,
        steps: int,
        seed: int,
        lambda_time_value: float,
        bypass_cache: bool = False,
        subgraph_json_override: str = "",
    ) -> Tuple[Any, str, float, float]:
        """
        Executa a lógica de despacho do subgrafo.
        """
        job_id = f"job-{uuid.uuid4().hex[:10]}"

        # 1. Montagem da estrutura do subgrafo
        if subgraph_json_override.strip():
            try:
                subgraph_data = json.loads(subgraph_json_override)
            except json.JSONDecodeError:
                subgraph_data = {"raw": subgraph_json_override}
        else:
            subgraph_data = {
                "model": model_name,
                "task_type": task_type,
                "resolution": resolution,
                "steps": steps,
                "seed": seed,
            }

        if subgraph_json_override.strip() and all(
            isinstance(value, dict) and "class_type" in value for value in subgraph_data.values()
        ):
            model_name = resolve_workflow(subgraph_data).model

        params = {
            "model_name": model_name,
            "task_type": task_type,
            "resolution": resolution,
            "steps": steps,
        }

        # 2. Verificação de Cache (Mesma seed + mesmos parâmetros = reuso instantâneo a Custo Zero)
        hash_key = compute_subgraph_hash(subgraph_data, seed, params)

        if not bypass_cache:
            cached = self.db.get_cached_output(hash_key)
            if cached:
                cached_data = json.loads(cached)
                print(f"[Modal Dispatcher] HIT NO CACHE! Subgrafo reutilizado sem custo no Modal.")
                info_json = json.dumps({
                    "job_id": job_id,
                    "status": "CACHE_HIT",
                    "gpu_used": "CACHE",
                    "cost_usd": 0.0,
                    "duration_s": 0.0,
                }, indent=2)
                return (cached_data.get("output"), info_json, 0.0, 0.0)

        # 3. Roteamento Inteligente de GPU via Scheduler
        route_decision = self.router.route_job(
            model=model_name,
            resolution=resolution,
            steps=steps,
            lambda_val=lambda_time_value,
        )

        selected_gpu = route_decision["selected_gpu"]
        print(
            f"[Modal Dispatcher] Rota Escolhida: GPU {selected_gpu} "
            f"(Score: {route_decision['score']}, Est. Custo: ${route_decision['estimated_cost_usd']:.4f})"
        )

        # 4. Execução real no Modal. Um override em formato API permite
        # despachar um workflow completo; o formato simples continua usando
        # o gerador SDXL compatível com o exemplo existente.
        start_time = time.time()

        # Simulação do progresso em tempo real enviando eventos para a UI do ComfyUI
        for step in range(1, steps + 1):
            if step % max(1, steps // 5) == 0 or step == steps:
                self._send_progress_update(step, steps)

        prompt = subgraph_data.get("prompt", "a cinematic architectural photograph")
        if subgraph_json_override.strip() and all(
            isinstance(value, dict) and "class_type" in value for value in subgraph_data.values()
        ):
            workflow_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump(subgraph_data, workflow_file)
            workflow_file.close()
            modal_script = os.path.join(CASA_AMARANO_ROOT, "comfyui", "modal_backend", "dispatch_workflow.py")
            command = [
                "modal", "run", modal_script, workflow_file.name,
                "--lambda-val", str(lambda_time_value),
                "--resolution", resolution,
                "--steps", str(steps),
            ]
        else:
            if model_name != "sdxl":
                raise RuntimeError(
                    f"O perfil {model_name} exige um workflow API completo em subgraph_json_override."
                )
            modal_script = os.path.join(CASA_AMARANO_ROOT, "comfyui", "modal_backend", "generate_sdxl.py")
            command = [
                "modal", "run", modal_script,
                "--prompt", prompt,
                "--seed", str(seed),
                "--steps", str(steps),
                "--gpu", selected_gpu,
            ]
        completed = subprocess.run(
            command,
            cwd=CASA_AMARANO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result_info = None
        for line in reversed(completed.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and ("outputs" in candidate or "output" in candidate):
                result_info = candidate
                break
        if result_info is None:
            raise RuntimeError(f"Modal não retornou JSON de resultado: {completed.stdout[-2000:]}")
        if "outputs" in result_info:
            first_output = result_info["outputs"][0]
            media_result = base64_to_tensor(first_output["data_base64"])
            actual_cost_usd = float(result_info["metrics"]["actual_cost_usd"])
        else:
            output_path = os.path.join(CASA_AMARANO_ROOT, result_info.pop("output"))
            with open(output_path, "rb") as output_file:
                media_result = base64_to_tensor(
                    __import__("base64").b64encode(output_file.read()).decode("ascii")
                )
            actual_cost_usd = float(result_info["cost_usd"])
        metrics = {
            "duration_s": float(result_info["duration_seconds"]),
            "actual_cost_usd": actual_cost_usd,
        }

        end_time = time.time()
        actual_duration_s = end_time - start_time
        actual_cost_usd = metrics["actual_cost_usd"]

        # Processamento do output
        # 5. Registro Medido no SQLite
        self.db.record_execution(
            job_id=job_id,
            task_type=task_type,
            model=model_name,
            gpu=selected_gpu,
            resolution=resolution,
            steps=steps,
            duration_s=actual_duration_s,
            cost_usd=actual_cost_usd,
            warm_container=route_decision["is_warm"],
            seed=seed,
            status="SUCCESS",
        )

        result_info = json.dumps({
            "job_id": job_id,
            "status": "SUCCESS",
            "gpu_allocated": selected_gpu,
            "duration_s": round(actual_duration_s, 3),
            "actual_cost_usd": round(actual_cost_usd, 6),
            "warm_container": route_decision["is_warm"],
            "hash_key": hash_key,
        }, indent=2)

        return (media_result, result_info, actual_duration_s, actual_cost_usd)
