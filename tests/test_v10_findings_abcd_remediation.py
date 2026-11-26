"""Regression tests for ZYRQUEN V10 Findings A, B, C, and D remediation.

NOTE ON VERIFICATION LEVEL:
All tests in this module are pure-Python UNIT / STATIC CONTRACT tests using
temporary directories and explicit JSON checkpoint doubles (`_json_save` / `_json_load`).
They do NOT install PyTorch, do NOT run real PyTorch tensor training/inference,
and must NOT be reported as PyTorch Runtime PASS.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.core.native.checkpoint import CheckpointManager, VersionedCheckpointManager
from apps.core.native.closure_audit import build_v10_closure_audit
from apps.core.native.config import ZyrquenConfig
from apps.core.native.evaluation import EvaluationEngine, EvaluationEvidenceError
from apps.core.native.registry import (
    FROZEN_BASELINE_NAMES,
    V10_VERSIONING_CONTRACT,
    ModelRegistry,
    RegistryError,
    is_v10_model_version,
    resolve_canonical_model_version,
)
from apps.core.native.sft import SFT_FORMAT_VERSION, train_slot_safe_tokenizer
from apps.core.native.tokenizer import SCHEMA_V2
from apps.core.workflow.handlers.groups import (
    handle_evaluation_gate,
    handle_evaluation_verify,
    handle_training_execute,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator

HAS_TORCH = importlib.util.find_spec("torch") is not None


def _json_save(obj: dict, path: str) -> None:
    Path(path).write_text(json.dumps(obj), encoding="utf-8")


def _json_load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class _FakeModel:
    def __init__(self, cfg: ZyrquenConfig) -> None:
        self.cfg = cfg

    def num_parameters(self) -> int:
        return self.cfg.validate_parameter_budget()


def _make_v10_dataset_and_tokenizer(root: Path) -> tuple[Path, Path, ZyrquenConfig]:
    tools_dir = str(REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from gen_nagi_v10 import generate_dataset

    ds_dir = root / "nagi_v10"
    generate_dataset(ds_dir, seed=42, counts={"train": 24, "validation": 12, "test": 12})
    train_rows = [
        json.loads(line)
        for line in (ds_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tok = train_slot_safe_tokenizer(train_rows, vocab_size=640, schema=SCHEMA_V2, use_slots=True)
    tok_path = root / "tokenizer.json"
    tok.save(tok_path)
    cfg = ZyrquenConfig(vocab_size=tok.vocab_size, max_seq_len=256, d_ff=704)
    return ds_dir, tok_path, cfg


def _make_fake_train_fn(cfg: ZyrquenConfig):
    def _fake_train(model, train_pairs, val_pairs, t_cfg, c_dir, log_path, **kwargs):
        cm = CheckpointManager(c_dir, save_fn=_json_save, load_fn=_json_load)
        cm.save(
            t_cfg.max_steps,
            {
                "step": t_cfg.max_steps,
                "tokenizer_sha256": kwargs.get("tokenizer_fingerprint"),
                "dataset_version": kwargs.get("dataset_version"),
                "prompt_format": SFT_FORMAT_VERSION,
                "model_config": cfg.to_dict(),
                "config": {"max_steps": t_cfg.max_steps},
            },
        )
        return {
            "steps": t_cfg.max_steps,
            "stopped_reason": None,
            "train_loss": 1.15,
            "val_loss": 1.25,
            "perplexity": 3.49,
            "parameter_changed": True,
            "prompt_format": SFT_FORMAT_VERSION,
        }

    return _fake_train


def _write_passing_eval_report(path: Path, model_version: str, ckpt_sha256: str) -> str:
    caps = (
        "abstract_reasoning",
        "relational_generalization",
        "ood_transfer",
        "multi_step_planning",
        "self_verification",
        "knowledge_integration",
    )
    payload = {
        "schema_version": "1.0",
        "report_schema": "zyrquen.v10.evaluation_report.v1",
        "experiment_id": "v10-unit-eval",
        "overall_status": "PASS",
        "inference_status": "PASS",
        "inference_hook_implemented": True,
        "dataset_integrity": "PASS",
        "leakage_audit_status": "PASS",
        "metrics": {
            "exact_match": 0.85,
            "validation_exact_match": 0.80,
            "test_exact_match": 0.90,
            "eos_hit_rate": 1.0,
            **{f"cap_{c}_accuracy": 0.85 for c in caps},
        },
        "capability_evaluation": {
            c: {"status": "PASS", "accuracy": 0.85, "correct": 8, "total": 10}
            for c in caps
        },
        "checkpoint": {
            "model_version": model_version,
            "checkpoint_sha256": ckpt_sha256,
            "verified": True,
        },
        "acceptance_assessment": {
            "criteria": {"exact_match_ge_0.80": {"status": "PASS"}},
            "stop_criteria_triggered": [],
        },
        "regression_comparison": [{"zero_regression": True}],
        "error": None,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestV10FindingACanonicalVersionPrefix(unittest.TestCase):
    def test_empty_registry_v10_registration_and_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            tok = train_slot_safe_tokenizer(
                [json.loads(l) for l in (ds_dir / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()],
                vocab_size=640,
                schema=SCHEMA_V2,
                use_slots=True,
            )
            tok.save(tok_path)

            ckpt_dir = root / "ckpt"
            cm = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
            cm.save(
                10,
                {
                    "step": 10,
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": cfg.to_dict(),
                },
            )

            reg = ModelRegistry(root / "registry", load_fn=_json_load)
            rec0 = reg.register_next_v10_version(ckpt_dir, tok_path, ds_dir)
            self.assertEqual(rec0["version"], "ZYRQUEN-Native-10.0.0")
            self.assertIsNone(rec0["parent"])
            self.assertTrue(is_v10_model_version(rec0["version"]))

            rec1 = reg.register_next_v10_version(ckpt_dir, tok_path, ds_dir)
            self.assertEqual(rec1["version"], "ZYRQUEN-Native-10.0.1")
            self.assertEqual(rec1["parent"], "ZYRQUEN-Native-10.0.0")

    def test_legacy_v7_v8_v9_and_0_1_0_entries_remain_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            from apps.core.native.tokenizer import ZyrquenTokenizer

            tok = ZyrquenTokenizer.load(tok_path)
            ckpt_dir = root / "ckpt"
            cm = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
            cm.save(
                10,
                {
                    "step": 10,
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": cfg.to_dict(),
                },
            )

            reg_root = root / "registry"
            reg = ModelRegistry(reg_root, load_fn=_json_load)

            # Seed pre-existing non-V10 entries including protected v7/v8/v9 history
            # (Bypass frozen check ONLY in test setup to simulate existing historical registry)
            reg_file = reg_root / "registry.json"
            reg_data = {
                "schema": "zyrquen.model-registry.v1",
                "active": "ZYRQUEN-Native-0.1.0",
                "history": ["v7", "v8", "v9"],
                "versions": {
                    name: {
                        "version": name,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "parent": None,
                        "lifecycle_status": "archived",
                        "frozen": True,
                        "checkpoint": {"step": 500, "sha256": "b" * 64, "path": f"artifacts/{name}/checkpoint.pt"},
                        "tokenizer": {"sha256": "c" * 64, "file_sha256": "d" * 64, "path": f"artifacts/{name}/tokenizer.json"},
                        "dataset": {"version": "0.1.0", "content_sha256": "e" * 64, "path": f"artifacts/{name}/dataset_manifest.json"},
                        "evaluation_evidence": {"passed": True, "zero_regression": True},
                    }
                    for name in ("v7", "v8", "v9")
                },
            }
            reg_file.write_text(json.dumps(reg_data, indent=2), encoding="utf-8")
            legacy_v0 = reg.register("ZYRQUEN-Native-0.1.0", ckpt_dir, tok_path, ds_dir)
            snapshot_before = {
                k: json.loads(json.dumps(reg.get(k)))
                for k in ("v7", "v8", "v9", "ZYRQUEN-Native-0.1.0")
            }

            # V10 registration on non-empty legacy registry starts cleanly at 10.0.0
            rec_v10 = reg.register_next_v10_version(ckpt_dir, tok_path, ds_dir)
            self.assertEqual(rec_v10["version"], "ZYRQUEN-Native-10.0.0")
            self.assertIsNone(rec_v10["parent"])

            # Verify v7-v9 and 0.1.0 records were NOT altered
            for k, old_rec in snapshot_before.items():
                self.assertEqual(reg.get(k), old_rec)

            # Protected baseline overwrite remains forbidden
            for frozen_name in ("v7", "v8", "v9"):
                self.assertIn(frozen_name, FROZEN_BASELINE_NAMES)
                with self.assertRaises(RegistryError):
                    reg.register(frozen_name, ckpt_dir, tok_path, ds_dir)

    def test_closure_audit_counts_only_eval_verified_canonical_v10_versions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            from apps.core.native.tokenizer import ZyrquenTokenizer

            tok = ZyrquenTokenizer.load(tok_path)
            ckpt_dir = root / "ckpt"
            cm = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
            cm.save(
                10,
                {
                    "step": 10,
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": cfg.to_dict(),
                },
            )

            reg_root = root / "registry"
            reg = ModelRegistry(reg_root, load_fn=_json_load)

            # 1) Register non-V10 0.1.0 and certify it -> Closure Audit MUST NOT count it as V10
            rec_010 = reg.register("ZYRQUEN-Native-0.1.0", ckpt_dir, tok_path, ds_dir)
            rep_010 = root / "rep_010.json"
            _write_passing_eval_report(rep_010, "ZYRQUEN-Native-0.1.0", rec_010["checkpoint"]["sha256"])
            gate_010 = handle_evaluation_gate(
                {"run_id": "eval-010"},
                {"report_path": str(rep_010), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-0.1.0"},
            )
            self.assertEqual(gate_010.verdict, "PASS")

            # 2) Register future V11 version and certify it -> Closure Audit MUST NOT count it as V10
            rec_11 = reg.register("ZYRQUEN-Native-11.0.0", ckpt_dir, tok_path, ds_dir)
            rep_11 = root / "rep_11.json"
            _write_passing_eval_report(rep_11, "ZYRQUEN-Native-11.0.0", rec_11["checkpoint"]["sha256"])
            handle_evaluation_gate(
                {"run_id": "eval-11"},
                {"report_path": str(rep_11), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-11.0.0"},
            )

            # 3) Register V10 10.0.0 WITHOUT evaluation -> NOT counted
            rec_10_unverified = reg.register("ZYRQUEN-Native-10.0.0", ckpt_dir, tok_path, ds_dir)

            # 4) Register V10 10.0.1 with FAIL evaluation -> quarantined, NOT counted
            reg.register("ZYRQUEN-Native-10.0.1", ckpt_dir, tok_path, ds_dir)
            reg.attach_evaluation_evidence(
                "ZYRQUEN-Native-10.0.1",
                eval_run_id="eval-fail",
                report_sha256="f" * 64,
                metrics={"exact_match": 0.1},
                passed=False,
                zero_regression=True,
                evaluation_status="FAIL",
                inference_executed=True,
            )

            audit_before = build_v10_closure_audit(
                eval_report_path=rep_010,
                registry_root=reg_root,
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                runtime_health={"runtime_status": "ready", "native_model_loaded": False, "is_trained": False},
            )
            self.assertEqual(audit_before["runtime_environment"]["verified_v10_models"], 0)
            self.assertEqual(audit_before["runtime_environment"]["verified_v10_versions"], [])
            self.assertIn("TRAINED_V10_MODEL_UNAVAILABLE", audit_before["blockers"])
            self.assertFalse(audit_before["v11_gate"]["unlocked"])

            # 5) Certify V10 10.0.0 through handle_evaluation_gate -> NOW Closure Audit detects ONLY 10.0.0
            rep_10 = root / "rep_10.json"
            _write_passing_eval_report(rep_10, "ZYRQUEN-Native-10.0.0", rec_10_unverified["checkpoint"]["sha256"])
            gate_10 = handle_evaluation_gate(
                {"run_id": "eval-10"},
                {"report_path": str(rep_10), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-10.0.0"},
            )
            self.assertEqual(gate_10.verdict, "PASS", gate_10.summary)

            audit_after = build_v10_closure_audit(
                eval_report_path=rep_10,
                registry_root=reg_root,
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                runtime_health={"runtime_status": "ready", "native_model_loaded": True, "is_trained": True, "model_version": "ZYRQUEN-Native-10.0.0"},
            )
            self.assertEqual(audit_after["runtime_environment"]["verified_v10_models"], 1)
            self.assertEqual(audit_after["runtime_environment"]["verified_v10_versions"], ["ZYRQUEN-Native-10.0.0"])
            if not HAS_TORCH:
                self.assertEqual(audit_after["overall_status"], "BLOCKED")
                self.assertEqual(audit_after["v11_gate"]["status"], "LOCKED")


class TestV10FindingBEliminateDualNaming(unittest.TestCase):
    def test_omitted_model_version_produces_single_canonical_id_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            ckpt_dir = root / "ckpt"
            reg_root = root / "registry"

            res1 = handle_training_execute(
                {
                    "run_id": "run-canonical-1",
                    "consumed_approval": {"id": "app-1"},
                    "_train_fn": _make_fake_train_fn(cfg),
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "registry_root": str(reg_root),
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(res1.verdict, "PASS", res1.summary)
            self.assertEqual(res1.output["model_version"], "ZYRQUEN-Native-10.0.0")
            self.assertEqual(res1.output["checkpoint_model_version"], "ZYRQUEN-Native-10.0.0")
            self.assertEqual(res1.output["registry_model_version"], "ZYRQUEN-Native-10.0.0")
            self.assertEqual(res1.output["version_source"], "canonical_auto")

            vcm = VersionedCheckpointManager(ckpt_dir, load_fn=_json_load)
            reg = ModelRegistry(reg_root, load_fn=_json_load)
            self.assertEqual([v["model_version"] for v in vcm.list_versions()], ["ZYRQUEN-Native-10.0.0"])
            self.assertEqual([v["version"] for v in reg.list_versions()], ["ZYRQUEN-Native-10.0.0"])

            # Checkpoint manifest version == Registry version and SHA-256 matches
            vcm_rec = vcm.get_version("ZYRQUEN-Native-10.0.0")
            reg_rec = reg.get("ZYRQUEN-Native-10.0.0")
            self.assertIsNotNone(vcm_rec)
            self.assertEqual(vcm_rec["checkpoint_sha256"], reg_rec["checkpoint"]["sha256"])

            # EvaluationEngine resolves the exact same version from both checkpoint_dir and registry_root
            eng_both = EvaluationEngine(checkpoint_dir=ckpt_dir, registry_root=reg_root, load_fn=_json_load)
            art_both = eng_both._resolve_version_artifacts("ZYRQUEN-Native-10.0.0")
            self.assertEqual(art_both["model_version"], "ZYRQUEN-Native-10.0.0")
            self.assertEqual(art_both["checkpoint_sha256"], reg_rec["checkpoint"]["sha256"])

            ev_verify = handle_evaluation_verify(
                {},
                {
                    "checkpoint_dir": str(ckpt_dir),
                    "registry_root": str(reg_root),
                    "model_version": "ZYRQUEN-Native-10.0.0",
                },
            )
            self.assertEqual(ev_verify.verdict, "PASS", ev_verify.summary)

            # Second run without model_version allocates ZYRQUEN-Native-10.0.1 consistently everywhere
            res2 = handle_training_execute(
                {
                    "run_id": "run-canonical-2",
                    "consumed_approval": {"id": "app-2"},
                    "_train_fn": _make_fake_train_fn(cfg),
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "registry_root": str(reg_root),
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(res2.verdict, "PASS", res2.summary)
            self.assertEqual(res2.output["model_version"], "ZYRQUEN-Native-10.0.1")
            self.assertEqual(res2.output["parent_version"], "ZYRQUEN-Native-10.0.0")
            self.assertEqual(res2.output["checkpoint_model_version"], "ZYRQUEN-Native-10.0.1")
            self.assertEqual(res2.output["registry_model_version"], "ZYRQUEN-Native-10.0.1")

            # Certify ZYRQUEN-Native-10.0.1 and confirm Closure Audit detects the exact registered version
            rep_1001 = root / "rep_1001.json"
            reg_rec2 = reg.get("ZYRQUEN-Native-10.0.1")
            _write_passing_eval_report(rep_1001, "ZYRQUEN-Native-10.0.1", reg_rec2["checkpoint"]["sha256"])
            gate_1001 = handle_evaluation_gate(
                {"run_id": "eval-1001"},
                {"report_path": str(rep_1001), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-10.0.1"},
            )
            self.assertEqual(gate_1001.verdict, "PASS", gate_1001.summary)

            audit = build_v10_closure_audit(
                eval_report_path=rep_1001,
                registry_root=reg_root,
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                runtime_health={"runtime_status": "ready", "native_model_loaded": True, "is_trained": True, "model_version": "ZYRQUEN-Native-10.0.1"},
            )
            self.assertEqual(audit["runtime_environment"]["verified_v10_versions"], ["ZYRQUEN-Native-10.0.1"])

    def test_explicit_model_version_shared_and_rejects_invalid_or_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            ckpt_dir = root / "ckpt"
            reg_root = root / "registry"

            # Reject invalid non-V10 explicit version before training
            bad_res = handle_training_execute(
                {
                    "run_id": "run-bad",
                    "consumed_approval": {"id": "app-bad"},
                    "_train_fn": _make_fake_train_fn(cfg),
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "registry_root": str(reg_root),
                    "model_version": "ZYRQUEN-Native-0.1.0",
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(bad_res.verdict, "BLOCKED")
            self.assertEqual(bad_res.error_code, "invalid_model_version")

            # Valid explicit V10 version passes & synchronizes CheckpointManager + Registry
            ok_res = handle_training_execute(
                {
                    "run_id": "run-explicit",
                    "consumed_approval": {"id": "app-ok"},
                    "_train_fn": _make_fake_train_fn(cfg),
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "registry_root": str(reg_root),
                    "model_version": "ZYRQUEN-Native-10.0.5",
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(ok_res.verdict, "PASS", ok_res.summary)
            self.assertEqual(ok_res.output["model_version"], "ZYRQUEN-Native-10.0.5")
            self.assertEqual(ok_res.output["checkpoint_model_version"], "ZYRQUEN-Native-10.0.5")
            self.assertEqual(ok_res.output["registry_model_version"], "ZYRQUEN-Native-10.0.5")
            self.assertEqual(ok_res.output["version_source"], "explicit")

            # Duplicate explicit version MUST be blocked before training runs
            dup_res = handle_training_execute(
                {
                    "run_id": "run-dup",
                    "consumed_approval": {"id": "app-dup"},
                    "_train_fn": _make_fake_train_fn(cfg),
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "registry_root": str(reg_root),
                    "model_version": "ZYRQUEN-Native-10.0.5",
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(dup_res.verdict, "BLOCKED")
            self.assertEqual(dup_res.error_code, "duplicate_model_version")

    def test_failed_training_releases_pre_reserved_version_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            reg_root = root / "registry"

            def _failing_train(*args, **kwargs):
                return {"steps": 1, "stopped_reason": "loss_diverged", "val_loss": 99.0, "parameter_changed": True}

            fail_res = handle_training_execute(
                {
                    "run_id": "run-fail-release",
                    "consumed_approval": {"id": "app-fail"},
                    "_train_fn": _failing_train,
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(root / "ckpt_fail"),
                    "registry_root": str(reg_root),
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(fail_res.verdict, "FAIL")
            reg = ModelRegistry(reg_root, load_fn=_json_load)
            self.assertEqual(reg.list_reservations(), [])

            # Next run should cleanly allocate ZYRQUEN-Native-10.0.0 without dangling lock
            ok_res = handle_training_execute(
                {
                    "run_id": "run-recover",
                    "consumed_approval": {"id": "app-rec"},
                    "_train_fn": _make_fake_train_fn(cfg),
                    "_model": _FakeModel(cfg),
                    "_load_fn": _json_load,
                },
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(root / "ckpt_ok"),
                    "registry_root": str(reg_root),
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(ok_res.verdict, "PASS", ok_res.summary)
            self.assertEqual(ok_res.output["model_version"], "ZYRQUEN-Native-10.0.0")

    def test_evaluation_engine_rejects_checkpoint_registry_artifact_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            from apps.core.native.tokenizer import ZyrquenTokenizer

            tok = ZyrquenTokenizer.load(tok_path)
            ckpt_a = root / "ckpt_a"
            cm_a = CheckpointManager(ckpt_a, save_fn=_json_save, load_fn=_json_load)
            cm_a.save(
                5,
                {
                    "step": 5,
                    "weights": [1],
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": cfg.to_dict(),
                },
            )
            vcm_a = VersionedCheckpointManager(ckpt_a, load_fn=_json_load)
            vcm_a.register_existing_checkpoint(
                model_version="ZYRQUEN-Native-10.0.0",
                dataset_version="10.0.0",
                dataset_content_hash="abc",
                config={},
                tokenizer_sha256=tok.fingerprint(),
            )

            ckpt_b = root / "ckpt_b"
            cm_b = CheckpointManager(ckpt_b, save_fn=_json_save, load_fn=_json_load)
            cm_b.save(
                5,
                {
                    "step": 5,
                    "weights": [999],
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": cfg.to_dict(),
                },
            )
            reg_root = root / "registry"
            reg = ModelRegistry(reg_root, load_fn=_json_load)
            reg.register("ZYRQUEN-Native-10.0.0", ckpt_b, tok_path, ds_dir)

            eng = EvaluationEngine(checkpoint_dir=ckpt_a, registry_root=reg_root, load_fn=_json_load)
            with self.assertRaises(EvaluationEvidenceError):
                eng._resolve_version_artifacts("ZYRQUEN-Native-10.0.0")


class TestV10FindingsCDTerminalGuideSignatures(unittest.TestCase):
    def test_terminal_guide_matches_real_closure_audit_and_cancel_run_signatures(self) -> None:
        guide = (REPO_ROOT / "docs" / "ZYRQUEN_V10_V20_TERMINAL_MASTER_GUIDE.md").read_text(encoding="utf-8")

        # Finding C: must NOT reference non-existent collect_v10_closure_audit
        self.assertNotIn("collect_v10_closure_audit", guide)
        self.assertIn('build_v10_closure_audit(repo_root=Path("."))', guide)

        sig_audit = inspect.signature(build_v10_closure_audit)
        self.assertIn("repo_root", sig_audit.parameters)
        self.assertEqual(sig_audit.parameters["repo_root"].kind, inspect.Parameter.KEYWORD_ONLY)
        audit_payload = build_v10_closure_audit(repo_root=REPO_ROOT)
        self.assertEqual(audit_payload["schema"], "zyrquen.v10.closure_audit.v1")

        # Finding D: must NOT reference actor= on cancel_run; must use actor_id=
        self.assertNotIn("cancel_run(run_id, actor=", guide)
        self.assertIn("actor_id=", guide)
        sig_cancel = inspect.signature(CentralWorkflowOrchestrator.cancel_run)
        self.assertIn("actor_id", sig_cancel.parameters)
        self.assertNotIn("actor", sig_cancel.parameters)

        with tempfile.TemporaryDirectory() as td:
            orch = CentralWorkflowOrchestrator(db_path=Path(td) / "wf.db", work_dir=td, approval_secret="s" * 32)
            try:
                run, _ = orch.store.create_run(
                    workflow_key="system.health_check",
                    workflow_version="1.0.0",
                    trigger_type="manual",
                    trigger_payload={},
                    steps=[{"step_key": "s1", "depends_on": [], "lane": "control_ops"}],
                    requested_by_user_id="admin",
                )
                cancelled = orch.cancel_run(run["id"], actor_id="admin", reason="manual_abort")
                self.assertIsNotNone(cancelled)
                self.assertEqual(cancelled["status"], "CANCELLED")
            finally:
                orch.shutdown(wait=True)

        # Canonical V10 version in B.5 example
        self.assertIn("--model-version ZYRQUEN-Native-10.0.0", guide)


class TestV10CanonicalVersioningContractEdgeCases(unittest.TestCase):
    def test_contract_spec_and_once_per_run_reservation_reuse(self) -> None:
        self.assertEqual(V10_VERSIONING_CONTRACT.schema, "zyrquen.v10.versioning_contract.v1")
        self.assertEqual(V10_VERSIONING_CONTRACT.target_major, 10)
        self.assertEqual(V10_VERSIONING_CONTRACT.initial_version, "ZYRQUEN-Native-10.0.0")
        self.assertTrue(V10_VERSIONING_CONTRACT.matches("ZYRQUEN-Native-10.0.0"))
        self.assertFalse(V10_VERSIONING_CONTRACT.matches("ZYRQUEN-Native-0.1.0"))
        self.assertFalse(V10_VERSIONING_CONTRACT.matches("ZYRQUEN-Native-11.0.0"))

        with tempfile.TemporaryDirectory() as td:
            reg = ModelRegistry(Path(td) / "reg", load_fn=_json_load)
            r1 = resolve_canonical_model_version(
                registry=reg, target_major=10, training_run_id="run-shared-1"
            )
            r2 = resolve_canonical_model_version(
                registry=reg, target_major=10, training_run_id="run-shared-1"
            )
            self.assertEqual(r1.version, "ZYRQUEN-Native-10.0.0")
            self.assertEqual(r1, r2)

            with self.assertRaises(RegistryError):
                resolve_canonical_model_version(
                    explicit_version="ZYRQUEN-Native-10.0.9",
                    registry=reg,
                    target_major=10,
                    training_run_id="run-shared-1",
                )

            r_other = resolve_canonical_model_version(
                registry=reg, target_major=10, training_run_id="run-shared-2"
            )
            self.assertEqual(r_other.version, "ZYRQUEN-Native-10.0.1")

            self.assertTrue(reg.release_reservation(r1.version, r1.token))
            self.assertTrue(reg.release_reservation(r_other.version, r_other.token))

    def test_partial_legacy_registry_compatibility_and_eval_report_version_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir, tok_path, cfg = _make_v10_dataset_and_tokenizer(root)
            from apps.core.native.tokenizer import ZyrquenTokenizer

            tok = ZyrquenTokenizer.load(tok_path)
            ckpt_dir = root / "ckpt"
            cm = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
            cm.save(
                10,
                {
                    "step": 10,
                    "tokenizer_sha256": tok.fingerprint(),
                    "dataset_version": "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": cfg.to_dict(),
                },
            )

            reg_root = root / "registry"
            reg_root.mkdir(parents=True, exist_ok=True)
            # Legacy partial registry.json missing created_at, history, and artifact hashes on v7/0.1.0
            (reg_root / "registry.json").write_text(
                json.dumps({
                    "schema": "zyrquen.model-registry.v1",
                    "active": "ZYRQUEN-Native-0.1.0",
                    "versions": {
                        "v7": {"version": "v7", "frozen": True},
                        "ZYRQUEN-Native-0.1.0": {"version": "ZYRQUEN-Native-0.1.0"},
                    },
                }),
                encoding="utf-8",
            )

            reg = ModelRegistry(reg_root, load_fn=_json_load)
            self.assertEqual(reg.active_version(), "ZYRQUEN-Native-0.1.0")
            self.assertEqual(len(reg.list_versions()), 2)
            self.assertFalse(reg.verify("v7"))
            self.assertFalse(reg.verify("ZYRQUEN-Native-0.1.0"))

            rec_v10 = reg.register_next_v10_version(ckpt_dir, tok_path, ds_dir)
            self.assertEqual(rec_v10["version"], "ZYRQUEN-Native-10.0.0")
            rep_v10 = root / "rep_v10.json"
            _write_passing_eval_report(rep_v10, "ZYRQUEN-Native-10.0.0", rec_v10["checkpoint"]["sha256"])
            gate = handle_evaluation_gate(
                {"run_id": "eval-v10-compat"},
                {"report_path": str(rep_v10), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-10.0.0"},
            )
            self.assertEqual(gate.verdict, "PASS", gate.summary)

            # Passing non-V10 eval report MUST NOT pass V10 closure even when a verified V10 exists
            rep_legacy = root / "rep_legacy.json"
            _write_passing_eval_report(rep_legacy, "ZYRQUEN-Native-0.1.0", "a" * 64)
            audit_legacy_rep = build_v10_closure_audit(
                eval_report_path=rep_legacy,
                registry_root=reg_root,
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                runtime_health={"runtime_status": "ready", "native_model_loaded": True, "is_trained": True, "model_version": "ZYRQUEN-Native-0.1.0"},
            )
            self.assertIn("EVAL_REPORT_NON_V10_MODEL", audit_legacy_rep["blockers"])
            self.assertFalse(audit_legacy_rep["v11_gate"]["unlocked"])
            self.assertEqual(audit_legacy_rep["runtime_environment"]["verified_v10_versions"], ["ZYRQUEN-Native-10.0.0"])
            self.assertEqual(
                sorted(audit_legacy_rep["runtime_environment"]["ignored_legacy_versions"]),
                ["ZYRQUEN-Native-0.1.0", "v7"],
            )
            self.assertEqual(audit_legacy_rep["runtime_environment"]["active_model_version"], "ZYRQUEN-Native-0.1.0")
            self.assertIsNone(audit_legacy_rep["runtime_environment"]["active_v10_model_version"])


if __name__ == "__main__":
    unittest.main()
