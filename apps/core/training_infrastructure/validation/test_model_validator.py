# Phase 4.6 - ของจริงเท่านั้น ห้ามจำลอง
# checkpoint จริงจาก CheckpointManager + tmp_path จริง + validate() ตัวจริง
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager
from apps.core.training_infrastructure.validation.model_validator import ModelValidator

def test_real_valid_checkpoint_and_metrics_pass(tmp_path):
    CheckpointManager(tmp_path).save(10, {"weights": [1.0, 2.0]})
    v = ModelValidator(max_val_loss=5.0, max_perplexity=50.0)
    r = v.validate(tmp_path, {"val_loss": 2.5, "perplexity": 12.0})
    assert r.passed is True

def test_real_no_checkpoint_fails_integrity(tmp_path):
    v = ModelValidator(max_val_loss=5.0, max_perplexity=50.0)
    r = v.validate(tmp_path, {"val_loss": 2.5, "perplexity": 12.0})
    assert r.passed is False

def test_real_high_val_loss_fails_threshold(tmp_path):
    CheckpointManager(tmp_path).save(10, {"a": 1})
    v = ModelValidator(max_val_loss=5.0, max_perplexity=50.0)
    r = v.validate(tmp_path, {"val_loss": 99.0, "perplexity": 12.0})
    assert r.passed is False

def test_real_high_perplexity_fails_threshold(tmp_path):
    CheckpointManager(tmp_path).save(10, {"a": 1})
    v = ModelValidator(max_val_loss=5.0, max_perplexity=50.0)
    r = v.validate(tmp_path, {"val_loss": 2.5, "perplexity": 999.0})
    assert r.passed is False
