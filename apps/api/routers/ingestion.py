"""Raw Data Ingestion API router with DatasetLeakageDetector validation and verified training dataset mapping."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from apps.api.models import User
from apps.api.routers.workflows import get_workflow_engine
from apps.api.security import get_current_user
from apps.api.training_jobs import training_admin_emails
from apps.core.dataset_leakage_detector import SemanticHashLeakageError
from apps.core.native.dataset_status import validate_dataset_version
from apps.core.native.dataset_v11 import DatasetLeakageError
from apps.core.native.ingestion import (
    MAX_RAW_UPLOAD_BYTES,
    IngestionPayloadTooLargeError,
    RawIngestionError,
    get_dataset_training_mapping,
    ingest_raw_dataset_upload,
    validate_raw_ingestion,
)
from apps.core.workflow import ApprovalViolationError

router = APIRouter(prefix="/v1/ingestion", tags=["Ingestion"])


class RawValidationRequest(BaseModel):
    raw_content: str | None = Field(default=None)
    entries: list[Any] | None = Field(default=None)
    format: Literal["auto", "jsonl", "json", "csv", "text"] = "auto"
    redact_pii: bool = True
    split_ratios: dict[str, float] | None = None


class RawIngestionUploadRequest(BaseModel):
    dataset_version: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=120)
    license: str = Field(min_length=1, max_length=120)
    provenance: str = Field(min_length=1, max_length=200)
    raw_content: str | None = Field(default=None)
    entries: list[Any] | None = Field(default=None)
    format: Literal["auto", "jsonl", "json", "csv", "text"] = "auto"
    redact_pii: bool = True
    split_ratios: dict[str, float] | None = None
    approval_id: str | None = Field(default=None, max_length=128)
    approval_ticket: str | None = Field(default=None, max_length=128)


def _require_ingestion_admin(current_user: User = Depends(get_current_user)) -> User:
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


@router.post("/validate")
def validate_raw_upload(
    payload: RawValidationRequest,
    _: User = Depends(_require_ingestion_admin),
):
    """Run pre-ingestion parsing, deterministic 4-split mapping preview, and DatasetLeakageDetector checks."""
    try:
        report = validate_raw_ingestion(
            raw_content=payload.raw_content,
            entries=payload.entries,
            fmt=payload.format,
            do_redact_pii=payload.redact_pii,
            split_ratios=payload.split_ratios,
        )
        return {
            "valid": report["valid"],
            "detected_format": report["detected_format"],
            "parsed_records": report["parsed_records"],
            "split_counts": report["split_counts"],
            "leakage_report": report["leakage_report"],
        }
    except IngestionPayloadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except RawIngestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_and_ingest_raw_data(
    payload: RawIngestionUploadRequest,
    _: User = Depends(_require_ingestion_admin),
):
    """Upload raw records/content, validate against DatasetLeakageDetector, and map to a verified training dataset version."""
    ticket = (payload.approval_id or payload.approval_ticket or "").strip()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier-2 workflow Approval Gate ticket (approval_id) is required before ingestion.",
        )

    engine = get_workflow_engine()
    try:
        return ingest_raw_dataset_upload(
            dataset_version=payload.dataset_version,
            source_name=payload.source_name,
            license_str=payload.license,
            provenance=payload.provenance,
            raw_content=payload.raw_content,
            entries=payload.entries,
            fmt=payload.format,
            do_redact_pii=payload.redact_pii,
            split_ratios=payload.split_ratios,
            approval_id=ticket,
            workflow_engine=engine,
            require_approval=True,
        )
    except ApprovalViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier-2 ingestion approval rejected: {exc}",
        ) from exc
    except IngestionPayloadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (SemanticHashLeakageError, DatasetLeakageError, RawIngestionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post("/raw", status_code=status.HTTP_201_CREATED)
async def upload_raw_stream(
    request: Request,
    dataset_version: str = Query(..., min_length=1, max_length=64),
    source_name: str = Query(..., min_length=1, max_length=120),
    license: str = Query(..., min_length=1, max_length=120),
    provenance: str = Query(..., min_length=1, max_length=200),
    approval_id: str | None = Query(default=None, max_length=128),
    format: Literal["auto", "jsonl", "json", "csv", "text"] = Query(default="auto"),
    redact_pii: bool = Query(default=True),
    _: User = Depends(_require_ingestion_admin),
):
    """Ingest a raw UTF-8 text/JSONL/CSV request body directly without multipart form dependencies."""
    ticket = (approval_id or "").strip()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier-2 workflow Approval Gate ticket (approval_id) is required before ingestion.",
        )

    raw_bytes = await request.body()
    if len(raw_bytes) > MAX_RAW_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Raw upload size ({len(raw_bytes)} bytes) exceeds limit ({MAX_RAW_UPLOAD_BYTES} bytes).",
        )

    engine = get_workflow_engine()
    try:
        return ingest_raw_dataset_upload(
            dataset_version=dataset_version,
            source_name=source_name,
            license_str=license,
            provenance=provenance,
            raw_content=raw_bytes,
            fmt=format,
            do_redact_pii=redact_pii,
            approval_id=ticket,
            workflow_engine=engine,
            require_approval=True,
        )
    except ApprovalViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier-2 ingestion approval rejected: {exc}",
        ) from exc
    except IngestionPayloadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (SemanticHashLeakageError, DatasetLeakageError, RawIngestionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/versions/{dataset_version}/mapping")
def get_version_training_mapping(
    dataset_version: str,
    _: User = Depends(get_current_user),
):
    """Inspect a dataset version's verified manifest and V11 training pipeline mapping."""
    try:
        validate_dataset_version(dataset_version)
        return get_dataset_training_mapping(dataset_version)
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
