import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

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
from apps.core.native.dataset import verify_dataset_manifest
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
                engine.governance.verify_and_consume_by_id(
                    approval_id,
                    expected_action_type="training.execute",
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
    """Run a read-only preflight of native training inputs; never submits a training job."""
    dataset_env = os.getenv("ZYRQUEN_DATASET_DIR", "").strip()
    tokenizer_env = os.getenv("ZYRQUEN_TOKENIZER_PATH", "").strip()
    dataset_dir = jobs._orchestrator.dataset_dir or (Path(dataset_env).resolve() if dataset_env else None)
    tokenizer_path = jobs._orchestrator.tokenizer_path or (Path(tokenizer_env).resolve() if tokenizer_env else None)
    dataset_configured = bool(dataset_dir is not None and not dataset_dir.is_symlink() and dataset_dir.is_dir())
    tokenizer_configured = bool(tokenizer_path is not None and not tokenizer_path.is_symlink() and tokenizer_path.is_file())
    admins = training_admin_emails()
    admin_configured = bool(admins)
    is_training_admin = current_user.email.strip().lower() in admins

    dataset_integrity_verified = False
    preflight_passed = False
    dataset_version = None
    preflight_error = None

    if dataset_configured and tokenizer_configured:
        try:
            manifest = verify_dataset_manifest(dataset_dir)
            dataset_version = manifest.get("version")
            if not isinstance(dataset_version, str) or not dataset_version.strip():
                raise TrainingUnavailable("Dataset manifest has no valid version.")
            request = TrainingRunRequest(dataset_version=dataset_version)
            # prepare() validates the native tokenizer, dataset splits, CPU resource
            # bounds, and artifact-storage availability. It does not execute training.
            jobs._orchestrator.prepare(
                dataset_version=dataset_version,
                training_values=request.training.model_dump(),
                model_values=request.model.model_dump(),
            )
            dataset_integrity_verified = True
            preflight_passed = True
        except (TrainingUnavailable, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            preflight_error = str(exc)

    configured = dataset_configured and tokenizer_configured and admin_configured and preflight_passed
    active_run_id = str(jobs._active_run_id) if jobs._future is not None and not jobs._future.done() and jobs._active_run_id else None
    return {
        "configured": configured,
        "status": "ready" if configured else "not_configured",
        "dataset_configured": dataset_configured,
        "dataset_integrity_verified": dataset_integrity_verified,
        "dataset_version": dataset_version,
        "tokenizer_configured": tokenizer_configured,
        "admin_allowlist_configured": admin_configured,
        "is_training_admin": is_training_admin,
        "training_preflight_passed": preflight_passed,
        "preflight_error": preflight_error,
        "tier2_approval_required": True,
        "active_run_id": active_run_id,
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
