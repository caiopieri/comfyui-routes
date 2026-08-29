"""Provider boundary used by the execution layer."""

from __future__ import annotations

from typing import Protocol

from ..models import ExecutionPlan, ExecutionResult, InferenceRequest


class ProviderError(RuntimeError):
    """An execution provider could not complete a planned request."""


class ExecutionProvider(Protocol):
    provider_name: str

    def execute(self, request: InferenceRequest, plan: ExecutionPlan) -> ExecutionResult:
        """Execute exactly the target selected by the planner."""
