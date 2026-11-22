"""Comprehensive V10 Critical Blocker Remediation Tests (Resource, Timeout, Checkpoint/Eval Contract, Governance)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from apps.core.native.checkpoint import CheckpointManager, VersionedCheckpointManager
from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.evaluation import EvaluationEngine, EvaluationEvidenceError
from apps.core.native.registry import ModelRegistry
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.workflow import ApprovalViolationError, CentralWorkflowOrchestrator
from apps.core.workflow.audit import WorkflowAuditLogger
from apps.core.workflow.autonomous_training_loop import (
    AutonomousTrainingLoop,
    RamMonitor,
    validate_budget,
)
from apps.core.workflow.handlers.groups import (
    handle_evaluation_verify,
    handle_training_execute,
)
from apps.core.workflow.models import StepExecutionResult, WorkflowDefinition, WorkflowStepSpec
from apps.core.workflow.resource_guard import (
    GB,
    TrainingRuntimeGuard,
    WorkflowResourceGuard,
    check_torch_cpu_runtime,
    enforce_cpu_thread_cap,
)
from apps.core.workflow.store import WorkflowStore


_DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


def _json_save(obj, path: str) -> None:
    Path(path).write_text(json.dumps(obj), encoding="utf-8")


def _json_load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


class _FakeTorch:
    def __init__(self, *, raise_interop: bool = False) -> None:
        self._threads = 8
        self._interop = 8
        self._raise_interop = raise_interop

    def set_num_threads(self, n: int) -> None:
        self._threads = int(n)

    def get_num_threads(self) -> int:
        return self._threads

    def set_num_interop_threads(self, n: int) -> None:
        if self._raise_interop:
            raise RuntimeError("parallel work has already started")
        self._interop = int(n)

    def get_num_interop_threads(self) -> int:
        return self._interop


class _FakeModel:
    def __init__(self, cfg: ZyrquenConfig) -> None:
        self.cfg = cfg


class TestV10ResourceAndTimeoutGuards(unittest.TestCase):
    def test_cpu_thread_cap_enforced_across_env_and_torch_and_overcap_blocked(self) -> None:
        fake_torch = _FakeTorch()
        prev_env = {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "TORCH_NUM_THREADS")}
        try:
            info = enforce_cpu_thread_cap(2, torch_mod=fake_torch)
            self.assertEqual(info["cap"], 2)
            self.assertEqual(fake_torch.get_num_threads(), 2)
            self.assertEqual(fake_torch.get_num_interop_threads(), 2)
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "2")
            self.assertEqual(os.environ["TORCH_NUM_THREADS"], "2")

            # Handles RuntimeError from set_num_interop_threads safely
            info2 = enforce_cpu_thread_cap(2, torch_mod=_FakeTorch(raise_interop=True))
            self.assertEqual(info2["torch_threads"], 2)
            self.assertIn("parallel work", info2["interop_note"])
        finally:
            for k, v in prev_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        with self.assertRaises(ValueError):
            enforce_cpu_thread_cap(3)

        ok, reason = validate_budget(1000, 128, 2, 100, cpu_threads=4)
        self.assertFalse(ok)
        self.assertIn("cpu_threads", reason or "")

        guard = WorkflowResourceGuard()
        step = WorkflowStepSpec(
            step_key="train",
            handler_key="training.execute",
            lane="compute_heavy",
            tier="tier2_approval",
            action_type="training.execute",
        )
        with patch.object(guard, "snapshot", return_value={"ram_mb": 100.0, "free_disk_gb": 10.0, "vram_available": False}):
            out = guard.check_step(step, {"cpu_threads": 4})
            self.assertFalse(out.allowed)
            self.assertTrue(out.blocked)

    def test_ram_soft_warning_and_hard_stop_and_disk_guards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = WorkflowStore(root / "wf.db")
            audit = WorkflowAuditLogger(store)
            clock = _FakeClock()

            # 1. RamMonitor soft warning (3.1 GB) without hard stop, then hard stop (3.6 GB)
            soft_events: list[dict] = []
            hard_events: list[dict] = []
            mon_soft = RamMonitor(
                rss_reader=lambda: int(3.1 * GB),
                on_soft_limit=soft_events.append,
                on_hard_limit=hard_events.append,
            )
            snap_soft = mon_soft.check_now()
            self.assertTrue(snap_soft["exceeded_soft"])
            self.assertFalse(snap_soft["exceeded_hard"])
            self.assertEqual(len(soft_events), 1)
            self.assertEqual(len(hard_events), 0)

            mon_hard = RamMonitor(
                rss_reader=lambda: int(3.6 * GB),
                on_soft_limit=soft_events.append,
                on_hard_limit=hard_events.append,
            )
            snap_hard = mon_hard.check_now()
            self.assertTrue(snap_hard["exceeded_hard"])
            self.assertEqual(len(hard_events), 1)

            # 2. TrainingRuntimeGuard soft RAM audit warning -> continues safely
            rss_box = {"val": int(3.1 * GB)}
            disk_box = {"free": int(5.0 * GB)}
            rg = TrainingRuntimeGuard(
                root / "ckpt",
                clock=clock,
                rss_reader=lambda: rss_box["val"],
                disk_usage_fn=lambda _: _DiskUsage(10 * GB, 5 * GB, disk_box["free"]),
                audit_logger=audit,
                run_id="run-ram",
                step_key="execute_training",
            )
            rg.start()
            ok, reason, snap = rg.check_runtime("before_step", step=1)
            self.assertTrue(ok)
            self.assertIsNone(reason)
            self.assertTrue(snap["soft_warning_triggered"])

            # 3. RAM hard stop -> blocked & audited
            rss_box["val"] = int(3.6 * GB)
            ok, reason, _ = rg.check_runtime("before_checkpoint", step=2, checkpoint_write=True)
            self.assertFalse(ok)
            self.assertEqual(reason, "ram_hard_limit")

            # 4. Disk reserve < 2.0 GB -> disk_reserve_violated
            rss_box["val"] = int(0.5 * GB)
            disk_box["free"] = int(1.5 * GB)
            ok, reason, _ = rg.check_runtime("before_checkpoint", step=3, checkpoint_write=True)
            self.assertFalse(ok)
            self.assertEqual(reason, "disk_reserve_violated")

            # 5. New disk budget (> max_new_disk_gb) -> disk_budget_violated
            disk_box["free"] = int(5.0 * GB)
            ckpt_sub = root / "ckpt_disk_cap"
            ckpt_sub.mkdir(parents=True, exist_ok=True)
            rg_disk = TrainingRuntimeGuard(
                ckpt_sub,
                max_new_disk_gb=0.0001,  # ~104 KB cap
                clock=clock,
                rss_reader=lambda: int(0.5 * GB),
                disk_usage_fn=lambda _: _DiskUsage(10 * GB, 5 * GB, 5 * GB),
                audit_logger=audit,
                run_id="run-ram",
                step_key="execute_training",
            )
            (ckpt_sub / "big_blob.bin").write_bytes(b"x" * 200_000)
            ok, reason, _ = rg_disk.check_runtime("before_checkpoint", step=4, checkpoint_write=True)
            self.assertFalse(ok)
            self.assertEqual(reason, "disk_budget_violated")

            events = {e["event_type"] for e in store.list_audit_logs(run_id="run-ram", limit=50)}
            self.assertTrue(
                {
                    "training.ram_soft_warning",
                    "training.ram_hard_limit",
                    "training.disk_reserve_violated",
                    "training.disk_budget_violated",
                }.issubset(events)
            )

            # 6. AutonomousTrainingLoop returns WAITING_RESOURCE when free disk < 2.0 GB
            loop = AutonomousTrainingLoop(
                checkpoint_dir=root / "ckpt_wait",
                disk_usage_fn=lambda _: _DiskUsage(10 * GB, 9 * GB, int(1.0 * GB)),
            )
            ds = root / "ds"
            ds.mkdir()
            loop_res = loop.run_once(
                {"consumed_approval": {"id": "app-1"}},
                {"dataset_dir": str(ds), "checkpoint_dir": str(root / "ckpt_wait")},
            )
            self.assertEqual(loop_res.status, "WAITING_RESOURCE")
            self.assertEqual(loop_res.verdict, "BLOCKED")
            self.assertEqual(loop_res.evidence["error_code"], "disk_reserve_violated")

    def test_experiment_timeout_and_loop_timeout_stop_cleanly_without_false_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = WorkflowStore(root / "wf.db")
            audit = WorkflowAuditLogger(store)
            clock = _FakeClock(start=1000.0)
            ds = root / "ds"
            ds.mkdir()

            # 1. Experiment timeout > 1200s -> TrainingRuntimeGuard + handle_training_execute map to BLOCKED
            rg = TrainingRuntimeGuard(
                root / "ckpt_exp",
                experiment_timeout_sec=1200.0,
                loop_timeout_sec=3600.0,
                clock=clock,
                rss_reader=lambda: int(0.5 * GB),
                disk_usage_fn=lambda _: _DiskUsage(20 * GB, 5 * GB, 15 * GB),
                audit_logger=audit,
                run_id="run-timeout",
                step_key="execute_training",
            )
            rg.start()
            clock.advance(1205.0)
            ok, reason, _ = rg.check_runtime("before_step", step=10)
            self.assertFalse(ok)
            self.assertEqual(reason, "experiment_timeout")

            def _timed_out_train(*args, **kwargs):
                return {
                    "steps": 10,
                    "stopped_reason": "experiment_timeout",
                    "val_loss": 2.0,
                    "perplexity": 7.38,
                    "parameter_changed": True,
                }

            res = handle_training_execute(
                {"consumed_approval": {"id": "app-1"}, "_train_fn": _timed_out_train, "_model": _FakeModel(ZyrquenConfig())},
                {
                    "checkpoint_dir": str(root / "ckpt_exp_h"),
                    "train_ids": [1, 2, 3, 4],
                    "val_ids": [1, 2, 3, 4],
                    "block_size": 8,
                    "batch_size": 2,
                    "max_steps": 10,
                },
            )
            self.assertEqual(res.verdict, "BLOCKED")
            self.assertEqual(res.error_code, "experiment_timeout")

            # 2. Loop timeout <= 3600s halts multi-experiment loop before starting experiment #3
            loop_clock = _FakeClock(start=5000.0)
            loop = AutonomousTrainingLoop(
                checkpoint_dir=root / "ckpt_loop",
                loop_timeout_sec=3600.0,
                experiment_timeout_sec=1200.0,
                clock=loop_clock,
                rss_reader=lambda: int(0.5 * GB),
                disk_usage_fn=lambda _: _DiskUsage(20 * GB, 5 * GB, 15 * GB),
            )
            executed_count = {"n": 0}

            def _fast_exec(ctx, payload):
                executed_count["n"] += 1
                loop_clock.advance(2000.0)
                return StepExecutionResult(verdict="PASS", summary="step ok")

            experiments = [
                ({"consumed_approval": {"id": f"app-{i}"}}, {"dataset_dir": str(ds), "checkpoint_dir": str(root / f"c{i}")})
                for i in range(4)
            ]
            results = loop.run_experiments(experiments, execute_fn=_fast_exec)
            self.assertEqual(executed_count["n"], 2)
            self.assertEqual(len(results), 3)
            self.assertEqual(results[-1].status, "BLOCKED")
            self.assertEqual(results[-1].evidence["error_code"], "loop_timeout")

            audit_types = {e["event_type"] for e in store.list_audit_logs(run_id="run-timeout", limit=20)}
            self.assertIn("training.experiment_timeout", audit_types)

    def test_torch_probe_is_honest_without_installing_dependencies(self) -> None:
        probe = check_torch_cpu_runtime()
        self.assertIn(probe["status"], ("TORCH_NOT_INSTALLED", "TORCH_AVAILABLE"))
        self.assertIsInstance(probe["available"], bool)


class TestV10CheckpointEvalContractAndIsolation(unittest.TestCase):
    def test_training_hook_writes_version_manifest_copies_tokenizer_isolates_runs_and_evaluates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docs = [{"text": f"native reasoning verify sample {i} plan logic"} for i in range(30)]
            src = root / "corpus.jsonl"
            src.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
            ds_dir = root / "ds"
            prepare_dataset([Source(str(src), "apache-2.0")], ds_dir, PrepConfig(val_fraction=0.2, test_fraction=0.2, version="10.0.0"))

            tok = ZyrquenTokenizer.train([d["text"] for d in docs], BASE_VOCAB + 16, version="10.0.0")
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)
            cfg = ZyrquenConfig(vocab_size=tok.vocab_size, d_ff=704, max_seq_len=64)

            ckpt_dir = root / "ckpt"

            def _fake_train_writes_ckpt(model, train_ids, val_ids, t_cfg, c_dir, log_path, **kwargs):
                cm = CheckpointManager(c_dir, save_fn=_json_save, load_fn=_json_load)
                cm.save(
                    t_cfg.max_steps,
                    {
                        "step": t_cfg.max_steps,
                        "tokenizer_sha256": kwargs.get("tokenizer_fingerprint"),
                        "dataset_version": kwargs.get("dataset_version"),
                        "model_config": cfg.to_dict(),
                        "config": {"max_steps": t_cfg.max_steps},
                    },
                )
                return {
                    "steps": t_cfg.max_steps,
                    "stopped_reason": None,
                    "train_loss": 1.1,
                    "val_loss": 1.2,
                    "perplexity": 3.32,
                    "parameter_changed": True,
                }

            # Run 1 writes manifest.json + version_manifest.json + tokenizer.json
            res1 = handle_training_execute(
                {"run_id": "run-1", "consumed_approval": {"id": "app-1"}, "_train_fn": _fake_train_writes_ckpt, "_model": _FakeModel(cfg)},
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "model_version": "ZYRQUEN-Native-10.0.1",
                    "block_size": 64,
                    "batch_size": 2,
                    "max_steps": 5,
                },
            )
            self.assertEqual(res1.verdict, "PASS", res1.summary)
            self.assertTrue((ckpt_dir / "version_manifest.json").is_file())
            self.assertTrue((ckpt_dir / "tokenizer.json").is_file())
            self.assertEqual(res1.output["model_version"], "ZYRQUEN-Native-10.0.1")

            # Verify handle_evaluation_verify accepts checkpoint_dir directly
            ev_v = handle_evaluation_verify(
                {},
                {"checkpoint_dir": str(ckpt_dir), "model_version": "ZYRQUEN-Native-10.0.1"},
            )
            self.assertEqual(ev_v.verdict, "PASS", ev_v.summary)

            # Verify EvaluationEngine loads from checkpoint_dir version_manifest.json
            eng_ckpt = EvaluationEngine(checkpoint_dir=ckpt_dir, load_fn=_json_load)
            art1 = eng_ckpt._resolve_version_artifacts("ZYRQUEN-Native-10.0.1")
            self.assertEqual(art1["_source"], "versioned_checkpoint")
            self.assertEqual(art1["dataset_version"], "10.0.0")

            # Tamper checkpoint -> verify_version fails & EvaluationEngine raises EvaluationEvidenceError
            vcm = VersionedCheckpointManager(ckpt_dir, load_fn=_json_load)
            rec = vcm.get_version("ZYRQUEN-Native-10.0.1")
            orig_bytes = (ckpt_dir / rec["checkpoint_file"]).read_bytes()
            (ckpt_dir / rec["checkpoint_file"]).write_bytes(b"corrupted")
            self.assertFalse(vcm.verify_version("ZYRQUEN-Native-10.0.1"))
            with self.assertRaises(EvaluationEvidenceError):
                eng_ckpt._resolve_version_artifacts("ZYRQUEN-Native-10.0.1")
            # Restore valid bytes
            (ckpt_dir / rec["checkpoint_file"]).write_bytes(orig_bytes)

            # Also verify ModelRegistry fallback resolution in EvaluationEngine
            reg = ModelRegistry(root / "reg", load_fn=_json_load)
            reg_rec = reg.register("ZYRQUEN-Native-10.0.2", ckpt_dir, tok_path, ds_dir)
            eng_reg = EvaluationEngine(registry_root=root / "reg", load_fn=_json_load)
            art2 = eng_reg._resolve_version_artifacts("ZYRQUEN-Native-10.0.2")
            self.assertEqual(art2["_source"], "model_registry")
            self.assertEqual(art2["checkpoint_sha256"], reg_rec["checkpoint"]["sha256"])

            # Run 2 targeting the same checkpoint_dir must isolate instead of overwriting Run 1
            res2 = handle_training_execute(
                {"run_id": "run-2", "consumed_approval": {"id": "app-2"}, "_train_fn": _fake_train_writes_ckpt, "_model": _FakeModel(cfg)},
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(ckpt_dir),
                    "model_version": "ZYRQUEN-Native-10.0.3",
                    "block_size": 64,
                    "batch_size": 2,
                    "max_steps": 5,
                },
            )
            self.assertEqual(res2.verdict, "PASS", res2.summary)
            self.assertEqual(Path(res2.output["checkpoint_dir"]), ckpt_dir / "run_run-2")
            self.assertTrue(vcm.verify_version("ZYRQUEN-Native-10.0.1"))


class TestV10GovernanceAndAuditHardening(unittest.TestCase):
    def test_paid_gpu_payload_boolean_bypass_is_rejected_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            orch = CentralWorkflowOrchestrator(db_path=Path(td) / "wf.db", work_dir=td, approval_secret="s" * 32)
            try:
                orch.registry.register_handler(
                    "test.gpu",
                    lambda ctx, payload: StepExecutionResult(verdict="PASS", summary="should never run"),
                )
                orch.registry.register_definition(
                    WorkflowDefinition(
                        workflow_key="test.gpu_bypass",
                        version="1.0.0",
                        group_name="training",
                        title="Paid GPU Bypass Test",
                        description="Must reject payload boolean bypass",
                        steps=(
                            WorkflowStepSpec(
                                step_key="gpu",
                                handler_key="test.gpu",
                                description="Paid GPU step",
                                lane="compute_heavy",
                                tier="tier2_approval",
                                action_type="training.execute",
                                requires_paid_gpu=True,
                            ),
                        ),
                    )
                )
                run = orch.trigger_workflow(
                    "test.gpu_bypass",
                    payload={"approved_paid_gpu": True, "use_paid_gpu": True},
                )
                self.assertEqual(run["status"], "BLOCKED")
                events = [e["event_type"] for e in orch.store.list_audit_logs(run_id=run["id"], limit=20)]
                self.assertIn("workflow.paid_gpu_bypass_rejected", events)
            finally:
                orch.shutdown(wait=True)

    def test_approval_binding_rejects_wrong_run_step_scope_and_expired_or_tampered_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WorkflowStore(Path(td) / "wf.db")
            gov = WorkflowGovernance = __import__(
                "apps.core.workflow.governance", fromlist=["WorkflowGovernance"]
            ).WorkflowGovernance(store, secret="b" * 32)
            steps = [{"step_key": "s1", "depends_on": [], "lane": "governance"}]
            run1 = store.create_run(
                workflow_key="w", workflow_version="1", trigger_type="manual", trigger_payload={}, steps=steps
            )[0]["id"]
            run2 = store.create_run(
                workflow_key="w", workflow_version="1", trigger_type="manual", trigger_payload={}, steps=steps
            )[0]["id"]

            spec = WorkflowStepSpec(
                step_key="s1", handler_key="security.audit", action_type="model.promote", lane="governance", tier="tier2_approval"
            )
            pending = gov.ensure_pending_approval(run_id=run1, step=spec, requested_by_user_id="u", scope="model:ZYRQUEN-Native-0.1.0")
            approved = gov.decide_approval(pending["id"], approve=True, approver_user_id="adm", approver_role="admin")

            with self.assertRaises(ApprovalViolationError):
                gov.verify_and_consume_by_id(approved["id"], expected_action_type="model.promote", expected_run_id=run2)
            with self.assertRaises(ApprovalViolationError):
                gov.verify_and_consume_by_id(approved["id"], expected_action_type="model.promote", expected_step_key="other")
            with self.assertRaises(ApprovalViolationError):
                gov.verify_and_consume_by_id(approved["id"], expected_action_type="model.promote", expected_model_version="ZYRQUEN-Native-0.9.0")

            # Expired token fails
            exp_spec = WorkflowStepSpec(
                step_key="s_exp", handler_key="security.audit", action_type="model.promote", lane="governance", tier="tier2_approval"
            )
            past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            rec_exp = store.create_approval_request(
                run_id=run1, step_key="s_exp", action_type="model.promote", scope="model:v1", requested_by_user_id="u", expires_at=past
            )
            with self.assertRaises(ApprovalViolationError):
                gov.decide_approval(rec_exp["id"], approve=True, approver_user_id="adm", approver_role="admin")

            # Audit log rows are strictly append-only in SQLite
            store.append_audit_log(
                actor_id="test",
                event_type="audit.probe",
                resource="res:1",
                decision="ALLOW",
                details={"k": "v"},
                run_id=run1,
            )
            with sqlite3.connect(str(Path(td) / "wf.db")) as conn:
                with self.assertRaises(sqlite3.DatabaseError):
                    conn.execute("UPDATE workflow_audit_logs SET decision = 'TAMPERED'")
                with self.assertRaises(sqlite3.DatabaseError):
                    conn.execute("DELETE FROM workflow_audit_logs")


if __name__ == "__main__":
    unittest.main()
