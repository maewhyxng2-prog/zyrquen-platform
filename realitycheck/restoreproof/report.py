from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

SCHEMA = "realitycheck.restoreproof.evidence.v1"
VALID = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_report(run_id: str, started_at: str, artifact: dict | None,
                 checks: list[dict], verdict: str, reasons: list[str],
                 cleanup: dict, tool_version: str = "0.1.0") -> dict:
    if verdict not in VALID:
        raise ValueError("Invalid verdict")
    # PASS requires every required check to have an explicit PASS and cleanup success.
    if verdict == "PASS":
        if not checks or any(c.get("status") != "PASS" for c in checks):
            verdict = "BLOCKED"
            reasons = [*reasons, "PASS requires all checks to pass"]
        if cleanup.get("status") != "PASS":
            verdict = "BLOCKED"
            reasons = [*reasons, "Cleanup did not complete successfully"]
        if artifact is None:
            verdict = "BLOCKED"
            reasons = [*reasons, "Artifact evidence is missing"]
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "tool_version": tool_version,
        "started_at": started_at,
        "finished_at": utc_now(),
        "artifact": ({
            "filename": Path(artifact["path"]).name,
            "size_bytes": artifact["size_bytes"],
            "sha256_before": artifact["sha256"],
            "sha256_after": artifact.get("sha256_after"),
        } if artifact else None),
        "checks": checks,
        "cleanup": cleanup,
        "verdict": verdict,
        "reasons": sorted(set(reasons)),
    }


def write_report(report: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
