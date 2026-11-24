#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — V10-D End-to-End Closure Pipeline Runner

Executes the complete, honest V10-D closure workflow without fabricating results:
  1. Honest PyTorch CPU runtime check (`TORCH_NOT_INSTALLED` -> BLOCKED, exit 3).
  2. Dataset generation (`tools/gen_nagi_v10.py`) & read-only leakage audit
     (`tools/audit_leakage_v10.py` + `tools/eval_nagi_v10.py::verify_dataset`).
  3. Slot-safe BPE tokenizer (`zyrquen.tokenizer.v2`) trained strictly on `train`
     with EL-05 leakage verification against `validation` and `test` entities.
  4. Controlled CPU SFT training (`batch_size <= 4`, `block_size == 256`,
     `steps <= 500`, `cpu_threads <= 2`, `use_paid_gpu = False`) orchestrated
     through `CentralWorkflowOrchestrator` with explicit Tier-2 HMAC admin
     approval and canonical `ModelRegistry` registration (`ZYRQUEN-Native-10.0.0`).
  5. Native inference evaluation (`EvaluationEngine.evaluate_native_model`)
     producing an immutable `zyrquen.v10.evaluation_report.v1` report and
     verifying it through `evaluation.model_verification` (`handle_evaluation_gate`).
  6. Final V10 closure audit (`build_v10_closure_audit`) verifying V11 unlock gate.

Safety:
  - CPU-only (`use_paid_gpu = False`, `cpu_threads <= 2`).
  - Never fabricates PASS, checkpoints, metrics, or Tier-2 HMAC approval.
  - Does not touch frozen `v7`, `v8`, or `v9` baselines or artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from apps.core.native.closure_audit import build_v10_closure_audit  # noqa: E402
from apps.core.native.dataset import load_sft_split  # noqa: E402
from apps.core.native.evaluation import EvaluationEngine  # noqa: E402
from apps.core.native.registry import ModelRegistry  # noqa: E402
from apps.core.native.sft import extract_entities, train_slot_safe_tokenizer  # noqa: E402
from apps.core.native.tokenizer import SCHEMA_V2  # noqa: E402
from apps.core.workflow.autonomous_training_loop import (  # noqa: E402
    DISK_RESERVE_GB,
    validate_budget,
)
from apps.core.workflow.handlers.groups import (  # noqa: E402
    handle_data_verify_and_audit,
    handle_evaluation_gate,
    handle_evaluation_verify,
    handle_training_execute,
)
from apps.core.workflow.models import (  # noqa: E402
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowStepSpec,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator  # noqa: E402
from apps.core.workflow.resource_guard import check_torch_cpu_runtime  # noqa: E402
from audit_leakage_v10 import run_audit as run_v10_leakage_audit  # noqa: E402
from eval_nagi_v10 import (  # noqa: E402
    build_evaluation_report,
    build_regression_comparison,
    verify_dataset as verify_v10_dataset,
    verify_registry_model,
    write_report as write_eval_report,
)
from gen_nagi_v10 import DEFAULT_COUNTS, generate_dataset  # noqa: E402

CLOSURE_RUNNER_SCHEMA = "zyrquen.v10.closure_runner.v1"
CLOSURE_WORKFLOW_KEY = "training.v10d_closure_run"
CLOSURE_WORKFLOW_VERSION = "1.0.0"

DEFAULT_WORKSPACE = PROJECT_ROOT / "artifacts" / "v10d_closure"
MAX_CLOSURE_BATCH_SIZE = 4
REQUIRED_CLOSURE_BLOCK_SIZE = 256
MAX_CLOSURE_STEPS = 500
MAX_CLOSURE_CPU_THREADS = 2


class V10DClosureError(RuntimeError):
    """Raised when V10-D closure prerequisites or validation checks fail."""


@contextmanager
def _open_orchestrator(workflow_db: Path) -> Iterator[CentralWorkflowOrchestrator]:
    workflow_db.parent.mkdir(parents=True, exist_ok=True)
    orch = CentralWorkflowOrchestrator(db_path=workflow_db, work_dir=PROJECT_ROOT)
    try:
        yield orch
    finally:
        orch.shutdown(wait=True)


def _register_v10d_closure_workflow(
    orch: CentralWorkflowOrchestrator,
    *,
    train_fn_override: Callable[..., dict[str, Any]] | None = None,
    model_override: Any | None = None,
    load_fn_override: Callable[[str], Any] | None = None,
) -> None:
    def _audit_step(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
        return handle_data_verify_and_audit(ctx, payload)

    def _train_step(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
        enriched_ctx = dict(ctx)
        if train_fn_override is not None:
            enriched_ctx["_train_fn"] = train_fn_override
        if model_override is not None:
            enriched_ctx["_model"] = model_override
        if load_fn_override is not None:
            enriched_ctx["_load_fn"] = load_fn_override
        return handle_training_execute(enriched_ctx, payload)

    def _eval_verify_step(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
        return handle_evaluation_verify(ctx, payload)

    def _eval_gate_step(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
        return handle_evaluation_gate(ctx, payload)

    orch.registry.register_handler("v10d.data_audit", _audit_step)
    orch.registry.register_handler("v10d.train_execute", _train_step)
    orch.registry.register_handler("v10d.eval_verify", _eval_verify_step)
    orch.registry.register_handler("v10d.eval_gate", _eval_gate_step)

    defn = WorkflowDefinition(
        workflow_key=CLOSURE_WORKFLOW_KEY,
        version=CLOSURE_WORKFLOW_VERSION,
        group_name="training",
        title="ZYRQUEN V10-D End-to-End Closure Training",
        description="Tier-1 v10 leakage audit followed by Tier-2 HMAC-gated CPU SFT training.",
        default_tier="tier2_approval",
        steps=(
            WorkflowStepSpec(
                step_key="v10_data_audit",
                handler_key="v10d.data_audit",
                description="Verify nagi_v10 manifest and run read-only leakage/solver audit.",
                lane="control_ops",
                tier="tier1_auto",
                action_type="read_only",
                min_disk_gb=DISK_RESERVE_GB,
            ),
            WorkflowStepSpec(
                step_key="execute_v10d_training",
                handler_key="v10d.train_execute",
                description="Execute CPU-bounded V10 SFT training with canonical ModelRegistry registration.",
                depends_on=("v10_data_audit",),
                lane="compute_heavy",
                tier="tier2_approval",
                action_type="training.execute",
                max_attempts=1,
                min_disk_gb=DISK_RESERVE_GB,
            ),
        ),
    )
    orch.registry.register_definition(defn)
    orch.store.upsert_definition(
        defn.workflow_key,
        defn.version,
        defn.group_name,
        defn.to_dag_spec(),
        defn.default_tier,
        defn.is_active,
    )


def _validate_closure_bounds(
    *,
    batch_size: int,
    block_size: int,
    training_steps: int,
    cpu_threads: int,
) -> None:
    if batch_size < 1 or batch_size > MAX_CLOSURE_BATCH_SIZE:
        raise V10DClosureError(
            f"batch_size={batch_size} violates V10-D CPU limit (1..{MAX_CLOSURE_BATCH_SIZE})"
        )
    if block_size != REQUIRED_CLOSURE_BLOCK_SIZE:
        raise V10DClosureError(
            f"block_size={block_size} violates V10-D sequence contract (must equal {REQUIRED_CLOSURE_BLOCK_SIZE})"
        )
    if training_steps < 1 or training_steps > MAX_CLOSURE_STEPS:
        raise V10DClosureError(
            f"training_steps={training_steps} violates V10-D step limit (1..{MAX_CLOSURE_STEPS})"
        )
    if cpu_threads < 1 or cpu_threads > MAX_CLOSURE_CPU_THREADS:
        raise V10DClosureError(
            f"cpu_threads={cpu_threads} violates V10-D CPU thread cap (1..{MAX_CLOSURE_CPU_THREADS})"
        )
    ok, reason = validate_budget(
        params=5_000_000,
        seq_len=block_size,
        batch_size=batch_size,
        steps=training_steps,
        cpu_threads=cpu_threads,
    )
    if not ok:
        raise V10DClosureError(f"Resource budget rejected: {reason}")


def _ensure_dataset_ready(
    dataset_dir: Path,
    *,
    seed: int,
    counts: dict[str, int] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not dataset_dir.exists():
        generate_dataset(dataset_dir, seed=seed, counts=counts or dict(DEFAULT_COUNTS))
    audit_result = run_v10_leakage_audit(dataset_dir)
    if audit_result.get("status") != "PASS":
        raise V10DClosureError(f"nagi_v10 leakage audit failed: {audit_result.get('status')}")
    dataset_result = verify_v10_dataset(dataset_dir)
    if dataset_result.get("dataset_integrity") != "PASS":
        raise V10DClosureError("nagi_v10 dataset integrity verification failed")
    return dataset_result, audit_result


def _ensure_tokenizer_ready(
    dataset_dir: Path,
    tokenizer_path: Path,
    *,
    vocab_size: int,
) -> Path:
    if tokenizer_path.is_file():
        return tokenizer_path
    if tokenizer_path.is_symlink():
        raise V10DClosureError(f"Tokenizer path cannot be a symlink: {tokenizer_path}")
    train_rows = list(load_sft_split(dataset_dir, "train"))
    forbidden_entities: set[str] = set()
    for split_name in ("validation", "test"):
        for row in load_sft_split(dataset_dir, split_name):
            forbidden_entities.update(extract_entities(str(row.get("input", ""))))
            forbidden_entities.update(extract_entities(str(row.get("target", ""))))

    tok = train_slot_safe_tokenizer(
        train_rows,
        vocab_size=vocab_size,
        version="10.0.0",
        use_slots=True,
        schema=SCHEMA_V2,
        forbidden_entities=sorted(forbidden_entities),
    )
    tokenizer_path.parent.mkdir(parents=True, exist_ok=True)
    tok.save(tokenizer_path)
    return tokenizer_path


def run_v10d_closure(
    *,
    dataset_dir: Path | None = None,
    checkpoint_dir: Path | None = None,
    registry_root: Path | None = None,
    tokenizer_path: Path | None = None,
    eval_output_dir: Path | None = None,
    workflow_db: Path | None = None,
    workspace_dir: Path = DEFAULT_WORKSPACE,
    seed: int = 42,
    counts: dict[str, int] | None = None,
    vocab_size: int = 512,
    batch_size: int = 4,
    block_size: int = REQUIRED_CLOSURE_BLOCK_SIZE,
    training_steps: int = 50,
    cpu_threads: int = MAX_CLOSURE_CPU_THREADS,
    requested_by: str = "operator:v10d_closure",
    experiment_id: str = "v10d-closure-run",
    model_version: str | None = None,
    max_examples: int | None = None,
    max_new_tokens: int = 32,
    resume_run_id: str | None = None,
    _train_fn: Callable[..., dict[str, Any]] | None = None,
    _eval_fn: Callable[..., dict[str, Any]] | None = None,
    _model: Any | None = None,
    _load_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run V10-D closure pipeline honestly; never fabricates PASS when torch or approval is missing."""
    _validate_closure_bounds(
        batch_size=batch_size,
        block_size=block_size,
        training_steps=training_steps,
        cpu_threads=cpu_threads,
    )

    ws = workspace_dir.expanduser().resolve()
    resolved_dataset_dir = (dataset_dir or (ws / "data" / "nagi_v10")).expanduser().resolve()
    resolved_ckpt_dir = (checkpoint_dir or (ws / "checkpoints" / "nagi_v10")).expanduser().resolve()
    resolved_registry_root = (registry_root or (ws / "registry")).expanduser().resolve()
    resolved_tokenizer_path = (tokenizer_path or (ws / "tokenizer" / "tokenizer.json")).expanduser().resolve()
    resolved_eval_dir = (eval_output_dir or (ws / "eval" / "nagi_v10")).expanduser().resolve()
    configured_workflow_db = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
    if workflow_db is not None and configured_workflow_db:
        if workflow_db.expanduser().resolve() != Path(configured_workflow_db).expanduser().resolve():
            raise V10DClosureError(
                "workflow_db must match ZYRQUEN_WORKFLOW_DB_PATH so the authenticated API "
                "and V10-D runner operate on the same workflow store."
            )
    resolved_wf_db = (
        workflow_db
        or (Path(configured_workflow_db) if configured_workflow_db else (ws / "workflow" / "v10d_closure.db"))
    ).expanduser().resolve()

    using_test_doubles = _train_fn is not None and _eval_fn is not None
    if not using_test_doubles:
        torch_probe = check_torch_cpu_runtime()
        if not torch_probe["available"]:
            audit = build_v10_closure_audit(
                eval_report_path=os.getenv("ZYRQUEN_EVAL_REPORT_PATH", ""),
                registry_root=str(resolved_registry_root) if resolved_registry_root.is_dir() else "",
                dataset_dir=str(resolved_dataset_dir) if resolved_dataset_dir.is_dir() else "",
                tokenizer_path=str(resolved_tokenizer_path) if resolved_tokenizer_path.is_file() else "",
                runtime_health={
                    "runtime_status": "torch_not_installed",
                    "native_model_loaded": False,
                    "is_trained": False,
                    "model_version": None,
                },
            )
            return {
                "schema": CLOSURE_RUNNER_SCHEMA,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "BLOCKED",
                "reason": "PyTorch CPU runtime is not installed (TORCH_NOT_INSTALLED); V10-D cannot execute real training/inference.",
                "blockers": list(dict.fromkeys([*list(audit.get("blockers") or []), "TORCH_NOT_INSTALLED"])),
                "torch_runtime": torch_probe,
                "v11_unlocked": False,
                "v11_gate": audit["v11_gate"],
                "paths": {
                    "dataset_dir": str(resolved_dataset_dir),
                    "checkpoint_dir": str(resolved_ckpt_dir),
                    "registry_root": str(resolved_registry_root),
                    "tokenizer_path": str(resolved_tokenizer_path),
                    "eval_output_dir": str(resolved_eval_dir),
                    "workflow_db": str(resolved_wf_db),
                },
                "closure_audit": audit,
            }

    # Stage 1 & 2: Dataset generation/verification, leakage audit, and slot-safe tokenizer
    dataset_result, audit_result = _ensure_dataset_ready(
        resolved_dataset_dir,
        seed=seed,
        counts=counts,
    )
    _ensure_tokenizer_ready(
        resolved_dataset_dir,
        resolved_tokenizer_path,
        vocab_size=vocab_size,
    )
    resolved_ckpt_dir.mkdir(parents=True, exist_ok=True)
    resolved_registry_root.mkdir(parents=True, exist_ok=True)

    # The API and runner are separate processes. Real V10-D training therefore
    # requires an explicitly shared SQLite store and HMAC secret; an ephemeral
    # per-process secret cannot authenticate an approval created by another process.
    if not using_test_doubles:
        if not configured_workflow_db:
            audit = build_v10_closure_audit(
                eval_report_path="",
                registry_root=str(resolved_registry_root),
                dataset_dir=str(resolved_dataset_dir),
                tokenizer_path=str(resolved_tokenizer_path),
                runtime_health={"runtime_status": "approval_store_not_shared", "native_model_loaded": False, "is_trained": False, "model_version": None},
            )
            return {
                "schema": CLOSURE_RUNNER_SCHEMA,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "BLOCKED",
                "reason": "Set ZYRQUEN_WORKFLOW_DB_PATH to a persistent path shared by the API and runner.",
                "blockers": ["V10D_SHARED_WORKFLOW_DB_REQUIRED", *list(audit.get("blockers") or [])],
                "v11_unlocked": False,
                "v11_gate": audit["v11_gate"],
                "closure_audit": audit,
            }
        if not os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip():
            audit = build_v10_closure_audit(
                eval_report_path="",
                registry_root=str(resolved_registry_root),
                dataset_dir=str(resolved_dataset_dir),
                tokenizer_path=str(resolved_tokenizer_path),
                runtime_health={"runtime_status": "shared_approval_secret_missing", "native_model_loaded": False, "is_trained": False, "model_version": None},
            )
            return {
                "schema": CLOSURE_RUNNER_SCHEMA,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "BLOCKED",
                "reason": "Set the same strong ZYRQUEN_APPROVAL_SECRET in the API and runner environments.",
                "blockers": ["V10D_SHARED_APPROVAL_SECRET_REQUIRED", *list(audit.get("blockers") or [])],
                "v11_unlocked": False,
                "v11_gate": audit["v11_gate"],
                "closure_audit": audit,
            }

    # Stage 3: Orchestrated Training with Tier-2 HMAC Approval Gate
    with _open_orchestrator(resolved_wf_db) as orch:
        _register_v10d_closure_workflow(
            orch,
            train_fn_override=_train_fn,
            model_override=_model,
            load_fn_override=_load_fn,
        )
        wf_payload: dict[str, Any] = {
            "dataset_dir": str(resolved_dataset_dir),
            "checkpoint_dir": str(resolved_ckpt_dir),
            "tokenizer_path": str(resolved_tokenizer_path),
            "registry_root": str(resolved_registry_root),
            "batch_size": batch_size,
            "block_size": block_size,
            "max_steps": training_steps,
            "segment_max_steps": training_steps,
            "cpu_threads": cpu_threads,
            "use_paid_gpu": False,
            "use_slots": True,
            "target_major": 10,
            "train_config": {
                "batch_size": batch_size,
                "block_size": block_size,
                "max_steps": training_steps,
                "segment_max_steps": training_steps,
                "seed": seed,
                "eval_interval": max(1, min(training_steps, 25)),
                "checkpoint_interval": max(1, min(training_steps, 25)),
                "log_interval": max(1, min(training_steps, 10)),
                "eval_batches": 2,
                "strict_limits": True,
            },
        }
        if model_version is not None:
            wf_payload["model_version"] = model_version

        if resume_run_id:
            wf_run = orch.store.get_run(resume_run_id)
            if wf_run is None:
                raise V10DClosureError(f"Cannot resume unknown V10-D workflow run: {resume_run_id}")
            if wf_run.get("workflow_key") != CLOSURE_WORKFLOW_KEY or wf_run.get("workflow_version") != CLOSURE_WORKFLOW_VERSION:
                raise V10DClosureError("Resume target is not the expected V10-D closure workflow.")
            if wf_run.get("trigger_payload") != wf_payload:
                raise V10DClosureError("Resume payload does not exactly match the original approved run scope.")
            if wf_run.get("status") != "COMPLETED":
                audit = build_v10_closure_audit(
                    eval_report_path="",
                    registry_root=str(resolved_registry_root),
                    dataset_dir=str(resolved_dataset_dir),
                    tokenizer_path=str(resolved_tokenizer_path),
                    runtime_health={"runtime_status": "awaiting_training_completion", "native_model_loaded": False, "is_trained": False, "model_version": None},
                )
                return {
                    "schema": CLOSURE_RUNNER_SCHEMA,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "overall_status": "BLOCKED",
                    "reason": f"Approved V10-D workflow has not completed (status={wf_run.get('status')}).",
                    "blockers": ["V10D_TRAINING_WORKFLOW_NOT_COMPLETED", *list(audit.get("blockers") or [])],
                    "workflow_run": wf_run,
                    "v11_unlocked": False,
                    "v11_gate": audit["v11_gate"],
                    "closure_audit": audit,
                }
        else:
            wf_run = orch.trigger_workflow(
                CLOSURE_WORKFLOW_KEY,
                version=CLOSURE_WORKFLOW_VERSION,
                trigger_type="manual",
                payload=wf_payload,
                requested_by_user_id=requested_by,
                actor_id=requested_by,
            )

        if wf_run["status"] == "WAITING_APPROVAL":
            # Fail closed: this CLI cannot authenticate an administrator.
            # Tier-2 decisions must be issued by the authenticated admin API.
            audit = build_v10_closure_audit(
                eval_report_path="",
                registry_root=str(resolved_registry_root),
                dataset_dir=str(resolved_dataset_dir),
                tokenizer_path=str(resolved_tokenizer_path),
                runtime_health={
                    "runtime_status": "awaiting_tier2_approval",
                    "native_model_loaded": False,
                    "is_trained": False,
                    "model_version": None,
                },
            )
            return {
                "schema": CLOSURE_RUNNER_SCHEMA,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "BLOCKED",
                "reason": (
                    "Workflow paused at WAITING_APPROVAL. This CLI cannot assert admin identity; "
                    "an authenticated Tier-2 approval integration is required before training."
                ),
                "blockers": ["TIER2_HMAC_APPROVAL_REQUIRED", *list(audit.get("blockers") or [])],
                "workflow_run": wf_run,
                "v11_unlocked": False,
                "v11_gate": audit["v11_gate"],
                "closure_audit": audit,
            }

        if wf_run["status"] != "COMPLETED":
            raise V10DClosureError(
                f"Training workflow did not complete: status={wf_run['status']} error={wf_run.get('error_message')}"
            )

        train_steps = [s for s in wf_run.get("steps", []) if s["step_key"] == "execute_v10d_training"]
        if not train_steps or not isinstance(train_steps[0].get("output"), dict):
            raise V10DClosureError("Training step did not emit structured output")
        train_output = train_steps[0]["output"]
        resolved_model_version = str(
            train_output.get("registry_model_version") or train_output.get("model_version") or ""
        )
        if not resolved_model_version:
            raise V10DClosureError("Training step did not return canonical model_version")
        resolved_train_ckpt_dir = Path(str(train_output.get("checkpoint_dir") or resolved_ckpt_dir))

        # Stage 4: Native Inference Evaluation + Evaluation Report + Registry Evidence Gate
        checkpoint_info = verify_registry_model(resolved_registry_root, resolved_model_version)
        if _eval_fn is not None:
            inference_result = _eval_fn(
                resolved_model_version,
                dataset_dir=resolved_dataset_dir,
                tokenizer_path=resolved_tokenizer_path,
                checkpoint_dir=resolved_train_ckpt_dir,
                registry_root=resolved_registry_root,
                max_examples=max_examples,
                max_new_tokens=max_new_tokens,
            )
        else:
            eval_engine = EvaluationEngine(
                checkpoint_dir=resolved_train_ckpt_dir,
                registry_root=resolved_registry_root,
                load_fn=_load_fn,
            )
            inference_result = eval_engine.evaluate_native_model(
                resolved_model_version,
                dataset_dir=resolved_dataset_dir,
                tokenizer_path=resolved_tokenizer_path,
                max_examples=max_examples,
                max_new_tokens=max_new_tokens,
            )

        regression_comparison = build_regression_comparison(
            resolved_registry_root,
            resolved_model_version,
            inference_result,
        )
        leakage_detail = {
            "status": str(audit_result.get("status", "FAIL")),
            "total_examples": audit_result.get("total_examples"),
            "split_counts": audit_result.get("split_counts"),
            "gates_passed": {
                k: bool(v.get("passed")) for k, v in (audit_result.get("gates") or {}).items()
            },
        }
        eval_report = build_evaluation_report(
            dataset_dir=resolved_dataset_dir,
            experiment_id=experiment_id,
            dataset_result=dataset_result,
            leakage_audit_status=leakage_detail["status"],
            leakage_audit_detail=leakage_detail,
            checkpoint_info=checkpoint_info,
            inference_result=inference_result,
            inference_status=str(inference_result.get("inference_status") or "PASS"),
            regression_comparison=regression_comparison,
            error=None,
        )
        eval_report_path = write_eval_report(eval_report, resolved_eval_dir)

        eval_wf_run = orch.trigger_workflow(
            "evaluation.model_verification",
            version="1.0.0",
            trigger_type="manual",
            payload={
                "model_version": resolved_model_version,
                "registry_root": str(resolved_registry_root),
                "checkpoint_dir": str(resolved_train_ckpt_dir),
                "report_path": str(eval_report_path),
            },
            requested_by_user_id=requested_by,
            actor_id=requested_by,
        )

    # Verify registry state after evaluation gate
    reg_kwargs = {"load_fn": _load_fn} if _load_fn is not None else {}
    reg = ModelRegistry(resolved_registry_root, **reg_kwargs)
    reg_rec = reg.get(resolved_model_version)

    # Stage 5: Final Closure Audit & V11 Gate
    audit = build_v10_closure_audit(
        eval_report_path=eval_report_path,
        registry_root=resolved_registry_root,
        dataset_dir=resolved_dataset_dir,
        tokenizer_path=resolved_tokenizer_path,
        runtime_health={
            "runtime_status": "ready",
            "native_model_loaded": True,
            "is_trained": True,
            "model_version": resolved_model_version,
        },
    )

    return {
        "schema": CLOSURE_RUNNER_SCHEMA,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": audit["overall_status"],
        "v11_unlocked": bool(audit["v11_gate"]["unlocked"]),
        "v11_gate": audit["v11_gate"],
        "blockers": list(audit.get("blockers") or []),
        "model_version": resolved_model_version,
        "lifecycle_status": reg_rec.get("lifecycle_status"),
        "eval_report_path": str(eval_report_path),
        "eval_overall_status": eval_report.get("overall_status"),
        "training_workflow_run_id": wf_run["id"],
        "training_workflow_status": wf_run["status"],
        "evaluation_workflow_run_id": eval_wf_run["id"],
        "evaluation_workflow_status": eval_wf_run["status"],
        "paths": {
            "dataset_dir": str(resolved_dataset_dir),
            "checkpoint_dir": str(resolved_train_ckpt_dir),
            "registry_root": str(resolved_registry_root),
            "tokenizer_path": str(resolved_tokenizer_path),
            "eval_output_dir": str(resolved_eval_dir),
            "workflow_db": str(resolved_wf_db),
        },
        "closure_audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute ZYRQUEN V10-D end-to-end closure pipeline.")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--dataset-dir", type=Path, default=None)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--registry-root", type=Path, default=None)
    parser.add_argument("--tokenizer-path", type=Path, default=None)
    parser.add_argument("--eval-output-dir", type=Path, default=None)
    parser.add_argument("--workflow-db", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--vocab-size", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--block-size", type=int, default=REQUIRED_CLOSURE_BLOCK_SIZE)
    parser.add_argument("--training-steps", type=int, default=50)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--requested-by", type=str, default="cli:close_v10d")
    parser.add_argument("--experiment-id", type=str, default="v10d-closure-run")
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--resume-run-id", type=str, default=None, help="Resume evaluation for a completed V10-D run after authenticated API approval.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_v10d_closure(
            workspace_dir=args.workspace_dir,
            dataset_dir=args.dataset_dir,
            checkpoint_dir=args.checkpoint_dir,
            registry_root=args.registry_root,
            tokenizer_path=args.tokenizer_path,
            eval_output_dir=args.eval_output_dir,
            workflow_db=args.workflow_db,
            seed=args.seed,
            vocab_size=args.vocab_size,
            batch_size=args.batch_size,
            block_size=args.block_size,
            training_steps=args.training_steps,
            cpu_threads=args.cpu_threads,
            requested_by=args.requested_by,
            experiment_id=args.experiment_id,
            max_examples=args.max_examples,
            max_new_tokens=args.max_new_tokens,
            resume_run_id=args.resume_run_id,
        )
    except V10DClosureError as exc:
        print(json.dumps({"schema": CLOSURE_RUNNER_SCHEMA, "overall_status": "FAILED", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    status = str(result.get("overall_status", "BLOCKED")).upper()
    if status == "PASS":
        return 0
    if status == "BLOCKED":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
