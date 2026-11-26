from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import Dict, List
import zipfile

try:
    from .evidence_models import ClaimSpec, EvidenceItem, sha256_file
except ImportError:
    from evidence_models import ClaimSpec, EvidenceItem, sha256_file


def _validate_archive_target(dest_root: Path, member_name: str) -> Path:
    if not member_name or member_name.startswith("/") or member_name.startswith("\\"):
        raise ValueError(f"Unsafe absolute archive member path: {member_name!r}")
    root_resolved = dest_root.resolve()
    target_resolved = (root_resolved / member_name).resolve()
    if not target_resolved.is_relative_to(root_resolved):
        raise ValueError(f"Archive path traversal detected: {member_name!r}")
    return target_resolved


def safe_unpack_archive(archive_path: Path, dest_dir: Path) -> None:
    """Safely extracts .zip or .tar* archives while blocking path traversal and symlinks."""
    name_lower = archive_path.name.lower()
    if name_lower.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                # Reject symlinks encoded in unix mode bits (0120000)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError(f"Refusing symlink archive entry: {info.filename!r}")
                target = _validate_archive_target(dest_dir, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src_f, target.open("wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
        return

    if any(name_lower.endswith(ext) for ext in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        with tarfile.open(archive_path, "r:*") as tf:
            for member in tf.getmembers():
                if member.issym() or member.islnk():
                    raise ValueError(f"Refusing link archive entry: {member.name!r}")
                target = _validate_archive_target(dest_dir, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src_f = tf.extractfile(member)
                    if src_f is None:
                        raise ValueError(f"Unable to read tar member: {member.name!r}")
                    with src_f, target.open("wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
        return

    raise ValueError(f"Unsupported archive format: {archive_path.name}")


def _collect_file_hashes(root: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    if not root.exists():
        return hashes
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            hashes[rel] = sha256_file(p)
    return hashes


def verify_restore_claim(claim: ClaimSpec) -> EvidenceItem:
    """Actively extracts/restores an archive or backup folder into a temp dir and verifies hashes."""
    archive_path = Path(str(claim.params.get("archive_path", "")))
    expected_hashes: Dict[str, str] = dict(claim.params.get("expected_hashes", {}))

    if not archive_path.exists() or not archive_path.is_file():
        return EvidenceItem(
            claim_id=claim.claim_id,
            probe_type=claim.probe_type,
            claimed_status=claim.claimed_status,
            verified_real=False,
            discrepancy=f"Backup archive missing: {archive_path}",
            observed={"archive_exists": False},
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="rc_restore_"))
    try:
        try:
            safe_unpack_archive(archive_path, tmp_dir)
        except Exception as exc:
            return EvidenceItem(
                claim_id=claim.claim_id,
                probe_type=claim.probe_type,
                claimed_status=claim.claimed_status,
                verified_real=False,
                discrepancy=f"Restore extraction failed: {type(exc).__name__}: {exc}",
                observed={"archive_exists": True},
            )

        restored_hashes = _collect_file_hashes(tmp_dir)
        mismatches: List[str] = []
        missing: List[str] = []

        if expected_hashes:
            for rel, exp_h in expected_hashes.items():
                got_h = restored_hashes.get(rel)
                if got_h is None:
                    missing.append(rel)
                elif got_h != exp_h:
                    mismatches.append(rel)
            extra = sorted(set(restored_hashes.keys()) - set(expected_hashes.keys()))
        else:
            extra = []

        ok = (len(restored_hashes) > 0) and (not missing) and (not mismatches)
        reasons: List[str] = []
        if len(restored_hashes) == 0:
            reasons.append("restored directory contains no files")
        if missing:
            reasons.append(f"missing files after restore: {missing}")
        if mismatches:
            reasons.append(f"hash mismatch after restore: {mismatches}")

        return EvidenceItem(
            claim_id=claim.claim_id,
            probe_type=claim.probe_type,
            claimed_status=claim.claimed_status,
            verified_real=ok,
            discrepancy="; ".join(reasons) if reasons else "none",
            observed={
                "restored_file_count": len(restored_hashes),
                "missing_count": len(missing),
                "mismatch_count": len(mismatches),
                "extra_files": extra,
            },
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def verify_sync_claim(claim: ClaimSpec) -> EvidenceItem:
    """Compares actual file hashes between source and target directories."""
    src_dir = Path(str(claim.params.get("source_dir", "")))
    dst_dir = Path(str(claim.params.get("target_dir", "")))

    if not src_dir.exists() or not dst_dir.exists():
        return EvidenceItem(
            claim_id=claim.claim_id,
            probe_type=claim.probe_type,
            claimed_status=claim.claimed_status,
            verified_real=False,
            discrepancy=f"Missing source ({src_dir.exists()}) or target ({dst_dir.exists()}) directory",
            observed={"source_exists": src_dir.exists(), "target_exists": dst_dir.exists()},
        )

    src_map = _collect_file_hashes(src_dir)
    dst_map = _collect_file_hashes(dst_dir)

    missing_in_dst = sorted(set(src_map.keys()) - set(dst_map.keys()))
    extra_in_dst = sorted(set(dst_map.keys()) - set(src_map.keys()))
    content_diff = sorted(
        k for k in (set(src_map.keys()) & set(dst_map.keys())) if src_map[k] != dst_map[k]
    )

    ok = (not missing_in_dst) and (not extra_in_dst) and (not content_diff)
    diffs: List[str] = []
    if missing_in_dst:
        diffs.append(f"missing in target: {missing_in_dst}")
    if extra_in_dst:
        diffs.append(f"stale/extra in target: {extra_in_dst}")
    if content_diff:
        diffs.append(f"content hash differs: {content_diff}")

    return EvidenceItem(
        claim_id=claim.claim_id,
        probe_type=claim.probe_type,
        claimed_status=claim.claimed_status,
        verified_real=ok,
        discrepancy="; ".join(diffs) if diffs else "none",
        observed={
            "source_files": len(src_map),
            "target_files": len(dst_map),
            "missing_in_target": missing_in_dst,
            "extra_in_target": extra_in_dst,
            "content_diff": content_diff,
        },
    )


def verify_execution_claim(claim: ClaimSpec) -> EvidenceItem:
    """Runs an independent verification command and checks exit code + expected output/file state."""
    cmd: List[str] = list(claim.params.get("command", []))
    expected_stdout_substr: str = str(claim.params.get("expected_stdout_contains", ""))
    required_path_str: str = str(claim.params.get("must_exist_path", ""))
    timeout_sec: float = float(claim.params.get("timeout_sec", 10.0))

    if not cmd:
        return EvidenceItem(
            claim_id=claim.claim_id,
            probe_type=claim.probe_type,
            claimed_status=claim.claimed_status,
            verified_real=False,
            discrepancy="No verification command provided",
            observed={},
        )

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except Exception as exc:
        return EvidenceItem(
            claim_id=claim.claim_id,
            probe_type=claim.probe_type,
            claimed_status=claim.claimed_status,
            verified_real=False,
            discrepancy=f"Probe command failed: {type(exc).__name__}: {exc}",
            observed={},
        )

    stdout_ok = (not expected_stdout_substr) or (expected_stdout_substr in proc.stdout)
    path_ok = (not required_path_str) or Path(required_path_str).exists()
    ok = (proc.returncode == 0) and stdout_ok and path_ok

    reasons: List[str] = []
    if proc.returncode != 0:
        reasons.append(f"exit_code={proc.returncode}")
    if not stdout_ok:
        reasons.append(f"missing expected output {expected_stdout_substr!r}")
    if not path_ok:
        reasons.append(f"required path missing: {required_path_str}")

    return EvidenceItem(
        claim_id=claim.claim_id,
        probe_type=claim.probe_type,
        claimed_status=claim.claimed_status,
        verified_real=ok,
        discrepancy="; ".join(reasons) if reasons else "none",
        observed={
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout.strip()[-200:],
            "stderr_tail": proc.stderr.strip()[-200:],
            "must_exist_ok": path_ok,
        },
    )


def dispatch_probe(claim: ClaimSpec) -> EvidenceItem:
    if claim.probe_type == "restore":
        return verify_restore_claim(claim)
    if claim.probe_type == "sync":
        return verify_sync_claim(claim)
    if claim.probe_type == "execution":
        return verify_execution_claim(claim)
    return EvidenceItem(
        claim_id=claim.claim_id,
        probe_type=claim.probe_type,
        claimed_status=claim.claimed_status,
        verified_real=False,
        discrepancy=f"Unsupported probe_type: {claim.probe_type}",
        observed={},
    )
