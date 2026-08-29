import tempfile
import unittest
from pathlib import Path

from adaptive_inference import (
    AdapterObservation,
    AdaptiveScheduler,
    BenchmarkConfig,
    BenchmarkHarness,
    BenchmarkPredictor,
    BenchmarkStore,
    ExecutionResult,
    ExecutionTarget,
    InferenceRequest,
    Orchestrator,
    ProviderRegistry,
    RuntimeWorker,
    SLA,
    SchedulingError,
    WorkloadSpec,
)


def workload() -> WorkloadSpec:
    return WorkloadSpec(
        workload_id="wan22-t2v-720p-81f",
        model="Wan2.2-A14B",
        model_version="2.2",
        pipeline="wan-t2v",
        pipeline_version="pipeline-1",
        quantization="fp8",
        width=1280,
        height=720,
        frames=81,
        steps=30,
    )


def target(target_id: str, price: float, quality: float = 0.9) -> ExecutionTarget:
    return ExecutionTarget(
        target_id=target_id,
        provider="fake",
        gpu=target_id,
        price_per_gpu_second=price,
        startup_latency_s=10,
        quality_score=quality,
        supported_workloads=("wan22-t2v-720p-81f",),
    )


class SequenceAdapter:
    def __init__(self, cold: float, warm: float):
        self.cold = cold
        self.warm = warm
        self.calls = []

    def execute(self, workload, target, run_kind, run_index):
        self.calls.append((target.target_id, run_kind, run_index, workload.workload_key))
        seconds = self.cold if run_kind == "cold" else self.warm + run_index
        return AdapterObservation(
            total_s=seconds,
            model_load_s=seconds - self.warm if run_kind == "cold" else 0,
            inference_s=seconds,
        )


class FakeProvider:
    provider_name = "fake"

    def execute(self, request, plan):
        return ExecutionResult(
            output={"target": plan.target_id},
            actual_latency_s=3.5,
            actual_cost_usd=0.03,
        )


class AdaptiveInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = BenchmarkStore(Path(self.temp_dir.name) / "knowledge.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_harness_separates_cold_and_warm_runs(self):
        current_workload = workload()
        current_target = target("target-a", 0.001)
        adapter = SequenceAdapter(cold=12, warm=2)
        result = BenchmarkHarness(self.store).run(
            current_workload,
            current_target,
            adapter,
            BenchmarkConfig(cold_runs=1, warm_runs=3),
        )

        self.assertEqual(len(result.samples), 4)
        self.assertEqual(result.cold_summary.sample_count, 1)
        self.assertEqual(result.warm_summary.sample_count, 3)
        self.assertEqual([call[1] for call in adapter.calls], ["cold", "warm", "warm", "warm"])
        self.assertEqual(adapter.calls[0][3], current_workload.workload_key)
        self.assertAlmostEqual(result.warm_summary.p50_latency_s, 3.0)
        self.assertAlmostEqual(result.warm_summary.p95_latency_s, 3.9)

    def test_summary_uses_percentiles_and_success_rate(self):
        current_workload = workload()
        current_target = target("target-a", 0.001)
        for index, seconds in enumerate([1, 2, 3, 4, 5]):
            from adaptive_inference.models import BenchmarkSample

            self.store.record_sample(
                BenchmarkSample(
                    workload_key=current_workload.workload_key,
                    target_id=current_target.target_id,
                    run_kind="warm",
                    run_index=index,
                    total_s=seconds,
                    actual_cost_usd=seconds / 100,
                )
            )
        summary = self.store.summarize(current_workload.workload_key, "target-a", "warm")
        self.assertEqual(summary.sample_count, 5)
        self.assertAlmostEqual(summary.p50_latency_s, 3.0)
        self.assertAlmostEqual(summary.p95_latency_s, 4.8)
        self.assertAlmostEqual(summary.p99_latency_s, 4.96)

    def test_warm_worker_uses_warm_knowledge_and_queue(self):
        current_workload = workload()
        current_target = target("target-a", 0.001)
        adapter = SequenceAdapter(cold=12, warm=2)
        BenchmarkHarness(self.store).run(
            current_workload,
            current_target,
            adapter,
            BenchmarkConfig(cold_runs=1, warm_runs=5),
        )
        worker = RuntimeWorker(
            worker_id="worker-a",
            target_id="target-a",
            state="BUSY",
            loaded_workload_key=current_workload.workload_key,
            queue_delay_s=1.7,
        )
        prediction = BenchmarkPredictor(self.store).predict(current_workload, current_target, worker)
        self.assertEqual(prediction.run_kind, "warm")
        self.assertEqual(prediction.worker_id, "worker-a")
        self.assertAlmostEqual(prediction.expected_queue_delay_s, 1.7)
        self.assertAlmostEqual(prediction.predicted_latency_s, 5.7)

    def test_scheduler_enforces_sla_and_supports_policy_modes(self):
        current_workload = workload()
        cheap = target("cheap", 0.001)
        fast = target("fast", 0.01)
        for current_target, seconds in ((cheap, 20), (fast, 8)):
            adapter = SequenceAdapter(cold=seconds, warm=seconds)
            BenchmarkHarness(self.store).run(
                current_workload,
                current_target,
                adapter,
                BenchmarkConfig(cold_runs=1, warm_runs=5),
            )
        registry = ProviderRegistry([cheap, fast])

        economy = AdaptiveScheduler(self.store, registry).plan(
            InferenceRequest(workload=current_workload, sla=SLA(mode="economy"))
        )
        self.assertEqual(economy.selected.target_id, "cheap")

        fast_result = AdaptiveScheduler(self.store, registry).plan(
            InferenceRequest(
                workload=current_workload,
                sla=SLA(mode="fast", max_latency_s=12),
            )
        )
        self.assertEqual(fast_result.selected.target_id, "fast")
        self.assertEqual([item.target_id for item in fast_result.rejected], ["cheap"])

    def test_orchestrator_records_prediction_feedback(self):
        current_workload = workload()
        current_target = target("target-a", 0.001)
        BenchmarkHarness(self.store).run(
            current_workload,
            current_target,
            SequenceAdapter(cold=10, warm=3),
            BenchmarkConfig(cold_runs=1, warm_runs=5),
        )
        scheduler = AdaptiveScheduler(self.store, ProviderRegistry([current_target]))
        orchestrator = Orchestrator(scheduler, {"fake": FakeProvider()})
        plan, execution = orchestrator.execute(InferenceRequest(workload=current_workload))
        self.assertTrue(execution.success)
        self.assertEqual(execution.output["target"], "target-a")
        with self.store._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(plan.provider, "fake")

    def test_missing_benchmark_is_a_hard_stop(self):
        with self.assertRaises(SchedulingError):
            AdaptiveScheduler(
                self.store,
                ProviderRegistry([target("target-a", 0.001)]),
            ).plan(InferenceRequest(workload=workload()))


if __name__ == "__main__":
    unittest.main()
