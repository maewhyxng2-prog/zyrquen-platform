#!/usr/bin/env python3
"""Read-only V11 dataset/tokenizer preflight.

This script validates local inputs and required environment configuration only.
It never imports a training loop, initializes a model, installs packages, writes
checkpoints, mutates the registry, or starts training.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

REQUIRED_ENV = (
    "ZYRQUEN_DATASET_DIR",
    "ZYRQUEN_TOKENIZER_PATH",
    "ZYRQUEN_TRAINING_ROOT",
)


class PreflightError(RuntimeError):
    """Raised when a required V11 preflight check fails."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_environment() -> dict[str, str]:
    missing = [
        name for name in REQUIRED_ENV
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise PreflightError(
            "Missing required environment variables: " + ", ".join(missing)
        )
    return {name: os.environ[name].strip() for name in REQUIRED_ENV}


def _existing_local_path(value: str, label: str, *, directory: bool) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise PreflightError(f"{label} must not be a symbolic link: {candidate}")
    if not candidate.exists():
        raise PreflightError(f"{label} does not exist: {candidate}")
    if directory and not candidate.is_dir():
        raise PreflightError(f"{label} is not a directory: {candidate}")
    if not directory and not candidate.is_file():
        raise PreflightError(f"{label} is not a regular file: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_absolute():
        raise PreflightError(f"{label} must resolve to an absolute local path")
    return resolved


def run_preflight() -> dict[str, Any]:
    env = _required_environment()

    dataset_dir = _existing_local_path(
        env["ZYRQUEN_DATASET_DIR"], "ZYRQUEN_DATASET_DIR", directory=True
    )
    tokenizer_path = _existing_local_path(
        env["ZYRQUEN_TOKENIZER_PATH"], "ZYRQUEN_TOKENIZER_PATH", directory=False
    )
    training_root = _existing_local_path(
        env["ZYRQUEN_TRAINING_ROOT"], "ZYRQUEN_TRAINING_ROOT", directory=True
    )

    # The tokenizer must belong to this local dataset handoff, not an external
    # model/tokenizer directory or a path supplied by a remote service.
    if not tokenizer_path.is_relative_to(dataset_dir):
        raise PreflightError(
            "ZYRQUEN_TOKENIZER_PATH must be inside ZYRQUEN_DATASET_DIR"
        )
    if not os.access(training_root, os.W_OK | os.X_OK):
        raise PreflightError(
            f"ZYRQUEN_TRAINING_ROOT is not writable/searchable: {training_root}"
        )

    from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA
    from apps.core.native.dataset import V11_SPLITS, verify_dataset_manifest
    from apps.core.native.tokenizer import SCHEMA_V2, ZyrquenTokenizer
    from audit_leakage_v11 import run_audit

    manifest = verify_dataset_manifest(dataset_dir, require_schema=True)
    if manifest.get("schema") != DATASET_SCHEMA:
        raise PreflightError("Unexpected dataset manifest schema")
    if manifest.get("dataset") != "nagi_v11":
        raise PreflightError("Dataset manifest dataset field must be 'nagi_v11'")

    files = manifest.get("files")
    splits = manifest.get("splits")
    if not isinstance(files, dict) or not all(
        f"{split}.jsonl" in files for split in V11_SPLITS
    ):
        raise PreflightError("Manifest must declare all four V11 split files")
    if not isinstance(splits, dict) or not all(
        split in splits for split in V11_SPLITS
    ):
        raise PreflightError("Manifest must declare all four V11 splits")

    tokenizer = ZyrquenTokenizer.load(tokenizer_path)
    if tokenizer.schema != SCHEMA_V2 or not tokenizer.supports_atomic_slots:
        raise PreflightError(
            "V11 tokenizer must use schema v2 with all 32 atomic slot tokens"
        )
    if tokenizer.vocab_size <= 0:
        raise PreflightError("Tokenizer vocabulary is empty")

    audit = run_audit(
        dataset_dir,
        tokenizer_path=tokenizer_path,
        max_seq_len=256,
        require_tokenizer=True,
        strict=True,
    )
    if audit.get("overall_status") != "PASS":
        failed = [
            name for name, result in (audit.get("gates") or {}).items()
            if not result.get("passed", False)
        ]
        raise PreflightError(
            "V11 integrity/leakage audit failed: "
            + (", ".join(failed) if failed else str(audit.get("overall_status")))
        )

    return {
        "schema": "zyrquen.v11.preflight.v1",
        "status": "PASS",
        "training_started": False,
        "dataset": {
            "path": str(dataset_dir),
            "manifest_sha256": _sha256_file(dataset_dir / "manifest.json"),
            "content_sha256": manifest.get("content_sha256"),
            "splits": list(V11_SPLITS),
            "split_counts": audit.get("split_counts", {}),
        },
        "tokenizer": {
            "path": str(tokenizer_path),
            "sha256": _sha256_file(tokenizer_path),
            "schema": tokenizer.schema,
            "vocab_size": tokenizer.vocab_size,
            "atomic_slots": tokenizer.supports_atomic_slots,
        },
        "training_root": str(training_root),
        "leakage_audit": {
            "status": audit.get("overall_status"),
            "gates": {
                name: bool(result.get("passed", False))
                for name, result in (audit.get("gates") or {}).items()
            },
        },
        "required_environment": {name: "present" for name in REQUIRED_ENV},
        "next_action": "Preflight only; training requires a separate explicit approval.",
    }


def main() -> int:
    try:
        report = run_preflight()
    except (OSError, ValueError, PreflightError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "schema": "zyrquen.v11.preflight.v1",
            "status": "BLOCKED",
            "training_started": False,
            "error": str(exc),
        }, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
