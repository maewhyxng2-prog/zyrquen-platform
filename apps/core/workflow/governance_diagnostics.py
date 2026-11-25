"""Read-only diagnostics helpers for Workflow Governance DB and HMAC secret (pure stdlib)."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

REQUIRED_WORKFLOW_TABLES: tuple[str, ...] = (
    "workflow_definitions",
    "workflow_runs",
    "workflow_step_runs",
    "workflow_approvals",
    "workflow_audit_logs",
)


def workflow_db_path_fingerprint(db_path: str | Path) -> str:
    resolved = str(Path(db_path).expanduser().resolve(strict=False))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def approval_secret_fingerprint(secret: str) -> str | None:
    cleaned = str(secret or "").strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]


def inspect_workflow_db_readonly(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path).expanduser().resolve(strict=False)
    if not path.is_file():
        return {
            "exists": False,
            "readable": False,
            "required_tables_present": False,
            "tables": [],
            "pending_approvals": 0,
            "approved_approvals": 0,
        }
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            tables = sorted(
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            )
            has_all = all(t in tables for t in REQUIRED_WORKFLOW_TABLES)
            pending = 0
            approved = 0
            if "workflow_approvals" in tables:
                pending = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM workflow_approvals WHERE status='pending'"
                    ).fetchone()[0]
                )
                approved = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM workflow_approvals WHERE status='approved'"
                    ).fetchone()[0]
                )
            return {
                "exists": True,
                "readable": True,
                "required_tables_present": has_all,
                "tables": tables,
                "pending_approvals": pending,
                "approved_approvals": approved,
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "exists": True,
            "readable": False,
            "required_tables_present": False,
            "tables": [],
            "error": str(exc),
        }
