import unittest

from apps.core.intelligence.code_policy import (
    FORBIDDEN_CODE_OPERATIONS,
    ExecutionSafetyPolicy,
)


class TestExecutionSafetyPolicy(unittest.TestCase):
    def test_execution_and_environment_operations_are_all_blocked(self):
        policy = ExecutionSafetyPolicy()
        for operation in FORBIDDEN_CODE_OPERATIONS:
            with self.subTest(operation=operation):
                decision = policy.evaluate(operation)
                self.assertEqual(decision["status"], "blocked")
                self.assertIs(decision["allowed"], False)
                self.assertIs(decision["code_executed"], False)

    def test_unknown_operations_are_rejected(self):
        with self.assertRaises(ValueError):
            ExecutionSafetyPolicy().evaluate("unknown")
        with self.assertRaises(ValueError):
            ExecutionSafetyPolicy().evaluate(None)


if __name__ == "__main__":
    unittest.main()
