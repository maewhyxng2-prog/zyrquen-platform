"""Read-only Dataset API for inspecting the configured native dataset artifact."""
import os
from pathlib import Path
from fastapi import APIRouter, Depends
from apps.api.models import User
from apps.api.security import get_current_user
from apps.core.native.dataset import SCHEMA, verify_dataset_manifest

router = APIRouter(prefix="/v1/datasets", tags=["Datasets"])

@router.get("/status")
def get_dataset_status(_: User = Depends(get_current_user)):
    """Return verified dataset metadata without exposing paths or document text."""
    configured_path = os.getenv("ZYRQUEN_DATASET_DIR", "").strip()
    if not configured_path:
        return {"configured": False, "available": False, "valid": False,
                "status": "not_configured", "schema": None, "version": None,
                "content_sha256": None, "splits": {},
                "detail": "ZYRQUEN_DATASET_DIR is not configured."}
    candidate = Path(configured_path).expanduser()
    if candidate.is_symlink():
        return {"configured": True, "available": False, "valid": False,
                "status": "unavailable_or_invalid", "schema": None, "version": None,
                "content_sha256": None, "splits": {},
                "detail": "Dataset manifest or split integrity validation failed."}
    try:
        dataset_dir = candidate.resolve(strict=True)
        if not dataset_dir.is_dir():
            raise ValueError("Dataset path is not a directory.")
        manifest = verify_dataset_manifest(dataset_dir)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        return {"configured": True, "available": False, "valid": False,
                "status": "unavailable_or_invalid", "schema": None, "version": None,
                "content_sha256": None, "splits": {},
                "detail": "Dataset manifest or split integrity validation failed."}
    files = manifest.get("files")
    if not isinstance(files, dict):
        files = {}
    splits = {}
    for split_name, entry in files.items():
        if isinstance(entry, dict):
            count = entry.get("documents")
            splits[split_name] = {
                "documents": count if isinstance(count, int) and not isinstance(count, bool) else None,
                "sha256": entry.get("sha256") if isinstance(entry.get("sha256"), str) else None,
            }
    return {"configured": True, "available": True, "valid": True,
            "status": "ready", "schema": SCHEMA, "version": manifest.get("version"),
            "content_sha256": manifest.get("content_sha256"), "splits": splits,
            "detail": "Dataset manifest and split integrity checks passed."}
