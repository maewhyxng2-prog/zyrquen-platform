import hashlib
from pathlib import Path
import zipfile

import pytest

from realitycheck.restoreproof.archive import isolated_zip_extract
from realitycheck.restoreproof.manifest import VerificationError


def make_zip(root: Path, files: dict[str, bytes]):
    path = root / "backup.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, value in files.items():
            zf.writestr(name, value)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_extract_is_temporary_and_reports_archive_digest(tmp_path):
    archive, digest = make_zip(tmp_path, {"dump.bin": b"PGDMP"})
    with isolated_zip_extract(archive, tmp_path / "scratch", digest) as result:
        workspace = result["workspace"]
        assert (workspace / "dump.bin").read_bytes() == b"PGDMP"
        assert result["archive_sha256_before"] == result["archive_sha256_after"] == digest
    assert not workspace.exists()


def test_zip_slip_fails_closed(tmp_path):
    archive, digest = make_zip(tmp_path, {"../outside.txt": b"blocked"})
    with pytest.raises(VerificationError, match="unsafe path") as error:
        with isolated_zip_extract(archive, tmp_path / "scratch", digest):
            pass
    assert error.value.code == "ZIP_SLIP_BLOCKED"
    assert not (tmp_path / "outside.txt").exists()


def test_sha256_mismatch_blocks_before_extraction(tmp_path):
    archive, _ = make_zip(tmp_path, {"dump.bin": b"PGDMP"})
    with pytest.raises(VerificationError) as error:
        with isolated_zip_extract(archive, tmp_path / "scratch", "0" * 64):
            pass
    assert error.value.code == "ZIP_DIGEST_MISMATCH"


def test_expansion_limit_is_enforced(tmp_path):
    archive, digest = make_zip(tmp_path, {"large.bin": b"x" * 4096})
    with pytest.raises(VerificationError) as error:
        with isolated_zip_extract(archive, tmp_path / "scratch", digest, max_extracted_bytes=1024):
            pass
    assert error.value.code == "ZIP_EXPANSION_LIMIT"


def test_sync_drift_blocks_result(tmp_path, monkeypatch):
    archive, digest = make_zip(tmp_path, {"dump.bin": b"PGDMP"})
    from realitycheck.restoreproof import archive as module
    original = module.sha256_file
    calls = 0

    def changed(path):
        nonlocal calls
        calls += 1
        return original(path) if calls == 1 else "f" * 64

    monkeypatch.setattr(module, "sha256_file", changed)
    with pytest.raises(VerificationError) as error:
        with isolated_zip_extract(archive, tmp_path / "scratch", digest):
            pass
    assert error.value.code == "ZIP_SYNC_DRIFT"
