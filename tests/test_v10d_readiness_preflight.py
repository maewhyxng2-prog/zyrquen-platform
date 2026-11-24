from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import preflight_v10d


class TestV10DReadOnlyPreflight(unittest.TestCase):
    def test_ready_report_is_read_only_and_never_invokes_training(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataset = root / "dataset"
            dataset.mkdir()
            tokenizer = root / "tokenizer.json"
            tokenizer.write_text("fixture", encoding="utf-8")
            checkpoint = root / "checkpoints"
            registry = root / "registry"

            fake_tokenizer = SimpleNamespace(
                schema=preflight_v10d.SCHEMA_V2,
                supports_atomic_slots=True,
                vocab_size=512,
                fingerprint=lambda: "a" * 64,
            )
            with (
                patch.object(preflight_v10d, "check_torch_cpu_runtime",
                             return_value={"available": True, "cuda_available": False, "version": "test"}),
                patch.object(preflight_v10d, "read_process_rss_bytes", return_value=128 * 1024 * 1024),
                patch.object(preflight_v10d, "check_disk_reserve", return_value=(True, {"free_gb": 10, "ok": True})),
                patch.object(preflight_v10d, "verify_dataset",
                             return_value={"dataset_integrity": "PASS", "manifest_sha256": "b" * 64,
                                           "content_sha256": "c" * 64, "splits": {}}),
                patch.object(preflight_v10d, "run_audit",
                             return_value={"status": "PASS", "total_examples": 600, "split_counts": {}}),
                patch.object(preflight_v10d.ZyrquenTokenizer, "load", return_value=fake_tokenizer),
            ):
                result = preflight_v10d.run_preflight(
                    dataset_dir=dataset, tokenizer_path=tokenizer,
                    checkpoint_dir=checkpoint, registry_root=registry,
                    require_shared_governance=False,
                )

            self.assertEqual(result["overall_status"], "READY_FOR_AUTHORIZED_TRAINING_REVIEW")
            self.assertTrue(result["read_only"])
            self.assertFalse(result["training_invoked"])
            self.assertFalse(result["checkpoint_written"])
            self.assertFalse(result["registry_modified"])
            self.assertFalse(checkpoint.exists())
            self.assertFalse(registry.exists())


if __name__ == "__main__":
    unittest.main()
