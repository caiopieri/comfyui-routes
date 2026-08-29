"""Benchmark-backed latency and cost prediction."""

from __future__ import annotations

import math
from typing import Optional

from .models import (
    ExecutionTarget,
    Prediction,
    RuntimeWorker,
    WorkloadSpec,
)
from .storage import BenchmarkStore


class PredictionUnavailable(Exception):
    """Raised when a target has no successful benchmark for this workload."""


class BenchmarkPredictor:
    def __init__(self, store: BenchmarkStore, min_confidence_samples: int = 5):
        self.store = store
        self.min_confidence_samples = max(1, min_confidence_samples)

    def predict(
        self,
        workload: WorkloadSpec,
        target: ExecutionTarget,
        worker: Optional[RuntimeWorker] = None,
    ) -> Prediction:
        compatible_warm = bool(
            worker
            and worker.is_warm
            and worker.loaded_workload_key == workload.workload_key
        )
        run_kind = "warm" if compatible_warm else "cold"
        summary = self.store.summarize(workload.workload_key, target.target_id, run_kind)
        if summary is None:
            raise PredictionUnavailable(
                f"sem benchmark {run_kind} para {workload.workload_key} em {target.target_id}"
            )

        if worker is None:
            # The cold benchmark's total_s already includes startup.  Adding
            # the catalog estimate here would count cold start twice.
            queue_delay = 0.0
            worker_id = None
            explanation = "sem worker compatível; usando benchmark cold com startup medido"
        else:
            queue_delay = worker.queue_delay_s
            worker_id = worker.worker_id
            explanation = (
                "worker quente compatível; usando benchmark warm"
                if compatible_warm
                else "worker existente incompatível; tratando execução como cold"
            )

        # Confidence is intentionally transparent.  A future model can use
        # Bayesian intervals, but sample count is already safer than pretending
        # that one measurement is as trustworthy as twenty.
        confidence = min(1.0, math.sqrt(summary.sample_count / self.min_confidence_samples))
        predicted_latency = summary.p50_latency_s + queue_delay
        p95_latency = summary.p95_latency_s + queue_delay
        return Prediction(
            target_id=target.target_id,
            worker_id=worker_id,
            run_kind=run_kind,
            predicted_latency_s=predicted_latency,
            p95_latency_s=p95_latency,
            predicted_cost_usd=summary.p50_cost_usd,
            expected_queue_delay_s=queue_delay,
            confidence=confidence,
            sample_count=summary.sample_count,
            quality_score=target.quality_score,
            explanation=explanation,
        )
