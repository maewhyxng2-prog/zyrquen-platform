from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional

try:
    from .control_engine import (
        check_backup_integrity,
        check_target_readiness,
        compare_runs,
        execute_verification_run,
        get_system_monitor,
        new_run_id,
        record_audit,
        cancel_run,
    )
    from .models import RunRecord, StepRecord, utc_now_iso
    from .store import EvidenceStore
except ImportError:
    from control_engine import (
        check_backup_integrity,
        check_target_readiness,
        compare_runs,
        execute_verification_run,
        get_system_monitor,
        new_run_id,
        record_audit,
        cancel_run,
    )
    from models import RunRecord, StepRecord, utc_now_iso
    from store import EvidenceStore


_RUN_ID_MENTION_RE = re.compile(r"\brun_[a-zA-Z0-9_-]{4,48}\b")


def diagnose_run_failure(run: RunRecord) -> Dict[str, Any]:
    """Deterministic root-cause & remediation analyzer grounded strictly in real evidence & logs."""
    if run.status == "PASS":
        return {
            "run_id": run.run_id,
            "root_cause_code": "NONE_PASSED",
            "severity": "info",
            "summary": f"งาน {run.run_id} ผ่านการตรวจสอบทุกขั้นตอน ({run.duration_sec}s) ไม่มีข้อขัดแย้ง",
            "evidence_citations": [f"status={run.status}", f"steps={len(run.steps)}"],
            "recommendations": [],
        }

    if run.status == "CANCELLED":
        return {
            "run_id": run.run_id,
            "root_cause_code": "OPERATOR_CANCELLED",
            "severity": "warning",
            "summary": f"งาน {run.run_id} ถูกยกเลิกก่อนจบการทำงาน จึงไม่สามารถประกาศผล PASS ได้",
            "evidence_citations": list(run.discrepancies),
            "recommendations": [
                {
                    "title": "สั่งทดสอบใหม่ (Retry) เมื่อพร้อม",
                    "reason": "งานเดิมถูกยกเลิกกลางทางและทำความสะอาดพื้นที่แยกแล้ว",
                    "requires_approval": True,
                    "suggested_action": {"type": "retry_run", "run_id": run.run_id},
                }
            ],
        }

    joined = " | ".join(run.discrepancies + run.logs_tail).lower()
    if "sha-256 mismatch" in joined or "hash mismatch" in joined:
        code = "SHA256_OR_MANIFEST_MISMATCH"
        summary = f"พบค่า SHA-256 ของไฟล์ไม่ตรงกับที่คาดไว้ใน {run.run_id} บ่งชี้ว่าไฟล์ถูกแก้ไข เสียหาย หรือ manifest ล้าสมัย"
        recs = [
            {
                "title": "ตรวจสอบไฟล์ต้นทางและสร้าง Backup ใหม่",
                "reason": "ไฟล์ Backup ปัจจุบันไม่ตรงกับ Baseline SHA-256 ห้ามนำไปกู้คืนจริง",
                "requires_approval": True,
                "suggested_action": {"type": "recheck_backup", "backup_source_id": run.backup_source_id},
            }
        ]
    elif "pg_restore or psql binary not available" in joined or "docker binary" in joined:
        code = "MISSING_WORKER_BINARY"
        summary = f"งาน {run.run_id} ถูกบล็อก (BLOCKED) เพราะ worker ปัจจุบันไม่มีคำสั่ง pg_restore/psql หรือ Docker สำหรับกู้คืน PostgreSQL"
        recs = [
            {
                "title": "ย้ายไปรันบน Worker ที่มี PostgreSQL Client/Docker หรือติดตั้งเครื่องมือใน Worker",
                "reason": "ระบบป้องกันการประกาศผล PASS เทียมโดยบังคับ BLOCKED เมื่อขาดเครื่องมือทดสอบจริง",
                "requires_approval": True,
                "suggested_action": {"type": "inspect_readiness"},
            }
        ]
    elif "reserved/production database" in joined:
        code = "RESERVED_PRODUCTION_DB_GUARD"
        summary = f"งาน {run.run_id} ถูกบล็อกเพื่อความปลอดภัย เนื่องจาก target_dbname='{run.target_dbname}' เป็นชื่อฐานข้อมูลสงวน/Production"
        recs = [
            {
                "title": "เปลี่ยนเป้าหมายเป็นฐานข้อมูล Ephemeral เช่น rp_verify_*",
                "reason": "ป้องกัน pg_restore --clean เขียนทับข้อมูลจริง",
                "requires_approval": True,
                "suggested_action": {"type": "select_isolated_target"},
            }
        ]
    elif "not found" in joined or "missing" in joined and "backup" in joined:
        code = "BACKUP_ARTIFACT_MISSING"
        summary = f"ไม่พบไฟล์ Backup ตามพาธ '{run.backup_uri}' ในงาน {run.run_id}"
        recs = [
            {
                "title": "ตรวจสอบการเชื่อมต่อพื้นที่เก็บข้อมูลหรือสร้าง/อัปโหลด Backup ใหม่",
                "reason": "ไม่สามารถกู้คืนได้เมื่อไฟล์ต้นทางหายไปจากดิสก์",
                "requires_approval": True,
                "suggested_action": {"type": "inspect_backups"},
            }
        ]
    elif "below required minimum" in joined or "row count" in joined or "missing required tables" in joined:
        code = "DATA_COMPLETENESS_OR_INVARIANT_FAIL"
        summary = f"การกู้คืนใน {run.run_id} ทำได้แต่ข้อมูลไม่ครบตามเกณฑ์ (จำนวนแถวต่ำกว่า {run.min_total_rows} หรือตารางขาดหาย)"
        recs = [
            {
                "title": "ตรวจสอบ Dump ต้นทางว่า Dump ครบทุก Schema/Table ก่อนนำไปใช้งาน",
                "reason": "ข้อมูลหลัง Restore ไม่ผ่าน Data Invariants ที่กำหนด",
                "requires_approval": True,
                "suggested_action": {"type": "inspect_report", "run_id": run.run_id},
            }
        ]
    elif "unpack failed" in joined or "corrupt" in joined or "traversal" in joined:
        code = "ARCHIVE_CORRUPT_OR_UNSAFE"
        summary = f"ไฟล์ Archive ใน {run.run_id} เสียหาย แตกไฟล์ไม่สำเร็จ หรือมีโครงสร้างไม่ปลอดภัย (เช่น Path Traversal)"
        recs = [
            {
                "title": "ปฏิเสธไฟล์นี้และสั่งสร้าง Archive Backup ชุดใหม่จากต้นทาง",
                "reason": "ไม่สามารถแตกไฟล์ได้อย่างปลอดภัยใน Sandbox",
                "requires_approval": True,
                "suggested_action": {"type": "inspect_backups"},
            }
        ]
    else:
        code = "RESTORE_OR_HEALTH_PROBE_FAILED"
        summary = f"งาน {run.run_id} จบด้วยสถานะ {run.status}: {run.discrepancies[0] if run.discrepancies else 'โปรดตรวจ Log ใน Evidence'}"
        recs = [
            {
                "title": "ตรวจสอบ stderr และ Step Trace ของงานนี้",
                "reason": "พบข้อผิดพลาดระหว่างคำสั่งกู้คืนหรือ Health Probe",
                "requires_approval": True,
                "suggested_action": {"type": "inspect_report", "run_id": run.run_id},
            }
        ]

    return {
        "run_id": run.run_id,
        "status": run.status,
        "root_cause_code": code,
        "severity": "error" if run.status == "FAIL" else "warning",
        "summary": summary,
        "evidence_citations": list(run.discrepancies) + list(run.logs_tail[-3:]),
        "recommendations": recs,
    }


def process_assistant_command(
    store: EvidenceStore,
    message: str,
    actor: str = "operator",
    confirm_execution: bool = False,
    context_run_id: Optional[str] = None,
    context_backup_id: Optional[str] = None,
    cancel_flags: Optional[Dict[str, threading.Event]] = None,
    pg_host: str = "127.0.0.1",
    pg_port: int = 5432,
    pg_user: str = "postgres",
) -> Dict[str, Any]:
    """
    Native Deterministic AI Operations Assistant for RealityCheck — RestoreProof.
    - Understands Thai/English operational requests.
    - Builds structured multi-step plans & risk checks.
    - Calls real Backend APIs/engines for read & verified checks.
    - Requires explicit Approval Gate (confirm_execution=True) for state-changing/restore commands.
    - Never fabricates PASS results; always cites real run_id & evidence.
    """
    text = (message or "").strip()
    lower = text.lower()
    mention_match = _RUN_ID_MENTION_RE.search(text)
    target_run_id = mention_match.group(0) if mention_match else context_run_id

    base_meta = {
        "native_deterministic": True,
        "external_ai_used": False,
        "cannot_fabricate_pass": True,
        "role_boundary": "AI Assistant วางแผน เรียกเครื่องมือตามสิทธิ์ และวิเคราะห์หลักฐาน — ผล PASS/FAIL/BLOCKED มาจาก Verification Engine เท่านั้น",
        "timestamp": utc_now_iso(),
        "input": text,
    }

    # 1. Cancel Run intent (Mutation -> Approval Gate)
    if any(k in lower for k in ("ยกเลิก", "cancel", "หยุดงาน", "stop run")):
        runs = store.list_runs(limit=20)
        target_rec = store.get(target_run_id) if target_run_id else next(
            (r for r in runs if r.status in ("RUNNING", "QUEUED")), None
        )
        if not target_rec:
            res = {
                **base_meta,
                "intent": "cancel_job",
                "risk_level": "low",
                "requires_approval": False,
                "executed": True,
                "plan_steps": [
                    {"step": "ค้นหางานสถานะ RUNNING/QUEUED ในคิว", "status": "DONE"}
                ],
                "answer": "ไม่พบงานที่กำลังทำงานหรือรอคิวอยู่ในขณะนี้ จึงไม่มีงานที่ต้องยกเลิก",
                "tool_outputs": {},
            }
            store.append_assistant_event(res)
            return res

        if not confirm_execution:
            res = {
                **base_meta,
                "intent": "cancel_job",
                "risk_level": "high",
                "requires_approval": True,
                "executed": False,
                "plan_steps": [
                    {"step": f"ตรวจสอบสถานะงาน {target_rec.run_id} ({target_rec.status})", "status": "READY"},
                    {"step": f"ขออนุมัติยกเลิกงาน {target_rec.run_id} และทำความสะอาด Sandbox", "status": "AWAITING_APPROVAL"},
                ],
                "proposed_action": {"type": "cancel_job", "run_id": target_rec.run_id},
                "answer": f"วางแผนยกเลิกงาน {target_rec.run_id} ({target_rec.source_name}) แล้ว — กรุณากดยืนยันอนุมัติเพื่อหยุดงานอย่างปลอดภัย",
                "tool_outputs": {"target_run": target_rec.to_dict()},
            }
            store.append_assistant_event(res)
            return res

        cancelled = cancel_run(store, target_rec.run_id, actor=actor, cancel_flags=cancel_flags)
        res = {
            **base_meta,
            "intent": "cancel_job",
            "risk_level": "high",
            "requires_approval": False,
            "executed": True,
            "plan_steps": [
                {"step": f"ยกเลิกงาน {cancelled.run_id} อย่างปลอดภัย", "status": "CANCELLED"}
            ],
            "answer": f"ยกเลิกงาน {cancelled.run_id} เรียบร้อยแล้ว (สถานะ: {cancelled.status})",
            "referenced_run_ids": [cancelled.run_id],
            "tool_outputs": {"cancelled_run": cancelled.to_dict()},
        }
        store.append_assistant_event(res)
        return res

    # 2. Check all latest backups intent (Read + Deterministic Hash Check)
    if any(k in lower for k in ("backup", "แบ็กอัป", "สำรอง", "sha", "manifest", "integrity")) and not any(
        k in lower for k in ("restore", "กู้คืน", "ทดสอบกู้")
    ):
        backups = store.list_backups()
        if not backups:
            res = {
                **base_meta,
                "intent": "check_backups",
                "risk_level": "low",
                "requires_approval": False,
                "executed": True,
                "plan_steps": [
                    {"step": "ตรวจสอบรายการ Backup ที่ลงทะเบียน", "status": "DONE"}
                ],
                "answer": "ยังไม่มีไฟล์ Backup ลงทะเบียนใน Backup Manager กรุณาเพิ่มหรือสร้างชุดทดสอบในแท็บ Backup ก่อนสั่งตรวจสอบ",
                "tool_outputs": {"backups_checked": 0, "results": []},
            }
            store.append_assistant_event(res)
            return res

        results = [check_backup_integrity(store, b.id, actor=actor) for b in backups[:10]]
        passed = sum(1 for x in results if x["status"] == "PASS")
        failed = sum(1 for x in results if x["status"] == "FAIL")
        blocked = sum(1 for x in results if x["status"] == "BLOCKED")
        res = {
            **base_meta,
            "intent": "check_backups",
            "risk_level": "low",
            "requires_approval": False,
            "executed": True,
            "plan_steps": [
                {"step": f"ดึงรายการ Backup ทั้งหมด ({len(results)} รายการ)", "status": "PASS"},
                {"step": "คำนวณ SHA-256 และตรวจ Manifest บนดิสก์จริง", "status": "FAIL" if failed else ("BLOCKED" if blocked else "PASS")},
            ],
            "answer": (
                f"ตรวจสอบ Backup จริงบนดิสก์แล้ว {len(results)} รายการ: "
                f"ผ่าน (PASS) {passed}, ไม่ผ่าน (FAIL) {failed}, ถูกบล็อก (BLOCKED) {blocked}"
            ),
            "tool_outputs": {"backups_checked": len(results), "results": results},
        }
        store.append_assistant_event(res)
        return res

    # 3. Compare runs intent
    if any(k in lower for k in ("เปรียบเทียบ", "compare", "diff", "เทียบผล")):
        runs = store.list_runs(limit=10)
        if len(runs) < 2:
            res = {
                **base_meta,
                "intent": "compare_runs",
                "risk_level": "low",
                "requires_approval": False,
                "executed": True,
                "plan_steps": [{"step": "ดึงผลรันอย่างน้อย 2 รอบเพื่อเปรียบเทียบ", "status": "BLOCKED"}],
                "answer": "ต้องมีผลตรวจสอบอย่างน้อย 2 รอบจึงจะเปรียบเทียบความเปลี่ยนแปลงได้",
                "tool_outputs": {},
            }
            store.append_assistant_event(res)
            return res
        cmp_data = compare_runs(runs[1], runs[0])
        res = {
            **base_meta,
            "intent": "compare_runs",
            "risk_level": "low",
            "requires_approval": False,
            "executed": True,
            "plan_steps": [
                {"step": f"เปรียบเทียบ {runs[1].run_id} กับ {runs[0].run_id}", "status": "PASS"}
            ],
            "referenced_run_ids": [runs[1].run_id, runs[0].run_id],
            "answer": (
                f"เปรียบเทียบ {runs[1].run_id} ({runs[1].status}) → {runs[0].run_id} ({runs[0].status}): "
                f"แถวต่างกัน {cmp_data['diff']['rows_delta']:+d} แถว, "
                f"SHA-256 {'เปลี่ยน' if cmp_data['diff']['sha256_changed'] else 'เหมือนเดิม'}"
            ),
            "tool_outputs": {"comparison": cmp_data},
        }
        store.append_assistant_event(res)
        return res

    # 4. Trigger Restore Test / Verification intent (Mutation/Compute -> Approval Gate)
    if any(k in lower for k in ("restore", "กู้คืน", "ทดสอบ", "รัน", "verify", "run test")):
        backups = store.list_backups()
        chosen_bkp = store.get_backup(context_backup_id) if context_backup_id else (backups[0] if backups else None)
        if not chosen_bkp:
            res = {
                **base_meta,
                "intent": "run_restore_verification",
                "risk_level": "medium",
                "requires_approval": False,
                "executed": False,
                "plan_steps": [{"step": "ค้นหา Backup Source เป้าหมาย", "status": "BLOCKED"}],
                "answer": "ยังไม่มี Backup Source สำหรับทดสอบ Restore — กรุณาสร้างหรือลงทะเบียนไฟล์ Backup ในแท็บ Backup ก่อน",
                "tool_outputs": {},
            }
            store.append_assistant_event(res)
            return res

        policies = store.get_policies()
        targets = store.list_targets()
        matched_target = next(
            (
                t
                for t in targets
                if (chosen_bkp.backup_format == "postgresql_custom" and t.engine == "postgresql")
                or (chosen_bkp.backup_format == "sqlite_dump" and t.engine == "sqlite")
                or (chosen_bkp.backup_format.startswith("archive_") and t.engine in ("archive", "sqlite"))
            ),
            targets[0] if targets else None,
        )
        readiness = check_target_readiness(matched_target, policies) if matched_target else {"ready": True, "status": "READY"}

        if not confirm_execution:
            res = {
                **base_meta,
                "intent": "run_restore_verification",
                "risk_level": "medium",
                "requires_approval": True,
                "executed": False,
                "plan_steps": [
                    {"step": f"ตรวจ Target Readiness: {matched_target.name if matched_target else 'Sandbox'} ({readiness['status']})", "status": readiness["status"]},
                    {"step": f"ตรวจ SHA-256 ของ {chosen_bkp.name} และแยกกู้คืนในพื้นที่ Isolation", "status": "AWAITING_APPROVAL"},
                    {"step": "ตรวจ Data Invariants, Health Query และ Cleanup อัตโนมัติ", "status": "PENDING"},
                ],
                "proposed_action": {
                    "type": "start_verification",
                    "backup_source_id": chosen_bkp.id,
                    "target_id": matched_target.id if matched_target else None,
                },
                "answer": (
                    f"วางแผนทดสอบ Restore สำหรับ '{chosen_bkp.name}' ({chosen_bkp.backup_format}) เรียบร้อยแล้ว "
                    f"[Target Readiness: {readiness['status']}] — กด 'อนุมัติและรันตามแผน' เพื่อให้ Restore Worker ทำงานจริง"
                ),
                "tool_outputs": {"backup": chosen_bkp.to_dict(), "readiness": readiness},
            }
            store.append_assistant_event(res)
            return res

        rid = new_run_id()
        rec = RunRecord(
            run_id=rid,
            source_name=chosen_bkp.name,
            backup_format=chosen_bkp.backup_format,
            backup_uri=chosen_bkp.uri,
            target_dbname=matched_target.target_dbname if matched_target else f"rp_verify_{rid}",
            min_total_rows=1,
            required_tables=["accounts"] if chosen_bkp.backup_format == "sqlite_dump" else [],
            expected_sha256=chosen_bkp.baseline_sha256 or None,
            status="RUNNING",
            started_at=utc_now_iso(),
            isolation_mode=matched_target.isolation_mode if matched_target else "sqlite_sandbox",
            drop_after_verify=policies.auto_cleanup_ephemeral,
            priority="normal",
            worker_id="worker-local-01",
            operator=f"assistant:{actor}",
            timeout_sec=policies.default_timeout_sec,
            max_retries=policies.default_max_retries,
            backup_source_id=chosen_bkp.id,
            target_id=matched_target.id if matched_target else None,
            steps=[StepRecord("file_and_sha256", "RUNNING", None, "Initiated via approved AI Operations plan")],
        )
        store.save(rec)
        record_audit(store, actor, "ASSISTANT_APPROVED_RUN", rid, "STARTED", f"Executed approved plan for backup {chosen_bkp.id}")
        finished = execute_verification_run(
            rec, store=store, pg_host=pg_host, pg_port=pg_port, pg_user=pg_user, cancel_flags=cancel_flags
        )
        diag = diagnose_run_failure(finished)
        res = {
            **base_meta,
            "intent": "run_restore_verification",
            "risk_level": "medium",
            "requires_approval": False,
            "executed": True,
            "plan_steps": [{"step": s.step_key, "status": s.status, "detail": s.detail} for s in finished.steps],
            "referenced_run_ids": [finished.run_id],
            "answer": f"รันการตรวจสอบจริงเสร็จสิ้นสำหรับ {finished.run_id} → ผลลัพธ์จาก Engine: {finished.status}. {diag['summary']}",
            "tool_outputs": {"run": finished.to_dict(), "diagnosis": diag},
        }
        store.append_assistant_event(res)
        return res

    # 5. Analyze Error / Failure / Explain Evidence / Run Lookup intent
    if target_run_id or any(
        k in lower for k in ("วิเคราะห์", "สาเหตุ", "ล้มเหลว", "พัง", "fail", "error", "blocked", "สรุป", "หลักฐาน", "evidence", "report")
    ):
        runs = store.list_runs(limit=30)
        chosen_run = store.get(target_run_id) if target_run_id else (
            next((r for r in runs if r.status in ("FAIL", "BLOCKED")), None) or (runs[0] if runs else None)
        )
        if not chosen_run:
            res = {
                **base_meta,
                "intent": "analyze_evidence",
                "risk_level": "low",
                "requires_approval": False,
                "executed": True,
                "plan_steps": [{"step": "ค้นหาหลักฐานการตรวจสอบใน EvidenceStore", "status": "DONE"}],
                "answer": "ยังไม่มี Run หรือ Evidence ให้วิเคราะห์ — กรุณารันการตรวจสอบจริงก่อน",
                "tool_outputs": {},
            }
            store.append_assistant_event(res)
            return res

        diag = diagnose_run_failure(chosen_run)
        res = {
            **base_meta,
            "intent": "analyze_evidence",
            "risk_level": "low",
            "requires_approval": False,
            "executed": True,
            "plan_steps": [
                {"step": f"โหลด Evidence และ Logs ของ {chosen_run.run_id}", "status": "PASS"},
                {"step": f"วิเคราะห์ Root Cause ({diag['root_cause_code']})", "status": chosen_run.status},
            ],
            "referenced_run_ids": [chosen_run.run_id],
            "answer": diag["summary"],
            "tool_outputs": {"diagnosis": diag, "run": chosen_run.to_dict()},
        }
        store.append_assistant_event(res)
        return res

    # 6. Default: System Health & Operations Overview
    mon = get_system_monitor(store)
    policies = store.get_policies()
    readiness_list = [check_target_readiness(t, policies) for t in store.list_targets()]
    rc = mon["run_counts"]
    res = {
        **base_meta,
        "intent": "system_overview",
        "risk_level": "low",
        "requires_approval": False,
        "executed": True,
        "plan_steps": [
            {"step": "ตรวจสถานะ Backend, CPU/RAM/Disk และ Worker", "status": "PASS"},
            {"step": "ตรวจ Readiness ของ Target Environments", "status": "PASS"},
        ],
        "answer": (
            f"สถานะระบบปัจจุบัน: งานทั้งหมด {rc['total']} รอบ (PASS {rc['passed']} / FAIL {rc['failed']} / BLOCKED {rc['blocked']}), "
            f"SQLite Sandbox: {'พร้อม' if mon['isolated_sqlite_ready'] else 'ไม่พร้อม'}, "
            f"PostgreSQL Worker (pg_restore/psql): {'พร้อม' if mon['isolated_pg_ready'] else 'ไม่พร้อม (BLOCKED)'}, "
            f"Backup ที่ลงทะเบียน {len(store.list_backups())} รายการ"
        ),
        "tool_outputs": {"monitor": mon, "targets_readiness": readiness_list},
    }
    store.append_assistant_event(res)
    return res
