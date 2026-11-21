import json
import math
from pathlib import Path

from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.evaluation import (
    EvaluationEngine,
    EvaluationEvidenceError,
    EvaluationNotConfiguredError,
    calculate_perplexity,
    calculate_token_accuracy,
)
from apps.core.native.evaluation.engine import EvaluationEngine as EngineFromSubmodule


def _build_dataset(tmp_path: Path, version: str = "0.1.0") -> tuple[Path, str]:
    src = tmp_path / "corpus.jsonl"
    docs = [
        {"text": f"เอกสารทดสอบที่ {i} และตัวอย่างข้อความภาษาอังกฤษ sample document {i}"}
        for i in range(60)
    ]
    src.write_text(
        "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs),
        encoding="utf-8",
    )
    ds_dir = tmp_path / "dataset"
    report = prepare_dataset(
        [Source(str(src), "test-declared")],
        ds_dir,
        PrepConfig(val_fraction=0.2, test_fraction=0.2, version=version),
    )
    return ds_dir, report.manifest["content_sha256"]


def _seed(tmp_path: Path, dataset_content_hash: str = "abc"):
    mgr = VersionedCheckpointManager(tmp_path)
    mgr.save_versioned(
        step=10,
        state={"a": 1},
        model_version="v0.1.0",
        dataset_version="0.1.0",
        dataset_content_hash=dataset_content_hash,
        config={"hidden": 64},
    )
    return EvaluationEngine(tmp_path, max_val_loss=5.0, max_perplexity=50.0)


def test_package_does_not_shadow_module():
    shadow_file = Path(__file__).resolve().parent / "evaluation.py"
    assert not shadow_file.exists()
    assert EvaluationEngine is EngineFromSubmodule


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


def test_evaluation_rejects_unconfigured_engine():
    eng = EvaluationEngine()
    assert eng.get_status()["status"] == "not_configured"
    for call in (
        lambda: eng.evaluate("v0.1.0", {"val_loss": 1.0}),
        lambda: eng.run_evaluation("v0.1.0"),
    ):
        try:
            call()
            assert False
        except EvaluationNotConfiguredError:
            pass


def test_evaluation_rejects_missing_or_invalid_metrics(tmp_path: Path):
    eng = _seed(tmp_path)
    for bad_metrics in ({}, {"val_loss": True}):
        try:
            eng.evaluate("v0.1.0", bad_metrics)
            assert False
        except EvaluationEvidenceError:
            pass


def test_evaluation_rejects_tampered_checkpoint(tmp_path: Path):
    eng = _seed(tmp_path)
    ckpt_files = list(tmp_path.glob("ckpt_*.pt"))
    assert len(ckpt_files) == 1
    ckpt_files[0].write_bytes(b"corrupted-weights")
    try:
        eng.evaluate("v0.1.0", {"val_loss": 2.0, "perplexity": 10.0})
        assert False
    except EvaluationEvidenceError:
        pass


def test_evaluation_verifies_dataset_and_rejects_tampering(tmp_path: Path):
    ds_dir, checksum = _build_dataset(tmp_path)
    ckpt_dir = tmp_path / "ckpt"
    eng = _seed(ckpt_dir, dataset_content_hash=checksum)

    res = eng.evaluate(
        "v0.1.0",
        {"val_loss": 2.0, "perplexity": 10.0},
        dataset_dir=ds_dir,
        dataset_checksum=checksum,
    )
    assert res["passed"] is True
    assert res["dataset_content_hash"] == checksum

    try:
        eng.evaluate(
            "v0.1.0",
            {"val_loss": 2.0, "perplexity": 10.0},
            dataset_dir=ds_dir,
            dataset_checksum="0" * 64,
        )
        assert False
    except EvaluationEvidenceError:
        pass

    (ds_dir / "validation.jsonl").write_text('{"text": "tampered"}\n', encoding="utf-8")
    try:
        eng.evaluate(
            "v0.1.0",
            {"val_loss": 2.0, "perplexity": 10.0},
            dataset_dir=ds_dir,
        )
        assert False
    except EvaluationEvidenceError:
        pass


def test_run_evaluation_rejects_missing_dataset_and_unwired_inference(tmp_path: Path):
    ds_dir, checksum = _build_dataset(tmp_path)
    ckpt_dir = tmp_path / "ckpt"
    eng = _seed(ckpt_dir, dataset_content_hash=checksum)

    try:
        eng.run_evaluation("v0.1.0")
        assert False
    except EvaluationEvidenceError:
        pass

    try:
        eng.run_evaluation("v0.1.0", dataset_dir=ds_dir, dataset_checksum=checksum)
        assert False
    except EvaluationNotConfiguredError:
        pass


def test_metrics_reject_invalid_inputs():
    assert math.isclose(calculate_perplexity(0.0), 1.0)
    assert math.isclose(calculate_token_accuracy([1, 2, 3], [1, 0, 3]), 2 / 3)
    for bad_loss in (-0.1, float("nan"), float("inf"), True):
        try:
            calculate_perplexity(bad_loss)
            assert False
        except ValueError:
            pass
    for preds, targets in (([], []), ([1], [1, 2])):
        try:
            calculate_token_accuracy(preds, targets)
            assert False
        except ValueError:
            pass

