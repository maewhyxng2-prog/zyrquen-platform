"""Read-only Dataset Pipeline Status & Integrity Inspector (pure stdlib).

Connects dataset.py and dataset_v11.py verification logic to API status endpoints
without fabricating dataset readiness or returning raw document payloads.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from apps.core.native.dataset import (
    V11_SPLITS,
    detect_dataset_format,
    resolve_dataset_splits,
    verify_dataset_manifest,
)
from apps.core.native.dataset_v11 import DataAdapter

_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_dataset_version(version: str) -> str:
    cleaned = str(version or "").strip()
    if not _VERSION_RE.match(cleaned) or ".." in cleaned:
        raise ValueError(f"Invalid dataset version identifier: {version!r}")
    return cleaned


def inspect_dataset_directory(
    dataset_dir: str | Path,
    *,
    allowed_root: str | Path | None = None,
    check_v11_leakage: bool = True,
) -> dict[str, Any]:
    """Verify a dataset directory's manifest, split hashes, format, and optional V11 leakage."""
    raw_dir = Path(dataset_dir)
    if raw_dir.is_symlink():
        raise ValueError("Dataset directory must not be a symlink.")
    resolved_dir = raw_dir.resolve()
    if allowed_root is not None:
        root_resolved = Path(allowed_root).resolve()
        if resolved_dir != root_resolved and not resolved_dir.is_relative_to(root_resolved):
            raise ValueError("Dataset directory escapes configured dataset root.")
    if not resolved_dir.is_dir():
        return {
            "exists": False,
            "verified": False,
            "status": "missing",
            "path": str(resolved_dir),
            "error": "Dataset directory does not exist.",
        }

    try:
        manifest = verify_dataset_manifest(resolved_dir)
        splits = resolve_dataset_splits(manifest)
        fmt = detect_dataset_format(resolved_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "exists": True,
            "verified": False,
            "status": "invalid",
            "path": str(resolved_dir),
            "error": str(exc),
        }

    split_summary: dict[str, Any] = {}
    doc_counts: dict[str, int] = {}
    files_map = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    splits_map = manifest.get("splits") if isinstance(manifest.get("splits"), dict) else {}
    for sp in splits:
        entry = files_map.get(f"{sp}.jsonl") if isinstance(files_map.get(f"{sp}.jsonl"), dict) else splits_map.get(sp)
        entry_dict = entry if isinstance(entry, dict) else {}
        raw_docs = entry_dict.get("documents", entry_dict.get("count"))
        if isinstance(raw_docs, int) and not isinstance(raw_docs, bool):
            doc_count = raw_docs
        else:
            rel_name = str(entry_dict.get("path") or f"{sp}.jsonl")
            sp_path = (resolved_dir / rel_name).resolve()
            if sp_path.is_file() and sp_path.is_relative_to(resolved_dir):
                doc_count = sum(1 for ln in sp_path.read_text(encoding="utf-8").splitlines() if ln.strip())
            else:
                doc_count = 0
        doc_counts[sp] = doc_count
        split_summary[sp] = {
            "documents": doc_count,
            "sha256": entry_dict.get("sha256"),
        }

    total_documents = sum(doc_counts.values())
    split_distribution: dict[str, Any] = {}
    for sp in V11_SPLITS:
        count = doc_counts.get(sp, 0)
        split_distribution[sp] = {
            "present": sp in doc_counts,
            "documents": count,
            "ratio": round(count / total_documents, 6) if total_documents > 0 and sp in doc_counts else 0.0,
        }
    for sp, count in doc_counts.items():
        if sp not in split_distribution:
            split_distribution[sp] = {
                "present": True,
                "documents": count,
                "ratio": round(count / total_documents, 6) if total_documents > 0 else 0.0,
            }

    four_split_compliant = tuple(splits) == V11_SPLITS
    missing_four_splits = [sp for sp in V11_SPLITS if sp not in doc_counts]

    sources = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else {}
    licensed_sources = [
        {
            "name": name,
            "license": info.get("license") if isinstance(info, dict) else None,
            "sha256": info.get("sha256") if isinstance(info, dict) else None,
        }
        for name, info in sources.items()
    ]

    leakage_summary: dict[str, Any] = {"status": "NOT RUN"}
    if check_v11_leakage and four_split_compliant:
        try:
            adapter = DataAdapter(resolved_dir, verify_on_init=False)
            adapter.manifest = manifest
            leak_report = adapter.detect_leakage(raise_on_leakage=False)
            leakage_summary = {
                "status": "PASS" if leak_report.passed else "FAIL",
                "passed": leak_report.passed,
                "violations": leak_report.violations,
            }
        except (OSError, ValueError) as exc:
            leakage_summary = {"status": "FAIL", "passed": False, "error": str(exc)}

    return {
        "exists": True,
        "verified": True,
        "status": "verified" if leakage_summary.get("status") != "FAIL" else "leakage_failed",
        "version": manifest.get("version"),
        "schema": manifest.get("schema"),
        "format": fmt,
        "content_sha256": manifest.get("content_sha256"),
        "splits": list(splits),
        "total_documents": total_documents,
        "split_counts": split_summary,
        "required_four_splits": list(V11_SPLITS),
        "four_split_compliant": four_split_compliant,
        "missing_four_splits": missing_four_splits,
        "split_distribution": split_distribution,
        "licensed_sources_count": len(licensed_sources),
        "licensed_sources": licensed_sources,
        "v11_leakage_check": leakage_summary,
    }


def get_datasets_pipeline_status(
    *,
    dataset_dir: str | Path | None = None,
    dataset_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return read-only Dataset Pipeline status across configured dataset_dir / dataset_root."""
    dir_val = str(dataset_dir if dataset_dir is not None else os.getenv("ZYRQUEN_DATASET_DIR", "")).strip()
    root_val = str(dataset_root if dataset_root is not None else os.getenv("ZYRQUEN_DATASET_ROOT", "")).strip()

    if not dir_val and not root_val:
        return {
            "configured": False,
            "status": "not_configured",
            "detail": "ZYRQUEN_DATASET_DIR and ZYRQUEN_DATASET_ROOT are not configured.",
            "active_dataset": None,
            "datasets": [],
        }

    active_record: dict[str, Any] | None = None
    datasets: list[dict[str, Any]] = []
    seen_versions: set[str] = set()

    if dir_val:
        active_record = inspect_dataset_directory(dir_val)
        ver = active_record.get("version")
        if isinstance(ver, str) and ver:
            seen_versions.add(ver)
        datasets.append(active_record)

    if root_val:
        root_path = Path(root_val)
        if not root_path.is_symlink() and root_path.is_dir():
            resolved_root = root_path.resolve()
            for child in sorted(resolved_root.iterdir()):
                if child.is_symlink() or not child.is_dir():
                    continue
                if not _VERSION_RE.match(child.name):
                    continue
                info = inspect_dataset_directory(child, allowed_root=resolved_root)
                ver = str(info.get("version") or child.name)
                if ver not in seen_versions:
                    seen_versions.add(ver)
                    datasets.append(info)

    any_verified = any(bool(d.get("verified")) for d in datasets)
    four_split_compliant = bool(
        active_record
        and active_record.get("verified")
        and active_record.get("four_split_compliant")
    ) if active_record is not None else any(
        bool(d.get("verified")) and bool(d.get("four_split_compliant")) for d in datasets
    )
    status_label = "ready" if any_verified else ("invalid" if datasets else "not_configured")
    return {
        "configured": True,
        "status": status_label,
        "four_split_compliant": four_split_compliant,
        "detail": (
            "Dataset manifest and SHA-256 integrity verified."
            if any_verified
            else "Configured dataset path has no valid verified manifest."
        ),
        "active_dataset": active_record,
        "datasets": datasets,
    }


def get_dataset_version_status(
    dataset_version: str,
    *,
    dataset_dir: str | Path | None = None,
    dataset_root: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect a specific dataset version securely without path traversal."""
    clean_version = validate_dataset_version(dataset_version)
    snapshot = get_datasets_pipeline_status(dataset_dir=dataset_dir, dataset_root=dataset_root)
    if not snapshot["configured"]:
        raise RuntimeError("Dataset pipeline paths are not configured.")

    root_val = str(dataset_root if dataset_root is not None else os.getenv("ZYRQUEN_DATASET_ROOT", "")).strip()
    if root_val:
        root_path = Path(root_val).resolve()
        candidate = (root_path / clean_version).resolve()
        if not candidate.is_relative_to(root_path):
            raise ValueError("Invalid dataset version path.")
        if candidate.is_dir():
            return inspect_dataset_directory(candidate, allowed_root=root_path)

    for item in snapshot["datasets"]:
        if item.get("version") == clean_version:
            return item

    raise LookupError(f"Dataset version not found: {clean_version}")


def inspect_v11_training_dataset_readiness(dataset_dir: str | Path | None) -> dict[str, Any]:
    """Enforce V11 4-split requirement and DataAdapter leakage detection for /training/readiness."""
    from apps.core.native.dataset_v11 import DatasetLeakageError

    reasons: list[str] = []
    if dataset_dir is None:
        reasons.append("ZYRQUEN_DATASET_DIR is not configured or missing.")
        return {
            "configured": False,
            "verified": False,
            "format": None,
            "four_split_enforced": True,
            "required_splits": list(V11_SPLITS),
            "splits": [],
            "four_split_present": False,
            "split_counts": {},
            "leakage_check": {"status": "NOT RUN", "passed": False, "violations": []},
            "reasons": reasons,
        }

    raw_dir = Path(dataset_dir)
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        reasons.append("ZYRQUEN_DATASET_DIR is not configured or missing.")
        return {
            "configured": False,
            "verified": False,
            "format": None,
            "four_split_enforced": True,
            "required_splits": list(V11_SPLITS),
            "splits": [],
            "four_split_present": False,
            "split_counts": {},
            "leakage_check": {"status": "NOT RUN", "passed": False, "violations": []},
            "reasons": reasons,
        }

    resolved_dir = raw_dir.resolve()
    verified = False
    four_split_present = False
    dataset_splits: list[str] = []
    dataset_format: str | None = None
    split_counts: dict[str, int] = {}
    leakage_report_dict: dict[str, Any] = {
        "status": "NOT RUN",
        "passed": False,
        "violations": [],
    }

    try:
        manifest = verify_dataset_manifest(resolved_dir)
        splits = resolve_dataset_splits(manifest)
        dataset_splits = list(splits)
        dataset_format = detect_dataset_format(resolved_dir)
        four_split_present = tuple(splits) == V11_SPLITS
        if not four_split_present:
            reasons.append(
                f"Dataset does not satisfy V11 4-split requirement {list(V11_SPLITS)}; found {dataset_splits}."
            )
        else:
            adapter = DataAdapter(resolved_dir, verify_on_init=True)
            leak_report = adapter.detect_leakage(raise_on_leakage=False)
            leakage_report_dict = leak_report.to_dict()
            split_counts = dict(leak_report.split_counts)
            if leak_report.passed:
                verified = True
            else:
                reasons.append(
                    f"V11 leakage detection failed: {', '.join(leak_report.violations)}."
                )
    except (DatasetLeakageError, OSError, ValueError, KeyError, TypeError) as exc:
        reasons.append(f"V11 dataset verification failed: {exc}")

    return {
        "configured": True,
        "verified": verified,
        "format": dataset_format,
        "four_split_enforced": True,
        "required_splits": list(V11_SPLITS),
        "splits": dataset_splits,
        "four_split_present": four_split_present,
        "split_counts": split_counts,
        "leakage_check": leakage_report_dict,
        "reasons": reasons,
    }


def inspect_training_preflight_readiness(
    *,
    dataset_dir: str | Path | None,
    tokenizer_path: str | Path | None,
    training_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run read-only TrainingOrchestrator.prepare() preflight checks without starting a worker or training."""
    from apps.core.native.tokenizer import ZyrquenTokenizer
    from apps.core.training.orchestrator import (
        MAX_CPU_BATCH_SIZE,
        MAX_CPU_MODEL_PARAMETERS,
        MAX_CPU_SEQUENCE_LENGTH,
        TrainingOrchestrator,
        TrainingUnavailable,
    )

    root_resolved = (
        Path(training_root).resolve()
        if training_root is not None
        else Path(os.getenv("ZYRQUEN_TRAINING_ROOT", "/data/training")).resolve()
    )

    tokenizer_configured = False
    tokenizer_valid = False
    tokenizer_detail = "ZYRQUEN_TOKENIZER_PATH is not configured or missing."
    vocab_size: int | None = None

    if tokenizer_path is not None:
        raw_tok = Path(tokenizer_path)
        if not raw_tok.is_symlink() and raw_tok.is_file():
            tokenizer_configured = True
            try:
                tok = ZyrquenTokenizer.load(raw_tok.resolve())
                tokenizer_valid = True
                vocab_size = int(tok.vocab_size)
                tokenizer_detail = f"Validated native tokenizer ({tok.schema}, vocab={vocab_size})."
            except (OSError, ValueError, KeyError, TypeError) as exc:
                tokenizer_detail = f"Tokenizer validation failed: {exc}"

    storage_writable = False
    try:
        probe = root_resolved
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        storage_writable = probe.is_dir() and not probe.is_symlink() and os.access(probe, os.W_OK | os.X_OK)
    except OSError:
        storage_writable = False

    preflight_passed = False
    preflight_detail = "Training preflight did not run because dataset or tokenizer is unavailable."
    resource_limits_checked = False
    reasons: list[str] = []

    if not tokenizer_valid:
        reasons.append(tokenizer_detail)
    if not storage_writable:
        reasons.append("ZYRQUEN_TRAINING_ROOT directory is not writable or unavailable.")

    if dataset_dir is not None and tokenizer_valid:
        raw_ds = Path(dataset_dir)
        if not raw_ds.is_symlink() and raw_ds.is_dir():
            resolved_ds = raw_ds.resolve()
            resolved_tok = Path(tokenizer_path).resolve() if tokenizer_path is not None else None
            try:
                manifest = verify_dataset_manifest(resolved_ds)
                version = str(manifest.get("version") or "").strip()
                orchestrator = TrainingOrchestrator(
                    dataset_dir=resolved_ds,
                    tokenizer_path=resolved_tok,
                    training_root=root_resolved,
                )
                prepared = orchestrator.prepare(
                    dataset_version=version,
                    training_values={
                        "block_size": 128,
                        "batch_size": 1,
                        "grad_accum_steps": 1,
                        "max_steps": 100,
                        "eval_batches": 4,
                        "warmup_steps": 10,
                    },
                    model_values={
                        "max_seq_len": 256,
                        "n_layers": 4,
                        "n_heads": 4,
                        "d_model": 256,
                        "d_ff": 704,
                    },
                )
                resource_limits_checked = True
                preflight_passed = True
                preflight_detail = (
                    f"Read-only orchestrator preflight passed for dataset={prepared.dataset_version} "
                    f"(cpu_max_params={MAX_CPU_MODEL_PARAMETERS:,})."
                )
            except (TrainingUnavailable, OSError, ValueError, KeyError, TypeError) as exc:
                preflight_detail = f"Training preflight rejected: {exc}"
                if str(exc) not in reasons:
                    reasons.append(preflight_detail)

    return {
        "passed": preflight_passed,
        "detail": preflight_detail,
        "tokenizer_configured": tokenizer_configured,
        "tokenizer_valid": tokenizer_valid,
        "tokenizer_detail": tokenizer_detail,
        "vocab_size": vocab_size,
        "storage_writable": storage_writable,
        "resource_limits_checked": resource_limits_checked,
        "max_cpu_parameters": MAX_CPU_MODEL_PARAMETERS,
        "max_cpu_seq_len": MAX_CPU_SEQUENCE_LENGTH,
        "max_cpu_batch_size": MAX_CPU_BATCH_SIZE,
        "reasons": reasons,
    }
