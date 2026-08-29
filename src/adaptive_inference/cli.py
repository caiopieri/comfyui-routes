"""Operator CLI for inspecting the MVP knowledge base and making plans."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .models import ExecutionTarget, InferenceRequest, SLA, WorkloadSpec
from .registry import ProviderRegistry
from .scheduler import AdaptiveScheduler, SchedulingError
from .storage import BenchmarkStore


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _workload(data: dict[str, Any]) -> WorkloadSpec:
    data = {key: value for key, value in data.items() if key != "workload_key"}
    return WorkloadSpec(**data)


def _target(data: dict[str, Any]) -> ExecutionTarget:
    data = dict(data)
    if "supported_workloads" in data:
        data["supported_workloads"] = tuple(data["supported_workloads"])
    return ExecutionTarget(**data)


def _request(data: dict[str, Any]) -> InferenceRequest:
    workload = _workload(data["workload"])
    sla = SLA(**data.get("sla", {}))
    return InferenceRequest(
        workload=workload,
        sla=sla,
        request_id=data.get("request_id", ""),
        created_at=data.get("created_at", None) or time.time(),
        payload=data.get("payload", {}),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adaptive-inference")
    parser.add_argument("--db", default="~/.adaptive_inference.db", help="SQLite knowledge base")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="exibe percentis de um target")
    summary.add_argument("--workload-key", required=True)
    summary.add_argument("--target-id", required=True)
    summary.add_argument("--run-kind", choices=["cold", "warm"], required=True)

    plan = subparsers.add_parser("plan", help="calcula um plano a partir de JSON")
    plan.add_argument("--request", required=True, help="arquivo JSON da request")
    plan.add_argument("--targets", required=True, help="arquivo JSON com uma lista de targets")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = BenchmarkStore(args.db)
    if args.command == "summary":
        summary = store.summarize(args.workload_key, args.target_id, args.run_kind)
        if summary is None:
            print("Nenhum benchmark encontrado", file=sys.stderr)
            return 1
        print(json.dumps(summary.__dict__, indent=2, ensure_ascii=False))
        return 0

    request = _request(_load_json(args.request))
    target_data = json.loads(Path(args.targets).read_text(encoding="utf-8"))
    registry = ProviderRegistry(_target(item) for item in target_data)
    try:
        result = AdaptiveScheduler(store, registry).plan(request)
    except SchedulingError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({
        "request_id": result.request_id,
        "selected": result.selected.__dict__ if result.selected else None,
        "candidates": [candidate.__dict__ for candidate in result.candidates],
        "rejected": [candidate.__dict__ for candidate in result.rejected],
    }, default=lambda value: value.__dict__, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
