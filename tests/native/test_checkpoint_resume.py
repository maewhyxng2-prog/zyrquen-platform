"""Tests for parameter_changed tracking, segmented checkpoint-resume, and V11 4-split DataAdapter."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA, V11_SPLITS
from apps.core.native.dataset_v11 import DataAdapter, DatasetLeakageError
from apps.core.native.train import (
    STRICT_BLOCK_SIZE,
    STRICT_MAX_BATCH_SIZE,
    STRICT_MAX_SEGMENT_STEPS,
    TrainConfig,
    lr_at,
    train,
    train_sft,
)

HAS_TORCH = importlib.util.find_spec("torch") is not None


# ---------------------------------------------------------------------------
# Lightweight pure-Python torch shim so train()/train_sft() parameter_changed
# and segmented checkpoint-resume logic run deterministically without torch.
# ---------------------------------------------------------------------------
class _ShimTensor:
    def __init__(self, data: list[float], *, requires_grad: bool = True) -> None:
        self.data = [float(v) for v in data]
        self.requires_grad = requires_grad
        self.grad: _ShimTensor | None = None

    def dim(self) -> int:
        return 2

    def detach(self) -> "_ShimTensor":
        return self

    def clone(self) -> "_ShimTensor":
        return _ShimTensor(list(self.data), requires_grad=self.requires_grad)

    def item(self) -> float:
        return float(self.data[0])

    def backward(self) -> None:
        return None

    def __truediv__(self, other: float) -> "_ShimTensor":
        return _ShimTensor([self.data[0] / float(other)], requires_grad=False)


class _ShimModel:
    class _Cfg:
        max_seq_len = 256

        def to_dict(self) -> dict:
            return {"max_seq_len": self.max_seq_len, "vocab_size": 320}

    def __init__(self, *, mutate_weights: bool = True) -> None:
        self.cfg = self._Cfg()
        self.mutate_weights = mutate_weights
        self._params = {
            "w": _ShimTensor([1.0, 2.0], requires_grad=True),
            "b": _ShimTensor([0.5], requires_grad=True),
        }

    def to(self, _device: str) -> "_ShimModel":
        return self

    def eval(self) -> None:
        return None

    def train(self) -> None:
        return None

    def parameters(self) -> list[_ShimTensor]:
        return list(self._params.values())

    def named_parameters(self):
        return list(self._params.items())

    def state_dict(self) -> dict:
        return {k: list(v.data) for k, v in self._params.items()}

    def load_state_dict(self, state: dict) -> None:
        for k, vals in state.items():
            if k in self._params:
                self._params[k].data = [float(v) for v in vals]
            else:
                self._params[k] = _ShimTensor(list(vals), requires_grad=True)

    def __call__(self, x, y=None):
        loss_val = sum(abs(v) for p in self._params.values() for v in p.data) * 0.25
        return None, _ShimTensor([loss_val], requires_grad=False)


class _ShimOptimizer:
    def __init__(self, param_groups, lr: float = 3e-4, betas=(0.9, 0.95)) -> None:
        self.param_groups = [{"lr": lr, "params": g["params"]} for g in param_groups]
        self.steps_taken = 0

    def zero_grad(self, set_to_none: bool = True) -> None:
        return None

    def step(self) -> None:
        self.steps_taken += 1
        for group in self.param_groups:
            lr = float(group.get("lr", 0.0))
            for p in group["params"]:
                if getattr(p, "_mutate", True):
                    p.data = [v - lr * 0.1 for v in p.data]

    def state_dict(self) -> dict:
        return {"steps_taken": self.steps_taken}

    def load_state_dict(self, state: dict) -> None:
        self.steps_taken = int(state.get("steps_taken", 0))


def _build_torch_shim(*, freeze_updates: bool = False):
    mod = types.ModuleType("torch")
    mod.long = int
    rng_state = {"seed": 0}

    def manual_seed(seed: int) -> None:
        rng_state["seed"] = int(seed)

    def get_rng_state() -> dict:
        return dict(rng_state)

    def set_rng_state(state: dict) -> None:
        rng_state["seed"] = int(state.get("seed", 0))

    def tensor(rows, dtype=None, device=None):
        return rows

    def equal(a: _ShimTensor, b: _ShimTensor) -> bool:
        return a.data == b.data

    class _NoGrad:
        def __call__(self, fn):
            return fn

        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    class _OptimMod:
        @staticmethod
        def AdamW(param_groups, lr=3e-4, betas=(0.9, 0.95)):
            if freeze_updates:
                for g in param_groups:
                    for p in g["params"]:
                        p._mutate = False
            return _ShimOptimizer(param_groups, lr=lr, betas=betas)

    class _UtilsMod:
        @staticmethod
        def clip_grad_norm_(params, max_norm):
            return 0.0

    class _NNMod:
        utils = _UtilsMod()

    def save(obj, path) -> None:
        # Serialize checkpoint dicts cleanly in pure JSON (batch_rng tuples -> lists)
        def _default(val):
            if isinstance(val, tuple):
                return list(val)
            raise TypeError(type(val))

        Path(path).write_text(json.dumps(obj, default=_default), encoding="utf-8")

    def load(path, map_location=None, weights_only=True):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("batch_rng"), list):
            st = raw["batch_rng"]
            raw["batch_rng"] = (st[0], tuple(st[1]), st[2])
        return raw

    mod.manual_seed = manual_seed
    mod.get_rng_state = get_rng_state
    mod.set_rng_state = set_rng_state
    mod.tensor = tensor
    mod.equal = equal
    mod.no_grad = _NoGrad
    mod.cuda = types.SimpleNamespace(
        is_available=lambda: False,
        get_rng_state_all=lambda: [],
        set_rng_state_all=lambda s: None,
    )
    mod.optim = _OptimMod()
    mod.nn = _NNMod()
    mod.save = save
    mod.load = load
    mod.set_num_threads = lambda n: None
    mod.get_num_threads = lambda: 2
    mod.set_num_interop_threads = lambda n: None
    mod.get_num_interop_threads = lambda: 2
    return mod


def _write_v11_dataset(root: Path, *, leak_entity: bool = False, leak_text: bool = False) -> Path:
    ds_dir = root / "ds_v11"
    ds_dir.mkdir(parents=True, exist_ok=True)
    rows_by_split = {
        "train": [
            {"split": "train", "input": "TR_E101 > TR_E102", "target": ">", "unique_answer_verified": True}
        ],
        "validation": [
            {"split": "validation", "input": "VA_E201 > VA_E202", "target": ">", "unique_answer_verified": True}
        ],
        "unseen": [
            {
                "split": "unseen",
                "input": "TR_E101 > TR_E102" if leak_text else ("TR_E101 > UN_E302" if leak_entity else "UN_E301 > UN_E302"),
                "target": ">",
                "unique_answer_verified": True,
            }
        ],
        "ood": [
            {"split": "ood", "input": "OO_E401 > OO_E402", "target": ">", "unique_answer_verified": True}
        ],
    }
    files: dict[str, dict] = {}
    for split in V11_SPLITS:
        p = ds_dir / f"{split}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows_by_split[split]), encoding="utf-8")
        files[f"{split}.jsonl"] = {
            "documents": len(rows_by_split[split]),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
    content_hash = hashlib.sha256(
        "".join(files[f"{sp}.jsonl"]["sha256"] for sp in V11_SPLITS).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema": DATASET_SCHEMA,
        "dataset": "nagi_v11",
        "version": "11.0.0",
        "content_sha256": content_hash,
        "files": files,
    }
    (ds_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return ds_dir


class TestStrictLimitsAndSegmentedResume(unittest.TestCase):
    def test_strict_resource_limits_enforced_on_tier0_v11(self) -> None:
        cfg = TrainConfig.tier0_v11(max_steps=1000, segment_max_steps=500, stage_id=1, experiment_index=1)
        self.assertEqual(cfg.batch_size, STRICT_MAX_BATCH_SIZE)
        self.assertEqual(cfg.block_size, STRICT_BLOCK_SIZE)
        self.assertEqual(cfg.segment_max_steps, STRICT_MAX_SEGMENT_STEPS)
        cfg.validate_strict_limits()

        with self.assertRaises(ValueError):
            TrainConfig.tier0_v11(batch_size=5)
        with self.assertRaises(ValueError):
            TrainConfig.tier0_v11(block_size=128)
        with self.assertRaises(ValueError):
            TrainConfig.tier0_v11(segment_max_steps=501)
        with self.assertRaises(ValueError):
            TrainConfig.tier0_v11(segment_max_steps=None)

    def test_parameter_changed_tracking_and_segmented_resume_pure_python(self) -> None:
        ids = list(range(1000))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt_dir = root / "ckpt"
            log_path = root / "train.jsonl"

            # Segment 1: steps 0 -> 5 (parameter_changed must be True)
            seg1_cfg = TrainConfig.tier0_v11(
                max_steps=10,
                segment_max_steps=5,
                lr_total_steps=20,
                warmup_steps=2,
                eval_interval=5,
                eval_batches=2,
                checkpoint_interval=5,
                log_interval=5,
                stage_id=1,
                experiment_index=1,
            )
            with patch.dict(sys.modules, {"torch": _build_torch_shim(freeze_updates=False)}):
                res1 = train(_ShimModel(), ids, ids, seg1_cfg, ckpt_dir, log_path)

            self.assertEqual(res1["resumed_from"], 0)
            self.assertEqual(res1["global_step_start"], 0)
            self.assertEqual(res1["global_step_end"], 5)
            self.assertEqual(res1["experiment_steps"], 5)
            self.assertTrue(res1["parameter_changed"])
            self.assertTrue(res1["checkpoint_saved"])

            # Segment 2: resume from step 5 -> 10 with same checkpoint_dir
            seg2_cfg = TrainConfig.tier0_v11(
                max_steps=10,
                segment_max_steps=5,
                lr_total_steps=20,
                warmup_steps=2,
                eval_interval=5,
                eval_batches=2,
                checkpoint_interval=5,
                log_interval=5,
                stage_id=1,
                experiment_index=2,
            )
            with patch.dict(sys.modules, {"torch": _build_torch_shim(freeze_updates=False)}):
                res2 = train(_ShimModel(), ids, ids, seg2_cfg, ckpt_dir, log_path)

            self.assertEqual(res2["resumed_from"], 5)
            self.assertEqual(res2["global_step_start"], 5)
            self.assertEqual(res2["global_step_end"], 10)
            self.assertEqual(res2["experiment_steps"], 5)
            self.assertEqual(res2["steps"], 10)
            self.assertTrue(res2["parameter_changed"])
            self.assertAlmostEqual(lr_at(5, seg1_cfg), lr_at(5, seg2_cfg), places=12)

            # Negative check: frozen parameters -> parameter_changed must be False
            no_change_dir = root / "ckpt_no_change"
            with patch.dict(sys.modules, {"torch": _build_torch_shim(freeze_updates=True)}):
                res_frozen = train(
                    _ShimModel(),
                    ids,
                    ids,
                    seg1_cfg,
                    no_change_dir,
                    root / "no_change.jsonl",
                )
            self.assertFalse(res_frozen["parameter_changed"])

    def test_sft_segmented_resume_and_versioned_manifest(self) -> None:
        pairs = [([1, 2, 3, 4], [-100, -100, 3, 2])] * 8
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt_dir = root / "sft_ckpt"
            log_path = root / "sft.jsonl"
            cfg1 = TrainConfig.tier0_v11(
                max_steps=6,
                segment_max_steps=3,
                lr_total_steps=12,
                warmup_steps=1,
                eval_interval=3,
                eval_batches=2,
                checkpoint_interval=3,
                log_interval=3,
                stage_id=1,
                experiment_index=1,
            )
            cfg2 = TrainConfig.tier0_v11(
                max_steps=6,
                segment_max_steps=3,
                lr_total_steps=12,
                warmup_steps=1,
                eval_interval=3,
                eval_batches=2,
                checkpoint_interval=3,
                log_interval=3,
                stage_id=1,
                experiment_index=2,
            )
            shim = _build_torch_shim(freeze_updates=False)
            with patch.dict(sys.modules, {"torch": shim}):
                r1 = train_sft(_ShimModel(), pairs, pairs, cfg1, ckpt_dir, log_path)
                r2 = train_sft(_ShimModel(), pairs, pairs, cfg2, ckpt_dir, log_path)

            self.assertEqual(r1["global_step_end"], 3)
            self.assertTrue(r1["parameter_changed"])
            self.assertEqual(r2["resumed_from"], 3)
            self.assertEqual(r2["global_step_start"], 3)
            self.assertEqual(r2["global_step_end"], 6)
            self.assertTrue(r2["parameter_changed"])

            vcm = VersionedCheckpointManager(ckpt_dir, load_fn=shim.load)
            rec = vcm.register_existing_checkpoint(
                model_version="ZYRQUEN-Native-11.0.0",
                dataset_version="11.0.0",
                dataset_content_hash="abc",
                config=cfg2.__dict__,
            )
            self.assertEqual(rec["step"], 6)
            self.assertTrue(vcm.verify_version("ZYRQUEN-Native-11.0.0"))

    @unittest.skipUnless(HAS_TORCH, "requires PyTorch runtime")
    def test_live_torch_segmented_resume_and_parameter_changed(self) -> None:
        import torch
        from apps.core.native.config import ZyrquenConfig
        from apps.core.native.model import ZyrquenModel

        mcfg = ZyrquenConfig(vocab_size=64, max_seq_len=256, n_layers=2, n_heads=2, d_model=32, d_ff=64)
        rng = random.Random(0)
        ids = [rng.randrange(64) for _ in range(300)] * 4

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt_dir = root / "torch_ckpt"
            log_path = root / "torch.jsonl"
            cfg1 = TrainConfig.tier0_v11(
                max_steps=4,
                segment_max_steps=2,
                lr_total_steps=8,
                warmup_steps=1,
                eval_interval=2,
                eval_batches=2,
                checkpoint_interval=2,
                log_interval=2,
            )
            cfg2 = TrainConfig.tier0_v11(
                max_steps=4,
                segment_max_steps=2,
                lr_total_steps=8,
                warmup_steps=1,
                eval_interval=2,
                eval_batches=2,
                checkpoint_interval=2,
                log_interval=2,
            )
            torch.manual_seed(0)
            r1 = train(ZyrquenModel(mcfg), ids, ids, cfg1, ckpt_dir, log_path)
            r2 = train(ZyrquenModel(mcfg), ids, ids, cfg2, ckpt_dir, log_path)
            self.assertTrue(r1["parameter_changed"])
            self.assertEqual(r1["global_step_end"], 2)
            self.assertEqual(r2["resumed_from"], 2)
            self.assertEqual(r2["global_step_end"], 4)
            self.assertTrue(r2["parameter_changed"])


class TestV11DataAdapter(unittest.TestCase):
    def test_four_split_adapter_and_leakage_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clean_dir = _write_v11_dataset(root / "clean")
            adapter = DataAdapter(clean_dir)
            splits, report = adapter.prepare_splits()
            self.assertEqual(tuple(splits.keys()), V11_SPLITS)
            self.assertTrue(report.passed)
            self.assertEqual(report.violations, [])

            entity_leak_dir = _write_v11_dataset(root / "ent_leak", leak_entity=True)
            ent_report = DataAdapter(entity_leak_dir).detect_leakage()
            self.assertFalse(ent_report.passed)
            self.assertTrue(any(v.startswith("entity_leakage:") for v in ent_report.violations))
            with self.assertRaises(DatasetLeakageError):
                DataAdapter(entity_leak_dir).validate_no_leakage()

            text_leak_dir = _write_v11_dataset(root / "txt_leak", leak_text=True)
            with self.assertRaises(DatasetLeakageError):
                DataAdapter(text_leak_dir).validate_no_leakage()


if __name__ == "__main__":
    unittest.main()
