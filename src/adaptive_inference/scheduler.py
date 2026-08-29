"""SLA-aware adaptive planner for the MVP."""

from __future__ import annotations

from typing import Iterable, Optional

from .models import (
    ExecutionPlan,
    ExecutionTarget,
    InferenceRequest,
    Prediction,
    RuntimeWorker,
    SchedulingResult,
)
from .predictor import BenchmarkPredictor, PredictionUnavailable
from .registry import ProviderRegistry
from .storage import BenchmarkStore


class SchedulingError(RuntimeError):
    """No execution target satisfies the request constraints."""


class AdaptiveScheduler:
    def __init__(
        self,
        store: BenchmarkStore,
        registry: ProviderRegistry,
        predictor: Optional[BenchmarkPredictor] = None,
        workers: Iterable[RuntimeWorker] = (),
        safety_margin_s: float = 0.0,
    ):
        if safety_margin_s < 0:
            raise ValueError("safety_margin_s não pode ser negativo")
        self.store = store
        self.registry = registry
        self.predictor = predictor or BenchmarkPredictor(store)
        self.safety_margin_s = safety_margin_s
        initial_workers = list(workers)
        if not initial_workers:
            initial_workers = store.list_workers()
        self._workers: dict[str, RuntimeWorker] = {
            worker.worker_id: worker for worker in initial_workers
        }

    def update_worker(self, worker: RuntimeWorker) -> None:
        self._workers[worker.worker_id] = worker
        self.store.upsert_worker(worker)

    def _workers_for(self, target: ExecutionTarget) -> list[RuntimeWorker]:
        return [
            worker
            for worker in self._workers.values()
            if worker.target_id == target.target_id and worker.is_usable
        ]

    def _best_worker(self, target: ExecutionTarget, workload_key: str) -> Optional[RuntimeWorker]:
        workers = self._workers_for(target)
        compatible = [
            worker
            for worker in workers
            if worker.loaded_workload_key == workload_key and worker.is_warm
        ]
        if compatible:
            return min(compatible, key=lambda worker: (worker.queue_delay_s, -worker.reliability_score))
        # An idle cold/starting worker is still useful, but it cannot consume
        # warm statistics for this workload.
        return min(workers, key=lambda worker: (worker.queue_delay_s, -worker.reliability_score), default=None)

    def _score(
        self,
        prediction: Prediction,
        target: ExecutionTarget,
        mode: str,
        all_predictions: list[Prediction],
        latency_target_s: float | None = None,
    ) -> float:
        costs = [item.predicted_cost_usd for item in all_predictions]
        latencies = [item.p95_latency_s for item in all_predictions]
        min_cost, max_cost = min(costs), max(costs)
        min_latency, max_latency = min(latencies), max(latencies)

        def normalize(value: float, lower: float, upper: float) -> float:
            if upper == lower:
                return 0.0
            return (value - lower) / (upper - lower)

        cost_score = normalize(prediction.predicted_cost_usd, min_cost, max_cost)
        latency_score = normalize(prediction.p95_latency_s, min_latency, max_latency)
        quality_penalty = 1.0 - target.quality_score
        target_penalty = 0.0
        if latency_target_s is not None and latency_target_s > 0:
            target_penalty = max(0.0, prediction.p95_latency_s - latency_target_s) / latency_target_s
        if mode == "economy":
            return 0.70 * cost_score + 0.20 * latency_score + 0.05 * quality_penalty + 0.05 * target_penalty
        if mode == "fast":
            return 0.70 * latency_score + 0.20 * cost_score + 0.05 * quality_penalty + 0.05 * target_penalty
        if mode == "frontier":
            return 0.55 * quality_penalty + 0.25 * latency_score + 0.15 * cost_score + 0.05 * target_penalty
        return 0.42 * cost_score + 0.43 * latency_score + 0.10 * quality_penalty + 0.05 * target_penalty

    def plan(self, request: InferenceRequest) -> SchedulingResult:
        candidates: list[ExecutionPlan] = []
        rejected: list[ExecutionPlan] = []
        provisional: list[tuple[ExecutionTarget, Optional[RuntimeWorker], Prediction]] = []

        for target in self.registry.list_targets():
            if not target.supports(request.workload):
                continue
            worker = self._best_worker(target, request.workload.workload_key)
            try:
                prediction = self.predictor.predict(request.workload, target, worker)
            except PredictionUnavailable:
                continue
            provisional.append((target, worker, prediction))

        if not provisional:
            raise SchedulingError(
                f"nenhum target possui benchmark válido para {request.workload.workload_key}"
            )

        predictions = [item[2] for item in provisional]
        for target, worker, prediction in provisional:
            latency = prediction.p95_latency_s + self.safety_margin_s
            reason = None
            if request.sla.max_latency_s is not None and latency > request.sla.max_latency_s:
                reason = f"p95 {latency:.2f}s excede max_latency {request.sla.max_latency_s:.2f}s"
            elif (
                request.sla.max_queue_delay_s is not None
                and prediction.expected_queue_delay_s > request.sla.max_queue_delay_s
            ):
                reason = (
                    f"fila {prediction.expected_queue_delay_s:.2f}s excede max_queue_delay "
                    f"{request.sla.max_queue_delay_s:.2f}s"
                )
            elif (
                request.sla.max_cost_usd is not None
                and prediction.predicted_cost_usd > request.sla.max_cost_usd
            ):
                reason = (
                    f"custo previsto ${prediction.predicted_cost_usd:.4f} excede "
                    f"max_cost ${request.sla.max_cost_usd:.4f}"
                )
            elif (
                request.sla.min_quality is not None
                and target.quality_score < request.sla.min_quality
            ):
                reason = (
                    f"quality_score {target.quality_score:.2f} abaixo do mínimo "
                    f"{request.sla.min_quality:.2f}"
                )

            plan = ExecutionPlan(
                request_id=request.request_id,
                target_id=target.target_id,
                provider=target.provider,
                worker_id=worker.worker_id if worker else None,
                score=self._score(
                    prediction,
                    target,
                    request.sla.mode,
                    predictions,
                    request.sla.latency_target_s,
                ),
                prediction=prediction,
                accepted=reason is None,
                rejection_reason=reason,
            )
            (candidates if reason is None else rejected).append(plan)

        if not candidates:
            raise SchedulingError(
                "nenhum target atende ao SLA: "
                + "; ".join(plan.rejection_reason or "rejeitado" for plan in rejected)
            )
        candidates.sort(key=lambda plan: (plan.score, -plan.prediction.confidence))
        return SchedulingResult(
            request_id=request.request_id,
            selected=candidates[0],
            candidates=tuple(candidates),
            rejected=tuple(rejected),
        )
