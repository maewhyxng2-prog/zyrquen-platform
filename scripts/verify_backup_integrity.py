#!/usr/bin/env python3
"""Verify a local backup file against a SHA-256 sidecar or manifest."""

import argparse
import hashlib
import os
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a backup file locally; this tool never connects to a database.",
    )
    parser.add_argument("backup", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="SHA-256 manifest with: <64_hex>  <backup_filename>",
    )
    args = parser.parse_args()

    backup = args.backup.resolve()
    if not backup.is_file():
        print("ERROR: backup file is missing", file=sys.stderr)
        return 2

    computed = sha256(backup)
    if args.manifest:
        manifest = args.manifest.resolve()
        if not manifest.is_file():
            print("ERROR: manifest is missing", file=sys.stderr)
            return 2
        matched = False
        for raw_line in manifest.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and backup.name in (" ".join(parts[1:]), parts[1]):
                matched = parts[0].lower() == computed
                if not matched:
                    print("FAIL: SHA-256 mismatch", file=sys.stderr)
                    return 1
        if not matched:
            print("FAIL: backup filename is not listed in manifest", file=sys.stderr)
            return 1
    else:
        sidecar = Path(str(backup) + ".sha256")
        if not sidecar.is_file():
            print("ERROR: sidecar is missing", file=sys.stderr)
            return 2
        expected = sidecar.read_text(encoding="ascii").strip().split()[0].lower()
        if expected != computed:
            print("FAIL: SHA-256 mismatch", file=sys.stderr)
            return 1

    print(f"PASS: {backup.name} SHA-256={computed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
