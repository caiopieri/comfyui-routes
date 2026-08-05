"""Resolução e despacho de workflows ComfyUI."""

from .workflow_resolver import WorkflowResolution, resolve_workflow
from .dispatch_plan import build_dispatch_plan

__all__ = ["WorkflowResolution", "resolve_workflow", "build_dispatch_plan"]
