"""V10-D authenticated API approval integration contract tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Importing the API router loads the database safety guard. These tests use
# the explicitly permitted SQLite-only unit_test environment; they never
# connect to or mutate a development, test, or production database.
os.environ.setdefault("ZYRQUEN_ENV", "unit_test")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException

from apps.api.routers import workflows


class TestV10DAPIApprovalIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_engine = workflows._ENGINE
        workflows._ENGINE = None

    def tearDown(self) -> None:
        if workflows._ENGINE is not None:
            workflows._ENGINE.shutdown(wait=True)
        workflows._ENGINE = self.previous_engine

    def test_v10d_api_registers_real_workflow_handlers_with_shared_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "shared-workflows.db"
            with patch.dict(
                os.environ,
                {
                    "ZYRQUEN_V10D_APPROVAL_ENABLED": "1",
                    "ZYRQUEN_WORKFLOW_DB_PATH": str(db_path),
                    "ZYRQUEN_APPROVAL_SECRET": "test-only-secret-for-unit-tests",
                    "ZYRQUEN_WORKFLOW_SCHEDULER": "0",
                    "ZYRQUEN_WORKFLOW_RECOVERY": "0",
                },
                clear=False,
            ):
                engine = workflows.get_workflow_engine()
                definition = engine.registry.get("training.v10d_closure_run", "1.0.0")
                self.assertEqual(definition.group_name, "training")
                self.assertIn("execute_v10d_training", [step.step_key for step in definition.steps])
                self.assertIsNotNone(engine.registry.get_handler("v10d.train_execute"))
                self.assertTrue(db_path.is_file())

    def test_v10d_api_fails_closed_without_shared_secret(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(
                os.environ,
                {
                    "ZYRQUEN_V10D_APPROVAL_ENABLED": "1",
                    "ZYRQUEN_WORKFLOW_DB_PATH": str(Path(td) / "shared.db"),
                },
                clear=False,
            ):
                os.environ.pop("ZYRQUEN_APPROVAL_SECRET", None)
                with self.assertRaises(HTTPException) as exc:
                    workflows.get_workflow_engine()
                self.assertEqual(exc.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
