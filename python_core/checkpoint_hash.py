"""Utilities for automatically computing, saving, and verifying checkpoint SHA-256 hashes."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_sidecar_path(checkpoint_path: str | Path) -> Path:
    """Return the canonical `.sha256` sidecar path for a checkpoint file."""
    ckpt = Path(checkpoint_path)
    return Path(f"{ckpt}.sha256")


def compute_file_sha256(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """Stream-compute the lowercase hex SHA-256 digest for a file on disk."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Checkpoint file not found: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_sha256_hex(value: str) -> str:
    cleaned = value.strip()
    if not _SHA256_HEX_RE.match(cleaned):
        raise ValueError(f"Invalid SHA-256 hex digest: {value!r}")
    return cleaned.lower()


def save_checkpoint_sha256(
    checkpoint_path: str | Path,
    *,
    digest: str | None = None,
    sidecar_path: str | Path | None = None,
    include_filename: bool = False,
) -> tuple[Path, str]:
    """Compute (if needed) and atomically write a checkpoint's `.sha256` sidecar file."""
    ckpt = Path(checkpoint_path)
    if not ckpt.is_file():
        raise FileNotFoundError(f"Checkpoint file not found: {ckpt}")

    resolved_digest = (
        compute_file_sha256(ckpt)
        if digest is None
        else _normalize_sha256_hex(digest)
    )
    target = Path(sidecar_path) if sidecar_path is not None else sha256_sidecar_path(ckpt)
    target.parent.mkdir(parents=True, exist_ok=True)

    content = f"{resolved_digest}  {ckpt.name}\n" if include_filename else resolved_digest
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise

    return target, resolved_digest


def read_checkpoint_sha256(
    checkpoint_path: str | Path,
    *,
    sidecar_path: str | Path | None = None,
) -> str:
    """Read and validate the SHA-256 hex digest from a checkpoint's `.sha256` sidecar."""
    target = (
        Path(sidecar_path)
        if sidecar_path is not None
        else sha256_sidecar_path(checkpoint_path)
    )
    if not target.is_file():
        raise FileNotFoundError(f"SHA-256 sidecar file not found: {target}")
    raw = target.read_text(encoding="utf-8").strip()
    token = raw.split()[0] if raw else ""
    return _normalize_sha256_hex(token)


def verify_checkpoint_sha256(
    checkpoint_path: str | Path,
    *,
    expected_sha256: str | None = None,
    sidecar_path: str | Path | None = None,
) -> bool:
    """Verify a checkpoint file against an expected digest or its `.sha256` sidecar."""
    try:
        expected = (
            _normalize_sha256_hex(expected_sha256)
            if expected_sha256 is not None
            else read_checkpoint_sha256(checkpoint_path, sidecar_path=sidecar_path)
        )
        actual = compute_file_sha256(checkpoint_path)
    except (FileNotFoundError, ValueError, OSError):
        return False
    return hmac.compare_digest(actual, expected)


def save_checkpoint_with_sha256(
    checkpoint_path: str | Path,
    writer: Callable[[Path], Any],
    *,
    overwrite: bool = True,
    sidecar_path: str | Path | None = None,
    include_filename: bool = False,
) -> tuple[Path, Path, str]:
    """Run `writer(ckpt_path)` and immediately generate & save its `.sha256` sidecar."""
    ckpt = Path(checkpoint_path)
    if not overwrite and ckpt.exists():
        raise FileExistsError(f"Refusing to overwrite existing checkpoint: {ckpt}")
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    writer(ckpt)
    resolved_sidecar, digest = save_checkpoint_sha256(
        ckpt,
        sidecar_path=sidecar_path,
        include_filename=include_filename,
    )
    return ckpt, resolved_sidecar, digest
