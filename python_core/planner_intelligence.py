#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Native Context-Aware DAG Planner Intelligence
----------------------------------------------------------
Pure Python 3.11 stdlib implementation (Zero external LLMs).

Responsibilities:
A. Goal Understanding:
   - Unwrap UI command/template wrappers (CreateArtifactView, plan prefixes)
   - Extract objective, requirements, context hints, expected deliverables
   - Detect corrupted, malformed, duplicate, or incomplete inputs -> NEEDS_CLARIFICATION
B. Context-Aware Planning (Strictly Read-Only):
   - Inspect real repository directory/files and registered ToolCenterRegistry capabilities
   - Map steps only to real existing files & registered capabilities (never invent paths/tools)
   - Omit generic CRUD / DB / API / UI steps unless explicitly required by the goal
C. Adaptive DAG Generation:
   - Emit rich node contracts (step_id, task_id, objective, title, input_contract, expected_output,
     output_contract, dependencies, depends_on, required_capabilities, tool_id, permission,
     risk_level, verification_criteria, preconditions, postconditions, failure_policy,
     retry_policy, status, execution_status)
D. Strict State Machine:
   - Supported node/plan states:
     NEEDS_CLARIFICATION | BLOCKED | READY | RUNNING | EXECUTING | COMPLETED | FAILED | CANCELLED
   - A node is READY strictly iff ALL its dependencies are COMPLETED and validated (so root
     nodes with no dependencies start READY, while downstream nodes with dependencies start BLOCKED).
   - Invalid or incomplete goals produce 0 executable steps.
"""

from __future__ import annotations

import collections
import re
import sqlite3
from pathlib import Path
from typing import Any

from cognitive_pipeline import (
    _analyze_unicode_semantics,
    _detect_opaque_noise,
    _is_plausible_latin_word,
    _is_plausible_thai_span,
)

CANONICAL_DAG_STATES = (
    "NEEDS_CLARIFICATION",
    "BLOCKED",
    "READY",
    "RUNNING",
    "EXECUTING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)

_WRAPPER_PREFIXES = (
    ("create_software", re.compile(r"^วางแผนและพัฒนาซอร์สโค้ด\s*:?\s*(.*)$", re.IGNORECASE)),
    ("create_document", re.compile(r"^สร้างเอกสารและรายงานเชิงโครงสร้าง\s*:?\s*(.*)$", re.IGNORECASE)),
    ("create_data", re.compile(r"^ออกแบบและสร้างโครงสร้างข้อมูล/ตาราง\s*:?\s*(.*)$", re.IGNORECASE)),
)

_PLAN_CMD_RE = re.compile(
    r"^(?:วางแผน|แผนงาน|กำหนดแผน|plan|decompose)\s*:?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Generic verbs/nouns that alone do not describe an actionable target
_GENERIC_ACTION_ONLY_TOKENS = frozenset({
    "วางแผน", "แผนงาน", "กำหนดแผน", "สร้าง", "พัฒนา", "ออกแบบ", "แก้ไข", "ปรับปรุง",
    "ทำ", "เขียน", "วิเคราะห์", "ตรวจสอบ", "จัดการ", "ช่วย", "หน่อย", "ครับ", "ค่ะ",
    "ระบบ", "งาน", "โปรเจกต์", "โครงการ", "แอป", "เว็บ", "โค้ด", "ไฟล์", "ข้อมูล", "เอกสาร",
    "plan", "decompose", "build", "create", "implement", "design", "make", "write",
    "fix", "update", "improve", "analyze", "check", "system", "app", "application",
    "web", "code", "project", "task", "file", "data", "something", "anything", "test",
})

_SKIP_REPO_DIRS = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    "data",
})

_FILE_MENTION_RE = re.compile(
    r"\b([A-Za-z0-9_.\-/]{1,120}\.(?:py|ts|tsx|js|jsx|json|md|sql|csv|txt|yaml|yml))\b"
)


def unwrap_command_wrapper(prompt: str) -> dict[str, Any]:
    """
    Strip CreateArtifactView / command template wrappers so validation inspects
    the actual user payload rather than being fooled by trusted Thai headings.
    """
    raw = str(prompt or "").strip()
    if not raw:
        return {
            "raw_prompt": raw,
            "wrapper_kind": None,
            "title": "",
            "spec_body": "",
            "attachment_name": "",
            "effective_goal": "",
        }

    lines = [ln.rstrip() for ln in raw.splitlines()]
    first_line = lines[0].strip() if lines else ""
    wrapper_kind: str | None = None
    title = ""
    rest_lines = lines[1:]

    for kind, pattern in _WRAPPER_PREFIXES:
        m = pattern.match(first_line)
        if m:
            wrapper_kind = kind
            title = m.group(1).strip()
            break

    if wrapper_kind is not None:
        spec_lines: list[str] = []
        attachment_name = ""
        in_spec = False
        for ln in rest_lines:
            stripped_ln = ln.strip()
            if not stripped_ln:
                if in_spec and spec_lines and spec_lines[-1] != "":
                    spec_lines.append("")
                continue
            if stripped_ln.startswith("รายละเอียดและข้อกำหนด:"):
                in_spec = True
                after = stripped_ln.split(":", 1)[1].strip()
                if after:
                    spec_lines.append(after)
                continue
            if stripped_ln.startswith("อ้างอิงไฟล์แนบ:"):
                in_spec = False
                attachment_name = stripped_ln.split(":", 1)[1].strip()
                continue
            if in_spec:
                spec_lines.append(stripped_ln)
            elif not title:
                title = stripped_ln
            else:
                spec_lines.append(stripped_ln)

        spec_body = "\n".join(spec_lines).strip()
        parts = [p for p in (title, spec_body) if p]
        effective_goal = " — ".join(parts) if parts else ""
        return {
            "raw_prompt": raw,
            "wrapper_kind": wrapper_kind,
            "title": title,
            "spec_body": spec_body,
            "attachment_name": attachment_name,
            "effective_goal": effective_goal,
        }

    m_plan = _PLAN_CMD_RE.match(raw)
    if m_plan:
        body = m_plan.group(1).strip()
        body_lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        cleaned_lines: list[str] = []
        attachment_name = ""
        for ln in body_lines:
            if ln.startswith("รายละเอียดและข้อกำหนด:"):
                after = ln.split(":", 1)[1].strip()
                if after:
                    cleaned_lines.append(after)
                continue
            if ln.startswith("อ้างอิงไฟล์แนบ:"):
                attachment_name = ln.split(":", 1)[1].strip()
                continue
            cleaned_lines.append(ln)
        eff = "\n".join(cleaned_lines).strip()
        return {
            "raw_prompt": raw,
            "wrapper_kind": "plan_prefix",
            "title": cleaned_lines[0] if cleaned_lines else "",
            "spec_body": "\n".join(cleaned_lines[1:]).strip() if len(cleaned_lines) > 1 else "",
            "attachment_name": attachment_name,
            "effective_goal": eff,
        }

    # Also unwrap standalone metadata labels ("รายละเอียดและข้อกำหนด:", "อ้างอิงไฟล์แนบ:")
    # so malformed specs like "รายละเอียดและข้อกำหนด: ะะี" cannot disguise corrupt text as valid Thai.
    plain_title = ""
    plain_spec: list[str] = []
    plain_attachment = ""
    in_plain_spec = False
    saw_metadata_label = False
    for ln in lines:
        stripped_ln = ln.strip()
        if not stripped_ln:
            continue
        if stripped_ln.startswith("รายละเอียดและข้อกำหนด:"):
            saw_metadata_label = True
            in_plain_spec = True
            after = stripped_ln.split(":", 1)[1].strip()
            if after:
                plain_spec.append(after)
            continue
        if stripped_ln.startswith("อ้างอิงไฟล์แนบ:"):
            saw_metadata_label = True
            in_plain_spec = False
            plain_attachment = stripped_ln.split(":", 1)[1].strip()
            continue
        if in_plain_spec:
            plain_spec.append(stripped_ln)
        elif not plain_title:
            plain_title = stripped_ln
        else:
            plain_spec.append(stripped_ln)

    if saw_metadata_label:
        spec_joined = "\n".join(plain_spec).strip()
        eff_parts = [p for p in (plain_title, spec_joined) if p]
        return {
            "raw_prompt": raw,
            "wrapper_kind": None,
            "title": plain_title,
            "spec_body": spec_joined,
            "attachment_name": plain_attachment,
            "effective_goal": " — ".join(eff_parts) if eff_parts else "",
        }

    return {
        "raw_prompt": raw,
        "wrapper_kind": None,
        "title": first_line,
        "spec_body": "\n".join(lines[1:]).strip(),
        "attachment_name": "",
        "effective_goal": raw,
    }


_PLACEHOLDER_ONLY_RE = re.compile(
    r"^(?:undefined|null|none|nan|\[object\s+object\]|tbd|todo|n/?a|placeholder|[-—_.•:;\s]+)$",
    re.IGNORECASE,
)


def _is_generic_placeholder(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    return bool(_PLACEHOLDER_ONLY_RE.match(stripped))


def _is_segment_corrupt_or_gibberish(text: str) -> tuple[bool, str | None]:
    stripped = text.strip()
    if not stripped:
        return True, "empty_segment"
    if _is_generic_placeholder(stripped):
        return True, "generic_placeholder"
    uni = _analyze_unicode_semantics(stripped)
    opaque, reason = _detect_opaque_noise(stripped, uni, kg_matched_any=False)
    if opaque:
        return True, reason or "opaque_noise"

    # Mixed Thai + Latin gibberish check: inspect every Thai/Latin token separately
    thai_spans = re.findall(r"[\u0E00-\u0E7F]+", stripped)
    latin_words = re.findall(r"[A-Za-z]+", stripped)
    if thai_spans:
        bad_thai = [sp for sp in thai_spans if not _is_plausible_thai_span(sp)]
        if bad_thai and len(bad_thai) == len(thai_spans) and not latin_words:
            return True, "implausible_thai_span"
        # Pure vowel/tone-mark fragment like "ะ" or "ะะี" without any Thai consonant
        if any(not any(0x0E01 <= ord(c) <= 0x0E2E for c in sp) for sp in thai_spans):
            return True, "thai_span_missing_consonants"
        # Implausible Thai span appended inside mixed text
        if any(len(sp) >= 2 and not _is_plausible_thai_span(sp) for sp in thai_spans):
            return True, "implausible_thai_span"

    if latin_words and not thai_spans:
        if all(not _is_plausible_latin_word(w) for w in latin_words):
            return True, "implausible_latin_words"

    # Repeated 4+ identical characters inside tokens (e.g. "aaaaa", "กกกก")
    if re.search(r"(.)\1{3,}", stripped):
        return True, "repeated_character_noise"

    return False, None


def _detect_duplicate_noise(text: str) -> bool:
    clauses = [
        re.sub(r"\s+", " ", c.strip().lower())
        for c in re.split(r"[\n;•]+", text)
        if c.strip()
    ]
    if len(clauses) >= 3 and len(set(clauses)) == 1:
        return True
    words = [w.lower() for w in re.findall(r"[\u0E00-\u0E7FA-Za-z0-9_]+", text)]
    if len(words) >= 4 and len(set(words)) == 1:
        return True
    return False


def analyze_planner_goal(prompt: str, *, attachment: str = "") -> dict[str, Any]:
    """
    A. Goal Understanding:
    Extract objective, requirements, context_hints, expected_deliverables,
    and strictly classify clarity_status as VALID | INCOMPLETE | INVALID_CORRUPT.
    """
    unwrapped = unwrap_command_wrapper(prompt)
    title = unwrapped["title"]
    spec_body = unwrapped["spec_body"]
    effective = unwrapped["effective_goal"]
    wrapper_kind = unwrapped["wrapper_kind"]

    issues: list[str] = []
    questions: list[str] = []

    if not effective and not attachment.strip():
        return {
            "raw_prompt": prompt,
            "wrapper_kind": wrapper_kind,
            "objective": "",
            "is_actionable_goal": False,
            "requirements": [],
            "context_hints": [],
            "expected_deliverables": [],
            "clarity_status": "INCOMPLETE",
            "issues": ["missing_goal_payload"],
            "clarification_questions": [
                "กรุณาระบุเป้าหมายหรือสิ่งที่ต้องการให้ระบบวางแผน/พัฒนาให้ชัดเจน",
                "ระบุไฟล์หรือโมดูลเป้าหมาย และผลลัพธ์ที่คาดหวัง (เช่น โค้ด เอกสาร หรือชุดทดสอบ)",
            ],
        }

    # Validate each user-supplied part independently so a wrapper header cannot hide corrupted spec
    if title:
        bad_title, bad_reason = _is_segment_corrupt_or_gibberish(title)
        if bad_title:
            issues.append(f"corrupt_title:{bad_reason}")
    if spec_body:
        bad_spec, bad_reason = _is_segment_corrupt_or_gibberish(spec_body)
        if bad_spec:
            issues.append(f"corrupt_spec:{bad_reason}")
    if effective and not issues:
        bad_eff, bad_reason = _is_segment_corrupt_or_gibberish(effective)
        if bad_eff:
            issues.append(f"corrupt_goal:{bad_reason}")

    if effective and _detect_duplicate_noise(effective):
        issues.append("duplicate_meaningless_input")

    if issues:
        return {
            "raw_prompt": prompt,
            "wrapper_kind": wrapper_kind,
            "objective": "",
            "is_actionable_goal": False,
            "requirements": [],
            "context_hints": [],
            "expected_deliverables": [],
            "clarity_status": "INVALID_CORRUPT",
            "issues": issues,
            "clarification_questions": [
                "ข้อความเป้าหมายหรือรายละเอียดมีอักขระผิดรูป ไม่สมบูรณ์ หรือซ้ำซ้อนจนไม่สามารถตีความความต้องการจริงได้",
                "กรุณาพิมพ์เป้าหมายและข้อกำหนดเป็นภาษาไทยหรือภาษาอังกฤษที่ระบุขอบเขตงานและผลลัพธ์ที่ต้องการให้ชัดเจน",
            ],
        }

    # Requirement extraction (deduplicated)
    raw_clauses = [
        re.sub(r"^[\-\*\d\.)\s]+", "", c).strip()
        for c in re.split(r"[\n;]+", effective)
        if c.strip()
    ]
    requirements: list[str] = []
    seen_req: set[str] = set()
    for cl in raw_clauses:
        key = cl.lower()
        if key and key not in seen_req:
            seen_req.add(key)
            requirements.append(cl)

    objective = title or (requirements[0] if requirements else effective)

    # Detect overly vague / incomplete goals lacking target domain or actionable substance
    tokens = re.findall(r"[\u0E00-\u0E7FA-Za-z0-9_.\-/]+", effective)
    meaningful_tokens = [
        t for t in tokens
        if t.lower() not in _GENERIC_ACTION_ONLY_TOKENS and len(t) >= 2
    ]
    # Also handle unspaced Thai phrases like "สร้างระบบ" or "แก้ไขโค้ด"
    eff_clean = effective.strip()
    for generic_w in sorted(_GENERIC_ACTION_ONLY_TOKENS, key=len, reverse=True):
        if len(generic_w) >= 2:
            eff_clean = re.sub(re.escape(generic_w), " ", eff_clean, flags=re.IGNORECASE)
    residual_content = re.sub(r"[\s\-—:.,!?/]+", "", eff_clean)

    if (not meaningful_tokens and not attachment.strip()) or (len(residual_content) < 2 and not attachment.strip()):
        issues.append("underspecified_target")
        questions.extend([
            "งานนี้ต้องการจัดการกับส่วนไหนหรือโดเมนใดของระบบ (เช่น ไฟล์ โมดูล API หรือชุดข้อมูลใด)?",
            "ผลลัพธ์ที่ต้องการส่งมอบคืออะไร และมีเงื่อนไขตรวจสอบความสำเร็จแบบใดบ้าง?",
        ])
        return {
            "raw_prompt": prompt,
            "wrapper_kind": wrapper_kind,
            "objective": "",
            "is_actionable_goal": False,
            "requirements": [],
            "context_hints": [],
            "expected_deliverables": [],
            "clarity_status": "INCOMPLETE",
            "issues": issues,
            "clarification_questions": questions,
        }

    low = effective.lower()
    context_hints: list[str] = []
    for fm in _FILE_MENTION_RE.findall(effective):
        if fm not in context_hints:
            context_hints.append(f"file:{fm}")
    if any(k in low for k in ("python", ".py", "pytest", "unittest", "zyrquen_core")):
        context_hints.append("stack:python")
    if any(k in low for k in ("typescript", "tsx", "react", "vite", "express", "server.ts")):
        context_hints.append("stack:typescript")
    if any(k in low for k in ("sqlite", "database", "db", "ฐานข้อมูล", "schema", "sql")):
        context_hints.append("domain:database")
    if any(k in low for k in ("api", "endpoint", "rest", "route")):
        context_hints.append("domain:api")
    if any(k in low for k in ("ui", "หน้าจอ", "frontend", "react", "component", "เว็บ", "แอป")):
        context_hints.append("domain:ui")
    if any(k in low for k in ("dataset", "train", "checkpoint", "ngram", "neural", "ฝึกโมเดล", "ประเมินผล", "benchmark")):
        context_hints.append("domain:native_ml")
    if any(k in low for k in ("กราฟความรู้", "knowledge graph", "triple", "ความจำ")):
        context_hints.append("domain:knowledge_graph")
    if any(k in low for k in ("security", "audit", "rbac", "approval", "ความปลอดภัย")):
        context_hints.append("domain:security")

    expected_deliverables: list[str] = []
    if wrapper_kind == "create_document" or any(k in low for k in ("เอกสาร", "รายงาน", "คู่มือ", "document", "spec", "markdown", "readme", "report")):
        expected_deliverables.append("markdown_document")
    if wrapper_kind == "create_data" or any(k in low for k in ("csv", "json", "ตาราง", "schema", "dataset", "โครงสร้างข้อมูล")):
        expected_deliverables.append("structured_data_schema")
    if wrapper_kind == "create_software" or any(k in low for k in ("โค้ด", "โมดูล", "ฟังก์ชัน", "แก้ไข", "บั๊ก", "bug", "fix", "implement", "refactor", "module", "code", "api", "ระบบ", "แอป")):
        expected_deliverables.append("verified_source_code")
    if any(k in low for k in ("test", "ทดสอบ", "unittest", "vitest", "verify", "ตรวจ")):
        expected_deliverables.append("test_verification_report")
    if not expected_deliverables:
        expected_deliverables.append("structured_action_plan")

    return {
        "raw_prompt": prompt,
        "wrapper_kind": wrapper_kind,
        "objective": objective,
        "is_actionable_goal": True,
        "requirements": requirements,
        "context_hints": context_hints,
        "expected_deliverables": expected_deliverables,
        "clarity_status": "VALID",
        "issues": [],
        "clarification_questions": [],
    }


def _walk_repo_files(repo_root: Path, max_files: int = 400) -> list[str]:
    files: list[str] = []
    if not repo_root.exists():
        return files
    for root_name in ("python_core", "src", "apps", "tests", ".github"):
        base = repo_root / root_name
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if any(part in _SKIP_REPO_DIRS for part in p.parts):
                continue
            if p.is_file() and p.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".md", ".json", ".yml", ".yaml"}:
                files.append(str(p.relative_to(repo_root)))
                if len(files) >= max_files:
                    return files
    for top_name in ("server.ts", "package.json", "tsconfig.json", "vitest.config.ts"):
        tp = repo_root / top_name
        if tp.is_file():
            files.append(top_name)
    return files


def resolve_underspecified_goal_with_context(
    conn: sqlite3.Connection,
    goal_info: dict[str, Any],
    repo_ctx: dict[str, Any],
    *,
    repo_root: Path,
    recent_context: list[str] | None = None,
) -> dict[str, Any]:
    """
    Context-Aware Goal Resolution:
    When a user goal has `underspecified_target`, infer concrete candidate goals
    from verified repository artifacts, active SQLite runs/datasets/checkpoints,
    and optional conversation context. Never fabricates files/state and never
    authorizes risky/mutating actions without explicit user confirmation.
    """
    issues = list(goal_info.get("issues") or [])
    if goal_info.get("clarity_status") == "INVALID_CORRUPT" or "underspecified_target" not in issues:
        return {
            "attempted": False,
            "resolved_from_context": False,
            "candidate_count": 0,
            "candidates": [],
            "missing_dimensions": [],
            "auto_execution_blocked": True,
            "requires_user_confirmation": True,
        }

    raw_l = str(goal_info.get("raw_prompt") or "").lower()
    ctx_text = " ".join(str(x) for x in (recent_context or [])).lower()
    combined = f"{raw_l} {ctx_text}".strip()
    sql_st = repo_ctx.get("sqlite_state") or {}

    all_files = _walk_repo_files(repo_root)
    workflow_files = [f for f in all_files if f.startswith(".github/workflows/")]
    sampler_files = [f for f in all_files if "StageAwareSampler" in f or f.startswith("apps/core/native/train/")]

    candidates: list[dict[str, Any]] = []

    # 1. Recent missions / workflow runs in SQLite
    try:
        recent_missions = conn.execute(
            "SELECT id, goal, status FROM autonomous_missions ORDER BY updated_at DESC LIMIT 3"
        ).fetchall()
    except sqlite3.Error:
        recent_missions = []

    for m in recent_missions:
        m_goal = str(m["goal"] or "").strip()
        if m_goal:
            candidates.append({
                "candidate_id": f"mission:{m['id'][:8]}",
                "domain": "Active Autonomous Mission",
                "proposed_objective": f"ตรวจสอบและสานต่อภารกิจล่าสุด: {m_goal}",
                "expected_deliverables": ["สถานะการดำเนินงานจริง", "ผลตรวจสอบหลังดำเนินการ"],
                "success_criteria": "ภารกิจผ่านการตรวจสอบตามขั้นตอนและไม่เปลี่ยนสถานะที่ต้องอนุมัติโดยพลการ",
                "grounded_evidence": [f"autonomous_missions:{m['id'][:8]} (status={m['status']})"],
                "risk_level": "MEDIUM",
                "requires_confirmation": True,
            })
            break

    # 2. GitHub / CI / PR context (when mentioned in prompt or recent context, and workflow files exist)
    pr_refs = re.findall(r"(?:pr\s*#?|#)(\d+)", combined, flags=re.IGNORECASE)
    wants_ci_or_git = bool(pr_refs) or any(
        tok in combined for tok in ("github", "pull request", "ci", "merge", "conflict", "branch", "workflow")
    )
    if workflow_files and (wants_ci_or_git or not candidates):
        pr_label = f"PR #{', #'.join(dict.fromkeys(pr_refs))}" if pr_refs else "CI Workflows / Pull Requests"
        candidates.append({
            "candidate_id": "ctx:github_ci",
            "domain": "GitHub Repository & CI Workflows",
            "proposed_objective": f"ตรวจสอบ {pr_label}, แยกแยะข้อขัดแย้งของโค้ด/การทดสอบ และรายงานผล CI แบบ Read-Only",
            "expected_deliverables": ["รายการปัญหา/ข้อขัดแย้งที่พบ", "ผลการตรวจ Syntax และชุดทดสอบ CI"],
            "success_criteria": "ไม่มี merge conflicts, ชุดทดสอบผ่าน และไม่แก้ไข branch main โดยไม่ได้รับอนุญาต",
            "grounded_evidence": workflow_files[:3],
            "risk_level": "HIGH" if any(k in combined for k in ("merge", "push", "commit")) else "LOW",
            "requires_confirmation": True,
        })

    # 3. Native Training & StageAwareSampler context
    clean_ds = sql_st.get("clean_datasets") or []
    leaked_ds = sql_st.get("leaked_datasets") or []
    pending_runs = sql_st.get("pending_runs") or []
    if sampler_files or clean_ds or leaked_ds or pending_runs:
        evidence = list(sampler_files[:3])
        if clean_ds:
            evidence.append(f"dataset:{clean_ds[0]['name']} (records={clean_ds[0]['total_records']}, leakage=0)")
        elif leaked_ds:
            evidence.append(f"leaked_dataset:{leaked_ds[0]['name']}")
        if pending_runs:
            evidence.append(f"pending_approval_runs:{len(pending_runs)}")
        candidates.append({
            "candidate_id": "ctx:native_training",
            "domain": "Native Training & Data Pipeline",
            "proposed_objective": "ตรวจสอบความพร้อมของข้อมูลฝึก Provenance, Data Leakage และการสุ่มแบบ StageAwareSampler",
            "expected_deliverables": ["ผลตรวจ Integrity/Leakage", "ผลการทดสอบ StageAwareSampler"],
            "success_criteria": "ไม่มี Data Leakage, ผ่านเกณฑ์ Provenance และไม่เริ่มฝึกจริงก่อนผ่าน Approval Gate",
            "grounded_evidence": evidence[:4],
            "risk_level": "HIGH",
            "requires_confirmation": True,
        })

    # 4. Knowledge Graph contradictions context
    contradictions = int(sql_st.get("contradictions") or 0)
    triple_rows = sql_st.get("triple_rows") or []
    if contradictions > 0 or triple_rows:
        candidates.append({
            "candidate_id": "ctx:knowledge_graph",
            "domain": "Knowledge Graph & Memory",
            "proposed_objective": (
                f"ตรวจสอบและแยกแยะความขัดแย้งในกราฟความรู้ ({contradictions} กลุ่ม)"
                if contradictions > 0
                else f"ตรวจสอบความครอบคลุมของ Provenance ในกราฟความรู้ ({len(triple_rows)} รายการ)"
            ),
            "expected_deliverables": ["รายงานความสอดคล้องและแหล่งที่มาของความรู้"],
            "success_criteria": "ไม่มีความรู้ขัดแย้งที่ยังไม่ตรวจสอบและทุก Triple มี Provenance",
            "grounded_evidence": [f"knowledge_triples:{len(triple_rows)} (contradictions={contradictions})"],
            "risk_level": "LOW",
            "requires_confirmation": True,
        })

    candidates = candidates[:3]
    missing_dims = ["target_selection", "confirmation_for_risky_action"]
    if not any("test" in c_txt for c_txt in (combined,)):
        missing_dims.append("success_verification_criteria")

    return {
        "attempted": True,
        "resolved_from_context": bool(candidates),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "missing_dimensions": missing_dims,
        "auto_execution_blocked": True,
        "requires_user_confirmation": True,
    }


def inspect_repository_context(
    conn: sqlite3.Connection,
    tc_reg: Any,
    goal_info: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """
    B. Context-Aware Planning (Strictly Read-Only):
    Inspect real repo files, real ToolCenterRegistry capabilities, and SQLite state.
    Never invents file paths, modules, or capability IDs.
    """
    all_repo_files = _walk_repo_files(repo_root)
    all_repo_set = set(all_repo_files)
    objective_l = str(goal_info.get("objective") or "").lower()
    req_l = " ".join(goal_info.get("requirements") or []).lower()
    combined_l = f"{objective_l} {req_l}"

    # 1. Explicit file mentions verified against disk
    mentioned_existing: list[str] = []
    mentioned_missing: list[str] = []
    for hint in goal_info.get("context_hints") or []:
        if hint.startswith("file:"):
            rel = hint.split(":", 1)[1].lstrip("./")
            if rel in all_repo_set or (repo_root / rel).is_file():
                mentioned_existing.append(rel)
            else:
                matches = [f for f in all_repo_files if f.endswith("/" + rel) or Path(f).name == Path(rel).name]
                if matches:
                    mentioned_existing.extend(matches[:3])
                else:
                    mentioned_missing.append(rel)

    # 2. Keyword relevance scoring against real repo files
    kw_tokens = [
        tok for tok in re.findall(r"[a-z0-9_]{3,}", combined_l)
        if tok not in {"the", "and", "for", "with", "from", "this", "that", "plan", "create", "build", "fix", "test"}
    ]
    scored_files: list[tuple[int, str]] = []
    for rel in all_repo_files:
        rel_l = rel.lower()
        score = 0
        for tok in kw_tokens:
            if tok in rel_l:
                score += 3
        if "workflow" in combined_l and "workflow" in rel_l:
            score += 2
        if any(k in combined_l for k in ("planner", "dag", "วางแผน")) and ("planner" in rel_l or "dag" in rel_l or "zyrquen_core" in rel_l):
            score += 2
        if any(k in combined_l for k in ("ui", "frontend", "react", "component", "workspace")) and rel.startswith("src/"):
            score += 1
        if any(k in combined_l for k in ("api", "server", "express", "route")) and ("server.ts" in rel_l):
            score += 2
        if any(k in combined_l for k in ("test", "ทดสอบ", "vitest", "unittest")) and ("test" in rel_l):
            score += 2
        if score > 0:
            scored_files.append((score, rel))

    scored_files.sort(key=lambda item: (-item[0], item[1]))
    relevant_files = list(dict.fromkeys(mentioned_existing + [rel for _, rel in scored_files]))[:8]

    # 3. Registered ToolCenterRegistry capabilities (verified only)
    registered_caps: set[str] = set()
    composed_caps: list[str] = []
    if tc_reg is not None:
        registered_caps = set(getattr(tc_reg, "_capabilities", {}).keys())
        try:
            tc_plan = tc_reg.compose_for_goal(
                goal_info.get("objective") or "analyze workspace",
                user_role="user",
                conn=conn,
            )
            for item in tc_plan.get("selected_capabilities") or []:
                cid = str(item.get("capability_id") or "")
                if cid in registered_caps and cid not in composed_caps:
                    composed_caps.append(cid)
        except Exception:
            pass

    # 4. Real SQLite snapshot
    ds_rows = conn.execute(
        "SELECT id, name, total_records, leakage_detected, status FROM datasets ORDER BY created_at DESC"
    ).fetchall()
    ckpt_rows = conn.execute(
        "SELECT id, version, perplexity, eval_accuracy, eval_status FROM checkpoints ORDER BY version DESC"
    ).fetchall()
    eval_rows = conn.execute(
        "SELECT id, overall_status, checkpoint_version, created_at FROM evaluations ORDER BY created_at DESC LIMIT 1"
    ).fetchall()
    triple_rows = conn.execute("SELECT subject, relation, object FROM knowledge_triples").fetchall()
    pending_runs = conn.execute(
        "SELECT id, group_id FROM workflow_runs WHERE status='PENDING_APPROVAL'"
    ).fetchall()

    pairs: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for r in triple_rows:
        pairs[(r["subject"].lower(), r["relation"].lower())].add(r["object"].lower())
    contradictions = sum(1 for objs in pairs.values() if len(objs) > 1)
    clean_datasets = [d for d in ds_rows if not d["leakage_detected"] and d["total_records"] >= 5]
    leaked_datasets = [d for d in ds_rows if d["leakage_detected"]]

    return {
        "repo_root": str(repo_root),
        "total_repo_files": len(all_repo_files),
        "relevant_files": relevant_files,
        "mentioned_missing_files": mentioned_missing,
        "registered_capabilities": registered_caps,
        "composed_capabilities": composed_caps,
        "sqlite_state": {
            "ds_rows": ds_rows,
            "clean_datasets": clean_datasets,
            "leaked_datasets": leaked_datasets,
            "ckpt_rows": ckpt_rows,
            "eval_rows": eval_rows,
            "triple_rows": triple_rows,
            "contradictions": contradictions,
            "pending_runs": pending_runs,
        },
    }


def _filter_registered_caps(candidates: list[str], registered: set[str]) -> list[str]:
    if not registered:
        return []
    return [c for c in candidates if c in registered]


def _enrich_dag_node(
    node: dict[str, Any],
    *,
    goal: str,
    registered_caps: set[str],
    default_risk: str = "LOW",
    check_type: str = "source_code",
) -> dict[str, Any]:
    deps = list(node.get("depends_on") or [])
    req_caps = _filter_registered_caps(list(node.get("required_capabilities") or []), registered_caps)
    if not req_caps and node.get("tool_id") in registered_caps:
        req_caps = [str(node["tool_id"])]
    tool_id = str(node.get("tool_id") or (req_caps[0] if req_caps else node.get("workflow_group") or "native_planner"))

    # Strict State Machine Rule:
    # A step is READY strictly iff ALL dependencies are COMPLETED (for an unexecuted initial plan,
    # only root steps with depends_on == [] can be READY; downstream steps MUST start BLOCKED).
    if deps:
        initial_status = "BLOCKED"
    elif node.get("_precondition_blocked"):
        initial_status = "BLOCKED"
    else:
        initial_status = "READY"

    requires_approval = bool(node.get("requires_approval", False))
    permission = "approval_required" if requires_approval else str(node.get("permission") or "auto")
    preconditions = list(node.get("preconditions") or [])
    for d in deps:
        dep_pre = f"dependency_completed:{d}"
        if dep_pre not in preconditions:
            preconditions.append(dep_pre)
    postconditions = list(node.get("postconditions") or ["output_contract_validated", "execution_evidence_recorded"])

    enriched = {
        "step_id": str(node["step_id"]),
        "task_id": str(node["step_id"]),
        "objective": str(node.get("objective") or node["title"]),
        "title": str(node["title"]),
        "workflow_group": str(node["workflow_group"]),
        "target_files": list(node.get("target_files") or []),
        "input_contract": node.get("input_contract") or {"required_keys": ["goal"], "goal": goal},
        "expected_output": str(node.get("expected_output") or node.get("detail") or ""),
        "output_contract": node.get("output_contract")
        or {"required_keys": ["status"], "disallow_statuses": ["FAILED", "BLOCKED"]},
        "dependencies": deps,
        "depends_on": deps,
        "required_capabilities": req_caps,
        "tool_id": tool_id,
        "permission": permission,
        "approval_policy": "approval_required" if requires_approval else "auto",
        "risk_level": str(node.get("risk_level") or ("HIGH" if requires_approval else default_risk)),
        "verification_criteria": node.get("verification_criteria")
        or {
            "check_type": check_type,
            "preconditions": preconditions,
            "postconditions": postconditions,
            "requires_real_execution_evidence": True,
        },
        "preconditions": preconditions,
        "postconditions": postconditions,
        "failure_policy": str(node.get("failure_policy") or "halt_downstream_and_block"),
        "retry_policy": node.get("retry_policy")
        or {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
        "requires_approval": requires_approval,
        "status": initial_status,
        "execution_status": initial_status,
        "detail": str(node.get("detail") or ""),
    }
    return enriched


def _validate_plan_dag(steps: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if not steps:
        return True, None
    step_ids = [s["step_id"] for s in steps]
    if len(set(step_ids)) != len(step_ids):
        return False, "Duplicate step_id in generated plan"
    id_set = set(step_ids)
    adj: dict[str, list[str]] = collections.defaultdict(list)
    for st in steps:
        sid = st["step_id"]
        for dep in st.get("depends_on") or []:
            if dep not in id_set or dep == sid:
                return False, f"Invalid dependency '{dep}' on step '{sid}'"
            adj[dep].append(sid)

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(nid: str) -> bool:
        if nid in visiting:
            return False
        if nid in visited:
            return True
        visiting.add(nid)
        for nxt in adj.get(nid, []):
            if not dfs(nxt):
                return False
        visiting.remove(nid)
        visited.add(nid)
        return True

    if not all(dfs(sid) for sid in step_ids):
        return False, "Cycle detected in plan DAG"
    return True, None


def build_context_aware_dag_plan(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    tc_reg: Any = None,
    repo_root: Path | None = None,
    force_plan: bool = False,
    recent_context: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Main entry point for ZYRQUEN Native Context-Aware DAG Planning.
    Returns None only when `force_plan=False` and the prompt is not a planning command.
    Returns `NEEDS_CLARIFICATION` with 0 steps when the goal is invalid or incomplete.
    """
    raw = str(prompt or "").strip()
    unwrapped = unwrap_command_wrapper(raw)
    is_explicit_plan = unwrapped["wrapper_kind"] in {
        "plan_prefix",
        "create_software",
        "create_document",
        "create_data",
    }
    if not is_explicit_plan and not force_plan:
        return None

    goal_info = analyze_planner_goal(raw)
    actual_repo_root = repo_root or Path(__file__).resolve().parent.parent

    if tc_reg is None:
        try:
            from tool_center import get_tool_center_registry
            tc_reg = get_tool_center_registry()
        except Exception:
            tc_reg = None

    repo_ctx = inspect_repository_context(conn, tc_reg, goal_info, actual_repo_root)
    sql_st = repo_ctx["sqlite_state"]
    state_snapshot = {
        "clean_datasets": len(sql_st["clean_datasets"]),
        "checkpoints": len(sql_st["ckpt_rows"]),
        "triples": len(sql_st["triple_rows"]),
        "pending_approvals": len(sql_st["pending_runs"]),
    }

    if goal_info["clarity_status"] != "VALID" or not goal_info.get("is_actionable_goal"):
        context_resolution = resolve_underspecified_goal_with_context(
            conn,
            goal_info,
            repo_ctx,
            repo_root=actual_repo_root,
            recent_context=recent_context,
        )
        questions = list(goal_info["clarification_questions"])
        if context_resolution["resolved_from_context"]:
            cand_summaries = [
                f"[{idx + 1}] {c['domain']}: {c['proposed_objective']}"
                for idx, c in enumerate(context_resolution["candidates"])
            ]
            questions = [
                "ระบบดึงบริบทจากงานปัจจุบันมาตีความเป้าหมายที่เป็นไปได้: " + " | ".join(cand_summaries),
                "กรุณายืนยันว่าจะเลือกเป้าหมายใด (หรือระบุเป้าหมายเฉพาะเพิ่มเติม) ก่อนที่ระบบจะสร้างแผนหรือเริ่มขั้นตอนที่มีความเสี่ยง",
            ]
            goal_info = {
                **goal_info,
                "context_resolution": context_resolution,
                "clarification_questions": questions,
            }
        else:
            goal_info = {
                **goal_info,
                "context_resolution": context_resolution,
            }

        return {
            "engine": "native_planner",
            "domain_mode": "clarification_required",
            "plan_status": "NEEDS_CLARIFICATION",
            "status": "NEEDS_CLARIFICATION",
            "goal": "",
            "is_actionable_goal": False,
            "plan_valid": False,
            "goal_interpretation": goal_info,
            "context_resolution": context_resolution,
            "issues": goal_info["issues"],
            "clarification_questions": questions,
            "status_transitions": [
                {
                    "from_status": "RECEIVED",
                    "to_status": "NEEDS_CLARIFICATION",
                    "reason": ",".join(goal_info["issues"]) or "invalid_or_incomplete_goal",
                }
            ],
            "repo_context": {
                "relevant_files": repo_ctx["relevant_files"],
                "mentioned_missing_files": repo_ctx["mentioned_missing_files"],
            },
            "steps": [],
            "summary": {
                "total_steps": 0,
                "ready_steps": 0,
                "blocked_steps": 0,
                "approval_gated_steps": 0,
                "state_snapshot": state_snapshot,
            },
        }

    goal = goal_info["objective"]
    goal_l = f"{goal} {' '.join(goal_info['requirements'])}".lower()
    reg_caps = repo_ctx["registered_capabilities"]
    rel_files = repo_ctx["relevant_files"]

    wants_train = any(k in goal_l for k in ["ฝึกโมเดล", "ฝึก", "โมเดล", "train", "checkpoint", "เตรียมข้อมูล", "ชุดข้อมูล", "data leakage", "ngram", "ngi"])
    wants_eval = any(k in goal_l for k in ["ประเมินผล", "ประเมิน", "eval", "benchmark", "baseline", "held-out", "perplexity"])
    wants_knowledge = any(k in goal_l for k in ["กราฟความรู้", "ความจำ", "knowledge graph", "triple", "zyrquen"])
    wants_ops = any(k in goal_l for k in ["ความปลอดภัยระบบ", "audit", "approval gate", "sqlite", "zyrquen", "security"])

    is_mlops_goal = wants_train or wants_eval or wants_knowledge or wants_ops

    raw_steps: list[dict[str, Any]] = []
    if is_mlops_goal:
        domain_mode = "mlops_native"
        engine_name = "native_planner"
        ds_rows = sql_st["ds_rows"]
        ckpt_rows = sql_st["ckpt_rows"]
        triple_rows = sql_st["triple_rows"]
        clean_datasets = sql_st["clean_datasets"]
        leaked_datasets = sql_st["leaked_datasets"]
        contradictions = sql_st["contradictions"]
        eval_rows = sql_st["eval_rows"]
        pending_runs = sql_st["pending_runs"]

        raw_steps.append({
            "step_id": "S1",
            "title": "ตรวจสุขภาพระบบและทรัพยากรเครื่องจริง (System Operations)",
            "objective": f"ตรวจสอบทรัพยากร Runtime และสถานะ SQLite สำหรับเป้าหมาย '{goal}'",
            "workflow_group": "system_ops",
            "target_files": [f for f in rel_files if f.endswith("zyrquen_core.py")][:2] or ["python_core/zyrquen_core.py"],
            "depends_on": [],
            "required_capabilities": ["api_integration.internal_health", "data.db_inspect"],
            "tool_id": "api_integration.internal_health",
            "requires_approval": False,
            "expected_output": "รายงานสุขภาพ SQLite, CPU/RAM/Disk และความพร้อมของแกน Native Core",
            "detail": f"SQLite มีข้อมูล {len(ds_rows)} ชุด, {len(ckpt_rows)} Checkpoint, {len(triple_rows)} ความจำ",
        })

        if wants_knowledge or contradictions > 0:
            raw_steps.append({
                "step_id": "S2",
                "title": "ตรวจสอบความสอดคล้องของกราฟความรู้",
                "objective": "ตรวจสอบความสัมพันธ์และกลุ่มขัดแย้งใน knowledge_triples",
                "workflow_group": "knowledge_memory",
                "target_files": [f for f in rel_files if "memory" in f or "zyrquen_core" in f][:2],
                "depends_on": ["S1"],
                "required_capabilities": ["research.knowledge_retriever", "research.contradiction_resolution"],
                "tool_id": "research.knowledge_retriever",
                "requires_approval": False,
                "expected_output": "ผลตรวจสอบจำนวน Triple, Provenance และกลุ่มความขัดแย้ง",
                "detail": (
                    f"รอ S1 เสร็จก่อน — พบข้อขัดแย้ง {contradictions} กลุ่มในกราฟความรู้"
                    if contradictions > 0
                    else (
                        f"รอ S1 เสร็จก่อน — ปัจจุบันมี {len(triple_rows)} รายการในกราฟความรู้"
                        if triple_rows
                        else "รอ S1 เสร็จก่อน — ปัจจุบันกราฟความรู้ยังว่าง (0 รายการ)"
                    )
                ),
            })

        if wants_train:
            ds_detail = (
                f"รอ S1 เสร็จก่อน — มีชุดข้อมูลผ่านเกณฑ์ {len(clean_datasets)} ชุด (ล่าสุด: {clean_datasets[0]['name']})"
                if clean_datasets
                else (
                    f"รอ S1 เสร็จก่อน — พบ Data Leakage ในชุดข้อมูล {len(leaked_datasets)} ชุด"
                    if leaked_datasets
                    else "รอ S1 เสร็จก่อน — ยังไม่มีชุดข้อมูลผ่านเกณฑ์ (>= 5 รายการ)"
                )
            )
            raw_steps.append({
                "step_id": "S3",
                "title": "ตรวจสอบ Data Leakage และ Split Train/Val/Test",
                "objective": "ตรวจสอบ SHA-256 manifest, provenance และ zero-leakage splits",
                "workflow_group": "data_pipeline",
                "target_files": [f for f in rel_files if "dataset" in f or "zyrquen_core" in f][:2],
                "depends_on": ["S1"],
                "required_capabilities": ["data.leakage_check", "data.dataset_lineage"],
                "tool_id": "data.leakage_check",
                "requires_approval": False,
                "expected_output": "ผลยืนยันความถูกต้องของชุดข้อมูลและ Train/Val/Test split",
                "detail": ds_detail,
            })

            raw_steps.append({
                "step_id": "S4",
                "title": "ฝึก Checkpoint โมเดลภายในผ่าน Approval Gate",
                "objective": "ส่งคำขอ Admin Approval Gate และฝึก Checkpoint ใหม่แบบไม่เขียนทับ",
                "workflow_group": "native_training",
                "target_files": [f for f in rel_files if "zyrquen_core" in f or "neural" in f][:2],
                "depends_on": ["S3"],
                "required_capabilities": ["automation.workflow_execute", "testing.dataset_verify"],
                "tool_id": "automation.workflow_execute",
                "requires_approval": True,
                "risk_level": "HIGH",
                "expected_output": "Checkpoint รุ่นใหม่แบบ versioned พร้อมบันทึก train/val loss",
                "detail": (
                    f"รอ S3 เสร็จก่อน และต้องผ่าน Admin Approval Gate (ปัจจุบันมี {len(ckpt_rows)} Checkpoint, รออนุมัติ {len(pending_runs)} งาน)"
                    if clean_datasets
                    else "รอ S3 เสร็จก่อน — ต้องมีชุดข้อมูลที่ผ่านการตรวจ Data Leakage และผ่าน Admin Approval Gate"
                ),
            })

        if wants_eval or wants_train:
            eval_deps = ["S4"] if wants_train else ["S1"]
            raw_steps.append({
                "step_id": "S5",
                "title": "รันชุดประเมินผลเชิงวิทยาศาสตร์และเทียบ Baseline",
                "objective": "ประเมิน AST, Knowledge, Planning และ Held-out Checkpoint เทียบ Baseline",
                "workflow_group": "evaluation",
                "target_files": [f for f in rel_files if "benchmark" in f or "eval" in f or "zyrquen_core" in f][:2],
                "depends_on": eval_deps,
                "required_capabilities": ["testing.engineering_benchmark", "testing.contract_assertion"],
                "tool_id": "testing.engineering_benchmark",
                "requires_approval": False,
                "expected_output": "Evaluation Report แยกสถานะ VERIFIED / PARTIAL / FAILED ตามหลักฐานจริง",
                "detail": (
                    f"รอ {','.join(eval_deps)} เสร็จก่อน — ผลประเมินล่าสุด: {eval_rows[0]['overall_status']}"
                    if eval_rows
                    else (
                        f"รอ {','.join(eval_deps)} เสร็จก่อน — พร้อมทดสอบกับ Checkpoint v{ckpt_rows[0]['version']}"
                        if ckpt_rows
                        else f"รอ {','.join(eval_deps)} เสร็จก่อน — Held-out Test จะรายงาน NOT_RUN จนกว่าจะมี Checkpoint"
                    )
                ),
            })

        if wants_ops:
            raw_steps.append({
                "step_id": "S6",
                "title": "ตรวจสอบความสมบูรณ์ของซอร์สโค้ดและ Audit Logs",
                "objective": "ตรวจสอบ SHA-256 ของโมดูลหลักและเหตุการณ์ใน audit_logs",
                "workflow_group": "security_governance",
                "target_files": ["python_core/zyrquen_core.py", "server.ts"],
                "depends_on": ["S1"],
                "required_capabilities": ["security.artifact_integrity", "security.governance_audit"],
                "tool_id": "security.governance_audit",
                "requires_approval": False,
                "expected_output": "ผลตรวจ integrity hash และ immutable audit trail",
                "detail": f"รอ S1 เสร็จก่อน — งานรออนุมัติปัจจุบัน {len(pending_runs)} รายการ",
            })

        enriched_steps = [
            _enrich_dag_node(
                st,
                goal=goal,
                registered_caps=reg_caps,
                check_type="trained_model" if st["workflow_group"] in {"native_training", "evaluation"} else "readonly_audit",
            )
            for st in raw_steps
        ]
    else:
        # Context-aware General Software / Engineering / Document / Data Planning
        # Omit generic CRUD/DB/API/UI steps unless the task explicitly requires them.
        domain_mode = "general_engineering"
        engine_name = "native_planner_domain_adaptive"

        has_thai = any(k in goal_l for k in ("ภาษาไทย", "ไทย", "thai"))
        is_recommender = any(k in goal_l for k in ("แนะนำ", "recommend", "ranking", "จัดอันดับ"))
        wants_bugfix = any(k in goal_l for k in ("แก้บั๊ก", "บั๊ก", "bug", "error", "traceback", "วินิจฉัย", "debug", "fix", "repair", "ซ่อม"))
        wants_doc_only = (
            unwrapped["wrapper_kind"] == "create_document"
            or (
                any(k in goal_l for k in ("เอกสาร", "รายงาน", "คู่มือ", "document", "spec", "markdown", "readme"))
                and not any(k in goal_l for k in ("โค้ด", "โมดูล", "api", "ui", "code", "implement", "fix", "bug"))
            )
        )
        wants_data_modeling = any(k in goal_l for k in (
            "ฐานข้อมูล", "database", "sqlite", "sql", "schema", "csv", "json", "ตาราง", "คลังสินค้า",
            "จอง", "แนะนำ", "ข้อมูล", "model", "data", "entity", "หนังสือ", "recommend",
        ))
        wants_api = any(k in goal_l for k in ("api", "endpoint", "rest", "route", "webhook", "backend", "เซิร์ฟเวอร์", "express"))
        wants_ui = any(k in goal_l for k in ("ui", "หน้าจอ", "frontend", "react", "component", "เว็บ", "แอป", "dashboard", "ออนไลน์"))
        wants_refactor_or_code = (
            not wants_doc_only
            or any(k in goal_l for k in ("โค้ด", "โมดูล", "ฟังก์ชัน", "implement", "module", "code", "script", "สคริปต์", "แก้ไข", "พัฒนา", "สร้างระบบ"))
        )

        # Pick only real existing files relevant to the task
        target_slice = rel_files[:4]

        raw_steps.append({
            "step_id": "S1",
            "title": (
                f"วินิจฉัยตำแหน่งโค้ดและสาเหตุของปัญหา: {goal}"
                if wants_bugfix
                else f"วิเคราะห์ขอบเขต บริบท Repository และเกณฑ์รับรอง: {goal}"
            ),
            "objective": f"สำรวจไฟล์เป้าหมายและความสามารถที่มีอยู่จริงสำหรับ '{goal}' (Read-Only)",
            "workflow_group": "domain_requirements",
            "target_files": target_slice,
            "depends_on": [],
            "required_capabilities": (
                ["development.error_diagnosis", "development.symbol_search", "development.code_analysis"]
                if wants_bugfix
                else ["development.code_analysis", "development.symbol_search"]
            ),
            "tool_id": "development.error_diagnosis" if wants_bugfix else "development.code_analysis",
            "requires_approval": False,
            "expected_output": "รายการไฟล์เป้าหมาย สัญลักษณ์ที่เกี่ยวข้อง และเกณฑ์ทดสอบความถูกต้อง",
            "detail": (
                f"ตรวจบริบทจริงใน Workspace ({len(target_slice)} ไฟล์ที่เกี่ยวข้อง: {', '.join(target_slice) or 'ตามเป้าหมายใหม่'}) "
                + "โดยไม่แก้ไฟล์ในขั้นวางแผน"
            ),
        })
        last_step = "S1"

        if wants_data_modeling and not wants_bugfix:
            data_detail = (
                f"ออกแบบโครงสร้างข้อมูลและกลไกตัดคำภาษาไทยสำหรับ '{goal}'"
                if has_thai
                else f"ออกแบบ Schema เอนทิตีและข้อจำกัดความถูกต้องของข้อมูลสำหรับ '{goal}'"
            )
            raw_steps.append({
                "step_id": "S2",
                "title": "ออกแบบโครงสร้างข้อมูลและสัญญาอินพุต-เอาต์พุต (Data Modeling)",
                "objective": "กำหนดโครงสร้างข้อมูล Schema และสัญญาการตรวจสอบความถูกต้อง",
                "workflow_group": "data_modeling",
                "target_files": [f for f in target_slice if f.endswith(("types.ts", "db_bridge.py", "zyrquen_core.py"))][:2],
                "depends_on": ["S1"],
                "required_capabilities": ["data.schema_inference", "development.contract_validate"],
                "tool_id": "development.contract_validate",
                "requires_approval": False,
                "expected_output": "นิยาม Schema/Type Contract พร้อมกฎตรวจสอบขอบเขตข้อมูล",
                "detail": f"รอ S1 เสร็จก่อน — {data_detail}",
            })
            last_step = "S2"

        if wants_doc_only and not wants_bugfix:
            raw_steps.append({
                "step_id": "S_DOC",
                "title": "ร่างเอกสารเชิงโครงสร้างจากหลักฐานจริงใน Repository",
                "objective": f"สังเคราะห์เอกสาร '{goal}' โดยอ้างอิงเฉพาะข้อมูลที่ตรวจสอบได้",
                "workflow_group": "document_synthesis",
                "target_files": target_slice,
                "depends_on": [last_step],
                "required_capabilities": ["document.spec_generate", "document.markdown_outline"],
                "tool_id": "document.spec_generate",
                "requires_approval": False,
                "expected_output": "เอกสาร Markdown ที่มีโครงสร้างชัดเจนและผ่านการตรวจ Secret/Path Scan",
                "detail": f"รอ {last_step} เสร็จก่อน — สร้างเอกสารพร้อมตรวจโครงสร้างหัวข้อ",
            })
            last_step = "S_DOC"
        elif wants_refactor_or_code or wants_bugfix:
            logic_detail = (
                "แก้ไขจุดบกพร่องแบบจำกัดขอบเขต (Bounded Patch) ในไฟล์เป้าหมายที่ตรวจพบ"
                if wants_bugfix
                else (
                    "พัฒนากลไกจัดอันดับ/แนะนำและการคำนวณคะแนนความเกี่ยวข้องที่ตรวจสอบผลลัพธ์ได้"
                    if is_recommender
                    else f"พัฒนาตรรกะแกนกลางและจัดการกรณี Edge Cases สำหรับ '{goal}'"
                )
            )
            raw_steps.append({
                "step_id": "S3",
                "title": (
                    "แก้ไขจุดบกพร่องแบบจำกัดขอบเขต (Bounded Patch)"
                    if wants_bugfix
                    else "พัฒนาตรรกะแกนกลางเฉพาะทาง (Core Domain Logic)"
                ),
                "objective": "แก้ไขหรือพัฒนาฟังก์ชันแกนกลางตามขอบเขตที่อนุมัติ",
                "workflow_group": "core_logic",
                "target_files": target_slice,
                "depends_on": [last_step],
                "required_capabilities": (
                    ["development.code_patch_apply", "development.refactor_engine"]
                    if wants_bugfix
                    else ["development.code_patch_apply", "development.code_analysis"]
                ),
                "tool_id": "development.code_patch_apply",
                "requires_approval": False,
                "risk_level": "MEDIUM",
                "expected_output": "ซอร์สโค้ดที่ผ่าน Static Syntax & Policy Audit",
                "detail": f"รอ {last_step} เสร็จก่อน — {logic_detail}",
            })
            last_step = "S3"

        # Add Interface / API / UI step ONLY when task actually involves API or UI!
        if (wants_api or wants_ui) and not wants_bugfix and not wants_doc_only:
            iface_files = [
                f for f in rel_files
                if (wants_api and f == "server.ts") or (wants_ui and f.startswith("src/components/"))
            ][:3]
            iface_caps = (
                ["development.api_implementation", "development.contract_validate"]
                if wants_api
                else ["development.frontend_a11y_audit", "development.contract_validate"]
            )
            iface_detail = (
                "เชื่อมต่อ Endpoint/API พร้อม Input Validation และ Parameterized Query"
                if wants_api and not wants_ui
                else (
                    "เชื่อมต่อส่วนติดต่อผู้ใช้ (UI) พร้อม Accessibility & Error Handling"
                    if wants_ui and not wants_api
                    else "เชื่อมต่อ API และส่วนติดต่อผู้ใช้พร้อม Input Validation และ Error Handling"
                )
            )
            raw_steps.append({
                "step_id": "S4",
                "title": "เชื่อมต่อส่วนติดต่อและตรวจสอบความถูกต้องของอินพุต (Interface Integration)",
                "objective": "ผสานชั้นติดต่อ API/UI ที่จำเป็นโดยยึดโครงสร้างเดิมของโปรเจกต์",
                "workflow_group": "interface_integration",
                "target_files": iface_files,
                "depends_on": [last_step],
                "required_capabilities": iface_caps,
                "tool_id": iface_caps[0],
                "requires_approval": False,
                "risk_level": "MEDIUM",
                "expected_output": "ส่วนเชื่อมต่อ API/UI ที่ผ่านการตรวจสอบ Contract และ Accessibility",
                "detail": f"รอ {last_step} เสร็จก่อน — {iface_detail}",
            })
            last_step = "S4"

        # Final Verification Step (Source-code verification, never demanding nonexistent ML checkpoints)
        existing_test_files = [f for f in rel_files if "test" in f.lower()][:3]
        raw_steps.append({
            "step_id": "S5",
            "title": "ตรวจสอบซอร์สโค้ดและรันการทดสอบเชิงประจักษ์ (Verification & Testing)",
            "objective": "รัน Static Validation, Security Scan, และชุดทดสอบจริงเพื่อยืนยันผลลัพธ์",
            "workflow_group": "verification_testing",
            "target_files": existing_test_files or target_slice,
            "depends_on": [last_step],
            "required_capabilities": [
                "development.test_discovery",
                "testing.sandbox_run",
                "testing.contract_assertion",
                "security.secret_and_path_scan",
            ],
            "tool_id": "testing.sandbox_run",
            "requires_approval": False,
            "expected_output": "หลักฐานการทดสอบ (Command, Exit Code, Assertions) พร้อมแยกการทดสอบเดิม vs สร้างใหม่",
            "detail": (
                f"รอ {last_step} เสร็จก่อน — ตรวจซอร์สโค้ดและรันการทดสอบจริง"
                + (f" (พบไฟล์ทดสอบที่เกี่ยวข้อง: {', '.join(existing_test_files)})" if existing_test_files else " (ยังไม่มีไฟล์ทดสอบเฉพาะ — จะสร้างและรันใน Sandbox)")
            ),
        })

        enriched_steps = [
            _enrich_dag_node(
                st,
                goal=goal,
                registered_caps=reg_caps,
                check_type="source_code",
            )
            for st in raw_steps
        ]

    dag_ok, dag_err = _validate_plan_dag(enriched_steps)
    steps_valid = bool(enriched_steps) and all(
        not _is_generic_placeholder(s.get("step_id", ""))
        and not _is_generic_placeholder(s.get("title", ""))
        and not _is_generic_placeholder(s.get("detail", ""))
        and s.get("status") in CANONICAL_DAG_STATES
        for s in enriched_steps
    )
    if not dag_ok or not steps_valid or _is_generic_placeholder(goal):
        reason = f"dag_validation_failed:{dag_err}" if not dag_ok else "invalid_plan_step_or_placeholder"
        return {
            "engine": engine_name,
            "domain_mode": domain_mode,
            "plan_status": "BLOCKED",
            "status": "BLOCKED",
            "goal": goal if not _is_generic_placeholder(goal) else "",
            "is_actionable_goal": False,
            "plan_valid": False,
            "goal_interpretation": goal_info,
            "issues": [reason],
            "clarification_questions": [],
            "status_transitions": [
                {
                    "from_status": "DRAFT",
                    "to_status": "BLOCKED",
                    "reason": reason,
                }
            ],
            "steps": [],
            "summary": {
                "total_steps": 0,
                "ready_steps": 0,
                "blocked_steps": 0,
                "approval_gated_steps": 0,
                "state_snapshot": state_snapshot,
            },
        }

    ready_count = sum(1 for s in enriched_steps if s["status"] == "READY")
    blocked_count = sum(1 for s in enriched_steps if s["status"] == "BLOCKED")
    approval_count = sum(1 for s in enriched_steps if s["requires_approval"])
    status_transitions = [
        {"from_status": "DRAFT", "to_status": "PLANNED", "reason": "goal_and_dag_validated"},
        *[
            {
                "step_id": s["step_id"],
                "from_status": "DRAFT",
                "to_status": s["status"],
                "reason": (
                    f"blocked_by:{','.join(s['depends_on'])}"
                    if s["depends_on"]
                    else "ready_no_dependencies"
                ),
            }
            for s in enriched_steps
        ],
    ]

    return {
        "engine": engine_name,
        "domain_mode": domain_mode,
        "plan_status": "PLANNED",
        "status": "PLANNED",
        "goal": goal,
        "is_actionable_goal": True,
        "plan_valid": True,
        "goal_interpretation": goal_info,
        "status_transitions": status_transitions,
        "repo_context": {
            "total_repo_files": repo_ctx["total_repo_files"],
            "relevant_files": rel_files,
            "mentioned_missing_files": repo_ctx["mentioned_missing_files"],
            "composed_capabilities": repo_ctx["composed_capabilities"],
        },
        "steps": enriched_steps,
        "summary": {
            "total_steps": len(enriched_steps),
            "ready_steps": ready_count,
            "blocked_steps": blocked_count,
            "approval_gated_steps": approval_count,
            "state_snapshot": state_snapshot,
        },
    }
