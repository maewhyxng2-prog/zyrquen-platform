from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
from typing import Dict, Iterator, Optional

_SAFE_DB_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{1,62}$")
_RESERVED_DBS = frozenset({"postgres", "template0", "template1", "zyrquen", "production", "prod"})


def validate_isolated_dbname(dbname: str) -> Optional[str]:
    """Returns error message if dbname is unsafe or reserved for production."""
    if not _SAFE_DB_RE.match(dbname):
        return f"Unsafe or invalid target_dbname: {dbname}"
    if dbname.lower() in _RESERVED_DBS:
        return f"Refusing reserved/production database name: {dbname}"
    return None


@dataclass
class IsolatedPgTarget:
    host: str
    port: int
    user: str
    dbname: str
    mode: str
    container_name: Optional[str] = None
    password: Optional[str] = None

    def env(self) -> Dict[str, str]:
        env = os.environ.copy()
        if self.password:
            env["PGPASSWORD"] = self.password
        return env


def _pick_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def isolated_postgres_workspace(
    mode: str,
    target_dbname: str,
    pg_host: str = "127.0.0.1",
    pg_port: int = 5432,
    pg_user: str = "postgres",
    drop_after_verify: bool = True,
    docker_image: str = "postgres:16-alpine",
    startup_timeout_sec: float = 30.0,
) -> Iterator[IsolatedPgTarget]:
    """
    Provisions and tears down an isolated PostgreSQL verification database.
    - isolated_db: creates & drops an ephemeral database on the configured verification Postgres server.
    - docker_ephemeral: starts an isolated ephemeral Docker container bound to 127.0.0.1 and removes it on exit.
    """
    err = validate_isolated_dbname(target_dbname)
    if err:
        raise ValueError(err)

    if mode == "docker_ephemeral":
        if shutil.which("docker") is None:
            raise RuntimeError("Docker binary is not available for docker_ephemeral isolation")
        host_port = _pick_free_local_port()
        container_name = f"rp_iso_{secrets.token_hex(6)}"
        ephemeral_pw = secrets.token_hex(12)
        run_cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-p",
            f"127.0.0.1:{host_port}:5432",
            "-e",
            f"POSTGRES_USER={pg_user}",
            "-e",
            f"POSTGRES_PASSWORD={ephemeral_pw}",
            "-e",
            f"POSTGRES_DB={target_dbname}",
            docker_image,
        ]
        proc = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30.0, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start isolated Postgres container: {proc.stderr.strip()}")

        target = IsolatedPgTarget(
            host="127.0.0.1",
            port=host_port,
            user=pg_user,
            dbname=target_dbname,
            mode=mode,
            container_name=container_name,
            password=ephemeral_pw,
        )
        try:
            deadline = time.monotonic() + startup_timeout_sec
            ready = False
            while time.monotonic() < deadline:
                probe = subprocess.run(
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
                        "-c",
                        "SELECT 1;",
                    ],
                    env=target.env(),
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )
                if probe.returncode == 0:
                    ready = True
                    break
                time.sleep(0.5)
            if not ready:
                raise RuntimeError("Isolated Postgres container did not become ready before timeout")
            yield target
        finally:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )
        return

    if mode != "isolated_db":
        raise ValueError(f"Unsupported target_isolation mode: {mode}")

    target = IsolatedPgTarget(
        host=pg_host,
        port=pg_port,
        user=pg_user,
        dbname=target_dbname,
        mode=mode,
        password=os.environ.get("PGPASSWORD"),
    )
    env = target.env()
    create_sql = f'CREATE DATABASE "{target_dbname}";'
    drop_sql = f'DROP DATABASE IF EXISTS "{target_dbname}" WITH (FORCE);'

    # Ensure clean ephemeral DB before restore
    subprocess.run(
        ["psql", "-h", pg_host, "-p", str(pg_port), "-U", pg_user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", drop_sql],
        env=env,
        capture_output=True,
        text=True,
        timeout=30.0,
        check=False,
    )
    c_proc = subprocess.run(
        ["psql", "-h", pg_host, "-p", str(pg_port), "-U", pg_user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", create_sql],
        env=env,
        capture_output=True,
        text=True,
        timeout=30.0,
        check=False,
    )
    if c_proc.returncode != 0:
        raise RuntimeError(
            f"Failed to create isolated verification DB {target_dbname}: {c_proc.stderr.strip()}"
        )

    try:
        yield target
    finally:
        if drop_after_verify:
            subprocess.run(
                ["psql", "-h", pg_host, "-p", str(pg_port), "-U", pg_user, "-d", "postgres", "-c", drop_sql],
                env=env,
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False,
            )
