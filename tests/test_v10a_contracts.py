"""V10-A Native Architecture & Integration Contract tests (pure stdlib unittest)."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.config import MAX_V10_PARAMETERS, NATIVE_MODEL_TYPE, ZyrquenConfig
from apps.core.native.dataset import (
    SCHEMA as DATASET_SCHEMA,
    detect_dataset_format,
    load_sft_split,
    load_split,
    load_split_records,
)
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager
from apps.core.native.sft import (
    IGNORE_INDEX,
    SFT_FORMAT_VERSION,
    SFT_SEP,
    bind_ephemeral_slots,
    build_sft_pairs,
    collate_sft_batch,
    encode_sft_pair,
    encode_sft_prompt,
    restore_ephemeral_slots,
    train_slot_safe_tokenizer,
)
from apps.core.native.tokenizer import (
    BASE_VOCAB,
    N_SPECIAL,
    SCHEMA as TOK_V1,
    SCHEMA_V2 as TOK_V2,
    SLOT_COUNT,
    SLOT_TOKENS,
    ZyrquenTokenizer,
)
from apps.core.native import train as train_mod
from apps.core.training.orchestrator import MAX_CPU_MODEL_PARAMETERS, TrainingOrchestrator, TrainingUnavailable


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_sft_dataset(root: Path, version: str = "10.0.0") -> None:
    root.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": [
            {"input": "TR_E101 is connected to TR_E102. Find target.", "target": "TR_E102"},
            {"input": "TR_E103 leads to TR_E104 via edge.", "target": "TR_E104"},
            {"input": "TR_E105 maps directly to TR_E106.", "target": "TR_E106"},
        ],
        "validation": [
            {"input": "VA_E201 is connected to VA_E202. Find target.", "target": "VA_E202"},
        ],
        "test": [
            {"input": "TE_E301 is connected to TE_E302. Find target.", "target": "TE_E302"},
        ],
    }
    files = {}
    for split, rows in splits.items():
        p = root / f"{split}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        files[f"{split}.jsonl"] = {"documents": len(rows), "sha256": _sha256_bytes(p.read_bytes())}

    content_hash = hashlib.sha256(
        "".join(files[f"{s}.jsonl"]["sha256"] for s in ("train", "validation", "test")).encode()
    ).hexdigest()
    manifest = {
        "schema": DATASET_SCHEMA,
        "version": version,
        "content_sha256": content_hash,
        "sources": {
            "nagi_v10": {
                "path": "synthetic://nagi_v10",
                "license": "internal-native-research",
                "sha256": "a" * 64,
            }
        },
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestContract1ModelConfigAndBudget(unittest.TestCase):
    def test_default_config_and_4096_vocab_within_5m_budget(self):
        cfg_default = ZyrquenConfig()
        self.assertEqual(cfg_default.d_ff, 704)
        self.assertEqual(cfg_default.model_type, NATIVE_MODEL_TYPE)
        self.assertEqual(cfg_default.estimated_num_parameters, 3_737_856)
        self.assertLessEqual(cfg_default.estimated_num_parameters, MAX_V10_PARAMETERS)
        self.assertEqual(cfg_default.validate_parameter_budget(), 3_737_856)

        cfg_4096 = ZyrquenConfig(vocab_size=4096, d_ff=704)
        self.assertEqual(cfg_4096.estimated_num_parameters, 4_262_144)
        self.assertLessEqual(cfg_4096.validate_parameter_budget(), MAX_V10_PARAMETERS)

        oversized = ZyrquenConfig(vocab_size=2048, d_ff=2048)
        with self.assertRaises(ValueError):
            oversized.validate_parameter_budget()

    def test_from_dict_tolerates_optional_model_type(self):
        cfg = ZyrquenConfig()
        payload = cfg.to_dict() | {"model_type": NATIVE_MODEL_TYPE}
        reloaded = ZyrquenConfig.from_dict(payload)
        self.assertEqual(reloaded, cfg)


class TestContract2And3TokenizerAndSFTAlignment(unittest.TestCase):
    def test_v1_tokenizer_fingerprint_and_specials_preserved(self):
        tok = ZyrquenTokenizer.train(["hello world " * 20], vocab_size=BASE_VOCAB + 8, schema=TOK_V1)
        self.assertEqual(tok.schema, TOK_V1)
        self.assertEqual(tok.n_special, N_SPECIAL)
        self.assertEqual(tok.byte_offset, 4)
        self.assertEqual(tok.base_vocab, 260)
        self.assertFalse(tok.supports_atomic_slots)
        expected_fp = hashlib.sha256(
            json.dumps(tok.merges, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(tok.fingerprint(), expected_fp)

    def test_v2_atomic_slots_ids_4_to_35_and_el05_zero_leakage(self):
        records = [
            {"input": "TR_E101 -> TR_E102 query", "target": "TR_E102"},
            {"input": "TR_E103 -> TR_E104 query", "target": "TR_E104"},
            {"input": "TR_E105 -> TR_E106 query", "target": "TR_E106"},
        ] * 5
        tok = train_slot_safe_tokenizer(
            records,
            vocab_size=320,
            use_slots=True,
            schema=TOK_V2,
            forbidden_entities=["TR_E101", "VA_E201", "TE_E301"],
        )
        self.assertTrue(tok.supports_atomic_slots)
        self.assertEqual(tok.n_special, 36)
        self.assertEqual(tok.byte_offset, 36)
        self.assertEqual(tok.base_vocab, 292)
        for idx in range(SLOT_COUNT):
            self.assertEqual(tok.slot_id(idx), 4 + idx)

        sample_ids = tok.encode("Node <slot_0> connects to <slot_31>.")
        self.assertIn(4, sample_ids)
        self.assertIn(35, sample_ids)
        decoded_skip_special = tok.decode(sample_ids, skip_special=True)
        self.assertEqual(decoded_skip_special, "Node <slot_0> connects to <slot_31>.")
        decoded_skip_slots = tok.decode(sample_ids, skip_special=True, skip_slots=True)
        self.assertEqual(decoded_skip_slots, "Node  connects to .")

        # Control tokens still require allow_special=True
        plain_bos = tok.encode("<|bos|>hi", allow_special=False)
        self.assertNotEqual(plain_bos[0], tok.bos_id)

        # Save/load round-trip preserves v2 schema and fingerprint
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "tok_v2.json"
            tok.save(p)
            reloaded = ZyrquenTokenizer.load(p)
            self.assertEqual(reloaded.fingerprint(), tok.fingerprint())
            self.assertEqual(reloaded.schema, TOK_V2)
            self.assertEqual(reloaded.encode("<slot_0> <slot_1>"), tok.encode("<slot_0> <slot_1>"))

    def test_train_slot_safe_tokenizer_rejects_entity_leakage(self):
        # Craft raw non-slotted entity repeated so BPE merges it -> EL-05 triggers
        records = [{"input": "VA_E999 VA_E999", "target": "VA_E999"}] * 20
        with self.assertRaises(ValueError) as ctx:
            train_slot_safe_tokenizer(
                records,
                vocab_size=310,
                use_slots=False,
                schema=TOK_V2,
                forbidden_entities=["VA_E999"],
            )
        self.assertIn("EL-05", str(ctx.exception))

    def test_bos_sep_eos_and_negative_100_mask_alignment(self):
        tok = ZyrquenTokenizer.train(
            [f"Alpha {SFT_SEP} Beta <slot_0> <slot_1> " * 10],
            vocab_size=320,
            schema=TOK_V2,
        )
        prompt = "From <slot_0> to ?"
        target = "<slot_1>"
        prefix = encode_sft_prompt(tok, prompt)
        self.assertEqual(prefix[0], tok.bos_id)

        x, y = encode_sft_pair(tok, prompt, target, max_seq_len=128)
        self.assertEqual(len(x), len(y))
        self.assertEqual(x[: len(prefix)], prefix)
        # First (len(prefix) - 1) target labels belong to prompt/SEP -> must be -100
        self.assertTrue(all(lbl == IGNORE_INDEX for lbl in y[: len(prefix) - 1]))
        # Position len(prefix) - 1 (last SEP token) predicts first token of target!
        target_ids = tok.encode(target, add_bos=False, add_eos=False) + [tok.eos_id]
        self.assertEqual(y[len(prefix) - 1 :], target_ids)
        self.assertEqual(y[-1], tok.eos_id)

        # Collate padding keeps -100 on padded label positions and pad_id=0 on x
        xs, ys = collate_sft_batch([(x, y), (x[:-1], y[:-1])], pad_id=tok.pad_id)
        self.assertEqual(xs[1][-1], 0)
        self.assertEqual(ys[1][-1], IGNORE_INDEX)

    def test_ephemeral_slot_bind_and_restore_roundtrip(self):
        bp, bt, binding = bind_ephemeral_slots("Go TE_E500 -> TE_E501", "TE_E501")
        self.assertEqual(bp, "Go <slot_0> -> <slot_1>")
        self.assertEqual(bt, "<slot_1>")
        self.assertEqual(restore_ephemeral_slots("Answer: <slot_1>", binding), "Answer: TE_E501")


class TestContract4And5SFTDatasetCheckpointAndStreaming(unittest.TestCase):
    def test_dataset_sft_detection_and_orchestrator_prepare_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ds_dir = root / "ds_v10"
            _write_sft_dataset(ds_dir, version="10.0.0")
            self.assertEqual(detect_dataset_format(ds_dir), "sft")
            val_rows = list(load_sft_split(ds_dir, "validation"))
            self.assertEqual(val_rows[0]["target"], "VA_E202")

            tok = train_slot_safe_tokenizer(
                list(load_sft_split(ds_dir, "train")) * 5,
                vocab_size=320,
                use_slots=True,
                schema=TOK_V2,
                forbidden_entities=["VA_E201", "VA_E202", "TE_E301", "TE_E302"],
            )
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)

            orch = TrainingOrchestrator(
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                training_root=root / "runs",
            )
            # Valid prepare
            prepared = orch.prepare(
                dataset_version="10.0.0",
                training_values={"block_size": 32, "batch_size": 2, "max_steps": 4, "warmup_steps": 1},
                model_values={"max_seq_len": 64, "d_ff": 704},
            )
            self.assertEqual(prepared.model_config.vocab_size, tok.vocab_size)
            self.assertLessEqual(prepared.model_config.estimated_num_parameters, MAX_CPU_MODEL_PARAMETERS)

            # Mismatched vocab_size rejected
            with self.assertRaises(TrainingUnavailable):
                orch.prepare(
                    dataset_version="10.0.0",
                    training_values={"block_size": 32, "batch_size": 2, "max_steps": 4, "warmup_steps": 1},
                    model_values={"vocab_size": tok.vocab_size + 10, "max_seq_len": 64},
                )

    def test_checkpoint_version_verifies_tokenizer_sha256(self):
        def _json_save(obj, path: str) -> None:
            Path(path).write_text(json.dumps(obj), encoding="utf-8")

        def _json_load(path: str):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            mgr = VersionedCheckpointManager(
                Path(tmp) / "ckpts",
                save_fn=_json_save,
                load_fn=_json_load,
            )
            fp = "f" * 64
            mgr.save_versioned(
                step=10,
                state={"model": {"w": [1]}, "tokenizer_sha256": fp},
                model_version="ZYRQUEN-Native-10.0.0",
                dataset_version="10.0.0",
                dataset_content_hash="d" * 64,
                config={"d_ff": 704},
            )
            self.assertTrue(mgr.verify_version("ZYRQUEN-Native-10.0.0", expected_tokenizer_sha256=fp))
            self.assertFalse(mgr.verify_version("ZYRQUEN-Native-10.0.0", expected_tokenizer_sha256="0" * 64))

    def test_train_checks_isfinite_before_optimizer_step(self):
        src_train = inspect.getsource(train_mod.train)
        idx_finite = src_train.find("math.isfinite(total_loss)")
        idx_step = src_train.find("optimizer.step()")
        self.assertGreater(idx_finite, 0)
        self.assertGreater(idx_step, idx_finite)

        src_sft = inspect.getsource(train_mod.train_sft)
        idx_finite_sft = src_sft.find("math.isfinite(total_loss)")
        idx_step_sft = src_sft.find("optimizer.step()")
        self.assertGreater(idx_finite_sft, 0)
        self.assertGreater(idx_step_sft, idx_finite_sft)

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic not installed in environment")
    def test_streaming_encode_prompt_aligns_with_sft_v1_and_legacy(self):
        from apps.core.streaming import _encode_prompt, _IncrementalTokenDecoder

        tok = ZyrquenTokenizer.train(["hello <slot_0> world " * 10], vocab_size=320, schema=TOK_V2)
        sft_ids = _encode_prompt(tok, "hello", prompt_format=SFT_FORMAT_VERSION)
        self.assertEqual(sft_ids, encode_sft_prompt(tok, "hello"))

        legacy_ids = _encode_prompt(tok, "hello", prompt_format=None)
        self.assertEqual(legacy_ids, tok.encode("hello", add_bos=False, add_eos=False))

        dec = _IncrementalTokenDecoder(tok)
        self.assertEqual(dec.decode_token(tok.slot_id(0)), "<slot_0>")

    def test_registry_preserves_prompt_format_and_rejects_symlinks(self):
        def _json_save(obj, path: str) -> None:
            Path(path).write_text(json.dumps(obj), encoding="utf-8")

        def _json_load(path: str):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ds_dir = root / "ds"
            _write_sft_dataset(ds_dir, version="10.0.0")
            tok = train_slot_safe_tokenizer(
                list(load_sft_split(ds_dir, "train")) * 5,
                vocab_size=320,
                use_slots=True,
                schema=TOK_V2,
                forbidden_entities=["VA_E201", "TE_E301"],
            )
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)

            ckpt_dir = root / "ckpts"
            mgr = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
            cfg = ZyrquenConfig(vocab_size=tok.vocab_size, d_ff=704).to_dict()
            mgr.save(
                5,
                {
                    "model": {"w": [1]},
                    "step": 5,
                    "config": {"max_steps": 5},
                    "model_config": cfg,
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                },
            )

            reg = ModelRegistry(root / "registry", load_fn=_json_load)
            rec = reg.register("ZYRQUEN-Native-0.1.0", ckpt_dir, tok_path, ds_dir)
            self.assertEqual(rec["prompt_format"], SFT_FORMAT_VERSION)

            # Dataset symlink tampering rejected by both dataset loader and ModelRegistry
            with self.assertRaises(ValueError):
                list(load_split_records(ds_dir, "../escape"))

            evil_ds = root / "evil_ds"
            evil_ds.mkdir()
            for name in ("manifest.json", "train.jsonl", "validation.jsonl", "test.jsonl"):
                if name == "train.jsonl":
                    (evil_ds / name).symlink_to(ds_dir / name)
                else:
                    (evil_ds / name).write_bytes((ds_dir / name).read_bytes())
            with self.assertRaises(ValueError):
                list(load_split_records(evil_ds, "train"))
            with self.assertRaises(RegistryError):
                reg.register("ZYRQUEN-Native-0.1.1", ckpt_dir, tok_path, evil_ds)

    def test_gen_nagi_v10_manifest_accepted_by_training_orchestrator_prepare(self):
        tools_dir = ROOT / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        import gen_nagi_v10  # type: ignore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ds_dir = root / "nagi_v10"
            manifest = gen_nagi_v10.generate_dataset(
                ds_dir,
                seed=42,
                counts={"train": 12, "validation": 6, "test": 6},
            )
            self.assertIn("sources", manifest)
            self.assertEqual(detect_dataset_format(ds_dir), "sft")

            tok = train_slot_safe_tokenizer(
                list(load_sft_split(ds_dir, "train")),
                vocab_size=384,
                use_slots=True,
                schema=TOK_V2,
            )
            tok_path = root / "tok.json"
            tok.save(tok_path)

            orch = TrainingOrchestrator(
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                training_root=root / "runs",
            )
            prepared = orch.prepare(
                dataset_version=manifest["version"],
                training_values={"block_size": 64, "batch_size": 2, "max_steps": 5, "warmup_steps": 1},
                model_values={"max_seq_len": 128, "d_ff": 704},
            )
            self.assertEqual(prepared.dataset_version, "10.0.0")
            self.assertEqual(prepared.tokenizer_fingerprint, tok.fingerprint())


if __name__ == "__main__":
    unittest.main()
