"""Plano de execução: alvo local/Modal e GPU antes de iniciar um job."""

from typing import Any, Dict, Iterable, Optional

from comfyui.dispatch.workflow_resolver import resolve_workflow
from comfyui.scheduler.router import GPURouter


def build_dispatch_plan(
    workflow: Dict[str, Any],
    router: GPURouter,
    resolution: str = "1024x1024",
    steps: int = 30,
    lambda_val: Optional[float] = None,
    local_model_roots: Optional[Iterable[str]] = None,
    warm_gpus: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Resolve dependências e calcula a GPU somente quando Modal é necessário."""
    resolved = resolve_workflow(workflow, local_model_roots)
    plan = {
        "model": resolved.model,
        "target": resolved.execution_target,
        "missing_files": resolved.missing_files,
        "required_files": resolved.required_files,
        "vram_required_gb": resolved.vram_required_gb,
    }
    if resolved.needs_modal:
        plan["route"] = router.route_job(
            model=resolved.model,
            resolution=resolution,
            steps=steps,
            lambda_val=lambda_val,
            warm_gpus=warm_gpus,
        )
    else:
        plan["route"] = None
    return plan
