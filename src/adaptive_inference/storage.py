"""SQLite persistence for benchmark knowledge and runtime telemetry."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .models import (
    BenchmarkSample,
    BenchmarkSummary,
    RuntimeWorker,
    TelemetryRecord,
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("não é possível calcular percentile sem amostras")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


class BenchmarkStore:
    """Small, inspectable knowledge base suitable for the MVP.

    Raw samples are retained.  Summaries are calculated on read so a change
    in percentile policy never requires a destructive migration.
    """

    def __init__(self, db_path: str | os.PathLike[str] = "~/.adaptive_inference.db"):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS benchmark_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workload_key TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    run_kind TEXT NOT NULL CHECK (run_kind IN ('cold', 'warm')),
                    run_index INTEGER NOT NULL,
                    total_s REAL NOT NULL,
                    model_load_s REAL,
                    inference_s REAL,
                    max_vram_gb REAL,
                    throughput REAL,
                    actual_cost_usd REAL,
                    success INTEGER NOT NULL,
                    error TEXT,
                    recorded_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_benchmark_lookup
                    ON benchmark_samples(workload_key, target_id, run_kind, success);

                CREATE TABLE IF NOT EXISTS runtime_workers (
                    worker_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    loaded_workload_key TEXT,
                    queue_delay_s REAL NOT NULL,
                    queue_depth INTEGER NOT NULL,
                    available_vram_gb REAL,
                    reliability_score REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workers_target
                    ON runtime_workers(target_id, state);

                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    workload_key TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    worker_id TEXT,
                    predicted_latency_s REAL NOT NULL,
                    p95_latency_s REAL NOT NULL,
                    predicted_cost_usd REAL NOT NULL,
                    actual_latency_s REAL NOT NULL,
                    actual_cost_usd REAL NOT NULL,
                    queue_delay_s REAL NOT NULL,
                    run_kind TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    recorded_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_telemetry_workload
                    ON telemetry(workload_key, target_id, recorded_at);
                """
            )

    def record_sample(self, sample: BenchmarkSample) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO benchmark_samples (
                    workload_key, target_id, run_kind, run_index, total_s,
                    model_load_s, inference_s, max_vram_gb, throughput,
                    actual_cost_usd, success, error, recorded_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.workload_key,
                    sample.target_id,
                    sample.run_kind,
                    sample.run_index,
                    sample.total_s,
                    sample.model_load_s,
                    sample.inference_s,
                    sample.max_vram_gb,
                    sample.throughput,
                    sample.actual_cost_usd,
                    int(sample.success),
                    sample.error,
                    sample.recorded_at,
                    json.dumps(sample.metadata, sort_keys=True),
                ),
            )

    def next_run_index(self, workload_key: str, target_id: str, run_kind: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(run_index), -1) + 1 AS next_index
                FROM benchmark_samples
                WHERE workload_key = ? AND target_id = ? AND run_kind = ?
                """,
                (workload_key, target_id, run_kind),
            ).fetchone()
        return int(row["next_index"])

    def summarize(
        self,
        workload_key: str,
        target_id: str,
        run_kind: str,
    ) -> Optional[BenchmarkSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT total_s, actual_cost_usd, success
                FROM benchmark_samples
                WHERE workload_key = ? AND target_id = ? AND run_kind = ?
                """,
                (workload_key, target_id, run_kind),
            ).fetchall()

        if not rows:
            return None
        successful = [row for row in rows if row["success"]]
        if not successful:
            return None
        latency = [float(row["total_s"]) for row in successful]
        costs = [float(row["actual_cost_usd"]) for row in successful if row["actual_cost_usd"] is not None]
        if not costs:
            costs = [0.0 for _ in latency]
        return BenchmarkSummary(
            workload_key=workload_key,
            target_id=target_id,
            run_kind=run_kind,
            sample_count=len(successful),
            p50_latency_s=_percentile(latency, 0.50),
            p90_latency_s=_percentile(latency, 0.90),
            p95_latency_s=_percentile(latency, 0.95),
            p99_latency_s=_percentile(latency, 0.99),
            mean_latency_s=sum(latency) / len(latency),
            p50_cost_usd=_percentile(costs, 0.50),
            p95_cost_usd=_percentile(costs, 0.95),
            success_rate=len(successful) / len(rows),
        )

    def upsert_worker(self, worker: RuntimeWorker) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_workers (
                    worker_id, target_id, state, loaded_workload_key,
                    queue_delay_s, queue_depth, available_vram_gb,
                    reliability_score, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    target_id=excluded.target_id,
                    state=excluded.state,
                    loaded_workload_key=excluded.loaded_workload_key,
                    queue_delay_s=excluded.queue_delay_s,
                    queue_depth=excluded.queue_depth,
                    available_vram_gb=excluded.available_vram_gb,
                    reliability_score=excluded.reliability_score,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    worker.worker_id,
                    worker.target_id,
                    worker.state,
                    worker.loaded_workload_key,
                    worker.queue_delay_s,
                    worker.queue_depth,
                    worker.available_vram_gb,
                    worker.reliability_score,
                    worker.updated_at,
                    json.dumps(worker.metadata, sort_keys=True),
                ),
            )

    def list_workers(self, target_id: Optional[str] = None) -> list[RuntimeWorker]:
        with self._connect() as connection:
            if target_id:
                rows = connection.execute(
                    "SELECT * FROM runtime_workers WHERE target_id = ?",
                    (target_id,),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM runtime_workers").fetchall()
        return [
            RuntimeWorker(
                worker_id=row["worker_id"],
                target_id=row["target_id"],
                state=row["state"],
                loaded_workload_key=row["loaded_workload_key"],
                queue_delay_s=row["queue_delay_s"],
                queue_depth=row["queue_depth"],
                available_vram_gb=row["available_vram_gb"],
                reliability_score=row["reliability_score"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def record_telemetry(self, record: TelemetryRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telemetry (
                    request_id, workload_key, target_id, worker_id,
                    predicted_latency_s, p95_latency_s, predicted_cost_usd,
                    actual_latency_s, actual_cost_usd, queue_delay_s,
                    run_kind, success, recorded_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.request_id,
                    record.workload_key,
                    record.target_id,
                    record.worker_id,
                    record.predicted_latency_s,
                    record.p95_latency_s,
                    record.predicted_cost_usd,
                    record.actual_latency_s,
                    record.actual_cost_usd,
                    record.queue_delay_s,
                    record.run_kind,
                    int(record.success),
                    record.recorded_at,
                    json.dumps(record.metadata, sort_keys=True),
                ),
            )

    def count_samples(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM benchmark_samples").fetchone()
        return int(row["count"])
