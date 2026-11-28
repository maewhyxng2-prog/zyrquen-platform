#!/usr/bin/env python3
"""Standalone utility script to verify SHA-256 integrity of all checkpoints in OUT_DIR."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_OUT_DIR = Path("/content/zyrquen-resume/checkpoints")
IGNORED_FILES = {"manifest.json", "version_manifest.json"}
IGNORED_SUFFIXES = (".sha256", ".tmp", ".approval.json")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_STEP_RE = re.compile(r"(?:^|[_-])step(\d+)(?:\.|$)", re.IGNORECASE)
_LOG_LINE_RE = re.compile(
    r"\bSTEP\s+(\d+)\b[^\n]*?\bSHA256\s+([0-9a-fA-F]{64})\b",
    re.IGNORECASE,
)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not _SHA256_RE.match(cleaned):
        return None
    return cleaned.lower()


def _extract_step(filename: str) -> int | None:
    match = _STEP_RE.search(filename)
    return int(match.group(1)) if match else None


def _is_checkpoint_candidate(
    path: Path,
    pattern: str | None = None,
    excluded_paths: set[Path] | None = None,
) -> bool:
    if not path.is_file():
        return False
    if excluded_paths and path.resolve() in excluded_paths:
        return False
    name = path.name
    if name in IGNORED_FILES or any(name.endswith(s) for s in IGNORED_SUFFIXES):
        return False
    if pattern is not None:
        return path.match(pattern)
    return True


def _load_sidecar_sha256(ckpt_path: Path) -> str | None:
    sidecar = Path(f"{ckpt_path}.sha256")
    if not sidecar.is_file():
        return None
    raw = sidecar.read_text(encoding="utf-8").strip()
    token = raw.split()[0] if raw else ""
    normalized = _normalize_sha256(token)
    if normalized is None:
        raise ValueError(f"Malformed SHA-256 in {sidecar.name}: {raw!r}")
    return normalized


def _load_manifest_hashes(out_dir: Path) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}

    manifest = out_dir / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for item in data.get("checkpoints", []):
                if isinstance(item, dict):
                    fname = item.get("file")
                    sha = _normalize_sha256(item.get("sha256"))
                    if isinstance(fname, str) and fname and sha:
                        expected.setdefault(Path(fname).name, {})["manifest.json"] = sha
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    version_manifest = out_dir / "version_manifest.json"
    if version_manifest.is_file():
        try:
            data = json.loads(version_manifest.read_text(encoding="utf-8"))
            for item in data.get("versions", []):
                if isinstance(item, dict):
                    fname = item.get("checkpoint_file")
                    sha = _normalize_sha256(item.get("checkpoint_sha256"))
                    if isinstance(fname, str) and fname and sha:
                        expected.setdefault(Path(fname).name, {})["version_manifest.json"] = sha
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    return expected


def _load_expected_json(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            sha = _normalize_sha256(v)
            if isinstance(k, str) and sha:
                out[Path(k).name] = sha
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                fname = item.get("file") or item.get("path") or item.get("checkpoint")
                sha = _normalize_sha256(item.get("sha256"))
                if isinstance(fname, str) and sha:
                    out[Path(fname).name] = sha
    else:
        raise ValueError("Expected JSON must be a dict or list")
    return out


def _load_log_hashes(log_path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = _LOG_LINE_RE.search(line)
        if match:
            out[int(match.group(1))] = match.group(2).lower()
    return out


def verify_checkpoints(
    out_dir: str | Path,
    *,
    pattern: str | None = None,
    log_file: str | Path | None = None,
    expected_json: str | Path | None = None,
    expected_overrides: dict[str, str] | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    root = Path(out_dir)
    if not root.exists() or not root.is_dir():
        return {
            "out_dir": str(root),
            "ok": False,
            "total": 0,
            "matched": 0,
            "failed": 0,
            "entries": [],
            "error": f"OUT_DIR does not exist: {root}",
        }

    manifest_map = _load_manifest_hashes(root)
    json_map = _load_expected_json(Path(expected_json)) if expected_json else {}
    log_map = _load_log_hashes(Path(log_file)) if log_file else {}
    cli_map = {
        Path(k).name: norm
        for k, v in (expected_overrides or {}).items()
        if (norm := _normalize_sha256(v)) is not None
    }

    excluded_paths: set[Path] = set()
    if expected_json is not None:
        excluded_paths.add(Path(expected_json).resolve())
    if log_file is not None:
        excluded_paths.add(Path(log_file).resolve())

    files = [
        p
        for p in root.iterdir()
        if _is_checkpoint_candidate(p, pattern=pattern, excluded_paths=excluded_paths)
    ]
    files.sort(key=lambda p: ((_extract_step(p.name) is None), _extract_step(p.name) or 0, p.name))

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for ckpt in files:
        seen.add(ckpt.name)
        step = _extract_step(ckpt.name)
        sources: dict[str, str] = {}

        try:
            sidecar_sha = _load_sidecar_sha256(ckpt)
            if sidecar_sha is not None:
                sources[f"{ckpt.name}.sha256"] = sidecar_sha
        except (OSError, ValueError) as exc:
            entries.append(
                {
                    "file": ckpt.name,
                    "step": step,
                    "status": "ERROR",
                    "actual_sha256": None,
                    "expected_sha256": None,
                    "sources": {},
                    "detail": str(exc),
                }
            )
            continue

        if ckpt.name in manifest_map:
            sources.update(manifest_map[ckpt.name])
        if ckpt.name in json_map:
            sources["expected_json"] = json_map[ckpt.name]
        if step is not None and step in log_map:
            sources["training_log"] = log_map[step]
        if ckpt.name in cli_map:
            sources["cli_expected"] = cli_map[ckpt.name]

        try:
            actual_sha = sha256_file(ckpt)
        except OSError as exc:
            entries.append(
                {
                    "file": ckpt.name,
                    "step": step,
                    "status": "ERROR",
                    "actual_sha256": None,
                    "expected_sha256": None,
                    "sources": sources,
                    "detail": str(exc),
                }
            )
            continue

        if not sources:
            entries.append(
                {
                    "file": ckpt.name,
                    "step": step,
                    "status": "MISSING_EXPECTED",
                    "actual_sha256": actual_sha,
                    "expected_sha256": None,
                    "sources": {},
                    "detail": "No expected SHA-256 recorded (.sha256 sidecar, manifest, or log)",
                }
            )
            continue

        distinct = set(sources.values())
        if len(distinct) > 1:
            entries.append(
                {
                    "file": ckpt.name,
                    "step": step,
                    "status": "CONFLICT",
                    "actual_sha256": actual_sha,
                    "expected_sha256": None,
                    "sources": sources,
                    "detail": "Conflicting expected SHA-256 hashes across sources",
                }
            )
            continue

        expected_sha = next(iter(distinct))
        matched = hmac.compare_digest(actual_sha, expected_sha)
        entries.append(
            {
                "file": ckpt.name,
                "step": step,
                "status": "MATCH" if matched else "MISMATCH",
                "actual_sha256": actual_sha,
                "expected_sha256": expected_sha,
                "sources": sources,
                "detail": "SHA-256 verified" if matched else "Actual SHA-256 does not match expected",
            }
        )

    for missing_name in sorted((set(manifest_map) | set(json_map) | set(cli_map)) - seen):
        if pattern is not None and not Path(missing_name).match(pattern):
            continue
        srcs: dict[str, str] = {}
        if missing_name in manifest_map:
            srcs.update(manifest_map[missing_name])
        if missing_name in json_map:
            srcs["expected_json"] = json_map[missing_name]
        if missing_name in cli_map:
            srcs["cli_expected"] = cli_map[missing_name]
        distinct = set(srcs.values())
        entries.append(
            {
                "file": missing_name,
                "step": _extract_step(missing_name),
                "status": "MISSING_FILE",
                "actual_sha256": None,
                "expected_sha256": next(iter(distinct)) if len(distinct) == 1 else None,
                "sources": srcs,
                "detail": "Expected checkpoint file missing from OUT_DIR",
            }
        )

    matched_count = sum(1 for e in entries if e["status"] == "MATCH")
    failed_count = len(entries) - matched_count
    if len(entries) == 0 and not allow_empty:
        return {
            "out_dir": str(root),
            "ok": False,
            "total": 0,
            "matched": 0,
            "failed": 0,
            "entries": [],
            "error": f"No checkpoint files found in {root}",
        }

    return {
        "out_dir": str(root),
        "ok": failed_count == 0,
        "total": len(entries),
        "matched": matched_count,
        "failed": failed_count,
        "entries": entries,
        "error": "",
    }


def print_report(report: dict[str, Any]) -> None:
    print("========== CHECKPOINT SHA256 VERIFICATION REPORT ==========")
    print(f"OUT_DIR : {report['out_dir']}")
    print(
        f"Summary : total={report['total']} matched={report['matched']} failed={report['failed']}"
    )
    if report.get("error"):
        print(f"Error   : {report['error']}")
    for entry in report["entries"]:
        src_list = ", ".join(sorted(entry["sources"])) or "none"
        print(
            f"[{entry['status']}] {entry['file']}\n"
            f"  actual  : {entry['actual_sha256'] or '-'}\n"
            f"  expected: {entry['expected_sha256'] or '-'} (sources: {src_list})"
        )
        if entry["status"] != "MATCH":
            print(f"  detail  : {entry['detail']}")
    print(f"STATUS  : {'ALL VERIFIED' if report['ok'] else 'VERIFICATION FAILED'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify SHA-256 hashes of all checkpoint files in OUT_DIR.",
    )
    parser.add_argument(
        "out_dir",
        nargs="?",
        type=Path,
        default=None,
        help=f"Directory containing checkpoints (defaults to $OUT_DIR or {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--out-dir",
        dest="out_dir_flag",
        type=Path,
        default=None,
        help="Directory containing checkpoints (overrides positional arg)",
    )
    parser.add_argument("--pattern", type=str, default=None, help="Optional filename glob filter")
    parser.add_argument("--log-file", type=Path, default=None, help="Training stdout log with STEP/SHA256 lines")
    parser.add_argument("--expected-json", type=Path, default=None, help="JSON map of filename -> expected sha256")
    parser.add_argument(
        "--expected",
        action="append",
        default=[],
        metavar="FILE=SHA256",
        help="Explicit expected hash override (can be repeated)",
    )
    parser.add_argument("--allow-empty", action="store_true", help="Exit 0 when OUT_DIR has no checkpoints")
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    args = parser.parse_args(argv)

    env_dir = os.environ.get("OUT_DIR", "").strip()
    target_dir = args.out_dir_flag or args.out_dir or (Path(env_dir) if env_dir else DEFAULT_OUT_DIR)

    overrides: dict[str, str] = {}
    for item in args.expected:
        if "=" not in item:
            print(f"Invalid --expected format (want FILE=SHA256): {item}", file=sys.stderr)
            return 2
        k, v = item.split("=", 1)
        overrides[k.strip()] = v.strip()

    try:
        report = verify_checkpoints(
            target_dir,
            pattern=args.pattern,
            log_file=args.log_file,
            expected_json=args.expected_json,
            expected_overrides=overrides,
            allow_empty=args.allow_empty,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    if report.get("error") and "does not exist" in report["error"]:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
