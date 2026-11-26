#!/usr/bin/env python3
"""
ZYRQUEN Native Model v10 — Diagnostic Controller

Read-only diagnostic utility:
  - Reads an existing v10 evaluation report (and optional training preflight report).
  - Verifies dataset split integrity evidence across ("train", "validation", "test").
  - Verifies leakage audit & inference status honestly.
  - Identifies missing capability evidence across all 6 v10 capabilities.
  - Produces an immutable diagnostic report without training, modifying checkpoints,
    or promoting models.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_DIR = PROJECT_ROOT / "eval" / "nagi_v10"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

DIAGNOSTIC_REPORT_SCHEMA = "zyrquen.v10.diagnostic_report.v1"
REQUIRED_SPLITS = ("train", "validation", "test")

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
        raise DiagnosticError(f"Report must be a regular non-symlink file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticError(f"Cannot read JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DiagnosticError("Report root must be a JSON object.")
    return value


def find_latest_report(eval_dir: Path, pattern: str = "v10_evaluation_*.json") -> Path:
    if not eval_dir.exists() or not eval_dir.is_dir():
        raise DiagnosticError(f"Evaluation directory does not exist: {eval_dir}")
    if eval_dir.is_symlink():
        raise DiagnosticError("Evaluation directory cannot be a symlink.")
    reports = sorted(
        (p for p in eval_dir.glob(pattern) if p.is_file() and not p.is_symlink()),
        key=lambda p: (p.stat().st_mtime_ns, p.name),
        reverse=True,
    )
    if not reports:
        raise DiagnosticError(f"No matching report ({pattern}) found in {eval_dir}. Run tools/eval_nagi_v10.py first.")
    return reports[0]


def normalize_status(value: Any) -> str:
    if not isinstance(value, str):
        return "NOT RUN"
    normalized = value.strip().upper()
    if normalized not in VALID_STATUSES:
        return "UNKNOWN"
    return normalized


def diagnose_dataset(report: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(report.get("dataset_integrity"))
    leakage_status = normalize_status(report.get("leakage_audit_status"))
    dataset = report.get("dataset")

    if status == "PASS" and isinstance(dataset, dict):
        splits = dataset.get("splits")
        if not isinstance(splits, dict):
            return {"status": "UNKNOWN", "finding": "Dataset split evidence is missing."}

        missing = set(REQUIRED_SPLITS) - set(splits)
        if missing:
            return {
                "status": "FAIL",
                "finding": "Required split evidence is missing: " + ", ".join(sorted(missing)),
            }

        invalid: list[str] = []
        for split in REQUIRED_SPLITS:
            item = splits.get(split)
            if not isinstance(item, dict):
                invalid.append(split)
                continue
            sha = str(item.get("sha256", ""))
            if (
                item.get("integrity") != "PASS"
                or item.get("valid_jsonl") is not True
                or len(sha) != 64
            ):
                invalid.append(split)

        if invalid:
            return {
                "status": "FAIL",
                "finding": "Split integrity is not verified: " + ", ".join(invalid),
            }

        if leakage_status == "FAIL":
            return {
                "status": "FAIL",
                "finding": "Dataset splits passed format check, but leakage audit FAILED.",
            }

        return {
            "status": "PASS",
            "leakage_audit_status": leakage_status,
            "finding": "All required dataset splits (train, validation, test) have verified SHA-256 and JSONL evidence.",
        }

    return {
        "status": status,
        "leakage_audit_status": leakage_status,
        "finding": (
            "Dataset integrity has not been established."
            if status != "PASS"
            else "Dataset evidence is incomplete."
        ),
    }


def diagnose_inference(report: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(report.get("inference_status"))
    if status == "PASS":
        metrics = report.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            return {
                "status": "FAIL",
                "finding": "Inference status says PASS, but metrics payload is missing.",
            }
        return {
            "status": "PASS",
            "finding": "Evaluation report contains non-empty metrics for inference.",
        }
    if status == "NOT RUN":
        return {
            "status": "NOT RUN",
            "finding": "No actual native model inference has been executed.",
        }
    return {
        "status": status,
        "finding": "Inference has not reached a verified PASS state.",
    }


def diagnose_capabilities(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    source = report.get("capability_evaluation")
    if not isinstance(source, dict):
        source = {}
    results: dict[str, dict[str, str]] = {}
    for capability in CAPABILITIES:
        raw_entry = source.get(capability)
        if isinstance(raw_entry, dict):
            status = normalize_status(raw_entry.get("status"))
        else:
            status = normalize_status(raw_entry)

        if status == "PASS":
            finding = "Capability reported PASS in evaluation report (requires independent audit)."
        elif status in ("NOT RUN", "UNKNOWN"):
            finding = "No verified capability evidence."
        else:
            finding = f"Capability status is {status}; promotion blocked."

        results[capability] = {"status": status, "finding": finding}
    return results


def build_diagnosis(
    report_path: Path,
    evaluation: dict[str, Any],
    *,
    preflight_path: Path | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = diagnose_dataset(evaluation)
    inference = diagnose_inference(evaluation)
    capabilities = diagnose_capabilities(evaluation)

    blockers: list[str] = []
    if dataset["status"] != "PASS":
        blockers.append("Dataset integrity must be verified.")
    if normalize_status(evaluation.get("leakage_audit_status")) != "PASS":
        blockers.append("Leakage and unique-answer audit has not passed.")
    if inference["status"] != "PASS":
        blockers.append("Actual native model inference has not been verified.")

    for capability, result in capabilities.items():
        if result["status"] != "PASS":
            blockers.append(f"Capability evidence missing or unverified: {capability}")

    evaluation_error = evaluation.get("error")
    if evaluation_error:
        blockers.append("Evaluation report contains an error.")

    preflight_diag: dict[str, Any] | None = None
    if preflight is not None:
        pf_blockers = list(preflight.get("blockers") or [])
        preflight_diag = {
            "source_preflight_report": str(preflight_path) if preflight_path else None,
            "status": preflight.get("status"),
            "training_started": bool(preflight.get("training_started", False)),
            "blockers": pf_blockers,
        }
        for b in pf_blockers:
            blockers.append(f"Preflight blocker: {b}")

    return {
        "schema_version": "1.0",
        "report_schema": DIAGNOSTIC_REPORT_SCHEMA,
        "project": "ZYRQUEN Ω∞",
        "experiment": "Native Model v10",
        "created_at": utc_now(),
        "source_evaluation_report": str(report_path),
        "overall_status": "READY_FOR_REVIEW" if not blockers else "NOT READY",
        "diagnostics": {
            "dataset": dataset,
            "inference": inference,
            "capabilities": capabilities,
            "training_preflight": preflight_diag,
        },
        "blockers": blockers,
        "evaluation_error": evaluation_error,
        "training_authorization": (
            ((preflight.get("tier2_approval") or {}).get("status"))
            if preflight is not None
            else "NOT CHECKED"
        ),
        "training_started": False,
        "promotion_authorized": False,
        "limitations": [
            "This utility performs read-only report analysis.",
            "It does not independently execute model inference.",
            "It does not issue or validate HMAC approval tokens.",
            "It does not authorize or start training.",
        ],
    }


def write_report(result: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise DiagnosticError("Output directory cannot be a symlink.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = output_dir / f"v10_diagnostic_{timestamp}.json"
    if output_path.exists():
        raise DiagnosticError("Refusing to overwrite an existing diagnostic.")

    payload = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=".v10_diagnostic_", suffix=".tmp", dir=output_dir)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if output_path.exists():
            raise DiagnosticError("Output appeared during write; refusing overwrite.")
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose ZYRQUEN v10 evaluation & readiness evidence.")
    parser.add_argument("--report", type=Path, default=None, help="Specific v10 evaluation JSON report.")
    parser.add_argument("--preflight-report", type=Path, default=None, help="Optional v10 training preflight JSON report.")
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.report is not None:
            report_path = args.report.expanduser().resolve()
        else:
            report_path = find_latest_report(args.eval_dir.expanduser().resolve())

        evaluation = load_json(report_path)
        if evaluation.get("experiment") != "Native Model v10":
            raise DiagnosticError("Report does not identify Native Model v10.")

        preflight_path: Path | None = None
        preflight: dict[str, Any] | None = None
        if args.preflight_report is not None:
            preflight_path = args.preflight_report.expanduser().resolve()
            preflight = load_json(preflight_path)

        result = build_diagnosis(
            report_path,
            evaluation,
            preflight_path=preflight_path,
            preflight=preflight,
        )

        if not args.no_write_report:
            output_path = write_report(result, args.output_dir.expanduser().resolve())
            print(f"Report: {output_path}")
    except (DiagnosticError, OSError) as exc:
        print(f"DIAGNOSTIC_FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"Status: {result['overall_status']}")
    print(f"Blockers: {len(result['blockers'])}")
    for blocker in result["blockers"]:
        print(f"- {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
