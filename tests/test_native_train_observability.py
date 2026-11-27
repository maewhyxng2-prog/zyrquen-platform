import json
from pathlib import Path

def test_observability_patch_injection():
    target = Path("apps/core/native/train/__init__.py")
    if not target.is_file():
        target = Path("apps/core/native/train.py")
    content = target.read_text(encoding="utf-8")
    assert "loss_val = loss.item()" in content
    assert "json.dumps(log_data)" in content
    assert "is_finite" in content

def test_log_format_is_valid_json():
    log_data = {
        "step": 10,
        "loss": 0.5,
        "learning_rate": 0.001,
        "is_finite": True
    }
    json_str = json.dumps(log_data)
    parsed = json.loads(json_str)
    assert parsed["step"] == 10
    assert parsed["is_finite"] is True
