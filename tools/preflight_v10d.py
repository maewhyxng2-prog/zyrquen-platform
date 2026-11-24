#!/usr/bin/env python3
"""Read-only V10-D runtime readiness preflight. Never trains or mutates artifacts."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from apps.core.native.config import ZyrquenConfig
from apps.core.native.tokenizer import SCHEMA_V2, ZyrquenTokenizer
from apps.core.workflow.autonomous_training_loop import validate_budget
from apps.core.workflow.resource_guard import (
    MIN_DISK_RESERVE_GB,
    RAM_HARD_LIMIT_GB,
    check_disk_reserve,
    check_torch_cpu_runtime,
    read_process_rss_bytes,
)
from audit_leakage_v10 import run_audit
from eval_nagi_v10 import verify_dataset


SCHEMA = "zyrquen.v10d.readiness_preflight.v1"


def _check(name: str, ok: bool, detail: Any, *, blocking: bool = True) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if ok else ("BLOCKED" if blocking else "WARNING"),
            "blocking": bool(blocking and not ok), "detail": detail}


def run_preflight(
    *,
    dataset_dir: Path,
    tokenizer_path: Path,
    checkpoint_dir: Path,
    registry_root: Path,
    workflow_db: Path | None = None,
    require_shared_governance: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    torch_info = check_torch_cpu_runtime()
    checks.append(_check("pytorch_cpu", bool(torch_info.get("available")) and not bool(torch_info.get("cuda_available")),
                         torch_info))
    rss_gb = read_process_rss_bytes() / (1024 ** 3)
    checks.append(_check("current_process_rss", rss_gb < RAM_HARD_LIMIT_GB,
                         {"rss_gb": round(rss_gb, 4), "hard_limit_gb": RAM_HARD_LIMIT_GB}))
    disk_ok, disk_info = check_disk_reserve(dataset_dir, MIN_DISK_RESERVE_GB)
    checks.append(_check("disk_reserve", disk_ok, disk_info))

    budget_ok, budget_reason = validate_budget(
        params=ZyrquenConfig().estimated_num_parameters,
        seq_len=256, batch_size=4, steps=50, cpu_threads=2,
    )
    checks.append(_check("cpu_training_budget", budget_ok,
                         {"params": ZyrquenConfig().estimated_num_parameters, "sequence_length": 256,
                          "batch_size": 4, "steps": 50, "cpu_threads": 2, "reason": budget_reason}))

    try:
        dataset_report = verify_dataset(dataset_dir)
        checks.append(_check("dataset_integrity", dataset_report.get("dataset_integrity") == "PASS",
                             {"manifest_sha256": dataset_report.get("manifest_sha256"),
                              "content_sha256": dataset_report.get("content_sha256"),
                              "splits": dataset_report.get("splits")}))
    except Exception as exc:
        checks.append(_check("dataset_integrity", False, {"error": str(exc)}))
        dataset_report = None

    try:
        leakage = run_audit(dataset_dir)
        checks.append(_check("dataset_leakage", leakage.get("status") == "PASS",
                             {"status": leakage.get("status"), "total_examples": leakage.get("total_examples"),
                              "split_counts": leakage.get("split_counts"),
                              "unseen_abstract_operator_generalization":
                                  leakage.get("unseen_abstract_operator_generalization")}))
    except Exception as exc:
        checks.append(_check("dataset_leakage", False, {"error": str(exc)}))
        leakage = None

    tokenizer_info: dict[str, Any] = {"path": str(tokenizer_path), "exists": tokenizer_path.is_file()}
    tokenizer_ok = False
    if tokenizer_path.is_file() and not tokenizer_path.is_symlink():
        try:
            tok = ZyrquenTokenizer.load(tokenizer_path)
            tokenizer_ok = tok.schema == SCHEMA_V2 and tok.supports_atomic_slots and tok.vocab_size <= 5000
            tokenizer_info.update({"schema": tok.schema, "vocab_size": tok.vocab_size,
                                   "fingerprint": tok.fingerprint(), "atomic_slots": tok.supports_atomic_slots})
        except Exception as exc:
            tokenizer_info["error"] = str(exc)
    checks.append(_check("tokenizer_integrity", tokenizer_ok, tokenizer_info))

    # Read-only artifact inventory. Missing outputs are expected before training and remain blockers.
    checkpoint_manifest = checkpoint_dir / "version_manifest.json"
    checks.append(_check("checkpoint_inventory", checkpoint_manifest.is_file(),
                         {"directory_exists": checkpoint_dir.is_dir(),
                          "version_manifest_exists": checkpoint_manifest.is_file()}))
    registry_file = registry_root / "registry.json"
    checks.append(_check("registry_inventory", registry_file.is_file(),
                         {"directory_exists": registry_root.is_dir(), "registry_file_exists": registry_file.is_file()}))

    if require_shared_governance:
        env_db = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
        env_secret = os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip()
        configured_db = Path(env_db).expanduser() if env_db else workflow_db
        checks.append(_check("shared_workflow_store",
                             bool(configured_db and configured_db.is_file()),
                             {"configured": bool(configured_db), "exists": bool(configured_db and configured_db.is_file())}))
        checks.append(_check("shared_approval_secret", len(env_secret) >= 32,
                             {"configured": bool(env_secret), "length_at_least_32": len(env_secret) >= 32}))
    else:
        checks.append(_check("shared_governance", True, "Not required by explicit caller", blocking=False))

    blockers = [item["name"] for item in checks if item["blocking"]]
    return {
        "schema": SCHEMA,
        "overall_status": "READY_FOR_AUTHORIZED_TRAINING_REVIEW" if not blockers else "BLOCKED",
        "read_only": True,
        "training_invoked": False,
        "checkpoint_written": False,
        "registry_modified": False,
        "blockers": blockers,
        "checks": checks,
        "dataset_summary": {
            "integrity": (dataset_report or {}).get("dataset_integrity", "NOT VERIFIED"),
            "leakage": (leakage or {}).get("status", "NOT VERIFIED"),
        },
        "authorization_note": "Readiness is not approval. This command cannot issue Tier-2 approval or start training.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ZYRQUEN V10-D runtime readiness preflight.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "data" / "nagi_v10")
    parser.add_argument("--tokenizer-path", type=Path, default=ROOT / "artifacts" / "v10d_closure" / "tokenizer" / "tokenizer.json")
    parser.add_argument("--checkpoint-dir", type=Path, default=ROOT / "artifacts" / "v10d_closure" / "checkpoints" / "nagi_v10")
    parser.add_argument("--registry-root", type=Path, default=ROOT / "artifacts" / "v10d_closure" / "registry")
    parser.add_argument("--workflow-db", type=Path, default=None)
    parser.add_argument("--skip-shared-governance-check", action="store_true")
    args = parser.parse_args()
    result = run_preflight(dataset_dir=args.dataset_dir, tokenizer_path=args.tokenizer_path,
                           checkpoint_dir=args.checkpoint_dir, registry_root=args.registry_root,
                           workflow_db=args.workflow_db,
                           require_shared_governance=not args.skip_shared_governance_check)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["overall_status"] == "READY_FOR_AUTHORIZED_TRAINING_REVIEW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
