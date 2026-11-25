"""Unit tests for KnowledgeTripleStore CRUD, versioning, and Dataset Version manifest linking."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from apps.core.knowledge import (
    DatasetManifestLinkError,
    KnowledgeTripleError,
    KnowledgeTripleStore,
    TripleNotFoundError,
)
from apps.core.native.dataset import SCHEMA


def _create_verified_dataset(root: Path, version: str, suffix: str = "a") -> Path:
    ds_dir = root / version
    ds_dir.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": json.dumps({"input": f"train_{version}_{suffix}", "target": f"out_{suffix}"}) + "\n",
        "validation": json.dumps({"input": f"val_{version}_{suffix}", "target": f"out_{suffix}"}) + "\n",
        "unseen": json.dumps({"input": f"unseen_{version}_{suffix}", "target": f"out_{suffix}"}) + "\n",
        "ood": json.dumps({"input": f"ood_{version}_{suffix}", "target": f"out_{suffix}"}) + "\n",
    }
    files = {}
    hashes = []
    for sp, body in splits.items():
        data = body.encode("utf-8")
        (ds_dir / f"{sp}.jsonl").write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        files[f"{sp}.jsonl"] = {"documents": 1, "sha256": sha}
        hashes.append(sha)
    content_sha = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "dataset": "nagi_v11",
        "version": version,
        "content_sha256": content_sha,
        "files": files,
    }
    (ds_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return ds_dir


class KnowledgeTripleStoreTests(unittest.TestCase):
    def test_crud_versioning_and_dataset_manifest_linkage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ds_root = tmp_path / "datasets"
            _create_verified_dataset(ds_root, "v11.1.0", "first")
            _create_verified_dataset(ds_root, "v11.2.0", "second")

            store = KnowledgeTripleStore(tmp_path / "kg.db", dataset_root=ds_root)
            try:
                created = store.create_triple(
                    "ZYRQUEN",
                    "uses_core",
                    "Native Core",
                    dataset_version="v11.1.0",
                    confidence=0.95,
                    metadata={"domain": "architecture"},
                    actor="admin@zyrquen.local",
                )
                self.assertEqual(created["version"], 1)
                self.assertEqual(created["status"], "active")
                self.assertEqual(created["dataset_version"], "v11.1.0")
                self.assertEqual(len(created["dataset_content_sha256"]), 64)
                self.assertEqual(len(created["dataset_manifest_sha256"]), 64)

                # Verify link is intact
                link_ok = store.verify_triple_manifest_link(created["id"])
                self.assertTrue(link_ok["verified"])

                # Update triple -> increments version and migrates dataset link to v11.2.0
                updated = store.update_triple(
                    created["id"],
                    obj="Native Cognitive Core",
                    dataset_version="v11.2.0",
                    confidence=0.99,
                    actor="curator@zyrquen.local",
                )
                self.assertEqual(updated["version"], 2)
                self.assertEqual(updated["object"], "Native Cognitive Core")
                self.assertEqual(updated["dataset_version"], "v11.2.0")
                self.assertNotEqual(
                    updated["dataset_content_sha256"],
                    created["dataset_content_sha256"],
                )

                # Contradiction detection when adding competing active object
                competing = store.create_triple(
                    "ZYRQUEN",
                    "uses_core",
                    "Legacy Baseline",
                    dataset_version="v11.2.0",
                )
                self.assertEqual(len(competing["contradictions"]), 1)
                self.assertEqual(
                    competing["contradictions"][0]["object"],
                    "Native Cognitive Core",
                )

                # Soft delete preserves version history
                del_res = store.delete_triple(created["id"], actor="admin@zyrquen.local")
                self.assertTrue(del_res["deleted"])
                self.assertEqual(del_res["version"], 3)

                active_list = store.list_triples(dataset_version="v11.2.0")
                self.assertEqual([t["id"] for t in active_list], [competing["id"]])

                all_list = store.list_triples(dataset_version="v11.2.0", include_deleted=True, status=None)
                self.assertEqual(len(all_list), 2)

                history = store.get_triple_history(created["id"])
                self.assertEqual([h["version"] for h in history], [1, 2, 3])
                self.assertEqual(
                    [h["operation"] for h in history],
                    ["create", "update", "soft_delete"],
                )
            finally:
                store.close()

    def test_rejects_missing_or_tampered_dataset_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ds_root = tmp_path / "datasets"
            ds_dir = _create_verified_dataset(ds_root, "v11.1.0")
            store = KnowledgeTripleStore(tmp_path / "kg.db", dataset_root=ds_root)
            try:
                with self.assertRaises(DatasetManifestLinkError):
                    store.create_triple(
                        "A", "rel", "B", dataset_version="v99.0.0"
                    )

                with self.assertRaises(ValueError):
                    store.create_triple(
                        "A", "rel", "B", dataset_version="../escape"
                    )

                created = store.create_triple(
                    "A", "rel", "B", dataset_version="v11.1.0"
                )
                # Tamper split file on disk -> verify_triple_manifest_link & update must detect drift
                (ds_dir / "train.jsonl").write_text('{"input":"tampered","target":"bad"}\n', encoding="utf-8")
                check = store.verify_triple_manifest_link(created["id"])
                self.assertFalse(check["verified"])
                with self.assertRaises(DatasetManifestLinkError):
                    store.update_triple(created["id"], confidence=0.5)

                with self.assertRaises(TripleNotFoundError):
                    store.update_triple("non-existent-id", confidence=0.5)
                with self.assertRaises(KnowledgeTripleError):
                    store.create_triple("   ", "rel", "B", dataset_version="v11.1.0")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
