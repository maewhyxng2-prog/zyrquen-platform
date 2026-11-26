#!/usr/bin/env python3
"""
ZYRQUEN Parameterized SQLite Bridge
Handles structured CRUD operations for Express API routes using parameterized queries.
"""

import json
import sys
import uuid
from zyrquen_core import (
    DATA_DIR,
    WORKFLOW_GROUPS,
    _calc_any_for_tool,
    extract_query_terms,
    get_db,
    get_system_metrics,
    handle_run_workflow,
    init_db,
    now_iso,
    query_knowledge_graph,
    resume_autonomous_mission,
    summarize_conversation,
    tokenize,
)
from tools_engine import (
    format_tool_markdown,
    invoke_tool_governed,
    list_workspace_files,
    save_workspace_file,
)
from dataset_ingestion import init_dataset_pipeline_schema
from tool_center import (
    ToolDependencyManager,
    analyze_failure_patterns,
    decide_improvement_proposal,
    execute_orchestrated_plan,
    get_resource_manager,
    get_tool_center_registry,
    init_tool_center_schema,
    record_task_memory,
    run_engineering_benchmark,
    run_self_improvement_evaluation,
)


def row_to_dict(row):
    return dict(row) if row is not None else None


def _insert_reasoning_trace(
    conn,
    *,
    user_id: str,
    conversation_id: str | None,
    message_id: str | None,
    prompt: str,
    response_content: str,
    mode: str,
    status: str,
    trace_obj: dict | None,
    created_at: str | None = None,
) -> dict:
    trace_dict = trace_obj if isinstance(trace_obj, dict) else {}
    raw_path = trace_dict.get("engine_path")
    engine_path = [str(x) for x in raw_path] if isinstance(raw_path, list) else []
    meta = trace_dict.get("metadata") if isinstance(trace_dict.get("metadata"), dict) else {}
    model_version = str(
        trace_dict.get("model_version")
        or meta.get("modelVersion")
        or meta.get("model_version")
        or "zyrquen-omega-v1"
    ).strip()[:64] or "zyrquen-omega-v1"
    try:
        latency_ms = float(trace_dict.get("latency_ms", 0.0) or 0.0)
    except Exception:
        latency_ms = 0.0
    ext_used = 1 if trace_dict.get("external_models_used", False) else 0
    trace_id = str(uuid.uuid4())
    ts = created_at or now_iso()
    preview = str(response_content or "").strip()[:320]
    trace_str = json.dumps(trace_dict, ensure_ascii=False)
    engine_str = json.dumps(engine_path, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO reasoning_traces (
            id, user_id, conversation_id, message_id, prompt, response_preview,
            mode, model_version, status, engine_path_json, trace_json,
            latency_ms, external_models_used, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id,
            str(user_id),
            conversation_id,
            message_id,
            str(prompt or "")[:1000],
            preview,
            str(mode or "auto")[:32],
            model_version,
            str(status or "VERIFIED")[:32],
            engine_str,
            trace_str,
            round(latency_ms, 2),
            ext_used,
            ts,
        ),
    )
    return {
        "id": trace_id,
        "user_id": str(user_id),
        "conversation_id": conversation_id,
        "message_id": message_id,
        "prompt": str(prompt or "")[:1000],
        "response_preview": preview,
        "mode": str(mode or "auto")[:32],
        "model_version": model_version,
        "status": str(status or "VERIFIED")[:32],
        "engine_path_json": engine_str,
        "trace_json": trace_str,
        "latency_ms": round(latency_ms, 2),
        "external_models_used": ext_used,
        "created_at": ts,
    }


def _query_reasoning_traces(
    conn,
    *,
    user_id: str | None = None,
    is_admin: bool = False,
    q: str = "",
    status: str = "",
    limit: int = 30,
) -> list[dict]:
    safe_limit = max(1, min(100, int(limit or 30)))
    clauses: list[str] = []
    params: list[object] = []
    if user_id and not is_admin:
        clauses.append("user_id = ?")
        params.append(str(user_id))
    clean_status = str(status or "").strip().upper()
    if clean_status and clean_status != "ALL":
        clauses.append("status = ?")
        params.append(clean_status)
    clean_q = str(q or "").strip().lower()
    if clean_q:
        like = f"%{clean_q}%"
        clauses.append(
            "(lower(prompt) LIKE ? OR lower(response_preview) LIKE ? OR lower(model_version) LIKE ? OR lower(engine_path_json) LIKE ? OR lower(status) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(safe_limit)
    rows = conn.execute(
        f"SELECT * FROM reasoning_traces {where_sql} ORDER BY created_at DESC, rowid DESC LIMIT ?",
        tuple(params),
    ).fetchall()
    return [dict(r) for r in rows]


def _enrich_conversation_project(conn, conv: dict) -> dict:
    cid = str(conv.get("id") or "")
    msgs = [
        dict(m)
        for m in conn.execute(
            "SELECT id, role, content, mode, trace_json, status, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC",
            (cid,),
        ).fetchall()
    ]
    tool_invs = [
        dict(t)
        for t in conn.execute(
            "SELECT id, tool_id, status, created_at FROM tool_invocations WHERE conversation_id = ? ORDER BY created_at DESC",
            (cid,),
        ).fetchall()
    ]

    user_msgs = [m for m in msgs if m.get("role") == "user"]
    assistant_msgs = [m for m in msgs if m.get("role") == "assistant"]

    latest_plan_steps: list[dict] = []
    for m in reversed(assistant_msgs):
        raw_trace = m.get("trace_json")
        if not raw_trace:
            continue
        try:
            parsed = json.loads(raw_trace)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            plan_obj = parsed.get("plan")
            if isinstance(plan_obj, dict) and isinstance(plan_obj.get("steps"), list) and plan_obj["steps"]:
                latest_plan_steps = [s for s in plan_obj["steps"] if isinstance(s, dict)]
                break

    pending_actions: list[dict] = []
    seen_titles: set[str] = set()

    def _add_pending(item_id: str, title: str, status: str, category: str) -> None:
        clean_title = str(title or "").strip()
        if not clean_title or clean_title in seen_titles:
            return
        seen_titles.add(clean_title)
        pending_actions.append(
            {
                "id": item_id,
                "title": clean_title[:140],
                "status": str(status or "PENDING"),
                "category": category,
            }
        )

    pending_tool_count = 0
    for inv in tool_invs:
        inv_status = str(inv.get("status") or "").upper()
        tool_name = str(inv.get("tool_id") or "tool")
        if inv_status == "PENDING_APPROVAL":
            pending_tool_count += 1
            _add_pending(str(inv.get("id")), f"รออนุมัติการใช้เครื่องมือ {tool_name}", "PENDING_APPROVAL", "approval")
        elif inv_status in ("FAILED", "BLOCKED"):
            _add_pending(str(inv.get("id")), f"ตรวจสอบเครื่องมือที่ไม่ผ่าน ({tool_name})", inv_status, "blocked")

    for idx, step in enumerate(latest_plan_steps):
        st_status = str(step.get("status") or "PENDING").upper()
        if st_status not in ("VERIFIED", "COMPLETED", "DONE"):
            cat = "approval" if step.get("requires_approval") or st_status in ("PENDING_APPROVAL", "AWAITING_APPROVAL") else "task"
            _add_pending(
                str(step.get("step_id") or f"step-{idx}"),
                str(step.get("title") or f"ขั้นตอนที่ {idx + 1}"),
                st_status,
                cat,
            )

    if len(user_msgs) > len(assistant_msgs):
        _add_pending("pending-reply", "รอการประมวลผลคำสั่งล่าสุด", "IN_PROGRESS", "task")

    if assistant_msgs:
        latest_asst_status = str(assistant_msgs[-1].get("status") or "").upper()
        if latest_asst_status in ("NOT_LEARNED", "UNCERTAIN", "UNKNOWN", "AWAITING_EVIDENCE"):
            _add_pending(
                "needs-clarification",
                "ระบุข้อมูลเพิ่มเติมหรือบันทึกความรู้เข้ากราฟ",
                latest_asst_status,
                "clarification",
            )
        elif latest_asst_status in ("BLOCKED", "FAILED", "ERROR", "REJECTED"):
            _add_pending(
                "resolve-blocked",
                "ตรวจสอบและแก้ไขข้อผิดพลาดของงานล่าสุด",
                latest_asst_status,
                "blocked",
            )
    elif len(msgs) == 0:
        _add_pending("initial-goal", "ส่งเป้าหมายหรือคำสั่งงานแรกของโปรเจกต์", "PENDING", "setup")

    if latest_plan_steps:
        completed_units = sum(
            1
            for s in latest_plan_steps
            if str(s.get("status") or "").upper() in ("VERIFIED", "COMPLETED", "DONE")
        )
        total_units = len(latest_plan_steps) + pending_tool_count
    elif user_msgs:
        verified_turns = sum(
            1 for m in assistant_msgs if str(m.get("status") or "").upper() in ("VERIFIED", "COMPLETED")
        )
        completed_units = min(len(user_msgs), verified_turns)
        total_units = len(user_msgs) + pending_tool_count
    else:
        completed_units = 0
        total_units = 0

    completion_pct = round((completed_units / total_units) * 100) if total_units > 0 else 0

    if any(a["category"] == "approval" for a in pending_actions):
        project_status = "AWAITING_APPROVAL"
    elif any(a["category"] == "blocked" for a in pending_actions):
        project_status = "BLOCKED"
    elif len(msgs) == 0 or any(a["category"] == "clarification" for a in pending_actions):
        project_status = "NEEDS_INPUT"
    elif total_units > 0 and completion_pct >= 100 and len(pending_actions) == 0:
        project_status = "COMPLETED"
    else:
        project_status = "ACTIVE"

    last_summary = None
    if msgs:
        raw_last = str(msgs[-1].get("content") or "").strip().splitlines()
        if raw_last:
            last_summary = raw_last[0][:110]

    conv["project_status"] = project_status
    conv["completion_pct"] = completion_pct
    conv["completed_units"] = completed_units
    conv["total_units"] = total_units
    conv["pending_actions"] = pending_actions[:8]
    conv["last_activity_summary"] = last_summary
    return conv


def handle_action(action: str, payload: dict) -> dict:
    conn = get_db()

    if action == "auth_status":
        admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return {"ok": True, "initialized": admin_count > 0, "user_count": user_count}

    if action == "auth_create_user":
        uid = str(uuid.uuid4())
        email = str(payload["email"]).strip().lower()
        display_name = str(payload["display_name"]).strip()
        role = payload["role"]
        if role not in ("admin", "user"):
            conn.close()
            return {"ok": False, "error": "Invalid role"}
        password_hash = str(payload["password_hash"])
        try:
            with conn:
                conn.execute(
                    "INSERT INTO users (id, email, display_name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, email, display_name, role, password_hash, now_iso()),
                )
            user = row_to_dict(
                conn.execute(
                    "SELECT id, email, display_name, role, created_at FROM users WHERE id=?",
                    (uid,),
                ).fetchone()
            )
            conn.close()
            return {"ok": True, "user": user}
        except Exception as exc:
            conn.close()
            return {"ok": False, "error": str(exc)}

    if action == "auth_find_by_email":
        email = str(payload["email"]).strip().lower()
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
        conn.close()
        return {"ok": True, "user": user}

    if action == "auth_find_by_id":
        uid = str(payload["user_id"])
        user = row_to_dict(
            conn.execute(
                "SELECT id, email, display_name, role, created_at FROM users WHERE id=?",
                (uid,),
            ).fetchone()
        )
        conn.close()
        return {"ok": True, "user": user}

    if action == "home_summary":
        uid = str(payload["user_id"])
        recent = [
            _enrich_conversation_project(conn, dict(r))
            for r in conn.execute(
                """
                SELECT c.id, c.title, c.mode, c.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c
                WHERE c.user_id = ?
                ORDER BY c.updated_at DESC
                LIMIT 6
                """,
                (uid,),
            ).fetchall()
        ]
        triples = conn.execute("SELECT COUNT(*) FROM knowledge_triples").fetchone()[0]
        ckpts = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        datasets = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        pending_approvals = conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE status='PENDING_APPROVAL'").fetchone()[0]
        evaluations = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
        missions_count = conn.execute("SELECT COUNT(*) FROM autonomous_missions").fetchone()[0]
        recent_missions = [
            dict(r)
            for r in conn.execute(
                "SELECT id, goal, status, capabilities_json, stages_json, knowledge_developed_json, research_summary_json, report_markdown, external_models_used, created_by, created_at, updated_at FROM autonomous_missions ORDER BY created_at DESC LIMIT 4"
            ).fetchall()
        ]
        conn.close()
        return {
            "ok": True,
            "recent_conversations": recent,
            "recent_missions": recent_missions,
            "counts": {
                "triples": triples,
                "checkpoints": ckpts,
                "datasets": datasets,
                "pending_approvals": pending_approvals,
                "evaluations": evaluations,
                "missions": missions_count,
            },
            "system": get_system_metrics(),
        }

    if action == "conv_list":
        uid = str(payload["user_id"])
        rows = [
            _enrich_conversation_project(conn, dict(r))
            for r in conn.execute(
                """
                SELECT c.id, c.title, c.mode, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c
                WHERE c.user_id = ?
                ORDER BY c.updated_at DESC
                """,
                (uid,),
            ).fetchall()
        ]
        conn.close()
        return {"ok": True, "conversations": rows}

    if action == "conv_create":
        uid = str(payload["user_id"])
        title = str(payload.get("title", "New Native Session")).strip() or "New Native Session"
        mode = str(payload.get("mode", "auto"))
        cid = str(uuid.uuid4())
        ts = now_iso()
        with conn:
            conn.execute(
                "INSERT INTO conversations (id, user_id, title, mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cid, uid, title[:120], mode, ts, ts),
            )
        conv = row_to_dict(conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone())
        conn.close()
        return {"ok": True, "conversation": conv}

    if action == "conv_get":
        uid = str(payload["user_id"])
        cid = str(payload["conversation_id"])
        conv = row_to_dict(
            conn.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, uid)).fetchone()
        )
        if not conv:
            conn.close()
            return {"ok": False, "error": "Conversation not found"}
        msgs = [
            dict(m)
            for m in conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC",
                (cid,),
            ).fetchall()
        ]
        conn.close()
        return {"ok": True, "conversation": conv, "messages": msgs}

    if action == "conv_summary":
        uid = str(payload["user_id"])
        cid = str(payload["conversation_id"])
        conv = row_to_dict(
            conn.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, uid)).fetchone()
        )
        if not conv:
            conn.close()
            return {"ok": False, "error": "Conversation not found"}
        msgs = [
            dict(m)
            for m in conn.execute(
                "SELECT id, role, content, mode, trace_json, status, created_at FROM messages WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC",
                (cid,),
            ).fetchall()
        ]
        conn.close()
        return {"ok": True, "summary": summarize_conversation(msgs)}

    if action == "conv_delete":
        uid = str(payload["user_id"])
        cid = str(payload["conversation_id"])
        with conn:
            cur = conn.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (cid, uid))
        conn.close()
        return {"ok": cur.rowcount > 0}

    if action == "conv_save_exchange":
        uid = str(payload["user_id"])
        cid = str(payload["conversation_id"])
        conv = conn.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, uid)).fetchone()
        if not conv:
            conn.close()
            return {"ok": False, "error": "Conversation not found"}
        user_msg_id = str(uuid.uuid4())
        asst_msg_id = str(uuid.uuid4())
        ts = now_iso()
        user_content = str(payload["user_content"])
        mode = str(payload.get("mode", "auto"))
        asst_content = str(payload["assistant_content"])
        asst_status = str(payload.get("assistant_status", "VERIFIED"))
        trace_obj = payload.get("trace", {})
        trace_json = json.dumps(trace_obj, ensure_ascii=False)
        asst_ts = now_iso()
        new_title = conv["title"]
        if new_title == "New Native Session" and user_content:
            new_title = user_content[:48] + ("..." if len(user_content) > 48 else "")
        with conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, mode, trace_json, status, created_at) VALUES (?, ?, 'user', ?, ?, NULL, 'USER', ?)",
                (user_msg_id, cid, user_content, mode, ts),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, mode, trace_json, status, created_at) VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?)",
                (asst_msg_id, cid, asst_content, mode, trace_json, asst_status, asst_ts),
            )
            _insert_reasoning_trace(
                conn,
                user_id=uid,
                conversation_id=cid,
                message_id=asst_msg_id,
                prompt=user_content,
                response_content=asst_content,
                mode=mode,
                status=asst_status,
                trace_obj=trace_obj if isinstance(trace_obj, dict) else {},
                created_at=asst_ts,
            )
            conn.execute(
                "UPDATE conversations SET title=?, mode=?, updated_at=? WHERE id=?",
                (new_title, mode, now_iso(), cid),
            )
        user_msg = row_to_dict(conn.execute("SELECT * FROM messages WHERE id=?", (user_msg_id,)).fetchone())
        asst_msg = row_to_dict(conn.execute("SELECT * FROM messages WHERE id=?", (asst_msg_id,)).fetchone())
        conn.close()
        return {"ok": True, "title": new_title, "user_message": user_msg, "assistant_message": asst_msg}

    if action == "knowledge_list":
        q = str(payload.get("q", "")).strip().lower()
        if q:
            like = f"%{q}%"
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT * FROM knowledge_triples
                    WHERE lower(subject) LIKE ? OR lower(relation) LIKE ? OR lower(object) LIKE ?
                    ORDER BY created_at DESC LIMIT 100
                    """,
                    (like, like, like),
                ).fetchall()
            ]
        else:
            rows = [
                dict(r)
                for r in conn.execute("SELECT * FROM knowledge_triples ORDER BY created_at DESC LIMIT 100").fetchall()
            ]
        conn.close()
        return {"ok": True, "triples": rows}

    if action == "knowledge_create":
        subj = str(payload["subject"]).strip()
        rel = str(payload["relation"]).strip()
        obj = str(payload["object"]).strip()
        uid = str(payload["user_id"])
        source = str(payload.get("source", "manual_memory"))
        existing = conn.execute(
            "SELECT object FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?)",
            (subj, rel),
        ).fetchall()
        contradictions = [r["object"] for r in existing if r["object"].lower() != obj.lower()]
        tid = str(uuid.uuid4())
        with conn:
            conn.execute(
                "INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at) VALUES (?, ?, ?, ?, ?, 1.0, ?, ?)",
                (tid, subj, rel, obj, source, uid, now_iso()),
            )
        triple = row_to_dict(conn.execute("SELECT * FROM knowledge_triples WHERE id=?", (tid,)).fetchone())
        conn.close()
        return {"ok": True, "triple": triple, "contradictions": contradictions}

    if action == "knowledge_delete":
        tid = str(payload["triple_id"])
        uid = str(payload["user_id"])
        is_admin = bool(payload.get("is_admin", False))
        with conn:
            if is_admin:
                cur = conn.execute("DELETE FROM knowledge_triples WHERE id=?", (tid,))
            else:
                cur = conn.execute("DELETE FROM knowledge_triples WHERE id=? AND created_by=?", (tid, uid))
        conn.close()
        return {"ok": cur.rowcount > 0}

    if action == "workflows_list":
        runs = [
            dict(r)
            for r in conn.execute("SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT 30").fetchall()
        ]
        reasoning_traces = _query_reasoning_traces(
            conn,
            user_id=payload.get("user_id"),
            is_admin=bool(payload.get("is_admin", False)),
            limit=30,
        )
        conn.close()
        return {
            "ok": True,
            "groups": WORKFLOW_GROUPS,
            "runs": runs,
            "reasoning_traces": reasoning_traces,
        }

    if action == "reasoning_traces_list":
        traces = _query_reasoning_traces(
            conn,
            user_id=payload.get("user_id"),
            is_admin=bool(payload.get("is_admin", False)),
            q=str(payload.get("q", "")),
            status=str(payload.get("status", "")),
            limit=int(payload.get("limit", 40) or 40),
        )
        conn.close()
        return {"ok": True, "reasoning_traces": traces}

    if action == "reasoning_trace_record":
        uid = str(payload.get("user_id", "")).strip()
        if not uid:
            conn.close()
            return {"ok": False, "error": "user_id is required"}
        with conn:
            rec = _insert_reasoning_trace(
                conn,
                user_id=uid,
                conversation_id=payload.get("conversation_id"),
                message_id=payload.get("message_id"),
                prompt=str(payload.get("prompt", "")),
                response_content=str(payload.get("response_content", "")),
                mode=str(payload.get("mode", "auto")),
                status=str(payload.get("status", "VERIFIED")),
                trace_obj=payload.get("trace") if isinstance(payload.get("trace"), dict) else {},
            )
        conn.close()
        return {"ok": True, "reasoning_trace": rec}

    if action == "workflow_decide":
        run_id = str(payload["run_id"])
        decision = str(payload["decision"])
        admin_email = str(payload["admin_email"])
        admin_id = str(payload["admin_id"])
        run = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            conn.close()
            return {"ok": False, "error": "Workflow run not found"}
        if run["status"] != "PENDING_APPROVAL":
            conn.close()
            return {"ok": False, "error": "Workflow run is not awaiting approval"}
        if decision == "reject":
            stages = json.loads(run["stages_json"])
            for s in stages:
                if s.get("stage") == "approval_gate":
                    s["status"] = "REJECTED"
                    s["detail"] = f"Rejected by {admin_email}"
            with conn:
                conn.execute(
                    "UPDATE workflow_runs SET status='REJECTED', approved_by=?, summary=?, stages_json=?, updated_at=? WHERE id=?",
                    (admin_email, f"Rejected at Approval Gate by {admin_email}.", json.dumps(stages), now_iso(), run_id),
                )
            updated = row_to_dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone())
            conn.close()
            return {"ok": True, "run": updated}
        group_id = run["group_id"]
        conn.close()
        return handle_run_workflow(
            {
                "group_id": group_id,
                "user_id": admin_id,
                "approved_by": admin_email,
                "run_id": run_id,
                "dataset_id": payload.get("dataset_id"),
                "_verified_approval_context": True,
            }
        )

    if action == "dev_overview":
        init_dataset_pipeline_schema(conn)
        uid = str(payload["user_id"])
        keys = [
            dict(r)
            for r in conn.execute(
                "SELECT id, name, key_prefix, scopes_json, quota_daily, requests_today, last_used_at, revoked, created_at FROM api_keys WHERE user_id=? ORDER BY created_at DESC",
                (uid,),
            ).fetchall()
        ]
        datasets = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, name, manifest_hash, total_records, train_count, val_count, test_count,
                       leakage_detected, status, created_at,
                       source_name, license, provenance, source_format, content_sha256
                FROM datasets ORDER BY created_at DESC LIMIT 20
                """
            ).fetchall()
        ]
        kg_proposals = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, dataset_id, dataset_name, provenance, source_name, license,
                       manifest_hash, proposal_checksum, triple_count, status,
                       submitted_by, approved_by, decision_reason, created_at, reviewed_at
                FROM kg_ingestion_proposals ORDER BY created_at DESC LIMIT 20
                """
            ).fetchall()
        ]
        checkpoints = [
            dict(r)
            for r in conn.execute(
                "SELECT id, version, dataset_id, vocab_size, ngram_order, train_loss, val_loss, perplexity, eval_accuracy, eval_status, created_at FROM checkpoints ORDER BY version DESC LIMIT 20"
            ).fetchall()
        ]
        usage_total = conn.execute("SELECT COUNT(*) FROM api_usage_logs WHERE user_id=?", (uid,)).fetchone()[0]
        avg_lat = conn.execute("SELECT COALESCE(AVG(latency_ms), 0) FROM api_usage_logs WHERE user_id=?", (uid,)).fetchone()[0]
        recent_usage = [
            dict(r)
            for r in conn.execute(
                "SELECT endpoint, method, status_code, latency_ms, created_at FROM api_usage_logs WHERE user_id=? ORDER BY created_at DESC LIMIT 15",
                (uid,),
            ).fetchall()
        ]
        evaluations = [
            dict(r)
            for r in conn.execute(
                "SELECT id, checkpoint_version, suite_name, overall_status, math_score, knowledge_score, planning_score, test_accuracy, perplexity, baseline_delta_json, created_at FROM evaluations ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        ]
        experiments = [
            dict(r)
            for r in conn.execute(
                "SELECT id, hypothesis, dataset_id, baseline_ckpt_id, candidate_ckpt_id, baseline_metrics_json, candidate_metrics_json, improved, approval_status, approved_by, created_at FROM experiments ORDER BY created_at DESC LIMIT 12"
            ).fetchall()
        ]
        conn.close()
        return {
            "ok": True,
            "keys": keys,
            "datasets": datasets,
            "kg_proposals": kg_proposals,
            "checkpoints": checkpoints,
            "evaluations": evaluations,
            "experiments": experiments,
            "usage": {
                "total_requests": usage_total,
                "avg_latency_ms": round(float(avg_lat), 1),
                "daily_quota": 1000,
                "recent": recent_usage,
            },
        }

    if action == "dev_key_create":
        kid = str(uuid.uuid4())
        with conn:
            conn.execute(
                "INSERT INTO api_keys (id, user_id, name, key_prefix, key_hash, scopes_json, quota_daily, requests_today, revoked, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
                (
                    kid,
                    str(payload["user_id"]),
                    str(payload["name"]).strip(),
                    str(payload["key_prefix"]),
                    str(payload["key_hash"]),
                    json.dumps(payload.get("scopes", ["infer:read"])),
                    int(payload.get("quota_daily", 1000)),
                    now_iso(),
                ),
            )
        row = row_to_dict(
            conn.execute(
                "SELECT id, name, key_prefix, scopes_json, quota_daily, requests_today, revoked, created_at FROM api_keys WHERE id=?",
                (kid,),
            ).fetchone()
        )
        conn.close()
        return {"ok": True, "key": row}

    if action == "dev_key_revoke":
        kid = str(payload["key_id"])
        uid = str(payload["user_id"])
        with conn:
            cur = conn.execute("UPDATE api_keys SET revoked=1 WHERE id=? AND user_id=?", (kid, uid))
        conn.close()
        return {"ok": cur.rowcount > 0}

    if action == "admin_audit_logs":
        limit = max(1, min(int(payload.get("limit", 500)), 500))
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, actor_id, actor_email, action, target, outcome, details_json, created_at "
                "FROM audit_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
        conn.close()
        return rows

    if action == "admin_overview":
        init_dataset_pipeline_schema(conn)
        init_tool_center_schema(conn)
        users = [
            dict(r)
            for r in conn.execute(
                "SELECT id, email, display_name, role, created_at FROM users ORDER BY created_at ASC"
            ).fetchall()
        ]
        pending_runs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM workflow_runs WHERE status='PENDING_APPROVAL' ORDER BY created_at DESC"
            ).fetchall()
        ]
        audit_logs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 40"
            ).fetchall()
        ]
        pending_tool_invocations = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tool_invocations WHERE status='PENDING_APPROVAL' ORDER BY created_at DESC"
            ).fetchall()
        ]
        tools = [
            dict(r)
            for r in conn.execute("SELECT * FROM external_tools ORDER BY id ASC").fetchall()
        ]
        pending_experiments = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM experiments WHERE approval_status='PENDING_APPROVAL' ORDER BY created_at DESC"
            ).fetchall()
        ]
        pending_kg_proposals = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, dataset_id, dataset_name, provenance, source_name, license,
                       manifest_hash, proposal_checksum, triples_json, contradictions_json,
                       triple_count, status, submitted_by, approved_by, decision_reason,
                       created_at, reviewed_at
                FROM kg_ingestion_proposals
                WHERE status='PENDING_APPROVAL'
                ORDER BY created_at DESC
                """
            ).fetchall()
        ]
        datasets = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, name, manifest_hash, total_records, train_count, val_count, test_count,
                       leakage_detected, status, created_at,
                       source_name, license, provenance, source_format, content_sha256
                FROM datasets ORDER BY created_at DESC LIMIT 20
                """
            ).fetchall()
        ]
        checkpoints = [
            dict(r)
            for r in conn.execute(
                "SELECT id, version, dataset_id, vocab_size, ngram_order, train_loss, val_loss, perplexity, eval_accuracy, eval_status, created_at FROM checkpoints ORDER BY version DESC LIMIT 20"
            ).fetchall()
        ]
        experiments_recent = [
            dict(r)
            for r in conn.execute(
                "SELECT id, hypothesis, dataset_id, baseline_ckpt_id, candidate_ckpt_id, baseline_metrics_json, candidate_metrics_json, improved, approval_status, approved_by, created_at FROM experiments ORDER BY created_at DESC LIMIT 12"
            ).fetchall()
        ]
        triples_total = conn.execute("SELECT COUNT(*) FROM knowledge_triples").fetchone()[0]
        verified_triples = conn.execute(
            """
            SELECT COUNT(*) FROM knowledge_triples
            WHERE confidence >= 0.8
              AND source NOT LIKE '%uncorroborated%'
              AND source NOT LIKE '%conflicting%'
              AND source NOT LIKE '%stale%'
            """
        ).fetchone()[0]
        clean_datasets = sum(
            1 for d in datasets if int(d.get("leakage_detected", 0)) == 0 and int(d.get("total_records", 0)) >= 5
        )
        eval_count = int(conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0])
        baseline_count = int(conn.execute("SELECT COUNT(*) FROM capability_baselines").fetchone()[0])
        baseline_evaluations = eval_count + baseline_count
        approved_training_runs = int(
            conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE group_id='native_training' AND status='COMPLETED' AND approved_by IS NOT NULL"
            ).fetchone()[0]
        )
        neural_checkpoints = sum(1 for c in checkpoints if str(c.get("eval_status") or "").startswith("NEURAL"))
        approved_experiments = sum(1 for e in experiments_recent if e.get("approval_status") == "APPROVED")
        pending_training_runs = sum(1 for r in pending_runs if r.get("group_id") == "native_training")

        if clean_datasets == 0:
            gate_status = "BLOCKED"
        elif baseline_evaluations == 0:
            gate_status = "BLOCKED_NO_BASELINE"
        elif len(pending_experiments) > 0 or pending_training_runs > 0:
            gate_status = "AWAITING_APPROVAL"
        elif len(checkpoints) == 0:
            gate_status = "READY_FOR_TRAINING_GATE"
        else:
            gate_status = "VERIFIED"

        reasoning_traces = _query_reasoning_traces(conn, is_admin=True, limit=40)
        recent_api_usage = [
            dict(r)
            for r in conn.execute(
                "SELECT endpoint, method, status_code, latency_ms, created_at FROM api_usage_logs ORDER BY created_at DESC LIMIT 40"
            ).fetchall()
        ]

        pending_tool_center_invocations = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tool_center_invocations WHERE status='PENDING_APPROVAL' ORDER BY created_at DESC"
            ).fetchall()
        ]
        pending_improvement_proposals = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM improvement_proposals WHERE approval_status='PENDING_APPROVAL' ORDER BY created_at DESC"
            ).fetchall()
        ]

        conn.close()
        return {
            "ok": True,
            "users": users,
            "pending_runs": pending_runs,
            "pending_tool_invocations": pending_tool_invocations,
            "pending_tool_center_invocations": pending_tool_center_invocations,
            "pending_improvement_proposals": pending_improvement_proposals,
            "pending_experiments": pending_experiments,
            "pending_kg_proposals": pending_kg_proposals,
            "tools": tools,
            "audit_logs": audit_logs,
            "system": get_system_metrics(),
            "reasoning_traces": reasoning_traces,
            "recent_api_usage": recent_api_usage,
            "training_readiness": {
                "gate_status": gate_status,
                "datasets_total": len(datasets),
                "clean_datasets": clean_datasets,
                "baseline_evaluations": baseline_evaluations,
                "approved_training_runs": approved_training_runs,
                "triples_total": triples_total,
                "verified_triples": verified_triples,
                "experiments_total": len(experiments_recent),
                "approved_experiments": approved_experiments,
                "pending_experiments": len(pending_experiments),
                "pending_training_runs": pending_training_runs,
                "pending_kg_proposals": len(pending_kg_proposals),
                "checkpoints_total": len(checkpoints),
                "neural_checkpoints": neural_checkpoints,
                "datasets": datasets,
                "checkpoints": checkpoints,
                "experiments": experiments_recent,
            },
        }

    if action == "admin_user_role":
        target_id = str(payload["target_user_id"])
        new_role = str(payload["role"])
        if new_role not in ("admin", "user"):
            conn.close()
            return {"ok": False, "error": "Invalid role"}
        with conn:
            cur = conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, target_id))
        conn.close()
        return {"ok": cur.rowcount > 0}

    if action == "log_api_usage":
        with conn:
            conn.execute(
                "INSERT INTO api_usage_logs (id, user_id, key_id, endpoint, method, status_code, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    payload.get("user_id"),
                    payload.get("key_id"),
                    str(payload["endpoint"]),
                    str(payload["method"]),
                    int(payload["status_code"]),
                    float(payload["latency_ms"]),
                    now_iso(),
                ),
            )
        conn.close()
        return {"ok": True}

    if action == "log_audit":
        with conn:
            conn.execute(
                "INSERT INTO audit_logs (id, actor_id, actor_email, action, target, outcome, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    str(payload["actor_id"]),
                    str(payload["actor_email"]),
                    str(payload["action"]),
                    str(payload["target"]),
                    str(payload["outcome"]),
                    json.dumps(payload.get("details", {})),
                    now_iso(),
                ),
            )
        conn.close()
        return {"ok": True}

    if action == "tools_overview":
        uid = str(payload.get("user_id", ""))
        tools = [dict(r) for r in conn.execute("SELECT * FROM external_tools ORDER BY id ASC").fetchall()]
        invocations = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM tool_invocations WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                (uid,),
            ).fetchall()
        ]
        ws_files = list_workspace_files(DATA_DIR)
        conn.close()
        return {"ok": True, "tools": tools, "invocations": invocations, "workspace_files": ws_files}

    if action == "tools_upload_file":
        filename = str(payload.get("filename", "")).strip()
        content = str(payload.get("content", ""))
        res = save_workspace_file(DATA_DIR, filename, content)
        conn.close()
        return res

    if action == "tools_invoke":
        tool_id = str(payload.get("tool_id", "")).strip()
        tool_input = payload.get("input", {})
        if not isinstance(tool_input, dict):
            tool_input = {}
        uid = str(payload.get("user_id", ""))
        res = invoke_tool_governed(
            conn,
            DATA_DIR,
            tool_id,
            tool_input,
            user_id=uid,
            conversation_id=payload.get("conversation_id"),
            approved_by=None,
            tokenize_fn=tokenize,
            extract_terms_fn=extract_query_terms,
            query_kg_fn=query_knowledge_graph,
            calc_fn=_calc_any_for_tool,
        )
        conn.close()
        return res

    if action == "admin_tools_update":
        tool_id = str(payload.get("tool_id", "")).strip()
        row = conn.execute("SELECT * FROM external_tools WHERE id=?", (tool_id,)).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "error": "Tool not found"}
        perm = str(payload.get("permission_mode", row["permission_mode"]))
        if perm not in ("auto", "approval_required", "disabled"):
            conn.close()
            return {"ok": False, "error": "Invalid permission_mode"}
        enabled = 1 if payload.get("enabled", row["enabled"]) else 0
        quota = max(1, min(10000, int(payload.get("quota_daily", row["quota_daily"]))))
        allowlist = payload.get("endpoint_allowlist")
        if isinstance(allowlist, list):
            allow_json = json.dumps([str(x).strip().lower() for x in allowlist if str(x).strip()][:20])
        else:
            allow_json = row["endpoint_allowlist_json"]
        with conn:
            conn.execute(
                """
                UPDATE external_tools
                SET permission_mode=?, enabled=?, quota_daily=?, endpoint_allowlist_json=?, updated_at=?
                WHERE id=?
                """,
                (perm, enabled, quota, allow_json, now_iso(), tool_id),
            )
        updated = row_to_dict(conn.execute("SELECT * FROM external_tools WHERE id=?", (tool_id,)).fetchone())
        conn.close()
        return {"ok": True, "tool": updated}

    if action == "admin_tool_decide":
        inv_id = str(payload.get("invocation_id", "")).strip()
        decision = str(payload.get("decision", "approve"))
        admin_email = str(payload.get("admin_email", ""))
        inv = conn.execute("SELECT * FROM tool_invocations WHERE id=?", (inv_id,)).fetchone()
        if not inv:
            conn.close()
            return {"ok": False, "error": "Tool invocation not found"}
        if inv["status"] != "PENDING_APPROVAL":
            conn.close()
            return {"ok": False, "error": "Tool invocation is not pending approval"}

        mission_id = inv["mission_id"] if "mission_id" in inv.keys() else None
        mission_node_id = inv["mission_node_id"] if "mission_node_id" in inv.keys() else None

        if decision == "reject":
            with conn:
                conn.execute(
                    """
                    UPDATE tool_invocations
                    SET status='REJECTED', approved_by=?, analysis_summary=?, updated_at=?
                    WHERE id=?
                    """,
                    (admin_email, f"ปฏิเสธโดยผู้ดูแลระบบ ({admin_email})", now_iso(), inv_id),
                )
            updated = row_to_dict(conn.execute("SELECT * FROM tool_invocations WHERE id=?", (inv_id,)).fetchone())
            conn.close()
            resumed = None
            if mission_id:
                resumed = resume_autonomous_mission(
                    {
                        "mission_id": mission_id,
                        "invocation_id": inv_id,
                        "node_id": mission_node_id,
                        "decision": "reject",
                        "approved_by": admin_email,
                    }
                )
            return {"ok": True, "invocation": updated, "status": "REJECTED", "resumed_mission": resumed}

        if mission_id:
            conn.close()
            resumed = resume_autonomous_mission(
                {
                    "mission_id": mission_id,
                    "invocation_id": inv_id,
                    "node_id": mission_node_id,
                    "decision": "approve",
                    "approved_by": admin_email,
                }
            )
            c2 = get_db()
            updated = row_to_dict(c2.execute("SELECT * FROM tool_invocations WHERE id=?", (inv_id,)).fetchone())
            c2.close()
            return {
                "ok": bool(resumed.get("ok")),
                "status": (updated or {}).get("status", "COMPLETED"),
                "invocation": updated,
                "resumed_mission": resumed,
            }

        try:
            tool_input = json.loads(inv["input_json"] or "{}")
        except Exception:
            tool_input = {}
        res = invoke_tool_governed(
            conn,
            DATA_DIR,
            inv["tool_id"],
            tool_input,
            user_id=inv["user_id"],
            conversation_id=inv["conversation_id"],
            approved_by=admin_email,
            existing_invocation_id=inv_id,
            tokenize_fn=tokenize,
            extract_terms_fn=extract_query_terms,
            query_kg_fn=query_knowledge_graph,
            calc_fn=_calc_any_for_tool,
        )
        if inv["conversation_id"] and res.get("ok"):
            md = format_tool_markdown(inv["tool_id"], res)
            analysis_obj = res.get("analysis") or {}
            t_grade = analysis_obj.get("trust_grade")
            if res.get("status") != "COMPLETED":
                msg_status = "BLOCKED" if res.get("status") == "BLOCKED" else "FAILED"
            elif t_grade in {"INSUFFICIENT_EVIDENCE", "CONFLICTING_SOURCES"}:
                msg_status = "NOT_LEARNED"
            elif t_grade == "BLOCKED":
                msg_status = "BLOCKED"
            else:
                msg_status = "VERIFIED"
            trace_obj = {
                "mode": "auto",
                "engine_path": [f"external_tool:{inv['tool_id']}", "native_tool_synthesizer"],
                "external_models_used": False,
                "approved_by": admin_email,
                "external_tool": {
                    "tool_id": inv["tool_id"],
                    "status": res.get("status"),
                    "invocation_id": inv_id,
                    "trust_grade": analysis_obj.get("trust_grade"),
                    "distinct_providers": analysis_obj.get("distinct_providers", []),
                    "kg_matches_count": len(analysis_obj.get("kg_matches") or []),
                    "limitations": analysis_obj.get("limitations", []),
                    "analysis_summary": analysis_obj.get("summary"),
                },
            }
            tool_msg_id = str(uuid.uuid4())
            tool_ts = now_iso()
            with conn:
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, mode, trace_json, status, created_at) VALUES (?, ?, 'assistant', ?, 'auto', ?, ?, ?)",
                    (tool_msg_id, inv["conversation_id"], md, json.dumps(trace_obj, ensure_ascii=False), msg_status, tool_ts),
                )
                _insert_reasoning_trace(
                    conn,
                    user_id=inv["user_id"],
                    conversation_id=inv["conversation_id"],
                    message_id=tool_msg_id,
                    prompt=f"[Governed Tool: {inv['tool_id']}] {json.dumps(tool_input, ensure_ascii=False)[:240]}",
                    response_content=md,
                    mode="auto",
                    status=msg_status,
                    trace_obj=trace_obj,
                    created_at=tool_ts,
                )
        conn.close()
        return res

    if action == "missions_list":
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM autonomous_missions ORDER BY created_at DESC LIMIT 25"
            ).fetchall()
        ]
        conn.close()
        return {"ok": True, "missions": rows}

    if action == "mission_detail":
        mid = str(payload.get("mission_id", "")).strip()
        m_row = row_to_dict(conn.execute("SELECT * FROM autonomous_missions WHERE id=?", (mid,)).fetchone())
        if not m_row:
            conn.close()
            return {"ok": False, "error": "Mission not found"}
        nodes = [dict(r) for r in conn.execute("SELECT * FROM mission_nodes WHERE mission_id=? ORDER BY rowid ASC", (mid,)).fetchall()]
        evidence = [dict(r) for r in conn.execute("SELECT * FROM mission_evidence WHERE mission_id=? ORDER BY rowid ASC", (mid,)).fetchall()]
        conn.close()
        return {"ok": True, "mission": m_row, "nodes": nodes, "evidence": evidence}

    if action == "kg_proposals_list":
        init_dataset_pipeline_schema(conn)
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, dataset_id, dataset_name, provenance, source_name, license,
                       manifest_hash, proposal_checksum, triples_json, contradictions_json,
                       triple_count, status, submitted_by, approved_by, decision_reason,
                       created_at, reviewed_at
                FROM kg_ingestion_proposals
                ORDER BY created_at DESC LIMIT 30
                """
            ).fetchall()
        ]
        conn.close()
        return {"ok": True, "proposals": rows}

    if action == "tool_center_overview":
        init_tool_center_schema(conn)
        uid = str(payload.get("user_id", ""))
        user_role = str(payload.get("user_role", "user"))
        is_admin = user_role.lower() == "admin"
        reg = get_tool_center_registry()
        toolkits = reg.list_toolkits(user_role=user_role)
        inventory = reg.audit_repository_inventory()
        dep_env = ToolDependencyManager().check_environment(reg)
        res_snapshot = get_resource_manager().snapshot()
        failure_patterns = analyze_failure_patterns(conn, limit=8)
        if is_admin:
            invs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM tool_center_invocations ORDER BY created_at DESC LIMIT 25"
                ).fetchall()
            ]
        else:
            invs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM tool_center_invocations WHERE user_id=? ORDER BY created_at DESC LIMIT 25",
                    (uid,),
                ).fetchall()
            ]
        if is_admin:
            proposals = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM improvement_proposals ORDER BY created_at DESC LIMIT 15"
                ).fetchall()
            ]
            recent_orch = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, goal, status, total_latency_ms, created_at, updated_at FROM orchestration_runs ORDER BY created_at DESC LIMIT 15"
                ).fetchall()
            ]
        else:
            proposals = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM improvement_proposals WHERE created_by=? ORDER BY created_at DESC LIMIT 15",
                    (uid,),
                ).fetchall()
            ]
            recent_orch = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, goal, status, total_latency_ms, created_at, updated_at FROM orchestration_runs WHERE user_id=? ORDER BY created_at DESC LIMIT 15",
                    (uid,),
                ).fetchall()
            ]
        conn.close()
        return {
            "ok": True,
            "toolkits": toolkits,
            "inventory": inventory,
            "dependency_environment": dep_env,
            "resource_snapshot": res_snapshot,
            "failure_patterns": failure_patterns,
            "invocations": invs,
            "improvement_proposals": proposals,
            "recent_orchestrations": recent_orch,
            "external_models_used": False,
        }

    if action == "tool_center_resolve":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        plan = reg.compose_for_goal(
            str(payload.get("goal", "")),
            user_role=str(payload.get("user_role", "user")),
            conn=conn,
        )
        conn.close()
        return plan

    if action == "tool_center_execute":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        cap_id = str(payload.get("capability_id", "")).strip()
        cap_input = payload.get("input", {})
        if not isinstance(cap_input, dict):
            cap_input = {}
        res = reg.execute(
            cap_id,
            cap_input,
            user_id=str(payload.get("user_id", "system")),
            user_role=str(payload.get("user_role", "user")),
            conn=conn,
            data_dir=DATA_DIR,
            project_id=payload.get("project_id"),
            conversation_id=payload.get("conversation_id"),
        )
        if res.get("status") in {"COMPLETED", "FAILED", "BLOCKED"}:
            qa = res.get("qa") or {}
            verdict = str(qa.get("verdict") or ("SUCCESS" if res.get("ok") else "FAILED"))
            if verdict in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED"}:
                record_task_memory(
                    conn,
                    trace_id=res.get("invocation_id"),
                    goal=f"Execute capability {cap_id}",
                    toolkit_ids=[str(res.get("toolkit_id") or "unknown")],
                    capability_sequence=[cap_id],
                    outcome_status=verdict,
                    error_code=None if res.get("ok") else ("PERMISSION_BLOCKED" if res.get("status") == "BLOCKED" else "EXECUTION_ERROR"),
                    error_message=res.get("error"),
                    context_keys=sorted(cap_input.keys()),
                    latency_ms=float(res.get("latency_ms") or 0.0),
                    verified=(verdict == "SUCCESS"),
                )
        conn.close()
        return res

    if action == "tool_center_orchestrate":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        steps = payload.get("steps")
        if not isinstance(steps, list):
            steps = []
        res = execute_orchestrated_plan(
            reg,
            str(payload.get("goal", "")),
            steps,
            conn=conn,
            data_dir=DATA_DIR,
            user_id=str(payload.get("user_id", "system")),
            user_role=str(payload.get("user_role", "user")),
            shared_context=payload.get("shared_context") if isinstance(payload.get("shared_context"), dict) else None,
            idempotency_scope=payload.get("idempotency_scope"),
            enable_parallel=bool(payload.get("enable_parallel", True)),
        )
        conn.close()
        return res

    if action == "tool_center_verify":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        tk_id = str(payload.get("toolkit_id") or "").strip() or None
        res = reg.verify_toolkit(tk_id, conn=conn, data_dir=DATA_DIR)
        conn.close()
        return res

    if action == "tool_center_decide":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        res = reg.decide_invocation(
            conn,
            invocation_id=str(payload.get("invocation_id", "")).strip(),
            decision=str(payload.get("decision", "reject")),
            admin_email=str(payload.get("admin_email", "admin")),
            data_dir=DATA_DIR,
        )
        conn.close()
        return res

    if action == "tool_center_self_improve":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        res = run_self_improvement_evaluation(
            conn,
            reg,
            data_dir=DATA_DIR,
            user_id=str(payload.get("user_id", "system")),
            sandbox_probe_code=payload.get("sandbox_probe_code"),
        )
        conn.close()
        return res

    if action == "tool_center_decide_improvement":
        init_tool_center_schema(conn)
        res = decide_improvement_proposal(
            conn,
            proposal_id=str(payload.get("proposal_id", "")).strip(),
            decision=str(payload.get("decision", "reject")),
            admin_email=str(payload.get("admin_email", "admin")),
            admin_id=str(payload.get("admin_id", "admin")),
            reason=payload.get("reason"),
        )
        conn.close()
        return res

    if action == "tool_center_engineering_benchmark":
        init_tool_center_schema(conn)
        reg = get_tool_center_registry()
        res = run_engineering_benchmark(reg, conn=conn, data_dir=DATA_DIR)
        conn.close()
        return res

    conn.close()
    return {"ok": False, "error": f"Unknown bridge action '{action}'"}


def main() -> None:
    init_db()
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"ok": False, "error": "Empty payload"}))
        return
    req = json.loads(raw)
    action = req.get("action", "")
    payload = req.get("payload", {})
    print(json.dumps(handle_action(action, payload)))


if __name__ == "__main__":
    main()
