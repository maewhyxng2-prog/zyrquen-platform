# Phase 4.3 - ของจริงเท่านั้น ห้ามจำลอง
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager

def test_real_save_and_load_latest(tmp_path):
    mgr = CheckpointManager(tmp_path, keep_last=3)
    assert mgr.load_latest() is None
    assert mgr.latest_valid() is None
    p = mgr.save(10, {"weights": [1.0, 2.0], "step": 10})
    assert p.exists()
    assert mgr.manifest_path.exists()
    step, state = mgr.load_latest()
    assert step == 10
    assert state == {"weights": [1.0, 2.0], "step": 10}

def test_real_verify_true_for_valid(tmp_path):
    mgr = CheckpointManager(tmp_path, keep_last=3)
    mgr.save(10, {"a": 1})
    entry = mgr.latest_valid()
    assert entry is not None
    assert mgr.verify(entry) is True

def test_real_verify_false_after_tamper(tmp_path):
    mgr = CheckpointManager(tmp_path, keep_last=3)
    p = mgr.save(10, {"a": 1})
    entry = mgr.latest_valid()
    assert mgr.verify(entry) is True
    data = p.read_bytes() + b"tamper"
    p.write_bytes(data)
    assert mgr.verify(entry) is False
    assert mgr.latest_valid() is None

def test_real_keep_last_prunes(tmp_path):
    mgr = CheckpointManager(tmp_path, keep_last=2)
    mgr.save(1, {"v": 1})
    mgr.save(2, {"v": 2})
    mgr.save(3, {"v": 3})
    step, state = mgr.load_latest()
    assert step == 3
    assert state == {"v": 3}
    files = [x for x in tmp_path.iterdir() if x.name != "manifest.json" and not x.name.endswith(".tmp")]
    assert len(files) <= 2


def test_checkpoint_defaults_to_weights_only_true_and_rejects_symlinks(tmp_path):
    import inspect
    import os
    from apps.core.native.registry import ModelRegistry
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import _safe_torch_load

    mgr = CheckpointManager(tmp_path)
    assert mgr._load is _safe_torch_load
    assert mgr._allow_unsafe_pickle is False
    assert "weights_only=True" in inspect.getsource(_safe_torch_load)

    reg = ModelRegistry(tmp_path / "registry")
    assert reg._load is _safe_torch_load

    # Tampered SHA-256 must be rejected before _load runs.
    called = []
    guarded = CheckpointManager(tmp_path / "guarded", save_fn=lambda obj, p: open(p, "w").write("ok"),
                                load_fn=lambda p: called.append(p) or {"step": 1})
    ckpt = guarded.save(1, {"step": 1})
    ckpt.write_text("tampered", encoding="utf-8")
    assert guarded.load_latest() is None
    assert called == []

    # Symlinked checkpoint must be rejected by verify() and load_latest().
    sym_mgr = CheckpointManager(tmp_path / "sym", save_fn=lambda obj, p: open(p, "w").write("ok"),
                                load_fn=lambda p: called.append(p) or {"step": 1})
    sym_ckpt = sym_mgr.save(1, {"step": 1})
    outside = tmp_path / "outside.pt"
    outside.write_bytes(sym_ckpt.read_bytes())
    sym_ckpt.unlink()
    os.symlink(outside, sym_ckpt)
    assert sym_mgr.latest_valid() is None
    assert sym_mgr.load_latest() is None
    assert called == []


def test_rng_state_capture_and_restore_supports_resume_formats():
    import random
    from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
        capture_rng_state,
        restore_rng_state,
    )

    state = capture_rng_state()
    expected = random.random()

    # Tuple format (direct pickle / torch.load)
    restore_rng_state(state)
    assert random.random() == expected

    # List-serialized Python RNG tuple format
    v, internal, gauss = state["python"]
    restore_rng_state({"python": [v, list(internal), gauss]})
    assert random.random() == expected


def test_unsafe_pickle_fallback_is_permanently_disabled(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="legacy pickle loading is prohibited"):
        CheckpointManager(tmp_path, allow_unsafe_pickle=True)
