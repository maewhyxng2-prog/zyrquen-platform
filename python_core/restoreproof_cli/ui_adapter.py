from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .engine import RestoreProofReport
except ImportError:
    from engine import RestoreProofReport


def _format_duration(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    if seconds < 1.0:
        return f"{int(round(seconds * 1000))} ms"
    sec_int = max(1, int(round(seconds)))
    if sec_int < 60:
        return f"{sec_int} วินาที"
    mins, rem = divmod(sec_int, 60)
    if rem == 0:
        return f"{mins}m"
    return f"{mins}m {rem:02d}s"


def _format_size(num_bytes: Optional[int]) -> Optional[str]:
    if num_bytes is None:
        return None
    size = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return None


def _short_hash(sha256_hex: Optional[str]) -> Optional[str]:
    if not sha256_hex or len(sha256_hex) < 12:
        return sha256_hex
    return f"{sha256_hex[:10]}....{sha256_hex[-4:]}"


def _build_steps(report: RestoreProofReport) -> List[Dict[str, Any]]:
    m = report.metrics
    step_timings: Dict[str, Optional[float]] = dict(m.get("step_durations_sec") or {})

    if not m.get("backup_exists"):
        integrity_status = "failed"
        integrity_detail = "ไม่พบไฟล์ Backup บนระบบ"
    elif m.get("hash_mismatches"):
        integrity_status = "failed"
        integrity_detail = f"พบไฟล์ที่ checksum ไม่ตรง: {m.get('hash_mismatches')}"
    else:
        integrity_status = "passed"
        integrity_detail = "ตรวจสอบไฟล์ Backup และคำนวณ SHA-256 เรียบร้อย"

    if not m.get("backup_exists"):
        restore_status = "not_run"
        restore_detail = "ไม่ได้รันการกู้คืนเนื่องจากไม่พบไฟล์ Backup"
    elif report.verified_restorable:
        restore_status = "passed"
        restore_detail = "ทดลองแตกไฟล์และกู้คืนในพื้นที่แยกสำเร็จ"
    else:
        restore_status = "failed"
        restore_detail = "การทดลองกู้คืนในพื้นที่แยกไม่สำเร็จ"

    if not m.get("backup_exists") or not report.verified_restorable:
        comp_status = "not_run"
        comp_detail = "ข้ามการตรวจความครบถ้วนเนื่องจากยังกู้คืนไฟล์ไม่สำเร็จ"
    elif report.completeness_ok:
        comp_status = "passed"
        comp_detail = f"จำนวนไฟล์ {m.get('restored_file_count', 0)} ไฟล์ ตรงตามเกณฑ์"
    else:
        comp_status = "failed"
        comp_detail = "ข้อมูลหลังกู้คืนไม่ครบหรือไม่ตรงตาม manifest"

    health_configured = m.get("health_cmd_configured", m.get("health_cmd_rc") is not None)
    if not report.verified_restorable or (health_configured and m.get("health_cmd_rc") is None):
        health_status = "not_run"
        health_detail = "ข้ามการตรวจสุขภาพบริการเนื่องจากยังไม่ผ่านการกู้คืน"
    elif report.health_check_ok:
        health_status = "passed"
        health_detail = (
            "คำสั่งตรวจสอบสุขภาพบริการผ่าน (exit code 0)"
            if health_configured
            else "ผ่านการกู้คืน (ไม่ได้ระบุคำสั่ง health-cmd แยก)"
        )
    else:
        health_status = "failed"
        health_detail = f"การตรวจสอบสภาพการทำงานไม่ผ่านเกณฑ์ (rc={m.get('health_cmd_rc')})"

    def _entry(key: str, title: str, status: str, detail: str) -> Dict[str, Any]:
        dur = step_timings.get(key)
        return {
            "step_key": key,
            "title": title,
            "status": status,
            "duration_sec": dur,
            "duration_label": _format_duration(dur),
            "detail": detail,
        }

    return [
        _entry("integrity_check", "ตรวจสอบข้อมูล Backup (Integrity Check)", integrity_status, integrity_detail),
        _entry("isolated_restore", "ทดลอง Restore ในระบบแยก", restore_status, restore_detail),
        _entry("data_completeness", "ตรวจสอบความครบถ้วนของข้อมูล", comp_status, comp_detail),
        _entry("service_health", "ตรวจสอบการทำงานของบริการ", health_status, health_detail),
    ]


def build_ui_payload(
    history_reports: List[RestoreProofReport],
    source_name: str = "Local Backup Target",
    backup_type: str = "Archive / Backup",
    is_demo: bool = False,
) -> Dict[str, Any]:
    """Builds UI payload strictly from observed execution reports; never fabricates PASS or 100% score."""
    now_iso = datetime.now(timezone.utc).isoformat()
    total_runs = len(history_reports)

    if total_runs == 0:
        return {
            "schema_version": "1.0.0",
            "product": "RealityCheck — RestoreProof",
            "source_mode": "demo_fixture" if is_demo else "live_verification",
            "is_demo": is_demo,
            "generated_at": now_iso,
            "summary": {
                "total_runs": 0,
                "runs_today": 0,
                "passed_runs": 0,
                "failed_runs": 0,
                "pass_rate_pct": None,
                "avg_duration_sec": None,
                "avg_duration_label": None,
            },
            "latest_run": None,
            "steps": [],
            "technical_details": None,
            "history": [],
            "reliability": {
                "score_pct": None,
                "score_label": None,
                "computation_rule": "no_verified_runs_yet",
                "checks": [],
                "verdict_text": "ยังไม่มีหลักฐานการตรวจสอบจริง ไม่สามารถยืนยันความพร้อมใช้งานได้",
            },
        }

    passed_runs = sum(1 for r in history_reports if r.overall_passed)
    failed_runs = total_runs - passed_runs
    pass_rate_pct = round((passed_runs / total_runs) * 100.0, 2)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    runs_today = sum(1 for r in history_reports if r.checked_at.startswith(today_str))

    durations = [
        float(r.metrics["total_duration_sec"])
        for r in history_reports
        if r.metrics.get("total_duration_sec") is not None
    ]
    avg_dur = round(sum(durations) / len(durations), 3) if durations else None

    latest = history_reports[-1]
    latest_dur = latest.metrics.get("total_duration_sec")
    latest_size = latest.metrics.get("backup_size_bytes")
    sha_full = latest.metrics.get("backup_sha256")
    restore_dur = (latest.metrics.get("step_durations_sec") or {}).get("isolated_restore")

    total_expected = len(latest.metrics.get("expected_manifest_files") or [])
    mismatches = len(latest.metrics.get("hash_mismatches") or [])
    missing = len(latest.metrics.get("missing_files") or [])
    if total_expected > 0:
        matched = max(0, total_expected - mismatches - missing)
        integrity_pct: Optional[float] = round((matched / total_expected) * 100.0, 2)
    elif latest.completeness_ok:
        integrity_pct = 100.0
    else:
        integrity_pct = None

    by_day: Dict[str, List[RestoreProofReport]] = defaultdict(list)
    for r in history_reports:
        day_key = r.checked_at[:10] if len(r.checked_at) >= 10 else "unknown"
        by_day[day_key].append(r)

    history_rows: List[Dict[str, Any]] = []
    for day_key in sorted(by_day.keys()):
        day_list = by_day[day_key]
        d_pass = sum(1 for x in day_list if x.overall_passed)
        d_fail = len(day_list) - d_pass
        try:
            dt_obj = datetime.strptime(day_key, "%Y-%m-%d") if len(day_key) == 10 else None
        except ValueError:
            dt_obj = None
        history_rows.append(
            {
                "date": day_key,
                "label": dt_obj.strftime("%d/%m") if dt_obj else day_key,
                "passed_count": d_pass,
                "failed_count": d_fail,
                "pass_rate_pct": round((d_pass / len(day_list)) * 100.0, 2),
            }
        )

    verified_flags = [
        latest.verified_restorable,
        latest.completeness_ok,
        latest.health_check_ok,
    ]
    latest_subcheck_score = (sum(1 for f in verified_flags if f) / len(verified_flags)) * 100.0
    rel_score_pct = round(min(pass_rate_pct, latest_subcheck_score), 2)

    if latest.overall_passed and pass_rate_pct == 100.0:
        verdict_text = f"ผ่านการตรวจสอบจริงทุกรอบ ({passed_runs}/{total_runs}) ตามเกณฑ์ที่ทดสอบ"
    elif latest.overall_passed:
        verdict_text = (
            f"รอบล่าสุดผ่านการตรวจสอบ แต่ประวัติรวมผ่าน {passed_runs}/{total_runs} ครั้ง — ควรตรวจประวัติย้อนหลังร่วมด้วย"
        )
    else:
        verdict_text = "ไม่ผ่านการตรวจสอบจริง — ห้ามถือว่า Backup พร้อมใช้งานจนกว่าจะแก้ไขข้อขัดแย้ง"

    return {
        "schema_version": "1.0.0",
        "product": "RealityCheck — RestoreProof",
        "source_mode": "demo_fixture" if is_demo else "live_verification",
        "is_demo": is_demo,
        "generated_at": now_iso,
        "summary": {
            "total_runs": total_runs,
            "runs_today": runs_today,
            "passed_runs": passed_runs,
            "failed_runs": failed_runs,
            "pass_rate_pct": pass_rate_pct,
            "avg_duration_sec": avg_dur,
            "avg_duration_label": _format_duration(avg_dur),
        },
        "latest_run": {
            "run_id": f"run_{latest.checked_at.replace(':', '').replace('-', '')[:15]}",
            "status": "passed" if latest.overall_passed else "failed",
            "status_label": "ผ่านการตรวจสอบ" if latest.overall_passed else "ไม่ผ่านการตรวจสอบ",
            "headline": (
                "Backup สามารถกู้คืนได้จริง ข้อมูลครบ และบริการผ่านการตรวจสอบตามเงื่อนไขที่กำหนด"
                if latest.overall_passed
                else "พบความคลาดเคลื่อนหรือการกู้คืนไม่สำเร็จตามหลักฐานจริง"
            ),
            "checked_at": latest.checked_at,
            "source_name": source_name,
            "data_size_bytes": latest_size,
            "data_size_label": _format_size(latest_size),
            "duration_sec": latest_dur,
            "duration_label": _format_duration(latest_dur),
            "discrepancies": list(latest.discrepancies),
        },
        "steps": _build_steps(latest),
        "technical_details": {
            "backup_type": backup_type,
            "file_size_label": _format_size(latest_size),
            "checksum_sha256": sha_full,
            "checksum_short": _short_hash(sha_full),
            "restore_time_label": _format_duration(restore_dur),
            "data_integrity_pct": integrity_pct,
            "data_integrity_label": f"{integrity_pct:.2f}%" if integrity_pct is not None else "N/A",
            "service_status": "OK" if latest.health_check_ok else "FAIL",
        },
        "history": history_rows,
        "reliability": {
            "score_pct": rel_score_pct,
            "score_label": f"{rel_score_pct:.0f}%" if float(rel_score_pct).is_integer() else f"{rel_score_pct}%",
            "computation_rule": "min(historical_pass_rate_pct, latest_verified_subchecks_pct)",
            "checks": [
                {"key": "restore_verified", "label": "Restore สำเร็จ", "passed": latest.verified_restorable},
                {"key": "data_complete", "label": "ข้อมูลครบถ้วน", "passed": latest.completeness_ok},
                {"key": "service_healthy", "label": "บริการทำงานปกติ", "passed": latest.health_check_ok},
            ],
            "verdict_text": verdict_text,
        },
    }


def write_ui_payload_from_reports(
    reports: List[RestoreProofReport],
    out_path: Path,
    source_name: str = "Local Backup Target",
    backup_type: str = "Archive / Backup",
    is_demo: bool = False,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_ui_payload(
        history_reports=reports,
        source_name=source_name,
        backup_type=backup_type,
        is_demo=is_demo,
    )
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
