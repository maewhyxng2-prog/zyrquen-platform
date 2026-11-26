from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from reality_check import ClaimSpec, run_reality_check, sha256_file  # noqa: E402
from restoreproof_cli import run_restore_proof  # noqa: E402


class TestRealityCheckAndRestoreProof(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="rc_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _build_sample_backup(self) -> tuple[Path, Path, dict[str, str]]:
        src = self.tmp_root / "src_data"
        src.mkdir()
        ledger = src / "ledger.txt"
        config = src / "config.json"
        ledger.write_text("tx=100\ntx=200\n", encoding="utf-8")
        config.write_text('{"mode": "strict"}\n', encoding="utf-8")

        db_path = src / "app.sqlite"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance INTEGER)")
            conn.execute("INSERT INTO accounts (id, balance) VALUES (1, 500), (2, 750)")
            conn.commit()

        hashes = {
            "ledger.txt": sha256_file(ledger),
            "config.json": sha256_file(config),
            "app.sqlite": sha256_file(db_path),
        }
        archive = Path(
            shutil.make_archive(str(self.tmp_root / "valid_backup"), "zip", root_dir=str(src))
        )
        return src, archive, hashes

    def test_reality_check_detects_sync_contradiction_and_passes_valid_claims(self) -> None:
        src, archive, hashes = self._build_sample_backup()
        dst = self.tmp_root / "dst_data"
        dst.mkdir()
        shutil.copy2(src / "ledger.txt", dst / "ledger.txt")
        shutil.copy2(src / "app.sqlite", dst / "app.sqlite")
        # Silent corruption in synced target
        (dst / "config.json").write_text('{"mode": "disabled"}\n', encoding="utf-8")

        report = run_reality_check(
            suite_name="test_suite",
            claims=[
                ClaimSpec(
                    claim_id="restore_ok",
                    probe_type="restore",
                    claimed_status="OK",
                    target=str(archive),
                    params={"archive_path": str(archive), "expected_hashes": hashes},
                ),
                ClaimSpec(
                    claim_id="sync_corrupt",
                    probe_type="sync",
                    claimed_status="SYNC_COMPLETE",
                    target=f"{src}->{dst}",
                    params={"source_dir": str(src), "target_dir": str(dst)},
                ),
                ClaimSpec(
                    claim_id="exec_ok",
                    probe_type="execution",
                    claimed_status="HEALTHY",
                    target="python_probe",
                    params={
                        "command": [sys.executable, "-c", "print('REALITY_OK')"],
                        "expected_stdout_contains": "REALITY_OK",
                    },
                ),
            ],
            report_out=self.tmp_root / "out" / "reality_report.json",
        )
        self.assertEqual(report.total_claims, 3)
        self.assertEqual(report.verified_true_count, 2)
        self.assertEqual(report.contradiction_count, 1)
        self.assertFalse(report.all_verified_true)
        sync_ev = [e for e in report.evidence if e.claim_id == "sync_corrupt"][0]
        self.assertFalse(sync_ev.verified_real)
        self.assertIn("config.json", sync_ev.discrepancy)

    def test_restoreproof_happy_path_with_sqlite_health_check_and_cli(self) -> None:
        _, archive, hashes = self._build_sample_backup()
        manifest_path = self.tmp_root / "manifest.json"
        manifest_path.write_text(json.dumps({"files": hashes}), encoding="utf-8")
        out_report = self.tmp_root / "cli_report.json"

        health_script = (
            "import sqlite3; "
            "c = sqlite3.connect('app.sqlite'); "
            "rows = c.execute('SELECT SUM(balance) FROM accounts').fetchone()[0]; "
            "assert rows == 1250, f'unexpected sum {rows}'"
        )
        cli_path = _PYTHON_CORE / "restoreproof_cli" / "cli.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "verify",
                "--backup",
                str(archive),
                "--min-files",
                "3",
                "--manifest",
                str(manifest_path),
                "--health-cmd",
                f"{sys.executable} -c \"{health_script}\"",
                "--out",
                str(out_report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        payload = json.loads(out_report.read_text(encoding="utf-8"))
        self.assertTrue(payload["overall_passed"])
        self.assertTrue(payload["verified_restorable"])
        self.assertTrue(payload["completeness_ok"])
        self.assertTrue(payload["health_check_ok"])
        self.assertEqual(payload["metrics"]["restored_file_count"], 3)

    def test_failure_case_1_corrupt_or_unreadable_backup_archive(self) -> None:
        corrupt_zip = self.tmp_root / "corrupt_backup.zip"
        corrupt_zip.write_bytes(b"NOT_A_REAL_ZIP_ARCHIVE_000000")
        manifest_path = self.tmp_root / "manifest.json"
        manifest_path.write_text(json.dumps({"files": {"ledger.txt": "abc"}}), encoding="utf-8")

        cli_path = _PYTHON_CORE / "restoreproof_cli" / "cli.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "verify",
                "--backup",
                str(corrupt_zip),
                "--manifest",
                str(manifest_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["verified_restorable"])
        self.assertFalse(payload["completeness_ok"])
        self.assertFalse(payload["health_check_ok"])
        self.assertFalse(payload["overall_passed"])
        self.assertTrue(any("Archive unpack failed" in d for d in payload["discrepancies"]))

    def test_failure_case_2_missing_file_and_tampered_hash_in_backup(self) -> None:
        src, _, hashes = self._build_sample_backup()
        # Drop app.sqlite and tamper config.json before archiving
        (src / "app.sqlite").unlink()
        (src / "config.json").write_text('{"mode": "tampered"}\n', encoding="utf-8")
        broken_archive = Path(
            shutil.make_archive(str(self.tmp_root / "tampered_backup"), "zip", root_dir=str(src))
        )
        manifest_path = self.tmp_root / "manifest.json"
        manifest_path.write_text(json.dumps({"files": hashes}), encoding="utf-8")

        cli_path = _PYTHON_CORE / "restoreproof_cli" / "cli.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "verify",
                "--backup",
                str(broken_archive),
                "--min-files",
                "3",
                "--manifest",
                str(manifest_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["verified_restorable"])
        self.assertFalse(payload["completeness_ok"])
        self.assertFalse(payload["overall_passed"])
        self.assertEqual(payload["metrics"]["missing_files"], ["app.sqlite"])
        self.assertEqual(payload["metrics"]["hash_mismatches"], ["config.json"])

    def test_failure_case_3_health_cmd_or_restore_cmd_fails(self) -> None:
        _, archive, hashes = self._build_sample_backup()
        manifest_path = self.tmp_root / "manifest.json"
        manifest_path.write_text(json.dumps({"files": hashes}), encoding="utf-8")

        cli_path = _PYTHON_CORE / "restoreproof_cli" / "cli.py"
        # Files are valid and manifest matches, but restored service fails readiness probe
        proc = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "verify",
                "--backup",
                str(archive),
                "--min-files",
                "3",
                "--manifest",
                str(manifest_path),
                "--health-cmd",
                f"{sys.executable} -c \"import sys; print('DB_CORRUPT_TABLE', file=sys.stderr); sys.exit(3)\"",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["verified_restorable"])
        self.assertTrue(payload["completeness_ok"])
        self.assertFalse(payload["health_check_ok"])
        self.assertFalse(payload["overall_passed"])
        self.assertEqual(payload["metrics"]["health_cmd_rc"], 3)
        self.assertIn("DB_CORRUPT_TABLE", payload["metrics"]["health_stderr_tail"])

    def test_security_blocks_zip_slip_path_traversal(self) -> None:
        evil_zip = self.tmp_root / "evil_traversal.zip"
        outside_marker = self.tmp_root / "pwned_outside.txt"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../pwned_outside.txt", "malicious")

        report = run_restore_proof(backup_path=evil_zip, min_files=1)
        self.assertFalse(report.verified_restorable)
        self.assertFalse(report.overall_passed)
        self.assertFalse(outside_marker.exists())
        self.assertTrue(any("traversal" in d.lower() for d in report.discrepancies))


if __name__ == "__main__":
    unittest.main()
