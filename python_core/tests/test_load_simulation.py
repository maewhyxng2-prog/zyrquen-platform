"""
Automated Verification Tests for ZYRQUEN Ω∞ Continuous Load Simulation.
Ensures sustained mixed reasoning, KG scaling, concurrent thread WAL contention,
and multi-process subprocess bursts maintain 0 false positives, 0 external LLM usage,
and deterministic accuracy in isolated temporary state.
"""

import sys
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from tests.load_simulation import format_load_report_text, run_load_simulation  # noqa: E402


class ContinuousLoadSimulationTests(unittest.TestCase):
    def test_sustained_load_simulation_and_wal_concurrency(self) -> None:
        report = run_load_simulation(scale=0.5, workers=6, processes=8, seed=20261124)
        text_summary = format_load_report_text(report)
        self.assertIn("ZYRQUEN Ω∞ Continuous Load Simulation Report", text_summary)

        env = report["environment"]
        summary = report["summary"]
        self.assertFalse(env["external_models_used"])
        self.assertEqual(summary["external_llm_breaches"], 0)
        self.assertEqual(summary["false_positives"], 0)
        self.assertEqual(summary["sqlite_lock_errors"], 0, f"SQLite lock errors observed:\n{text_summary}")
        self.assertEqual(summary["total_errors"], 0, f"Unexpected runtime errors:\n{text_summary}")
        self.assertEqual(summary["failed"], 0, f"Load simulation failures:\n{text_summary}")
        self.assertGreaterEqual(summary["total_operations"], 100)
        self.assertEqual(len(report["stages"]), 4)


if __name__ == "__main__":
    unittest.main()
