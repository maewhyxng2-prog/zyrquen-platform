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


def approval_secret_fingerprint(secret: str) -> str:
    cleaned = str(secret or "").strip()
    if not cleaned:
        return ""
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def inspect_workflow_db_readonly(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path).expanduser().resolve(strict=False)
    if not path.exists() or not path.is_file():
        return {
            "exists": path.exists(),
            "is_file": False,
            "readable": False,
            "read_only": True,
            "required_tables_present": False,
            "tables": [],
            "missing_tables": list(REQUIRED_WORKFLOW_TABLES),
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
            missing_tables = [t for t in REQUIRED_WORKFLOW_TABLES if t not in tables]
            has_all = len(missing_tables) == 0
            pending = 0
            approved = 0
            if "workflow_approvals" in tables:
                cols = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(workflow_approvals)").fetchall()
                }
                if "status" in cols:
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
                "is_file": True,
                "readable": True,
                "read_only": True,
                "required_tables_present": has_all,
                "tables": tables,
                "missing_tables": missing_tables,
                "pending_approvals": pending,
                "approved_approvals": approved,
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "exists": True,
            "is_file": True,
            "readable": False,
            "read_only": True,
            "required_tables_present": False,
            "tables": [],
            "missing_tables": list(REQUIRED_WORKFLOW_TABLES),
            "error": str(exc),
        }
