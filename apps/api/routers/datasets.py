"""Read-only Dataset Status API exposing verified manifest, split counts, and leakage checks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.models import User
from apps.api.security import get_current_user
from apps.core.native.dataset_status import (
    get_dataset_version_status,
    get_datasets_pipeline_status,
)

router = APIRouter(prefix="/v1/datasets", tags=["Datasets"])


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
