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
