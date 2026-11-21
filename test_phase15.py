from phase15 import ModelConfig, ModelRegistry, check_compatibility

def test_model_config_creates():
    c = ModelConfig(vocab=32000, hidden=256, layers=4, kv_cache_size=1024)
    assert c.to_dict()["kv_cache_size"] == 1024

def test_compatibility_pass():
    c = ModelConfig(vocab=32000, hidden=256, layers=4)
    out = check_compatibility(c, {"vocab": 32000, "hidden": 256, "layers": 4})
    assert out["compatible"] is True

def test_compatibility_blocked_when_mismatch():
    c = ModelConfig(vocab=32000, hidden=256, layers=4)
    out = check_compatibility(c, {"vocab": 32000, "hidden": 512, "layers": 4})
    assert out["compatible"] is False
    assert "hidden" in out["reason"]

def test_lifecycle_register_validate_promote():
    r = ModelRegistry()
    assert r.register_model("v0.1", "ckpt-001", ModelConfig())["status"] == "registered"
    assert r.validate("v0.1")["status"] == "validated"
    assert r.promote("v0.1")["status"] == "promoted"
    assert r.get("v0.1")["status"] == "promoted"

def test_lifecycle_no_auto_promotion_without_validation():
    r = ModelRegistry()
    r.register_model("v0.2", "ckpt-002", ModelConfig())
    out = r.promote("v0.2")
    assert out["status"] == "blocked"
    assert "validate" in out["reason"]

def test_lifecycle_rollback():
    r = ModelRegistry()
    r.register_model("v0.3", "ckpt-003", ModelConfig())
    r.validate("v0.3")
    r.promote("v0.3")
    out = r.rollback("v0.3", reason="bad eval")
    assert out["status"] == "rolled_back"
    assert r.get("v0.3")["reason"] == "bad eval"
