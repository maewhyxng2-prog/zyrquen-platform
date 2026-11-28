"""Unit tests for tools/verify_checkpoint_dir.py."""

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON_CORE_DIR = REPO_ROOT / "python_core"
for _path in (str(REPO_ROOT), str(PYTHON_CORE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from checkpoint_hash import save_checkpoint_sha256  # noqa: E402
from tools.verify_checkpoint_dir import main, verify_checkpoint_directory  # noqa: E402


class TestVerifyCheckpointDir(unittest.TestCase):
    def test_verifies_all_sidecars_and_rejects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            for step in (5025, 5050, 5075):
                ckpt = out_dir / f"v2_teacher_transfer_run5000_step{step}.json.gz"
                ckpt.write_bytes(f"checkpoint-data-{step}".encode("utf-8"))
                save_checkpoint_sha256(ckpt)

            report = verify_checkpoint_directory(out_dir)
            self.assertTrue(report.ok)
            self.assertEqual(report.total_checked, 3)
            self.assertEqual(report.verified_count, 3)
            self.assertEqual(report.failed_count, 0)
            self.assertEqual(
                [r.step for r in report.results],
                [5025, 5050, 5075],
            )

            # Tamper one checkpoint
            bad = out_dir / "v2_teacher_transfer_run5000_step5050.json.gz"
            bad.write_bytes(b"corrupted-bytes")

            bad_report = verify_checkpoint_directory(out_dir)
            self.assertFalse(bad_report.ok)
            self.assertEqual(bad_report.verified_count, 2)
            self.assertEqual(bad_report.failed_count, 1)
            by_file = {r.file: r for r in bad_report.results}
            self.assertEqual(by_file[bad.name].status, "MISMATCH")

    def test_verifies_against_training_log_and_detects_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            c1 = out_dir / "v2_teacher_transfer_run5000_step5025.json.gz"
            c2 = out_dir / "v2_teacher_transfer_run5000_step5050.json.gz"
            c1.write_bytes(b"step-5025")
            c2.write_bytes(b"step-5050")
            sha1 = hashlib.sha256(b"step-5025").hexdigest()
            sha2 = hashlib.sha256(b"step-5050").hexdigest()

            log_file = out_dir / "colab_output.log"
            log_file.write_text(
                f"STEP 5025 | LOSS 2.1464 | SHA256 {sha1}\n"
                f"STEP 5050 | LOSS 2.0835 | SHA256 {sha2}\n",
                encoding="utf-8",
            )

            report = verify_checkpoint_directory(out_dir, training_log=log_file)
            self.assertTrue(report.ok)
            self.assertEqual(report.verified_count, 2)

            # Add conflicting sidecar hash for step 5050
            (out_dir / f"{c2.name}.sha256").write_text("0" * 64, encoding="utf-8")
            conflict_report = verify_checkpoint_directory(out_dir, training_log=log_file)
            self.assertFalse(conflict_report.ok)
            by_file = {r.file: r for r in conflict_report.results}
            self.assertEqual(by_file[c2.name].status, "CONFLICT")

    def test_missing_expected_hash_and_missing_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            ckpt = out_dir / "ckpt_00000010.pt"
            ckpt.write_bytes(b"pt-bytes")

            report = verify_checkpoint_directory(out_dir)
            self.assertFalse(report.ok)
            self.assertEqual(report.results[0].status, "MISSING_EXPECTED")

            # Now write manifest referencing a missing file too
            (out_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "zyrquen.checkpoint-manifest.v1",
                        "checkpoints": [
                            {
                                "step": 10,
                                "file": "ckpt_00000010.pt",
                                "sha256": hashlib.sha256(b"pt-bytes").hexdigest(),
                            },
                            {
                                "step": 20,
                                "file": "ckpt_00000020.pt",
                                "sha256": "a" * 64,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest_report = verify_checkpoint_directory(out_dir)
            self.assertFalse(manifest_report.ok)
            by_file = {r.file: r for r in manifest_report.results}
            self.assertEqual(by_file["ckpt_00000010.pt"].status, "VERIFIED")
            self.assertEqual(by_file["ckpt_00000020.pt"].status, "MISSING_FILE")

    def test_cli_json_and_pattern_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            target = out_dir / "v2_teacher_transfer_run5000_step5200.json.gz"
            other = out_dir / "unrelated_ckpt.json.gz"
            target.write_bytes(b"target-5200")
            other.write_bytes(b"no-sidecar")
            save_checkpoint_sha256(target)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--out-dir",
                        str(out_dir),
                        "--pattern",
                        "v2_teacher_transfer_run5000_step*.json.gz",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["total_checked"], 1)
            self.assertEqual(payload["results"][0]["file"], target.name)


if __name__ == "__main__":
    unittest.main()
