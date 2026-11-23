"""Pure-stdlib unit tests for Dataset Pipeline Status & Integrity Inspector."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from apps.core.native.dataset import SCHEMA
from apps.core.native.dataset_status import (
    get_dataset_version_status,
    get_datasets_pipeline_status,
    inspect_dataset_directory,
    inspect_v11_training_dataset_readiness,
    validate_dataset_version,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_dataset_dir(
    root: Path,
    *,
    version: str,
    split_rows: dict[str, list[dict]],
    dataset_name: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    hashes: list[str] = []
    for split, rows in split_rows.items():
        content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
        (root / f"{split}.jsonl").write_bytes(content)
        sha = _sha256_bytes(content)
        files[f"{split}.jsonl"] = {"documents": len(rows), "sha256": sha}
        hashes.append(sha)

    content_sha = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "version": version,
        "content_sha256": content_sha,
        "sources": {
            "synthetic_unit": {"license": "CC-BY-4.0", "sha256": content_sha},
        },
        "files": files,
    }
    if dataset_name:
        manifest["dataset"] = dataset_name
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


class DatasetStatusApiTests(unittest.TestCase):
    def test_unconfigured_paths_report_not_configured(self) -> None:
        prev_dir = os.environ.pop("ZYRQUEN_DATASET_DIR", None)
        prev_root = os.environ.pop("ZYRQUEN_DATASET_ROOT", None)
        try:
            res = get_datasets_pipeline_status()
            self.assertFalse(res["configured"])
            self.assertEqual(res["status"], "not_configured")
            self.assertIsNone(res["active_dataset"])
            self.assertEqual(res["datasets"], [])
            with self.assertRaises(RuntimeError):
                get_dataset_version_status("0.1.0")
        finally:
            if prev_dir is not None:
                os.environ["ZYRQUEN_DATASET_DIR"] = prev_dir
            if prev_root is not None:
                os.environ["ZYRQUEN_DATASET_ROOT"] = prev_root

    def test_valid_v10_three_split_manifest_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ds_dir = _write_dataset_dir(
                Path(tmp) / "v0.1.0",
                version="0.1.0",
                split_rows={
                    "train": [{"input": "hello TR_E1", "target": "ok TR_E1"}],
                    "validation": [{"input": "val VA_E1", "target": "ok VA_E1"}],
                    "test": [{"input": "test TE_E1", "target": "ok TE_E1"}],
                },
            )
            status = get_datasets_pipeline_status(dataset_dir=ds_dir)
            self.assertTrue(status["configured"])
            self.assertEqual(status["status"], "ready")
            active = status["active_dataset"]
            self.assertTrue(active["verified"])
            self.assertEqual(active["status"], "verified")
            self.assertEqual(active["format"], "sft")
            self.assertEqual(active["splits"], ["train", "validation", "test"])
            self.assertEqual(active["v11_leakage_check"]["status"], "NOT RUN")

    def test_valid_v11_four_split_manifest_passes_leakage_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "datasets"
            _write_dataset_dir(
                root / "nagi_v11",
                version="nagi_v11",
                dataset_name="nagi_v11",
                split_rows={
                    "train": [{"input": "train rule TR_E101", "target": "ans TR_E101", "split": "train"}],
                    "validation": [{"input": "val rule VA_E202", "target": "ans VA_E202", "split": "validation"}],
                    "unseen": [{"input": "unseen rule UN_E303", "target": "ans UN_E303", "split": "unseen"}],
                    "ood": [{"input": "ood rule OO_E404", "target": "ans OO_E404", "split": "ood"}],
                },
            )
            ver = get_dataset_version_status("nagi_v11", dataset_root=root)
            self.assertTrue(ver["verified"])
            self.assertEqual(ver["status"], "verified")
            self.assertEqual(ver["splits"], ["train", "validation", "unseen", "ood"])
            self.assertEqual(ver["v11_leakage_check"]["status"], "PASS")

    def test_corrupted_split_file_fails_integrity_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ds_dir = _write_dataset_dir(
                Path(tmp) / "broken",
                version="0.1.0",
                split_rows={
                    "train": [{"text": "clean train text here"}],
                    "validation": [{"text": "clean val text here"}],
                    "test": [{"text": "clean test text here"}],
                },
            )
            (ds_dir / "train.jsonl").write_text('{"text": "tampered"}\n', encoding="utf-8")
            status = get_datasets_pipeline_status(dataset_dir=ds_dir)
            self.assertTrue(status["configured"])
            self.assertEqual(status["status"], "invalid")
            self.assertFalse(status["active_dataset"]["verified"])
            self.assertEqual(status["active_dataset"]["status"], "invalid")

    def test_v11_entity_leakage_marks_leakage_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ds_dir = _write_dataset_dir(
                Path(tmp) / "leaked_v11",
                version="nagi_v11",
                dataset_name="nagi_v11",
                split_rows={
                    "train": [{"input": "train uses TR_E999", "target": "TR_E999 ok", "split": "train"}],
                    "validation": [{"input": "val uses VA_E202", "target": "VA_E202 ok", "split": "validation"}],
                    "unseen": [{"input": "unseen leaks TR_E999", "target": "TR_E999 leak", "split": "unseen"}],
                    "ood": [{"input": "ood uses OO_E404", "target": "OO_E404 ok", "split": "ood"}],
                },
            )
            report = inspect_dataset_directory(ds_dir)
            self.assertTrue(report["verified"])
            self.assertEqual(report["status"], "leakage_failed")
            self.assertEqual(report["v11_leakage_check"]["status"], "FAIL")
            self.assertTrue(report["v11_leakage_check"]["violations"])

    def test_rejects_path_traversal_and_symlinks(self) -> None:
        for bad in ["../secret", "v1..2", "/etc/passwd", "bad/version", ""]:
            with self.assertRaises(ValueError):
                validate_dataset_version(bad)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            link = root / "linked"
            link.symlink_to(outside)
            with self.assertRaises(ValueError):
                inspect_dataset_directory(link, allowed_root=root)

    def test_v11_training_readiness_enforces_four_split_and_leakage_detection(self) -> None:
        unconfigured = inspect_v11_training_dataset_readiness(None)
        self.assertFalse(unconfigured["configured"])
        self.assertFalse(unconfigured["verified"])
        self.assertTrue(unconfigured["four_split_enforced"])

        with tempfile.TemporaryDirectory() as tmp:
            ds_v10 = _write_dataset_dir(
                Path(tmp) / "v10",
                version="0.1.0",
                split_rows={
                    "train": [{"input": "hello TR_E1", "target": "ok TR_E1"}],
                    "validation": [{"input": "val VA_E1", "target": "ok VA_E1"}],
                    "test": [{"input": "test TE_E1", "target": "ok TE_E1"}],
                },
            )
            res_v10 = inspect_v11_training_dataset_readiness(ds_v10)
            self.assertTrue(res_v10["configured"])
            self.assertFalse(res_v10["four_split_present"])
            self.assertFalse(res_v10["verified"])
            self.assertTrue(any("4-split" in r for r in res_v10["reasons"]))

            ds_leaked = _write_dataset_dir(
                Path(tmp) / "v11_leak",
                version="nagi_v11",
                dataset_name="nagi_v11",
                split_rows={
                    "train": [{"input": "rule TR_E77", "target": "TR_E77", "split": "train"}],
                    "validation": [{"input": "rule VA_E2", "target": "VA_E2", "split": "validation"}],
                    "unseen": [{"input": "rule TR_E77", "target": "TR_E77", "split": "unseen"}],
                    "ood": [{"input": "rule OO_E4", "target": "OO_E4", "split": "ood"}],
                },
            )
            res_leak = inspect_v11_training_dataset_readiness(ds_leaked)
            self.assertTrue(res_leak["four_split_present"])
            self.assertFalse(res_leak["verified"])
            self.assertFalse(res_leak["leakage_check"]["passed"])

            ds_clean = _write_dataset_dir(
                Path(tmp) / "v11_clean",
                version="nagi_v11",
                dataset_name="nagi_v11",
                split_rows={
                    "train": [{"input": "rule TR_E101", "target": "TR_E101 ok", "split": "train"}],
                    "validation": [{"input": "rule VA_E202", "target": "VA_E202 ok", "split": "validation"}],
                    "unseen": [{"input": "rule UN_E303", "target": "UN_E303 ok", "split": "unseen"}],
                    "ood": [{"input": "rule OO_E404", "target": "OO_E404 ok", "split": "ood"}],
                },
            )
            res_clean = inspect_v11_training_dataset_readiness(ds_clean)
            self.assertTrue(res_clean["configured"])
            self.assertTrue(res_clean["four_split_present"])
            self.assertTrue(res_clean["verified"])
            self.assertTrue(res_clean["leakage_check"]["passed"])
            self.assertEqual(res_clean["reasons"], [])


if __name__ == "__main__":
    unittest.main()
