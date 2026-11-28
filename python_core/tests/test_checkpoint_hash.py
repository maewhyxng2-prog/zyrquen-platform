"""Unit tests for automatic checkpoint SHA-256 sidecar generation and verification."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from checkpoint_hash import (  # noqa: E402
    compute_file_sha256,
    read_checkpoint_sha256,
    save_checkpoint_sha256,
    save_checkpoint_with_sha256,
    sha256_sidecar_path,
    verify_checkpoint_sha256,
)
from native_neural import NativeTransformerLM  # noqa: E402
from native_tokenizer import NativeBPETokenizer  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
)
from v2.zyrquen_v2_trainer import ByteTokenizer  # noqa: E402


class TestCheckpointHashUtility(unittest.TestCase):
    def test_save_read_and_verify_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "model_step_100.json.gz"
            payload = b"zyrquen-checkpoint-bytes" * 128
            ckpt.write_bytes(payload)

            sidecar, digest = save_checkpoint_sha256(ckpt)
            expected = hashlib.sha256(payload).hexdigest()

            self.assertEqual(sidecar, sha256_sidecar_path(ckpt))
            self.assertTrue(sidecar.is_file())
            self.assertEqual(digest, expected)
            self.assertEqual(sidecar.read_text(encoding="utf-8"), expected)
            self.assertEqual(read_checkpoint_sha256(ckpt), expected)
            self.assertTrue(verify_checkpoint_sha256(ckpt))

            # Tampering with checkpoint must fail verification
            ckpt.write_bytes(payload + b"tamper")
            self.assertFalse(verify_checkpoint_sha256(ckpt))

    def test_missing_checkpoint_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "does_not_exist.json.gz"
            with self.assertRaises(FileNotFoundError):
                save_checkpoint_sha256(missing)
            self.assertFalse(verify_checkpoint_sha256(missing))

    def test_save_checkpoint_with_sha256_wrapper_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "step_5200.pt"
            saved_path, sidecar_path, digest = save_checkpoint_with_sha256(
                ckpt,
                lambda p: p.write_bytes(b"weights-payload"),
                overwrite=False,
                include_filename=True,
            )
            self.assertEqual(saved_path, ckpt)
            self.assertTrue(sidecar_path.is_file())
            self.assertEqual(digest, compute_file_sha256(ckpt))
            self.assertIn("step_5200.pt", sidecar_path.read_text(encoding="utf-8"))
            self.assertTrue(verify_checkpoint_sha256(ckpt))

            with self.assertRaises(FileExistsError):
                save_checkpoint_with_sha256(
                    ckpt,
                    lambda p: p.write_bytes(b"overwrite"),
                    overwrite=False,
                )

    def test_native_neural_save_checkpoint_writes_sha256(self) -> None:
        tok = NativeBPETokenizer()
        tok.train(["alpha beta gamma", "delta epsilon zeta"], target_vocab_size=64)
        model = NativeTransformerLM(
            vocab_size=tok.vocab_size,
            d_model=8,
            n_heads=2,
            n_layers=1,
            d_ff=16,
            max_seq_len=16,
            seed=42,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "native.json.gz"
            returned_path, digest = model.save_checkpoint(ckpt, tok, metrics={"loss": 1.23})
            self.assertEqual(returned_path, ckpt)
            sidecar = sha256_sidecar_path(ckpt)
            self.assertTrue(sidecar.is_file())
            self.assertEqual(sidecar.read_text(encoding="utf-8"), digest)
            self.assertTrue(verify_checkpoint_sha256(ckpt))

    def test_pure_v2_save_checkpoint_writes_sha256(self) -> None:
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
            ckpt = Path(tmpdir) / "v2_step5200.json.gz"
            saved_path, digest = trainer.save_checkpoint(ckpt)
            sidecar = sha256_sidecar_path(saved_path)
            self.assertTrue(sidecar.is_file())
            self.assertEqual(sidecar.read_text(encoding="utf-8"), digest)
            self.assertTrue(verify_checkpoint_sha256(saved_path))


if __name__ == "__main__":
    unittest.main()
