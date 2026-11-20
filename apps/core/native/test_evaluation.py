from pathlib import Path
from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.evaluation import EvaluationEngine

def _seed(tmp_path: Path):
    mgr = VersionedCheckpointManager(tmp_path)
    mgr.save_versioned(step=10, state={"a": 1}, model_version="v0.1.0",
                       dataset_version="0.1.0", dataset_content_hash="abc",
                       config={"hidden": 64})
    return EvaluationEngine(tmp_path, max_val_loss=5.0, max_perplexity=50.0)

def test_evaluation_pass(tmp_path: Path):
    eng = _seed(tmp_path)
    r = eng.evaluate("v0.1.0", {"val_loss": 2.5, "perplexity": 12.0})
    assert r["model_version"] == "v0.1.0"
    assert r["dataset_version"] == "0.1.0"
    assert r["passed"] is True
    assert (tmp_path / "evaluation_v0.1.0.json").exists()

def test_evaluation_fail_on_high_loss(tmp_path: Path):
    eng = _seed(tmp_path)
    r = eng.evaluate("v0.1.0", {"val_loss": 99.0, "perplexity": 999.0})
    assert r["passed"] is False

def test_evaluation_unknown_version(tmp_path: Path):
    eng = _seed(tmp_path)
    try:
        eng.evaluate("v9.9.9", {"val_loss": 1.0})
        assert False
    except ValueError:
        pass

def test_evaluation_links_dataset(tmp_path: Path):
    eng = _seed(tmp_path)
    r = eng.evaluate("v0.1.0", {"val_loss": 2.0, "perplexity": 10.0})
    assert r["dataset_content_hash"] == "abc"
    assert r["checkpoint_file"] != ""
