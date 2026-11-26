from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

_PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE_DIR))

from reality_check.probes import safe_unpack_archive  # noqa: E402
from restoreproof_cli.db_restore_templates import build_sqlite_dump_commands  # noqa: E402
from restoreproof_cli.engine import run_restore_proof  # noqa: E402

try:
    from .isolated_worker import validate_isolated_dbname
    from .models import (
        AuditEntry,
        BackupSource,
        RestoreTarget,
        RunRecord,
        SecurityPolicies,
        StepRecord,
        utc_now_iso,
    )
    from .pg_verifier import compute_sha256, execute_postgresql_verification
    from .store import EvidenceStore
except ImportError:
    from isolated_worker import validate_isolated_dbname
    from models import (
        AuditEntry,
        BackupSource,
        RestoreTarget,
        RunRecord,
        SecurityPolicies,
        StepRecord,
        utc_now_iso,
    )
    from pg_verifier import compute_sha256, execute_postgresql_verification
    from store import EvidenceStore


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"run_{stamp}_{secrets.token_hex(2)}"


def new_entity_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def record_audit(
    store: EvidenceStore,
    actor: str,
    action: str,
    target: str,
    outcome: str,
    detail: str,
) -> AuditEntry:
    entry = AuditEntry(
        id=new_entity_id("aud"),
        timestamp=utc_now_iso(),
        actor=actor or "system",
        action=action,
        target=target,
        outcome=outcome,
        detail=detail[:400],
    )
    store.append_audit(entry)
    return entry


def _read_ram_stats() -> Dict[str, Optional[float]]:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return {"total_mb": None, "available_mb": None, "used_pct": None}
    values: Dict[str, int] = {}
    for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
        if ":" not in line:
            continue
        k, rest = line.split(":", 1)
        parts = rest.strip().split()
        if parts and parts[0].isdigit():
            values[k.strip()] = int(parts[0])
    total_kb = values.get("MemTotal")
    avail_kb = values.get("MemAvailable", values.get("MemFree"))
    if not total_kb or avail_kb is None:
        return {"total_mb": None, "available_mb": None, "used_pct": None}
    used_kb = max(0, total_kb - avail_kb)
    return {
        "total_mb": round(total_kb / 1024.0, 1),
        "available_mb": round(avail_kb / 1024.0, 1),
        "used_pct": round((used_kb / total_kb) * 100.0, 1),
    }


def detect_runtime_binaries() -> Dict[str, Any]:
    return {
        "python3": {
            "available": True,
            "version": platform.python_version(),
        },
        "sqlite3": {
            "available": True,
            "version": sqlite3.sqlite_version,
        },
        "pg_restore": {
            "available": shutil.which("pg_restore") is not None,
            "path": shutil.which("pg_restore"),
        },
        "psql": {
            "available": shutil.which("psql") is not None,
            "path": shutil.which("psql"),
        },
        "docker": {
            "available": shutil.which("docker") is not None,
            "path": shutil.which("docker"),
        },
    }


def get_system_monitor(store: EvidenceStore) -> Dict[str, Any]:
    binaries = detect_runtime_binaries()
    disk = shutil.disk_usage(store.data_dir)
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except OSError:
        load_1m, load_5m, load_15m = 0.0, 0.0, 0.0

    runs = store.list_runs(limit=200)
    counts = {
        "total": len(runs),
        "running": sum(1 for r in runs if r.status == "RUNNING"),
        "queued": sum(1 for r in runs if r.status == "QUEUED"),
        "passed": sum(1 for r in runs if r.status == "PASS"),
        "failed": sum(1 for r in runs if r.status == "FAIL"),
        "blocked": sum(1 for r in runs if r.status == "BLOCKED"),
        "cancelled": sum(1 for r in runs if r.status == "CANCELLED"),
    }

    workers = store.list_workers()
    worker_rows = []
    for w in workers:
        active_for_w = sum(
            1 for r in runs if r.worker_id == w.id and r.status in ("RUNNING", "QUEUED")
        )
        worker_rows.append(
            {
                **w.to_dict(),
                "active_jobs": active_for_w,
            }
        )

    alerts: List[Dict[str, str]] = []
    if not binaries["pg_restore"]["available"] or not binaries["psql"]["available"]:
        alerts.append(
            {
                "severity": "warning",
                "code": "PG_BINARIES_MISSING",
                "message": "ไม่พบ pg_restore/psql ใน worker นี้ — การตรวจ PostgreSQL .dump จะคืนค่า BLOCKED แบบ Fail-Closed (SQLite และ Archive ทำงานได้ปกติ)",
            }
        )
    for r in runs[:10]:
        if r.status == "FAIL":
            alerts.append(
                {
                    "severity": "error",
                    "code": "RUN_FAILED",
                    "run_id": r.run_id,
                    "message": f"งาน {r.run_id} ({r.source_name}) ล้มเหลว: {r.discrepancies[0] if r.discrepancies else 'ดูรายละเอียดหลักฐาน'}",
                }
            )
        elif r.status == "BLOCKED":
            alerts.append(
                {
                    "severity": "warning",
                    "code": "RUN_BLOCKED",
                    "run_id": r.run_id,
                    "message": f"งาน {r.run_id} ({r.source_name}) ถูกบล็อก: {r.discrepancies[0] if r.discrepancies else 'ขาดเงื่อนไขพร้อมรัน'}",
                }
            )

    return {
        "service": "realitycheck-restoreproof-backend",
        "version": "1.0.0",
        "checked_at": utc_now_iso(),
        "host": {
            "platform": platform.platform(),
            "cpu_count": os.cpu_count() or 1,
            "load_avg": [round(load_1m, 2), round(load_5m, 2), round(load_15m, 2)],
            "ram": _read_ram_stats(),
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "used_pct": round(((disk.total - disk.free) / max(1, disk.total)) * 100.0, 1),
            },
        },
        "binaries": binaries,
        "isolated_pg_ready": binaries["pg_restore"]["available"] and binaries["psql"]["available"],
        "isolated_sqlite_ready": True,
        "run_counts": counts,
        "workers": worker_rows,
        "alerts": alerts[:12],
    }


def check_target_readiness(
    target: RestoreTarget, policies: SecurityPolicies
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    block_reason: Optional[str] = None

    db_err = validate_isolated_dbname(target.target_dbname)
    if not db_err and target.target_dbname.lower() in {
        d.lower() for d in policies.reserved_db_blocklist
    }:
        db_err = f"Refusing reserved/production database name: {target.target_dbname}"

    checks.append(
        {
            "key": "reserved_db_guard",
            "label": "ป้องกันชื่อฐานข้อมูล Production",
            "passed": db_err is None,
            "detail": db_err or f"อนุญาตชื่อชั่วคราว '{target.target_dbname}'",
        }
    )
    if db_err:
        block_reason = db_err

    binaries = detect_runtime_binaries()
    if target.engine == "sqlite" or target.isolation_mode == "sqlite_sandbox":
        checks.append(
            {
                "key": "sqlite_runtime",
                "label": "SQLite3 Isolated Sandbox Runtime",
                "passed": True,
                "detail": f"พร้อมใช้งาน (SQLite {binaries['sqlite3']['version']})",
            }
        )
    elif target.engine == "archive" or target.isolation_mode == "archive_sandbox":
        checks.append(
            {
                "key": "archive_runtime",
                "label": "Archive Safe-Unpack Sandbox",
                "passed": True,
                "detail": "พร้อมใช้งาน (ป้องกัน Path Traversal และ Symlink)",
            }
        )
    elif target.isolation_mode == "docker_ephemeral":
        has_docker = bool(binaries["docker"]["available"])
        checks.append(
            {
                "key": "docker_binary",
                "label": "Docker Daemon / CLI",
                "passed": has_docker,
                "detail": "พร้อมใช้งาน" if has_docker else "ไม่พบคำสั่ง docker ใน worker",
            }
        )
        if not has_docker and not block_reason:
            block_reason = "Docker CLI not available for docker_ephemeral isolation"
    else:
        has_pg = bool(binaries["pg_restore"]["available"] and binaries["psql"]["available"])
        checks.append(
            {
                "key": "pg_binaries",
                "label": "PostgreSQL Client Tools (pg_restore + psql)",
                "passed": has_pg,
                "detail": "พร้อมใช้งาน" if has_pg else "ไม่พบ pg_restore หรือ psql ใน PATH",
            }
        )
        if not has_pg and not block_reason:
            block_reason = "pg_restore or psql binary not available in worker environment"

    ready = all(c["passed"] for c in checks)
    return {
        "target_id": target.id,
        "target_name": target.name,
        "engine": target.engine,
        "isolation_mode": target.isolation_mode,
        "ready": ready,
        "status": "READY" if ready else "BLOCKED",
        "block_reason": block_reason,
        "checks": checks,
        "checked_at": utc_now_iso(),
    }


def _confine_path(candidate: Path, allowed_root: Optional[Path]) -> Path:
    resolved = candidate.resolve()
    if allowed_root is not None:
        root_resolved = allowed_root.resolve()
        if resolved != root_resolved and not str(resolved).startswith(str(root_resolved) + os.sep):
            raise ValueError(f"Path outside allowed backup workspace: {candidate}")
    return resolved


def create_managed_backup_bundle(
    store: EvidenceStore,
    name: str,
    preset: str = "valid_sqlite",
    actor: str = "operator",
    custom_rows: Optional[List[tuple[int, str, float]]] = None,
) -> BackupSource:
    """
    Creates a real SQLite dump or archive backup artifact inside store.backups_vault_dir
    so operators can inspect SHA-256, tamper detection, and real isolated restores.
    """
    bid = new_entity_id("bkp")
    work = Path(tempfile.mkdtemp(prefix="rp_make_bkp_"))
    try:
        pkg = work / "pkg"
        pkg.mkdir()
        manifest: Dict[str, str] = {}
        backup_format = "sqlite_dump"
        notes = ""

        if preset in ("valid_sqlite", "low_rows_sqlite"):
            rows = custom_rows or (
                [(1, "alice", 1500.0), (2, "bob", 2300.5), (3, "charlie", 900.0)]
                if preset == "valid_sqlite"
                else [(1, "alice", 1500.0)]
            )
            dump_p = pkg / "dump.sql"
            src_db = work / "seed.sqlite3"
            conn = sqlite3.connect(str(src_db))
            try:
                conn.execute(
                    "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, balance REAL NOT NULL)"
                )
                conn.executemany(
                    "INSERT INTO accounts (id, name, balance) VALUES (?, ?, ?)", rows
                )
                conn.commit()
                dump_p.write_text("\n".join(conn.iterdump()) + "\n", encoding="utf-8")
            finally:
                conn.close()
            manifest["dump.sql"] = compute_sha256(dump_p)
            notes = f"Real SQLite SQL dump containing {len(rows)} rows in table 'accounts'"
            archive_path = Path(
                shutil.make_archive(str(store.backups_vault_dir / bid), "zip", root_dir=str(pkg))
            )
        elif preset == "tampered_manifest_archive":
            cfg = pkg / "config.json"
            data = pkg / "ledger.csv"
            cfg.write_text('{"mode": "strict"}\n', encoding="utf-8")
            data.write_text("id,amount\n1,500\n2,750\n", encoding="utf-8")
            manifest["config.json"] = compute_sha256(cfg)
            manifest["ledger.csv"] = compute_sha256(data)
            # Tamper config.json AFTER recording baseline manifest
            cfg.write_text('{"mode": "tampered"}\n', encoding="utf-8")
            backup_format = "archive_zip"
            notes = "Archive whose config.json was altered after manifest generation"
            archive_path = Path(
                shutil.make_archive(str(store.backups_vault_dir / bid), "zip", root_dir=str(pkg))
            )
        elif preset == "corrupt_archive":
            backup_format = "archive_zip"
            archive_path = store.backups_vault_dir / f"{bid}.zip"
            archive_path.write_bytes(b"CORRUPTED_BINARY_NOT_A_VALID_ZIP_0001")
            manifest = {"dump.sql": "0" * 64}
            notes = "Corrupt zip artifact to prove Fail-Closed unpack rejection"
        elif preset == "pg_custom_sample":
            backup_format = "postgresql_custom"
            archive_path = store.backups_vault_dir / f"{bid}.dump"
            archive_path.write_bytes(b"PGDMP_SAMPLE_HEADER_FOR_READINESS_TEST")
            manifest = {}
            notes = "Sample PostgreSQL custom dump header (requires pg_restore + psql worker)"
        else:
            raise ValueError(f"Unsupported backup preset: {preset}")

        sha = compute_sha256(archive_path)
        size_b = archive_path.stat().st_size
        source = BackupSource(
            id=bid,
            name=name.strip() or f"Backup {bid}",
            backup_format=backup_format,
            uri=str(archive_path),
            size_bytes=size_b,
            sha256=sha,
            baseline_sha256=sha,
            file_count=max(1, len(manifest)),
            manifest_hashes=manifest,
            notes=notes,
        )
        store.save_backup(source)
        record_audit(
            store,
            actor,
            "BACKUP_CREATED",
            bid,
            "CREATED",
            f"Created managed backup '{source.name}' ({backup_format}, sha256={sha[:12]}...)",
        )
        return source
    finally:
        shutil.rmtree(work, ignore_errors=True)


def register_backup_source(
    store: EvidenceStore,
    name: str,
    backup_format: str,
    uri: str,
    manifest_hashes: Optional[Dict[str, str]] = None,
    actor: str = "operator",
    allowed_root: Optional[Path] = None,
) -> BackupSource:
    p = _confine_path(Path(uri), allowed_root)
    if p.exists() and p.is_file():
        sha = compute_sha256(p)
        size_b = p.stat().st_size
    else:
        sha = ""
        size_b = 0
    bid = new_entity_id("bkp")
    source = BackupSource(
        id=bid,
        name=name.strip() or p.name,
        backup_format=backup_format,
        uri=str(p),
        size_bytes=size_b,
        sha256=sha,
        baseline_sha256=sha,
        file_count=max(1, len(manifest_hashes or {})),
        manifest_hashes=dict(manifest_hashes or {}),
    )
    store.save_backup(source)
    record_audit(
        store,
        actor,
        "BACKUP_REGISTERED",
        bid,
        "REGISTERED",
        f"Registered backup '{source.name}' uri={p}",
    )
    return source


def check_backup_integrity(
    store: EvidenceStore, backup_id: str, actor: str = "operator"
) -> Dict[str, Any]:
    src = store.get_backup(backup_id)
    if src is None:
        raise KeyError(f"Backup source not found: {backup_id}")

    p = Path(src.uri)
    checked_at = utc_now_iso()
    discrepancies: List[str] = []

    if not p.exists() or not p.is_file():
        src.last_checked_at = checked_at
        src.last_check_status = "BLOCKED"
        discrepancies.append(f"Backup file missing on disk: {src.uri}")
        src.last_discrepancies = discrepancies
        store.save_backup(src)
        record_audit(store, actor, "BACKUP_CHECK", backup_id, "BLOCKED", discrepancies[0])
        return {
            "backup": src.to_dict(),
            "status": "BLOCKED",
            "sha256_current": None,
            "sha256_drift": False,
            "discrepancies": discrepancies,
            "checked_at": checked_at,
        }

    current_sha = compute_sha256(p)
    current_size = p.stat().st_size
    sha_drift = bool(src.baseline_sha256 and current_sha != src.baseline_sha256)
    if sha_drift:
        discrepancies.append(
            f"Archive SHA-256 changed since baseline: expected={src.baseline_sha256[:16]}..., actual={current_sha[:16]}..."
        )

    status = "PASS"
    restored_files: Dict[str, str] = {}
    if src.backup_format in ("sqlite_dump", "archive_zip", "archive_tar"):
        tmp_dir = Path(tempfile.mkdtemp(prefix="rp_bkp_chk_"))
        try:
            safe_unpack_archive(p, tmp_dir)
            for fp in sorted(tmp_dir.rglob("*")):
                if fp.is_file():
                    restored_files[fp.relative_to(tmp_dir).as_posix()] = compute_sha256(fp)
            for rel, exp_h in src.manifest_hashes.items():
                got_h = restored_files.get(rel.lstrip("./"))
                if got_h is None:
                    discrepancies.append(f"Missing manifest file: {rel}")
                elif got_h.lower() != exp_h.lower():
                    discrepancies.append(f"Manifest hash mismatch: {rel}")
        except Exception as exc:
            discrepancies.append(f"Archive unreadable or unsafe: {type(exc).__name__}: {exc}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    elif src.backup_format == "postgresql_custom":
        header = p.read_bytes()[:5]
        if header != b"PGDMP":
            discrepancies.append("Invalid PostgreSQL custom dump signature (missing PGDMP header)")

    if discrepancies:
        status = "FAIL"

    src.sha256 = current_sha
    src.size_bytes = current_size
    src.last_checked_at = checked_at
    src.last_check_status = status
    src.last_discrepancies = discrepancies
    store.save_backup(src)
    record_audit(
        store,
        actor,
        "BACKUP_CHECK",
        backup_id,
        status,
        "; ".join(discrepancies) if discrepancies else f"Integrity verified (sha256={current_sha[:12]}...)",
    )
    return {
        "backup": src.to_dict(),
        "status": status,
        "sha256_current": current_sha,
        "sha256_drift": sha_drift,
        "files_inspected": len(restored_files),
        "discrepancies": discrepancies,
        "checked_at": checked_at,
    }


def _finalize_cancelled(record: RunRecord, t_start: float) -> RunRecord:
    record.status = "CANCELLED"
    record.finished_at = utc_now_iso()
    record.duration_sec = round(time.perf_counter() - t_start, 3)
    if not any(s.status == "CANCELLED" for s in record.steps):
        record.steps.append(StepRecord("execution", "CANCELLED", record.duration_sec, "งานถูกยกเลิกอย่างปลอดภัยตามคำสั่งผู้ดูแล"))
    record.discrepancies.append("Job cancelled by operator before completion")
    record.logs_tail.append("[CANCEL] Execution aborted safely and workspace cleaned.")
    record.report = {
        "report_id": record.run_id,
        "run_id": record.run_id,
        "verdict": "CANCELLED",
        "evidence_complete": False,
        "verified_at": record.finished_at,
        "backup_artifact": {
            "uri": record.backup_uri,
            "format": record.backup_format,
            "size_bytes": Path(record.backup_uri).stat().st_size if Path(record.backup_uri).exists() else None,
            "sha256_actual": None,
            "sha256_matched": None,
        },
        "restore_evidence": {
            "isolation_mode": record.isolation_mode,
            "target_dbname": record.target_dbname,
            "pg_restore_exit_code": None,
            "health_query_exit_code": None,
            "tables_found": [],
            "missing_tables": list(record.required_tables),
            "total_rows_observed": 0,
            "min_total_rows_required": record.min_total_rows,
        },
        "steps": [s.__dict__ for s in record.steps],
        "discrepancies": list(record.discrepancies),
    }
    return record


def execute_verification_run(
    record: RunRecord,
    store: EvidenceStore,
    pg_host: str = "127.0.0.1",
    pg_port: int = 5432,
    pg_user: str = "postgres",
    cancel_flags: Optional[Dict[str, threading.Event]] = None,
) -> RunRecord:
    """
    Executes real verification & isolated restore for PostgreSQL custom dump,
    SQLite SQL dump (.zip), or generic archive bundles.
    """
    t_start = time.perf_counter()
    cancel_ev = cancel_flags.get(record.run_id) if cancel_flags else None
    if record.cancel_requested or (cancel_ev and cancel_ev.is_set()):
        updated = _finalize_cancelled(record, t_start)
        store.save(updated)
        return updated

    if record.backup_format == "postgresql_custom":
        record.logs_tail.append(f"[START] PostgreSQL verification -> {record.target_dbname} ({record.isolation_mode})")
        store.save(record)
        updated = execute_postgresql_verification(
            record=record, pg_host=pg_host, pg_port=pg_port, pg_user=pg_user
        )
        if cancel_ev and cancel_ev.is_set():
            updated = _finalize_cancelled(updated, t_start)
        else:
            if updated.report is not None:
                updated.report["report_sha256"] = hashlib.sha256(
                    json.dumps(updated.report, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
            updated.logs_tail.extend(updated.discrepancies[-4:] or [f"[{updated.status}] Completed in {updated.duration_sec}s"])
        store.save(updated)
        record_audit(
            store,
            updated.operator,
            "VERIFICATION_FINISHED",
            updated.run_id,
            updated.status,
            f"format={updated.backup_format} verdict={updated.status}",
        )
        return updated

    # SQLite dump (.zip) or generic archive verification
    backup_path = Path(record.backup_uri)
    steps: List[StepRecord] = []
    discrepancies: List[str] = []
    logs: List[str] = [f"[START] {record.backup_format} verification -> {record.isolation_mode}"]

    policies = store.get_policies()
    db_err = validate_isolated_dbname(record.target_dbname)
    if not db_err and record.target_dbname.lower() in {d.lower() for d in policies.reserved_db_blocklist}:
        db_err = f"Refusing reserved/production database name: {record.target_dbname}"
    if db_err:
        record.status = "BLOCKED"
        record.discrepancies = [db_err]
        record.steps = [StepRecord("environment_readiness", "BLOCKED", 0.0, db_err)]
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.logs_tail = logs + [f"[BLOCKED] {db_err}"]
        record.report = _build_sandbox_report(record, None, None, None, 0, [], record.required_tables, None, None)
        store.save(record)
        return record

    if not backup_path.exists() or not backup_path.is_file():
        msg = f"Backup artifact not found: {record.backup_uri}"
        record.status = "BLOCKED"
        record.discrepancies = [msg]
        record.steps = [
            StepRecord("file_and_sha256", "BLOCKED", 0.0, msg),
            StepRecord("isolated_restore", "NOT_RUN", None, "ไม่ได้รันเนื่องจากไม่พบไฟล์"),
            StepRecord("data_completeness", "NOT_RUN", None, "ไม่ได้รันเนื่องจากไม่พบไฟล์"),
        ]
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.logs_tail = logs + [f"[BLOCKED] {msg}"]
        record.report = _build_sandbox_report(record, 0, None, None, 0, [], record.required_tables, None, None)
        store.save(record)
        return record

    size_bytes = backup_path.stat().st_size
    actual_sha = compute_sha256(backup_path)
    sha_matched: Optional[bool] = None
    if record.expected_sha256:
        sha_matched = actual_sha.lower() == record.expected_sha256.strip().lower()
        if not sha_matched:
            discrepancies.append(
                f"SHA-256 mismatch: expected={record.expected_sha256.strip().lower()}, actual={actual_sha}"
            )
    if sha_matched is False:
        record.status = "FAIL"
        record.discrepancies = discrepancies
        record.steps = [
            StepRecord("file_and_sha256", "FAIL", round(time.perf_counter() - t_start, 3), "SHA-256 ไม่ตรงกับค่าที่ระบุ"),
            StepRecord("isolated_restore", "NOT_RUN", None, "ข้ามเนื่องจาก SHA-256 ไม่ตรง"),
            StepRecord("data_completeness", "NOT_RUN", None, "ข้ามเนื่องจาก SHA-256 ไม่ตรง"),
        ]
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.logs_tail = logs + [f"[FAIL] {discrepancies[0]}"]
        record.report = _build_sandbox_report(record, size_bytes, actual_sha, sha_matched, 0, [], record.required_tables, None, None)
        store.save(record)
        return record

    steps.append(
        StepRecord(
            "file_and_sha256",
            "PASS",
            round(time.perf_counter() - t_start, 3),
            f"SHA-256 ตรวจผ่าน ({actual_sha[:12]}...)",
        )
    )

    if cancel_ev and cancel_ev.is_set():
        record.steps = steps
        updated = _finalize_cancelled(record, t_start)
        store.save(updated)
        return updated

    expected_manifest: Optional[Dict[str, str]] = None
    if record.backup_source_id:
        bkp = store.get_backup(record.backup_source_id)
        if bkp and bkp.manifest_hashes:
            expected_manifest = dict(bkp.manifest_hashes)

    restore_cmd: Optional[List[str]] = None
    health_cmd: Optional[List[str]] = None
    if record.backup_format == "sqlite_dump":
        cmds = build_sqlite_dump_commands(
            dump_filename="dump.sql",
            restored_db_filename="restored_check.sqlite3",
            min_total_rows=record.min_total_rows,
            required_tables=record.required_tables,
        )
        restore_cmd = cmds.restore_cmd
        health_cmd = cmds.health_cmd

    rp_report = run_restore_proof(
        backup_path=backup_path,
        min_files=1,
        expected_manifest_hashes=expected_manifest,
        restore_cmd=restore_cmd,
        health_cmd=health_cmd,
        timeout_sec=record.timeout_sec,
    )

    m = rp_report.metrics
    durs = m.get("step_durations_sec") or {}
    steps.append(
        StepRecord(
            "isolated_restore",
            "PASS" if rp_report.verified_restorable else "FAIL",
            durs.get("isolated_restore"),
            "กู้คืนใน Sandbox แยกส่วนสำเร็จ" if rp_report.verified_restorable else "การกู้คืนใน Sandbox ล้มเหลว",
        )
    )
    steps.append(
        StepRecord(
            "data_completeness",
            "PASS" if (rp_report.completeness_ok and rp_report.health_check_ok) else ("NOT_RUN" if not rp_report.verified_restorable else "FAIL"),
            durs.get("service_health") or durs.get("data_completeness"),
            str(m.get("health_stdout_tail") or f"ตรวจสอบไฟล์ {m.get('restored_file_count', 0)} ไฟล์"),
        )
    )
    steps.append(
        StepRecord(
            "cleanup",
            "PASS",
            0.001,
            "ลบพื้นที่ Sandbox ชั่วคราวเรียบร้อยหลังจบการตรวจสอบ",
        )
    )

    if m.get("health_stderr_tail"):
        logs.append(f"[HEALTH_STDERR] {m['health_stderr_tail']}")
    if m.get("restore_stderr_tail"):
        logs.append(f"[RESTORE_STDERR] {m['restore_stderr_tail']}")
    if m.get("health_stdout_tail"):
        logs.append(f"[HEALTH_STDOUT] {m['health_stdout_tail']}")

    # Extract parsed row/table metrics if SQLITE_RESTORE_OK present
    observed_rows = 0
    tables_found: List[str] = []
    stdout_tail = str(m.get("health_stdout_tail") or "")
    if "rows=" in stdout_tail:
        try:
            observed_rows = int(stdout_tail.split("rows=")[-1].split()[0])
        except Exception:
            observed_rows = 0
    if rp_report.health_check_ok and record.required_tables:
        tables_found = list(record.required_tables)

    discrepancies.extend(rp_report.discrepancies)
    verdict = "PASS" if rp_report.overall_passed else "FAIL"
    record.status = verdict
    record.steps = steps
    record.discrepancies = discrepancies
    record.finished_at = utc_now_iso()
    record.duration_sec = round(time.perf_counter() - t_start, 3)
    record.logs_tail = logs + (discrepancies[:4] or [f"[{verdict}] Verified cleanly"])
    record.report = _build_sandbox_report(
        record=record,
        size_bytes=size_bytes,
        actual_sha=actual_sha,
        sha_matched=sha_matched,
        observed_rows=observed_rows,
        tables_found=tables_found,
        missing_tables=[] if rp_report.health_check_ok else list(record.required_tables),
        restore_rc=m.get("restore_cmd_rc"),
        health_rc=m.get("health_cmd_rc"),
    )
    store.save(record)
    record_audit(
        store,
        record.operator,
        "VERIFICATION_FINISHED",
        record.run_id,
        verdict,
        f"format={record.backup_format} verdict={verdict}",
    )
    return record


def _build_sandbox_report(
    record: RunRecord,
    size_bytes: Optional[int],
    actual_sha: Optional[str],
    sha_matched: Optional[bool],
    observed_rows: int,
    tables_found: List[str],
    missing_tables: List[str],
    restore_rc: Optional[int],
    health_rc: Optional[int],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "report_id": record.run_id,
        "run_id": record.run_id,
        "verdict": record.status,
        "evidence_complete": record.status in ("PASS", "FAIL"),
        "verified_at": record.finished_at or utc_now_iso(),
        "backup_artifact": {
            "uri": record.backup_uri,
            "format": record.backup_format,
            "size_bytes": size_bytes,
            "sha256_actual": actual_sha,
            "sha256_matched": sha_matched,
        },
        "restore_evidence": {
            "isolation_mode": record.isolation_mode,
            "target_dbname": record.target_dbname,
            "pg_restore_exit_code": restore_rc,
            "health_query_exit_code": health_rc,
            "tables_found": tables_found,
            "missing_tables": missing_tables,
            "total_rows_observed": observed_rows,
            "min_total_rows_required": record.min_total_rows,
        },
        "steps": [s.__dict__ for s in record.steps],
        "discrepancies": list(record.discrepancies),
    }
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return payload


def cancel_run(
    store: EvidenceStore,
    run_id: str,
    actor: str = "operator",
    cancel_flags: Optional[Dict[str, threading.Event]] = None,
) -> RunRecord:
    rec = store.get(run_id)
    if rec is None:
        raise KeyError(f"Run not found: {run_id}")
    if rec.status not in ("QUEUED", "RUNNING"):
        raise ValueError(f"Cannot cancel run in terminal state '{rec.status}'")
    rec.cancel_requested = True
    if cancel_flags and run_id in cancel_flags:
        cancel_flags[run_id].set()
    rec = _finalize_cancelled(rec, time.perf_counter())
    store.save(rec)
    record_audit(store, actor, "JOB_CANCELLED", run_id, "CANCELLED", "Cancelled active/queued job safely")
    return rec


def compare_runs(run_a: RunRecord, run_b: RunRecord) -> Dict[str, Any]:
    rep_a = run_a.report or {}
    rep_b = run_b.report or {}
    ev_a = rep_a.get("restore_evidence") or {}
    ev_b = rep_b.get("restore_evidence") or {}
    art_a = rep_a.get("backup_artifact") or {}
    art_b = rep_b.get("backup_artifact") or {}

    rows_a = int(ev_a.get("total_rows_observed") or 0)
    rows_b = int(ev_b.get("total_rows_observed") or 0)
    tables_a = set(ev_a.get("tables_found") or [])
    tables_b = set(ev_b.get("tables_found") or [])

    return {
        "run_a": {
            "run_id": run_a.run_id,
            "source_name": run_a.source_name,
            "status": run_a.status,
            "duration_sec": run_a.duration_sec,
            "rows_observed": rows_a,
            "sha256": art_a.get("sha256_actual"),
            "discrepancies_count": len(run_a.discrepancies),
        },
        "run_b": {
            "run_id": run_b.run_id,
            "source_name": run_b.source_name,
            "status": run_b.status,
            "duration_sec": run_b.duration_sec,
            "rows_observed": rows_b,
            "sha256": art_b.get("sha256_actual"),
            "discrepancies_count": len(run_b.discrepancies),
        },
        "diff": {
            "verdict_changed": run_a.status != run_b.status,
            "verdict_transition": f"{run_a.status} -> {run_b.status}",
            "rows_delta": rows_b - rows_a,
            "duration_delta_sec": round((run_b.duration_sec or 0.0) - (run_a.duration_sec or 0.0), 3),
            "sha256_changed": art_a.get("sha256_actual") != art_b.get("sha256_actual"),
            "tables_added": sorted(tables_b - tables_a),
            "tables_removed": sorted(tables_a - tables_b),
            "new_discrepancies": [d for d in run_b.discrepancies if d not in run_a.discrepancies],
            "resolved_discrepancies": [d for d in run_a.discrepancies if d not in run_b.discrepancies],
        },
        "compared_at": utc_now_iso(),
    }
