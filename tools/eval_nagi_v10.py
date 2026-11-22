#!/usr/bin/env python3
"""
ZYRQUEN Native Model v10 — Evaluation Controller

Responsibilities:
- Validate the v10 dataset manifest.
- Verify declared split files using SHA-256.
- Validate JSONL records and split availability.
- Produce an immutable evaluation report.
- Explicitly report NOT RUN when native inference is unavailable.

This file does NOT:
- Train or modify model weights.
- Modify v9, v8, or v7 artifacts.
- Invent model capability scores.
- Promote or register a model.
- Claim generalization without actual inference results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v10"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

MANIFEST_CANDIDATES = (
    "manifest.json",
    "dataset_manifest.json",
)

REQUIRED_SPLITS = {
    "train",
    "val",
    "test",
}


class EvaluationError(RuntimeError):
    """Raised when dataset evaluation prerequisites are invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def safe_resolve_file(root: Path, relative_path: str) -> Path:
    """
    Resolve a manifest-declared file without allowing:
    - Path traversal outside the dataset directory.
    - Symlink-based path escapes.
    - Absolute paths.
    """

    relative = Path(relative_path)

    if relative.is_absolute():
        raise EvaluationError(
            f"Absolute manifest path is forbidden: {relative_path}"
        )

    root_resolved = root.resolve(strict=True)
    candidate = root / relative

    if candidate.is_symlink():
        raise EvaluationError(
            f"Symlink dataset file is forbidden: {relative_path}"
        )

    resolved = candidate.resolve(strict=True)

    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise EvaluationError(
            f"Dataset path escapes dataset directory: {relative_path}"
        ) from exc

    if not resolved.is_file():
        raise EvaluationError(
            f"Manifest entry is not a file: {relative_path}"
        )

    return resolved


def load_manifest(dataset_dir: Path) -> tuple[Path, dict[str, Any]]:
    if not dataset_dir.exists():
        raise EvaluationError(
            f"Dataset directory does not exist: {dataset_dir}"
        )

    if dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise EvaluationError(
            "Dataset directory must be a real directory, not a symlink."
        )

    manifest_path = None

    for filename in MANIFEST_CANDIDATES:
        candidate = dataset_dir / filename

        if candidate.exists():
            manifest_path = candidate
            break

    if manifest_path is None:
        raise EvaluationError(
            "Dataset manifest not found. Expected one of: "
            + ", ".join(MANIFEST_CANDIDATES)
        )

    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvaluationError("Manifest must be a regular file.")

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(
            f"Cannot read dataset manifest: {exc}"
        ) from exc

    if not isinstance(manifest, dict):
        raise EvaluationError("Manifest root must be a JSON object.")

    return manifest_path, manifest


def discover_split_entries(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Discover split declarations from common manifest layouts.

    Supported examples:

    {
      "splits": {
        "train": {
          "file": "train.jsonl",
          "sha256": "..."
        }
      }
    }

    or:

    {
      "files": {
        "train.jsonl": {
          "sha256": "..."
        }
      }
    }

    Only manifest-declared files are accepted.
    """

    found: dict[str, dict[str, Any]] = {}

    def classify(name: str) -> str | None:
        normalized = name.lower().replace("-", "_")

        if normalized in ("train", "training"):
            return "train"

        if normalized in (
            "val",
            "valid",
            "validation",
            "dev",
        ):
            return "val"

        if normalized in ("test", "testing"):
            return "test"

        stem = Path(normalized).stem

        if stem in ("train", "training"):
            return "train"

        if stem in ("val", "valid", "validation", "dev"):
            return "val"

        if stem in ("test", "testing"):
            return "test"

        return None

    def walk(node: Any, parent_key: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                split = classify(str(key))

                if split and isinstance(value, dict):
                    path_value = (
                        value.get("file")
                        or value.get("path")
                        or value.get("filename")
                    )

                    expected_hash = (
                        value.get("sha256")
                        or value.get("hash")
                    )

                    if path_value and expected_hash:
                        if split in found:
                            raise EvaluationError(
                                f"Duplicate manifest declaration: {split}"
                            )

                        found[split] = {
                            "path": str(path_value),
                            "sha256": str(expected_hash),
                            "count": value.get("count"),
                        }

                elif isinstance(value, dict):
                    path_value = (
                        value.get("file")
                        or value.get("path")
                        or value.get("filename")
                    )

                    expected_hash = (
                        value.get("sha256")
                        or value.get("hash")
                    )

                    split_from_path = (
                        classify(str(path_value))
                        if path_value
                        else None
                    )

                    if (
                        split_from_path
                        and expected_hash
                    ):
                        if split_from_path in found:
                            raise EvaluationError(
                                "Duplicate split declaration: "
                                + split_from_path
                            )

                        found[split_from_path] = {
                            "path": str(path_value),
                            "sha256": str(expected_hash),
                            "count": value.get("count"),
                        }

                    walk(value, str(key))

                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            path_value = (
                                item.get("file")
                                or item.get("path")
                                or item.get("filename")
                            )

                            expected_hash = (
                                item.get("sha256")
                                or item.get("hash")
                            )

                            split = (
                                classify(str(path_value))
                                if path_value
                                else None
                            )

                            if split and expected_hash:
                                if split in found:
                                    raise EvaluationError(
                                        "Duplicate split declaration: "
                                        + split
                                    )

                                found[split] = {
                                    "path": str(path_value),
                                    "sha256": str(expected_hash),
                                    "count": item.get("count"),
                                }

        elif isinstance(node, list):
            for item in node:
                walk(item, parent_key)

    walk(manifest)

    return found


def validate_jsonl(
    path: Path,
    expected_count: Any = None,
) -> dict[str, Any]:
    records = 0
    invalid_lines = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue

            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                invalid_lines.append(line_number)
                continue

            if not isinstance(record, dict):
                invalid_lines.append(line_number)
                continue

            records += 1

    if invalid_lines:
        raise EvaluationError(
            f"Invalid JSONL records in {path.name}: "
            f"lines {invalid_lines[:10]}"
        )

    if records == 0:
        raise EvaluationError(
            f"Dataset split is empty: {path.name}"
        )

    if expected_count is not None:
        try:
            expected = int(expected_count)
        except (TypeError, ValueError) as exc:
            raise EvaluationError(
                f"Invalid manifest count for {path.name}"
            ) from exc

        if records != expected:
            raise EvaluationError(
                f"Record count mismatch for {path.name}: "
                f"expected={expected}, actual={records}"
            )

    return {
        "records": records,
        "valid_jsonl": True,
    }


def verify_dataset(dataset_dir: Path) -> dict[str, Any]:
    manifest_path, manifest = load_manifest(dataset_dir)

    split_entries = discover_split_entries(manifest)

    missing = REQUIRED_SPLITS - set(split_entries)

    if missing:
        raise EvaluationError(
            "Manifest does not declare required splits: "
            + ", ".join(sorted(missing))
        )

    results: dict[str, Any] = {}

    for split_name in sorted(REQUIRED_SPLITS):
        entry = split_entries[split_name]

        relative_path = entry["path"]
        expected_hash = entry["sha256"].lower()

        if len(expected_hash) != 64:
            raise EvaluationError(
                f"Invalid SHA-256 declaration for {split_name}"
            )

        file_path = safe_resolve_file(
            dataset_dir,
            relative_path,
        )

        actual_hash = sha256_file(file_path)

        if actual_hash != expected_hash:
            raise EvaluationError(
                f"SHA-256 mismatch for {split_name}: "
                f"{relative_path}"
            )

        jsonl_result = validate_jsonl(
            file_path,
            entry.get("count"),
        )

        results[split_name] = {
            "file": relative_path,
            "sha256": actual_hash,
            **jsonl_result,
            "integrity": "PASS",
        }

    return {
        "manifest": str(manifest_path.relative_to(dataset_dir)),
        "dataset_integrity": "PASS",
        "splits": results,
    }


def build_not_run_report(
    dataset_dir: Path,
    dataset_result: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    No inference hook is implemented in this controller.

    Therefore capability metrics must remain NOT RUN.
    Dataset integrity is reported independently.
    """

    integrity_status = (
        dataset_result["dataset_integrity"]
        if dataset_result
        else "FAIL"
    )

    return {
        "schema_version": "1.0",
        "project": "ZYRQUEN",
        "experiment": "Native Model v10",
        "created_at": utc_now(),
        "dataset_dir": str(dataset_dir),
        "overall_status": (
            "NOT RUN"
            if integrity_status == "PASS"
            else "FAILED"
        ),
        "dataset_integrity": integrity_status,
        "inference_status": "NOT RUN",
        "capability_evaluation": {
            "abstract_reasoning": "NOT RUN",
            "relational_generalization": "NOT RUN",
            "ood_transfer": "NOT RUN",
            "multi_step_planning": "NOT RUN",
            "self_verification": "NOT RUN",
            "knowledge_integration": "NOT RUN",
        },
        "metrics": None,
        "checkpoint": None,
        "dataset": dataset_result,
        "error": error,
        "limitations": [
            "Native inference hook is not implemented.",
            "No model predictions were generated.",
            "No capability scores were fabricated.",
            "No model promotion or registry operation occurred.",
            "Dataset integrity PASS does not prove model generalization.",
        ],
    }


def write_report(
    report: dict[str, Any],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_dir.is_symlink():
        raise EvaluationError(
            "Report output directory cannot be a symlink."
        )

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S_%fZ"
    )

    output_path = output_dir / (
        f"v10_evaluation_{timestamp}.json"
    )

    if output_path.exists():
        raise EvaluationError(
            "Refusing to overwrite an existing report."
        )

    payload = json.dumps(
        report,
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    fd, temporary_name = tempfile.mkstemp(
        prefix=".v10_eval_",
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
            raise EvaluationError(
                "Report appeared during write; refusing overwrite."
            )

        os.replace(temporary_path, output_path)

    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate ZYRQUEN v10 dataset and produce "
            "an honest evaluation readiness report."
        )
    )

    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    dataset_dir = args.dataset_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    dataset_result = None
    error = None

    try:
        dataset_result = verify_dataset(dataset_dir)

    except (EvaluationError, OSError) as exc:
        error = str(exc)

    report = build_not_run_report(
        dataset_dir=dataset_dir,
        dataset_result=dataset_result,
        error=error,
    )

    try:
        report_path = write_report(
            report,
            output_dir,
        )
    except (EvaluationError, OSError) as exc:
        print(
            f"REPORT_WRITE_FAILED: {exc}",
            file=sys.stderr,
        )
        return 2

    print(f"Report: {report_path}")
    print(f"Dataset integrity: {report['dataset_integrity']}")
    print(f"Inference: {report['inference_status']}")
    print(f"Overall: {report['overall_status']}")

    if error:
        print(f"Reason: {error}")

    if report["overall_status"] == "FAILED":
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
