"""Execution facade and prediction-vs-reality feedback loop."""

from __future__ import annotations

import time
from typing import Mapping

from .models import BenchmarkSample, ExecutionPlan, ExecutionResult, InferenceRequest, TelemetryRecord
from .providers.base import ExecutionProvider
from .scheduler import AdaptiveScheduler


class Orchestrator:
    def __init__(self, scheduler: AdaptiveScheduler, providers: Mapping[str, ExecutionProvider]):
        self.scheduler = scheduler
        self.providers = dict(providers)

    def execute(self, request: InferenceRequest) -> tuple[ExecutionPlan, ExecutionResult]:
        result = self.scheduler.plan(request)
        assert result.selected is not None
        plan = result.selected
        try:
            provider = self.providers[plan.provider]
        except KeyError as error:
            raise RuntimeError(f"provider não registrado: {plan.provider}") from error

        started = time.perf_counter()
        try:
            execution = provider.execute(request, plan)
        except Exception as error:
            execution = ExecutionResult(
                output=None,
                actual_latency_s=time.perf_counter() - started,
                actual_cost_usd=0.0,
                success=False,
                error=str(error),
            )
        telemetry = TelemetryRecord(
            request_id=request.request_id,
            workload_key=request.workload.workload_key,
            target_id=plan.target_id,
            worker_id=plan.worker_id,
            predicted_latency_s=plan.prediction.predicted_latency_s,
            p95_latency_s=plan.prediction.p95_latency_s,
            predicted_cost_usd=plan.prediction.predicted_cost_usd,
            actual_latency_s=execution.actual_latency_s,
            actual_cost_usd=execution.actual_cost_usd,
            queue_delay_s=plan.prediction.expected_queue_delay_s,
            run_kind=plan.prediction.run_kind,
            success=execution.success,
            metadata=execution.metadata,
        )
        self.scheduler.store.record_telemetry(telemetry)
        # Real executions become additional evidence.  They are kept under
        # the same cold/warm key used by the harness, so the next plan can
        # recalibrate itself without a separate ETL job.
        self.scheduler.store.record_sample(
            BenchmarkSample(
                workload_key=request.workload.workload_key,
                target_id=plan.target_id,
                run_kind=plan.prediction.run_kind,
                run_index=self.scheduler.store.next_run_index(
                    request.workload.workload_key,
                    plan.target_id,
                    plan.prediction.run_kind,
                ),
                total_s=execution.actual_latency_s,
                actual_cost_usd=execution.actual_cost_usd,
                success=execution.success,
                error=execution.error,
                metadata={"source": "production", **execution.metadata},
            )
        )
        return plan, execution
