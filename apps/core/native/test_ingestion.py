"""Unit tests for raw data ingestion, pre-ingestion semantic leakage gate, and V11 dataset version mapping."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.core.dataset_leakage_detector import SemanticHashLeakageError
from apps.core.native.ingestion import (
    IngestionPayloadTooLargeError,
    RawIngestionError,
    get_dataset_training_mapping,
    ingest_raw_dataset_upload,
    parse_raw_entries,
    validate_raw_ingestion,
)
from apps.core.workflow import ApprovalViolationError, CentralWorkflowOrchestrator, WorkflowStepSpec


def _mint_ingest_approval(engine: CentralWorkflowOrchestrator, dataset_version: str) -> str:
    wf_run, _ = engine.store.create_run(
        workflow_key="data.ingest_v11",
        workflow_version="1.0.0",
        trigger_type="manual",
        trigger_payload={"dataset_version": dataset_version},
        steps=[{"step_key": "dataset_ingest", "handler_key": "dataset.ingest"}],
        requested_by_user_id="admin-1",
    )
    pending = engine.governance.ensure_pending_approval(
        run_id=wf_run["id"],
        step=WorkflowStepSpec(
            step_key="dataset_ingest",
            handler_key="dataset.ingest",
            tier="tier2_approval",
            action_type="dataset.ingest",
        ),
        requested_by_user_id="admin-1",
        scope=f"dataset:{dataset_version}",
    )
    decided = engine.governance.decide_approval(
        pending["id"],
        approve=True,
        approver_user_id="admin-1",
        approver_role="admin",
        reason="Approved dataset version ingestion",
    )
    return decided["id"]


class NativeIngestionTests(unittest.TestCase):
    def test_parse_formats_and_size_bounds(self) -> None:
        jsonl_raw = "\n".join(
            [
                json.dumps({"input": "alpha question one", "target": "alpha answer one"}),
                json.dumps({"input": "beta question two", "target": "beta answer two"}),
            ]
        )
        recs, fmt = parse_raw_entries(raw_content=jsonl_raw, fmt="auto")
        self.assertEqual(fmt, "jsonl")
        self.assertEqual(len(recs), 2)

        csv_raw = "input,target,split\ngamma item,gamma out,train\ndelta item,delta out,validation\n"
        csv_recs, csv_fmt = parse_raw_entries(raw_content=csv_raw, fmt="auto")
        self.assertEqual(csv_fmt, "csv")
        self.assertEqual(csv_recs[0]["split"], "train")

        with self.assertRaises(RawIngestionError):
            parse_raw_entries(raw_content=b"abc\x00def")

        with self.assertRaises(IngestionPayloadTooLargeError):
            parse_raw_entries(raw_content="x" * 200, max_bytes=100)

    def test_pre_ingestion_leakage_blocks_cross_version_overlap_and_allows_clean_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ds_root = tmp_path / "datasets"
            ds_root.mkdir(parents=True, exist_ok=True)
            engine = CentralWorkflowOrchestrator(
                db_path=tmp_path / "wf.db",
                work_dir=tmp_path / "wf-work",
                approval_secret="unit-test-ingestion-approval-secret-32c",
            )
            try:
                raw_v1 = "\n".join(
                    [
                        json.dumps({"input": f"Native astronomy observation alpha {i} TR_E{i}", "target": f"Verified orbital constant alpha {i} TR_E{i}"})
                        for i in range(1, 9)
                    ]
                )
                # Missing approval must fail closed
                with self.assertRaises(ApprovalViolationError):
                    ingest_raw_dataset_upload(
                        dataset_version="v11.1.0",
                        source_name="observatory-log",
                        license_str="CC-BY-4.0",
                        provenance="internal-curated-corpus",
                        raw_content=raw_v1,
                        dataset_root=ds_root,
                        workflow_engine=engine,
                        approval_id=None,
                    )

                ticket_v1 = _mint_ingest_approval(engine, "v11.1.0")
                res1 = ingest_raw_dataset_upload(
                    dataset_version="v11.1.0",
                    source_name="observatory-log",
                    license_str="CC-BY-4.0",
                    provenance="internal-curated-corpus",
                    raw_content=raw_v1,
                    dataset_root=ds_root,
                    workflow_engine=engine,
                    approval_id=ticket_v1,
                )
                self.assertTrue(res1["ingested"])
                self.assertEqual(res1["dataset_status"]["status"], "ready")
                self.assertTrue(res1["training_pipeline_mapping"]["four_split_ready"])

                mapping = get_dataset_training_mapping("v11.1.0", dataset_root=ds_root)
                self.assertTrue(mapping["training_ready"])
                self.assertEqual(mapping["dataset_version"], "v11.1.0")

                # Second upload containing a semantic near-duplicate against v11.1.0 must be blocked pre-ingestion
                leaky_v2 = "\n".join(
                    [
                        json.dumps({"input": "Native astronomy observation alpha 1 TR_E1!!", "target": "Verified orbital constant alpha 1 TR_E1"}),
                        json.dumps({"input": "Fresh botany classification node beta 10", "target": "Botany output beta 10"}),
                        json.dumps({"input": "Fresh oceanography depth sensor gamma 20", "target": "Ocean output gamma 20"}),
                        json.dumps({"input": "Fresh geology mineral strata delta 30", "target": "Geology output delta 30"}),
                    ]
                )
                val_report = validate_raw_ingestion(
                    raw_content=leaky_v2,
                    dataset_root=ds_root,
                )
                self.assertFalse(val_report["valid"])

                ticket_v2 = _mint_ingest_approval(engine, "v11.2.0")
                with self.assertRaises(SemanticHashLeakageError):
                    ingest_raw_dataset_upload(
                        dataset_version="v11.2.0",
                        source_name="mixed-corpus",
                        license_str="CC-BY-4.0",
                        provenance="internal-curated-corpus",
                        raw_content=leaky_v2,
                        dataset_root=ds_root,
                        workflow_engine=engine,
                        approval_id=ticket_v2,
                    )
                self.assertFalse((ds_root / "v11.2.0").exists())
            finally:
                engine.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
