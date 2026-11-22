"""Static Contract / Regression Tests for AutonomousTrainingLoop. No real training."""
import inspect
from pathlib import Path

from apps.core.workflow.autonomous_training_loop import (
    AutonomousTrainingLoop,
    build_train_config,
    check_disk_reserve,
    map_verdict_to_status,
    validate_budget,
)

class _FakeResult:
    def __init__(self, verdict, summary="", error_code=None):
        self.verdict = verdict
        self.summary = summary
        self.error_code = error_code

def test_verdict_mapping_matches_implementation_a():
    assert map_verdict_to_status("PASS") == "COMPLETED"
    assert map_verdict_to_status("NOT RUN") == "BLOCKED"
    assert map_verdict_to_status("BLOCKED") == "BLOCKED"
    assert map_verdict_to_status("FAIL") == "FAILED"

def test_budget_rejects_trainconfig_defaults():
    ok, _ = validate_budget(params=1000, seq_len=128, batch_size=16, steps=1000)
    assert not ok

def test_budget_accepts_locked_values():
    ok, reason = validate_budget(params=1000, seq_len=128, batch_size=4, steps=500)
    assert ok, reason

def test_build_train_config_overrides_defaults():
    cfg = build_train_config(block_size=128, batch_size=4, max_steps=500)
    assert cfg.batch_size == 4
    assert cfg.max_steps == 500
    assert cfg.block_size == 128

def test_build_train_config_rejects_over_budget():
    try:
        build_train_config(batch_size=16, max_steps=1000)
    except ValueError:
        return
    raise AssertionError("should reject batch=16 / steps=1000")

def test_save_versioned_is_keyword_only_and_rejects_duplicate():
    from apps.core.native.checkpoint import VersionedCheckpointManager

    sig = inspect.signature(VersionedCheckpointManager.save_versioned)
    step_param = sig.parameters["step"]
    assert step_param.kind == inspect.Parameter.KEYWORD_ONLY
    src = Path(inspect.getfile(VersionedCheckpointManager)).read_text()
    assert "model_version duplicate" in src

def test_training_monitor_is_not_ram_monitor():
    from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor

    names = {n for n, _ in inspect.getmembers(TrainingMonitor, predicate=inspect.isfunction)}
    assert "log" in names and "history" in names and "summary" in names
    assert "start" not in names or "stop" not in names

def test_loop_propagates_not_run_without_claiming_completed(tmp_path):
    loop = AutonomousTrainingLoop(checkpoint_dir=tmp_path)

    def fake_preflight(ctx, payload):
        return _FakeResult("PASS", "ok")

    def fake_execute(ctx, payload):
        return _FakeResult("NOT RUN", "hook not implemented", "training_hook_not_implemented")

    r = loop.run_once(
        {"consumed_approval": {"id": "test"}},
        {"dataset_dir": str(tmp_path), "batch_size": 4, "max_steps": 500, "block_size": 128, "params": 1000},
        preflight_fn=fake_preflight,
        execute_fn=fake_execute,
    )
    assert r.verdict == "NOT RUN"
    assert r.status == "BLOCKED"
    assert r.evidence["error_code"] == "training_hook_not_implemented"

def test_loop_waits_for_tier2_when_no_approval(tmp_path):
    loop = AutonomousTrainingLoop(checkpoint_dir=tmp_path)

    def fake_preflight(ctx, payload):
        return _FakeResult("PASS", "ok")

    r = loop.run_once(
        {},
        {"batch_size": 4, "max_steps": 500, "block_size": 128, "params": 1000},
        preflight_fn=fake_preflight,
        execute_fn=lambda c, p: _FakeResult("PASS", "should not reach"),
    )
    assert r.status == "WAITING_APPROVAL"

def test_disk_guard_reports_free_space(tmp_path):
    ok, info = check_disk_reserve(tmp_path, reserve_gb=0.0)
    assert ok is True
    assert "free_gb" in info
