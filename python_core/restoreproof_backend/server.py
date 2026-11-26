from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

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
        VALID_RUN_STATUSES,
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
        VALID_RUN_STATUSES,
        WorkerNode,
        utc_now_iso,
    )
    from ops_assistant import diagnose_run_failure, process_assistant_command
    from store import EvidenceStore


_CANCEL_FLAGS: Dict[str, threading.Event] = {}


def _new_run_id() -> str:
    return new_run_id()


def create_handler(store: EvidenceStore, pg_host: str, pg_port: int, pg_user: str):
    class RealityCheckHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send_json(
            self, code: int, payload: Any, extra_headers: Optional[Dict[str, str]] = None
        ) -> None:
            body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> Optional[Dict[str, Any]]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            if length > 2_097_152:
                raise ValueError("Payload exceeds 2MB limit")
            raw = self.rfile.read(length)
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be an object")
            return parsed

        def _run_worker(self, run_id: str) -> None:
            rec = store.get(run_id)
            if rec is None:
                return
            try:
                execute_verification_run(
                    record=rec,
                    store=store,
                    pg_host=pg_host,
                    pg_port=pg_port,
                    pg_user=pg_user,
                    cancel_flags=_CANCEL_FLAGS,
                )
            finally:
                _CANCEL_FLAGS.pop(run_id, None)

        def _start_verification_job(
            self,
            body: Dict[str, Any],
            actor: str = "api",
            parent_run_id: Optional[str] = None,
            attempt: int = 1,
        ) -> tuple[int, Dict[str, Any]]:
            backup_source_id = body.get("backup_source_id")
            backup_uri = str(body.get("backup_uri", "")).strip()
            backup_format = str(body.get("backup_format", "postgresql_custom")).strip() or "postgresql_custom"
            source_name = str(body.get("source_name", "PostgreSQL Backup Target")).strip()
            expected_sha = str(body["expected_sha256"]).strip() if body.get("expected_sha256") else None

            if backup_source_id and not backup_uri:
                bkp = store.get_backup(str(backup_source_id))
                if bkp is None:
                    return 404, {"error": "backup_not_found", "backup_source_id": backup_source_id}
                backup_uri = bkp.uri
                backup_format = bkp.backup_format
                source_name = source_name or bkp.name
                if expected_sha is None and bkp.baseline_sha256:
                    expected_sha = bkp.baseline_sha256

            if not backup_uri:
                return 422, {"error": "validation_error", "detail": "backup_uri or backup_source_id is required"}

            if backup_format not in VALID_BACKUP_FORMATS:
                return 422, {
                    "error": "validation_error",
                    "detail": f"backup_format must be one of {VALID_BACKUP_FORMATS}",
                }

            try:
                min_total_rows = int(body.get("min_total_rows", 1))
                if min_total_rows < 0:
                    raise ValueError("min_total_rows must be >= 0")
            except (TypeError, ValueError) as exc:
                return 422, {"error": "validation_error", "detail": str(exc)}

            raw_req_tables = body.get("required_tables") or []
            if not isinstance(raw_req_tables, list):
                return 422, {"error": "validation_error", "detail": "required_tables must be an array"}

            isolation = body.get("target_isolation") or {}
            if not isinstance(isolation, dict):
                return 422, {"error": "validation_error", "detail": "target_isolation must be an object"}

            policies = store.get_policies()
            priority = str(body.get("priority", "normal")).strip().lower() or "normal"
            if priority not in VALID_PRIORITIES:
                priority = "normal"

            run_id = _new_run_id()
            default_db = f"rp_verify_{run_id.replace('-', '_')}"
            target_dbname = str(isolation.get("target_dbname", default_db)).strip() or default_db
            default_iso = (
                "sqlite_sandbox"
                if backup_format == "sqlite_dump"
                else ("archive_sandbox" if backup_format.startswith("archive_") else "isolated_db")
            )
            isolation_mode = str(isolation.get("mode", default_iso)).strip() or default_iso
            drop_after_verify = bool(isolation.get("drop_after_verify", policies.auto_cleanup_ephemeral))
            created_at = utc_now_iso()

            rec = RunRecord(
                run_id=run_id,
                source_name=source_name,
                backup_format=backup_format,
                backup_uri=backup_uri,
                target_dbname=target_dbname,
                min_total_rows=min_total_rows,
                required_tables=[str(t) for t in raw_req_tables],
                expected_sha256=expected_sha,
                status="RUNNING",
                started_at=created_at,
                isolation_mode=isolation_mode,
                drop_after_verify=drop_after_verify,
                priority=priority,
                worker_id=str(body.get("worker_id", "worker-local-01")).strip() or "worker-local-01",
                operator=str(body.get("operator", actor)).strip() or actor,
                attempt=attempt,
                max_retries=int(body.get("max_retries", policies.default_max_retries)),
                parent_run_id=parent_run_id,
                timeout_sec=float(body.get("timeout_sec", policies.default_timeout_sec)),
                backup_source_id=str(backup_source_id) if backup_source_id else None,
                target_id=str(body["target_id"]) if body.get("target_id") else None,
                steps=[
                    StepRecord("file_and_sha256", "RUNNING", None, "Queued for isolated verification")
                ],
            )
            _CANCEL_FLAGS[run_id] = threading.Event()
            store.save(rec)
            record_audit(
                store,
                rec.operator,
                "VERIFICATION_QUEUED",
                run_id,
                "RUNNING",
                f"source={rec.source_name} format={rec.backup_format} priority={rec.priority}",
            )

            t = threading.Thread(target=self._run_worker, args=(run_id,), daemon=True)
            t.start()

            return 202, {
                "run_id": run_id,
                "status": "RUNNING",
                "source_name": rec.source_name,
                "backup_format": rec.backup_format,
                "priority": rec.priority,
                "worker_id": rec.worker_id,
                "created_at": created_at,
                "evidence_ref": {
                    "report_url": f"/v1/reports/{run_id}",
                    "export_url": f"/v1/reports/{run_id}/export",
                },
            }

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            if path == "/v1/health":
                worker_ready = (
                    shutil.which("pg_restore") is not None and shutil.which("psql") is not None
                )
                self._send_json(
                    200,
                    {
                        "service": "realitycheck-restoreproof-backend",
                        "version": "1.0.0",
                        "status": "ok",
                        "isolated_worker_ready": worker_ready,
                        "sqlite_sandbox_ready": True,
                        "checked_at": utc_now_iso(),
                    },
                )
                return

            if path == "/v1/system/monitor":
                self._send_json(200, get_system_monitor(store))
                return

            if path == "/v1/backups":
                items = [b.to_dict() for b in store.list_backups()]
                self._send_json(200, {"items": items, "total": len(items)})
                return

            if path == "/v1/targets":
                policies = store.get_policies()
                items = [
                    {**t.to_dict(), "readiness": check_target_readiness(t, policies)}
                    for t in store.list_targets()
                ]
                self._send_json(200, {"items": items, "total": len(items)})
                return

            if path.startswith("/v1/targets/") and path.endswith("/readiness"):
                tid = path[len("/v1/targets/") : -len("/readiness")].strip("/")
                t = store.get_target(tid)
                if t is None:
                    self._send_json(404, {"error": "target_not_found", "target_id": tid})
                    return
                self._send_json(200, check_target_readiness(t, store.get_policies()))
                return

            if path == "/v1/workers":
                items = [w.to_dict() for w in store.list_workers()]
                self._send_json(200, {"items": items, "total": len(items)})
                return

            if path == "/v1/policies":
                self._send_json(200, store.get_policies().to_dict())
                return

            if path == "/v1/audit":
                raw_limit = qs.get("limit", ["50"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = 50
                items = [e.to_dict() for e in store.list_audit(limit=limit)]
                self._send_json(200, {"items": items, "total": len(items)})
                return

            if path == "/v1/compare":
                a_id = qs.get("a", [""])[0].strip()
                b_id = qs.get("b", [""])[0].strip()
                ra = store.get(a_id)
                rb = store.get(b_id)
                if ra is None or rb is None:
                    self._send_json(404, {"error": "run_not_found", "a": a_id, "b": b_id})
                    return
                self._send_json(200, compare_runs(ra, rb))
                return

            if path == "/v1/runs":
                raw_limit = qs.get("limit", ["20"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    self._send_json(400, {"error": "invalid_limit", "detail": "limit must be an integer"})
                    return
                status_f = qs.get("status", [None])[0]
                if status_f is not None and status_f not in VALID_RUN_STATUSES:
                    self._send_json(
                        400,
                        {"error": "invalid_status", "detail": f"status must be one of {VALID_RUN_STATUSES}"},
                    )
                    return
                priority_f = qs.get("priority", [None])[0]
                runs = store.list_runs(status_filter=status_f, priority_filter=priority_f, limit=limit)
                items = [
                    {
                        "run_id": r.run_id,
                        "source_name": r.source_name,
                        "backup_format": r.backup_format,
                        "status": r.status,
                        "priority": r.priority,
                        "worker_id": r.worker_id,
                        "operator": r.operator,
                        "attempt": r.attempt,
                        "max_retries": r.max_retries,
                        "started_at": r.started_at,
                        "finished_at": r.finished_at,
                        "duration_sec": r.duration_sec,
                        "has_evidence": r.report is not None,
                    }
                    for r in runs
                ]
                self._send_json(200, {"items": items, "total": len(items)})
                return

            if path.startswith("/v1/runs/"):
                run_id = path.split("/v1/runs/", 1)[1]
                rec = store.get(run_id)
                if rec is None:
                    self._send_json(404, {"error": "run_not_found", "run_id": run_id})
                    return
                diag = diagnose_run_failure(rec) if rec.status != "RUNNING" else None
                self._send_json(
                    200,
                    {
                        "run_id": rec.run_id,
                        "source_name": rec.source_name,
                        "backup_format": rec.backup_format,
                        "isolation_mode": rec.isolation_mode,
                        "target_dbname": rec.target_dbname,
                        "status": rec.status,
                        "priority": rec.priority,
                        "worker_id": rec.worker_id,
                        "operator": rec.operator,
                        "attempt": rec.attempt,
                        "max_retries": rec.max_retries,
                        "parent_run_id": rec.parent_run_id,
                        "started_at": rec.started_at,
                        "finished_at": rec.finished_at,
                        "duration_sec": rec.duration_sec,
                        "steps": [s.__dict__ for s in rec.steps],
                        "discrepancies": rec.discrepancies,
                        "logs_tail": rec.logs_tail,
                        "diagnosis": diag,
                        "report_id": rec.run_id if rec.report else None,
                    },
                )
                return

            if path.startswith("/v1/reports/") and path.endswith("/export"):
                run_id = path[len("/v1/reports/") : -len("/export")].strip("/")
                rec = store.get(run_id)
                if rec is None:
                    self._send_json(404, {"error": "report_not_found", "run_id": run_id})
                    return
                if rec.status == "RUNNING" or rec.report is None:
                    self._send_json(
                        409,
                        {
                            "error": "evidence_not_ready",
                            "run_id": run_id,
                            "status": rec.status,
                            "message": "Evidence is not complete while run is still active.",
                        },
                    )
                    return
                self._send_json(
                    200,
                    rec.report,
                    extra_headers={
                        "Content-Disposition": f'attachment; filename="restoreproof_{run_id}.json"'
                    },
                )
                return

            if path.startswith("/v1/reports/"):
                run_id = path.split("/v1/reports/", 1)[1]
                rec = store.get(run_id)
                if rec is None:
                    self._send_json(404, {"error": "report_not_found", "run_id": run_id})
                    return
                if rec.status == "RUNNING" or rec.report is None:
                    self._send_json(
                        409,
                        {
                            "error": "evidence_not_ready",
                            "run_id": run_id,
                            "status": rec.status,
                            "message": "Evidence is not complete while run is still active.",
                        },
                    )
                    return
                self._send_json(200, rec.report)
                return

            self._send_json(404, {"error": "not_found", "path": path})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            try:
                body = self._read_json_body() or {}
            except Exception as exc:
                self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
                return

            if path == "/v1/verifications":
                code, resp = self._start_verification_job(body)
                self._send_json(code, resp)
                return

            if path.startswith("/v1/runs/") and path.endswith("/cancel"):
                run_id = path[len("/v1/runs/") : -len("/cancel")].strip("/")
                try:
                    rec = cancel_run(
                        store,
                        run_id,
                        actor=str(body.get("operator", "api")),
                        cancel_flags=_CANCEL_FLAGS,
                    )
                    self._send_json(200, {"ok": True, "run_id": rec.run_id, "status": rec.status})
                except KeyError:
                    self._send_json(404, {"error": "run_not_found", "run_id": run_id})
                except ValueError as exc:
                    self._send_json(409, {"error": "cannot_cancel", "detail": str(exc)})
                return

            if path.startswith("/v1/runs/") and path.endswith("/retry"):
                run_id = path[len("/v1/runs/") : -len("/retry")].strip("/")
                orig = store.get(run_id)
                if orig is None:
                    self._send_json(404, {"error": "run_not_found", "run_id": run_id})
                    return
                if orig.attempt > orig.max_retries and not bool(body.get("force", False)):
                    self._send_json(
                        409,
                        {
                            "error": "retry_limit_reached",
                            "detail": f"Run already at attempt {orig.attempt}/{orig.max_retries + 1}",
                        },
                    )
                    return
                retry_body = {
                    "source_name": orig.source_name,
                    "backup_format": orig.backup_format,
                    "backup_uri": orig.backup_uri,
                    "expected_sha256": orig.expected_sha256,
                    "min_total_rows": orig.min_total_rows,
                    "required_tables": orig.required_tables,
                    "priority": orig.priority,
                    "worker_id": orig.worker_id,
                    "max_retries": orig.max_retries,
                    "timeout_sec": orig.timeout_sec,
                    "backup_source_id": orig.backup_source_id,
                    "target_id": orig.target_id,
                    "target_isolation": {
                        "mode": orig.isolation_mode,
                        "target_dbname": orig.target_dbname,
                        "drop_after_verify": orig.drop_after_verify,
                    },
                }
                code, resp = self._start_verification_job(
                    retry_body,
                    actor=str(body.get("operator", "api")),
                    parent_run_id=orig.run_id,
                    attempt=orig.attempt + 1,
                )
                self._send_json(code, resp)
                return

            if path == "/v1/backups":
                try:
                    preset = body.get("preset")
                    if preset:
                        src = create_managed_backup_bundle(
                            store,
                            name=str(body.get("name", f"Backup ({preset})")),
                            preset=str(preset),
                            actor=str(body.get("actor", "api")),
                        )
                    else:
                        uri = str(body.get("uri", "")).strip()
                        if not uri:
                            self._send_json(422, {"error": "validation_error", "detail": "uri or preset is required"})
                            return
                        src = register_backup_source(
                            store,
                            name=str(body.get("name", "Backup Target")),
                            backup_format=str(body.get("backup_format", "archive_zip")),
                            uri=uri,
                            manifest_hashes=body.get("manifest_hashes") or {},
                            actor=str(body.get("actor", "api")),
                        )
                    self._send_json(201, {"ok": True, "backup": src.to_dict()})
                except ValueError as exc:
                    self._send_json(422, {"error": "validation_error", "detail": str(exc)})
                return

            if path.startswith("/v1/backups/") and path.endswith("/check"):
                bid = path[len("/v1/backups/") : -len("/check")].strip("/")
                try:
                    res = check_backup_integrity(store, bid, actor=str(body.get("actor", "api")))
                    self._send_json(200, res)
                except KeyError:
                    self._send_json(404, {"error": "backup_not_found", "backup_id": bid})
                return

            if path == "/v1/targets":
                iso = str(body.get("isolation_mode", "sqlite_sandbox")).strip()
                if iso not in VALID_ISOLATION_MODES:
                    self._send_json(422, {"error": "validation_error", "detail": f"isolation_mode must be in {VALID_ISOLATION_MODES}"})
                    return
                tgt = RestoreTarget(
                    id=new_entity_id("tgt"),
                    name=str(body.get("name", "Isolated Target")).strip() or "Isolated Target",
                    engine=str(body.get("engine", "sqlite")).strip() or "sqlite",
                    isolation_mode=iso,
                    target_dbname=str(body.get("target_dbname", f"rp_verify_{new_entity_id('db')}")).strip(),
                    host=str(body.get("host", "127.0.0.1")).strip(),
                    port=int(body.get("port", 5432)),
                    user=str(body.get("user", "restoreproof_user")).strip(),
                    drop_after_verify=bool(body.get("drop_after_verify", True)),
                )
                store.save_target(tgt)
                record_audit(store, str(body.get("actor", "api")), "TARGET_CREATED", tgt.id, "CREATED", tgt.name)
                self._send_json(201, {"ok": True, "target": tgt.to_dict()})
                return

            if path == "/v1/workers":
                wnode = WorkerNode(
                    id=str(body.get("id") or new_entity_id("wrk")),
                    name=str(body.get("name", "Verification Worker")).strip(),
                    endpoint=str(body.get("endpoint", "local://sandbox")).strip(),
                    isolation_modes=list(body.get("isolation_modes") or ["sqlite_sandbox", "archive_sandbox"]),
                    max_concurrent=int(body.get("max_concurrent", 2)),
                    status=str(body.get("status", "ONLINE")),
                    last_heartbeat=utc_now_iso(),
                )
                store.save_worker(wnode)
                record_audit(store, str(body.get("actor", "api")), "WORKER_SAVED", wnode.id, wnode.status, wnode.endpoint)
                self._send_json(201, {"ok": True, "worker": wnode.to_dict()})
                return

            if path == "/v1/assistant/command":
                msg = str(body.get("message", "")).strip()
                if not msg:
                    self._send_json(422, {"error": "validation_error", "detail": "message is required"})
                    return
                out = process_assistant_command(
                    store=store,
                    message=msg,
                    actor=str(body.get("actor", "operator")),
                    confirm_execution=bool(body.get("confirm_execution", False)),
                    context_run_id=body.get("context_run_id"),
                    context_backup_id=body.get("context_backup_id"),
                    cancel_flags=_CANCEL_FLAGS,
                    pg_host=pg_host,
                    pg_port=pg_port,
                    pg_user=pg_user,
                )
                self._send_json(200, out)
                return

            self._send_json(404, {"error": "not_found", "path": path})

        def do_PUT(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path != "/v1/policies":
                self._send_json(404, {"error": "not_found", "path": path})
                return
            try:
                body = self._read_json_body() or {}
            except Exception as exc:
                self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
                return
            cur = store.get_policies()
            updated = SecurityPolicies(
                require_sha256_match=bool(body.get("require_sha256_match", cur.require_sha256_match)),
                auto_cleanup_ephemeral=bool(body.get("auto_cleanup_ephemeral", cur.auto_cleanup_ephemeral)),
                reserved_db_blocklist=list(body.get("reserved_db_blocklist", cur.reserved_db_blocklist)),
                default_timeout_sec=float(body.get("default_timeout_sec", cur.default_timeout_sec)),
                default_max_retries=int(body.get("default_max_retries", cur.default_max_retries)),
                alert_on_fail=bool(body.get("alert_on_fail", cur.alert_on_fail)),
                alert_on_blocked=bool(body.get("alert_on_blocked", cur.alert_on_blocked)),
                require_approval_for_assistant_mutations=bool(
                    body.get(
                        "require_approval_for_assistant_mutations",
                        cur.require_approval_for_assistant_mutations,
                    )
                ),
            )
            store.save_policies(updated)
            record_audit(store, str(body.get("actor", "admin")), "POLICY_UPDATED", "policies", "UPDATED", "Updated security policies")
            self._send_json(200, {"ok": True, "policies": updated.to_dict()})

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path.startswith("/v1/backups/"):
                bid = path.split("/v1/backups/", 1)[1]
                ok = store.delete_backup(bid)
                if not ok:
                    self._send_json(404, {"error": "backup_not_found", "backup_id": bid})
                    return
                record_audit(store, "operator", "BACKUP_DELETED", bid, "DELETED", "Removed backup registration")
                self._send_json(200, {"ok": True})
                return
            if path.startswith("/v1/targets/"):
                tid = path.split("/v1/targets/", 1)[1]
                ok = store.delete_target(tid)
                if not ok:
                    self._send_json(404, {"error": "target_not_found", "target_id": tid})
                    return
                record_audit(store, "operator", "TARGET_DELETED", tid, "DELETED", "Removed restore target")
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not_found", "path": path})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return RealityCheckHandler


def create_server(
    host: str,
    port: int,
    data_dir: Path,
    pg_host: str = "127.0.0.1",
    pg_port: int = 5432,
    pg_user: str = "postgres",
) -> ThreadingHTTPServer:
    store = EvidenceStore(data_dir)
    handler = create_handler(store, pg_host=pg_host, pg_port=pg_port, pg_user=pg_user)
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="RealityCheck RestoreProof Verification Backend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", default="python_core/restoreproof_backend/data")
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-user", default="postgres")
    args = parser.parse_args()

    server = create_server(
        host=args.host,
        port=args.port,
        data_dir=Path(args.data_dir),
        pg_host=args.pg_host,
        pg_port=args.pg_port,
        pg_user=args.pg_user,
    )
    print(f"RestoreProof Backend listening on http://{args.host}:{args.port} (data={args.data_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
