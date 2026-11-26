from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_restore_templates import build_postgres_isolated_commands  # noqa: E402
from engine import RestoreProofReport, file_sha256, run_restore_proof  # noqa: E402
from ui_adapter import write_ui_payload_from_reports  # noqa: E402


def _run_cmd(
    cmd: List[str], env: Dict[str, str] | None = None, timeout: float = 60.0
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def _docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker CLI not found in PATH"
    res = _run_cmd(["docker", "info"], timeout=10.0)
    if res.returncode != 0:
        return False, f"docker daemon unavailable: {res.stderr.strip() or res.stdout.strip()}"
    return True, "docker_ready"


def _wait_for_pg(container_name: str, db_user: str, db_name: str, wait_sec: int = 25) -> bool:
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        res = _run_cmd(
            ["docker", "exec", container_name, "pg_isready", "-U", db_user, "-d", db_name],
            timeout=5.0,
        )
        if res.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def _create_pg_custom_dump(
    container_name: str,
    db_user: str,
    db_password: str,
    source_db: str,
    host_dump_out: Path,
    rows: List[tuple[int, str, float]],
) -> None:
    values_sql = ", ".join(
        f"({int(rid)}, '{str(acct).replace(chr(39), chr(39)*2)}', {float(amt)})"
        for rid, acct, amt in rows
    )
    sql_setup = (
        "DROP TABLE IF EXISTS ledger_entries; "
        "CREATE TABLE ledger_entries (id INTEGER PRIMARY KEY, account TEXT NOT NULL, amount NUMERIC(12,2) NOT NULL); "
        + (f"INSERT INTO ledger_entries (id, account, amount) VALUES {values_sql};" if rows else "")
    )
    setup_res = _run_cmd(
        [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={db_password}",
            container_name,
            "psql",
            "-U",
            db_user,
            "-d",
            source_db,
            "-c",
            sql_setup,
        ],
        timeout=15.0,
    )
    if setup_res.returncode != 0:
        raise RuntimeError(f"Failed to seed source PG db: {setup_res.stderr.strip()}")

    container_dump_path = "/tmp/rp_source.dump"
    dump_res = _run_cmd(
        [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={db_password}",
            container_name,
            "pg_dump",
            "-Fc",
            "-U",
            db_user,
            "-d",
            source_db,
            "-f",
            container_dump_path,
        ],
        timeout=20.0,
    )
    if dump_res.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {dump_res.stderr.strip()}")

    cp_res = _run_cmd(
        ["docker", "cp", f"{container_name}:{container_dump_path}", str(host_dump_out)],
        timeout=15.0,
    )
    if cp_res.returncode != 0:
        raise RuntimeError(f"docker cp dump failed: {cp_res.stderr.strip()}")


def run_postgres_docker_restore_test(
    image: str = "postgres:16-alpine",
    host_port: int = 15432,
    db_user: str = "restoreproof_user",
    db_password: str = "rp_isolated_pass_2026",
    source_db: str = "rp_source_db",
    verify_db: str = "restoreproof_verify_db",
    min_total_rows: int = 3,
    out_dir: Path | None = None,
) -> Dict:
    ok_docker, docker_msg = _docker_available()
    if not ok_docker:
        blocked = {
            "status": "blocked_environment",
            "reason": docker_msg,
            "note": "No pass/fail score fabricated because Docker is not available in this runtime.",
        }
        print(json.dumps(blocked, indent=2, ensure_ascii=False))
        return blocked

    container_name = f"rp_pg_iso_{os.getpid()}_{int(time.time())}"
    work_dir = Path(tempfile.mkdtemp(prefix="rp_pg_docker_"))
    pg_env = os.environ.copy()
    pg_env["PGPASSWORD"] = db_password

    try:
        run_res = _run_cmd(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                container_name,
                "-e",
                f"POSTGRES_USER={db_user}",
                "-e",
                f"POSTGRES_PASSWORD={db_password}",
                "-e",
                f"POSTGRES_DB={source_db}",
                "-p",
                f"127.0.0.1:{host_port}:5432",
                image,
            ],
            timeout=30.0,
        )
        if run_res.returncode != 0:
            raise RuntimeError(f"Failed to start isolated PG container: {run_res.stderr.strip()}")

        if not _wait_for_pg(container_name, db_user, source_db):
            raise RuntimeError("Isolated PostgreSQL container did not become ready in time")

        _run_cmd(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={db_password}",
                container_name,
                "createdb",
                "-U",
                db_user,
                verify_db,
            ],
            timeout=10.0,
        )

        # Case 1: Full dump with 3 rows
        pkg_ok = work_dir / "pkg_ok"
        pkg_ok.mkdir()
        dump_ok = pkg_ok / "pg_backup.dump"
        _create_pg_custom_dump(
            container_name=container_name,
            db_user=db_user,
            db_password=db_password,
            source_db=source_db,
            host_dump_out=dump_ok,
            rows=[(1, "acct_a", 500.00), (2, "acct_b", 1250.50), (3, "acct_c", 75.25)],
        )
        manifest_ok = {"pg_backup.dump": file_sha256(dump_ok)}
        zip_ok = Path(shutil.make_archive(str(work_dir / "pg_bundle_ok"), "zip", root_dir=str(pkg_ok)))

        cmds_ok = build_postgres_isolated_commands(
            dump_filename="pg_backup.dump",
            target_dbname=verify_db,
            host="127.0.0.1",
            port=host_port,
            user=db_user,
            min_total_rows=min_total_rows,
        )
        report_ok: RestoreProofReport = run_restore_proof(
            backup_path=zip_ok,
            min_files=1,
            expected_manifest_hashes=manifest_ok,
            restore_cmd=cmds_ok.restore_cmd,
            health_cmd=cmds_ok.health_cmd,
            env=pg_env,
        )

        # Reset verify_db before Case 2
        _run_cmd(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={db_password}",
                container_name,
                "dropdb",
                "--if-exists",
                "-U",
                db_user,
                verify_db,
            ],
            timeout=10.0,
        )
        _run_cmd(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={db_password}",
                container_name,
                "createdb",
                "-U",
                db_user,
                verify_db,
            ],
            timeout=10.0,
        )

        # Case 2: Incomplete dump (only 1 row when min_total_rows=3 -> must fail closed)
        pkg_short = work_dir / "pkg_short"
        pkg_short.mkdir()
        dump_short = pkg_short / "pg_backup.dump"
        _create_pg_custom_dump(
            container_name=container_name,
            db_user=db_user,
            db_password=db_password,
            source_db=source_db,
            host_dump_out=dump_short,
            rows=[(1, "acct_a", 500.00)],
        )
        manifest_short = {"pg_backup.dump": file_sha256(dump_short)}
        zip_short = Path(
            shutil.make_archive(str(work_dir / "pg_bundle_short"), "zip", root_dir=str(pkg_short))
        )

        report_short: RestoreProofReport = run_restore_proof(
            backup_path=zip_short,
            min_files=1,
            expected_manifest_hashes=manifest_short,
            restore_cmd=cmds_ok.restore_cmd,
            health_cmd=cmds_ok.health_cmd,
            env=pg_env,
        )

        target_out_dir = out_dir or (ROOT / "artifacts")
        target_out_dir.mkdir(parents=True, exist_ok=True)
        ui_out = target_out_dir / "pg_docker_restoreproof_ui.json"
        write_ui_payload_from_reports(
            reports=[report_ok, report_short],
            out_path=ui_out,
            source_name=f"Isolated Docker PostgreSQL ({image})",
            backup_type="PostgreSQL Custom Dump (.dump)",
            is_demo=False,
        )

        summary = {
            "status": "executed",
            "container": container_name,
            "case_1_valid_pg_restore": {
                "overall_passed": report_ok.overall_passed,
                "verified_restorable": report_ok.verified_restorable,
                "completeness_ok": report_ok.completeness_ok,
                "health_check_ok": report_ok.health_check_ok,
                "health_stdout_tail": report_ok.metrics.get("health_stdout_tail"),
                "discrepancies": report_ok.discrepancies,
            },
            "case_2_incomplete_pg_restore": {
                "overall_passed": report_short.overall_passed,
                "verified_restorable": report_short.verified_restorable,
                "completeness_ok": report_short.completeness_ok,
                "health_check_ok": report_short.health_check_ok,
                "health_stderr_tail": report_short.metrics.get("health_stderr_tail"),
                "discrepancies": report_short.discrepancies,
            },
            "ui_payload_path": str(ui_out),
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary
    finally:
        _run_cmd(["docker", "rm", "-f", container_name], timeout=15.0)
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    run_postgres_docker_restore_test()
