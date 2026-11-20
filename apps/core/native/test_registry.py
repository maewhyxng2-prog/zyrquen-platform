import json

import pytest

from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


def _save(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _env(tmp_path, ds_version="0.1.0", tok_override=None, ds_override=None):
    """Builds a small tokenizer, dataset and checkpoint (JSON-serialised test fixtures)."""
    src = tmp_path / "d.jsonl"
    docs = [{"text": f"เอกสารตัวอย่างที่ {i} for the registry test, document number {i}"} for i in range(60)]
    src.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs), encoding="utf-8")
    ds = tmp_path / "ds"
    prepare_dataset([Source(str(src), "test-declared")], ds,
                    PrepConfig(val_fraction=0.1, test_fraction=0.1, version=ds_version))
    tok = ZyrquenTokenizer.train([d["text"] for d in docs], BASE_VOCAB + 30, version="t1")
    tok_path = tmp_path / "tokenizer.json"
    tok.save(tok_path)
    manifest = json.loads((ds / "manifest.json").read_text(encoding="utf-8"))
    ck = tmp_path / "ck"
    mgr = CheckpointManager(ck, save_fn=_save, load_fn=_load)
    mgr.save(10, {"step": 10, "config": {"lr": 0.001}, "model_config": {"n_layers": 2},
                  "tokenizer_sha256": tok_override or tok.fingerprint(),
                  "dataset_version": ds_override or manifest["version"]})
    return ck, tok_path, ds


def _reg(tmp_path):
    return ModelRegistry(tmp_path / "reg", load_fn=_load)


def test_register_links_everything(tmp_path):
    ck, tok, ds = _env(tmp_path)
    rec = _reg(tmp_path).register("v1", ck, tok, ds, metrics={"val_loss": 3.1})
    assert rec["checkpoint"]["step"] == 10 and rec["tokenizer"]["version"] == "t1"
    assert rec["dataset"]["version"] == "0.1.0" and rec["training_config"] == {"lr": 0.001}
    assert rec["metrics"]["val_loss"] == 3.1
    assert (tmp_path / "reg" / "artifacts" / "v1" / "checkpoint.pt").is_file()
    assert _reg(tmp_path).verify("v1")


def test_duplicate_and_bad_names_rejected(tmp_path):
    ck, tok, ds = _env(tmp_path)
    reg = _reg(tmp_path)
    reg.register("v1", ck, tok, ds)
    with pytest.raises(RegistryError):
        reg.register("v1", ck, tok, ds)
    with pytest.raises(RegistryError):
        reg.register("../evil", ck, tok, ds)
    with pytest.raises(RegistryError):
        reg.register("v2", ck, tok, ds, parent="missing")


def test_tokenizer_mismatch_rejected_and_nothing_left_behind(tmp_path):
    ck, tok, ds = _env(tmp_path, tok_override="0" * 64)
    reg = _reg(tmp_path)
    with pytest.raises(RegistryError):
        reg.register("v1", ck, tok, ds)
    assert reg.list_versions() == [] and not (tmp_path / "reg" / "artifacts" / "v1").exists()


def test_dataset_version_mismatch_rejected(tmp_path):
    ck, tok, ds = _env(tmp_path, ds_override="9.9.9")
    with pytest.raises(RegistryError):
        _reg(tmp_path).register("v1", ck, tok, ds)


def test_tampered_dataset_and_tokenizer_rejected(tmp_path):
    ck, tok, ds = _env(tmp_path)
    (ds / "train.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RegistryError):
        _reg(tmp_path).register("v1", ck, tok, ds)
    (tmp_path / "b").mkdir()
    ck2, tok2, ds2 = _env(tmp_path / "b")
    tok2.write_text(tok2.read_text(encoding="utf-8").replace("[[", "[[9,", 1), encoding="utf-8")
    with pytest.raises(RegistryError):
        _reg(tmp_path / "b").register("v1", ck2, tok2, ds2)


def test_corrupt_checkpoint_rejected(tmp_path):
    ck, tok, ds = _env(tmp_path)
    (ck / "ckpt_00000010.pt").write_text("garbage", encoding="utf-8")
    with pytest.raises(RegistryError):
        _reg(tmp_path).register("v1", ck, tok, ds)


def test_promote_and_rollback(tmp_path):
    ck, tok, ds = _env(tmp_path)
    reg = _reg(tmp_path)
    reg.register("v1", ck, tok, ds)
    reg.register("v2", ck, tok, ds, parent="v1")
    reg.promote("v1")
    reg.promote("v2")
    assert reg.active_version() == "v2"
    assert reg.rollback() == "v1" and reg.active_version() == "v1"
    assert reg.rollback("v2") == "v2"
    with pytest.raises(RegistryError):
        reg.rollback("nope")


def test_corrupted_artifact_blocks_promote_and_rollback(tmp_path):
    ck, tok, ds = _env(tmp_path)
    reg = _reg(tmp_path)
    reg.register("v1", ck, tok, ds)
    reg.register("v2", ck, tok, ds)
    reg.promote("v1")
    reg.promote("v2")
    (tmp_path / "reg" / "artifacts" / "v1" / "checkpoint.pt").write_text("bad", encoding="utf-8")
    assert not reg.verify("v1")
    with pytest.raises(RegistryError):
        reg.rollback()
    assert reg.active_version() == "v2"
    with pytest.raises(RegistryError):
        reg.promote("v1")


def test_rollback_with_no_history(tmp_path):
    ck, tok, ds = _env(tmp_path)
    reg = _reg(tmp_path)
    reg.register("v1", ck, tok, ds)
    reg.promote("v1")
    with pytest.raises(RegistryError):
        reg.rollback()
