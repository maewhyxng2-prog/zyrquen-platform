from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

try:
    import torch
except ImportError:  # pragma: no cover - runtime test reports skip without torch
    torch = None

from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager,
    capture_rng_state,
    restore_rng_state,
    serialize_python_rng_state,
    restore_python_rng_state,
    validate_resume_identity,
)


class TestV10DResumeIntegrity(unittest.TestCase):
    def test_identity_validation_rejects_each_mismatched_identity(self):
        expected = {
            "dataset_version": "10.0.0",
            "dataset_content_sha256": "dataset-a",
            "tokenizer_sha256": "tokenizer-a",
            "model_config": {"vocab_size": 512, "d_model": 256},
            "training_identity": {"seed": 7, "lr": 0.0003},
        }
        state = dict(expected)
        validate_resume_identity(state, expected=expected)
        for field in expected:
            altered = dict(state)
            altered[field] = {"changed": True} if isinstance(state[field], dict) else "different"
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    validate_resume_identity(altered, expected=expected)

    def test_identity_validation_rejects_legacy_checkpoint_without_fingerprints(self):
        with self.assertRaisesRegex(ValueError, "missing identity fields"):
            validate_resume_identity({"model": {}}, expected={})

    def test_python_rng_state_round_trips_as_primitive_lists(self):
        source = random.Random(1234)
        expected_next = source.random()
        state = serialize_python_rng_state(source.getstate())
        self.assertIsInstance(state, list)
        self.assertIsInstance(state[1], list)
        restored = random.Random()
        restore_python_rng_state(restored, state)
        self.assertEqual(restored.random(), expected_next)

    @unittest.skipIf(torch is None, "PyTorch is not installed")
    def test_real_torch_weights_only_checkpoint_save_reload(self):
        with tempfile.TemporaryDirectory() as td:
            model = torch.nn.Linear(3, 2)
            optimizer = torch.optim.AdamW(model.parameters())
            expected = {
                "dataset_version": "10.0.0",
                "dataset_content_sha256": "dataset-sha",
                "tokenizer_sha256": "tokenizer-sha",
                "model_config": {"vocab_size": 512, "d_model": 256},
                "training_identity": {"seed": 7, "lr": 0.0003},
            }
            batch_rng = random.Random(99)
            state = {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                **expected,
                "batch_rng": serialize_python_rng_state(batch_rng.getstate()),
                "rng": capture_rng_state(),
            }
            manager = CheckpointManager(Path(td), keep_last=2)
            manager.save(12, state)
            loaded = manager.load_latest()
            self.assertIsNotNone(loaded)
            step, restored = loaded
            self.assertEqual(step, 12)
            validate_resume_identity(restored, expected=expected)
            self.assertIsInstance(restored["batch_rng"], list)
            restore_python_rng_state(random.Random(), restored["batch_rng"])
            restore_rng_state(restored["rng"])
            self.assertTrue(torch.equal(restored["model"]["weight"], state["model"]["weight"]))


if __name__ == "__main__":
    unittest.main()
