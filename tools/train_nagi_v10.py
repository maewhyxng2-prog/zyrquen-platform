#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — NAGI v10 Training Controller

Purpose:
  Perform a strict pre-training readiness check for NAGI v10 while reusing the
  existing ZYRQUEN Workflow Engine, Resource Guard, HMAC Approval Gate, and
  Model Registry without creating duplicate orchestration or governance systems.

Capabilities:
  - Locked CPU-only resource budget enforcement (via autonomous_training_loop)
  - WorkflowResourceGuard inspection (RAM, Disk, CPU bounds, CostLimits, no paid GPU)
  - Dataset manifest & SHA-256 verification + independent leakage auditor check
  - CentralWorkflowOrchestrator + WorkflowGovernance HMAC-SHA256 Tier-2 gate check
  - Honest PyTorch availability check (never simulates or starts training)
  - Immutable atomic readiness report under eval/nagi_v10/

Safety:
  - CPU only; no paid GPU.
  - Does not modify v7, v8, or v9 artifacts.
  - Does not modify datasets or overwrite checkpoints.
  - Does not auto-approve Tier-2 HMAC tokens.
  - Does not start training or fabricate metrics.

Exit codes:
  0 = PREFLIGHT PASS (only if hook + approval + resources all ready; training not started)
  1 = PREFLIGHT FAILED (invalid dataset, manifest, audit failure, or config error)
  2 = INVALID ARGUMENTS
  3 = TRAINING BLOCKED (resources, missing Tier-2 approval, missing torch, or unimplemented hook)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.core.native.registry import ModelRegistry, RegistryError  # noqa: E402
from apps.core.resource import ResourceManager  # noqa: E402
from apps.core.workflow.autonomous_training_loop import (  # noqa: E402
    DISK_RESERVE_GB,
    MAX_BATCH,
    MAX_CHECKPOINTS_PER_RUN,
    MAX_PARAMS,
    MAX_SEQ,
    MAX_STEPS,
    RAM_HARD_GB,
    RAM_SOFT_GB,
    check_disk_reserve,
    validate_budget,
)
from apps.core.workflow.models import (  # noqa: E402
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowStepSpec,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator  # noqa: E402
from apps.core.workflow.resource_guard import WorkflowResourceGuard  # noqa: E402

DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v10"
DEFAULT_AUDITOR = PROJECT_ROOT / "tools" / "audit_leakage_v10.py"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "eval" / "nagi_v10"

PREFLIGHT_REPORT_SCHEMA = "zyrquen.v10.training_preflight.v1"
WORKFLOW_KEY = "training.nagi_v10_controlled_run"
WORKFLOW_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Locked Resource Budget (aligned with v10_summary.md & autonomous_training_loop)
# ---------------------------------------------------------------------------
MAX_CPU_CORES = 2
MAX_PARAMETERS = MAX_PARAMS  # 5,000,000
MAX_SEQUENCE_LENGTH = MAX_SEQ  # 256
MAX_BATCH_SIZE = MAX_BATCH  # 4
MAX_TRAINING_STEPS = MAX_STEPS  # 500

RAM_SOFT_LIMIT_BYTES = int(RAM_SOFT_GB * 1024**3)
RAM_HARD_LIMIT_BYTES = int(RAM_HARD_GB * 1024**3)
MIN_FREE_DISK_BYTES = int(DISK_RESERVE_GB * 1024**3)
MAX_NEW_DISK_BYTES = int(1.0 * 1024**3)

EXPERIMENT_TIMEOUT_SECONDS = 20 * 60
COMPLETE_LOOP_TIMEOUT_SECONDS = 60 * 60

# ---------------------------------------------------------------------------
# Locked Implementation & Authorization Constants (never fake approval)
# ---------------------------------------------------------------------------
TRAINING_HOOK_IMPLEMENTED = False
PAID_GPU_ALLOWED = False
TRAINING_IMPLEMENTATION_STATUS = "training_hook_not_implemented"
MODEL_ARCHITECTURE_STATUS = "pending_review"
TRAINING_OBJECTIVE_STATUS = "pending_review"


@dataclass
class ResourceSnapshot:
    host_cpu_cores: int
    configured_cpu_threads: int
    ram_total_bytes: int | None
    ram_available_bytes: int | None
    process_ram_bytes: int | None
    disk_free_bytes: int
    disk_free_gb: float
    gpu_available: bool
    torch_installed: bool
    torch_version: str | None
    platform: str


@dataclass
class TrainingConfig:
    seed: int = 42
    batch_size: int = 4
    sequence_length: int = 256
    training_steps: int = 500
    learning_rate: float = 0.0003
    weight_decay: float = 0.01
    max_parameters: int = MAX_PARAMETERS
    cpu_threads: int = MAX_CPU_CORES
    max_checkpoints: int = MAX_CHECKPOINTS_PER_RUN
    device: str = "cpu"
    use_paid_gpu: bool = False
    timeout_seconds: int = EXPERIMENT_TIMEOUT_SECONDS


class PreflightError(Exception):
    """Raised when a mandatory dataset, manifest, audit, or config prerequisite fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    path = Path("/proc/meminfo")
    if not path.is_file():
        return result
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            parts = value.strip().split()
            if parts:
                result[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        return {}
    return result


def process_memory_bytes() -> int | None:
    status = Path("/proc/self/status")
    if not status.is_file():
        return None
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def detect_cpu_cores() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def detect_gpu_without_cuda_init() -> bool:
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_visible is not None and cuda_visible.strip() in ("", "-1"):
        return False
    return shutil.which("nvidia-smi") is not None


def detect_torch() -> tuple[bool, str | None]:
    try:
        import torch  # type: ignore

        return True, getattr(torch, "__version__", "unknown")
    except ModuleNotFoundError:
        return False, None


def detect_resources(dataset_dir: Path, cpu_threads: int) -> ResourceSnapshot:
    meminfo = read_meminfo()
    ram_total = meminfo.get("MemTotal")
    ram_available = meminfo.get("MemAvailable")
    if ram_total is None:
        try:
            ram_total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            ram_total = None

    disk_target = dataset_dir
    while not disk_target.exists() and disk_target != disk_target.parent:
        disk_target = disk_target.parent
    disk_free = shutil.disk_usage(disk_target).free
    torch_ok, torch_ver = detect_torch()

    return ResourceSnapshot(
        host_cpu_cores=detect_cpu_cores(),
        configured_cpu_threads=cpu_threads,
        ram_total_bytes=ram_total,
        ram_available_bytes=ram_available,
        process_ram_bytes=process_memory_bytes(),
        disk_free_bytes=disk_free,
        disk_free_gb=round(disk_free / (1024**3), 3),
        gpu_available=detect_gpu_without_cuda_init(),
        torch_installed=torch_ok,
        torch_version=torch_ver,
        platform=platform.platform(),
    )


def validate_config(config: TrainingConfig) -> None:
    if config.device != "cpu" or config.use_paid_gpu:
        raise PreflightError("Only CPU-only execution is permitted (paid GPU forbidden)")
    if config.cpu_threads < 1 or config.cpu_threads > MAX_CPU_CORES:
        raise PreflightError(f"cpu_threads must be between 1 and {MAX_CPU_CORES}")
    if config.max_checkpoints < 1 or config.max_checkpoints > MAX_CHECKPOINTS_PER_RUN:
        raise PreflightError(f"max_checkpoints must be between 1 and {MAX_CHECKPOINTS_PER_RUN}")

    ok, reason = validate_budget(
        params=config.max_parameters,
        seq_len=config.sequence_length,
        batch_size=config.batch_size,
        steps=config.training_steps,
    )
    if not ok:
        raise PreflightError(f"Resource budget violated: {reason}")

    if config.timeout_seconds < 1 or config.timeout_seconds > EXPERIMENT_TIMEOUT_SECONDS:
        raise PreflightError(f"Experiment timeout must be between 1 and {EXPERIMENT_TIMEOUT_SECONDS}s")
    if config.learning_rate <= 0:
        raise PreflightError("Learning rate must be positive")
    if config.weight_decay < 0:
        raise PreflightError("Weight decay cannot be negative")


def validate_resources(
    resources: ResourceSnapshot,
    dataset_dir: Path,
    checkpoint_dir: Path,
) -> list[str]:
    blockers: list[str] = []
    if resources.host_cpu_cores < 1:
        blockers.append("CPU_UNAVAILABLE")
    if resources.configured_cpu_threads > MAX_CPU_CORES:
        blockers.append(f"CPU_THREADS_EXCEEDED:{resources.configured_cpu_threads}")
    if resources.ram_available_bytes is not None and resources.ram_available_bytes < RAM_SOFT_LIMIT_BYTES:
        blockers.append("INSUFFICIENT_AVAILABLE_RAM")
    if resources.process_ram_bytes is not None and resources.process_ram_bytes >= RAM_HARD_LIMIT_BYTES:
        blockers.append("PROCESS_RAM_HARD_LIMIT_REACHED")

    disk_ok, _ = check_disk_reserve(checkpoint_dir, reserve_gb=DISK_RESERVE_GB)
    if not disk_ok or resources.disk_free_bytes < MIN_FREE_DISK_BYTES:
        blockers.append("DISK_FREE_RESERVE_NOT_MET")

    if not resources.torch_installed:
        blockers.append("TORCH_NOT_INSTALLED")

    return blockers


def check_dataset_manifest(dataset_dir: Path) -> dict[str, Any]:
    if not dataset_dir.exists() or dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise PreflightError(f"Dataset directory not found or invalid: {dataset_dir}")

    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise PreflightError("Dataset manifest.json is missing or symlinked")

    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"Cannot read dataset manifest: {exc}") from exc

    if not isinstance(manifest, dict):
        raise PreflightError("Dataset manifest root must be a JSON object")
    if manifest.get("dataset") != "nagi_v10":
        raise PreflightError(f"Unexpected dataset identifier: {manifest.get('dataset')!r}")
    if manifest.get("schema") != "zyrquen.dataset-manifest.v1":
        raise PreflightError(f"Unexpected manifest schema: {manifest.get('schema')!r}")

    return {
        "status": "PRESENT",
        "dataset": manifest.get("dataset"),
        "version": manifest.get("version"),
        "schema": manifest.get("schema"),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "content_sha256": manifest.get("content_sha256"),
        "total_examples": manifest.get("total_examples"),
        "seed": manifest.get("seed"),
    }


def run_leakage_audit(auditor: Path, dataset_dir: Path) -> dict[str, Any]:
    if not auditor.is_file():
        raise PreflightError(f"Leakage auditor not found: {auditor}")
    if not dataset_dir.is_dir():
        raise PreflightError(f"Dataset directory not found: {dataset_dir}")

    command = [
        sys.executable,
        str(auditor),
        "--dataset-dir",
        str(dataset_dir),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PreflightError("Leakage audit timed out") from exc

    if result.returncode != 0:
        raise PreflightError(
            f"Leakage audit did not pass (exit={result.returncode}): "
            f"{(result.stderr or result.stdout)[-1000:]}"
        )

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError("Leakage auditor did not return valid JSON") from exc

    if report.get("status") != "PASS":
        raise PreflightError("Leakage auditor did not report PASS")
    if report.get("read_only") is not True:
        raise PreflightError("Leakage auditor did not confirm read-only execution")

    return {
        "status": "PASS",
        "return_code": result.returncode,
        "dataset": report.get("dataset"),
        "total_examples": report.get("total_examples"),
        "split_counts": report.get("split_counts"),
        "capabilities": report.get("capabilities"),
        "reasoning_operators": report.get("reasoning_operators"),
        "content_sha256": report.get("content_sha256"),
        "unseen_abstract_operator_generalization": report.get("unseen_abstract_operator_generalization"),
    }


@contextmanager
def open_orchestrator(workflow_db: Path | None) -> Iterator[tuple[CentralWorkflowOrchestrator, bool]]:
    """Open existing CentralWorkflowOrchestrator with persistent or ephemeral SQLite store."""
    if workflow_db is not None:
        orch = CentralWorkflowOrchestrator(db_path=workflow_db, work_dir=PROJECT_ROOT)
        try:
            yield orch, False
        finally:
            orch.shutdown(wait=True)
        return

    with tempfile.TemporaryDirectory(prefix="zyrquen_v10_wf_") as tmp_dir:
        tmp_db = Path(tmp_dir) / "workflow_preflight.db"
        orch = CentralWorkflowOrchestrator(db_path=tmp_db, work_dir=PROJECT_ROOT)
        try:
            yield orch, True
        finally:
            orch.shutdown(wait=True)


def register_v10_workflow(
    orch: CentralWorkflowOrchestrator,
    *,
    auditor_path: Path,
) -> None:
    """Register the v10 controlled training workflow on the existing CentralWorkflowOrchestrator."""

    def handle_v10_preflight(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
        dataset_dir = Path(str(payload["dataset_dir"])).resolve()
        checkpoint_dir = Path(str(payload["checkpoint_dir"])).resolve()
        cfg_dict = dict(payload["training_config_raw"])
        cfg = TrainingConfig(**cfg_dict)

        validate_config(cfg)
        resources = detect_resources(dataset_dir, cfg.cpu_threads)
        manifest_info = check_dataset_manifest(dataset_dir)
        audit_info = run_leakage_audit(auditor_path, dataset_dir)
        res_blockers = validate_resources(resources, dataset_dir, checkpoint_dir)

        if res_blockers:
            return StepExecutionResult(
                verdict="BLOCKED",
                summary=f"v10 preflight resource/runtime blockers: {res_blockers}",
                output={
                    "dataset": manifest_info,
                    "leakage_audit": audit_info,
                    "resource_blockers": res_blockers,
                },
                evidence={"verdict": "BLOCKED", "blockers": res_blockers},
                error_code="resource_or_runtime_blocked",
            )

        return StepExecutionResult(
            verdict="PASS",
            summary="v10 dataset integrity, leakage audit, and resource preflight PASSED.",
            output={"dataset": manifest_info, "leakage_audit": audit_info},
            evidence={
                "verdict": "PASS",
                "manifest_sha256": manifest_info["manifest_sha256"],
                "content_sha256": manifest_info["content_sha256"],
            },
        )

    def handle_v10_execute(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
        # Mandatory Tier-2 consumed approval check (WorkflowGovernance already verified HMAC)
        approval = ctx.get("consumed_approval") or {}
        if not approval:
            return StepExecutionResult(
                verdict="NOT RUN",
                summary="Tier-2 HMAC approval missing in execution context.",
                error_code="approval_required",
            )

        torch_ok, _ = detect_torch()
        if not torch_ok:
            return StepExecutionResult(
                verdict="BLOCKED",
                summary="v10 training blocked: PyTorch runtime is not installed.",
                error_code="torch_not_installed",
            )

        if not TRAINING_HOOK_IMPLEMENTED:
            return StepExecutionResult(
                verdict="BLOCKED",
                summary="v10 training blocked: native v10 architecture and training hook are not implemented.",
                error_code="training_hook_not_implemented",
            )

        return StepExecutionResult(
            verdict="NOT RUN",
            summary="v10 training hook intentionally disabled.",
            error_code="training_hook_not_implemented",
        )

    orch.registry.register_handler("v10.preflight_and_audit", handle_v10_preflight)
    orch.registry.register_handler("v10.execute_training", handle_v10_execute)

    defn = WorkflowDefinition(
        workflow_key=WORKFLOW_KEY,
        version=WORKFLOW_VERSION,
        group_name="training",
        title="NAGI v10 Controlled CPU Training Pipeline",
        description="Tier-1 dataset/leakage/resource preflight followed by Tier-2 HMAC-gated training step.",
        default_tier="tier2_approval",
        steps=(
            WorkflowStepSpec(
                step_key="preflight_and_leakage_audit",
                handler_key="v10.preflight_and_audit",
                description="Verify nagi_v10 manifest, leakage gates, and CPU budget.",
                lane="control_ops",
                tier="tier1_auto",
                action_type="read_only",
                min_disk_gb=DISK_RESERVE_GB,
            ),
            WorkflowStepSpec(
                step_key="execute_v10_training",
                handler_key="v10.execute_training",
                description="Execute CPU-bounded v10 training after Tier-2 HMAC admin approval.",
                depends_on=("preflight_and_leakage_audit",),
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


def inspect_workflow_and_resource_guard(
    *,
    config: TrainingConfig,
    dataset_dir: Path,
    checkpoint_dir: Path,
    auditor_path: Path,
    workflow_db: Path | None,
    requested_by: str,
    run_id: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Run real WorkflowResourceGuard + CentralWorkflowOrchestrator + HMAC Governance check."""
    guard = WorkflowResourceGuard(
        resource_manager=ResourceManager(max_ram_mb=int(RAM_HARD_GB * 1024)),
        work_dir=PROJECT_ROOT,
        min_free_disk_gb=DISK_RESERVE_GB,
    )
    step_spec = WorkflowStepSpec(
        step_key="execute_v10_training",
        handler_key="v10.execute_training",
        description="NAGI v10 controlled CPU training",
        lane="compute_heavy",
        tier="tier2_approval",
        action_type="training.execute",
        min_disk_gb=DISK_RESERVE_GB,
    )
    guard_payload = {
        "use_paid_gpu": config.use_paid_gpu,
        "estimated_params": config.max_parameters,
        "training_config": {"batch_size": config.batch_size, "max_steps": config.training_steps},
        "model_config": {"max_seq_len": config.sequence_length},
    }
    guard_outcome = guard.check_step(step_spec, guard_payload, has_paid_gpu_approval=False)

    integration_blockers: list[str] = []
    if not guard_outcome.allowed:
        integration_blockers.append(
            f"RESOURCE_GUARD_{'BLOCKED' if guard_outcome.blocked else 'WAITING'}:{guard_outcome.reason}"
        )

    with open_orchestrator(workflow_db) as (orch, is_ephemeral):
        register_v10_workflow(orch, auditor_path=auditor_path)

        if run_id:
            existing = orch.store.get_run(run_id)
            if existing is None:
                raise PreflightError(f"Workflow run_id not found: {run_id}")
            wf_run = orch.execute_run(run_id)
        else:
            wf_payload = {
                "dataset_dir": str(dataset_dir),
                "checkpoint_dir": str(checkpoint_dir),
                "training_config_raw": asdict(config),
                "training_config": {"batch_size": config.batch_size, "max_steps": config.training_steps},
                "model_config": {"max_seq_len": config.sequence_length},
                "estimated_params": config.max_parameters,
                "use_paid_gpu": False,
            }
            wf_run = orch.trigger_workflow(
                WORKFLOW_KEY,
                version=WORKFLOW_VERSION,
                trigger_type="manual",
                payload=wf_payload,
                requested_by_user_id=requested_by,
                actor_id=requested_by,
            )

        approvals = wf_run.get("approvals", [])
        latest_approval = approvals[0] if approvals else None
        audit_count = len(orch.store.list_audit_logs(run_id=wf_run["id"], limit=50))

        wf_summary = {
            "orchestrator": "CentralWorkflowOrchestrator",
            "workflow_key": WORKFLOW_KEY,
            "workflow_version": WORKFLOW_VERSION,
            "ephemeral_db": is_ephemeral,
            "workflow_run_id": wf_run["id"],
            "workflow_status": wf_run["status"],
            "steps": {
                s["step_key"]: {"status": s["status"], "error_code": s.get("error_code")}
                for s in wf_run.get("steps", [])
            },
            "approval": (
                {
                    "id": latest_approval["id"],
                    "status": latest_approval["status"],
                    "action_type": latest_approval["action_type"],
                    "scope": latest_approval["scope"],
                    "hmac_signed": bool(latest_approval.get("signature_hmac")),
                }
                if latest_approval
                else None
            ),
            "audit_events_recorded": audit_count,
            "resource_guard": {
                "allowed": guard_outcome.allowed,
                "blocked": guard_outcome.blocked,
                "wait_for_resource": guard_outcome.wait_for_resource,
                "reason": guard_outcome.reason,
                "snapshot": guard_outcome.snapshot,
            },
        }

        if wf_run["status"] == "WAITING_APPROVAL":
            integration_blockers.append("TIER2_HMAC_APPROVAL_REQUIRED")
        elif latest_approval is None or latest_approval.get("status") != "consumed":
            integration_blockers.append("TIER2_APPROVAL_NOT_CONSUMED")

    return wf_summary, integration_blockers


def inspect_registry(registry_root: Path | None) -> dict[str, Any] | None:
    if registry_root is None:
        return None
    if not registry_root.exists():
        return {"configured": True, "exists": False, "active_version": None}
    try:
        reg = ModelRegistry(registry_root)
        return {
            "configured": True,
            "exists": True,
            "active_version": reg.active_version(),
            "registered_count": len(reg.list_versions()),
        }
    except RegistryError as exc:
        return {"configured": True, "exists": True, "error": str(exc)}


def build_readiness_report(
    *,
    config: TrainingConfig,
    resources: ResourceSnapshot,
    dataset_result: dict[str, Any] | None,
    audit_result: dict[str, Any] | None,
    workflow_result: dict[str, Any] | None,
    registry_result: dict[str, Any] | None,
    blockers: list[str],
) -> dict[str, Any]:
    approval_verified = bool(
        workflow_result
        and (workflow_result.get("approval") or {}).get("status") == "consumed"
    )
    approval_status = (
        (workflow_result.get("approval") or {}).get("status")
        if workflow_result and workflow_result.get("approval")
        else "tier2_token_not_issued"
    )

    return {
        "schema_version": "1.0",
        "report_schema": PREFLIGHT_REPORT_SCHEMA,
        "project": "ZYRQUEN Ω∞",
        "model": "NAGI v10",
        "created_at_utc": utc_now(),
        "status": "BLOCKED" if blockers else "PREFLIGHT_PASS",
        "training_started": False,
        "training_hook": {
            "implemented": TRAINING_HOOK_IMPLEMENTED,
            "status": TRAINING_IMPLEMENTATION_STATUS,
        },
        "tier2_approval": {
            "verified_via_governance": approval_verified,
            "status": approval_status,
            "gate": "apps.core.workflow.governance.WorkflowGovernance",
        },
        "architecture": MODEL_ARCHITECTURE_STATUS,
        "training_objective": TRAINING_OBJECTIVE_STATUS,
        "config": asdict(config),
        "resources": asdict(resources),
        "dataset": dataset_result,
        "leakage_audit": audit_result,
        "workflow_integration": workflow_result,
        "model_registry": registry_result,
        "blockers": blockers,
        "checkpoint_created": False,
        "evaluation_performed": False,
        "promotion": "NOT AUTHORIZED",
        "limitations": [
            "This controller prepares and gates v10 training; it does not train a model.",
            "No v10 model architecture or training objective has been approved yet.",
            "Actual training metrics remain unavailable until execution is implemented and approved.",
            "No checkpoint was created or modified.",
        ],
    }


def write_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    if report_dir.is_symlink():
        raise PreflightError("Report output directory cannot be a symlink")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    report_path = report_dir / f"v10_training_preflight_{timestamp}.json"
    if report_path.exists():
        raise PreflightError(f"Refusing to overwrite existing preflight report: {report_path}")
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".v10_preflight_", suffix=".tmp", dir=report_dir)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if report_path.exists():
            raise PreflightError("Report appeared concurrently; refusing overwrite")
        os.replace(tmp_path, report_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NAGI v10 CPU-only training readiness controller.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--auditor", type=Path, default=DEFAULT_AUDITOR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--checkpoint-dir", type=Path, default=PROJECT_ROOT / "checkpoints" / "nagi_v10")
    parser.add_argument("--workflow-db", type=Path, default=None, help="Optional persistent workflow SQLite DB path.")
    parser.add_argument("--workflow-run-id", type=str, default=None, help="Optional existing approved workflow run ID.")
    parser.add_argument("--registry-root", type=Path, default=None, help="Optional ModelRegistry root for read-only check.")
    parser.add_argument("--requested-by", type=str, default="cli:train_nagi_v10")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sequence-length", type=int, default=256)
    parser.add_argument("--training-steps", type=int, default=500)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--no-write-report", action="store_true", help="Do not write JSON report file to disk.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = TrainingConfig(
        seed=args.seed,
        batch_size=args.batch_size,
        sequence_length=args.sequence_length,
        training_steps=args.training_steps,
        cpu_threads=args.cpu_threads,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
    )

    dataset_dir = args.dataset_dir.expanduser().resolve()
    auditor_path = args.auditor.expanduser().resolve()
    checkpoint_dir = args.checkpoint_dir.expanduser().resolve()
    env_wf_db = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
    workflow_db = (
        args.workflow_db.expanduser().resolve()
        if args.workflow_db is not None
        else (Path(env_wf_db).expanduser().resolve() if env_wf_db else None)
    )
    registry_root = args.registry_root.expanduser().resolve() if args.registry_root else None

    try:
        validate_config(config)
        resources = detect_resources(dataset_dir, config.cpu_threads)
        blockers = validate_resources(resources, dataset_dir, checkpoint_dir)

        dataset_result = check_dataset_manifest(dataset_dir)
        audit_result = run_leakage_audit(auditor_path, dataset_dir)
        workflow_result, wf_blockers = inspect_workflow_and_resource_guard(
            config=config,
            dataset_dir=dataset_dir,
            checkpoint_dir=checkpoint_dir,
            auditor_path=auditor_path,
            workflow_db=workflow_db,
            requested_by=args.requested_by,
            run_id=args.workflow_run_id,
        )
        registry_result = inspect_registry(registry_root)

        for b in wf_blockers:
            if b not in blockers:
                blockers.append(b)

        if not TRAINING_HOOK_IMPLEMENTED:
            blockers.append("TRAINING_HOOK_NOT_IMPLEMENTED")
        if MODEL_ARCHITECTURE_STATUS != "APPROVED":
            blockers.append("MODEL_ARCHITECTURE_NOT_APPROVED")
        if TRAINING_OBJECTIVE_STATUS != "APPROVED":
            blockers.append("TRAINING_OBJECTIVE_NOT_APPROVED")

        report = build_readiness_report(
            config=config,
            resources=resources,
            dataset_result=dataset_result,
            audit_result=audit_result,
            workflow_result=workflow_result,
            registry_result=registry_result,
            blockers=blockers,
        )

        report_path: Path | None = None
        if not args.no_write_report:
            report_path = write_report(report, args.report_dir.expanduser().resolve())

        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if report_path is not None:
            print(f"\nPreflight report: {report_path}")

        if blockers:
            print("\nTRAINING STATUS: BLOCKED")
            print("Training started: NO")
            print("Checkpoint created: NO")
            for blocker in blockers:
                print(f"BLOCKER: {blocker}")
            return 3

        print("\nPREFLIGHT: PASS")
        print("Training started: NO")
        return 0

    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr)
        print("Training started: NO", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Training started: NO", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
