"""Hook tests — Mock train(), no real training, no torch training."""
from apps.core.workflow.handlers.groups import handle_training_execute

def _ctx(fake_train=None, model=None):
    c = {"consumed_approval": {"id": "test-tier2"}}
    if fake_train is not None:
        c["_train_fn"] = fake_train
    if model is not None:
        c["_model"] = model
    return c

def _payload(tmp_path, **kw):
    d = {"checkpoint_dir": str(tmp_path), "train_ids": [1,2,3,4,5,6,7,8], "val_ids": [1,2,3,4], "batch_size": 4, "max_steps": 10, "block_size": 8}
    d.update(kw)
    return d

class _FakeModel:
    pass

def test_hook_requires_approval(tmp_path):
    r = handle_training_execute({}, _payload(tmp_path))
    assert r.verdict == "NOT RUN"
    assert r.error_code == "approval_required"

def test_hook_rejects_over_budget(tmp_path):
    def fake_train(*a, **k):
        raise AssertionError("should not train when over budget")
    r = handle_training_execute(_ctx(fake_train, _FakeModel()), _payload(tmp_path, batch_size=16, max_steps=1000))
    assert r.verdict == "BLOCKED"
    assert r.error_code == "budget_violated"

def test_hook_passes_on_mock_train_success(tmp_path):
    def fake_train(model, train_ids, val_ids, cfg, ckpt, log, device="cpu", **kw):
        assert cfg.batch_size == 4 and cfg.max_steps == 10
        return {"steps": 10, "stopped_reason": None, "val_loss": 2.5, "perplexity": 12.1, "parameter_changed": True}
    r = handle_training_execute(_ctx(fake_train, _FakeModel()), _payload(tmp_path))
    assert r.verdict == "PASS", r.summary
    assert "val_loss=2.5" in r.summary

def test_hook_fails_on_diverged(tmp_path):
    def fake_train(*a, **k):
        return {"steps": 5, "stopped_reason": "loss_diverged", "val_loss": 99.0, "perplexity": None, "parameter_changed": True}
    r = handle_training_execute(_ctx(fake_train, _FakeModel()), _payload(tmp_path))
    assert r.verdict == "FAIL"
    assert r.error_code == "loss_diverged"

def test_hook_fails_on_no_param_change(tmp_path):
    def fake_train(*a, **k):
        return {"steps": 10, "stopped_reason": None, "val_loss": 2.5, "perplexity": 12.0, "parameter_changed": False}
    r = handle_training_execute(_ctx(fake_train, _FakeModel()), _payload(tmp_path))
    assert r.verdict == "FAIL"
    assert r.error_code == "training_no_change"

def test_hook_blocks_without_tokenizer_when_no_ids(tmp_path):
    p = {"checkpoint_dir": str(tmp_path), "dataset_dir": str(tmp_path), "batch_size": 4, "max_steps": 10, "block_size": 8}
    r = handle_training_execute(_ctx(lambda *a, **k: {}, _FakeModel()), p)
    assert r.verdict == "BLOCKED"
    assert r.error_code == "tokenizer_missing"

def test_hook_propagates_train_exception_as_fail(tmp_path):
    def fake_train(*a, **k):
        raise RuntimeError("boom")
    r = handle_training_execute(_ctx(fake_train, _FakeModel()), _payload(tmp_path))
    assert r.verdict == "FAIL"
    assert r.error_code == "training_failed"
