import hmac
import importlib.util
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.core.native.dataset_status import (
    inspect_training_preflight_readiness,
    inspect_v11_training_dataset_readiness,
)
from apps.core.training_infrastructure.monitoring.training_monitor import (
    TrainingMonitor,
)
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    SCHEMA as CHECKPOINT_SCHEMA,
    CheckpointManager,
)
from apps.core.training.orchestrator import TrainingUnavailable
from apps.core.workflow import ApprovalViolationError
from apps.api.database import SessionLocal, get_db
from apps.api.models import User
from apps.api.routers.workflows import get_workflow_engine
from apps.api.security import get_current_user
from apps.api.training_jobs import (
    TrainingJobBusy,
    TrainingJobService,
    training_admin_emails,
)
from apps.api.training_models import TrainingRun
from apps.api.training_schemas import (
    TrainingRunRequest,
    TrainingRunResponse,
    TrainingTelemetryResponse,
)

router = APIRouter(prefix="/training", tags=["Training"])
jobs = TrainingJobService(SessionLocal)


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _run_response(run: TrainingRun) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "dataset_version": run.dataset_version,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "result": _json_safe(run.result),
        "error_message": run.error_message,
    }


def _reconcile_run(run: TrainingRun, db: Session) -> None:
    if run.status in {"queued", "running"} and not jobs.is_active(run.id):
        run.status = "failed"
        run.error_message = "Training worker is no longer active."
        run.finished_at = datetime.now(timezone.utc)
        db.commit()


def require_training_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    admins = training_admin_emails()
    if not admins:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Training admin allowlist is not configured.",
        )
    if current_user.email.strip().lower() not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Training administrator access is required.",
        )
    return current_user


def _verify_training_approval_readonly(engine, approval_id: str) -> dict:
    """Verify Tier-2 approval status, action binding, expiry, and HMAC signature without consuming."""
    approval = engine.governance.store.get_approval(approval_id)
    if approval is None:
        raise ApprovalViolationError(f"Approval request not found: {approval_id}")
    if approval.get("action_type") != "training.execute":
        raise ApprovalViolationError(
            f"Approval {approval_id} action_type={approval.get('action_type')!r} "
            "does not match required 'training.execute'."
        )
    if approval.get("status") != "approved":
        raise ApprovalViolationError(
            f"Approval {approval_id} is not in 'approved' state (status={approval.get('status')!r})."
        )
    try:
        expires_at = datetime.fromisoformat(str(approval["expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ApprovalViolationError(
            f"Approval {approval_id} has invalid expiration timestamp."
        ) from exc
    if expires_at <= datetime.now(timezone.utc):
        raise ApprovalViolationError(f"Approval {approval_id} has expired.")

    expected_sig = engine.governance._compute_signature(
        approval_id=approval["id"],
        run_id=approval["run_id"],
        step_key=approval["step_key"],
        action_type=approval["action_type"],
        scope=approval["scope"],
        expires_at=approval["expires_at"],
    )
    provided_sig = str(approval.get("signature_hmac") or "")
    if not provided_sig or not hmac.compare_digest(expected_sig, provided_sig):
        raise ApprovalViolationError(f"Approval HMAC signature invalid for {approval_id}.")
    return approval


@router.post(
    "/runs",
    response_model=TrainingRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_training(
    request: TrainingRunRequest,
    current_user: User = Depends(require_training_admin),
    db: Session = Depends(get_db),
):
    try:
        # Preserve HTTP 503 when dataset/tokenizer paths are not yet configured;
        # once configured, enforce Tier-2 HMAC workflow approval before execution.
        if (
            jobs._orchestrator.dataset_dir is not None
            and jobs._orchestrator.tokenizer_path is not None
        ):
            approval_id = (request.approval_id or "").strip()
            if not approval_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tier-2 workflow approval_id is required to execute native training.",
                )
            engine = get_workflow_engine()
            try:
                _verify_training_approval_readonly(engine, approval_id)
            except ApprovalViolationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Tier-2 training approval rejected: {exc}",
                ) from exc

            if jobs.is_busy():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A training job is already active.",
                )
            training_cfg = request.training.model_dump()
            model_cfg = request.model.model_dump()
            prepared = jobs._orchestrator.prepare(
                dataset_version=request.dataset_version,
                training_values=training_cfg,
                model_values=model_cfg,
            )

            try:
                return jobs.submit_prepared(
                    db,
                    owner_id=current_user.id,
                    dataset_version=request.dataset_version,
                    training_config=training_cfg,
                    model_config=model_cfg,
                    prepared=prepared,
                    before_enqueue=lambda: engine.governance.verify_and_consume_by_id(
                        approval_id,
                        expected_action_type="training.execute",
                    ),
                )
            except ApprovalViolationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Tier-2 training approval rejected: {exc}",
                ) from exc

        return jobs.submit(
            db,
            owner_id=current_user.id,
            dataset_version=request.dataset_version,
            training_config=request.training.model_dump(),
            model_config=request.model.model_dump(),
        )
    except TrainingJobBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except TrainingUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/readiness")
def get_training_readiness(
    current_user: User = Depends(get_current_user),
):
    """Report structured readiness of Dataset (enforcing V11 4-split + leakage detection), Tokenizer, Runtime, Worker, and Tier-2 Approval without starting training."""
    reasons: list[str] = []

    dataset_env = os.getenv("ZYRQUEN_DATASET_DIR", "").strip()
    tokenizer_env = os.getenv("ZYRQUEN_TOKENIZER_PATH", "").strip()
    dataset_dir = jobs._orchestrator.dataset_dir or (Path(dataset_env).resolve() if dataset_env else None)
    tokenizer_path = jobs._orchestrator.tokenizer_path or (Path(tokenizer_env).resolve() if tokenizer_env else None)
    ds_report = inspect_v11_training_dataset_readiness(dataset_dir)
    dataset_configured = bool(ds_report["configured"])
    dataset_verified = bool(ds_report["verified"])
    four_split_present = bool(ds_report["four_split_present"])
    reasons.extend(ds_report["reasons"])

    preflight = inspect_training_preflight_readiness(
        dataset_dir=dataset_dir,
        tokenizer_path=tokenizer_path,
        training_root=jobs._orchestrator.training_root,
    )
    tokenizer_configured = bool(preflight["tokenizer_configured"])
    tokenizer_valid = bool(preflight["tokenizer_valid"])
    tokenizer_detail = str(preflight["tokenizer_detail"])
    training_root_ready = bool(preflight["storage_writable"])
    for pre_reason in preflight["reasons"]:
        if pre_reason not in reasons:
            reasons.append(pre_reason)

    torch_available = importlib.util.find_spec("torch") is not None
    if not torch_available:
        reasons.append("PyTorch runtime (torch) is not installed in the backend environment.")

    runtime_ready = torch_available and training_root_ready

    worker_busy = jobs.is_busy()
    worker_ready = not getattr(jobs._executor, "_shutdown", False)
    active_run_id = (
        str(jobs._active_run_id)
        if worker_busy and jobs._active_run_id is not None
        else None
    )
    if worker_busy:
        reasons.append(f"Training worker is currently busy with run {active_run_id}.")
    if not worker_ready:
        reasons.append("Training worker executor is shut down.")

    admins = training_admin_emails()
    admin_configured = bool(admins)
    is_training_admin = current_user.email.strip().lower() in admins
    if not admin_configured:
        reasons.append("ZYRQUEN_TRAINING_ADMIN_EMAILS allowlist is not configured.")
    elif not is_training_admin:
        reasons.append("Current user email is not in ZYRQUEN_TRAINING_ADMIN_EMAILS.")

    approval_secret_configured = bool(os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip())
    approved_training_approvals = 0
    pending_training_approvals = 0
    try:
        engine = get_workflow_engine()
        approved_list = engine.governance.store.list_approvals(status="approved", limit=100)
        pending_list = engine.governance.store.list_approvals(status="pending", limit=100)
        now = datetime.now(timezone.utc)
        approved_training_approvals = sum(
            1
            for item in approved_list
            if item.get("action_type") == "training.execute"
            and datetime.fromisoformat(item["expires_at"]) > now
        )
        pending_training_approvals = sum(
            1
            for item in pending_list
            if item.get("action_type") == "training.execute"
            and datetime.fromisoformat(item["expires_at"]) > now
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass

    if approved_training_approvals == 0:
        reasons.append("No active signed Tier-2 approval token for training.execute (required before dispatch).")

    configured = dataset_configured and tokenizer_configured and admin_configured
    all_ready = (
        dataset_verified
        and four_split_present
        and tokenizer_valid
        and bool(preflight["passed"])
        and runtime_ready
        and worker_ready
        and not worker_busy
        and admin_configured
    )
    status_value = (
        "ready"
        if all_ready
        else ("not_configured" if not configured else "not_ready")
    )

    return {
        "configured": configured,
        "status": status_value,
        "dataset_configured": dataset_configured,
        "dataset_verified": dataset_verified,
        "four_split_present": four_split_present,
        "tokenizer_configured": tokenizer_valid,
        "runtime_ready": runtime_ready,
        "torch_available": torch_available,
        "training_root_ready": training_root_ready,
        "worker_ready": worker_ready,
        "worker_busy": worker_busy,
        "admin_allowlist_configured": admin_configured,
        "is_training_admin": is_training_admin,
        "tier2_approval_required": True,
        "approval_secret_configured": approval_secret_configured,
        "approved_training_approvals": approved_training_approvals,
        "pending_training_approvals": pending_training_approvals,
        "active_run_id": active_run_id,
        "dataset": {
            key: value for key, value in ds_report.items() if key != "reasons"
        },
        "tokenizer": {
            "configured": tokenizer_configured,
            "valid": tokenizer_valid,
            "detail": tokenizer_detail,
        },
        "preflight": {
            key: value for key, value in preflight.items() if key != "reasons"
        },
        "runtime": {
            "ready": runtime_ready,
            "torch_available": torch_available,
            "training_root_ready": training_root_ready,
            "worker_ready": worker_ready,
            "worker_busy": worker_busy,
            "active_run_id": active_run_id,
        },
        "reasons": reasons,
    }


@router.get("/runs")
def list_training_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_training_admin),
    db: Session = Depends(get_db),
):
    """List training runs owned by the authenticated training administrator."""
    runs = (
        db.query(TrainingRun)
        .filter(TrainingRun.owner_id == current_user.id)
        .order_by(desc(TrainingRun.created_at))
        .limit(limit)
        .all()
    )
    items = []
    for run in runs:
        _reconcile_run(run, db)
        items.append(_run_response(run))
    return {"items": items}


@router.get("/runs/{run_id}", response_model=TrainingRunResponse)
def get_training_status(
    run_id: UUID,
    current_user: User = Depends(require_training_admin),
    db: Session = Depends(get_db),
):
    run = db.get(TrainingRun, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training run not found.",
        )
    _reconcile_run(run, db)
    return _run_response(run)


@router.get(
    "/runs/{run_id}/telemetry",
    response_model=TrainingTelemetryResponse,
)
def get_training_telemetry(
    run_id: UUID,
    current_user: User = Depends(require_training_admin),
    db: Session = Depends(get_db),
):
    run = db.get(TrainingRun, run_id)
    if run is None or run.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training run not found.",
        )
    _reconcile_run(run, db)

    training_root = Path(
        os.getenv("ZYRQUEN_TRAINING_ROOT", "/data/training")
    ).resolve()
    run_dir = (training_root / str(run.id)).resolve()
    if not run_dir.is_relative_to(training_root):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Training artifact path is invalid.",
        )

    try:
        metrics = _json_safe(
            TrainingMonitor(run_dir / "metrics.jsonl").history()
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Training metrics are unavailable.",
        ) from exc
    checkpoint_dir = run_dir / "checkpoints"
    manifest_path = checkpoint_dir / "manifest.json"
    checkpoints = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Checkpoint telemetry manifest is unreadable.",
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != CHECKPOINT_SCHEMA
            or not isinstance(manifest.get("checkpoints"), list)
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Checkpoint telemetry manifest has an unsupported format.",
            )
        manager = CheckpointManager(checkpoint_dir)
        for entry in manifest["checkpoints"]:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("step"), int)
                or isinstance(entry.get("step"), bool)
                or entry["step"] < 0
                or entry.get("file") != f"ckpt_{entry['step']:08d}.pt"
                or not isinstance(entry.get("size_bytes"), int)
                or entry["size_bytes"] < 0
                or not isinstance(entry.get("sha256"), str)
                or len(entry["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in entry["sha256"])
            ):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Checkpoint telemetry manifest contains an invalid entry.",
                )
            try:
                valid = manager.verify(entry)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Checkpoint telemetry could not be verified.",
                ) from exc
            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Checkpoint telemetry integrity verification failed.",
                )
            checkpoints.append(entry)

    return {
        "run_id": run.id,
        "status": run.status,
        "metrics": metrics,
        "checkpoints": checkpoints,
        "epochs_completed": None,
    }
