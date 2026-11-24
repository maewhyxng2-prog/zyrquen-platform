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
    ModelStageRequest,
    TriggerWorkflowRequest,
)
from apps.core.native.closure_audit import build_v10_closure_audit
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.runtime import runtime
from apps.core.workflow import (
    ApprovalViolationError,
    CentralWorkflowOrchestrator,
    WorkflowValidationError,
    create_default_orchestrator,
)
from apps.core.workflow.audit import redact_dict
from apps.core.workflow.governance_diagnostics import (
    approval_secret_fingerprint,
    inspect_workflow_db_readonly,
    workflow_db_path_fingerprint,
)

router = APIRouter(tags=["Workflows & Model Registry"])

_ENGINE: CentralWorkflowOrchestrator | None = None


def get_workflow_engine() -> CentralWorkflowOrchestrator:
    global _ENGINE
    if _ENGINE is None:
        v10d_enabled = os.getenv("ZYRQUEN_V10D_APPROVAL_ENABLED", "0").strip() == "1"
        if v10d_enabled:
            if not os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="V10-D approval requires an explicitly shared ZYRQUEN_WORKFLOW_DB_PATH.",
                )
            if not os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="V10-D approval requires a configured shared ZYRQUEN_APPROVAL_SECRET.",
                )
        _ENGINE = create_default_orchestrator()
        if v10d_enabled:
            # Register the exact closure workflow and its real handlers in the
            # authenticated API process so an admin decision can safely resume it.
            from tools.close_v10d import _register_v10d_closure_workflow

            _register_v10d_closure_workflow(_ENGINE)
    return _ENGINE



@router.get("/v1/workflows/governance/diagnostics")
def get_workflow_governance_diagnostics(
    _: User = Depends(require_admin),
):
    """Read-only live API/Runner governance comparison; never exposes the HMAC secret."""
    engine = get_workflow_engine()
    configured_db = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
    configured_secret = os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip()
    v10d_enabled = os.getenv("ZYRQUEN_V10D_APPROVAL_ENABLED", "0").strip() == "1"

    engine_db = Path(engine.store.db_path).expanduser().resolve(strict=False)
    configured_db_path = Path(configured_db).expanduser().resolve(strict=False) if configured_db else None
    db_matches = bool(configured_db_path and configured_db_path == engine_db)
    db_report = inspect_workflow_db_readonly(engine_db)

    workflow_registered = False
    required_handlers_registered = False
    workflow_contract: dict[str, object] = {}
    try:
        definition = engine.registry.get("training.v10d_closure_run", "1.0.0")
        workflow_registered = True
        steps = {step.step_key: step for step in definition.steps}
        training_step = steps.get("execute_v10d_training")
        audit_step = steps.get("v10_data_audit")
        workflow_contract = {
            "default_tier": definition.default_tier,
            "training_action_type": training_step.action_type if training_step else None,
            "training_tier": training_step.tier if training_step else None,
            "training_handler_key": training_step.handler_key if training_step else None,
            "audit_action_type": audit_step.action_type if audit_step else None,
            "audit_handler_key": audit_step.handler_key if audit_step else None,
        }
        engine.registry.get_handler("v10d.data_audit")
        engine.registry.get_handler("v10d.train_execute")
        required_handlers_registered = bool(
            training_step
            and audit_step
            and training_step.action_type == "training.execute"
            and training_step.tier == "tier2_approval"
            and training_step.handler_key == "v10d.train_execute"
            and audit_step.handler_key == "v10d.data_audit"
        )
    except Exception:
        workflow_registered = False
        required_handlers_registered = False

    service_status = engine.get_service_status()
    checks = {
        "v10d_approval_enabled": v10d_enabled,
        "shared_workflow_db_configured": bool(configured_db),
        "api_db_matches_configured_path": db_matches,
        "workflow_db_readable_and_schema_valid": bool(db_report.get("required_tables_present")),
        "shared_approval_secret_configured": bool(configured_secret),
        "workflow_definition_registered": workflow_registered,
        "required_handlers_registered": required_handlers_registered,
        "workflow_engine_started": bool(service_status.get("started")),
    }
    return {
        "schema": "zyrquen.v10d.live_governance_diagnostics.v1",
        "overall_status": "PASS" if all(checks.values()) else "BLOCKED",
        "read_only": True,
        "checks": checks,
        "api_process": {
            "pid": os.getpid(),
            "workflow_db_path_sha256": workflow_db_path_fingerprint(engine_db),
            "approval_secret_fingerprint": approval_secret_fingerprint(configured_secret),
            "workflow_db": db_report,
            "workflow_contract": workflow_contract,
            "service": service_status,
        },
    }


def _get_model_registry() -> tuple[ModelRegistry | None, str]:
    root = os.getenv("ZYRQUEN_MODEL_REGISTRY_ROOT", "").strip()
    if not root:
        return None, "ZYRQUEN_MODEL_REGISTRY_ROOT is not configured"
    path = Path(root)
    if not path.exists():
        return None, f"Model registry root does not exist: {path}"
    return ModelRegistry(path), str(path)


@router.get("/v1/v10/closure-audit")
def get_v10_closure_audit(
    _: User = Depends(get_current_user),
):
    """Return real-time V10 integration contract & closure gate verification status. Requires authentication."""
    return build_v10_closure_audit(runtime_health=runtime.get_health_status())


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
        approval = engine.store.get_approval(approval_id)
        if approval is None:
            raise ApprovalViolationError(f"Approval request not found: {approval_id}")
        run = engine.decide_approval_and_resume(
            approval_id,
            approve=body.approve,
            approver_user_id=str(current_user.id),
            approver_role=current_user.role,
            reason=body.reason,
            execute_async=bool(body.approve and approval.get("action_type") == "training.execute"),
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


_BASELINE_POLICY = {
    "v7": {"status": "Baseline", "note": "Preserved legacy baseline"},
    "v8": {"status": "CLOSED / FROZEN", "note": "Immutable frozen reference"},
    "v9": {"status": "Development", "note": "Experimental candidate track"},
}


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
            "registered_count": 0,
            "baseline_policy": _BASELINE_POLICY,
            "versions": [],
        }
    try:
        versions = registry.list_versions()
        enriched = []
        for rec in versions:
            compat = registry.check_compatibility(rec["version"])
            enriched.append({**rec, "compatibility": compat})
        return {
            "configured": True,
            "root": info,
            "active_version": registry.active_version(),
            "registered_count": len(enriched),
            "baseline_policy": _BASELINE_POLICY,
            "versions": enriched,
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


@router.get("/v1/models/registry/{version}/lineage")
def get_model_lineage(
    version: str,
    _: User = Depends(get_current_user),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    try:
        return {
            "record": registry.get(version),
            "lineage": registry.get_lineage(version),
            "compatibility": registry.check_compatibility(version),
        }
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/v1/models/registry/{version}/stage")
def stage_model_version(
    version: str,
    body: ModelStageRequest,
    current_user: User = Depends(require_admin),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    engine = get_workflow_engine()
    try:
        return engine.stage_model_with_approval(
            registry,
            version,
            approval_id=body.approval_id,
            actor_id=current_user.email,
            reason=body.reason,
        )
    except ApprovalViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier-2 stage approval rejected: {exc}",
        ) from exc
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/v1/models/registry/{version}/promote")
def promote_model_version(
    version: str,
    body: ModelPromoteRequest,
    current_user: User = Depends(require_admin),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    engine = get_workflow_engine()
    try:
        return engine.promote_model_with_approval(
            registry,
            version,
            approval_id=body.approval_id,
            actor_id=current_user.email,
        )
    except ApprovalViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier-2 promote approval rejected: {exc}",
        ) from exc
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/v1/models/registry/rollback")
def rollback_model_version(
    body: ModelRollbackRequest,
    current_user: User = Depends(require_admin),
):
    registry, info = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=info)
    engine = get_workflow_engine()
    try:
        return engine.rollback_model_with_approval(
            registry,
            to_version=body.to_version,
            approval_id=body.approval_id,
            actor_id=current_user.email,
        )
    except ApprovalViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier-2 rollback approval rejected: {exc}",
        ) from exc
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
