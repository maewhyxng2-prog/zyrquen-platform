import json
from pathlib import Path

from apps.core.native.checkpoint import VersionedCheckpointManager


def test_save_and_list_versions(tmp_path: Path):
    mgr = VersionedCheckpointManager(tmp_path)
    entry = mgr.save_versioned(
        step=10,
        state={"weights": [1.0, 2.0]},
        model_version="v0.1.0",
        dataset_version="0.1.0",
        dataset_content_hash="abc123",
        config={"hidden": 64},
        val_loss=2.5,
        perplexity=12.0,
    )
    assert entry["model_version"] == "v0.1.0"
    assert entry["dataset_version"] == "0.1.0"
    assert entry["checkpoint_sha256"] != ""
    assert len(mgr.list_versions()) == 1


def test_duplicate_version_rejected(tmp_path: Path):
    mgr = VersionedCheckpointManager(tmp_path)
    mgr.save_versioned(
        step=10,
        state={},
        model_version="v0.1.0",
        dataset_version="0.1.0",
        dataset_content_hash="x",
        config={},
    )
    try:
        mgr.save_versioned(
            step=20,
            state={},
            model_version="v0.1.0",
            dataset_version="0.1.0",
            dataset_content_hash="x",
            config={},
        )
        assert False, "must reject duplicate model versions"
    except ValueError:
        pass


def test_verify_version(tmp_path: Path):
    mgr = VersionedCheckpointManager(tmp_path)
    mgr.save_versioned(
        step=10,
        state={"a": 1},
        model_version="v0.1.0",
        dataset_version="0.1.0",
        dataset_content_hash="x",
        config={},
    )
    assert mgr.verify_version("v0.1.0") is True
    assert mgr.verify_version("v9.9.9") is False


def test_parent_version_chain(tmp_path: Path):
    mgr = VersionedCheckpointManager(tmp_path)
    mgr.save_versioned(
        step=10,
        state={},
        model_version="v0.1.0",
        dataset_version="0.1.0",
        dataset_content_hash="x",
        config={},
    )
    mgr.save_versioned(
        step=20,
        state={},
        model_version="v0.1.1",
        parent_version="v0.1.0",
        dataset_version="0.1.0",
        dataset_content_hash="x",
        config={},
    )
    version = mgr.get_version("v0.1.1")
    assert version["parent_version"] == "v0.1.0"
    assert mgr.latest_version()["model_version"] == "v0.1.1"
