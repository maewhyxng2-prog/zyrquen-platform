from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from .isolated_worker import isolated_postgres_workspace, validate_isolated_dbname
    from .models import RunRecord, StepRecord, VALID_ISOLATION_MODES, utc_now_iso
except ImportError:
    from isolated_worker import isolated_postgres_workspace, validate_isolated_dbname
    from models import RunRecord, StepRecord, VALID_ISOLATION_MODES, utc_now_iso


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_proc(cmd: List[str], env: Dict[str, str], timeout: float = 60.0) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def execute_postgresql_verification(
    record: RunRecord,
    pg_host: str = "127.0.0.1",
    pg_port: int = 5432,
    pg_user: str = "postgres",
) -> RunRecord:
    """
    Fail-Closed verifier for PostgreSQL Custom Format (.dump).
    Never marks PASS unless artifact exists, SHA-256 matches (if provided),
    isolated DB/container provisions cleanly, pg_restore succeeds, and tables/rows meet thresholds.
    """
    t_start = time.perf_counter()
    steps: List[StepRecord] = []
    discrepancies: List[str] = []

    dump_path = Path(record.backup_uri)
    if record.backup_format != "postgresql_custom":
        record.status = "BLOCKED"
        record.discrepancies = [f"Unsupported backup_format: {record.backup_format}"]
        record.steps = [StepRecord("file_and_sha256", "BLOCKED", 0.0, record.discrepancies[0])]
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(record, None, None, None, None, None, [], record.required_tables, 0)
        return record

    if record.isolation_mode not in VALID_ISOLATION_MODES:
        record.status = "BLOCKED"
        record.discrepancies = [f"Unsupported isolation_mode: {record.isolation_mode}"]
        record.steps = [StepRecord("file_and_sha256", "BLOCKED", 0.0, record.discrepancies[0])]
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(record, None, None, None, None, None, [], record.required_tables, 0)
        return record

    db_err = validate_isolated_dbname(record.target_dbname)
    if db_err:
        record.status = "BLOCKED"
        record.discrepancies = [db_err]
        record.steps = [StepRecord("file_and_sha256", "BLOCKED", 0.0, db_err)]
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(record, None, None, None, None, None, [], record.required_tables, 0)
        return record

    # Step 1: File & SHA-256 check
    s1_t0 = time.perf_counter()
    if not dump_path.exists() or not dump_path.is_file():
        s1_dur = round(time.perf_counter() - s1_t0, 3)
        discrepancies.append(f"Backup artifact not found: {record.backup_uri}")
        record.status = "BLOCKED"
        record.steps = [
            StepRecord("file_and_sha256", "BLOCKED", s1_dur, discrepancies[-1]),
            StepRecord("isolated_pg_restore", "BLOCKED", None, "Blocked: backup artifact missing"),
            StepRecord("data_completeness", "BLOCKED", None, "Blocked: backup artifact missing"),
        ]
        record.discrepancies = discrepancies
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(record, 0, None, None, None, None, [], record.required_tables, 0)
        return record

    size_bytes = dump_path.stat().st_size
    actual_sha = compute_sha256(dump_path)
    sha_matched: Optional[bool] = None
    if record.expected_sha256:
        sha_matched = actual_sha.lower() == record.expected_sha256.strip().lower()
        if not sha_matched:
            discrepancies.append(
                f"SHA-256 mismatch: expected={record.expected_sha256.strip().lower()}, actual={actual_sha}"
            )
    s1_dur = round(time.perf_counter() - s1_t0, 3)

    if sha_matched is False:
        record.status = "FAIL"
        record.steps = [
            StepRecord("file_and_sha256", "FAIL", s1_dur, "SHA-256 ไม่ตรงกับค่าที่ระบุ"),
            StepRecord("isolated_pg_restore", "BLOCKED", None, "Skipped due to SHA-256 failure"),
            StepRecord("data_completeness", "BLOCKED", None, "Skipped due to SHA-256 failure"),
        ]
        record.discrepancies = discrepancies
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(
            record, size_bytes, actual_sha, sha_matched, None, None, [], record.required_tables, 0
        )
        return record

    steps.append(
        StepRecord(
            "file_and_sha256",
            "PASS",
            s1_dur,
            "SHA-256 ตรงกับค่าที่ระบุ" if sha_matched else "คำนวณ SHA-256 สำเร็จ (ไม่ได้ระบุค่าอ้างอิง)",
        )
    )

    # Check pg_restore / psql availability
    if shutil.which("pg_restore") is None or shutil.which("psql") is None:
        discrepancies.append("pg_restore or psql binary not available in worker environment")
        record.status = "BLOCKED"
        steps.append(StepRecord("isolated_pg_restore", "BLOCKED", 0.0, discrepancies[-1]))
        steps.append(StepRecord("data_completeness", "BLOCKED", None, "Blocked: PostgreSQL client tools missing"))
        record.steps = steps
        record.discrepancies = discrepancies
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(
            record, size_bytes, actual_sha, sha_matched, None, None, [], record.required_tables, 0
        )
        return record

    # Step 2 & Step 3 inside isolated PostgreSQL workspace
    s2_t0 = time.perf_counter()
    try:
        with isolated_postgres_workspace(
            mode=record.isolation_mode,
            target_dbname=record.target_dbname,
            pg_host=pg_host,
            pg_port=pg_port,
            pg_user=pg_user,
            drop_after_verify=record.drop_after_verify,
        ) as target:
            env = target.env()
            restore_cmd = [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "-h",
                target.host,
                "-p",
                str(target.port),
                "-U",
                target.user,
                "-d",
                target.dbname,
                str(dump_path),
            ]
            restore_rc, _, restore_err = _run_proc(restore_cmd, env=env, timeout=120.0)
            s2_dur = round(time.perf_counter() - s2_t0, 3)

            if restore_rc != 0:
                discrepancies.append(f"pg_restore exited with code {restore_rc}: {restore_err[-240:]}")
                steps.append(
                    StepRecord("isolated_pg_restore", "FAIL", s2_dur, f"pg_restore ล้มเหลว (exit code {restore_rc})")
                )
                steps.append(StepRecord("data_completeness", "BLOCKED", None, "Skipped: pg_restore did not succeed"))
                record.status = "FAIL"
                record.steps = steps
                record.discrepancies = discrepancies
                record.finished_at = utc_now_iso()
                record.duration_sec = round(time.perf_counter() - t_start, 3)
                record.report = _build_report_payload(
                    record, size_bytes, actual_sha, sha_matched, restore_rc, None, [], record.required_tables, 0
                )
                return record

            steps.append(
                StepRecord("isolated_pg_restore", "PASS", s2_dur, "pg_restore ลงฐานข้อมูลแยกสำเร็จ (exit code 0)")
            )

            # Step 3: Completeness check (tables & row counts)
            s3_t0 = time.perf_counter()
            sql_tables = (
                "SELECT table_schema || '.' || table_name "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY 1;"
            )
            t_rc, t_out, t_err = _run_proc(
                [
                    "psql",
                    "-h",
                    target.host,
                    "-p",
                    str(target.port),
                    "-U",
                    target.user,
                    "-d",
                    target.dbname,
                    "-t",
                    "-A",
                    "-c",
                    sql_tables,
                ],
                env=env,
                timeout=30.0,
            )
            tables_found = [line.strip() for line in t_out.splitlines() if line.strip()]

            total_rows = 0
            row_query_ok = t_rc == 0
            health_rc = t_rc
            if not row_query_ok:
                discrepancies.append(f"Failed to list restored tables: {t_err[-200:]}")
            else:
                for tbl in tables_found:
                    if "." in tbl:
                        schema_name, table_name = tbl.split(".", 1)
                        safe_schema = schema_name.replace('"', '""')
                        safe_table = table_name.replace('"', '""')
                        q = f'SELECT COUNT(*) FROM "{safe_schema}"."{safe_table}";'
                    else:
                        safe_table = tbl.replace('"', '""')
                        q = f'SELECT COUNT(*) FROM "{safe_table}";'
                    c_rc, c_out, c_err = _run_proc(
                        [
                            "psql",
                            "-h",
                            target.host,
                            "-p",
                            str(target.port),
                            "-U",
                            target.user,
                            "-d",
                            target.dbname,
                            "-t",
                            "-A",
                            "-c",
                            q,
                        ],
                        env=env,
                        timeout=30.0,
                    )
                    if c_rc != 0:
                        row_query_ok = False
                        health_rc = c_rc
                        discrepancies.append(f"Failed counting rows on {tbl}: {c_err[-200:]}")
                        break
                    total_rows += int((c_out.splitlines()[-1] if c_out else "0").strip() or "0")

            missing_tables = [t for t in record.required_tables if t not in tables_found]
            if missing_tables:
                discrepancies.append(f"Missing required tables: {missing_tables}")
            if row_query_ok and total_rows < record.min_total_rows:
                discrepancies.append(
                    f"Row count {total_rows} is below required minimum {record.min_total_rows}"
                )

            s3_dur = round(time.perf_counter() - s3_t0, 3)
            comp_passed = row_query_ok and (len(missing_tables) == 0) and (total_rows >= record.min_total_rows)
            steps.append(
                StepRecord(
                    "data_completeness",
                    "PASS" if comp_passed else "FAIL",
                    s3_dur,
                    f"พบ {len(tables_found)} ตาราง และจำนวนแถวรวม {total_rows} แถว"
                    if comp_passed
                    else "ความครบถ้วนของตารางหรือจำนวนแถวไม่ตรงตามเกณฑ์",
                )
            )

            record.steps = steps
            record.discrepancies = discrepancies
            record.status = "PASS" if comp_passed and not discrepancies else "FAIL"
            record.finished_at = utc_now_iso()
            record.duration_sec = round(time.perf_counter() - t_start, 3)
            record.report = _build_report_payload(
                record=record,
                size_bytes=size_bytes,
                actual_sha=actual_sha,
                sha_matched=sha_matched,
                restore_rc=restore_rc,
                health_rc=0 if row_query_ok else health_rc,
                tables_found=tables_found,
                missing_tables=missing_tables,
                total_rows=total_rows,
            )
            return record
    except Exception as exc:
        s2_dur = round(time.perf_counter() - s2_t0, 3)
        discrepancies.append(f"Isolated worker blocked: {exc}")
        steps.append(StepRecord("isolated_pg_restore", "BLOCKED", s2_dur, discrepancies[-1]))
        steps.append(StepRecord("data_completeness", "BLOCKED", None, "Blocked: isolated worker unavailable"))
        record.status = "BLOCKED"
        record.steps = steps
        record.discrepancies = discrepancies
        record.finished_at = utc_now_iso()
        record.duration_sec = round(time.perf_counter() - t_start, 3)
        record.report = _build_report_payload(
            record, size_bytes, actual_sha, sha_matched, None, None, [], record.required_tables, 0
        )
        return record


def _build_report_payload(
    record: RunRecord,
    size_bytes: Optional[int],
    actual_sha: Optional[str],
    sha_matched: Optional[bool],
    restore_rc: Optional[int],
    health_rc: Optional[int],
    tables_found: List[str],
    missing_tables: List[str],
    total_rows: int,
) -> Dict[str, Any]:
    evidence_complete = (record.status in ("PASS", "FAIL")) and (
        restore_rc is not None or sha_matched is False
    )
    return {
        "report_id": record.run_id,
        "run_id": record.run_id,
        "verdict": record.status,
        "evidence_complete": evidence_complete,
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
            "total_rows_observed": total_rows,
            "min_total_rows_required": record.min_total_rows,
        },
        "steps": [s.__dict__ for s in record.steps],
        "discrepancies": list(record.discrepancies),
    }
