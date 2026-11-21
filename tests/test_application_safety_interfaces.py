import unittest

from apps.core.intelligence.build_validation import (
    BuildValidationInterface,
    BuildValidationUnavailable,
)
from apps.core.intelligence.workspace_policy import (
    WorkspaceBoundaryPolicy,
    WorkspaceBoundaryViolation,
)


class TestApplicationSafetyInterfaces(unittest.TestCase):
    def test_workspace_policy_accepts_only_normalized_relative_paths(self):
        policy = WorkspaceBoundaryPolicy()
        for path in ("src/main.py", "README.md", "tests/unit/test_app.py"):
            with self.subTest(path=path):
                result = policy.analyze_path(path)
                self.assertEqual(result["status"], "valid_relative_path")
                self.assertIs(result["filesystem_accessed"], False)

    def test_workspace_policy_rejects_external_and_ambiguous_paths(self):
        policy = WorkspaceBoundaryPolicy()
        for path in ("/tmp/file", "../outside", "src/../file", "./file",
                     "src//file", "src\\file", "C:/file", ".", "file:stream"):
            with self.subTest(path=path):
                self.assertEqual(
                    policy.analyze_path(path)["status"], "invalid_relative_path")

    def test_workspace_policy_raise_path_is_explicit(self):
        with self.assertRaises(WorkspaceBoundaryViolation):
            WorkspaceBoundaryPolicy().require_relative_path("../outside")

    def test_build_validation_fails_closed_without_building(self):
        interface = BuildValidationInterface()
        with self.assertRaisesRegex(BuildValidationUnavailable, "no build was run"):
            interface.validate({"application_id": "sample"}, {"entries": []})


if __name__ == "__main__":
    unittest.main()
