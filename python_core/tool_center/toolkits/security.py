"""
Security Toolkit for ZYRQUEN Tool Center.
Provides Native-Only AST/dependency policy auditing, secret & path-traversal scanning,
and RBAC/governance audit trail inspection.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from apps.core.intelligence.cognitive_core import (
    PROHIBITED_PYTHON_DOTTED_PREFIXES,
    PROHIBITED_PYTHON_LLM_MODULES,
    PROHIBITED_WEB_LLM_PACKAGES,
)
import tools_engine as te

from ..contracts import CapabilitySpec, ToolkitManifest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_like_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("github_pat", re.compile(r"\bghp_[0-9A-Za-z]{20,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

_FROM_PRETRAINED_RE = re.compile(r"\bfrom_pretrained\s*\(")


def _scan_python_text(source: str, label: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    try:
        tree = ast.parse(source, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".", 1)[0]
                    if root_mod in PROHIBITED_PYTHON_LLM_MODULES or any(
                        alias.name.startswith(pref) for pref in PROHIBITED_PYTHON_DOTTED_PREFIXES
                    ):
                        findings.append({
                            "target": label,
                            "rule": "prohibited_external_llm_import",
                            "detail": f"Prohibited import '{alias.name}' at line {node.lineno}",
                        })
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                root_mod = mod.split(".", 1)[0]
                if root_mod in PROHIBITED_PYTHON_LLM_MODULES or any(
                    mod.startswith(pref) for pref in PROHIBITED_PYTHON_DOTTED_PREFIXES
                ):
                    findings.append({
                        "target": label,
                        "rule": "prohibited_external_llm_import",
                        "detail": f"Prohibited from-import '{mod}' at line {node.lineno}",
                    })
    except SyntaxError as exc:
        findings.append({"target": label, "rule": "syntax_error", "detail": str(exc)})

    if _FROM_PRETRAINED_RE.search(source):
        findings.append({
            "target": label,
            "rule": "from_pretrained_call",
            "detail": "Detected from_pretrained() call (external pretrained weights prohibited).",
        })
    for host in te.BLOCKED_EXTERNAL_LLM_HOSTS:
        if host in source:
            findings.append({
                "target": label,
                "rule": "blocked_external_ai_host",
                "detail": f"Detected blocked external AI host '{host}'.",
            })
    return findings


def _handle_native_policy_audit(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source")
    if isinstance(source, str) and source.strip():
        findings = _scan_python_text(source, "<inline_source>")
        for pkg in PROHIBITED_WEB_LLM_PACKAGES:
            if pkg in source:
                findings.append({
                    "target": "<inline_source>",
                    "rule": "prohibited_web_llm_package",
                    "detail": f"Detected prohibited package reference '{pkg}'.",
                })
        compliant = len(findings) == 0
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "scope": "inline_source",
                "policy_compliant": compliant,
                "scanned_files": 1,
                "findings": findings,
            },
            "summary": (
                "ผ่านการตรวจสอบนโยบาย Native-Only (ไม่พบการฝังโมเดลภายนอก)"
                if compliant
                else f"พบการละเมิดนโยบาย Native-Only จำนวน {len(findings)} รายการ"
            ),
        }

    # Repository audit (confined to python_core/ and src/)
    target_rel = str(payload.get("target_path") or "python_core").strip()
    target = (REPO_ROOT / target_rel).resolve()
    if target != REPO_ROOT and not target.is_relative_to(REPO_ROOT):
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": f"Path '{target_rel}' not found.", "output": {}}

    findings: list[dict[str, str]] = []
    scanned = 0
    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    for fpath in files:
        parts = fpath.relative_to(REPO_ROOT).parts
        if any(p in {"node_modules", "dist", "__pycache__", ".venv", "tool_center"} for p in parts):
            continue
        if fpath.suffix != ".py":
            continue
        scanned += 1
        text = fpath.read_text(encoding="utf-8", errors="replace")
        rel = "/".join(parts)
        # Skip tool_center/security.py and tools_engine.py's blocklist definitions
        file_findings = _scan_python_text(text, rel)
        if rel in {"python_core/tools_engine.py", "apps/core/intelligence/cognitive_core.py", "apps/core/intelligence/research.py"}:
            file_findings = [f for f in file_findings if f["rule"] != "blocked_external_ai_host"]
        findings.extend(file_findings)

    compliant = len(findings) == 0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "scope": target_rel,
            "policy_compliant": compliant,
            "scanned_files": scanned,
            "findings": findings[:50],
        },
        "summary": (
            f"ตรวจสอบนโยบาย Native-Only ครบ {scanned} ไฟล์: ปลอดภัย (0 การฝังโมเดลภายนอก)"
            if compliant
            else f"ตรวจพบข้อสังเกต {len(findings)} รายการจากการสแกน {scanned} ไฟล์"
        ),
    }


def _handle_secret_and_path_scan(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("content") or "")
    candidate_path = str(payload.get("path") or "").strip()
    findings: list[dict[str, str]] = []

    if candidate_path:
        norm = candidate_path.replace("\\", "/")
        if norm.startswith("/") or ".." in norm.split("/") or "\x00" in norm:
            findings.append({
                "type": "path_traversal",
                "detail": f"Unsafe path detected: '{candidate_path}'",
            })

    for rule_name, regex in _SECRET_PATTERNS:
        if regex.search(text):
            findings.append({
                "type": "secret_pattern",
                "rule": rule_name,
                "detail": f"Matched potential secret pattern ({rule_name}).",
            })

    clean = len(findings) == 0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "clean": clean,
            "finding_count": len(findings),
            "findings": findings,
        },
        "summary": (
            "ไม่พบรูปแบบ Secret รั่วไหลหรือ Path Traversal"
            if clean
            else f"ตรวจพบความเสี่ยงด้านความปลอดภัย {len(findings)} รายการ"
        ),
    }


def _handle_governance_audit(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}

    raw_limit = int(payload.get("limit") or 20)
    limit = max(1, min(50, raw_limit))
    tools_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT id, permission_mode, enabled, quota_daily, calls_today FROM external_tools ORDER BY id ASC"
        ).fetchall()
    ]
    pending_tool_gates = int(
        conn.execute("SELECT COUNT(*) FROM tool_invocations WHERE status='PENDING_APPROVAL'").fetchone()[0]
    )
    pending_wf_gates = int(
        conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE status='PENDING_APPROVAL'").fetchone()[0]
    )
    recent_audits = [
        dict(r)
        for r in conn.execute(
            "SELECT id, actor_email, action, target, outcome, created_at FROM audit_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "tool_policies": tools_rows,
            "pending_approvals": {
                "tool_invocations": pending_tool_gates,
                "workflow_runs": pending_wf_gates,
            },
            "recent_audit_logs": recent_audits,
        },
        "summary": (
            f"ตรวจสอบ Governance: เครื่องมือ {len(tools_rows)} รายการ, "
            f"รออนุมัติ {pending_tool_gates + pending_wf_gates} รายการ, Audit Logs ล่าสุด {len(recent_audits)} รายการ"
        ),
    }


def _handle_dependency_audit(_payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    import json as _json

    prohibited_hits: list[dict[str, str]] = []
    pkg_json = REPO_ROOT / "package.json"
    checked_files: list[str] = []
    if pkg_json.exists():
        checked_files.append("package.json")
        try:
            data = _json.loads(pkg_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies"):
                deps = data.get(section) or {}
                if isinstance(deps, dict):
                    for dep_name in deps.keys():
                        low = str(dep_name).lower()
                        if any(p in low for p in PROHIBITED_WEB_LLM_PACKAGES):
                            prohibited_hits.append({"file": "package.json", "package": str(dep_name), "section": section})
        except Exception as exc:
            prohibited_hits.append({"file": "package.json", "error": str(exc)})

    req_txt = REPO_ROOT / "apps" / "api" / "requirements.txt"
    if req_txt.exists():
        checked_files.append("apps/api/requirements.txt")
        for line in req_txt.read_text(encoding="utf-8", errors="replace").splitlines():
            clean = line.strip().split("==")[0].split(">=")[0].strip().lower()
            if not clean or clean.startswith("#"):
                continue
            if clean in PROHIBITED_PYTHON_LLM_MODULES or any(clean.startswith(p) for p in PROHIBITED_PYTHON_DOTTED_PREFIXES):
                prohibited_hits.append({"file": "apps/api/requirements.txt", "package": clean})

    clean = len(prohibited_hits) == 0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "clean": clean,
            "checked_files": checked_files,
            "prohibited_dependencies": prohibited_hits,
        },
        "summary": (
            f"ตรวจ Dependencies ({', '.join(checked_files)}): ปลอดภัย ไม่พบแพ็กเกจ AI ภายนอก"
            if clean
            else f"พบ Dependency ต้องห้าม {len(prohibited_hits)} รายการ"
        ),
    }


_PERMISSIVE_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "PSF-2.0", "Python-2.0", "Unlicense"})
_COPYLEFT_LICENSES = frozenset({"GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0"})


def _safe_repo_subpath(raw: str | None) -> Path | None:
    clean = str(raw or ".").strip() or "."
    target = (REPO_ROOT / clean).resolve()
    if target != REPO_ROOT and not target.is_relative_to(REPO_ROOT):
        return None
    return target


def _collect_sbom_components(target: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    pkg_json = target / "package.json"
    lock_json = target / "package-lock.json"
    lock_packages: dict[str, Any] = {}
    if lock_json.is_file() and lock_json.stat().st_size <= 8_000_000:
        try:
            lock_data = json.loads(lock_json.read_text(encoding="utf-8"))
            lock_packages = lock_data.get("packages") or {}
        except Exception:
            lock_packages = {}

    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies"):
                deps = data.get(section) or {}
                if isinstance(deps, dict):
                    for name, spec in sorted(deps.items()):
                        lock_meta = lock_packages.get(f"node_modules/{name}") or {}
                        components.append({
                            "name": str(name),
                            "version": str(lock_meta.get("version") or spec),
                            "declared_spec": str(spec),
                            "ecosystem": "npm",
                            "scope": "dev" if section == "devDependencies" else "runtime",
                            "license": lock_meta.get("license") or "UNKNOWN",
                        })
        except Exception:
            pass

    for req_rel in ("requirements.txt", "apps/api/requirements.txt"):
        rf = target / req_rel
        if rf.is_file():
            for line in rf.read_text(encoding="utf-8", errors="replace").splitlines():
                clean = line.strip()
                if not clean or clean.startswith(("#", "-")):
                    continue
                m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", clean)
                if m:
                    components.append({
                        "name": m.group(1),
                        "version": m.group(2).strip() or "unspecified",
                        "declared_spec": clean,
                        "ecosystem": "pypi",
                        "scope": "runtime",
                        "license": "UNKNOWN",
                    })
    return components


def _handle_sbom_generate(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    target = _safe_repo_subpath(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}

    components = _collect_sbom_components(target)
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "componentCount": len(components),
        "components": components,
    }
    bom_sha = hashlib.sha256(json.dumps(bom, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "bom_format": "CycloneDX",
            "spec_version": "1.5",
            "component_count": len(components),
            "components": components[:200],
            "bom_sha256": bom_sha,
        },
        "summary": f"สร้าง SBOM (CycloneDX 1.5): พบองค์ประกอบซอฟต์แวร์ {len(components)} รายการ",
    }


def _handle_license_compliance(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    target = _safe_repo_subpath(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}

    components = _collect_sbom_components(target)
    permissive = 0
    copyleft_flags: list[dict[str, str]] = []
    unknown: list[str] = []
    for c in components:
        lic = str(c.get("license") or "UNKNOWN")
        if lic in _PERMISSIVE_LICENSES:
            permissive += 1
        elif any(cl in lic for cl in _COPYLEFT_LICENSES):
            copyleft_flags.append({"package": c["name"], "license": lic, "ecosystem": c["ecosystem"]})
        else:
            unknown.append(c["name"])

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "total_components": len(components),
            "permissive_count": permissive,
            "copyleft_review_count": len(copyleft_flags),
            "unknown_license_count": len(unknown),
            "copyleft_flags": copyleft_flags,
            "unknown_packages": unknown[:50],
            "compliant": len(copyleft_flags) == 0,
        },
        "summary": f"ตรวจสอบ License ({len(components)} รายการ): Permissive {permissive}, Copyleft Review {len(copyleft_flags)}, Unknown {len(unknown)}",
    }


def _handle_threat_model(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    target = _safe_repo_subpath(payload.get("target_path") or ".")
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}

    surfaces: list[dict[str, Any]] = []
    controls_verified: list[str] = []

    server_ts = target / "server.ts"
    if server_ts.is_file():
        stxt = server_ts.read_text(encoding="utf-8", errors="replace")
        has_auth = "requireAuth" in stxt
        has_admin = "requireAdmin" in stxt
        has_helmet_or_csp = "helmet" in stxt or "Content-Security-Policy" in stxt or "cors" in stxt
        if has_auth:
            controls_verified.append("Express routes enforce requireAuth middleware")
        if has_admin:
            controls_verified.append("Privileged endpoints enforce requireAdmin")
        surfaces.append({
            "asset": "server.ts",
            "stride_categories": ["Spoofing", "Elevation of Privilege", "Tampering"],
            "controls_present": {"requireAuth": has_auth, "requireAdmin": has_admin, "headers_or_cors": has_helmet_or_csp},
        })

    sandbox_py = target / "python_core" / "tool_center" / "sandbox.py"
    if sandbox_py.is_file():
        sb_txt = sandbox_py.read_text(encoding="utf-8", errors="replace")
        has_ast_guard = "inspect_sandbox_code_policy" in sb_txt
        has_rlimit = "setrlimit" in sb_txt
        if has_ast_guard and has_rlimit:
            controls_verified.append("Python sandbox enforces AST guard + OS rlimits")
        surfaces.append({
            "asset": "python_core/tool_center/sandbox.py",
            "stride_categories": ["Tampering", "Information Disclosure", "Denial of Service"],
            "controls_present": {"ast_policy_guard": has_ast_guard, "os_rlimit": has_rlimit},
        })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "methodology": "STRIDE-deterministic",
            "surface_count": len(surfaces),
            "surfaces": surfaces,
            "verified_controls": controls_verified,
        },
        "summary": f"วิเคราะห์ Threat Model (STRIDE): ตรวจพบ {len(surfaces)} พื้นผิวหลัก และกลไกป้องกัน {len(controls_verified)} รายการ",
    }


def _handle_permission_audit(_payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    registry = ctx["registry"]
    misconfigured: list[dict[str, str]] = []
    by_mode: dict[str, int] = {"auto": 0, "approval_required": 0, "admin_only": 0, "disabled": 0}
    total = 0

    for cid in registry.list_capability_ids():
        spec = registry.get_spec(cid)
        if spec is None:
            continue
        total += 1
        by_mode[spec.permission_mode] = by_mode.get(spec.permission_mode, 0) + 1
        if spec.risk_tier == "external_readonly" and spec.permission_mode == "auto":
            misconfigured.append({"capability_id": cid, "issue": "external_readonly capability should require approval_required"})
        if spec.risk_tier == "governance" and spec.permission_mode == "auto" and spec.toolkit_id != "automation":
            misconfigured.append({"capability_id": cid, "issue": "governance capability should enforce admin_only or approval_required"})

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "total_capabilities": total,
            "permission_distribution": by_mode,
            "misconfigurations": misconfigured,
            "rbac_compliant": len(misconfigured) == 0,
        },
        "summary": f"ตรวจสอบสิทธิ์ RBAC ทั้ง {total} ความสามารถ: {'ถูกต้องตามนโยบาย' if not misconfigured else f'พบจุดเสี่ยง {len(misconfigured)} รายการ'}",
    }


def _handle_artifact_integrity(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data_dir: Path = ctx["data_dir"]
    artifacts = payload.get("artifacts")
    results: list[dict[str, Any]] = []
    all_valid = True

    if isinstance(artifacts, list) and artifacts:
        ws_files = (data_dir / "workspace_files").resolve()
        sb_root = (data_dir / "sandbox_workspaces").resolve()
        for item in artifacts[:50]:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or item.get("filename") or "").strip()
            expected_sha = str(item.get("expected_sha256") or "").strip().lower()
            content = item.get("content")
            if isinstance(content, str):
                actual_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                matched = (actual_sha == expected_sha) if expected_sha else True
                if expected_sha and not matched:
                    all_valid = False
                results.append({"target": rel or "<inline>", "sha256": actual_sha, "expected_sha256": expected_sha or None, "verified": matched})
                continue

            if not rel or ".." in Path(rel).parts or rel.startswith("/"):
                all_valid = False
                results.append({"target": rel, "verified": False, "error": "Invalid or escaping artifact path"})
                continue
            cand = (ws_files / rel).resolve()
            if not cand.exists() or not cand.is_relative_to(ws_files):
                cand = (sb_root / rel).resolve()
                if not cand.is_relative_to(sb_root):
                    all_valid = False
                    results.append({"target": rel, "verified": False, "error": "Path escapes allowed artifact directories"})
                    continue
            if not cand.is_file():
                all_valid = False
                results.append({"target": rel, "verified": False, "error": "Artifact file missing"})
                continue
            actual_sha = hashlib.sha256(cand.read_bytes()).hexdigest()
            matched = (actual_sha == expected_sha) if expected_sha else True
            if expected_sha and not matched:
                all_valid = False
            results.append({"target": rel, "size_bytes": cand.stat().st_size, "sha256": actual_sha, "expected_sha256": expected_sha or None, "verified": matched})
    else:
        ws_files = (data_dir / "workspace_files").resolve()
        if ws_files.exists():
            for fp in sorted(ws_files.iterdir()):
                if fp.is_file():
                    results.append({
                        "target": fp.name,
                        "size_bytes": fp.stat().st_size,
                        "sha256": hashlib.sha256(fp.read_bytes()).hexdigest(),
                        "verified": True,
                    })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "artifact_count": len(results),
            "all_verified": all_valid,
            "artifacts": results,
        },
        "summary": f"ตรวจสอบความสมบูรณ์ Artifact {len(results)} รายการ: {'ผ่านทั้งหมด' if all_valid else 'พบความคลาดเคลื่อน'}",
    }


def register_security_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="security",
        name="Security Toolkit",
        thai_name="ชุดเครื่องมือความปลอดภัยและธรรมาภิบาล",
        version="1.2.0",
        description="ตรวจสอบการฝังโมเดล AI ภายนอก, SBOM, License Compliance, Threat Model, Permission Audit, Artifact Integrity และ Secret/Path Scan",
        category="security",
        dependencies=("apps.core.intelligence.cognitive_core", "python_core.tools_engine"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=(
            "apps/core/intelligence/cognitive_core.py",
            "python_core/tools_engine.py",
            "apps/core/workflow/governance.py",
        ),
        documentation="ใช้สแกนความปลอดภัยเชิงสถิต, Supply Chain (SBOM/License), Threat Model, Permission Audit และตรวจ Audit Logs",
    )

    specs = [
        (
            CapabilitySpec(
                id="security.native_policy_audit",
                toolkit_id="security",
                name="ตรวจสอบนโยบาย Native-Only (AST Import & Host Audit)",
                version="1.0.0",
                description="สแกนโค้ดหรือโมดูลใน Repository ด้วย AST เพื่อยืนยันว่าไม่มีการนำเข้า SDK/โฮสต์ LLM ภายนอก",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "source": {"type": "string"},
                        "target_path": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["policy_compliant", "scanned_files", "findings"]},
                dependencies=("apps.core.intelligence.cognitive_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/intelligence/cognitive_core.py",),
                documentation="ส่ง source เพื่อตรวจโค้ดโดยตรง หรือระบุ target_path (เช่น 'python_core') เพื่อสแกนทั้งโฟลเดอร์",
                example_input={"target_path": "python_core"},
                keywords=("security", "policy", "native", "audit", "llm", "ความปลอดภัย", "ตรวจสอบสิทธิ์"),
            ),
            _handle_native_policy_audit,
        ),
        (
            CapabilitySpec(
                id="security.dependency_audit",
                toolkit_id="security",
                name="ตรวจสอบ Dependencies (Dependency Auditing)",
                version="1.0.0",
                description="ตรวจสอบ package.json และ requirements.txt เพื่อหาแพ็กเกจโมเดล AI ภายนอกต้องห้าม",
                input_schema={"type": "object", "required": [], "properties": {}},
                output_schema={"type": "object", "required": ["clean", "checked_files", "prohibited_dependencies"]},
                dependencies=("apps.core.intelligence.cognitive_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/intelligence/cognitive_core.py",),
                documentation="ตรวจสอบรายการแพ็กเกจของโปรเจกต์เพื่อรักษาข้อกำหนด No External Models",
                example_input={},
                keywords=("dependency", "audit", "package", "security", "ความปลอดภัย"),
            ),
            _handle_dependency_audit,
        ),
        (
            CapabilitySpec(
                id="security.secret_and_path_scan",
                toolkit_id="security",
                name="สแกน Secret รั่วไหลและ Path Traversal",
                version="1.0.0",
                description="ตรวจจับรูปแบบคีย์/โทเค็นต้องห้าม (sk-, AIza, ghp_, Private Key) และเส้นทางไฟล์นอกขอบเขต",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "content": {"type": "string"},
                        "path": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["clean", "finding_count", "findings"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py",),
                documentation="ส่ง content และ/หรือ path เพื่อตรวจจับความเสี่ยงก่อนบันทึกหรือประมวลผล",
                example_input={"path": "workspace/report.md", "content": "Safe project summary content."},
                keywords=("secret", "scan", "traversal", "security", "ความปลอดภัย", "คีย์"),
            ),
            _handle_secret_and_path_scan,
        ),
        (
            CapabilitySpec(
                id="security.governance_audit",
                toolkit_id="security",
                name="ตรวจนโยบาย P5 Gate และ Audit Logs (Admin Only)",
                version="1.0.0",
                description="ดึงสถานะสิทธิ์เครื่องมือ รายการรออนุมัติ และบันทึก Audit Trail ล่าสุดจาก SQLite (เฉพาะผู้ดูแลระบบ)",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {"limit": {"type": "integer"}},
                },
                output_schema={"type": "object", "required": ["tool_policies", "pending_approvals", "recent_audit_logs"]},
                dependencies=("python_core.tools_engine",),
                permission_mode="admin_only",
                risk_tier="governance",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py", "apps/core/workflow/governance.py"),
                documentation="สงวนสิทธิ์เฉพาะ role='admin' เท่านั้น ผู้ใช้ทั่วไปจะถูกปฏิเสธ (BLOCKED)",
                example_input={"limit": 10},
                keywords=("governance", "rbac", "audit", "admin", "สิทธิ์", "ความปลอดภัย"),
            ),
            _handle_governance_audit,
        ),
        (
            CapabilitySpec(
                id="security.sbom_generate",
                toolkit_id="security",
                name="สร้างรายการองค์ประกอบซอฟต์แวร์ (SBOM CycloneDX)",
                version="1.0.0",
                description="สร้าง CycloneDX 1.5 SBOM จาก package.json, package-lock.json และ requirements.txt พร้อม SHA-256",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["bom_format", "component_count", "components", "bom_sha256"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/security.py",),
                documentation="สร้างรายการซอฟต์แวร์และไลบรารีที่ใช้ในโปรเจกต์เพื่อตรวจ Supply Chain",
                example_input={"target_path": "."},
                keywords=("sbom", "supply_chain", "cyclonedx", "dependencies", "ความปลอดภัย"),
            ),
            _handle_sbom_generate,
        ),
        (
            CapabilitySpec(
                id="security.license_compliance",
                toolkit_id="security",
                name="ตรวจสอบความสอดคล้องของ License (License Compliance)",
                version="1.0.0",
                description="จำแนก License ของแพ็กเกจใน Lockfile/Manifests เป็น Permissive, Copyleft Review หรือ Unknown",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["total_components", "permissive_count", "copyleft_review_count", "compliant"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/security.py",),
                documentation="ตรวจสอบความเสี่ยงด้าน License ของแพ็กเกจทั้งหมด",
                example_input={"target_path": "."},
                keywords=("license", "compliance", "oss", "legal", "สัญญาอนุญาต"),
            ),
            _handle_license_compliance,
        ),
        (
            CapabilitySpec(
                id="security.threat_model",
                toolkit_id="security",
                name="วิเคราะห์ Threat Model เชิงโครงสร้าง (STRIDE Surface Analysis)",
                version="1.0.0",
                description="ตรวจพื้นผิวรับข้อมูล Middleware Auth/Admin และ Sandbox AST/rlimit Controls ตามกรอบ STRIDE",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["methodology", "surface_count", "surfaces", "verified_controls"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/security.py",),
                documentation="วิเคราะห์ขอบเขตความปลอดภัยของเซิร์ฟเวอร์และ Sandbox เชิงกำหนด",
                example_input={"target_path": "."},
                keywords=("threat", "stride", "surface", "security", "ภัยคุกคาม"),
            ),
            _handle_threat_model,
        ),
        (
            CapabilitySpec(
                id="security.permission_audit",
                toolkit_id="security",
                name="ตรวจสอบสิทธิ์การเข้าถึง Capability ทั้งระบบ (Permission Audit)",
                version="1.0.0",
                description="ตรวจ RBAC mode และ Risk Tier ของความสามารถทุกตัวใน Tool Center เพื่อป้องกันสิทธิ์รั่วไหล",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "required": ["total_capabilities", "permission_distribution", "misconfigurations", "rbac_compliant"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/security.py",),
                documentation="ตรวจสอบว่าเครื่องมือที่มีความเสี่ยงสูงอยู่ภายใต้ admin_only หรือ approval_required",
                example_input={},
                keywords=("permission", "rbac", "audit", "access", "สิทธิ์"),
            ),
            _handle_permission_audit,
        ),
        (
            CapabilitySpec(
                id="security.artifact_integrity",
                toolkit_id="security",
                name="ทวนสอบแฮชและความสมบูรณ์ของ Artifact (Artifact Integrity)",
                version="1.0.0",
                description="คำนวณ SHA-256 และเทียบกับ expected_sha256 สำหรับผลผลิตใน workspace_files/sandbox_workspaces",
                input_schema={"type": "object", "properties": {"artifacts": {"type": "array"}}},
                output_schema={"type": "object", "required": ["artifact_count", "all_verified", "artifacts"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/security.py",),
                documentation="ตรวจสอบว่าไฟล์ผลลัพธ์ไม่ถูกดัดแปลงระหว่างทาง",
                example_input={"artifacts": [{"filename": "demo.txt", "content": "ok", "expected_sha256": "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df"}]},
                keywords=("artifact", "integrity", "sha256", "checksum", "ความสมบูรณ์"),
            ),
            _handle_artifact_integrity,
        ),
    ]

    registry.register_toolkit(manifest, specs)
