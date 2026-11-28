#!/usr/bin/env python3
"""Verify integrity of all checkpoints in OUT_DIR by recalculating SHA-256 hashes."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_CORE_DIR = REPO_ROOT / "python_core"
for _path in (str(REPO_ROOT), str(PYTHON_CORE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from checkpoint_hash import (  # noqa: E402
    compute_file_sha256,
    read_checkpoint_sha256,
    sha256_sidecar_path,
)

DEFAULT_OUT_DIR = Path("/content/zyrquen-resume/checkpoints")
CHECKPOINT_SUFFIXES = (".json.gz", ".pt", ".pth", ".ckpt", ".safetensors", ".bin")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_STEP_RE = re.compile(r"(?:^|[_-])step(\d+)(?:\.|$)", re.IGNORECASE)
_LOG_LINE_RE = re.compile(
    r"\bSTEP\s+(\d+)\b[^\n]*?\bSHA256\s+([0-9a-fA-F]{64})\b",
    re.IGNORECASE,
)


@dataclass
class CheckpointVerificationResult:
    file: str
    status: str  # VERIFIED | MISMATCH | MISSING_EXPECTED | CONFLICT | MISSING_FILE | ERROR
    actual_sha256: str | None
    expected_sha256: str | None
    expected_sources: dict[str, str] = field(default_factory=dict)
    size_bytes: int | None = None
    step: int | None = None
    detail: str = ""


@dataclass
class DirectoryVerificationReport:
    out_dir: str
    ok: bool
    total_checked: int
    verified_count: int
    failed_count: int
    results: list[CheckpointVerificationResult] = field(default_factory=list)
    error: str = ""


def _extract_step(name: str) -> int | None:
    match = _STEP_RE.search(name)
    return int(match.group(1)) if match else None


def _is_checkpoint_file(path: Path, pattern: str | None = None) -> bool:
    if not path.is_file():
        return False
    name = path.name
    if (
        name.endswith(".sha256")
        or name.endswith(".tmp")
        or name.endswith(".approval.json")
        or name in ("manifest.json", "version_manifest.json")
    ):
        return False
    if pattern is not None:
        return path.match(pattern)
    return any(name.endswith(ext) for ext in CHECKPOINT_SUFFIXES)


def _normalize_digest(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not _SHA256_RE.match(cleaned):
        return None
    return cleaned.lower()


def _load_manifest_expected(out_dir: Path) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}

    manifest_path = out_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in data.get("checkpoints", []):
                if not isinstance(item, dict):
                    continue
                fname = item.get("file")
                sha = _normalize_digest(item.get("sha256"))
                if isinstance(fname, str) and fname and sha:
                    expected.setdefault(Path(fname).name, {})["manifest.json"] = sha
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    version_manifest_path = out_dir / "version_manifest.json"
    if version_manifest_path.is_file():
        try:
            data = json.loads(version_manifest_path.read_text(encoding="utf-8"))
            for item in data.get("versions", []):
                if not isinstance(item, dict):
                    continue
                fname = item.get("checkpoint_file")
                sha = _normalize_digest(item.get("checkpoint_sha256"))
                if isinstance(fname, str) and fname and sha:
                    expected.setdefault(Path(fname).name, {})["version_manifest.json"] = sha
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    return expected


def _load_expected_json(expected_json_path: Path) -> dict[str, str]:
    data = json.loads(expected_json_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for key, val in data.items():
            sha = _normalize_digest(val)
            if isinstance(key, str) and sha:
                out[Path(key).name] = sha
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            fname = item.get("file") or item.get("path") or item.get("checkpoint")
            sha = _normalize_digest(item.get("sha256"))
            if isinstance(fname, str) and sha:
                out[Path(fname).name] = sha
    else:
        raise ValueError("Expected JSON must be an object mapping filename->sha256 or a list of entries")
    return out


def _load_training_log_expected(log_path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = _LOG_LINE_RE.search(line)
        if match:
            step = int(match.group(1))
            sha = match.group(2).lower()
            out[step] = sha
    return out


def verify_checkpoint_directory(
    out_dir: str | Path,
    *,
    pattern: str | None = None,
    expected_json: str | Path | None = None,
    training_log: str | Path | None = None,
    allow_empty: bool = False,
    reject_symlinks: bool = True,
) -> DirectoryVerificationReport:
    """Recalculate SHA-256 hashes for all checkpoints in `out_dir` and compare against stored hashes."""
    root = Path(out_dir)
    if not root.exists() or not root.is_dir():
        return DirectoryVerificationReport(
            out_dir=str(root),
            ok=False,
            total_checked=0,
            verified_count=0,
            failed_count=0,
            error=f"Checkpoint directory does not exist: {root}",
        )

    manifest_expected = _load_manifest_expected(root)
    json_expected: dict[str, str] = {}
    if expected_json is not None:
        json_expected = _load_expected_json(Path(expected_json))
    log_expected: dict[int, str] = {}
    if training_log is not None:
        log_expected = _load_training_log_expected(Path(training_log))

    candidates = [
        p
        for p in root.iterdir()
        if _is_checkpoint_file(p, pattern=pattern)
    ]
    candidates.sort(key=lambda p: ((_extract_step(p.name) is None), _extract_step(p.name) or 0, p.name))

    results: list[CheckpointVerificationResult] = []
    seen_names: set[str] = set()

    for ckpt in candidates:
        seen_names.add(ckpt.name)
        step = _extract_step(ckpt.name)

        if reject_symlinks and ckpt.is_symlink():
            results.append(
                CheckpointVerificationResult(
                    file=ckpt.name,
                    status="ERROR",
                    actual_sha256=None,
                    expected_sha256=None,
                    step=step,
                    detail="Refusing symlinked checkpoint file",
                )
            )
            continue

        sources: dict[str, str] = {}
        sidecar = sha256_sidecar_path(ckpt)
        if sidecar.is_file():
            try:
                sources[sidecar.name] = read_checkpoint_sha256(ckpt, sidecar_path=sidecar)
            except (OSError, ValueError) as exc:
                results.append(
                    CheckpointVerificationResult(
                        file=ckpt.name,
                        status="ERROR",
                        actual_sha256=None,
                        expected_sha256=None,
                        step=step,
                        detail=f"Invalid sidecar {sidecar.name}: {exc}",
                    )
                )
                continue

        if ckpt.name in manifest_expected:
            sources.update(manifest_expected[ckpt.name])
        if ckpt.name in json_expected:
            sources["expected_json"] = json_expected[ckpt.name]
        if step is not None and step in log_expected:
            sources["training_log"] = log_expected[step]

        try:
            actual_sha = compute_file_sha256(ckpt)
            size_bytes = ckpt.stat().st_size
        except OSError as exc:
            results.append(
                CheckpointVerificationResult(
                    file=ckpt.name,
                    status="ERROR",
                    actual_sha256=None,
                    expected_sha256=None,
                    expected_sources=sources,
                    step=step,
                    detail=f"Failed to read checkpoint: {exc}",
                )
            )
            continue

        if not sources:
            results.append(
                CheckpointVerificationResult(
                    file=ckpt.name,
                    status="MISSING_EXPECTED",
                    actual_sha256=actual_sha,
                    expected_sha256=None,
                    expected_sources={},
                    size_bytes=size_bytes,
                    step=step,
                    detail="No expected SHA-256 found (.sha256 sidecar, manifest, or log)",
                )
            )
            continue

        distinct_expected = set(sources.values())
        if len(distinct_expected) > 1:
            results.append(
                CheckpointVerificationResult(
                    file=ckpt.name,
                    status="CONFLICT",
                    actual_sha256=actual_sha,
                    expected_sha256=None,
                    expected_sources=sources,
                    size_bytes=size_bytes,
                    step=step,
                    detail="Expected SHA-256 sources disagree",
                )
            )
            continue

        expected_sha = next(iter(distinct_expected))
        if hmac.compare_digest(actual_sha, expected_sha):
            results.append(
                CheckpointVerificationResult(
                    file=ckpt.name,
                    status="VERIFIED",
                    actual_sha256=actual_sha,
                    expected_sha256=expected_sha,
                    expected_sources=sources,
                    size_bytes=size_bytes,
                    step=step,
                    detail="SHA-256 match",
                )
            )
        else:
            results.append(
                CheckpointVerificationResult(
                    file=ckpt.name,
                    status="MISMATCH",
                    actual_sha256=actual_sha,
                    expected_sha256=expected_sha,
                    expected_sources=sources,
                    size_bytes=size_bytes,
                    step=step,
                    detail="Recalculated SHA-256 does not match expected hash",
                )
            )

    # Check for files referenced in manifests or expected_json that are missing on disk
    referenced_missing: dict[str, dict[str, str]] = {}
    for fname, srcs in manifest_expected.items():
        if fname not in seen_names and (pattern is None or Path(fname).match(pattern)):
            referenced_missing.setdefault(fname, {}).update(srcs)
    for fname, sha in json_expected.items():
        if fname not in seen_names and (pattern is None or Path(fname).match(pattern)):
            referenced_missing.setdefault(fname, {})["expected_json"] = sha

    for fname in sorted(referenced_missing):
        srcs = referenced_missing[fname]
        distinct = set(srcs.values())
        results.append(
            CheckpointVerificationResult(
                file=fname,
                status="MISSING_FILE",
                actual_sha256=None,
                expected_sha256=next(iter(distinct)) if len(distinct) == 1 else None,
                expected_sources=srcs,
                step=_extract_step(fname),
                detail="Referenced in stored hashes/manifest but missing from OUT_DIR",
            )
        )

    verified_count = sum(1 for r in results if r.status == "VERIFIED")
    failed_count = len(results) - verified_count

    if len(results) == 0 and not allow_empty:
        return DirectoryVerificationReport(
            out_dir=str(root),
            ok=False,
            total_checked=0,
            verified_count=0,
            failed_count=0,
            results=[],
            error=f"No checkpoint files found in {root}",
        )

    return DirectoryVerificationReport(
        out_dir=str(root),
        ok=(failed_count == 0),
        total_checked=len(results),
        verified_count=verified_count,
        failed_count=failed_count,
        results=results,
    )


def _format_human_report(report: DirectoryVerificationReport) -> str:
    lines = [
        f"Checkpoint Integrity Verification: {report.out_dir}",
        f"Checked: {report.total_checked} | Verified: {report.verified_count} | Failed: {report.failed_count}",
    ]
    if report.error:
        lines.append(f"ERROR: {report.error}")
    for item in report.results:
        sources = ", ".join(sorted(item.expected_sources)) or "none"
        sha_info = item.actual_sha256 or "-"
        lines.append(
            f"[{item.status}] {item.file} | actual={sha_info} | sources={sources}"
            + (f" | {item.detail}" if item.status != "VERIFIED" else "")
        )
    lines.append("OVERALL: PASS" if report.ok else "OVERALL: FAIL")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify integrity of all checkpoints in OUT_DIR by recalculating SHA-256 hashes.",
    )
    parser.add_argument(
        "out_dir_pos",
        nargs="?",
        type=Path,
        help=f"Checkpoint directory (defaults to $OUT_DIR or {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        dest="out_dir_flag",
        help="Checkpoint directory path (overrides positional argument)",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default=None,
        help="Optional filename glob filter (e.g. 'v2_teacher_transfer_run5000_step*.json.gz')",
    )
    parser.add_argument(
        "--expected-json",
        type=Path,
        default=None,
        help="Optional JSON file mapping checkpoint filenames to expected SHA-256 digests",
    )
    parser.add_argument(
        "--training-log",
        type=Path,
        default=None,
        help="Optional training output log containing 'STEP <n> ... SHA256 <hex>' lines",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Return exit code 0 if OUT_DIR contains no checkpoints",
    )
    parser.add_argument(
        "--allow-symlinks",
        action="store_true",
        help="Allow verifying symlinked checkpoint files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON verification report",
    )
    args = parser.parse_args(argv)

    env_dir = os.environ.get("OUT_DIR", "").strip()
    resolved_dir = (
        args.out_dir_flag
        or args.out_dir_pos
        or (Path(env_dir) if env_dir else DEFAULT_OUT_DIR)
    )

    try:
        report = verify_checkpoint_directory(
            resolved_dir,
            pattern=args.pattern,
            expected_json=args.expected_json,
            training_log=args.training_log,
            allow_empty=args.allow_empty,
            reject_symlinks=not args.allow_symlinks,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(_format_human_report(report))

    if report.error and report.total_checked == 0 and not args.allow_empty:
        return 2 if "does not exist" in report.error else 1
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
