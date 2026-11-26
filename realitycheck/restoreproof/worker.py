from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from . import VERSION
from .manifest import VerificationError, sha256_file, verify_artifact
from .report import build_report, utc_now, write_report

_IMAGE = re.compile(r"^postgres@sha256:[0-9a-f]{64}$")


def _run(args: list[str], timeout: int, *, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError("COMMAND_TIMEOUT") from None
    except OSError:
        raise RuntimeError("CONTAINER_RUNTIME_UNAVAILABLE") from None
    if check and result.returncode != 0:
        # Never include command output: it may contain paths or secrets.
        raise RuntimeError("ISOLATED_RESTORE_COMMAND_FAILED")
    return result


def run_restore(backup: Path, manifest: Path, report_path: Path,
                postgres_image: str, timeout_seconds: int = 900) -> dict:
    run_id = str(uuid.uuid4())
    started = utc_now()
    started_clock = time.monotonic()
    checks: list[dict] = []
    reasons: list[str] = []
    artifact = None
    container_id = None
    cleanup = {"status": "NOT_RUN"}
    verdict = "BLOCKED"

    if not _IMAGE.fullmatch(postgres_image):
        reasons.append("POSTGRES_IMAGE_MUST_BE_PINNED_BY_SHA256_DIGEST")
        report = build_report(run_id, started, None, checks, verdict, reasons, cleanup, VERSION)
        write_report(report, report_path)
        return report
    if shutil.which("docker") is None:
        reasons.append("CONTAINER_RUNTIME_UNAVAILABLE")
        report = build_report(run_id, started, None, checks, verdict, reasons, cleanup, VERSION)
        write_report(report, report_path)
        return report

    try:
        artifact = verify_artifact(backup, manifest)
        checks.append({"name": "artifact_digest_and_format", "status": "PASS"})
    except VerificationError as exc:
        checks.append({"name": "artifact_digest_and_format", "status": "FAIL", "code": exc.code})
        reasons.append(exc.code)
        report = build_report(run_id, started, None, checks, "FAIL", reasons, cleanup, VERSION)
        write_report(report, report_path)
        return report

    # Container has no network, no host ports, bounded resources, and a read-only source mount.
    # Image is required to be pinned by immutable digest; no shell is invoked.
    password = os.urandom(32).hex()
    container_name = "restoreproof-" + run_id
    try:
        created = _run([
            "docker", "create", "--name", container_name,
            "--network", "none", "--memory", "1g", "--cpus", "1.0",
            "--pids-limit", "128", "--read-only",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=768m",
            "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,size=16m",
            "--mount", "type=bind,src=" + str(artifact["path"]) + ",dst=/backup.dump,readonly",
            "-e", "POSTGRES_PASSWORD=" + password,
            "-e", "POSTGRES_DB=restoreproof",
            postgres_image,
        ], 30)
        container_id = created.stdout.strip()
        if not container_id:
            raise RuntimeError("CONTAINER_CREATE_FAILED")
        _run(["docker", "start", container_id], 30)
        deadline = time.monotonic() + min(timeout_seconds, 900)
        ready = False
        while time.monotonic() < deadline:
            probe = _run(["docker", "exec", container_id, "pg_isready", "-U", "postgres"], 5, check=False)
            if probe.returncode == 0:
                ready = True
                break
            time.sleep(2)
        if not ready:
            raise RuntimeError("POSTGRES_READINESS_TIMEOUT")

        # The backup is bind-mounted read-only; no writable copy is created.
        _run(["docker", "exec", container_id, "pg_restore", "--exit-on-error",
              "--no-owner", "--no-privileges", "-U", "postgres",
              "-d", "restoreproof", "/backup.dump"],
             max(1, int(deadline - time.monotonic())))
        checks.append({"name": "isolated_postgres_restore", "status": "PASS"})

        query = "SELECT count(*) FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')"
        result = _run(["docker", "exec", container_id, "psql", "-U", "postgres",
                       "-d", "restoreproof", "-At", "-c", query], 30)
        schema_count = int(result.stdout.strip())
        if schema_count < 1:
            checks.append({"name": "restored_schema_presence", "status": "FAIL"})
            reasons.append("NO_USER_SCHEMAS_RESTORED")
            verdict = "FAIL"
        else:
            checks.append({"name": "restored_schema_presence", "status": "PASS",
                           "measured_user_schemas": schema_count})
            verdict = "PASS"
    except RuntimeError as exc:
        code = str(exc)
        checks.append({"name": "isolated_restore_execution", "status": "FAIL", "code": code})
        reasons.append(code)
        verdict = "FAIL" if code not in {"CONTAINER_RUNTIME_UNAVAILABLE"} else "BLOCKED"
    finally:
        if container_id:
            removed = _run(["docker", "rm", "-f", container_id], 30, check=False)
            cleanup = {"status": "PASS" if removed.returncode == 0 else "FAIL"}
            if removed.returncode != 0:
                reasons.append("CONTAINER_CLEANUP_FAILED")
                verdict = "BLOCKED"
        else:
            cleanup = {"status": "NOT_RUN"}
        # Re-hash the source; never allow a changed source to pass.
        try:
            after = sha256_file(artifact["path"]) if artifact else None
            if artifact and after != artifact["sha256"]:
                reasons.append("SOURCE_ARTIFACT_CHANGED")
                verdict = "FAIL"
            if artifact:
                artifact["sha256_after"] = after
        except OSError:
            reasons.append("SOURCE_ARTIFACT_RECHECK_FAILED")
            verdict = "BLOCKED"

    report = build_report(run_id, started, artifact, checks, verdict, reasons, cleanup, VERSION)
    report["duration_seconds"] = round(time.monotonic() - started_clock, 3)
    write_report(report, report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fail-closed isolated PostgreSQL restore verification.")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--postgres-image", required=True, help="Immutable postgres@sha256:<64 hex> image reference")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if args.timeout < 30 or args.timeout > 900:
        parser.error("--timeout must be between 30 and 900 seconds")
    report = run_restore(args.backup, args.manifest, args.report, args.postgres_image, args.timeout)
    print(json.dumps({"run_id": report["run_id"], "verdict": report["verdict"],
                      "report": str(args.report)}, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
