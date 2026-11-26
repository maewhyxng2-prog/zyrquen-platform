from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Dict, List


@dataclass
class RestoreCommands:
    engine: str
    restore_cmd: List[str]
    health_cmd: List[str]
    notes: List[str]


def build_sqlite_dump_commands(
    dump_filename: str = "dump.sql",
    restored_db_filename: str = "restored_check.sqlite3",
    min_total_rows: int = 1,
    required_tables: List[str] | None = None,
) -> RestoreCommands:
    """
    Restores a SQLite SQL dump into an isolated SQLite file inside the temporary working directory,
    then verifies table existence and total row count.
    """
    req_tables = required_tables or []
    verify_script = (
        "import pathlib, sqlite3; "
        f"db_p = pathlib.Path({restored_db_filename!r}); "
        "assert db_p.exists(), 'restored sqlite db missing'; "
        "conn = sqlite3.connect(str(db_p)); "
        "cur = conn.cursor(); "
        "tables = [r[0] for r in cur.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\").fetchall()]; "
        "assert len(tables) > 0, 'no user tables restored'; "
        f"req = {req_tables!r}; "
        "missing_t = [t for t in req if t not in tables]; "
        "assert not missing_t, f'missing tables: {missing_t}'; "
        "total_rows = sum(cur.execute('SELECT COUNT(*) FROM \"' + t.replace('\"', '\"\"') + '\"').fetchone()[0] for t in tables); "
        f"assert total_rows >= {int(min_total_rows)}, f'row count {{total_rows}} < {int(min_total_rows)}'; "
        "conn.close(); "
        "print(f'SQLITE_RESTORE_OK tables={len(tables)} rows={total_rows}')"
    )
    return RestoreCommands(
        engine="sqlite",
        restore_cmd=[
            "python3",
            "-c",
            (
                "import pathlib, sqlite3; "
                f"sql_p = pathlib.Path({dump_filename!r}); "
                "assert sql_p.exists(), 'sql dump missing'; "
                f"conn = sqlite3.connect({restored_db_filename!r}); "
                "conn.executescript(sql_p.read_text(encoding='utf-8')); "
                "conn.commit(); conn.close()"
            ),
        ],
        health_cmd=["python3", "-c", verify_script],
        notes=[
            "Runs strictly inside RestoreProof temporary workspace; never modifies source/production DB.",
            "Fails closed if dump is missing, SQL fails, required tables are absent, or row count is below threshold.",
        ],
    )


def build_postgres_isolated_commands(
    dump_filename: str = "pg_backup.dump",
    target_dbname: str = "restoreproof_verify_db",
    host: str = "127.0.0.1",
    port: int = 5432,
    user: str = "postgres",
    min_total_rows: int = 1,
) -> RestoreCommands:
    """
    Produces pg_restore + psql verification commands targeting an isolated verification database name.
    Ensure target_dbname is a dedicated scratch DB (never production) and PGPASSWORD is supplied via env.
    """
    psql_check_sql = (
        "SELECT COALESCE(SUM(n_live_tup), 0) AS total_rows FROM pg_stat_user_tables;"
    )
    health_py = (
        "import os, subprocess, sys; "
        "env = os.environ.copy(); "
        f"cmd = ['psql', '-h', {host!r}, '-p', {str(port)!r}, '-U', {user!r}, '-d', {target_dbname!r}, '-t', '-A', '-c', {psql_check_sql!r}]; "
        "res = subprocess.run(cmd, env=env, capture_output=True, text=True); "
        "assert res.returncode == 0, f'psql failed: {res.stderr.strip()}'; "
        "rows = int((res.stdout.strip() or '0').splitlines()[-1]); "
        f"assert rows >= {int(min_total_rows)}, f'restored rows {{rows}} < {int(min_total_rows)}'; "
        f"print(f'PG_RESTORE_OK db={target_dbname!r} rows={{rows}}')"
    )
    return RestoreCommands(
        engine="postgresql",
        restore_cmd=[
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            target_dbname,
            dump_filename,
        ],
        health_cmd=["python3", "-c", health_py],
        notes=[
            "Uses an isolated verification database name; point to an isolated test/container instance only.",
            "Verifies both pg_restore exit status and live tuple count inside the restored database.",
        ],
    )


def format_cli_flags(cmds: RestoreCommands) -> Dict[str, str]:
    return {
        "restore_cmd_arg": shlex.join(cmds.restore_cmd),
        "health_cmd_arg": shlex.join(cmds.health_cmd),
    }
