"""Read-only diagnostics for cross-process V10-D workflow governance."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import quote
from typing import Any


REQUIRED_WORKFLOW_TABLES = frozenset(
    {
        "workflow_definitions",
        "workflow_runs",
        "workflow_step_runs",
        "workflow_approvals",
        "workflow_audit_logs",
    }
)


def approval_secret_fingerprint(secret: str) -> str:
    """Return a comparison fingerprint; never return or log the configured secret."""
    if not isinstance(secret, str) or not secret.strip():
        return ""
    return hashlib.sha256(secret.strip().encode("utf-8")).hexdigest()


def workflow_db_path_fingerprint(path: str | Path) -> str:
    """Fingerprint the canonical absolute path without disclosing the path itself."""
    canonical = Path(path).expanduser().resolve(strict=False)
    return hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()


def inspect_workflow_db_readonly(path: str | Path) -> dict[str, Any]:
    """Inspect required SQLite tables using a read-only connection; never initialize schema."""
    candidate = Path(path).expanduser()
    try:
        canonical = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return {
            "exists": False,
            "is_file": False,
            "required_tables_present": False,
            "missing_tables": sorted(REQUIRED_WORKFLOW_TABLES),
            "error": type(exc).__name__,
        }

    if not canonical.is_file():
        return {
            "exists": True,
            "is_file": False,
            "required_tables_present": False,
            "missing_tables": sorted(REQUIRED_WORKFLOW_TABLES),
            "error": "NOT_A_FILE",
        }

    stat = canonical.stat()
    file_identity = {"device": int(stat.st_dev), "inode": int(stat.st_ino)}
    uri = f"file:{quote(str(canonical), safe='/')}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            present = {str(row[0]) for row in rows}
            missing = sorted(REQUIRED_WORKFLOW_TABLES - present)
            return {
                "exists": True,
                "is_file": True,
                "required_tables_present": not missing,
                "missing_tables": missing,
                "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
                "file_identity": file_identity,
                "read_only": True,
            }
    except sqlite3.Error as exc:
        return {
            "exists": True,
            "is_file": True,
            "required_tables_present": False,
            "missing_tables": sorted(REQUIRED_WORKFLOW_TABLES),
            "error": type(exc).__name__,
            "read_only": True,
        }
