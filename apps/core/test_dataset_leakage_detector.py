"""Unit and ingestion integration tests for apps.core.dataset_leakage_detector."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from apps.core.dataset_leakage_detector import (
    DatasetLeakageDetector,
    SemanticHashLeakageError,
    prevent_ingestion_leakage,
)

try:
    from apps.core.native.dataset_status import ingest_v11_dataset
    from apps.core.native.dataset_v11 import DatasetLeakageError

    _HAS_V11_INGEST = True
except ModuleNotFoundError:
    ingest_v11_dataset = None  # type: ignore[assignment]
    DatasetLeakageError = ValueError  # type: ignore[assignment,misc]
    _HAS_V11_INGEST = False


class DatasetLeakageDetectorTests(unittest.TestCase):
    def test_exact_and_near_duplicate_simhash_detection_english_and_thai(self) -> None:
        detector = DatasetLeakageDetector()
        current_splits = {
            "train": [
                {"text": "SQLite WAL mode maintains concurrent readers while serializing atomic checkpoint writes cleanly."},
                {"text": "ระบบ ZYRQUEN บันทึกประวัติการตรวจสอบและแฮช SHA-256 ของชุดข้อมูลทุกเวอร์ชันอย่างถาวร"},
            ],
            "validation": [
                {"input": "verify checkpoint immutability", "target": "ensure historical baseline weights never overwrite"},
            ],
        }

        new_entries = [
            # Exact normalized duplicate (case + extra whitespace) against train
            {"text": "  sqlite wal mode maintains concurrent readers while serializing atomic checkpoint writes cleanly. "},
            # Semantic near-duplicate paraphrase (SimHash) against Thai train entry
            {"text": "ระบบ ZYRQUEN จะบันทึกประวัติการตรวจสอบพร้อมแฮช SHA-256 ของชุดข้อมูลทุกเวอร์ชันอย่างถาวรเสมอ"},
            # Paraphrase against validation SFT pair
            {"input": "verify checkpoint immutability policy", "target": "ensure historical baseline weights never overwrite"},
            # Completely unrelated clean record
            {"text": "PostgreSQL implements multi-version concurrency control across isolated analytics transactions."},
        ]

        report = detector.check_entries(
            new_entries,
            reference_splits=current_splits,
            raise_on_leakage=False,
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.status, "FAIL")
        self.assertEqual(report.new_records_scanned, 4)
        self.assertEqual(report.reference_records_scanned, 3)
        self.assertGreaterEqual(report.exact_matches, 1)
        self.assertGreaterEqual(report.near_duplicate_matches, 1)
        match_types = {m.match_type for m in report.matches}
        self.assertIn("exact_semantic_hash", match_types)
        self.assertIn("simhash_near_duplicate", match_types)
        flagged_indices = {m.new_index for m in report.matches}
        self.assertEqual(flagged_indices, {0, 1, 2})

    def test_structural_semantic_hash_catches_slot_swapped_records_without_short_false_positives(self) -> None:
        detector = DatasetLeakageDetector()
        refs = {
            "train": [
                {"text": "Billing settlement batch 44019 completed verification in zone us-east-1."},
                {"text": "rule TR_E11"},
            ],
            "val": [
                {"text": "rule VA_E22"},
            ],
        }
        incoming = {
            "unseen": [
                {"text": "Billing settlement batch 99812 completed verification in zone us-east-1."},
                {"text": "rule UN_E33"},
                {"text": "Quantum error correction relies on syndrome decoding over stabilizer lattices."},
            ]
        }
        report = detector.check_entries(incoming, reference_splits=refs)
        self.assertFalse(report.passed)
        flagged_indices = {m.new_index for m in report.matches}
        self.assertEqual(flagged_indices, {0})

    def test_clean_distinct_corpus_passes_and_prevent_helper_fail_closed(self) -> None:
        refs = {
            "train": [
                "Symbolic AST arithmetic evaluates nested mathematical expressions deterministically.",
            ],
            "validation": [
                "Topological DAG planning detects cyclic step dependencies prior to execution.",
            ],
        }
        clean_entries = [
            "Cryptographic audit logs track every administrative approval decision immutably.",
            "Byte-level BPE tokenization encodes arbitrary UTF-8 strings without unknown tokens.",
        ]
        report = prevent_ingestion_leakage(clean_entries, reference_splits=refs)
        self.assertTrue(report.passed)
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.violations, [])

        leaked_entries = [
            "Symbolic AST arithmetic evaluates nested mathematical expressions deterministically!",
        ]
        with self.assertRaises(SemanticHashLeakageError):
            prevent_ingestion_leakage(leaked_entries, reference_splits=refs)

    def test_loads_from_disk_directories_and_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 1. Directory loading check (train.jsonl + validation.jsonl)
            ds_dir = tmp_path / "ds_v1"
            ds_dir.mkdir()
            (ds_dir / "train.jsonl").write_text(
                json.dumps({"text": "Deterministic BPE tokenizers guarantee reproducible token IDs across restarts."})
                + "\n",
                encoding="utf-8",
            )
            (ds_dir / "validation.jsonl").write_text(
                json.dumps({"text": "Immutable checkpoints prevent overwriting previously verified model weights."})
                + "\n",
                encoding="utf-8",
            )
            det = DatasetLeakageDetector()
            dir_report = det.check_entries(
                {
                    "unseen": [
                        {"text": "Deterministic BPE tokenizers guarantee reproducible token IDs across training restarts."}
                    ]
                },
                reference_dirs=[ds_dir],
                allowed_root=tmp_path,
            )
            self.assertFalse(dir_report.passed)
            self.assertEqual(dir_report.reference_records_scanned, 2)
            self.assertEqual(dir_report.reference_splits_scanned, ["train", "validation"])

            # 2. SQLite reference split loading check
            db_path = tmp_path / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, records_json TEXT, created_at TEXT)"
            )
            conn.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?)",
                (
                    "ds-1",
                    "base-corpus",
                    json.dumps(
                        {
                            "train": [
                                "Deterministic BPE tokenizers guarantee reproducible token IDs across training restarts."
                            ],
                            "val": [
                                "Immutable checkpoints prevent overwriting previously verified model weights."
                            ],
                        }
                    ),
                    "2026-11-25T00:00:00Z",
                ),
            )
            conn.commit()
            sqlite_report = det.check_entries(
                ["Deterministic BPE tokenizers guarantee reproducible token IDs across restarts."],
                reference_conn=conn,
            )
            conn.close()
            self.assertFalse(sqlite_report.passed)

    @unittest.skipUnless(_HAS_V11_INGEST, "Requires full apps.core.native V11 runtime dependencies")
    def test_blocks_cross_version_v11_ingestion(self) -> None:
        from apps.core.workflow import ApprovalViolationError, CentralWorkflowOrchestrator

        assert ingest_v11_dataset is not None
        with tempfile.TemporaryDirectory() as tmp:
            ds_root = Path(tmp) / "v11_root"
            ds_root.mkdir()
            engine = CentralWorkflowOrchestrator(
                db_path=Path(tmp) / "wf.db",
                work_dir=Path(tmp) / "wf_work",
                approval_secret="unit-test-approval-secret-minimum-32-chars",
            )
            try:
                v1_splits = {
                    "train": [
                        {
                            "input": "explain checkpoint versioning",
                            "target": "Each model training round persists an isolated immutable versioned checkpoint file.",
                        }
                    ],
                    "validation": [
                        {
                            "input": "describe sha256 verification",
                            "target": "Split files are hashed with SHA-256 and recorded inside the dataset manifest.",
                        }
                    ],
                    "unseen": [
                        {
                            "input": "summarize audit trail retention",
                            "target": "Governance events log actor identity timestamp target resource and decision outcome.",
                        }
                    ],
                    "ood": [
                        {
                            "input": "outline graph cycle rejection",
                            "target": "Topological DAG sorting fails closed whenever directed workflow steps form cycles.",
                        }
                    ],
                }

                # Without an Approval Gate ticket from apps/core/workflow/, ingestion must fail closed
                with self.assertRaises(ApprovalViolationError):
                    ingest_v11_dataset(
                        dataset_version="1.0.0",
                        dataset_root=ds_root,
                        source_name="native_engineering_docs",
                        license_str="Apache-2.0",
                        provenance="verified_project_documentation",
                        splits=v1_splits,
                        workflow_engine=engine,
                    )
                self.assertFalse((ds_root / "1.0.0").exists())

                # Issue and approve a valid dataset.ingest Approval Gate ticket
                run1 = engine.trigger_workflow(
                    "dataset.governed_ingest",
                    payload={"dataset_version": "1.0.0"},
                    requested_by_user_id="dev-1",
                    actor_id="dev-1",
                )
                ticket1 = run1["pending_approval_id"]
                engine.governance.decide_approval(
                    ticket1,
                    approve=True,
                    approver_user_id="admin-1",
                    approver_role="admin",
                    reason="Approve v1.0.0 ingestion",
                )

                v1 = ingest_v11_dataset(
                    dataset_version="1.0.0",
                    dataset_root=ds_root,
                    source_name="native_engineering_docs",
                    license_str="Apache-2.0",
                    provenance="verified_project_documentation",
                    splits=v1_splits,
                    approval_id=ticket1,
                    workflow_engine=engine,
                )
                self.assertTrue(v1["verified"])
                self.assertEqual(v1["status"], "ready")
                self.assertTrue(v1["approval_gate_verified"])
                self.assertTrue(v1["semantic_leakage_check"]["passed"])
                self.assertEqual(engine.store.get_approval(ticket1)["status"], "consumed")

                # Second version with valid Approval Gate ticket must still block semantic leakage
                run2 = engine.trigger_workflow(
                    "dataset.governed_ingest",
                    payload={"dataset_version": "1.1.0"},
                    requested_by_user_id="dev-1",
                    actor_id="dev-1",
                )
                ticket2 = run2["pending_approval_id"]
                engine.governance.decide_approval(
                    ticket2,
                    approve=True,
                    approver_user_id="admin-1",
                    approver_role="admin",
                    reason="Approve v1.1.0 ingestion",
                )

                with self.assertRaises(DatasetLeakageError) as ctx:
                    ingest_v11_dataset(
                        dataset_version="1.1.0",
                        dataset_root=ds_root,
                        source_name="native_engineering_docs_v2",
                        license_str="Apache-2.0",
                        provenance="verified_project_documentation_v2",
                        approval_id=ticket2,
                        workflow_engine=engine,
                        splits={
                            "train": [
                                {
                                    "input": "detail memory isolation tiers",
                                    "target": "Episodic working verified knowledge training and eval corpora remain separate.",
                                }
                            ],
                            "validation": [
                                {
                                    "input": "specify tokenizer roundtrip",
                                    "target": "Byte-level BPE restores normalized input strings deterministically across runs.",
                                }
                            ],
                            "unseen": [
                                {
                                    "input": "explain checkpoint versioning",
                                    "target": "Each model training round persists an isolated immutable versioned checkpoint.",
                                }
                            ],
                            "ood": [
                                {
                                    "input": "verify causal contradiction halt",
                                    "target": "Conflicting source assertions transition immediately to a blocked contradiction state.",
                                }
                            ],
                        },
                    )
                self.assertIn("Semantic hash leakage gate failed", str(ctx.exception))
                self.assertFalse((ds_root / "1.1.0").exists())
                # Rejected ingestion must preserve ticket2 (not burn single-use approval on failed ingest)
                self.assertEqual(engine.store.get_approval(ticket2)["status"], "approved")
            finally:
                engine.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
