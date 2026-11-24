#!/usr/bin/env python3
"""Compare live API and runner V10-D governance configuration without mutations."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.workflow.governance_diagnostics import (
    approval_secret_fingerprint,
    inspect_workflow_db_readonly,
    workflow_db_path_fingerprint,
)


def _fetch_api_diagnostics(base_url: str, token: str) -> dict:
    url = base_url.rstrip("/") + "/v1/workflows/governance/diagnostics"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Cache-Control": "no-store",
        },
        method="GET",
    )
    with urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"API returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("API diagnostics response is not an object")
    return payload


def run() -> int:
    db_value = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
    secret = os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip()
    api_url = os.getenv("ZYRQUEN_API_BASE_URL", "http://127.0.0.1:8000").strip()
    token = os.getenv("ZYRQUEN_ADMIN_BEARER_TOKEN", "").strip()

    checks: dict[str, bool] = {
        "runner_shared_db_configured": bool(db_value),
        "runner_shared_secret_configured": bool(secret),
        "admin_api_url_configured": bool(api_url),
        "admin_bearer_token_configured": bool(token),
    }
    output: dict = {
        "schema": "zyrquen.v10d.runner_governance_verification.v1",
        "read_only": True,
        "runner_process": {"pid": os.getpid()},
        "checks": checks,
    }

    if not db_value or not secret:
        output["overall_status"] = "BLOCKED"
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 3

    db_path = Path(db_value).expanduser().resolve(strict=False)
    local_db = inspect_workflow_db_readonly(db_path)
    local_path_fp = workflow_db_path_fingerprint(db_path)
    local_secret_fp = approval_secret_fingerprint(secret)
    checks["runner_workflow_db_readable_and_schema_valid"] = bool(
        local_db.get("required_tables_present")
    )
    output["runner_process"].update(
        {
            "workflow_db_path_sha256": local_path_fp,
            "approval_secret_fingerprint": local_secret_fp,
            "workflow_db": local_db,
        }
    )

    if not api_url or not token:
        output["overall_status"] = "BLOCKED"
        output["reason"] = "Set ZYRQUEN_API_BASE_URL and ZYRQUEN_ADMIN_BEARER_TOKEN in the runner environment."
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 3

    try:
        api = _fetch_api_diagnostics(api_url, token)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        output["overall_status"] = "BLOCKED"
        output["api_error"] = type(exc).__name__
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 3

    api_process = api.get("api_process") if isinstance(api.get("api_process"), dict) else {}
    api_checks = api.get("checks") if isinstance(api.get("checks"), dict) else {}
    checks["api_governance_checks_pass"] = (
        api.get("overall_status") == "PASS"
        and bool(api_checks)
        and all(value is True for value in api_checks.values())
    )
    checks["api_runner_db_path_fingerprint_match"] = (
        bool(local_path_fp)
        and local_path_fp == api_process.get("workflow_db_path_sha256")
    )
    checks["api_runner_secret_fingerprint_match"] = (
        bool(local_secret_fp)
        and local_secret_fp == api_process.get("approval_secret_fingerprint")
    )
    output["api_process"] = {
        "pid": api_process.get("pid"),
        "workflow_db_path_sha256": api_process.get("workflow_db_path_sha256"),
        "approval_secret_fingerprint": api_process.get("approval_secret_fingerprint"),
        "overall_status": api.get("overall_status"),
        "checks": api_checks,
        "workflow_contract": api_process.get("workflow_contract"),
    }
    output["overall_status"] = "PASS" if all(checks.values()) else "BLOCKED"
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output["overall_status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(run())
