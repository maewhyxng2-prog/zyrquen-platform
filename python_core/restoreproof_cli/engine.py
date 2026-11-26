from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

_PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE_DIR))

from reality_check.probes import safe_unpack_archive  # noqa: E402


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RestoreProofReport:
    target: str
    verified_restorable: bool
    completeness_ok: bool
    health_check_ok: bool
    overall_passed: bool
    discrepancies: List[str]
    metrics: Dict[str, Any]
    checked_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def write_json(self, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return out_path


def run_restore_proof(
    backup_path: Path,
    min_files: int = 1,
    expected_manifest_hashes: Optional[Dict[str, str]] = None,
    restore_cmd: Optional[List[str]] = None,
    health_cmd: Optional[List[str]] = None,
    timeout_sec: float = 30.0,
) -> RestoreProofReport:
    """Tests backup restoration in an isolated temporary workspace without touching production."""
    checked_at = datetime.now(timezone.utc).isoformat()
    discrepancies: List[str] = []
    metrics: Dict[str, Any] = {
        "backup_exists": backup_path.exists(),
        "restored_file_count": 0,
        "min_files_required": min_files,
        "missing_files": [],
        "hash_mismatches": [],
        "restore_cmd_rc": None,
        "health_cmd_rc": None,
    }

    if not backup_path.exists() or not backup_path.is_file():
        discrepancies.append(f"Backup artifact not found: {backup_path}")
        return RestoreProofReport(
            target=str(backup_path),
            verified_restorable=False,
            completeness_ok=False,
            health_check_ok=False,
            overall_passed=False,
            discrepancies=discrepancies,
            metrics=metrics,
            checked_at=checked_at,
        )

    metrics["backup_sha256"] = file_sha256(backup_path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="restoreproof_iso_"))
    restored_ok = False
    completeness_ok = False
    health_ok = False

    try:
        try:
            safe_unpack_archive(backup_path, tmp_dir)
            restored_ok = True
        except Exception as exc:
            discrepancies.append(f"Archive unpack failed: {type(exc).__name__}: {exc}")

        if restored_ok and restore_cmd:
            try:
                proc_r = subprocess.run(
                    restore_cmd,
                    cwd=str(tmp_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    check=False,
                )
                metrics["restore_cmd_rc"] = proc_r.returncode
                metrics["restore_stdout_tail"] = proc_r.stdout.strip()[-200:]
                metrics["restore_stderr_tail"] = proc_r.stderr.strip()[-200:]
                if proc_r.returncode != 0:
                    restored_ok = False
                    discrepancies.append(f"Restore command exited with {proc_r.returncode}")
            except Exception as exc:
                restored_ok = False
                discrepancies.append(f"Restore command error: {type(exc).__name__}: {exc}")

        restored_hashes: Dict[str, str] = {}
        if restored_ok:
            for p in sorted(tmp_dir.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(tmp_dir).as_posix()
                    restored_hashes[rel] = file_sha256(p)

        file_count = len(restored_hashes)
        metrics["restored_file_count"] = file_count

        missing_files: List[str] = []
        hash_mismatches: List[str] = []

        if restored_ok and expected_manifest_hashes:
            for rel, exp_hash in expected_manifest_hashes.items():
                norm_rel = rel.lstrip("./")
                got_hash = restored_hashes.get(norm_rel)
                if got_hash is None:
                    missing_files.append(norm_rel)
                elif got_hash.lower() != exp_hash.lower():
                    hash_mismatches.append(norm_rel)

        metrics["missing_files"] = missing_files
        metrics["hash_mismatches"] = hash_mismatches

        completeness_ok = (
            restored_ok
            and (file_count >= min_files)
            and (len(missing_files) == 0)
            and (len(hash_mismatches) == 0)
        )
        if restored_ok and file_count < min_files:
            discrepancies.append(
                f"Restored file count {file_count} below minimum required {min_files}"
            )
        if missing_files:
            discrepancies.append(f"Missing files after restore: {missing_files}")
        if hash_mismatches:
            discrepancies.append(f"Hash mismatches after restore: {hash_mismatches}")

        if not health_cmd:
            health_ok = restored_ok
        else:
            if not restored_ok:
                health_ok = False
                discrepancies.append("Skipped health check because restore did not succeed")
            else:
                try:
                    proc_h = subprocess.run(
                        health_cmd,
                        cwd=str(tmp_dir),
                        capture_output=True,
                        text=True,
                        timeout=timeout_sec,
                        check=False,
                    )
                    metrics["health_cmd_rc"] = proc_h.returncode
                    metrics["health_stdout_tail"] = proc_h.stdout.strip()[-200:]
                    metrics["health_stderr_tail"] = proc_h.stderr.strip()[-200:]
                    health_ok = proc_h.returncode == 0
                    if not health_ok:
                        discrepancies.append(
                            f"Health check failed with exit code {proc_h.returncode}"
                        )
                except Exception as exc:
                    health_ok = False
                    discrepancies.append(f"Health check error: {type(exc).__name__}: {exc}")

        overall_passed = restored_ok and completeness_ok and health_ok
        return RestoreProofReport(
            target=str(backup_path),
            verified_restorable=restored_ok,
            completeness_ok=completeness_ok,
            health_check_ok=health_ok,
            overall_passed=overall_passed,
            discrepancies=discrepancies,
            metrics=metrics,
            checked_at=checked_at,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
