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
    files_map = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    splits_map = manifest.get("splits") if isinstance(manifest.get("splits"), dict) else {}
    for sp in splits:
        entry = files_map.get(f"{sp}.jsonl") if isinstance(files_map.get(f"{sp}.jsonl"), dict) else splits_map.get(sp)
        entry_dict = entry if isinstance(entry, dict) else {}
        split_summary[sp] = {
            "documents": entry_dict.get("documents", entry_dict.get("count")),
            "sha256": entry_dict.get("sha256"),
        }

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
    if check_v11_leakage and tuple(splits) == V11_SPLITS:
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
        "split_counts": split_summary,
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
    status_label = "ready" if any_verified else ("invalid" if datasets else "not_configured")
    return {
        "configured": True,
        "status": status_label,
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
