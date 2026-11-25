"""
API & Integration Toolkit for ZYRQUEN Tool Center.
Provides API contract validation, internal Express/Python/SQLite service health integration,
and P5-gated webhook validation/dispatch (strict SSRF + external AI host protection).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from apps.core.intelligence.research import validate_research_url
import tools_engine as te

from ..contracts import CapabilitySpec, ToolkitManifest


def _handle_api_contract_validate(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    method = str(payload.get("method") or "GET").strip().upper()
    endpoint = str(payload.get("endpoint") or "").strip()
    required_fields = payload.get("required_fields") or []
    sample_body = payload.get("sample_body")

    problems: list[str] = []
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        problems.append(f"Unsupported HTTP method '{method}'.")
    if not endpoint.startswith("/api/"):
        problems.append("Internal API endpoint path must start with '/api/'.")
    if not isinstance(required_fields, list):
        problems.append("required_fields must be an array of field names.")
        required_fields = []

    if method in {"POST", "PUT", "PATCH"} and required_fields:
        if not isinstance(sample_body, dict):
            problems.append("sample_body must be a JSON object when required_fields are specified.")
        else:
            for field_name in required_fields:
                key = str(field_name)
                val = sample_body.get(key)
                if val is None or (isinstance(val, str) and not val.strip()):
                    problems.append(f"Missing or empty required body field '{key}'.")

    valid = len(problems) == 0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "valid": valid,
            "method": method,
            "endpoint": endpoint,
            "problems": problems,
        },
        "summary": (
            f"สัญญา API {method} {endpoint} ถูกต้องครบถ้วน"
            if valid
            else f"สัญญา API {method} {endpoint} พบข้อผิดพลาด {len(problems)} รายการ"
        ),
    }


def _handle_internal_health(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn: sqlite3.Connection | None = ctx.get("conn")
    data_dir: Path = ctx["data_dir"]
    registry = ctx["registry"]

    db_ok = False
    tables_count = 0
    if conn is not None:
        try:
            row = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()
            tables_count = int(row[0])
            db_ok = True
        except Exception:
            db_ok = False

    toolkits = registry.list_toolkits(user_role=ctx.get("user_role") or "user")
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "service_status": "ready" if db_ok else "degraded",
            "python_version": sys.version.split()[0],
            "sqlite_connected": db_ok,
            "sqlite_table_count": tables_count,
            "data_dir_exists": data_dir.exists(),
            "registered_toolkits": len(toolkits),
            "external_models_used": False,
        },
        "summary": (
            f"เชื่อมต่อบริการภายในปกติ (Python {sys.version.split()[0]}, "
            f"SQLite {tables_count} ตาราง, Toolkits {len(toolkits)} ชุด)"
        ),
    }


def _handle_webhook_dispatch(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    event_body = payload.get("body")
    if not isinstance(event_body, dict):
        return {"ok": False, "status": "FAILED", "error": "body must be a JSON object.", "output": {}}

    res_check = validate_research_url(url)
    host = str(res_check.get("host") or "").lower()
    ai_blocked = any(host == b or host.endswith(f".{b}") for b in te.BLOCKED_EXTERNAL_LLM_HOSTS)
    scheme_ok = str(res_check.get("scheme") or "").lower() == "https"
    if not res_check.get("valid") or not scheme_ok or ai_blocked:
        reason = (
            f"Blocked prohibited external AI host ({host})."
            if ai_blocked
            else ("Only https:// webhook URLs are allowed." if res_check.get("valid") and not scheme_ok else str(res_check.get("reason") or "Webhook URL rejected by SSRF policy."))
        )
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": reason,
            "output": {"url": url, "blocked": True},
        }

    # Only reaches here after Admin P5 Approval Gate (approval_required in CapabilitySpec)
    dry_run = bool(payload.get("dry_run", True))
    if dry_run:
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "dispatched": False,
                "dry_run": True,
                "url": url,
                "payload_bytes": len(json.dumps(event_body, ensure_ascii=False).encode("utf-8")),
            },
            "summary": f"ตรวจสอบ Webhook '{url}' ผ่าน P5 Gate แล้ว (dry_run)",
        }

    safe_ok, safe_msg = te.validate_safe_public_url(url)
    if not safe_ok:
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": safe_msg,
            "output": {"url": url, "blocked": True},
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(event_body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "ZYRQUEN-Webhook/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {
                "ok": True,
                "status": "COMPLETED",
                "output": {
                    "dispatched": True,
                    "dry_run": False,
                    "url": url,
                    "http_status": int(resp.status),
                },
                "summary": f"ส่ง Webhook ไปยัง {url} สำเร็จ (HTTP {resp.status})",
            }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "status": "FAILED",
            "error": f"Webhook delivery failed: {exc}",
            "output": {"dispatched": False, "url": url},
        }


def register_api_integration_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="api_integration",
        name="API & Integration Toolkit",
        thai_name="ชุดเครื่องมือ API และการเชื่อมต่อระบบ",
        version="1.0.0",
        description="ตรวจสอบสัญญา REST API Contract, ตรวจสอบความพร้อมบริการภายใน และจัดการ Webhook ภายใต้ SSRF Guard และ P5 Approval Gate",
        category="integration",
        dependencies=("python_core.tools_engine",),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=("python_core/tools_engine.py", "server.ts"),
        documentation="ตรวจสอบสัญญา API และเชื่อมบริการภายในอย่างปลอดภัย พร้อมควบคุมคำขอ Webhook ภายนอกด้วย Approval Gate",
    )

    specs = [
        (
            CapabilitySpec(
                id="api_integration.contract_validate",
                toolkit_id="api_integration",
                name="ตรวจสอบสัญญา REST API Contract",
                version="1.0.0",
                description="ตรวจความถูกต้องของ Method, เส้นทาง /api/* และฟิลด์บังคับใน Request Payload",
                input_schema={
                    "type": "object",
                    "required": ["method", "endpoint"],
                    "properties": {
                        "method": {"type": "string"},
                        "endpoint": {"type": "string"},
                        "required_fields": {"type": "array"},
                        "sample_body": {"type": "object"},
                    },
                },
                output_schema={"type": "object", "required": ["valid", "method", "endpoint", "problems"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/api_integration.py",),
                documentation="ส่ง method, endpoint, required_fields และ sample_body เพื่อตรวจก่อนเรียกใช้งานจริง",
                example_input={
                    "method": "POST",
                    "endpoint": "/api/conversations",
                    "required_fields": ["title"],
                    "sample_body": {"title": "New Workspace"},
                },
                keywords=("api", "rest", "contract", "endpoint", "integration", "เชื่อมต่อ"),
            ),
            _handle_api_contract_validate,
        ),
        (
            CapabilitySpec(
                id="api_integration.internal_health",
                toolkit_id="api_integration",
                name="ตรวจสอบการเชื่อมต่อบริการภายใน (Internal Service Integration)",
                version="1.0.0",
                description="ตรวจสถานะ Python Runtime, SQLite Tables, Data Directory และจำนวน Toolkits ที่ลงทะเบียนจริง",
                input_schema={"type": "object", "required": [], "properties": {}},
                output_schema={"type": "object", "required": ["service_status", "sqlite_connected", "external_models_used"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/api_integration.py",),
                documentation="ตรวจสุขภาพการเชื่อมต่อระหว่าง Node/Express, Python Worker และ SQLite",
                example_input={},
                keywords=("health", "integration", "internal", "service", "สถานะ", "เชื่อมต่อ"),
            ),
            _handle_internal_health,
        ),
        (
            CapabilitySpec(
                id="api_integration.webhook_dispatch",
                toolkit_id="api_integration",
                name="ส่ง Webhook ภายนอกอย่างปลอดภัย (P5 Approval Gate)",
                version="1.0.0",
                description="ส่ง POST JSON Webhook ไปยัง HTTPS ภายนอก (บล็อก IP ภายใน/โฮสต์ AI) และต้องผ่านการอนุมัติ P5 Gate",
                input_schema={
                    "type": "object",
                    "required": ["url", "body"],
                    "properties": {
                        "url": {"type": "string"},
                        "body": {"type": "object"},
                        "dry_run": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["dispatched", "url"]},
                dependencies=("python_core.tools_engine",),
                permission_mode="approval_required",
                risk_tier="external_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py",),
                documentation="ทุกคำขอส่ง Webhook ต้องผ่านการอนุมัติ P5 Gate ก่อนเสมอ",
                example_input={"url": "https://en.wikipedia.org/wiki/Webhook", "body": {"event": "test"}, "dry_run": True},
                keywords=("webhook", "api", "http", "dispatch"),
            ),
            _handle_webhook_dispatch,
        ),
    ]

    registry.register_toolkit(manifest, specs)
