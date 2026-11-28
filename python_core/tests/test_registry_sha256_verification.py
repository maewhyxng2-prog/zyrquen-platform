"""Unit tests for ModelRegistry `.sha256` sidecar emission and strict integrity verification."""

from __future__ import annotations

import json
import py_compile
import tempfile
import unittest
from pathlib import Path

from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


def _build_registry_fixtures(tmp_dir: Path) -> tuple[Path, Path, Path, Path]:
    ckpt_dir = tmp_dir / "ckpts"
    ds_dir = tmp_dir / "dataset"
    tok_path = tmp_dir / "tokenizer.json"
    reg_root = tmp_dir / "registry"

    src = tmp_dir / "docs.jsonl"
    docs = [
        {"text": f"hello zyrquen native world sample {i} for registry verification"}
        for i in range(60)
    ]
    src.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in docs),
        encoding="utf-8",
    )
    prepare_dataset(
        [Source(str(src), "test-declared")],
        ds_dir,
        PrepConfig(val_fraction=0.1, test_fraction=0.1, version="ds-test-1"),
    )

    tok = ZyrquenTokenizer.train(
        [d["text"] for d in docs],
        BASE_VOCAB + 30,
        version="tok-test-1",
    )
    tok.save(tok_path)
    manifest = json.loads((ds_dir / "manifest.json").read_text(encoding="utf-8"))

    manager = CheckpointManager(
        ckpt_dir,
        save_fn=lambda obj, p: Path(p).write_text(json.dumps(obj), encoding="utf-8"),
        load_fn=lambda p: json.loads(Path(p).read_text(encoding="utf-8")),
    )
    manager.save(
        25,
        {
            "step": 25,
            "tokenizer_sha256": tok.fingerprint(),
            "dataset_version": manifest["version"],
            "model_config": {
                "model_type": "zyrquen-decoder",
                "vocab_size": tok.vocab_size,
                "max_seq_len": 32,
                "n_layers": 1,
                "n_heads": 1,
                "d_model": 16,
                "d_ff": 32,
            },
        },
    )
    return ckpt_dir, tok_path, ds_dir, reg_root


class TestRegistrySha256Verification(unittest.TestCase):
    def test_register_creates_sidecar_and_verify_checkpoint_integrity_returns_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_dir, tok_path, ds_dir, reg_root = _build_registry_fixtures(Path(tmp))
            registry = ModelRegistry(
                reg_root,
                load_fn=lambda p: json.loads(Path(p).read_text(encoding="utf-8")),
            )
            record = registry.register("ZYRQUEN-Native-10.0.0", ckpt_dir, tok_path, ds_dir)

            sidecar = reg_root / "artifacts" / "ZYRQUEN-Native-10.0.0" / "checkpoint.pt.sha256"
            self.assertTrue(sidecar.is_file())
            self.assertEqual(
                record["checkpoint"]["sha256_path"],
                "artifacts/ZYRQUEN-Native-10.0.0/checkpoint.pt.sha256",
            )

            report = registry.verify_checkpoint_integrity("ZYRQUEN-Native-10.0.0")
            self.assertEqual(report["status"], "Verified")
            self.assertTrue(report["verified"])
            self.assertTrue(report["sidecar_present"])
            self.assertEqual(report["expected_sha256"], report["actual_sha256"])

    def test_verify_checkpoint_integrity_returns_corrupted_on_tamper_or_missing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_dir, tok_path, ds_dir, reg_root = _build_registry_fixtures(Path(tmp))
            registry = ModelRegistry(
                reg_root,
                load_fn=lambda p: json.loads(Path(p).read_text(encoding="utf-8")),
            )
            registry.register("ZYRQUEN-Native-10.0.0", ckpt_dir, tok_path, ds_dir)

            ckpt_file = reg_root / "artifacts" / "ZYRQUEN-Native-10.0.0" / "checkpoint.pt"
            sidecar = reg_root / "artifacts" / "ZYRQUEN-Native-10.0.0" / "checkpoint.pt.sha256"
            original_bytes = ckpt_file.read_bytes()

            ckpt_file.write_bytes(b"corrupted-weights")
            tampered_report = registry.verify_checkpoint_integrity("ZYRQUEN-Native-10.0.0")
            self.assertEqual(tampered_report["status"], "Corrupted")
            self.assertFalse(tampered_report["verified"])

            ckpt_file.write_bytes(original_bytes)
            sidecar.unlink()
            missing_sidecar_report = registry.verify_checkpoint_integrity("ZYRQUEN-Native-10.0.0")
            self.assertEqual(missing_sidecar_report["status"], "Corrupted")
            self.assertFalse(missing_sidecar_report["verified"])
            self.assertFalse(missing_sidecar_report["sidecar_present"])

            with self.assertRaises(RegistryError):
                registry.verify_checkpoint_integrity("../escape")

    def test_workflows_router_compiles_cleanly(self) -> None:
        py_compile.compile("apps/api/routers/workflows.py", doraise=True)
        py_compile.compile("apps/core/native/registry.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
