"""Reproducible benchmark harness.

The harness owns experiment protocol and persistence, while an adapter owns
the provider-specific act of running one workload.  This keeps Modal, fal,
RunPod and local runners interchangeable without putting provider assumptions
into the benchmark database.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import BenchmarkSample, BenchmarkSummary, ExecutionTarget, WorkloadSpec
from .storage import BenchmarkStore


@dataclass(frozen=True)
class AdapterObservation:
    """Measurements returned by one provider execution."""

    total_s: float | None = None
    model_load_s: float | None = None
    inference_s: float | None = None
    max_vram_gb: float | None = None
    throughput: float | None = None
    actual_cost_usd: float | None = None
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BenchmarkAdapter(Protocol):
    def execute(
        self,
        workload: WorkloadSpec,
        target: ExecutionTarget,
        run_kind: str,
        run_index: int,
    ) -> AdapterObservation:
        """Execute exactly one run against the requested target."""


@dataclass(frozen=True)
class BenchmarkConfig:
    cold_runs: int = 1
    warm_runs: int = 5
    pause_between_runs_s: float = 0.0

    def __post_init__(self) -> None:
        if self.cold_runs < 1 or self.warm_runs < 1:
            raise ValueError("cold_runs e warm_runs devem ser pelo menos 1")
        if self.pause_between_runs_s < 0:
            raise ValueError("pause_between_runs_s não pode ser negativo")


@dataclass(frozen=True)
class BenchmarkRunResult:
    workload_key: str
    target_id: str
    samples: tuple[BenchmarkSample, ...]
    cold_summary: BenchmarkSummary | None
    warm_summary: BenchmarkSummary | None


class BenchmarkHarness:
    def __init__(self, store: BenchmarkStore):
        self.store = store

    def run(
        self,
        workload: WorkloadSpec,
        target: ExecutionTarget,
        adapter: BenchmarkAdapter,
        config: BenchmarkConfig = BenchmarkConfig(),
    ) -> BenchmarkRunResult:
        samples: list[BenchmarkSample] = []
        sequence = [("cold", index) for index in range(config.cold_runs)]
        sequence += [("warm", index) for index in range(config.warm_runs)]

        for position, (run_kind, run_index) in enumerate(sequence):
            started = time.perf_counter()
            try:
                observation = adapter.execute(workload, target, run_kind, run_index)
            except Exception as error:  # adapters must not abort the whole matrix
                observation = AdapterObservation(success=False, error=str(error))
            wall_time_s = time.perf_counter() - started
            total_s = observation.total_s if observation.total_s is not None else wall_time_s
            cost = observation.actual_cost_usd
            if cost is None and observation.success:
                cost = total_s * target.price_per_second
            sample = BenchmarkSample(
                workload_key=workload.workload_key,
                target_id=target.target_id,
                run_kind=run_kind,
                run_index=run_index,
                total_s=max(0.0, total_s),
                model_load_s=observation.model_load_s,
                inference_s=observation.inference_s,
                max_vram_gb=observation.max_vram_gb,
                throughput=observation.throughput,
                actual_cost_usd=cost,
                success=observation.success,
                error=observation.error,
                metadata={"wall_time_s": wall_time_s, **observation.metadata},
            )
            self.store.record_sample(sample)
            samples.append(sample)
            if position != len(sequence) - 1 and config.pause_between_runs_s:
                time.sleep(config.pause_between_runs_s)

        return BenchmarkRunResult(
            workload_key=workload.workload_key,
            target_id=target.target_id,
            samples=tuple(samples),
            cold_summary=self.store.summarize(workload.workload_key, target.target_id, "cold"),
            warm_summary=self.store.summarize(workload.workload_key, target.target_id, "warm"),
        )
