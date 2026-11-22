#!/usr/bin/env python3
"""
ZYRQUEN Native Model v10 — Diagnostic Controller

Read-only diagnostic utility.

- Reads an existing v10 evaluation report.
- Checks dataset integrity and inference status.
- Identifies missing capability evidence.
- Produces an immutable diagnostic report.
- Never trains, modifies checkpoints, or promotes models.
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

CAPABILITIES = (
    "abstract_reasoning",
    "relational_generalization",
    "ood_transfer",
    "multi_step_planning",
    "self_verification",
    "knowledge_integration",
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


class DiagnosticError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticError(
            f"Report must be a regular non-symlink file: {path}"
        )

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticError(
            f"Cannot read evaluation report: {exc}"
        ) from exc

    if not isinstance(value, dict):
        raise DiagnosticError(
            "Evaluation report root must be a JSON object."
        )

    return value


def find_latest_report(eval_dir: Path) -> Path:
    if not eval_dir.exists() or not eval_dir.is_dir():
        raise DiagnosticError(
            f"Evaluation directory does not exist: {eval_dir}"
        )

    if eval_dir.is_symlink():
        raise DiagnosticError(
            "Evaluation directory cannot be a symlink."
        )

    reports = sorted(
        (
            path
            for path in eval_dir.glob("v10_evaluation_*.json")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    if not reports:
        raise DiagnosticError(
            "No v10 evaluation report found. "
            "Run tools/eval_nagi_v10.py first."
        )

    return reports[0]


def normalize_status(value: Any) -> str:
    if not isinstance(value, str):
        return "NOT RUN"

    normalized = value.strip().upper()

    if normalized not in VALID_STATUSES:
        return "UNKNOWN"

    return normalized


def diagnose_dataset(report: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(
        report.get("dataset_integrity")
    )

    dataset = report.get("dataset")

    if status == "PASS" and isinstance(dataset, dict):
        splits = dataset.get("splits")

        if not isinstance(splits, dict):
            return {
                "status": "UNKNOWN",
                "finding": "Dataset split evidence is missing.",
            }

        required = {"train", "val", "test"}
        missing = required - set(splits)

        if missing:
            return {
                "status": "FAIL",
                "finding": (
                    "Required split evidence is missing: "
                    + ", ".join(sorted(missing))
                ),
            }

        invalid = []

        for split in sorted(required):
            item = splits.get(split)

            if not isinstance(item, dict):
                invalid.append(split)
                continue

            if (
                item.get("integrity") != "PASS"
                or item.get("valid_jsonl") is not True
            ):
                invalid.append(split)

        if invalid:
            return {
                "status": "FAIL",
                "finding": (
                    "Split integrity is not verified: "
                    + ", ".join(invalid)
                ),
            }

        return {
            "status": "PASS",
            "finding": "All required dataset splits have integrity evidence.",
        }

    return {
        "status": status,
        "finding": (
            "Dataset integrity has not been established."
            if status != "PASS"
            else "Dataset evidence is incomplete."
        ),
    }


def diagnose_inference(report: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(
        report.get("inference_status")
    )

    if status == "PASS":
        return {
            "status": "UNKNOWN",
            "finding": (
                "Inference status says PASS, but this diagnostic "
                "does not independently verify inference execution."
            ),
        }

    if status == "NOT RUN":
        return {
            "status": "NOT RUN",
            "finding": (
                "No actual model inference has been demonstrated."
            ),
        }

    return {
        "status": status,
        "finding": "Inference has not reached a verified PASS state.",
    }


def diagnose_capabilities(
    report: dict[str, Any],
) -> dict[str, dict[str, str]]:
    source = report.get("capability_evaluation")

    if not isinstance(source, dict):
        source = {}

    results = {}

    for capability in CAPABILITIES:
        status = normalize_status(
            source.get(capability)
        )

        if status == "PASS":
            status = "UNVERIFIED"

        results[capability] = {
            "status": status,
            "finding": (
                "No verified capability evidence."
                if status in ("NOT RUN", "UNKNOWN", "UNVERIFIED")
                else "Capability evaluation requires review."
            ),
        }

    return results


def build_diagnosis(
    report_path: Path,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    dataset = diagnose_dataset(evaluation)
    inference = diagnose_inference(evaluation)
    capabilities = diagnose_capabilities(evaluation)

    blockers = []

    if dataset["status"] != "PASS":
        blockers.append(
            "Dataset integrity must be verified."
        )

    if inference["status"] != "PASS":
        blockers.append(
            "Actual native model inference has not been verified."
        )

    for capability, result in capabilities.items():
        if result["status"] != "PASS":
            blockers.append(
                f"Capability evidence missing or unverified: {capability}"
            )

    evaluation_error = evaluation.get("error")

    if evaluation_error:
        blockers.append(
            "Evaluation report contains an error."
        )

    return {
        "schema_version": "1.0",
        "project": "ZYRQUEN",
        "experiment": "Native Model v10",
        "created_at": utc_now(),
        "source_evaluation_report": str(report_path),
        "overall_status": (
            "READY_FOR_REVIEW"
            if not blockers
            else "NOT READY"
        ),
        "diagnostics": {
            "dataset": dataset,
            "inference": inference,
            "capabilities": capabilities,
        },
        "blockers": blockers,
        "evaluation_error": evaluation_error,
        "training_authorization": "NOT CHECKED",
        "training_started": False,
        "promotion_authorized": False,
        "limitations": [
            "This utility performs read-only report analysis.",
            "It does not independently execute model inference.",
            "It does not validate HMAC approval tokens.",
            "It does not authorize or start training.",
            "A diagnostic result is not proof of NGI capability.",
        ],
    }


def write_report(
    result: dict[str, Any],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_dir.is_symlink():
        raise DiagnosticError(
            "Output directory cannot be a symlink."
        )

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S_%fZ"
    )

    output_path = output_dir / (
        f"v10_diagnostic_{timestamp}.json"
    )

    if output_path.exists():
        raise DiagnosticError(
            "Refusing to overwrite an existing diagnostic."
        )

    payload = json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    fd, temporary_name = tempfile.mkstemp(
        prefix=".v10_diagnostic_",
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
            raise DiagnosticError(
                "Output appeared during write; refusing overwrite."
            )

        os.replace(temporary_path, output_path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose ZYRQUEN v10 evaluation evidence."
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Specific evaluation JSON report.",
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

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.report is not None:
            report_path = args.report.expanduser().resolve()
        else:
            eval_dir = args.eval_dir.expanduser().resolve()
            report_path = find_latest_report(eval_dir)

        evaluation = load_json(report_path)

        if evaluation.get("experiment") != "Native Model v10":
            raise DiagnosticError(
                "Report does not identify Native Model v10."
            )

        result = build_diagnosis(
            report_path,
            evaluation,
        )

        output_path = write_report(
            result,
            args.output_dir.expanduser().resolve(),
        )

    except (DiagnosticError, OSError) as exc:
        print(f"DIAGNOSTIC_FAILED: {exc}")
        return 1

    print(f"Report: {output_path}")
    print(f"Status: {result['overall_status']}")
    print(f"Blockers: {len(result['blockers'])}")

    for blocker in result["blockers"]:
        print(f"- {blocker}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
