#!/usr/bin/env python3
"""
ZYRQUEN Native Model v10 — Experiment & Baseline Comparison

Read-only comparison of actual v10 evaluation reports (and optional frozen
v7/v8/v9 baseline reports when supplied on disk).

Safety:
  - Never trains a model or mutates checkpoints.
  - Never modifies v7, v8, or v9 files or baselines.
  - Never promotes or registers a model.
  - Never invents missing metrics or treats NOT RUN as zero or PASS.
  - Checks dataset_content_sha256 compatibility across compared v10 runs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_DIR = PROJECT_ROOT / "eval" / "nagi_v10"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

COMPARISON_REPORT_SCHEMA = "zyrquen.v10.comparison_report.v1"

CAPABILITY_KEYS = (
    "abstract_reasoning",
    "relational_generalization",
    "ood_transfer",
    "multi_step_planning",
    "self_verification",
    "knowledge_integration",
)

METRIC_KEYS = (
    "exact_match",
    "validation_exact_match",
    "test_exact_match",
    "eos_hit_rate",
    *(f"cap_{cap}_accuracy" for cap in CAPABILITY_KEYS),
)

VALID_STATUSES = {
    "PASS",
    "FAIL",
    "FAILED",
    "NOT RUN",
    "BLOCKED",
    "WAITING_RESOURCE",
    "WAITING_APPROVAL",
}


class ComparisonError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(value: Any) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    normalized = value.strip().upper()
    return normalized if normalized in VALID_STATUSES else "UNKNOWN"


def load_v10_report(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ComparisonError(f"Report must be a regular non-symlink file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"Cannot read report {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ComparisonError(f"Invalid report structure: {path.name}")
    if data.get("experiment") != "Native Model v10":
        raise ComparisonError(f"Not a v10 evaluation report: {path.name}")
    return data


def load_baseline_report(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        return {"path": str(path), "status": "NOT AVAILABLE", "reason": "file_not_found_or_symlink"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"path": str(path), "status": "UNREADABLE", "reason": str(exc)}
    if not isinstance(data, dict):
        return {"path": str(path), "status": "INVALID", "reason": "root_not_object"}
    return {
        "path": str(path),
        "status": "AVAILABLE",
        "experiment": data.get("experiment") or data.get("arm") or path.stem,
        "overall_status": data.get("overall_status") or data.get("status") or "UNKNOWN",
        "metrics": data.get("metrics"),
    }


def discover_reports(eval_dir: Path) -> list[Path]:
    if eval_dir.is_symlink() or not eval_dir.is_dir():
        raise ComparisonError(f"Invalid evaluation directory: {eval_dir}")
    reports = sorted(
        (p for p in eval_dir.glob("v10_evaluation_*.json") if p.is_file() and not p.is_symlink()),
        key=lambda p: p.name,
    )
    if not reports:
        raise ComparisonError("No v10 evaluation reports found.")
    return reports


def extract_metrics(report: dict[str, Any]) -> dict[str, float | None]:
    raw = report.get("metrics")
    if not isinstance(raw, dict):
        return {key: None for key in METRIC_KEYS}
    extracted: dict[str, float | None] = {}
    for key in METRIC_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            extracted[key] = None
            continue
        if isinstance(value, (int, float)):
            numeric = float(value)
            extracted[key] = numeric if (math.isfinite(numeric) and 0.0 <= numeric <= 1.0) else None
        else:
            extracted[key] = None
    return extracted


def extract_capabilities(report: dict[str, Any]) -> dict[str, str]:
    raw = report.get("capability_evaluation")
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, str] = {}
    for key in CAPABILITY_KEYS:
        val = raw.get(key)
        if isinstance(val, dict):
            out[key] = normalize_status(val.get("status"))
        else:
            out[key] = normalize_status(val)
    return out


def build_entry(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    inference_status = normalize_status(report.get("inference_status"))
    overall_status = normalize_status(report.get("overall_status"))
    metrics = extract_metrics(report)
    actual_metrics_available = (
        inference_status == "PASS" and any(v is not None for v in metrics.values())
    )
    return {
        "report": path.name,
        "experiment_id": report.get("experiment_id"),
        "created_at": report.get("created_at"),
        "dataset_content_sha256": report.get("dataset_content_sha256"),
        "dataset_integrity": normalize_status(report.get("dataset_integrity")),
        "leakage_audit_status": normalize_status(report.get("leakage_audit_status")),
        "inference_status": inference_status,
        "overall_status": overall_status,
        "metrics": metrics,
        "capabilities": extract_capabilities(report),
        "actual_metrics_available": actual_metrics_available,
    }


def compare_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    dataset_hashes = {
        e["dataset_content_sha256"]
        for e in entries
        if isinstance(e.get("dataset_content_sha256"), str) and e["dataset_content_sha256"]
    }
    matched_dataset = len(dataset_hashes) == 1

    metric_comparisons: dict[str, Any] = {}
    for metric in METRIC_KEYS:
        available = [
            {"report": entry["report"], "value": float(entry["metrics"][metric])}
            for entry in entries
            if entry["actual_metrics_available"] and entry["metrics"][metric] is not None
        ]
        available.sort(key=lambda item: (-item["value"], item["report"]))
        metric_comparisons[metric] = {
            "status": (
                "COMPARABLE"
                if (len(available) >= 2 and matched_dataset)
                else ("DATASET_MISMATCH" if len(available) >= 2 else "INSUFFICIENT_DATA")
            ),
            "ranked_results": available,
        }

    capability_comparisons = {
        capability: {entry["report"]: entry["capabilities"][capability] for entry in entries}
        for capability in CAPABILITY_KEYS
    }

    valid_experiments = [e for e in entries if e["actual_metrics_available"]]
    if len(valid_experiments) >= 2 and not matched_dataset:
        winner = {
            "status": "NOT COMPARABLE",
            "reason": "Evaluations ran against different or missing dataset_content_sha256 hashes.",
        }
    elif len(valid_experiments) >= 2:
        winner = {
            "status": "NOT SELECTED",
            "reason": (
                "Promotion requires full evaluation gate, zero regression, and governance approval; "
                "a single highest metric does not auto-select a winner."
            ),
        }
    elif len(valid_experiments) == 1:
        winner = {
            "status": "INSUFFICIENT COMPARISON",
            "reason": "Only one report contains actual inference metrics.",
        }
    else:
        winner = {
            "status": "NOT RUN",
            "reason": "No report contains verified actual inference metrics.",
        }

    return {
        "experiment_count": len(entries),
        "inference_verified_count": len(valid_experiments),
        "matched_dataset": matched_dataset,
        "dataset_hashes": sorted(dataset_hashes),
        "metric_comparisons": metric_comparisons,
        "capability_comparisons": capability_comparisons,
        "winner": winner,
    }


def build_result(
    entries: list[dict[str, Any]],
    baselines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    comparison = compare_entries(entries)
    comparable = comparison["inference_verified_count"] >= 2 and comparison["matched_dataset"]
    return {
        "schema_version": "1.0",
        "report_schema": COMPARISON_REPORT_SCHEMA,
        "project": "ZYRQUEN Ω∞",
        "experiment": "Native Model v10",
        "created_at": utc_now(),
        "overall_status": "COMPARISON_AVAILABLE" if comparable else "INSUFFICIENT_EVIDENCE",
        "experiments": entries,
        "baselines_read_only": baselines or [],
        "comparison": comparison,
        "safety": {
            "training_started": False,
            "checkpoints_modified": False,
            "baselines_modified": False,
            "model_promoted": False,
            "missing_metrics_fabricated": False,
            "not_run_treated_as_zero": False,
        },
        "limitations": [
            "Only evaluation reports are compared.",
            "This tool does not verify model weights directly.",
            "No model winner is automatically promoted.",
            "Capability claims require verified actual inference evidence.",
        ],
    }


def write_result(result: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ComparisonError("Output directory cannot be a symlink.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = output_dir / f"v10_comparison_{timestamp}.json"
    if output_path.exists():
        raise ComparisonError("Refusing to overwrite existing comparison.")

    payload = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=".v10_comparison_", suffix=".tmp", dir=output_dir)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if output_path.exists():
            raise ComparisonError("Output appeared during write; refusing overwrite.")
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare ZYRQUEN v10 evaluation reports.")
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reports", nargs="*", type=Path, help="Explicit v10 evaluation report paths.")
    parser.add_argument("--baseline-reports", nargs="*", type=Path, help="Optional frozen v7/v8/v9 report paths (read-only).")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.reports:
            report_paths = [p.expanduser().resolve() for p in args.reports]
        else:
            report_paths = discover_reports(args.eval_dir.expanduser().resolve())

        if len(report_paths) < 2:
            raise ComparisonError("At least two v10 evaluation reports are required for comparison.")

        entries = [build_entry(p, load_v10_report(p)) for p in report_paths]
        baselines = [
            load_baseline_report(p.expanduser().resolve())
            for p in (args.baseline_reports or [])
        ]
        result = build_result(entries, baselines)

        if not args.no_write_report:
            output_path = write_result(result, args.output_dir.expanduser().resolve())
            print(f"Report: {output_path}")
    except (ComparisonError, OSError) as exc:
        print(f"COMPARISON_FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"Experiments: {len(entries)}")
    print(f"Inference verified: {result['comparison']['inference_verified_count']}")
    print(f"Matched dataset: {result['comparison']['matched_dataset']}")
    print(f"Status: {result['overall_status']}")
    print(f"Winner: {result['comparison']['winner']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
