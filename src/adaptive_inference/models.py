"""Domain contracts shared by the benchmarker, predictor and scheduler."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


def now_unix() -> float:
    return time.time()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class WorkloadSpec:
    """A fully specified inference workload.

    The workload key includes every field that can affect performance.  A
    benchmark is therefore never reused accidentally for a different model
    revision, resolution, frame count or quantization.
    """

    workload_id: str
    model: str
    model_version: str
    pipeline: str
    pipeline_version: str
    quantization: str
    width: int
    height: int
    frames: int
    steps: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("width", "height", "frames", "steps"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} deve ser maior que zero")
        if not self.workload_id.strip():
            raise ValueError("workload_id não pode ser vazio")

    @property
    def workload_key(self) -> str:
        payload = _jsonable(asdict(self))
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()[:16]
        return f"{self.workload_id}:{digest}"

    def as_dict(self) -> dict[str, Any]:
        return {**_jsonable(asdict(self)), "workload_key": self.workload_key}


@dataclass(frozen=True)
class SLA:
    """Constraints and preference mode attached to a request."""

    latency_target_s: Optional[float] = None
    max_latency_s: Optional[float] = None
    max_queue_delay_s: Optional[float] = None
    max_cost_usd: Optional[float] = None
    min_quality: Optional[float] = None
    priority: int = 50
    mode: str = "balanced"

    def __post_init__(self) -> None:
        for name in (
            "latency_target_s",
            "max_latency_s",
            "max_queue_delay_s",
            "max_cost_usd",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} não pode ser negativo")
        if self.latency_target_s is not None and self.max_latency_s is not None:
            if self.latency_target_s > self.max_latency_s:
                raise ValueError("latency_target_s não pode exceder max_latency_s")
        if self.min_quality is not None and not 0 <= self.min_quality <= 1:
            raise ValueError("min_quality deve estar entre 0 e 1")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority deve estar entre 0 e 100")
        if self.mode not in {"economy", "balanced", "fast", "frontier", "custom"}:
            raise ValueError(f"modo de SLA desconhecido: {self.mode}")


@dataclass(frozen=True)
class InferenceRequest:
    workload: WorkloadSpec
    sla: SLA = field(default_factory=SLA)
    request_id: str = ""
    created_at: float = field(default_factory=now_unix)
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id:
            object.__setattr__(self, "request_id", f"req-{int(self.created_at * 1000)}")


@dataclass(frozen=True)
class ExecutionTarget:
    """A benchmarkable execution option, including multi-GPU topology."""

    target_id: str
    provider: str
    gpu: str
    gpu_count: int = 1
    interconnect: str = "unknown"
    region: str = "unknown"
    price_per_gpu_second: float = 0.0
    startup_latency_s: float = 0.0
    quality_score: float = 0.0
    trust_tier: int = 0
    supported_workloads: tuple[str, ...] = ()
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gpu_count <= 0:
            raise ValueError("gpu_count deve ser maior que zero")
        if self.price_per_gpu_second < 0 or self.startup_latency_s < 0:
            raise ValueError("preço e startup_latency_s não podem ser negativos")
        if not 0 <= self.quality_score <= 1:
            raise ValueError("quality_score deve estar entre 0 e 1")

    @property
    def price_per_second(self) -> float:
        return self.price_per_gpu_second * self.gpu_count

    def supports(self, workload: WorkloadSpec) -> bool:
        if not self.supported_workloads:
            return True
        return any(
            token in {workload.workload_id, workload.model, workload.pipeline}
            for token in self.supported_workloads
        )


WORKER_STATES = {
    "COLD",
    "STARTING",
    "LOADING_MODEL",
    "WARM_IDLE",
    "BUSY",
    "DRAINING",
    "TERMINATING",
}


@dataclass(frozen=True)
class RuntimeWorker:
    worker_id: str
    target_id: str
    state: str
    loaded_workload_key: Optional[str] = None
    queue_delay_s: float = 0.0
    queue_depth: int = 0
    available_vram_gb: Optional[float] = None
    reliability_score: float = 1.0
    updated_at: float = field(default_factory=now_unix)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in WORKER_STATES:
            raise ValueError(f"estado de worker desconhecido: {self.state}")
        if self.queue_delay_s < 0 or self.queue_depth < 0:
            raise ValueError("fila não pode ter valores negativos")
        if not 0 <= self.reliability_score <= 1:
            raise ValueError("reliability_score deve estar entre 0 e 1")

    @property
    def is_usable(self) -> bool:
        return self.state in {"WARM_IDLE", "BUSY", "STARTING", "LOADING_MODEL", "COLD"}

    @property
    def is_warm(self) -> bool:
        return self.state in {"WARM_IDLE", "BUSY"} and bool(self.loaded_workload_key)


@dataclass(frozen=True)
class BenchmarkSample:
    workload_key: str
    target_id: str
    run_kind: str
    run_index: int
    total_s: float
    model_load_s: Optional[float] = None
    inference_s: Optional[float] = None
    max_vram_gb: Optional[float] = None
    throughput: Optional[float] = None
    actual_cost_usd: Optional[float] = None
    success: bool = True
    error: Optional[str] = None
    recorded_at: float = field(default_factory=now_unix)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.run_kind not in {"cold", "warm"}:
            raise ValueError("run_kind deve ser cold ou warm")
        if self.run_index < 0 or self.total_s < 0:
            raise ValueError("run_index e total_s não podem ser negativos")


@dataclass(frozen=True)
class BenchmarkSummary:
    workload_key: str
    target_id: str
    run_kind: str
    sample_count: int
    p50_latency_s: float
    p90_latency_s: float
    p95_latency_s: float
    p99_latency_s: float
    mean_latency_s: float
    p50_cost_usd: float
    p95_cost_usd: float
    success_rate: float


@dataclass(frozen=True)
class Prediction:
    target_id: str
    worker_id: Optional[str]
    run_kind: str
    predicted_latency_s: float
    p95_latency_s: float
    predicted_cost_usd: float
    expected_queue_delay_s: float
    confidence: float
    sample_count: int
    quality_score: float
    explanation: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    request_id: str
    target_id: str
    provider: str
    worker_id: Optional[str]
    score: float
    prediction: Prediction
    accepted: bool = True
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class SchedulingResult:
    request_id: str
    selected: Optional[ExecutionPlan]
    candidates: tuple[ExecutionPlan, ...] = ()
    rejected: tuple[ExecutionPlan, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    output: Any
    actual_latency_s: float
    actual_cost_usd: float
    success: bool = True
    error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TelemetryRecord:
    request_id: str
    workload_key: str
    target_id: str
    worker_id: Optional[str]
    predicted_latency_s: float
    p95_latency_s: float
    predicted_cost_usd: float
    actual_latency_s: float
    actual_cost_usd: float
    queue_delay_s: float
    run_kind: str
    success: bool
    recorded_at: float = field(default_factory=now_unix)
    metadata: Mapping[str, Any] = field(default_factory=dict)
