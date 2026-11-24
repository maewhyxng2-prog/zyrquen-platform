"""Static safety contract for the read-only V10 native forward probe."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "probe_v10d_native_forward.py"


class TestV10DNativeForwardProbeContract(unittest.TestCase):
    def test_probe_is_syntactically_valid_and_has_no_training_or_write_calls(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(PROBE))
        forbidden = {
            "backward",
            "step",
            "save",
            "register",
            "promote",
            "trigger_workflow",
            "handle_training_execute",
            "train",
            "train_sft",
        }
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else ""
            )
            if name in forbidden:
                calls.append(name)
        self.assertEqual(calls, [], f"probe contains forbidden operations: {calls}")
        self.assertIn('"training_invoked": False', source)
        self.assertIn('"backward_invoked": False', source)
        self.assertIn('"checkpoint_written": False', source)
        self.assertIn('"registry_modified": False', source)


if __name__ == "__main__":
    unittest.main()
