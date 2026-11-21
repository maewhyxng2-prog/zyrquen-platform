from phases.phase12 import CapabilityRegistry, LocalRuleProvider, NativeIntelligence

def test_architecture_is_isolated():
    ni = NativeIntelligence()
    out = ni.handle({"type": "summarize_text", "text": "hello world"})
    assert out["status"] == "ok"
    assert out["result"] == "hello world"

def test_interfaces_provider_contract():
    p = LocalRuleProvider()
    assert p.name() == "local_rule"
    assert "summarize_text" in p.capabilities()
    assert p.can_handle({"type": "summarize_text"}) is True
    assert p.can_handle({"type": "train_model"}) is False

def test_capability_available():
    reg = CapabilityRegistry()
    reg.register(LocalRuleProvider())
    s = reg.get_status("summarize_text")
    assert s["status"] == "available"

def test_capability_blocked_is_not_fake_success():
    reg = CapabilityRegistry()
    reg.register(LocalRuleProvider())
    for cap in ["train_model", "load_weights", "external_ai"]:
        s = reg.get_status(cap)
        assert s["status"] == "blocked"
        assert "reason" in s and s["reason"]

def test_capability_not_available():
    reg = CapabilityRegistry()
    reg.register(LocalRuleProvider())
    s = reg.get_status("do_magic")
    assert s["status"] == "not_available"

def test_native_intelligence_blocks_unsupported():
    ni = NativeIntelligence()
    out = ni.handle({"type": "train_model"})
    assert out["status"] == "blocked"
    assert out["result"] is None
