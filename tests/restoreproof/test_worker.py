import hashlib
import json
from pathlib import Path

import pytest

from realitycheck.restoreproof.manifest import VerificationError, verify_artifact
from realitycheck.restoreproof.report import build_report


def _fixture(tmp_path: Path):
    backup = tmp_path / "sample.dump"
    backup.write_bytes(b"PGDMP" + b"fixture-data")
    manifest = tmp_path / "sample.manifest.json"
    manifest.write_text(json.dumps({
        "schema": "realitycheck.restoreproof.manifest.v1",
        "filename": backup.name,
        "size_bytes": backup.stat().st_size,
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    return backup, manifest


def test_valid_manifest_verifies_artifact(tmp_path):
    backup, manifest = _fixture(tmp_path)
    result = verify_artifact(backup, manifest)
    assert result["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()


def test_digest_mismatch_fails_before_restore(tmp_path):
    backup, manifest = _fixture(tmp_path)
    data = json.loads(manifest.read_text())
    data["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data))
    with pytest.raises(VerificationError, match="SHA-256"):
        verify_artifact(backup, manifest)


def test_missing_manifest_fails_closed(tmp_path):
    backup, _ = _fixture(tmp_path)
    with pytest.raises(VerificationError) as error:
        verify_artifact(backup, tmp_path / "missing.json")
    assert error.value.code == "MANIFEST_MISSING"


def test_wrong_dump_format_rejected(tmp_path):
    backup, manifest = _fixture(tmp_path)
    backup.write_bytes(b"not-a-postgres-dump")
    data = json.loads(manifest.read_text())
    data["size_bytes"] = backup.stat().st_size
    data["sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data))
    with pytest.raises(VerificationError) as error:
        verify_artifact(backup, manifest)
    assert error.value.code == "UNSUPPORTED_DUMP_FORMAT"


def test_pass_cannot_be_issued_without_checks_or_cleanup():
    report = build_report("run", "2026-01-01T00:00:00Z", None, [], "PASS", [], {"status": "NOT_RUN"})
    assert report["verdict"] == "BLOCKED"
    assert report["artifact"] is None
