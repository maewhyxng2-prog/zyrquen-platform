"""FastAPI routers exposing Central Native Workflow Engine and Model Registry Lifecycle APIs."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.models import User
from apps.api.routers.admin import require_admin
from apps.api.security import get_current_user
from apps.api.workflow_schemas import (
    ApprovalDecisionRequest,
    ModelPromoteRequest,
    ModelRollbackRequest,
    TriggerWorkflowRequest,
)
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.workflow import (
    ApprovalViolationError,
    CentralWorkflowOrchestrator,
    WorkflowValidationError,
    create_default_orchestrator,
)
from apps.core.workflow.audit import redact_dict

router = APIRouter(tags=["Workflows & Model Registry"])

_ENGINE: CentralWorkflowOrchestrator | None = None


def get_workflow_engine() -> CentralWorkflowOrchestrator:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_default_orchestrator()
    return _ENGINE


def _get_model_registry() -> tuple[ModelRegistry | None, str]:
    root = os.getenv("ZYRQUEN_MODEL_REGISTRY_ROOT", "").strip()
    if not root:
        return None, "ZYRQUEN_MODEL_REGISTRY_ROOT is not configured"
    path = Path(root)
    if not path.exists():
        return None, f"Model registry root does not exist: {path}"
    return ModelRegistry(path), str(path)


@router.get("/v1/workflows/definitions")
def list_workflow_definitions(
    group_name: str | None = Query(default=None),
    _: User = Depends(get_current_user),
):
    engine = get_workflow_engine()
    items = engine.registry.list_definitions(group_name=group_name)
    return {
        "items": [
            {
                "workflow_key": d.workflow_key,
                "version": d.version,
                "group_name": d.group_name,
                "title": d.title,
                "description": d.description,
                "default_tier": d.default_tier,
                "schedule_interval_sec": d.schedule_interval_sec,
                "event_triggers": list(d.event_triggers),
                "steps": [s.to_dict() for s in d.steps],
            }
            for d in items
        ],
        "scheduler_active": engine.scheduler.is_running(),
    }


@router.get("/v1/workflows/runs")
def list_workflow_runs(
    status_filter: str | None = Query(default=None, alias="status"),
    workflow_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(get_current_user),
):
    engine = get_workflow_engine()
    runs = engine.store.list_runs(status=status_filter, workflow_key=workflow_key, limit=limit)
    return {"items": redact_dict(runs)}


@router.get("/v1/workflows/runs/{run_id}")
def get_workflow_run(
    run_id: str,
    _: User = Depends(get_current_user),
):
    engine = get_workflow_engine()
    run = engine.store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
    return redact_dict(run)


@router.post("/v1/workflows/runs", status_code=status.HTTP_202_ACCEPTED)
def trigger_workflow_run(
    body: TriggerWorkflowRequest,
    current_user: User = Depends(get_current_user),
):
    engine = get_workflow_engine()
    try:
        run = engine.trigger_workflow(
            body.workflow_key,
            version=body.version,
            trigger_type="manual",
            payload=body.payload,
            requested_by_user_id=str(current_user.id),
            actor_id=current_user.email,
            dedup_key=body.dedup_key,
            execute_async=body.execute_async,
        )
        return redact_dict(run)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/v1/workflows/runs/{run_id}/cancel")
def cancel_workflow_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    engine = get_workflow_engine()
    existing = engine.store.get_run(run_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
    if current_user.role != "admin" and existing.get("requested_by_user_id") != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    cancelled = engine.cancel_run(run_id, actor_id=current_user.email)
    return redact_dict(cancelled)


@router.get("/v1/workflows/approvals")
def list_workflow_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_admin),
):
    engine = get_workflow_engine()
    items = engine.store.list_approvals(status=status_filter, limit=limit)
    # Never expose internal HMAC signature over REST responses
    sanitized = [{k: v for k, v in item.items() if k != "signature_hmac"} for item in items]
    return {"items": sanitized}


@router.post("/v1/workflows/approvals/{approval_id}/decision")
def decide_workflow_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    current_user: User = Depends(require_admin),
):
    engine = get_workflow_engine()
    try:
        run = engine.decide_approval_and_resume(
            approval_id,
            approve=body.approve,
            approver_user_id=str(current_user.id),
            approver_role=current_user.role,
            reason=body.reason,
        )
        return redact_dict(run)
    except ApprovalViolationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/v1/workflows/audit-logs")
def list_workflow_audit_logs(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(require_admin),
):
    engine = get_workflow_engine()
    return {"items": redact_dict(engine.store.list_audit_logs(run_id=run_id, limit=limit))}


@router.get("/v1/models/registry")
def list_model_registry(
    _: User = Depends(get_current_user),
):
    registry, info = _get_model_registry()
    if registry is None:
        return {
            "configured": False,
            "detail": info,
            "active_version": None,
            "versions": [],
        }
    try:
        return {
            "configured": True,
            "root": info,
            "active_version": registry.active_version(),
            "versions": registry.list_versions(),
        }
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/v1/models/registry/compare")
def compare_model_versions(
    base: str = Query(..., min_length=1, max_length=64),
    candidate: str = Query(..., min_length=1, max_length=64),
    _: User = Depends(get_current_user),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    try:
        return registry.compare_versions(base, candidate)
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/v1/models/registry/{version}/promote")
def promote_model_version(
    version: str,
    body: ModelPromoteRequest,
    current_user: User = Depends(require_admin),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    if not body.approval_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier-2 approval_id is required to promote a model version.",
        )
    try:
        registry.promote(
            version,
            enforce_evaluation_gate=True,
            approval_id=body.approval_id,
            approved_by=current_user.email,
        )
        return {
            "status": "promoted",
            "active_version": registry.active_version(),
            "record": registry.get(version),
        }
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/v1/models/registry/rollback")
def rollback_model_version(
    body: ModelRollbackRequest,
    _: User = Depends(require_admin),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    if not body.approval_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier-2 approval_id is required to rollback a production model version.",
        )
    try:
        target = registry.rollback(body.to_version, approval_id=body.approval_id)
        return {
            "status": "rolled_back",
            "active_version": target,
            "record": registry.get(target),
        }
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
