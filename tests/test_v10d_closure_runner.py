"""Security and contract tests for tools/close_v10d.py."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from close_v10d import CLOSURE_RUNNER_SCHEMA, V10DClosureError, parse_args, run_v10d_closure


class TestV10DClosureRunner(unittest.TestCase):
    def test_honest_blocked_status_when_torch_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            with patch("close_v10d.check_torch_cpu_runtime", return_value={"available": False, "reason": "No module named torch"}):
                result = run_v10d_closure(workspace_dir=ws)
            self.assertEqual(result["schema"], CLOSURE_RUNNER_SCHEMA)
            self.assertEqual(result["overall_status"], "BLOCKED")
            self.assertFalse(result["v11_unlocked"])
            self.assertEqual(result["v11_gate"]["status"], "LOCKED")
            self.assertIn("TORCH_NOT_INSTALLED", result["blockers"])
            self.assertFalse((ws / "checkpoints").exists())
            self.assertFalse((ws / "eval").exists())

    def test_rejects_resource_budget_violations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, batch_size=8)
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, block_size=128)
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, training_steps=501)
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, cpu_threads=4)

    def test_runner_requires_and_passes_shared_hmac_secret(self) -> None:
        from close_v10d import _open_orchestrator

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "workflow.db"
            with patch.dict("os.environ", {"ZYRQUEN_APPROVAL_SECRET": "s" * 48}):
                with patch("close_v10d.CentralWorkflowOrchestrator") as factory:
                    fake = factory.return_value
                    with _open_orchestrator(db):
                        pass
                    factory.assert_called_once_with(
                        db_path=db,
                        work_dir=ROOT,
                        approval_secret="s" * 48,
                    )
                    fake.shutdown.assert_called_once_with(wait=True)

            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(V10DClosureError):
                    with _open_orchestrator(db):
                        pass

    def test_cli_rejects_self_asserted_admin_approval(self) -> None:
        with patch.object(sys, "argv", ["close_v10d.py", "--approve-as-admin", "admin-01"]):
            with self.assertRaises(SystemExit) as exc:
                parse_args()
        self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
