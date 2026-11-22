#!/usr/bin/env python3
"""
ZYRQUEN Native Model v10 — Experiment Comparison

Read-only comparison of actual v10 evaluation reports.

Safety:
- Never trains a model.
- Never modifies checkpoints.
- Never promotes or registers a model.
- Never invents missing metrics.
- NOT RUN is never treated as zero or PASS.
- Reports insufficient evidence when metrics are unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EVAL_DIR = PROJECT_ROOT / "eval" / "nagi_v10"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

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
    "unseen_accuracy",
    "ood_accuracy",
    "reasoning_accuracy",
    "generalization_score",
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

    if normalized not in VALID_STATUSES:
        return "UNKNOWN"

    return normalized


def load_report(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ComparisonError(
            f"Report must be a regular non-symlink file: {path}"
        )

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(
            f"Cannot read report {path.name}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ComparisonError(
            f"Invalid report structure: {path.name}"
        )

    if data.get("experiment") != "Native Model v10":
        raise ComparisonError(
            f"Not a v10 evaluation report: {path.name}"
        )

    return data


def discover_reports(eval_dir: Path) -> list[Path]:
    if eval_dir.is_symlink() or not eval_dir.is_dir():
        raise ComparisonError(
            f"Invalid evaluation directory: {eval_dir}"
        )

    reports = sorted(
        (
            path
            for path in eval_dir.glob("v10_evaluation_*.json")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.name,
    )

    if not reports:
        raise ComparisonError(
            "No v10 evaluation reports found."
        )

    return reports


def extract_metrics(
    report: dict[str, Any],
) -> dict[str, float | None]:
    raw = report.get("metrics")

    if not isinstance(raw, dict):
        return {
            key: None
            for key in METRIC_KEYS
        }

    extracted: dict[str, float | None] = {}

    for key in METRIC_KEYS:
        value = raw.get(key)

        if isinstance(value, bool):
            extracted[key] = None
            continue

        if isinstance(value, (int, float)):
            numeric = float(value)

            if 0.0 <= numeric <= 1.0:
                extracted[key] = numeric
            else:
                extracted[key] = None
        else:
            extracted[key] = None

    return extracted


def extract_capabilities(
    report: dict[str, Any],
) -> dict[str, str]:
    raw = report.get("capability_evaluation")

    if not isinstance(raw, dict):
        raw = {}

    return {
        key: normalize_status(raw.get(key))
        for key in CAPABILITY_KEYS
    }


def build_entry(
    path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    inference_status = normalize_status(
        report.get("inference_status")
    )

    overall_status = normalize_status(
        report.get("overall_status")
    )

    metrics = extract_metrics(report)

    actual_metrics_available = (
        inference_status == "PASS"
        and any(value is not None for value in metrics.values())
    )

    return {
        "report": path.name,
        "created_at": report.get("created_at"),
        "inference_status": inference_status,
        "overall_status": overall_status,
        "dataset_integrity": normalize_status(
            report.get("dataset_integrity")
        ),
        "metrics": metrics,
        "capabilities": extract_capabilities(report),
        "actual_metrics_available": actual_metrics_available,
    }


def compare_entries(
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    metric_comparisons = {}

    for metric in METRIC_KEYS:
        available = [
            {
                "report": entry["report"],
                "value": entry["metrics"][metric],
            }
            for entry in entries
            if (
                entry["actual_metrics_available"]
                and entry["metrics"][metric] is not None
            )
        ]

        available.sort(
            key=lambda item: item["value"],
            reverse=True,
        )

        metric_comparisons[metric] = {
            "status": (
                "COMPARABLE"
                if len(available) >= 2
                else "INSUFFICIENT_DATA"
            ),
            "ranked_results": available,
        }

    capability_comparisons = {}

    for capability in CAPABILITY_KEYS:
        capability_comparisons[capability] = {
            entry["report"]: entry["capabilities"][capability]
            for entry in entries
        }

    valid_experiments = [
        entry
        for entry in entries
        if entry["actual_metrics_available"]
    ]

    winner = None

    if len(valid_experiments) >= 2:
        winner = {
            "status": "NOT SELECTED",
            "reason": (
                "Metrics require a predefined evaluation policy, "
                "matched test conditions, and independent verification. "
                "A single highest metric is insufficient to select "
                "a model winner."
            ),
        }
    elif len(valid_experiments) == 1:
        winner = {
            "status": "INSUFFICIENT COMPARISON",
            "reason": (
                "Only one report contains actual inference metrics."
            ),
        }
    else:
        winner = {
            "status": "NOT RUN",
            "reason": (
                "No report contains verified actual inference metrics."
            ),
        }

    return {
        "experiment_count": len(entries),
        "inference_verified_count": len(valid_experiments),
        "metric_comparisons": metric_comparisons,
        "capability_comparisons": capability_comparisons,
        "winner": winner,
    }


def build_result(
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    comparison = compare_entries(entries)

    return {
        "schema_version": "1.0",
        "project": "ZYRQUEN",
        "experiment": "Native Model v10",
        "created_at": utc_now(),
        "overall_status": (
            "COMPARISON_AVAILABLE"
            if comparison["inference_verified_count"] >= 2
            else "INSUFFICIENT_EVIDENCE"
        ),
        "experiments": entries,
        "comparison": comparison,
        "safety": {
            "training_started": False,
            "checkpoints_modified": False,
            "model_promoted": False,
            "missing_metrics_fabricated": False,
            "not_run_treated_as_zero": False,
        },
        "limitations": [
            "Only evaluation reports are compared.",
            "This tool does not verify model weights.",
            "This tool does not establish matched experimental conditions.",
            "No model winner is automatically promoted.",
            "Capability claims require actual inference evidence.",
        ],
    }


def write_result(
    result: dict[str, Any],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_dir.is_symlink():
        raise ComparisonError(
            "Output directory cannot be a symlink."
        )

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S_%fZ"
    )

    output_path = output_dir / (
        f"v10_comparison_{timestamp}.json"
    )

    if output_path.exists():
        raise ComparisonError(
            "Refusing to overwrite existing comparison."
        )

    payload = json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    fd, temporary_name = tempfile.mkstemp(
        prefix=".v10_comparison_",
        suffix=".tmp",
        dir=output_dir,
    )

    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        if output_path.exists():
            raise ComparisonError(
                "Output appeared during write; refusing overwrite."
            )

        os.replace(temporary_path, output_path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare ZYRQUEN v10 evaluation reports."
    )

    parser.add_argument(
        "--eval-dir",
        type=Path,
        default=DEFAULT_EVAL_DIR,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )

    parser.add_argument(
        "--reports",
        nargs="*",
        type=Path,
        help="Explicit evaluation report paths.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.reports:
            report_paths = [
                path.expanduser().resolve()
                for path in args.reports
            ]
        else:
            report_paths = discover_reports(
                args.eval_dir.expanduser().resolve()
            )

        if len(report_paths) < 2:
            raise ComparisonError(
                "At least two evaluation reports are required "
                "for experiment comparison."
            )

        entries = []

        for path in report_paths:
            report = load_report(path)
            entries.append(
                build_entry(path, report)
            )

        result = build_result(entries)

        output_path = write_result(
            result,
            args.output_dir.expanduser().resolve(),
        )

    except (ComparisonError, OSError) as exc:
        print(f"COMPARISON_FAILED: {exc}")
        return 1

    print(f"Report: {output_path}")
    print(f"Experiments: {len(entries)}")
    print(
        "Inference verified: "
        f"{result['comparison']['inference_verified_count']}"
    )
    print(f"Status: {result['overall_status']}")
    print(
        "Winner: "
        f"{result['comparison']['winner']['status']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
