"""Unit tests for standalone verify_checkpoints.py and trainer .sha256 sidecar generation."""

import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON_CORE_DIR = REPO_ROOT / "python_core"
for _path in (str(REPO_ROOT), str(PYTHON_CORE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import verify_checkpoints  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
)
from v2.zyrquen_v2_trainer import ByteTokenizer  # noqa: E402


class TestStandaloneVerifyCheckpoints(unittest.TestCase):
    def test_trainer_save_checkpoint_and_verify_checkpoints_report(self) -> None:
        tok = ByteTokenizer()
        cfg = PureZyrquenV2Config(
            vocab_size=tok.vocab_size,
            d_model=8,
            n_heads=2,
            n_layers=1,
            d_ff=16,
            base_seq_len=16,
            max_seq_len=32,
        )
        trainer = PureContinualTrainerV2(PureNativeTransformerLMV2(cfg), tok)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            baseline = out_dir / "v2_teacher_transfer_step5000.json.gz"
            trainer.global_step = 5000
            _, base_sha = trainer.save_checkpoint(baseline)
            self.assertTrue(Path(f"{baseline}.sha256").is_file())

            trainer.global_step = 5025
            c1, sha1 = trainer.save_checkpoint(
                out_dir / "v2_teacher_transfer_run5000_step5025.json.gz"
            )
            self.assertTrue(Path(f"{c1}.sha256").is_file())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = verify_checkpoints.main(
                    [
                        "--out-dir",
                        str(out_dir),
                        "--expected",
                        f"{baseline.name}={base_sha}",
                    ]
                )
            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("ALL VERIFIED", output)
            self.assertIn("[MATCH]", output)
            self.assertIn(sha1, output)

            # Tamper c1 -> must exit 1 and report MISMATCH
            c1.write_bytes(b"tampered-checkpoint")
            stdout_bad = io.StringIO()
            with contextlib.redirect_stdout(stdout_bad):
                bad_code = verify_checkpoints.main(["--out-dir", str(out_dir)])
            self.assertEqual(bad_code, 1)
            self.assertIn("[MISMATCH]", stdout_bad.getvalue())

    def test_verify_against_training_log_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            ckpt = out_dir / "v2_teacher_transfer_run5000_step5025.json.gz"
            ckpt.write_bytes(b"step-5025-content")
            expected = hashlib.sha256(b"step-5025-content").hexdigest()
            log_file = out_dir / "train.log"
            log_file.write_text(
                f"STEP 5025 | LOSS 2.1464 | SHA256 {expected}\n",
                encoding="utf-8",
            )

            report = verify_checkpoints.verify_checkpoints(out_dir, log_file=log_file)
            self.assertTrue(report["ok"])
            self.assertEqual(report["matched"], 1)
            self.assertEqual(report["entries"][0]["status"], "MATCH")


if __name__ == "__main__":
    unittest.main()
