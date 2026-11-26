from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evidence_models import ClaimSpec, sha256_file
from runner import run_reality_check


def run_demo() -> None:
    base = Path(tempfile.mkdtemp(prefix="rc_demo_"))
    try:
        src = base / "source_data"
        dst = base / "synced_data"
        src.mkdir()
        dst.mkdir()

        f1 = src / "ledger.txt"
        f2 = src / "config.json"
        f1.write_text("tx=100\ntx=200\n", encoding="utf-8")
        f2.write_text('{"mode": "strict"}\n', encoding="utf-8")

        expected_hashes = {
            "ledger.txt": sha256_file(f1),
            "config.json": sha256_file(f2),
        }

        # Create real archive from source_data
        archive_base = base / "backup_bundle"
        archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=str(src)))

        # Simulate "Sync claimed success", but config.json in dst was altered/corrupted
        shutil.copy2(f1, dst / "ledger.txt")
        (dst / "config.json").write_text('{"mode": "disabled"}\n', encoding="utf-8")

        claims = [
            ClaimSpec(
                claim_id="claim_backup_restore",
                probe_type="restore",
                claimed_status="BACKUP_AND_RESTORE_OK",
                target=str(archive_path),
                params={
                    "archive_path": str(archive_path),
                    "expected_hashes": expected_hashes,
                },
            ),
            ClaimSpec(
                claim_id="claim_sync_match",
                probe_type="sync",
                claimed_status="SYNC_COMPLETE",
                target=f"{src} -> {dst}",
                params={
                    "source_dir": str(src),
                    "target_dir": str(dst),
                },
            ),
            ClaimSpec(
                claim_id="claim_runtime_check",
                probe_type="execution",
                claimed_status="SERVICE_HEALTHY",
                target="python_probe",
                params={
                    "command": [sys.executable, "-c", "print('REALITY_OK')"],
                    "expected_stdout_contains": "REALITY_OK",
                },
            ),
        ]

        report = run_reality_check(
            suite_name="reality_check_mvp_demo",
            claims=claims,
            report_out=base / "reports" / "reality_report.json",
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    run_demo()
