"""Adapter for the existing deployed ComfyUI worker app on Modal.

This adapter is intentionally thin: the planner selects a target, and this
class translates the plan to the existing `dispatch_workflow.py` entrypoint.
It is useful for the current ComfyUI integration while the first native Wan
provider is being benchmarked.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Mapping

from ..models import ExecutionPlan, ExecutionResult, InferenceRequest
from ..registry import ProviderRegistry
from .base import ExecutionProvider, ProviderError


class ModalComfyUIProvider:
    provider_name = "modal"

    def __init__(
        self,
        registry: ProviderRegistry,
        project_root: str | Path,
        modal_command: str = "modal",
    ):
        self.registry = registry
        self.project_root = Path(project_root)
        self.modal_command = modal_command
        self.dispatch_script = self.project_root / "comfyui" / "modal_backend" / "dispatch_workflow.py"

    def execute(self, request: InferenceRequest, plan: ExecutionPlan) -> ExecutionResult:
        workflow = request.payload.get("workflow")
        if not isinstance(workflow, Mapping):
            raise ProviderError("request.payload.workflow deve conter um workflow ComfyUI API")
        target = self.registry.get_target(plan.target_id)
        gpu_name = str(target.metadata.get("modal_gpu_name", target.gpu))
        resolution = f"{request.workload.width}x{request.workload.height}"
        with tempfile.TemporaryDirectory(prefix="adaptive-inference-modal-") as temp_dir:
            workflow_path = Path(temp_dir) / "workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            command = [
                self.modal_command,
                "run",
                str(self.dispatch_script),
                str(workflow_path),
                "--resolution",
                resolution,
                "--steps",
                str(request.workload.steps),
                "--gpu-override",
                gpu_name,
            ]
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(self.project_root),
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as error:
                raise ProviderError((error.stderr or error.stdout or str(error))[-4000:]) from error

        summary = None
        for line in reversed(completed.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "actual" in candidate and "outputs" in candidate:
                summary = candidate
                break
        if summary is None:
            raise ProviderError("Modal não retornou um resumo de execução válido")
        metrics = summary["actual"]
        return ExecutionResult(
            output=summary["outputs"],
            actual_latency_s=float(metrics.get("duration_s", time.perf_counter() - started)),
            actual_cost_usd=float(metrics.get("actual_cost_usd", 0.0)),
            metadata={"provider": "modal", "gpu": gpu_name, "stdout_tail": completed.stdout[-1000:]},
        )
