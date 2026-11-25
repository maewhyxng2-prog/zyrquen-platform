"""
Document Toolkit for ZYRQUEN Tool Center.
Provides Markdown outline/completeness analysis, deterministic conversation summarization,
and structured specification generation into workspace_files.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import tools_engine as te
import zyrquen_core as zc

from ..contracts import CapabilitySpec, ToolkitManifest

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_CODE_FENCE_RE = re.compile(r"^```")


def _handle_markdown_outline(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    content = str(payload.get("content") or "")
    if not content.strip():
        return {"ok": False, "status": "FAILED", "error": "content is required.", "output": {}}

    headings: list[dict[str, Any]] = []
    code_blocks = 0
    in_code = False
    lines = content.splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if _CODE_FENCE_RE.match(stripped):
            if not in_code:
                code_blocks += 1
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _HEADING_RE.match(line)
        if m:
            headings.append({
                "level": len(m.group(1)),
                "text": m.group(2).strip(),
                "line": idx,
            })

    word_count = len(re.findall(r"\S+", content))
    toc_lines = [f"{'  ' * (h['level'] - 1)}- {h['text']} (line {h['line']})" for h in headings]
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "heading_count": len(headings),
            "headings": headings,
            "toc_markdown": "\n".join(toc_lines),
            "code_block_count": code_blocks,
            "line_count": len(lines),
            "word_count": word_count,
            "has_h1": any(h["level"] == 1 for h in headings),
        },
        "summary": f"สกัดโครงสร้าง Markdown: {len(headings)} หัวข้อ, {code_blocks} บล็อกโค้ด, {len(lines)} บรรทัด",
    }


def _handle_conversation_summary(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conversation_id = str(payload.get("conversation_id") or "").strip()
    messages_input = payload.get("messages")
    messages: list[dict[str, Any]] = []

    if conversation_id:
        conn = ctx.get("conn")
        if conn is None:
            return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}
        uid = ctx.get("user_id")
        is_admin = str(ctx.get("user_role") or "").lower() == "admin"
        conv = conn.execute("SELECT id, user_id, title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            return {"ok": False, "status": "FAILED", "error": "Conversation not found.", "output": {}}
        if conv["user_id"] != uid and not is_admin:
            return {"ok": False, "status": "BLOCKED", "error": "Insufficient permission for this conversation.", "output": {}}
        messages = [
            dict(r)
            for r in conn.execute(
                "SELECT role, content, mode, trace_json, status, created_at FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        ]
    elif isinstance(messages_input, list):
        messages = [m for m in messages_input if isinstance(m, dict)]
    else:
        return {"ok": False, "status": "FAILED", "error": "conversation_id or messages list is required.", "output": {}}

    summary_obj = zc.summarize_conversation(messages)
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": summary_obj,
        "summary": (
            f"สรุปเอกสาร/บทสนทนาเชิงกำหนด ({summary_obj['metrics']['total_messages']} ข้อความ, "
            f"{len(summary_obj['bullets'])} ประเด็น)"
        ),
    }


def _handle_spec_generate(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    objective = str(payload.get("objective") or "").strip()
    if not title or not objective:
        return {"ok": False, "status": "FAILED", "error": "title and objective are required.", "output": {}}

    sections = payload.get("sections") or []
    constraints = payload.get("constraints") or []
    save_file = bool(payload.get("save_to_workspace", False))
    filename = str(payload.get("filename") or "").strip()

    lines = [
        f"# {title}",
        "",
        "## วัตถุประสงค์ (Objective)",
        objective,
        "",
    ]
    if isinstance(constraints, list) and constraints:
        lines.append("## ข้อจำกัดและเงื่อนไข (Constraints)")
        for item in constraints:
            if str(item).strip():
                lines.append(f"- {str(item).strip()}")
        lines.append("")

    if isinstance(sections, list) and sections:
        lines.append("## หัวข้อรายละเอียด")
        for sec in sections:
            if isinstance(sec, dict):
                heading = str(sec.get("heading") or "หัวข้อ").strip()
                body = str(sec.get("body") or "").strip()
                lines.append(f"### {heading}")
                if body:
                    lines.append(body)
                lines.append("")
            elif str(sec).strip():
                lines.append(f"- {str(sec).strip()}")
        lines.append("")

    markdown = "\n".join(lines).strip() + "\n"
    content_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    saved_file = None
    if save_file:
        if not filename:
            slug = re.sub(r"[^a-z0-9_-]+", "-", title.lower()).strip("-")[:32] or "document-spec"
            filename = f"{slug}.md"
        saved_res = te.save_workspace_file(ctx["data_dir"], filename, markdown)
        if not saved_res.get("ok"):
            return {"ok": False, "status": "FAILED", "error": saved_res.get("error"), "output": {}}
        saved_file = saved_res.get("file")

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "title": title,
            "markdown": markdown,
            "content_sha256": content_sha256,
            "saved_file": saved_file,
        },
        "summary": (
            f"สร้างเอกสาร '{title}' ({len(markdown)} ตัวอักษร)"
            + (f" และบันทึกไฟล์ {saved_file['name']}" if saved_file else "")
        ),
    }


def _handle_binary_office_parser(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    fmt = str(payload.get("format") or "pdf").strip().lower()
    return {
        "ok": False,
        "status": "BLOCKED",
        "error": f"Binary parser for '{fmt}' (PDF/DOCX/XLSX/PPTX) is NOT_IMPLEMENTED in pure-stdlib Python 3.11 environment.",
        "output": {"implemented": False, "format": fmt, "supported_text_formats": ["md", "txt", "csv", "json", "xml"]},
        "summary": f"ตัวอ่านเอกสารไบนารี ({fmt.upper()}) ยังไม่พร้อมใช้งานในสภาพแวดล้อม pure-stdlib",
    }


def register_document_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="document",
        name="Document Toolkit",
        thai_name="ชุดเครื่องมือเอกสารและรายงาน",
        version="1.0.0",
        description="สกัดโครงสร้าง Markdown, สรุปประวัติการทำงานเชิงกำหนด (Deterministic Summarizer) และสร้างเอกสารสเปกพร้อม SHA-256",
        category="document",
        dependencies=("python_core.zyrquen_core", "python_core.tools_engine"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=("python_core/zyrquen_core.py", "python_core/tools_engine.py"),
        documentation="สร้างและตรวจโครงสร้างเอกสาร Markdown/Spec โดยอ้างอิงข้อมูลจริงและบันทึก Hash กำกับทุกฉบับ",
    )

    specs = [
        (
            CapabilitySpec(
                id="document.markdown_outline",
                toolkit_id="document",
                name="วิเคราะห์โครงสร้างและสารบัญ Markdown",
                version="1.0.0",
                description="แยกหัวข้อ H1–H6 สร้างสารบัญ (TOC) นับบล็อกโค้ด และตรวจสอบความครบถ้วนของเอกสาร",
                input_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {"content": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["heading_count", "headings", "toc_markdown"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/document.py",),
                documentation="ส่งเนื้อหา Markdown เพื่อสกัดสารบัญและสถิติเอกสาร",
                example_input={"content": "# Architecture Spec\n\n## Goals\nBuild modular toolkits.\n\n## Security\nEnforce RBAC."},
                keywords=("markdown", "outline", "toc", "document", "เอกสาร", "สารบัญ"),
            ),
            _handle_markdown_outline,
        ),
        (
            CapabilitySpec(
                id="document.conversation_summary",
                toolkit_id="document",
                name="สรุปผลการทำงานเชิงกำหนด (Deterministic Summarizer)",
                version="1.0.0",
                description="สรุปคำนวณ AST, ข้อเท็จจริง KG, แผนงาน DAG และผลเครื่องมือจาก conversation_id หรือข้อความจริง",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "conversation_id": {"type": "string"},
                        "messages": {"type": "array"},
                    },
                },
                output_schema={"type": "object", "required": ["bullets", "metrics"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/zyrquen_core.py",),
                documentation="ส่ง conversation_id (ตรวจสิทธิ์เจ้าของ) หรือ messages array เพื่อสรุปโดยไม่ใช้ LLM ภายนอก",
                example_input={
                    "messages": [
                        {"role": "user", "content": "คำนวณ 7 * 9", "status": "VERIFIED"},
                        {
                            "role": "assistant",
                            "content": "63",
                            "status": "VERIFIED",
                            "trace_json": "{\"math\": {\"expression\": \"7 * 9\", \"result\": 63}}",
                        },
                    ]
                },
                keywords=("summary", "report", "document", "สรุป", "รายงาน", "เอกสาร"),
            ),
            _handle_conversation_summary,
        ),
        (
            CapabilitySpec(
                id="document.spec_generate",
                toolkit_id="document",
                name="สร้างเอกสารสเปกโครงสร้าง (Spec Builder)",
                version="1.0.0",
                description="ประกอบเอกสารข้อกำหนด Markdown พร้อม SHA-256 Checksum และตัวเลือกบันทึกลง workspace_files",
                input_schema={
                    "type": "object",
                    "required": ["title", "objective"],
                    "properties": {
                        "title": {"type": "string"},
                        "objective": {"type": "string"},
                        "constraints": {"type": "array"},
                        "sections": {"type": "array"},
                        "save_to_workspace": {"type": "boolean"},
                        "filename": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["title", "markdown", "content_sha256"]},
                dependencies=("python_core.tools_engine",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py",),
                documentation="สร้างเอกสารสเปกจากข้อมูลที่ส่งเข้า (สามารถเลือก save_to_workspace=true เพื่อบันทึกเป็นไฟล์ .md)",
                example_input={
                    "title": "Project Management Module Spec",
                    "objective": "Provide CRUD API with strict ownership checks and audit trail.",
                    "constraints": ["Zero external LLMs", "Parameterized SQLite queries"],
                    "save_to_workspace": False,
                },
                keywords=("spec", "document", "markdown", "สร้างเอกสาร", "สเปก", "รายงาน"),
            ),
            _handle_spec_generate,
        ),
        (
            CapabilitySpec(
                id="document.binary_office_parser",
                toolkit_id="document",
                name="PDF / DOCX / XLSX / PPTX Binary Parser (อยู่ระหว่างพัฒนา)",
                version="0.1.0",
                description="ยังไม่มีไลบรารีไบนารี PDF/DOCX/XLSX/PPTX ในสภาพแวดล้อม stdlib — ตอบกลับแบบ Fail-Closed โดยไม่จำลองผล",
                input_schema={"type": "object", "required": [], "properties": {"format": {"type": "string"}}},
                output_schema={"type": "object", "required": ["implemented"]},
                dependencies=(),
                permission_mode="admin_only",
                risk_tier="local_readonly",
                lifecycle_status="IN_DEVELOPMENT",
                bound_modules=(),
                documentation="ต้องติดตั้งตัวแปลงเอกสารเฉพาะทางเพิ่มเติมก่อนเปิดใช้งานจริง",
                example_input={"format": "pdf"},
                keywords=("pdf", "docx", "xlsx", "pptx"),
            ),
            _handle_binary_office_parser,
        ),
    ]

    registry.register_toolkit(manifest, specs)
