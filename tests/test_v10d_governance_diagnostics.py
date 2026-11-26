from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from apps.core.workflow.governance_diagnostics import (
    REQUIRED_WORKFLOW_TABLES,
    approval_secret_fingerprint,
    inspect_workflow_db_readonly,
    workflow_db_path_fingerprint,
)


class TestV10DGovernanceDiagnostics(unittest.TestCase):
    def test_secret_fingerprint_is_stable_without_returning_secret(self) -> None:
        secret = "test-only-secret-never-used-for-real-approval"
        fingerprint = approval_secret_fingerprint(secret)
        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn(secret, fingerprint)
        self.assertEqual(fingerprint, approval_secret_fingerprint(secret))
        self.assertNotEqual(fingerprint, approval_secret_fingerprint(secret + "-other"))
        self.assertEqual("", approval_secret_fingerprint("  "))

    def test_path_fingerprint_uses_canonical_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.db"
            self.assertEqual(
                workflow_db_path_fingerprint(path),
                workflow_db_path_fingerprint(Path(tmp) / "." / "workflow.db"),
            )

    def test_inspection_requires_existing_complete_schema_and_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "workflow.db"
            with sqlite3.connect(db_path) as conn:
                for table in sorted(REQUIRED_WORKFLOW_TABLES):
                    conn.execute(f'CREATE TABLE "{table}" (id TEXT)')
                conn.commit()

            before = db_path.read_bytes()
            result = inspect_workflow_db_readonly(db_path)
            after = db_path.read_bytes()

            self.assertTrue(result["exists"])
            self.assertTrue(result["is_file"])
            self.assertTrue(result["required_tables_present"])
            self.assertTrue(result["read_only"])
            self.assertEqual([], result["missing_tables"])
            self.assertEqual(before, after)

    def test_missing_database_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            result = inspect_workflow_db_readonly(db_path)
            self.assertFalse(result["exists"])
            self.assertFalse(result["required_tables_present"])
            self.assertFalse(db_path.exists())

    def test_incomplete_schema_reports_missing_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "partial.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE workflow_runs (id TEXT)")
                conn.commit()
            result = inspect_workflow_db_readonly(db_path)
            self.assertFalse(result["required_tables_present"])
            self.assertIn("workflow_approvals", result["missing_tables"])


if __name__ == "__main__":
    unittest.main()
