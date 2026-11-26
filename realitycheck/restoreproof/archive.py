from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile
from typing import Iterator

from .manifest import VerificationError, sha256_file

MAX_ARCHIVE_BYTES = 20 * 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 40 * 1024 * 1024 * 1024
MAX_MEMBERS = 100_000
MAX_COMPRESSION_RATIO = 200


def _safe_member(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name:
        raise VerificationError("ZIP_MEMBER_PATH_INVALID", "Archive member path is invalid")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise VerificationError("ZIP_SLIP_BLOCKED", "Archive contains an unsafe path")
    if path.parts and ":" in path.parts[0]:
        raise VerificationError("ZIP_SLIP_BLOCKED", "Archive contains an unsafe path")
    return path


@contextmanager
def isolated_zip_extract(archive: Path, temporary_root: Path, expected_sha256: str,
                         *, max_archive_bytes: int = MAX_ARCHIVE_BYTES,
                         max_extracted_bytes: int = MAX_EXTRACTED_BYTES,
                         max_members: int = MAX_MEMBERS) -> Iterator[dict]:
    """Digest-check and safely extract a ZIP in a private temporary workspace."""
    if not archive.is_file() or archive.is_symlink():
        raise VerificationError("ZIP_ARCHIVE_UNSAFE", "Archive must be a regular non-symlink file")
    archive = archive.resolve(strict=True)
    size = archive.stat().st_size
    if size < 1 or size > max_archive_bytes:
        raise VerificationError("ZIP_ARCHIVE_SIZE_INVALID", "Archive size is outside configured limits")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise VerificationError("ZIP_EXPECTED_DIGEST_INVALID", "Expected SHA-256 is required")
    before = sha256_file(archive)
    if before != expected_sha256.lower():
        raise VerificationError("ZIP_DIGEST_MISMATCH", "Archive SHA-256 does not match manifest")

    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="restoreproof-", dir=temporary_root) as name:
        workspace = Path(name).resolve(strict=True)
        total = 0
        seen: set[str] = set()
        try:
            with zipfile.ZipFile(archive, "r") as zipped:
                infos = zipped.infolist()
                if not infos or len(infos) > max_members:
                    raise VerificationError("ZIP_MEMBER_COUNT_INVALID", "Archive member count is outside limits")
                for info in infos:
                    relative = _safe_member(info.filename)
                    key = relative.as_posix().rstrip("/")
                    if key in seen:
                        raise VerificationError("ZIP_DUPLICATE_PATH", "Archive contains duplicate paths")
                    seen.add(key)
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode):
                        raise VerificationError("ZIP_SYMLINK_BLOCKED", "Archive symlinks are not permitted")
                    if info.flag_bits & 1:
                        raise VerificationError("ZIP_ENCRYPTED_MEMBER", "Encrypted members are not permitted")
                    total += info.file_size
                    if info.file_size < 0 or total > max_extracted_bytes:
                        raise VerificationError("ZIP_EXPANSION_LIMIT", "Archive expansion limit exceeded")
                    if info.file_size and (info.compress_size == 0 or
                                           info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                        raise VerificationError("ZIP_COMPRESSION_RATIO_LIMIT", "Archive compression ratio exceeded")
                    target = workspace.joinpath(*relative.parts)
                    if not target.parent.resolve().is_relative_to(workspace):
                        raise VerificationError("ZIP_SLIP_BLOCKED", "Archive member escaped workspace")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() or target.is_symlink():
                        raise VerificationError("ZIP_DUPLICATE_PATH", "Archive member collides with an existing path")
                    written = 0
                    digest = hashlib.sha256()
                    with zipped.open(info, "r") as source, target.open("xb") as output:
                        while chunk := source.read(1024 * 1024):
                            written += len(chunk)
                            if written > info.file_size or written > max_extracted_bytes:
                                raise VerificationError("ZIP_MEMBER_SIZE_MISMATCH", "Member exceeded declared size")
                            digest.update(chunk)
                            output.write(chunk)
                    if written != info.file_size:
                        raise VerificationError("ZIP_MEMBER_SIZE_MISMATCH", "Member size did not match metadata")
            after = sha256_file(archive)
            if after != before:
                raise VerificationError("ZIP_SYNC_DRIFT", "Source archive changed during extraction")
            yield {"workspace": workspace, "archive_sha256_before": before,
                   "archive_sha256_after": after, "extracted_files": sorted(
                       p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file()),
                   "extracted_bytes": total, "member_count": len(seen)}
        except (zipfile.BadZipFile, OSError, RuntimeError):
            raise VerificationError("ZIP_EXTRACTION_FAILED", "Archive extraction failed closed") from None
