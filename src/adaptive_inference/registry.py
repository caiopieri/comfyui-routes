"""Provider and execution-target registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .models import ExecutionTarget


class ProviderRegistry:
    """Registry kept deliberately simple so providers can be plugins later."""

    def __init__(self, targets: Iterable[ExecutionTarget] = ()):
        self._targets: dict[str, ExecutionTarget] = {}
        self._providers: dict[str, Any] = {}
        for target in targets:
            self.register_target(target)

    def register_provider(self, provider: Any) -> None:
        name = getattr(provider, "provider_name", "")
        if not name:
            raise ValueError("provider precisa declarar provider_name")
        if name in self._providers:
            raise ValueError(f"provider já registrado: {name}")
        self._providers[name] = provider

    def get_provider(self, provider_name: str) -> Any:
        try:
            return self._providers[provider_name]
        except KeyError as error:
            raise KeyError(f"provider não registrado: {provider_name}") from error

    def list_providers(self) -> list[Any]:
        return list(self._providers.values())

    def register_target(self, target: ExecutionTarget) -> None:
        if target.target_id in self._targets:
            raise ValueError(f"target já registrado: {target.target_id}")
        self._targets[target.target_id] = target

    def replace_target(self, target: ExecutionTarget) -> None:
        self._targets[target.target_id] = target

    def get_target(self, target_id: str) -> ExecutionTarget:
        try:
            return self._targets[target_id]
        except KeyError as error:
            raise KeyError(f"target não registrado: {target_id}") from error

    def list_targets(self, provider: Optional[str] = None) -> list[ExecutionTarget]:
        targets = list(self._targets.values())
        if provider is not None:
            targets = [target for target in targets if target.provider == provider]
        return [target for target in targets if target.enabled]
