from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import run_restore_proof  # noqa: E402


def _load_manifest_hashes(manifest_path: Optional[str]) -> Optional[Dict[str, str]]:
    if not manifest_path:
        return None
    target = Path(manifest_path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Manifest file not found: {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "files" in data and isinstance(data["files"], dict):
        return {str(k): str(v) for k, v in data["files"].items()}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    raise ValueError("Manifest JSON must be an object or contain a 'files' object.")


def _parse_cmd(cmd_str: Optional[str]) -> Optional[List[str]]:
    if not cmd_str or not cmd_str.strip():
        return None
    return shlex.split(cmd_str)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="restoreproof",
        description="RestoreProof CLI — independent backup restoration & completeness verifier.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify_p = sub.add_parser("verify", help="Verify a backup archive in an isolated temp dir.")
    verify_p.add_argument("--backup", required=True, help="Path to backup archive (.zip, .tar, .tar.gz)")
    verify_p.add_argument("--min-files", type=int, default=1, help="Minimum restored file count")
    verify_p.add_argument("--manifest", default="", help="Optional JSON file mapping relative path -> sha256")
    verify_p.add_argument("--restore-cmd", default="", help="Optional restore command run in isolated cwd")
    verify_p.add_argument("--health-cmd", default="", help="Optional health/readiness command run in isolated cwd")
    verify_p.add_argument("--timeout-sec", type=float, default=30.0, help="Command timeout in seconds")
    verify_p.add_argument("--out", default="", help="Optional output path for JSON evidence report")

    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            manifest_hashes = _load_manifest_hashes(args.manifest or None)
        except Exception as exc:
            print(json.dumps({"error": f"Invalid manifest: {exc}"}, ensure_ascii=False), file=sys.stderr)
            return 2

        report = run_restore_proof(
            backup_path=Path(args.backup),
            min_files=args.min_files,
            expected_manifest_hashes=manifest_hashes,
            restore_cmd=_parse_cmd(args.restore_cmd),
            health_cmd=_parse_cmd(args.health_cmd),
            timeout_sec=args.timeout_sec,
        )
        if args.out:
            report.write_json(Path(args.out))
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0 if report.overall_passed else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
