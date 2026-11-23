"""ZYRQUEN V11 Stage 1 Code Readiness unit tests (pure Python stdlib unittest)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.native.config import MAX_V10_PARAMETERS, ZyrquenConfig
from apps.core.native.dataset import (
    SCHEMA as DATASET_SCHEMA,
    SPLITS,
    V11_SPLITS,
    detect_dataset_format,
    load_sft_split,
    resolve_dataset_splits,
    verify_dataset_manifest,
)
from apps.core.native.evaluation import EvaluationEngine, EvaluationEvidenceError
from apps.core.native.registry import (
    ModelRegistry,
    RegistryError,
    is_v11_model_version,
)
from apps.core.native.sft import (
    SFT_FORMAT_VERSION,
    _V10_ENTITY_RE,
    _V11_ENTITY_RE,
    bind_ephemeral_slots,
    extract_entities,
    restore_ephemeral_slots,
    train_slot_safe_tokenizer,
)
from apps.core.native.tokenizer import SCHEMA_V2
from apps.core.native.train import TrainConfig, lr_at
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager
from apps.core.workflow.handlers.groups import (
    handle_data_verify_and_audit,
    handle_evaluation_gate,
    handle_training_execute,
)
from apps.core.workflow.models import LeakageGateFailedError


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_v11_dataset(
    root: Path,
    *,
    version: str = "11.0.0",
    manifest_style: str = "files",
) -> Path:
    ds_dir = root / "nagi_v11"
    ds_dir.mkdir(parents=True, exist_ok=True)
    rows_by_split = {
        "train": [
            {
                "example_id": "v11-tr-0001",
                "split": "train",
                "capability": "abstract_reasoning",
                "input": "FACTS: TR_E101 > TR_E102 | QUERY: TR_E101 ? TR_E102",
                "target": ">",
                "unique_answer_verified": True,
            },
            {
                "example_id": "v11-tr-0002",
                "split": "train",
                "capability": "ood_transfer",
                "input": "GRAPH: node_tr_01 -> node_tr_02 | QUERY: target of node_tr_01",
                "target": "node_tr_02",
                "unique_answer_verified": True,
            },
        ],
        "validation": [
            {
                "example_id": "v11-va-0001",
                "split": "validation",
                "capability": "abstract_reasoning",
                "input": "FACTS: VA_E201 > VA_E202 | QUERY: VA_E201 ? VA_E202",
                "target": ">",
                "unique_answer_verified": True,
            }
        ],
        "unseen": [
            {
                "example_id": "v11-un-0001",
                "split": "unseen",
                "capability": "ood_transfer",
                "input": "GRAPH: UN_E301 -> UN_E302 | QUERY: target of UN_E301",
                "target": "UN_E302",
                "unique_answer_verified": True,
            }
        ],
        "ood": [
            {
                "example_id": "v11-oo-0001",
                "split": "ood",
                "capability": "ood_transfer",
                "input": "GRAPH: OO_E401 -> OO_E402 -> OO_E403 | QUERY: terminal from OO_E401",
                "target": "OO_E403",
                "unique_answer_verified": True,
            }
        ],
    }

    files: dict[str, dict] = {}
    splits_meta: dict[str, dict] = {}
    for split_name in V11_SPLITS:
        rows = rows_by_split[split_name]
        p = ds_dir / f"{split_name}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        digest = _sha256_bytes(p.read_bytes())
        files[f"{split_name}.jsonl"] = {"documents": len(rows), "sha256": digest}
        splits_meta[split_name] = {"path": f"{split_name}.jsonl", "documents": len(rows), "sha256": digest}

    content_hash = hashlib.sha256(
        "".join(files[f"{sp}.jsonl"]["sha256"] for sp in V11_SPLITS).encode("utf-8")
    ).hexdigest()

    manifest: dict = {
        "schema": DATASET_SCHEMA,
        "dataset": "nagi_v11",
        "version": version,
        "content_sha256": content_hash,
        "sources": {
            "nagi_v11": {
                "path": "synthetic://nagi_v11",
                "license": "internal-native-research",
                "sha256": content_hash,
            }
        },
    }
    if manifest_style == "files":
        manifest["files"] = files
    elif manifest_style == "splits":
        manifest["splits"] = splits_meta
    else:
        manifest["files"] = files
        manifest["splits"] = splits_meta

    (ds_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return ds_dir


def _write_v10_dataset(root: Path, *, version: str = "10.0.0") -> Path:
    ds_dir = root / "nagi_v10"
    ds_dir.mkdir(parents=True, exist_ok=True)
    rows_by_split = {
        "train": [{"input": "TR_E101 -> TR_E102", "target": "TR_E102"}],
        "validation": [{"input": "VA_E201 -> VA_E202", "target": "VA_E202"}],
        "test": [{"input": "TE_E301 -> TE_E302", "target": "TE_E302"}],
    }
    files: dict[str, dict] = {}
    for split_name in SPLITS:
        rows = rows_by_split[split_name]
        p = ds_dir / f"{split_name}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        files[f"{split_name}.jsonl"] = {"documents": len(rows), "sha256": _sha256_bytes(p.read_bytes())}
    content_hash = hashlib.sha256(
        "".join(files[f"{sp}.jsonl"]["sha256"] for sp in SPLITS).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema": DATASET_SCHEMA,
        "dataset": "nagi_v10",
        "version": version,
        "content_sha256": content_hash,
        "files": files,
    }
    (ds_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return ds_dir


def _build_valid_v11_report(*, model_version: str = "ZYRQUEN-Native-11.0.0", ckpt_sha: str | None = None) -> dict:
    caps = (
        "abstract_reasoning",
        "relational_generalization",
        "ood_transfer",
        "multi_step_planning",
        "self_verification",
        "knowledge_integration",
    )
    cap_eval = {
        cap: {
            "status": "PASS",
            "splits": {
                "validation": {"status": "PASS", "accuracy": 0.8},
                "unseen": {"status": "PASS", "accuracy": 0.75},
                "ood": {"status": "PASS", "accuracy": 0.7},
            },
        }
        for cap in caps
    }
    return {
        "schema_version": "2.0",
        "report_schema": "zyrquen.v11.evaluation_report.v1",
        "experiment_id": "v11-stage6-exp20-step10000",
        "experiment_index": 20,
        "experiment_steps": 500,
        "global_step_start": 9500,
        "global_step_end": 10000,
        "stage": 6,
        "global_step": 10000,
        "overall_status": "PASS",
        "inference_status": "PASS",
        "inference_executed": True,
        "dataset_integrity": "PASS",
        "leakage_audit_status": "PASS",
        "checkpoint": {
            "model_version": model_version,
            "checkpoint_sha256": ckpt_sha or ("a" * 64),
            "verified": True,
        },
        "splits": {
            "train": {"evaluated": 2, "exact_match": 0.85, "diagnostic_only": True},
            "validation": {"evaluated": 1, "exact_match": 0.8},
            "unseen": {"evaluated": 1, "exact_match": 0.75, "unseen_entity_copy_acc": 1.0},
            "ood": {"evaluated": 1, "exact_match": 0.7, "unseen_entity_copy_acc": 1.0},
        },
        "capability_evaluation": cap_eval,
        "metrics": {
            "exact_match": 0.75,
            "validation_exact_match": 0.8,
            "unseen_exact_match": 0.75,
            "ood_exact_match": 0.7,
            "eos_hit_rate": 1.0,
        },
        "regression_comparison": [
            {"baseline_version": "ZYRQUEN-Native-10.0.0", "zero_regression": True}
        ],
        "acceptance_assessment": {
            "criteria": {
                "all_6_capabilities_pass": {"status": "PASS"},
                "ood_transfer_verified": {"status": "PASS"},
            },
            "stop_criteria_triggered": [],
        },
    }


def _register_dummy_v11_model(root: Path, ds_dir: Path, *, version: str = "ZYRQUEN-Native-11.0.0") -> tuple[ModelRegistry, str]:
    train_rows = [json.loads(ln) for ln in (ds_dir / "train.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    tok = train_slot_safe_tokenizer(train_rows, vocab_size=640, schema=SCHEMA_V2, use_slots=True)
    tok_path = root / "tokenizer.json"
    tok.save(tok_path)

    ckpt_dir = root / "ckpt"
    model_cfg = ZyrquenConfig(vocab_size=tok.vocab_size, d_model=64, n_layers=2, n_heads=2, d_ff=128, max_seq_len=256)
    model_cfg.validate_parameter_budget(MAX_V10_PARAMETERS)
    state = {
        "model": {"dummy": [1, 2, 3]},
        "model_config": model_cfg.to_dict(),
        "config": TrainConfig.tier0_v11().__dict__,
        "tokenizer_sha256": tok.fingerprint(),
        "dataset_version": "11.0.0",
        "prompt_format": SFT_FORMAT_VERSION,
    }

    def _save_json(obj, path):
        Path(path).write_text(json.dumps(obj), encoding="utf-8")

    def _load_json(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    cm = CheckpointManager(ckpt_dir, save_fn=_save_json, load_fn=_load_json)
    cm.save(500, state)

    reg_dir = root / "registry"
    reg = ModelRegistry(reg_dir, load_fn=_load_json)
    rec = reg.register(
        version,
        ckpt_dir,
        tok_path,
        ds_dir,
        metrics={"val_loss": 1.2, "perplexity": 3.32},
        prompt_format=SFT_FORMAT_VERSION,
    )
    return reg, str(rec["checkpoint"]["sha256"])


class TestV11Stage1Readiness(unittest.TestCase):
    def test_sft_v11_slot_superset_and_v10_compatibility(self) -> None:
        self.assertIs(_V11_ENTITY_RE.search("UN_E0001") is not None, True)
        self.assertIs(_V11_ENTITY_RE.search("OO_E0002") is not None, True)
        self.assertIsNone(_V10_ENTITY_RE.search("UN_E0001"))
        self.assertIsNone(_V10_ENTITY_RE.search("OO_E0002"))

        v10_prompt = "TR_E101 -> VA_E202 -> TE_E303 and rec_tr_e1 -> step_te_9"
        self.assertEqual(_V10_ENTITY_RE.findall(v10_prompt), _V11_ENTITY_RE.findall(v10_prompt))

        prompt = "FACTS: UN_E101 -> OO_E202; node_oo_3 -> step_un_4 | QUERY: rec_oo_e5"
        target = "OO_E202 and rec_oo_e5"
        self.assertEqual(
            extract_entities(prompt),
            ["UN_E101", "OO_E202", "node_oo_3", "step_un_4", "rec_oo_e5"],
        )
        bp, bt, binding = bind_ephemeral_slots(prompt, target, permute_slots=False)
        self.assertNotIn("UN_E101", bp)
        self.assertNotIn("OO_E202", bp)
        self.assertIn("<slot_0>", bp)
        self.assertEqual(restore_ephemeral_slots(bt or "", binding), target)

    def test_four_split_dataset_verification_and_failure_modes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_files = _write_v11_dataset(root / "a", manifest_style="files")
            ds_splits = _write_v11_dataset(root / "b", manifest_style="splits")
            ds_v10 = _write_v10_dataset(root / "v10")

            for ds in (ds_files, ds_splits):
                manifest = verify_dataset_manifest(ds)
                self.assertEqual(resolve_dataset_splits(manifest), V11_SPLITS)
                self.assertEqual(detect_dataset_format(ds), "sft")
                self.assertEqual(len(list(load_sft_split(ds, "unseen"))), 1)
                self.assertEqual(len(list(load_sft_split(ds, "ood"))), 1)
                ee = EvaluationEngine(registry_root=root / "reg_unused")
                verified = ee.verify_dataset(ds, expected_version="11.0.0")
                self.assertEqual(verified["dataset"], "nagi_v11")
                res = handle_data_verify_and_audit({}, {"dataset_dir": str(ds)})
                self.assertEqual(res.verdict, "PASS", res.summary)

            # V10 3-split compatibility preserved
            m10 = verify_dataset_manifest(ds_v10)
            self.assertEqual(resolve_dataset_splits(m10), SPLITS)
            self.assertEqual(EvaluationEngine(registry_root=root / "reg_unused").verify_dataset(ds_v10)["version"], "10.0.0")

            # Tamper ood.jsonl -> fail-closed
            (ds_files / "ood.jsonl").write_text('{"input": "tamper", "target": "x"}\n', encoding="utf-8")
            with self.assertRaises(EvaluationEvidenceError):
                EvaluationEngine(registry_root=root / "reg_unused").verify_dataset(ds_files)
            with self.assertRaises(LeakageGateFailedError):
                handle_data_verify_and_audit({}, {"dataset_dir": str(ds_files)})

    def test_data_audit_rejects_entity_leakage_across_v11_splits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _write_v11_dataset(root)
            unseen_path = ds_dir / "unseen.jsonl"
            leaked_row = {
                "example_id": "v11-un-leak",
                "split": "unseen",
                "capability": "abstract_reasoning",
                "input": "FACTS: TR_E101 > UN_E999 | QUERY: TR_E101 ? UN_E999",
                "target": ">",
                "unique_answer_verified": True,
            }
            unseen_path.write_text(json.dumps(leaked_row) + "\n", encoding="utf-8")
            manifest = json.loads((ds_dir / "manifest.json").read_text(encoding="utf-8"))
            new_sha = _sha256_bytes(unseen_path.read_bytes())
            manifest["files"]["unseen.jsonl"]["sha256"] = new_sha
            manifest["content_sha256"] = hashlib.sha256(
                "".join(manifest["files"][f"{sp}.jsonl"]["sha256"] for sp in V11_SPLITS).encode("utf-8")
            ).hexdigest()
            (ds_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            with self.assertRaises(LeakageGateFailedError):
                handle_data_verify_and_audit({}, {"dataset_dir": str(ds_dir)})

    def test_train_config_tier0_v11_and_global_lr_continuity(self) -> None:
        default_cfg = TrainConfig()
        self.assertEqual((default_cfg.block_size, default_cfg.batch_size, default_cfg.max_steps), (128, 16, 1000))

        t0 = TrainConfig.tier0_v11(stage_id=1, experiment_index=1)
        self.assertEqual(t0.block_size, 256)
        self.assertEqual(t0.batch_size, 4)
        self.assertEqual(t0.max_steps, 500)
        self.assertEqual(t0.segment_max_steps, 500)
        self.assertEqual(t0.lr_total_steps, 10_000)

        seg1_cfg = TrainConfig.tier0_v11(max_steps=1_000, segment_max_steps=500, lr_total_steps=10_000, stage_id=1, experiment_index=1)
        seg2_cfg = TrainConfig.tier0_v11(max_steps=1_000, segment_max_steps=500, lr_total_steps=10_000, stage_id=1, experiment_index=2)
        self.assertAlmostEqual(lr_at(500, seg1_cfg), lr_at(500, seg2_cfg), places=12)
        self.assertLess(lr_at(5000, seg2_cfg), lr_at(500, seg1_cfg))
        self.assertAlmostEqual(lr_at(10_000, seg2_cfg), seg2_cfg.min_lr, places=12)

    def test_handle_training_execute_segmented_budget_and_v11_versioning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _write_v11_dataset(root)
            train_rows = [json.loads(ln) for ln in (ds_dir / "train.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
            tok = train_slot_safe_tokenizer(train_rows, vocab_size=640, schema=SCHEMA_V2, use_slots=True)
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)

            # Budget Lock rejects segment > 500
            blocked = handle_training_execute(
                {"consumed_approval": {"id": "app-1"}, "_train_fn": lambda *a, **k: {}, "_model": object()},
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(root / "ckpt_bad"),
                    "batch_size": 4,
                    "block_size": 256,
                    "global_target_steps": 1000,
                    "segment_max_steps": 501,
                },
            )
            self.assertEqual(blocked.verdict, "BLOCKED")
            self.assertEqual(blocked.error_code, "budget_violated")

            captured: dict = {}

            def _fake_train_sft(model, train_pairs, val_pairs, cfg, checkpoint_dir, log_path, **kwargs):
                captured["cfg"] = cfg
                return {
                    "steps": 500,
                    "resumed_from": 0,
                    "global_step_start": 0,
                    "global_step_end": 500,
                    "experiment_steps": 500,
                    "stage_id": cfg.stage_id,
                    "experiment_index": cfg.experiment_index,
                    "stopped_reason": None,
                    "train_loss": 1.5,
                    "val_loss": 1.6,
                    "perplexity": 4.95,
                    "parameter_changed": True,
                    "prompt_format": SFT_FORMAT_VERSION,
                }

            res = handle_training_execute(
                {"consumed_approval": {"id": "app-2"}, "_train_fn": _fake_train_sft, "_model": object()},
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(root / "ckpt_ok"),
                    "batch_size": 4,
                    "block_size": 256,
                    "global_target_steps": 1000,
                    "segment_max_steps": 500,
                    "lr_total_steps": 10_000,
                    "stage_id": 1,
                    "experiment_index": 1,
                },
            )
            self.assertEqual(res.verdict, "PASS", res.summary)
            self.assertEqual(captured["cfg"].max_steps, 1000)
            self.assertEqual(captured["cfg"].segment_max_steps, 500)
            self.assertEqual(captured["cfg"].lr_total_steps, 10_000)
            self.assertEqual(captured["cfg"].stage_id, 1)
            self.assertEqual(captured["cfg"].experiment_index, 1)
            self.assertTrue(is_v11_model_version(res.output["model_version"]))
            self.assertEqual(res.output["model_version"], "ZYRQUEN-Native-11.0.0")
            self.assertEqual(res.output["global_step_end"], 500)
            self.assertEqual(res.output["experiment_steps"], 500)

    def test_handle_evaluation_gate_v11_strict_fail_closed_and_evidence_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _write_v11_dataset(root)
            reg, ckpt_sha = _register_dummy_v11_model(root, ds_dir, version="ZYRQUEN-Native-11.0.0")

            # 1. Valid PASS report attaches evidence without promoting active version
            pass_report = _build_valid_v11_report(model_version="ZYRQUEN-Native-11.0.0", ckpt_sha=ckpt_sha)
            pass_path = root / "eval_pass.json"
            pass_path.write_text(json.dumps(pass_report), encoding="utf-8")
            res_pass = handle_evaluation_gate(
                {"run_id": "wf-eval-v11-1"},
                {"report_path": str(pass_path), "registry_root": str(reg.root), "model_version": "ZYRQUEN-Native-11.0.0"},
            )
            self.assertEqual(res_pass.verdict, "PASS", res_pass.summary)
            self.assertIsNone(reg.active_version())
            rec = reg.get("ZYRQUEN-Native-11.0.0")
            self.assertEqual(rec["lifecycle_status"], "verified")
            self.assertEqual(rec["evaluation_evidence"]["report_schema"], "zyrquen.v11.evaluation_report.v1")

            # 2. Empty regression_comparison -> FAIL
            empty_reg_path = root / "eval_empty_reg.json"
            bad_report = _build_valid_v11_report()
            bad_report["regression_comparison"] = []
            empty_reg_path.write_text(json.dumps(bad_report), encoding="utf-8")
            res_empty = handle_evaluation_gate({}, {"report_path": str(empty_reg_path)})
            self.assertEqual(res_empty.verdict, "FAIL")
            self.assertIn("regression_comparison_missing_or_empty", res_empty.output["failures"])

            # 3. Missing OOD split -> FAIL
            no_ood_path = root / "eval_no_ood.json"
            no_ood = _build_valid_v11_report()
            del no_ood["splits"]["ood"]
            no_ood_path.write_text(json.dumps(no_ood), encoding="utf-8")
            res_no_ood = handle_evaluation_gate({}, {"report_path": str(no_ood_path)})
            self.assertEqual(res_no_ood.verdict, "FAIL")
            self.assertIn("missing_split:ood", res_no_ood.output["failures"])

            # 4. inference_executed=False -> NOT RUN
            not_run_path = root / "eval_not_run.json"
            not_run = _build_valid_v11_report()
            not_run["inference_executed"] = False
            not_run["overall_status"] = "NOT RUN"
            not_run["inference_status"] = "NOT RUN"
            not_run_path.write_text(json.dumps(not_run), encoding="utf-8")
            res_not_run = handle_evaluation_gate({}, {"report_path": str(not_run_path)})
            self.assertEqual(res_not_run.verdict, "NOT RUN")

            # 5. BLOCKED status -> BLOCKED
            blocked_path = root / "eval_blocked.json"
            blocked = _build_valid_v11_report()
            blocked["overall_status"] = "BLOCKED"
            blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
            res_blocked = handle_evaluation_gate({}, {"report_path": str(blocked_path)})
            self.assertEqual(res_blocked.verdict, "BLOCKED")

            # 6. Symlinked report -> BLOCKED
            sym_path = root / "eval_symlink.json"
            os.symlink(pass_path, sym_path)
            res_sym = handle_evaluation_gate({}, {"report_path": str(sym_path)})
            self.assertEqual(res_sym.verdict, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
