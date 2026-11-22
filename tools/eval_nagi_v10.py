#!/usr/bin/env python3
"""
ZYRQUEN Native Model v10 — Evaluation Controller

Responsibilities:
  - Validate the v10 dataset manifest (zyrquen.dataset-manifest.v1).
  - Verify all canonical splits ("train", "validation", "test") via SHA-256 and content_sha256.
  - Validate JSONL records against the v10 dataset schema.
  - Run independent leakage & unique-answer audit (tools/audit_leakage_v10.py).
  - Optionally verify ModelRegistry artifact integrity (read-only).
  - Produce an immutable evaluation report under eval/nagi_v10/.
  - Explicitly report NOT RUN when native inference is unavailable or unimplemented.

Safety:
  - Does NOT train or modify model weights.
  - Does NOT modify v7, v8, or v9 artifacts.
  - Does NOT fabricate capability scores or metrics.
  - Does NOT promote or mutate ModelRegistry state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from apps.core.native.evaluation import (  # noqa: E402
    EvaluationEngine,
    EvaluationError as NativeEvaluationError,
    EvaluationNotConfiguredError,
)
from apps.core.native.registry import ModelRegistry, RegistryError  # noqa: E402
from audit_leakage_v10 import (  # noqa: E402
    EXPECTED_CAPABILITIES,
    MANIFEST_SCHEMA,
    REQUIRED_RECORD_FIELDS,
    SPLITS as CANONICAL_SPLITS,
    run_audit,
)

DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v10"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

EVAL_REPORT_SCHEMA = "zyrquen.v10.evaluation_report.v1"
MANIFEST_CANDIDATES = ("manifest.json",)
REQUIRED_SPLITS = CANONICAL_SPLITS  # ("train", "validation", "test")

INFERENCE_HOOK_IMPLEMENTED = True


class EvaluationError(RuntimeError):
    """Raised when dataset or checkpoint evaluation prerequisites are invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_resolve_file(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        raise EvaluationError(f"Absolute manifest path is forbidden: {relative_path}")

    root_resolved = root.resolve(strict=True)
    candidate = root / relative
    if candidate.is_symlink():
        raise EvaluationError(f"Symlink dataset file is forbidden: {relative_path}")

    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise EvaluationError(f"Dataset path escapes dataset directory: {relative_path}") from exc

    if not resolved.is_file():
        raise EvaluationError(f"Manifest entry is not a regular file: {relative_path}")
    return resolved


def load_manifest(dataset_dir: Path) -> tuple[Path, dict[str, Any]]:
    if not dataset_dir.exists():
        raise EvaluationError(f"Dataset directory does not exist: {dataset_dir}")
    if dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise EvaluationError("Dataset directory must be a real non-symlink directory.")

    manifest_path = None
    for filename in MANIFEST_CANDIDATES:
        candidate = dataset_dir / filename
        if candidate.exists():
            manifest_path = candidate
            break

    if manifest_path is None:
        raise EvaluationError("Dataset manifest.json not found.")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvaluationError("Manifest must be a regular non-symlink file.")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"Cannot read dataset manifest: {exc}") from exc

    if not isinstance(manifest, dict):
        raise EvaluationError("Manifest root must be a JSON object.")
    if manifest.get("dataset") != "nagi_v10":
        raise EvaluationError(f"Unexpected dataset id in manifest: {manifest.get('dataset')!r}")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise EvaluationError(f"Unsupported manifest schema: {manifest.get('schema')!r}")

    return manifest_path, manifest


def discover_split_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract canonical split entries (train, validation, test) from manifest."""
    found: dict[str, dict[str, Any]] = {}
    splits_section = manifest.get("splits")
    files_section = manifest.get("files")

    for split in REQUIRED_SPLITS:
        entry = None
        if isinstance(splits_section, dict) and isinstance(splits_section.get(split), dict):
            entry = splits_section[split]
        elif isinstance(files_section, dict) and isinstance(files_section.get(f"{split}.jsonl"), dict):
            entry = files_section[f"{split}.jsonl"]

        if not isinstance(entry, dict):
            continue

        rel_path = entry.get("path") or entry.get("file") or entry.get("filename")
        expected_hash = entry.get("sha256") or entry.get("hash")
        expected_count = entry.get("example_count", entry.get("count", entry.get("documents")))

        if not rel_path or not expected_hash:
            raise EvaluationError(f"Incomplete manifest declaration for split '{split}'")

        found[split] = {
            "path": str(rel_path),
            "sha256": str(expected_hash).lower(),
            "count": expected_count,
        }

    return found


def validate_jsonl(path: Path, split_name: str, expected_count: Any = None) -> dict[str, Any]:
    records = 0
    invalid_lines: list[int] = []
    schema_errors: list[int] = []
    cap_counts: Counter[str] = Counter()

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
            if not REQUIRED_RECORD_FIELDS.issubset(record.keys()) or record.get("split") != split_name:
                schema_errors.append(line_number)
                continue
            cap_counts[str(record.get("capability"))] += 1
            records += 1

    if invalid_lines:
        raise EvaluationError(f"Invalid JSONL records in {path.name}: lines {invalid_lines[:10]}")
    if schema_errors:
        raise EvaluationError(f"Schema validation failed in {path.name}: lines {schema_errors[:10]}")
    if records == 0:
        raise EvaluationError(f"Dataset split is empty: {path.name}")

    if expected_count is not None:
        try:
            expected = int(expected_count)
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"Invalid manifest count for {path.name}") from exc
        if records != expected:
            raise EvaluationError(f"Record count mismatch for {path.name}: expected={expected}, actual={records}")

    return {
        "records": records,
        "valid_jsonl": True,
        "capabilities": dict(sorted(cap_counts.items())),
    }


def verify_dataset(dataset_dir: Path) -> dict[str, Any]:
    manifest_path, manifest = load_manifest(dataset_dir)
    split_entries = discover_split_entries(manifest)

    missing = set(REQUIRED_SPLITS) - set(split_entries)
    if missing:
        raise EvaluationError("Manifest missing required splits: " + ", ".join(sorted(missing)))

    results: dict[str, Any] = {}
    for split_name in REQUIRED_SPLITS:
        entry = split_entries[split_name]
        relative_path = entry["path"]
        expected_hash = entry["sha256"]
        if len(expected_hash) != 64:
            raise EvaluationError(f"Invalid SHA-256 declaration for {split_name}")

        file_path = safe_resolve_file(dataset_dir, relative_path)
        actual_hash = sha256_file(file_path)
        if actual_hash != expected_hash:
            raise EvaluationError(f"SHA-256 mismatch for {split_name}: {relative_path}")

        jsonl_result = validate_jsonl(file_path, split_name, entry.get("count"))
        results[split_name] = {
            "file": relative_path,
            "sha256": actual_hash,
            **jsonl_result,
            "integrity": "PASS",
        }

    combined_sha = hashlib.sha256(
        "".join(results[s]["sha256"] for s in REQUIRED_SPLITS).encode("utf-8")
    ).hexdigest()
    if manifest.get("content_sha256") != combined_sha:
        raise EvaluationError("Dataset content_sha256 does not match split SHA-256 hashes")

    return {
        "manifest": str(manifest_path.relative_to(dataset_dir)),
        "manifest_sha256": sha256_file(manifest_path),
        "content_sha256": combined_sha,
        "dataset_version": manifest.get("version"),
        "dataset_integrity": "PASS",
        "splits": results,
    }


def verify_registry_model(registry_root: Path | None, model_version: str | None) -> dict[str, Any] | None:
    if not registry_root or not model_version:
        return None
    if not registry_root.is_dir():
        raise EvaluationError(f"ModelRegistry root does not exist: {registry_root}")
    reg = ModelRegistry(registry_root)
    try:
        verified = reg.verify(model_version)
        rec = reg.get(model_version)
    except RegistryError as exc:
        raise EvaluationError(f"Registry verification failed for {model_version}: {exc}") from exc
    if not verified:
        raise EvaluationError(f"Artifact SHA-256 check failed for {model_version}")
    return {
        "model_version": model_version,
        "lifecycle_status": rec.get("lifecycle_status"),
        "checkpoint_sha256": (rec.get("checkpoint") or {}).get("sha256"),
        "active_baseline_version": reg.active_version(),
        "verified": True,
    }


def build_regression_comparison(
    registry_root: Path | None,
    model_version: str | None,
    inference_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not registry_root or not model_version or not inference_result:
        return []
    reg = ModelRegistry(registry_root)
    baseline_version = reg.active_version()
    if not baseline_version or baseline_version == model_version:
        return []

    base_rec = reg.get(baseline_version)
    cand_rec = reg.get(model_version)
    comparison = reg.compare_versions(baseline_version, model_version)

    # Also check newly evaluated inference metrics & capabilities against active baseline
    base_metrics = dict(base_rec.get("metrics") or {})
    cand_metrics = dict(cand_rec.get("metrics") or {})
    if isinstance(inference_result.get("metrics"), dict):
        for k, v in inference_result["metrics"].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cand_metrics[str(k)] = float(v)

    base_caps = dict(base_rec.get("capabilities") or {})
    cand_caps = dict(cand_rec.get("capabilities") or {})
    raw_cap_eval = inference_result.get("capability_evaluation")
    if isinstance(raw_cap_eval, dict):
        for cap, info in raw_cap_eval.items():
            if isinstance(info, dict):
                val = info.get("score", info.get("exact_match", info.get("accuracy")))
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    cand_caps[str(cap)] = float(val)

    def _check_regressions(b_map: dict[str, Any], c_map: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        deltas: dict[str, Any] = {}
        regressed: list[str] = []
        for k in sorted(set(b_map) & set(c_map)):
            bv, cv = b_map[k], c_map[k]
            if (
                isinstance(bv, (int, float))
                and not isinstance(bv, bool)
                and isinstance(cv, (int, float))
                and not isinstance(cv, bool)
            ):
                d = round(float(cv) - float(bv), 6)
                deltas[k] = {"base": float(bv), "candidate": float(cv), "delta": d}
                if k.endswith("loss"):
                    if d > 0.01:
                        regressed.append(k)
                elif d < -0.01:
                    regressed.append(k)
        return deltas, regressed

    m_deltas, m_reg = _check_regressions(base_metrics, cand_metrics)
    c_deltas, c_reg = _check_regressions(base_caps, cand_caps)
    comparison["metric_deltas"] = {**comparison.get("metric_deltas", {}), **m_deltas}
    comparison["capability_deltas"] = {**comparison.get("capability_deltas", {}), **c_deltas}
    comparison["regressed_metrics"] = sorted(set(comparison.get("regressed_metrics", [])) | set(m_reg))
    comparison["regressed_capabilities"] = sorted(set(comparison.get("regressed_capabilities", [])) | set(c_reg))
    comparison["zero_regression"] = (
        len(comparison["regressed_metrics"]) == 0 and len(comparison["regressed_capabilities"]) == 0
    )
    return [comparison]


def build_evaluation_report(
    *,
    dataset_dir: Path,
    experiment_id: str,
    dataset_result: dict[str, Any] | None,
    leakage_audit_status: str,
    leakage_audit_detail: dict[str, Any] | None,
    checkpoint_info: dict[str, Any] | None,
    inference_result: dict[str, Any] | None = None,
    inference_status: str = "NOT RUN",
    regression_comparison: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    integrity_status = dataset_result["dataset_integrity"] if dataset_result else "FAIL"
    dataset_and_audit_ok = integrity_status == "PASS" and leakage_audit_status in ("PASS", "NOT RUN")
    reg_cmp = list(regression_comparison) if regression_comparison is not None else []
    zero_reg = all(isinstance(item, dict) and item.get("zero_regression") is True for item in reg_cmp)
    stop_criteria_triggered: list[str] = []

    if error is not None and inference_status == "BLOCKED":
        overall_status = "BLOCKED"
        capability_eval = {cap: "NOT RUN" for cap in EXPECTED_CAPABILITIES}
        metrics = None
        stop_criteria_triggered.append(f"blocked:{error}")
    elif error is not None or not dataset_and_audit_ok:
        overall_status = "FAILED"
        capability_eval = {cap: "NOT RUN" for cap in EXPECTED_CAPABILITIES}
        metrics = None
        stop_criteria_triggered.append(f"failed:{error or 'dataset_or_audit_invalid'}")
    elif inference_result is not None and inference_status == "PASS":
        raw_caps = dict(inference_result.get("capability_evaluation") or {})
        capability_eval = {}
        for cap in EXPECTED_CAPABILITIES:
            if cap in raw_caps:
                entry = raw_caps[cap]
                if isinstance(entry, dict):
                    norm_entry = dict(entry)
                    if "exact_match" not in norm_entry and "accuracy" in norm_entry:
                        norm_entry["exact_match"] = norm_entry["accuracy"]
                    capability_eval[cap] = norm_entry
                else:
                    capability_eval[cap] = entry
            else:
                capability_eval[cap] = "NOT RUN"
        metrics = inference_result.get("metrics")
        all_caps_passed = all(
            isinstance(capability_eval[cap], dict) and capability_eval[cap].get("status") == "PASS"
            for cap in EXPECTED_CAPABILITIES
        )
        if leakage_audit_status != "PASS":
            stop_criteria_triggered.append("leakage_audit_not_passed")
        if not all_caps_passed:
            stop_criteria_triggered.append("capability_threshold_failed")
        if not zero_reg:
            stop_criteria_triggered.append("regression_detected")
        overall_status = (
            "PASS"
            if (leakage_audit_status == "PASS" and all_caps_passed and zero_reg)
            else "FAIL"
        )
    else:
        overall_status = "NOT RUN"
        capability_eval = {cap: "NOT RUN" for cap in EXPECTED_CAPABILITIES}
        metrics = None

    all_caps_criterion_status = (
        "PASS"
        if (
            inference_status == "PASS"
            and all(
                isinstance(capability_eval[cap], dict) and capability_eval[cap].get("status") == "PASS"
                for cap in EXPECTED_CAPABILITIES
            )
        )
        else ("NOT RUN" if inference_status == "NOT RUN" else ("BLOCKED" if inference_status == "BLOCKED" else "FAIL"))
    )
    acceptance_assessment = {
        "criteria": {
            "dataset_integrity": {"status": integrity_status},
            "leakage_audit": {"status": leakage_audit_status},
            "native_inference": {"status": inference_status},
            "all_capabilities_evaluated": {"status": all_caps_criterion_status},
            "zero_regression": {"status": "PASS" if zero_reg else "FAIL"},
        },
        "stop_criteria_triggered": stop_criteria_triggered,
    }

    limitations = [
        "No model promotion or registry mutation occurred.",
        "Dataset integrity PASS does not prove model generalization.",
    ]
    if inference_status != "PASS":
        limitations.insert(
            0,
            "Native v10 inference hook is wired via EvaluationEngine.evaluate_native_model, but inference was not executed in this run.",
        )
        limitations.insert(1, "No capability scores were fabricated.")

    return {
        "schema_version": "1.0",
        "report_schema": EVAL_REPORT_SCHEMA,
        "project": "ZYRQUEN Ω∞",
        "experiment": "Native Model v10",
        "experiment_id": experiment_id,
        "created_at": utc_now(),
        "dataset_dir": str(dataset_dir),
        "dataset_manifest_sha256": dataset_result.get("manifest_sha256") if dataset_result else None,
        "dataset_content_sha256": dataset_result.get("content_sha256") if dataset_result else None,
        "tokenizer_sha256": inference_result.get("tokenizer_sha256") if inference_result else None,
        "overall_status": overall_status,
        "dataset_integrity": integrity_status,
        "leakage_audit_status": leakage_audit_status,
        "leakage_audit": leakage_audit_detail,
        "inference_status": inference_status,
        "inference_hook_implemented": INFERENCE_HOOK_IMPLEMENTED,
        "capability_evaluation": capability_eval,
        "metrics": metrics,
        "regression_comparison": reg_cmp,
        "acceptance_assessment": acceptance_assessment,
        "checkpoint": checkpoint_info,
        "dataset": dataset_result,
        "error": error,
        "limitations": limitations,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise EvaluationError("Report output directory cannot be a symlink.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = output_dir / f"v10_evaluation_{timestamp}.json"
    if output_path.exists():
        raise EvaluationError("Refusing to overwrite an existing report.")

    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=".v10_eval_", suffix=".tmp", dir=output_dir)
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if output_path.exists():
            raise EvaluationError("Report appeared during write; refusing overwrite.")
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ZYRQUEN v10 dataset/audit integrity and optionally run native inference evaluation."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--experiment-id", type=str, default="v10-baseline-prep")
    parser.add_argument("--registry-root", type=Path, default=None)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--tokenizer-path", type=Path, default=None)
    parser.add_argument("--model-version", type=str, default=None)
    parser.add_argument("--run-inference", action="store_true")
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--skip-leakage-audit", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = args.dataset_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    registry_root = args.registry_root.expanduser().resolve() if args.registry_root else None
    checkpoint_dir = args.checkpoint_dir.expanduser().resolve() if args.checkpoint_dir else None
    tokenizer_path = args.tokenizer_path.expanduser().resolve() if args.tokenizer_path else None

    dataset_result: dict[str, Any] | None = None
    leakage_audit_status = "NOT RUN"
    leakage_audit_detail: dict[str, Any] | None = None
    checkpoint_info: dict[str, Any] | None = None
    inference_result: dict[str, Any] | None = None
    inference_status = "NOT RUN"
    regression_comparison: list[dict[str, Any]] = []
    error: str | None = None

    try:
        dataset_result = verify_dataset(dataset_dir)
        if not args.skip_leakage_audit:
            audit_res = run_audit(dataset_dir)
            leakage_audit_status = str(audit_res.get("status", "FAIL"))
            leakage_audit_detail = {
                "status": leakage_audit_status,
                "total_examples": audit_res.get("total_examples"),
                "split_counts": audit_res.get("split_counts"),
                "gates_passed": {
                    k: bool(v.get("passed")) for k, v in (audit_res.get("gates") or {}).items()
                },
            }
            if leakage_audit_status != "PASS":
                raise EvaluationError("Leakage and unique-answer audit failed.")
        checkpoint_info = verify_registry_model(registry_root, args.model_version)

        if args.run_inference:
            if not checkpoint_dir or not args.model_version:
                inference_status = "BLOCKED"
                raise EvaluationNotConfiguredError(
                    "--run-inference requires --checkpoint-dir and --model-version"
                )
            engine = EvaluationEngine(checkpoint_dir=checkpoint_dir)
            try:
                inference_result = engine.evaluate_native_model(
                    args.model_version,
                    dataset_dir=dataset_dir,
                    tokenizer_path=tokenizer_path,
                    max_examples=args.max_examples,
                    max_new_tokens=args.max_new_tokens,
                )
                inference_status = str(inference_result.get("inference_status") or "PASS")
                regression_comparison = build_regression_comparison(
                    registry_root,
                    args.model_version,
                    inference_result,
                )
            except EvaluationNotConfiguredError:
                inference_status = "BLOCKED"
                raise
            except NativeEvaluationError as exc:
                inference_status = "FAIL"
                raise EvaluationError(str(exc)) from exc
    except EvaluationNotConfiguredError as exc:
        inference_status = "BLOCKED"
        error = str(exc)
    except (EvaluationError, OSError, ValueError) as exc:
        error = str(exc)

    report = build_evaluation_report(
        dataset_dir=dataset_dir,
        experiment_id=args.experiment_id,
        dataset_result=dataset_result,
        leakage_audit_status=leakage_audit_status,
        leakage_audit_detail=leakage_audit_detail,
        checkpoint_info=checkpoint_info,
        inference_result=inference_result,
        inference_status=inference_status,
        regression_comparison=regression_comparison,
        error=error,
    )

    if not args.no_write_report:
        try:
            report_path = write_report(report, output_dir)
            print(f"Report: {report_path}")
        except (EvaluationError, OSError) as exc:
            print(f"REPORT_WRITE_FAILED: {exc}", file=sys.stderr)
            return 2

    print(f"Dataset integrity: {report['dataset_integrity']}")
    print(f"Leakage audit: {report['leakage_audit_status']}")
    print(f"Inference: {report['inference_status']}")
    print(f"Overall: {report['overall_status']}")
    if error:
        print(f"Reason: {error}")

    if report["overall_status"] == "BLOCKED":
        return 3
    return 1 if report["overall_status"] in ("FAILED", "FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
