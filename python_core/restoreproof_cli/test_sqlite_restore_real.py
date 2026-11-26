from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_restore_templates import build_sqlite_dump_commands  # noqa: E402
from engine import RestoreProofReport, file_sha256, run_restore_proof  # noqa: E402
from ui_adapter import write_ui_payload_from_reports  # noqa: E402


def _create_sqlite_dump(dump_path: Path, rows: list[tuple[int, str, float]]) -> None:
    src_db = dump_path.parent / "_build_source.sqlite3"
    conn = sqlite3.connect(str(src_db))
    try:
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, balance REAL)")
        conn.executemany("INSERT INTO accounts (id, name, balance) VALUES (?, ?, ?)", rows)
        conn.commit()
        dump_sql = "\n".join(conn.iterdump()) + "\n"
        dump_path.write_text(dump_sql, encoding="utf-8")
    finally:
        conn.close()
        if src_db.exists():
            src_db.unlink()


def run_real_sqlite_restore_tests(out_dir: Path | None = None) -> dict:
    work_dir = Path(tempfile.mkdtemp(prefix="rp_sqlite_real_"))
    try:
        # Case 1: Valid SQLite dump with 3 rows (requires >= 3 rows and table 'accounts')
        pkg_ok_dir = work_dir / "pkg_ok"
        pkg_ok_dir.mkdir()
        dump_ok = pkg_ok_dir / "dump.sql"
        _create_sqlite_dump(
            dump_ok,
            rows=[(1, "alice", 1500.0), (2, "bob", 2300.5), (3, "charlie", 900.0)],
        )
        manifest_ok = {"dump.sql": file_sha256(dump_ok)}
        zip_ok = Path(
            shutil.make_archive(str(work_dir / "sqlite_backup_ok"), "zip", root_dir=str(pkg_ok_dir))
        )

        cmds_ok = build_sqlite_dump_commands(
            dump_filename="dump.sql",
            restored_db_filename="restored_check.sqlite3",
            min_total_rows=3,
            required_tables=["accounts"],
        )
        report_ok: RestoreProofReport = run_restore_proof(
            backup_path=zip_ok,
            min_files=1,
            expected_manifest_hashes=manifest_ok,
            restore_cmd=cmds_ok.restore_cmd,
            health_cmd=cmds_ok.health_cmd,
        )

        # Case 2: Incomplete SQLite dump (only 1 row, but min_total_rows=3 -> must fail closed)
        pkg_short_dir = work_dir / "pkg_short"
        pkg_short_dir.mkdir()
        dump_short = pkg_short_dir / "dump.sql"
        _create_sqlite_dump(dump_short, rows=[(1, "alice", 1500.0)])
        manifest_short = {"dump.sql": file_sha256(dump_short)}
        zip_short = Path(
            shutil.make_archive(
                str(work_dir / "sqlite_backup_short_rows"), "zip", root_dir=str(pkg_short_dir)
            )
        )

        cmds_short = build_sqlite_dump_commands(
            dump_filename="dump.sql",
            restored_db_filename="restored_check.sqlite3",
            min_total_rows=3,
            required_tables=["accounts"],
        )
        report_short: RestoreProofReport = run_restore_proof(
            backup_path=zip_short,
            min_files=1,
            expected_manifest_hashes=manifest_short,
            restore_cmd=cmds_short.restore_cmd,
            health_cmd=cmds_short.health_cmd,
        )

        target_out_dir = out_dir or (ROOT / "artifacts")
        target_out_dir.mkdir(parents=True, exist_ok=True)
        ui_out = target_out_dir / "sqlite_restoreproof_ui.json"
        write_ui_payload_from_reports(
            reports=[report_ok, report_short],
            out_path=ui_out,
            source_name="Isolated SQLite Dump Verification",
            backup_type="SQLite SQL Dump (.zip)",
            is_demo=False,
        )

        summary = {
            "case_1_valid_dump": {
                "overall_passed": report_ok.overall_passed,
                "verified_restorable": report_ok.verified_restorable,
                "completeness_ok": report_ok.completeness_ok,
                "health_check_ok": report_ok.health_check_ok,
                "health_stdout_tail": report_ok.metrics.get("health_stdout_tail"),
                "discrepancies": report_ok.discrepancies,
            },
            "case_2_insufficient_rows": {
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
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    run_real_sqlite_restore_tests()
