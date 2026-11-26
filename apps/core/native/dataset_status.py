"""Read-only Dataset Pipeline Status & Integrity Inspector (pure stdlib).

Connects dataset.py and dataset_v11.py verification logic to API status endpoints
without fabricating dataset readiness or returning raw document payloads.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from apps.core.native.dataset import (
    SCHEMA,
    V11_SPLITS,
    _sha256_file,
    clean_text,
    detect_dataset_format,
    redact_pii,
    resolve_dataset_splits,
    verify_dataset_manifest,
)
from apps.core.dataset_leakage_detector import (
    DatasetLeakageDetector,
    SemanticHashLeakageError,
)
from apps.core.native.dataset_v11 import DataAdapter, DatasetLeakageError
from apps.core.workflow import ApprovalViolationError, create_default_orchestrator

_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DISALLOWED_PROVENANCE_TOKENS = (
    "fake",
    "mock",
    "fabricated",
    "synthetic_llm",
    "external_llm",
    "gpt",
    "openai",
    "claude",
    "gemini",
)


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
    semantic_summary: dict[str, Any] = {"status": "NOT RUN"}
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
            splits_data = adapter.load_all_splits()
            sem_report = DatasetLeakageDetector().check_entries(
                splits_data,
                check_internal_splits=True,
                raise_on_leakage=False,
            )
            semantic_summary = sem_report.to_dict()
        except (OSError, ValueError, SemanticHashLeakageError) as exc:
            leakage_summary = {"status": "FAIL", "passed": False, "error": str(exc)}
            semantic_summary = {"status": "FAIL", "passed": False, "error": str(exc)}

    leakage_failed = (
        leakage_summary.get("status") == "FAIL"
        or semantic_summary.get("status") == "FAIL"
    )
    approval_gate = manifest.get("approval_gate") if isinstance(manifest.get("approval_gate"), dict) else None
    approval_gate_verified = bool(
        approval_gate
        and approval_gate.get("verified") is True
        and str(approval_gate.get("approval_id") or "").strip()
    )
    manifest_status = str(manifest.get("status") or "").strip().lower()
    if leakage_failed:
        resolved_status = "leakage_failed"
    elif manifest_status == "pending_approval":
        resolved_status = "pending_approval"
    elif manifest_status == "ready" and approval_gate_verified:
        resolved_status = "ready"
    else:
        resolved_status = "verified"

    return {
        "exists": True,
        "verified": True,
        "status": resolved_status,
        "training_ready": bool(not leakage_failed and (approval_gate_verified or manifest_status == "")),
        "approval_gate_verified": approval_gate_verified,
        "approval_gate": approval_gate,
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
        "semantic_leakage_check": semantic_summary,
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
    any_ready = any(bool(d.get("verified")) and bool(d.get("training_ready", True)) for d in datasets)
    any_pending = any(d.get("status") == "pending_approval" for d in datasets)
    any_leakage_failed = any(d.get("status") == "leakage_failed" for d in datasets)
    four_split_compliant = bool(
        active_record
        and active_record.get("verified")
        and active_record.get("four_split_compliant")
    ) if active_record is not None else any(
        bool(d.get("verified")) and bool(d.get("four_split_compliant")) for d in datasets
    )
    if any_ready:
        status_label = "ready"
        detail_msg = "Dataset manifest and SHA-256 integrity verified."
    elif any_leakage_failed:
        status_label = "leakage_failed"
        detail_msg = "Dataset failed leakage verification."
    elif any_pending:
        status_label = "pending_approval"
        detail_msg = "Dataset is verified but awaiting Approval Gate before ready status."
    elif any_verified:
        status_label = "verified"
        detail_msg = "Dataset manifest verified."
    elif datasets:
        status_label = "invalid"
        detail_msg = "Configured dataset path has no valid verified manifest."
    else:
        status_label = "not_configured"
        detail_msg = "Configured dataset path has no valid verified manifest."
    return {
        "configured": True,
        "status": status_label,
        "four_split_compliant": four_split_compliant,
        "detail": detail_msg,
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
            "dataset_version": None,
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
            "dataset_version": None,
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
    dataset_version: str | None = None
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
        dataset_version = str(manifest.get("version") or "").strip() or None
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
        "dataset_version": dataset_version,
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


def _validate_provenance_and_license(source_name: str, license_str: str, provenance: str) -> tuple[str, str, str]:
    clean_source = str(source_name or "").strip()
    clean_license = str(license_str or "").strip()
    clean_provenance = str(provenance or "").strip()
    if not clean_source:
        raise ValueError("source_name is required for dataset provenance.")
    if not clean_license:
        raise ValueError("license is required for dataset provenance.")
    if not clean_provenance:
        raise ValueError("provenance is required for dataset origin traceability.")
    combined = f"{clean_source} {clean_license} {clean_provenance}".lower()
    for tok in _DISALLOWED_PROVENANCE_TOKENS:
        if tok in combined:
            raise ValueError(f"Disallowed synthetic or external model provenance token: {tok!r}")
    return clean_source, clean_license, clean_provenance


def verify_dataset_approval_ticket(
    workflow_engine: Any,
    approval_id: str | None,
    *,
    dataset_version: str | None = None,
) -> dict[str, Any]:
    """Verify an Approval Gate ticket from apps/core/workflow/ before dataset ingestion."""
    ticket_id = str(approval_id or "").strip()
    if not ticket_id:
        raise ApprovalViolationError(
            "Tier-2 workflow Approval Gate ticket (approval_id) is required before marking a dataset as 'ready'."
        )
    if workflow_engine is None or not hasattr(workflow_engine, "governance"):
        raise ApprovalViolationError("Workflow Approval Gate registry is unavailable.")

    expected_scope = f"dataset:{dataset_version}" if dataset_version else None
    return workflow_engine.governance.verify_approval_readonly(
        ticket_id,
        expected_action_type="dataset.ingest",
        expected_scope=expected_scope,
    )


def ingest_v11_dataset(
    *,
    dataset_version: str,
    splits: dict[str, list[dict[str, Any]]],
    source_name: str,
    license_str: str,
    provenance: str,
    dataset_root: str | Path | None = None,
    do_redact_pii: bool = True,
    approval_id: str | None = None,
    workflow_engine: Any | None = None,
    require_approval: bool = True,
) -> dict[str, Any]:
    """Ingest, clean, hash, and leakage-verify a 4-split V11 dataset atomically with Approval Gate verification."""
    clean_version = validate_dataset_version(dataset_version)
    ticket_id = str(approval_id or "").strip()
    owns_engine = False
    engine = workflow_engine

    if require_approval:
        if not ticket_id:
            raise ApprovalViolationError(
                "Tier-2 workflow Approval Gate ticket (approval_id) is required before marking a dataset as 'ready'."
            )
        if engine is None:
            engine = create_default_orchestrator()
            owns_engine = True
        verify_dataset_approval_ticket(engine, ticket_id, dataset_version=clean_version)

    try:
        clean_source, clean_license, clean_provenance = _validate_provenance_and_license(
            source_name, license_str, provenance
        )

        root_val = str(dataset_root if dataset_root is not None else os.getenv("ZYRQUEN_DATASET_ROOT", "")).strip()
        if not root_val:
            raise RuntimeError("ZYRQUEN_DATASET_ROOT is not configured.")
        raw_root = Path(root_val)
        if raw_root.is_symlink() or not raw_root.is_dir():
            raise RuntimeError("ZYRQUEN_DATASET_ROOT directory is missing or invalid.")
        resolved_root = raw_root.resolve()

        target_dir = (resolved_root / clean_version).resolve()
        if target_dir == resolved_root or not target_dir.is_relative_to(resolved_root):
            raise ValueError("Dataset version resolves outside configured dataset root.")
        if target_dir.exists() or target_dir.is_symlink():
            raise FileExistsError(f"Dataset version {clean_version!r} already exists; overwrite is forbidden.")

        if not isinstance(splits, dict):
            raise ValueError("splits payload must be an object mapping train/validation/unseen/ood.")
        missing_splits = [sp for sp in V11_SPLITS if sp not in splits]
        if missing_splits:
            raise ValueError(f"V11 dataset requires 4 splits {list(V11_SPLITS)}; missing {missing_splits}.")

        seen_norms: set[str] = set()
        cleaned_splits: dict[str, list[dict[str, Any]]] = {sp: [] for sp in V11_SPLITS}
        detected_mode: str | None = None

        for sp in V11_SPLITS:
            rows = splits.get(sp)
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Split {sp!r} must be a non-empty list of records.")
            for idx, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError(f"Split {sp!r} row {idx} must be a JSON object.")
                if "input" in row and "target" in row:
                    mode = "sft"
                    inp = clean_text(str(row["input"]))
                    tgt = clean_text(str(row["target"]))
                    if do_redact_pii:
                        inp = redact_pii(inp)
                        tgt = redact_pii(tgt)
                    if not inp or not tgt:
                        continue
                    norm_key = re.sub(r"\s+", " ", inp).casefold()
                    out_row: dict[str, Any] = {"input": inp, "target": tgt, "split": sp, "source": clean_source}
                elif "text" in row:
                    mode = "text"
                    txt = clean_text(str(row["text"]))
                    if do_redact_pii:
                        txt = redact_pii(txt)
                    if not txt:
                        continue
                    norm_key = re.sub(r"\s+", " ", txt).casefold()
                    out_row = {"text": txt, "split": sp, "source": clean_source}
                else:
                    raise ValueError(f"Split {sp!r} row {idx} must contain ('input','target') or 'text'.")

                if detected_mode is None:
                    detected_mode = mode
                elif detected_mode != mode:
                    raise ValueError("Mixed SFT and text record schemas within the same dataset are not allowed.")

                if norm_key in seen_norms:
                    continue
                seen_norms.add(norm_key)
                cleaned_splits[sp].append(out_row)

            if not cleaned_splits[sp]:
                raise ValueError(f"Split {sp!r} has no unique non-empty records after cleaning/deduplication.")

        staging_dir = Path(tempfile.mkdtemp(prefix=f".ingest_{clean_version}_", dir=str(resolved_root)))
        try:
            files_meta: dict[str, dict[str, Any]] = {}
            split_hashes: list[str] = []
            for sp in V11_SPLITS:
                sp_file = staging_dir / f"{sp}.jsonl"
                with sp_file.open("w", encoding="utf-8") as fh:
                    for item in cleaned_splits[sp]:
                        fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                sha = _sha256_file(sp_file)
                files_meta[f"{sp}.jsonl"] = {"documents": len(cleaned_splits[sp]), "sha256": sha}
                split_hashes.append(sha)

            content_sha = hashlib.sha256("".join(split_hashes).encode("utf-8")).hexdigest()
            manifest_path = staging_dir / "manifest.json"
            manifest: dict[str, Any] = {
                "schema": SCHEMA,
                "dataset": "nagi_v11",
                "version": clean_version,
                "status": "pending_approval",
                "content_sha256": content_sha,
                "provenance": clean_provenance,
                "sources": {
                    clean_source: {
                        "license": clean_license,
                        "provenance": clean_provenance,
                        "sha256": content_sha,
                    }
                },
                "files": files_meta,
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            adapter = DataAdapter(staging_dir, verify_on_init=True)
            leak_report = adapter.detect_leakage(raise_on_leakage=False)
            if not leak_report.passed:
                raise DatasetLeakageError(
                    f"V11 leakage gate failed; dataset rejected: {', '.join(leak_report.violations)}"
                )

            existing_dirs = [
                p
                for p in resolved_root.iterdir()
                if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and p != staging_dir
            ]
            semantic_detector = DatasetLeakageDetector()
            semantic_report = semantic_detector.check_entries(
                cleaned_splits,
                reference_dirs=existing_dirs,
                allowed_root=resolved_root,
                check_internal_splits=True,
                raise_on_leakage=False,
            )
            if not semantic_report.passed:
                raise DatasetLeakageError(
                    f"Semantic hash leakage gate failed; dataset rejected: {', '.join(semantic_report.violations)}"
                )

            if require_approval and engine is not None:
                consumed = engine.governance.verify_and_consume_by_id(
                    ticket_id,
                    expected_action_type="dataset.ingest",
                    expected_scope=f"dataset:{clean_version}",
                )
                manifest["status"] = "ready"
                manifest["approval_gate"] = {
                    "approval_id": consumed["id"],
                    "run_id": consumed["run_id"],
                    "action_type": consumed["action_type"],
                    "scope": consumed["scope"],
                    "approved_by_user_id": consumed.get("approved_by_user_id"),
                    "consumed_at": consumed.get("consumed_at"),
                    "verified": True,
                }
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            staging_dir.rename(target_dir)
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        return inspect_dataset_directory(target_dir, allowed_root=resolved_root, check_v11_leakage=True)
    finally:
        if owns_engine and engine is not None:
            engine.shutdown(wait=True)
