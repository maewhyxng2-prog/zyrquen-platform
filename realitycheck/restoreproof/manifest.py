from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_BACKUP_BYTES = 20 * 1024 * 1024 * 1024


class VerificationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path, backup: Path) -> dict:
    if not path.is_file():
        raise VerificationError("MANIFEST_MISSING", "Digest manifest is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise VerificationError("MANIFEST_INVALID", "Digest manifest is invalid") from None
    if not isinstance(data, dict):
        raise VerificationError("MANIFEST_INVALID", "Digest manifest must be an object")
    if data.get("schema") != "realitycheck.restoreproof.manifest.v1":
        raise VerificationError("MANIFEST_SCHEMA_UNSUPPORTED", "Manifest schema is unsupported")
    if data.get("filename") != backup.name:
        raise VerificationError("MANIFEST_FILENAME_MISMATCH", "Manifest filename does not match backup")
    digest = data.get("sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest.lower()):
        raise VerificationError("MANIFEST_DIGEST_INVALID", "Manifest SHA-256 is invalid")
    size = data.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise VerificationError("MANIFEST_SIZE_INVALID", "Manifest size is invalid")
    return {"sha256": digest.lower(), "size_bytes": size}


def verify_artifact(backup: Path, manifest_path: Path) -> dict:
    if not backup.is_file() or backup.is_symlink():
        raise VerificationError("BACKUP_MISSING_OR_UNSAFE", "Backup must be a regular non-symlink file")
    resolved = backup.resolve(strict=True)
    size = resolved.stat().st_size
    if size < 1 or size > MAX_BACKUP_BYTES:
        raise VerificationError("BACKUP_SIZE_OUT_OF_RANGE", "Backup size is outside configured limits")
    manifest = load_manifest(manifest_path, resolved)
    if size != manifest["size_bytes"]:
        raise VerificationError("BACKUP_SIZE_MISMATCH", "Backup size does not match manifest")
    actual = sha256_file(resolved)
    if actual != manifest["sha256"]:
        raise VerificationError("BACKUP_DIGEST_MISMATCH", "Backup SHA-256 does not match manifest")
    with resolved.open("rb") as stream:
        signature = stream.read(5)
    if signature != b"PGDMP":
        raise VerificationError("UNSUPPORTED_DUMP_FORMAT", "Input is not a PostgreSQL custom-format dump")
    return {"path": resolved, "size_bytes": size, "sha256": actual}
