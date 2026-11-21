import unittest

from apps.core.intelligence.code_contract import (
    CodeContractViolation,
    analyze_code_output,
    analyze_code_task,
    validate_code_output,
    validate_code_task,
)
from apps.core.intelligence.language_registry import ProgrammingLanguageRegistry


def _task(**overrides):
    task = {
        "task_id": "task-1",
        "objective": "Create a small module",
        "language": "python",
        "requirements": ["Expose a function"],
    }
    task.update(overrides)
    return task


def _output(**overrides):
    output = {
        "task_id": "task-1",
        "language": "python",
        "files": [{"path": "src/module.py", "content": "def run():\n    return 1\n"}],
    }
    output.update(overrides)
    return output


class TestCodeContracts(unittest.TestCase):
    def setUp(self):
        self.languages = ProgrammingLanguageRegistry()

    def test_valid_task_and_output(self):
        self.assertEqual(analyze_code_task(_task(), self.languages)["status"],
                         "valid_task")
        self.assertEqual(analyze_code_output(
            _output(), self.languages, expected_task_id="task-1")["status"],
            "valid_output")

    def test_task_rejects_missing_extra_and_unknown_language(self):
        missing = _task()
        del missing["objective"]
        for task in (missing, _task(unexpected=True),
                     _task(language="unregistered")):
            with self.subTest(task=task):
                self.assertEqual(
                    analyze_code_task(task, self.languages)["status"],
                    "invalid_task")

    def test_task_requires_nonempty_requirements(self):
        for requirements in ([], ["  "], "requirement"):
            with self.subTest(requirements=requirements):
                self.assertEqual(
                    analyze_code_task(
                        _task(requirements=requirements), self.languages)["status"],
                    "invalid_task")

    def test_validate_task_raises_for_invalid_task(self):
        with self.assertRaises(CodeContractViolation):
            validate_code_task(_task(language="unknown"), self.languages)

    def test_output_rejects_absolute_traversal_and_noncanonical_paths(self):
        bad_paths = ("/tmp/module.py", "../module.py", "src/../module.py",
                     "C:/temp/module.py", r"src\module.py", "./module.py")
        for path in bad_paths:
            with self.subTest(path=path):
                output = _output(files=[{"path": path, "content": "x = 1"}])
                self.assertEqual(analyze_code_output(
                    output, self.languages)["status"], "invalid_output")

    def test_output_rejects_wrong_extension_duplicate_and_task_mismatch(self):
        cases = (
            _output(files=[{"path": "src/module.txt", "content": "source"}]),
            _output(files=[
                {"path": "src/module.py", "content": "first"},
                {"path": "SRC/MODULE.PY", "content": "second"},
            ]),
            _output(task_id="other-task"),
        )
        for output in cases:
            with self.subTest(output=output):
                self.assertEqual(analyze_code_output(
                    output, self.languages, expected_task_id="task-1")["status"],
                    "invalid_output")

    def test_output_requires_nonempty_files_and_content(self):
        for output in (
                _output(files=[]),
                _output(files=[{"path": "module.py", "content": "  "}]),
                _output(files=[{"path": "module.py", "content": "x", "extra": 1}])):
            with self.subTest(output=output):
                self.assertEqual(analyze_code_output(
                    output, self.languages)["status"], "invalid_output")

    def test_validate_output_raises_for_invalid_path(self):
        with self.assertRaises(CodeContractViolation):
            validate_code_output(
                _output(files=[{"path": "../bad.py", "content": "x"}]),
                self.languages)


if __name__ == "__main__":
    unittest.main()
