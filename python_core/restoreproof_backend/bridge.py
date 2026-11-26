from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
from typing import Any, Dict, List, Optional

_PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE_DIR))

from restoreproof_cli.db_restore_templates import build_sqlite_dump_commands  # noqa: E402
from restoreproof_cli.engine import RestoreProofReport, file_sha256, run_restore_proof  # noqa: E402
from restoreproof_cli.ui_adapter import build_ui_payload  # noqa: E402

try:
    from .control_engine import (
        cancel_run,
        check_backup_integrity,
        check_target_readiness,
        compare_runs,
        create_managed_backup_bundle,
        execute_verification_run,
        get_system_monitor,
        new_entity_id,
        new_run_id,
        record_audit,
        register_backup_source,
    )
    from .models import (
        RestoreTarget,
        RunRecord,
        SecurityPolicies,
        StepRecord,
        VALID_BACKUP_FORMATS,
        VALID_ISOLATION_MODES,
        VALID_PRIORITIES,
        WorkerNode,
        utc_now_iso,
    )
    from .ops_assistant import diagnose_run_failure, process_assistant_command
    from .store import EvidenceStore
except ImportError:
    from control_engine import (
        cancel_run,
        check_backup_integrity,
        check_target_readiness,
        compare_runs,
        create_managed_backup_bundle,
        execute_verification_run,
        get_system_monitor,
        new_entity_id,
        new_run_id,
        record_audit,
        register_backup_source,
    )
    from models import (
        RestoreTarget,
        RunRecord,
        SecurityPolicies,
        StepRecord,
        VALID_BACKUP_FORMATS,
        VALID_ISOLATION_MODES,
        VALID_PRIORITIES,
        WorkerNode,
        utc_now_iso,
    )
    from ops_assistant import diagnose_run_failure, process_assistant_command
    from store import EvidenceStore


_BRIDGE_CANCEL_FLAGS: Dict[str, threading.Event] = {}
_HISTORY_LOCK = threading.Lock()


def _history_file(data_dir: Path) -> Path:
    return data_dir / "restoreproof_history.json"


def _load_history(data_dir: Path) -> List[Dict[str, Any]]:
    hp = _history_file(data_dir)
    if not hp.exists():
        return []
    try:
        raw = json.loads(hp.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save_history(data_dir: Path, items: List[Dict[str, Any]]) -> None:
    hp = _history_file(data_dir)
    hp.parent.mkdir(parents=True, exist_ok=True)
    tmp = hp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(hp)


def _to_report_obj(raw: Dict[str, Any]) -> RestoreProofReport:
    return RestoreProofReport(
        target=str(raw["target"]),
        verified_restorable=bool(raw["verified_restorable"]),
        completeness_ok=bool(raw["completeness_ok"]),
        health_check_ok=bool(raw["health_check_ok"]),
        overall_passed=bool(raw["overall_passed"]),
        discrepancies=list(raw.get("discrepancies") or []),
        metrics=dict(raw.get("metrics") or {}),
        checked_at=str(raw["checked_at"]),
    )


def _validate_rel_bundle_path(rel_path: str) -> Path:
    cleaned = rel_path.strip().replace("\\", "/")
    if not cleaned or "\x00" in cleaned or cleaned.startswith("/"):
        raise ValueError(f"Unsafe file path: {rel_path!r}")
    parts = [p for p in cleaned.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise ValueError(f"Path traversal blocked: {rel_path!r}")
    return Path(*parts)


def _run_single_scenario(scenario: str) -> tuple[RestoreProofReport, str, str]:
    work_dir = Path(tempfile.mkdtemp(prefix="rp_ui_scen_"))
    try:
        if scenario == "valid_sqlite_backup":
            pkg = work_dir / "pkg_ok"
            pkg.mkdir()
            dump_p = pkg / "dump.sql"
            db_src = work_dir / "seed.sqlite3"
            conn = sqlite3.connect(str(db_src))
            try:
                conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, balance REAL)")
                conn.executemany(
                    "INSERT INTO accounts (id, name, balance) VALUES (?, ?, ?)",
                    [(1, "alice", 1500.0), (2, "bob", 2300.5), (3, "charlie", 900.0)],
                )
                conn.commit()
                dump_p.write_text("\n".join(conn.iterdump()) + "\n", encoding="utf-8")
            finally:
                conn.close()
            manifest = {"dump.sql": file_sha256(dump_p)}
            zip_ok = Path(shutil.make_archive(str(work_dir / "valid_sqlite"), "zip", root_dir=str(pkg)))
            cmds = build_sqlite_dump_commands(
                dump_filename="dump.sql",
                restored_db_filename="restored_check.sqlite3",
                min_total_rows=3,
                required_tables=["accounts"],
            )
            rep = run_restore_proof(
                backup_path=zip_ok,
                min_files=1,
                expected_manifest_hashes=manifest,
                restore_cmd=cmds.restore_cmd,
                health_cmd=cmds.health_cmd,
            )
            return rep, "Valid SQLite Dump Sandbox Probe", "SQLite SQL Dump (.zip)"

        if scenario == "corrupt_archive":
            bad_zip = work_dir / "corrupt_backup.zip"
            bad_zip.write_bytes(b"NOT_A_REAL_ZIP_ARCHIVE_000000")
            rep = run_restore_proof(
                backup_path=bad_zip,
                min_files=1,
                expected_manifest_hashes={"dump.sql": "0" * 64},
            )
            return rep, "Corrupt Archive Probe (Failure Case 1)", "Archive (.zip)"

        if scenario == "missing_tampered_file":
            pkg = work_dir / "pkg_tamper"
            pkg.mkdir()
            f_sqlite = pkg / "app.sqlite"
            f_cfg = pkg / "config.json"
            f_ledger = pkg / "ledger.txt"
            f_sqlite.write_bytes(b"SQLITE_BYTES_SAMPLE")
            f_cfg.write_text('{"mode": "strict"}\n', encoding="utf-8")
            f_ledger.write_text("tx=100\n", encoding="utf-8")
            manifest = {
                "app.sqlite": file_sha256(f_sqlite),
                "config.json": file_sha256(f_cfg),
                "ledger.txt": file_sha256(f_ledger),
            }
            # Drop app.sqlite and tamper config.json
            f_sqlite.unlink()
            f_cfg.write_text('{"mode": "tampered"}\n', encoding="utf-8")
            broken_zip = Path(shutil.make_archive(str(work_dir / "tampered_backup"), "zip", root_dir=str(pkg)))
            rep = run_restore_proof(
                backup_path=broken_zip,
                min_files=3,
                expected_manifest_hashes=manifest,
            )
            return rep, "Tampered/Missing Manifest Probe (Failure Case 2)", "SQLite + Config (.zip)"

        if scenario == "failed_health_check":
            pkg = work_dir / "pkg_health_fail"
            pkg.mkdir()
            f_cfg = pkg / "config.json"
            f_cfg.write_text('{"mode": "strict"}\n', encoding="utf-8")
            manifest = {"config.json": file_sha256(f_cfg)}
            ok_zip = Path(shutil.make_archive(str(work_dir / "health_fail_backup"), "zip", root_dir=str(pkg)))
            rep = run_restore_proof(
                backup_path=ok_zip,
                min_files=1,
                expected_manifest_hashes=manifest,
                health_cmd=[
                    sys.executable,
                    "-c",
                    "import sys; print('DB_CORRUPT_TABLE', file=sys.stderr); sys.exit(3)",
                ],
            )
            return rep, "Health Probe Failure (Failure Case 3)", "Service Config (.zip)"

        raise ValueError(f"Unsupported scenario: {scenario}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _get_control_store(data_dir: Path) -> EvidenceStore:
    return EvidenceStore(data_dir / "restoreproof_control")


def handle_restoreproof_bridge(action: str, payload: Dict[str, Any], data_dir: Path) -> Dict[str, Any]:
    # 1) Classic RestoreProof Panel & E2E endpoints
    if action == "restoreproof_status":
        with _HISTORY_LOCK:
            rows = _load_history(data_dir)
        reports = [_to_report_obj(r["report"]) for r in rows]
        last_src = rows[-1]["source_name"] if rows else "Local Backup Target"
        last_type = rows[-1]["backup_type"] if rows else "Archive / Backup"
        ui_payload = build_ui_payload(
            reports, source_name=last_src, backup_type=last_type, is_demo=False
        )
        return {"ok": True, "ui_payload": ui_payload}

    if action == "restoreproof_verify_scenario":
        scenario = str(payload.get("scenario", "")).strip()
        seq = (
            ["corrupt_archive", "missing_tampered_file", "failed_health_check"]
            if scenario == "run_all_3_failures"
            else [scenario]
        )
        new_entries: List[Dict[str, Any]] = []
        raw_reports: List[Dict[str, Any]] = []
        for sname in seq:
            rep, src_name, bkp_type = _run_single_scenario(sname)
            r_dict = rep.to_dict()
            raw_reports.append(r_dict)
            new_entries.append(
                {"source_name": src_name, "backup_type": bkp_type, "report": r_dict}
            )
        with _HISTORY_LOCK:
            rows = _load_history(data_dir)
            rows.extend(new_entries)
            rows = rows[-100:]
            _save_history(data_dir, rows)
        all_reports = [_to_report_obj(r["report"]) for r in rows]
        ui_payload = build_ui_payload(
            all_reports,
            source_name=new_entries[-1]["source_name"],
            backup_type=new_entries[-1]["backup_type"],
            is_demo=False,
        )
        return {"ok": True, "reports": raw_reports, "ui_payload": ui_payload}

    if action == "restoreproof_verify_bundle":
        raw_files = payload.get("files") or []
        if not isinstance(raw_files, list) or len(raw_files) == 0:
            return {"ok": False, "status_code": 400, "error": "files array must not be empty"}
        source_name = str(payload.get("sourceName") or "Custom Backup Bundle").strip()
        backup_type = str(payload.get("backupType") or "Custom Bundle (.zip)").strip()
        tamper = str(payload.get("simulateTamper") or "none").strip()
        min_files = int(payload.get("minFiles") or len(raw_files))

        work_dir = Path(tempfile.mkdtemp(prefix="rp_custom_bundle_"))
        try:
            stage = work_dir / "stage"
            stage.mkdir()
            stage_resolved = stage.resolve()
            manifest: Dict[str, str] = {}
            ordered_paths: List[Path] = []

            for item in raw_files:
                if not isinstance(item, dict):
                    return {"ok": False, "status_code": 400, "error": "Each file entry must be an object"}
                rel_p = _validate_rel_bundle_path(str(item.get("path", "")))
                dest = (stage_resolved / rel_p).resolve()
                if not str(dest).startswith(str(stage_resolved) + os.sep):
                    return {"ok": False, "status_code": 400, "error": "Path escapes staging directory"}
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(str(item.get("content", "")), encoding="utf-8")
                manifest[rel_p.as_posix()] = file_sha256(dest)
                ordered_paths.append(dest)

            if tamper == "drop_first_file" and ordered_paths:
                ordered_paths[0].unlink()
            elif tamper == "tamper_first_file" and ordered_paths:
                ordered_paths[0].write_text("TAMPERED_CONTENT_DOES_NOT_MATCH_MANIFEST\n", encoding="utf-8")

            if tamper == "corrupt_archive":
                archive_path = work_dir / "custom_bundle.zip"
                archive_path.write_bytes(b"CORRUPT_ZIP_PAYLOAD")
            else:
                archive_path = Path(
                    shutil.make_archive(str(work_dir / "custom_bundle"), "zip", root_dir=str(stage))
                )

            health_cmd = (
                [sys.executable, "-c", "import sys; print('CUSTOM_HEALTH_FAIL', file=sys.stderr); sys.exit(4)"]
                if tamper == "fail_health_check"
                else None
            )
            rep = run_restore_proof(
                backup_path=archive_path,
                min_files=min_files,
                expected_manifest_hashes=manifest,
                health_cmd=health_cmd,
            )
        except ValueError as exc:
            return {"ok": False, "status_code": 400, "error": str(exc)}
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        rep_dict = rep.to_dict()
        with _HISTORY_LOCK:
            rows = _load_history(data_dir)
            rows.append(
                {"source_name": source_name, "backup_type": backup_type, "report": rep_dict}
            )
            rows = rows[-100:]
            _save_history(data_dir, rows)
        all_reports = [_to_report_obj(r["report"]) for r in rows]
        ui_payload = build_ui_payload(
            all_reports, source_name=source_name, backup_type=backup_type, is_demo=False
        )
        return {"ok": True, "report": rep_dict, "ui_payload": ui_payload}

    if action == "restoreproof_history_clear":
        with _HISTORY_LOCK:
            hp = _history_file(data_dir)
            if hp.exists():
                hp.unlink()
        ui_payload = build_ui_payload([], is_demo=False)
        return {"ok": True, "ui_payload": ui_payload}

    # 2) Full RealityCheck — RestoreProof Control Center actions
    store = _get_control_store(data_dir)
    actor = str(payload.get("actor") or "operator")

    if action == "rp_control_overview":
        policies = store.get_policies()
        targets = [
            {**t.to_dict(), "readiness": check_target_readiness(t, policies)}
            for t in store.list_targets()
        ]
        runs = [r.to_dict() for r in store.list_runs(limit=100)]
        backups = [b.to_dict() for b in store.list_backups()]
        workers = [w.to_dict() for w in store.list_workers()]
        audit = [e.to_dict() for e in store.list_audit(limit=50)]
        return {
            "ok": True,
            "monitor": get_system_monitor(store),
            "backups": backups,
            "targets": targets,
            "workers": workers,
            "policies": policies.to_dict(),
            "runs": runs,
            "audit": audit,
            "assistant_history": store.list_assistant_history(limit=25),
        }

    if action == "rp_control_create_backup":
        preset = str(payload.get("preset") or "").strip()
        name = str(payload.get("name") or "").strip()
        if preset:
            try:
                bkp = create_managed_backup_bundle(
                    store,
                    name=name or f"Backup ({preset})",
                    preset=preset,
                    actor=actor,
                )
            except ValueError as exc:
                return {"ok": False, "status_code": 400, "error": str(exc)}
        else:
            uri = str(payload.get("uri") or "").strip()
            fmt = str(payload.get("backup_format") or "archive_zip").strip()
            if fmt not in VALID_BACKUP_FORMATS:
                return {"ok": False, "status_code": 422, "error": f"Unsupported backup_format: {fmt}"}
            try:
                bkp = register_backup_source(
                    store,
                    name=name or "Backup Source",
                    backup_format=fmt,
                    uri=uri,
                    actor=actor,
                    allowed_root=data_dir,
                )
            except ValueError as exc:
                return {"ok": False, "status_code": 400, "error": str(exc)}
        return {"ok": True, "backup": bkp.to_dict()}

    if action == "rp_control_check_backup":
        bid = str(payload.get("backup_id") or "").strip()
        try:
            res = check_backup_integrity(store, bid, actor=actor)
            return {"ok": True, **res}
        except KeyError as exc:
            return {"ok": False, "status_code": 404, "error": str(exc)}

    if action == "rp_control_delete_backup":
        bid = str(payload.get("backup_id") or "").strip()
        ok = store.delete_backup(bid)
        if not ok:
            return {"ok": False, "status_code": 404, "error": f"Backup not found: {bid}"}
        record_audit(store, actor, "BACKUP_DELETED", bid, "DELETED", "Removed backup source")
        return {"ok": True}

    if action == "rp_control_create_target":
        iso = str(payload.get("isolation_mode") or "sqlite_sandbox").strip()
        if iso not in VALID_ISOLATION_MODES:
            return {"ok": False, "status_code": 422, "error": f"Unsupported isolation_mode: {iso}"}
        tgt = RestoreTarget(
            id=new_entity_id("tgt"),
            name=str(payload.get("name") or "Isolated Target").strip(),
            engine=str(payload.get("engine") or "sqlite").strip(),
            isolation_mode=iso,
            target_dbname=str(payload.get("target_dbname") or f"rp_verify_{new_entity_id('db')}").strip(),
            host=str(payload.get("host") or "127.0.0.1").strip(),
            port=int(payload.get("port") or 5432),
            user=str(payload.get("user") or "restoreproof_user").strip(),
            drop_after_verify=bool(payload.get("drop_after_verify", True)),
        )
        store.save_target(tgt)
        record_audit(store, actor, "TARGET_CREATED", tgt.id, "CREATED", tgt.name)
        return {
            "ok": True,
            "target": {**tgt.to_dict(), "readiness": check_target_readiness(tgt, store.get_policies())},
        }

    if action == "rp_control_delete_target":
        tid = str(payload.get("target_id") or "").strip()
        ok = store.delete_target(tid)
        if not ok:
            return {"ok": False, "status_code": 404, "error": f"Target not found: {tid}"}
        record_audit(store, actor, "TARGET_DELETED", tid, "DELETED", "Deleted restore target")
        return {"ok": True}

    if action == "rp_control_start_verification":
        bid = str(payload.get("backup_source_id") or "").strip()
        bkp = store.get_backup(bid) if bid else None
        if bkp is None:
            return {"ok": False, "status_code": 404, "error": "backup_source_id not found"}
        tid = str(payload.get("target_id") or "").strip()
        tgt = store.get_target(tid) if tid else None
        policies = store.get_policies()

        priority = str(payload.get("priority") or "normal").strip().lower()
        if priority not in VALID_PRIORITIES:
            priority = "normal"

        rid = new_run_id()
        target_dbname = (
            str(payload.get("target_dbname") or "").strip()
            or (tgt.target_dbname if tgt else f"rp_verify_{rid}")
        )
        isolation_mode = (
            str(payload.get("isolation_mode") or "").strip()
            or (
                tgt.isolation_mode
                if tgt
                else (
                    "sqlite_sandbox"
                    if bkp.backup_format == "sqlite_dump"
                    else ("archive_sandbox" if bkp.backup_format.startswith("archive_") else "isolated_db")
                )
            )
        )
        req_tables = payload.get("required_tables")
        if not isinstance(req_tables, list):
            req_tables = ["accounts"] if bkp.backup_format == "sqlite_dump" else []

        rec = RunRecord(
            run_id=rid,
            source_name=bkp.name,
            backup_format=bkp.backup_format,
            backup_uri=bkp.uri,
            target_dbname=target_dbname,
            min_total_rows=max(0, int(payload.get("min_total_rows", 1))),
            required_tables=[str(x) for x in req_tables],
            expected_sha256=(
                None
                if payload.get("skip_sha256")
                else (str(payload.get("expected_sha256") or bkp.baseline_sha256 or "").strip() or None)
            ),
            status="RUNNING",
            started_at=utc_now_iso(),
            isolation_mode=isolation_mode,
            drop_after_verify=bool(payload.get("drop_after_verify", policies.auto_cleanup_ephemeral)),
            priority=priority,
            worker_id=str(payload.get("worker_id") or "worker-local-01"),
            operator=actor,
            max_retries=int(payload.get("max_retries", policies.default_max_retries)),
            timeout_sec=float(payload.get("timeout_sec", policies.default_timeout_sec)),
            backup_source_id=bkp.id,
            target_id=tgt.id if tgt else None,
            steps=[StepRecord("file_and_sha256", "RUNNING", None, "Executing isolated verification")],
        )
        _BRIDGE_CANCEL_FLAGS[rid] = threading.Event()
        store.save(rec)
        record_audit(store, actor, "VERIFICATION_QUEUED", rid, "RUNNING", f"backup={bkp.id} target={target_dbname}")
        finished = execute_verification_run(
            rec,
            store=store,
            pg_host=tgt.host if tgt else "127.0.0.1",
            pg_port=tgt.port if tgt and tgt.port > 0 else 5432,
            pg_user=tgt.user if tgt else "restoreproof_user",
            cancel_flags=_BRIDGE_CANCEL_FLAGS,
        )
        _BRIDGE_CANCEL_FLAGS.pop(rid, None)
        return {
            "ok": True,
            "run": finished.to_dict(),
            "diagnosis": diagnose_run_failure(finished),
        }

    if action == "rp_control_cancel_run":
        rid = str(payload.get("run_id") or "").strip()
        try:
            rec = cancel_run(store, rid, actor=actor, cancel_flags=_BRIDGE_CANCEL_FLAGS)
            return {"ok": True, "run": rec.to_dict()}
        except KeyError as exc:
            return {"ok": False, "status_code": 404, "error": str(exc)}
        except ValueError as exc:
            return {"ok": False, "status_code": 409, "error": str(exc)}

    if action == "rp_control_retry_run":
        rid = str(payload.get("run_id") or "").strip()
        orig = store.get(rid)
        if orig is None:
            return {"ok": False, "status_code": 404, "error": f"Run not found: {rid}"}
        if orig.attempt > orig.max_retries and not bool(payload.get("force", False)):
            return {"ok": False, "status_code": 409, "error": "Retry limit reached"}
        new_id = new_run_id()
        rec = RunRecord(
            run_id=new_id,
            source_name=orig.source_name,
            backup_format=orig.backup_format,
            backup_uri=orig.backup_uri,
            target_dbname=orig.target_dbname,
            min_total_rows=orig.min_total_rows,
            required_tables=list(orig.required_tables),
            expected_sha256=orig.expected_sha256,
            status="RUNNING",
            started_at=utc_now_iso(),
            isolation_mode=orig.isolation_mode,
            drop_after_verify=orig.drop_after_verify,
            priority=orig.priority,
            worker_id=orig.worker_id,
            operator=actor,
            attempt=orig.attempt + 1,
            max_retries=orig.max_retries,
            parent_run_id=orig.run_id,
            timeout_sec=orig.timeout_sec,
            backup_source_id=orig.backup_source_id,
            target_id=orig.target_id,
            steps=[StepRecord("file_and_sha256", "RUNNING", None, f"Retry #{orig.attempt + 1} of {orig.run_id}")],
        )
        store.save(rec)
        record_audit(store, actor, "JOB_RETRIED", new_id, "STARTED", f"parent_run_id={orig.run_id}")
        finished = execute_verification_run(rec, store=store, cancel_flags=_BRIDGE_CANCEL_FLAGS)
        return {"ok": True, "run": finished.to_dict(), "diagnosis": diagnose_run_failure(finished)}

    if action == "rp_control_compare_runs":
        a_id = str(payload.get("run_a") or "").strip()
        b_id = str(payload.get("run_b") or "").strip()
        ra = store.get(a_id)
        rb = store.get(b_id)
        if ra is None or rb is None:
            return {"ok": False, "status_code": 404, "error": "One or both runs not found"}
        return {"ok": True, "comparison": compare_runs(ra, rb)}

    if action == "rp_control_update_policies":
        cur = store.get_policies()
        updated = SecurityPolicies(
            require_sha256_match=bool(payload.get("require_sha256_match", cur.require_sha256_match)),
            auto_cleanup_ephemeral=bool(payload.get("auto_cleanup_ephemeral", cur.auto_cleanup_ephemeral)),
            reserved_db_blocklist=list(payload.get("reserved_db_blocklist", cur.reserved_db_blocklist)),
            default_timeout_sec=float(payload.get("default_timeout_sec", cur.default_timeout_sec)),
            default_max_retries=int(payload.get("default_max_retries", cur.default_max_retries)),
            alert_on_fail=bool(payload.get("alert_on_fail", cur.alert_on_fail)),
            alert_on_blocked=bool(payload.get("alert_on_blocked", cur.alert_on_blocked)),
            require_approval_for_assistant_mutations=bool(
                payload.get(
                    "require_approval_for_assistant_mutations",
                    cur.require_approval_for_assistant_mutations,
                )
            ),
        )
        store.save_policies(updated)
        record_audit(store, actor, "POLICY_UPDATED", "policies", "UPDATED", "Updated security policies")
        return {"ok": True, "policies": updated.to_dict()}

    if action == "rp_control_save_worker":
        wnode = WorkerNode(
            id=str(payload.get("id") or new_entity_id("wrk")),
            name=str(payload.get("name") or "Verification Worker").strip(),
            endpoint=str(payload.get("endpoint") or "local://sandbox").strip(),
            isolation_modes=list(payload.get("isolation_modes") or ["sqlite_sandbox", "archive_sandbox"]),
            max_concurrent=max(1, int(payload.get("max_concurrent") or 2)),
            status=str(payload.get("status") or "ONLINE"),
            last_heartbeat=utc_now_iso(),
        )
        store.save_worker(wnode)
        record_audit(store, actor, "WORKER_SAVED", wnode.id, wnode.status, wnode.endpoint)
        return {"ok": True, "worker": wnode.to_dict()}

    if action == "rp_control_assistant_command":
        msg = str(payload.get("message") or "").strip()
        if not msg:
            return {"ok": False, "status_code": 422, "error": "message is required"}
        out = process_assistant_command(
            store=store,
            message=msg,
            actor=actor,
            confirm_execution=bool(payload.get("confirm_execution", False)),
            context_run_id=payload.get("context_run_id"),
            context_backup_id=payload.get("context_backup_id"),
            cancel_flags=_BRIDGE_CANCEL_FLAGS,
        )
        return {"ok": True, **out}

    return {"ok": False, "status_code": 400, "error": f"Unknown RestoreProof bridge action: {action}"}
