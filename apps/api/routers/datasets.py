"""Dataset Status & Fail-Closed V11 Ingest API exposing manifest integrity, split counts, and leakage checks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.models import User
from apps.api.routers.workflows import get_workflow_engine
from apps.api.security import get_current_user
from apps.api.training_jobs import training_admin_emails
from apps.core.native.dataset_status import (
    get_dataset_version_status,
    get_datasets_pipeline_status,
    ingest_v11_dataset,
    verify_dataset_approval_ticket,
)
from apps.core.native.dataset_v11 import DatasetLeakageError
from apps.core.workflow import ApprovalViolationError

router = APIRouter(prefix="/v1/datasets", tags=["Datasets"])


class DatasetIngestRequest(BaseModel):
    dataset_version: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=120)
    license: str = Field(min_length=1, max_length=120)
    provenance: str = Field(min_length=1, max_length=200)
    redact_pii: bool = True
    approval_id: str | None = Field(default=None, max_length=128)
    approval_ticket: str | None = Field(default=None, max_length=128)
    splits: dict[str, list[dict[str, Any]]]


def _require_dataset_admin(current_user: User = Depends(get_current_user)) -> User:
    admins = training_admin_emails()
    if not admins:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Training admin allowlist is not configured.",
        )
    if current_user.email.strip().lower() not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dataset ingestion requires training administrator access.",
        )
    return current_user


@router.get("/status")
def datasets_pipeline_status(
    _: User = Depends(get_current_user),
):
    """Return read-only Dataset Pipeline readiness, active manifest integrity, and version summary."""
    return get_datasets_pipeline_status()


@router.get("/{dataset_version}/status")
def dataset_version_status(
    dataset_version: str,
    _: User = Depends(get_current_user),
):
    """Verify and return status for a specific dataset version under configured dataset storage."""
    try:
        return get_dataset_version_status(dataset_version)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
def ingest_dataset_version(
    payload: DatasetIngestRequest,
    _: User = Depends(_require_dataset_admin),
):
    """Ingest a 4-split V11 dataset with required Approval Gate ticket, provenance/license, SHA-256 manifest, and leakage gate."""
    ticket = (payload.approval_id or payload.approval_ticket or "").strip()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier-2 workflow Approval Gate ticket (approval_id) is required before marking a dataset as 'ready'.",
        )

    engine = get_workflow_engine()
    try:
        verify_dataset_approval_ticket(
            engine,
            ticket,
            dataset_version=payload.dataset_version,
        )
        return ingest_v11_dataset(
            dataset_version=payload.dataset_version,
            splits=payload.splits,
            source_name=payload.source_name,
            license_str=payload.license,
            provenance=payload.provenance,
            do_redact_pii=payload.redact_pii,
            approval_id=ticket,
            workflow_engine=engine,
            require_approval=True,
        )
    except ApprovalViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier-2 dataset ingestion approval rejected: {exc}",
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (DatasetLeakageError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


