import unittest

from apps.core.intelligence.file_manifest_contract import (
    FileManifestViolation,
    analyze_file_manifest,
    validate_file_manifest,
)
from apps.core.intelligence.language_registry import ProgrammingLanguageRegistry
from apps.core.intelligence.project_structure_registry import ProjectStructureRegistry
from apps.core.intelligence.workspace_policy import WorkspaceBoundaryPolicy


def _spec():
    return {"application_id": "sample-app", "structure_id": "python_package"}


def _manifest(**overrides):
    manifest = {
        "application_id": "sample-app",
        "structure_id": "python_package",
        "entries": [
            {"path": "src", "kind": "directory"},
            {"path": "src/main.py", "kind": "file"},
            {"path": "README.md", "kind": "file"},
        ],
    }
    manifest.update(overrides)
    return manifest


class TestFileManifestContract(unittest.TestCase):
    def setUp(self):
        self.languages = ProgrammingLanguageRegistry()
        self.structures = ProjectStructureRegistry(self.languages)
        self.structures.register(
            "python_package", "python", ("src", "tests"), (".py", ".md"))
        self.workspace = WorkspaceBoundaryPolicy()

    def test_valid_manifest_is_metadata_only(self):
        result = analyze_file_manifest(
            _manifest(), _spec(), self.structures, self.workspace)
        self.assertEqual(result["status"], "valid_manifest")
        self.assertIs(result["filesystem_accessed"], False)

    def test_manifest_rejects_paths_outside_lexical_workspace(self):
        for path in ("/tmp/main.py", "../main.py", "src/../../outside.py",
                     r"src\main.py", "C:/main.py"):
            manifest = _manifest(entries=[{"path": path, "kind": "file"}])
            with self.subTest(path=path):
                self.assertEqual(analyze_file_manifest(
                    manifest, _spec(), self.structures)["status"],
                    "invalid_manifest")

    def test_manifest_rejects_unregistered_paths_and_extensions(self):
        for path in ("outside/main.py", "src/main.txt"):
            manifest = _manifest(entries=[{"path": path, "kind": "file"}])
            with self.subTest(path=path):
                self.assertEqual(analyze_file_manifest(
                    manifest, _spec(), self.structures)["status"],
                    "invalid_manifest")

    def test_manifest_rejects_duplicate_entries_case_insensitively(self):
        manifest = _manifest(entries=[
            {"path": "src/main.py", "kind": "file"},
            {"path": "SRC/MAIN.PY", "kind": "file"},
        ])
        self.assertEqual(analyze_file_manifest(
            manifest, _spec(), self.structures)["status"], "invalid_manifest")

    def test_manifest_rejects_file_parent_conflict(self):
        manifest = _manifest(entries=[
            {"path": "src", "kind": "file"},
            {"path": "src/main.py", "kind": "file"},
        ])
        self.assertEqual(analyze_file_manifest(
            manifest, _spec(), self.structures)["status"], "invalid_manifest")

    def test_manifest_requires_matching_spec_and_at_least_one_file(self):
        for manifest in (
                _manifest(application_id="other"),
                _manifest(structure_id="other"),
                _manifest(entries=[{"path": "src", "kind": "directory"}])):
            with self.subTest(manifest=manifest):
                self.assertEqual(analyze_file_manifest(
                    manifest, _spec(), self.structures)["status"],
                    "invalid_manifest")

    def test_manifest_rejects_invalid_entry_shape(self):
        manifest = _manifest(entries=[
            {"path": "src/main.py", "kind": "unsupported", "extra": True},
        ])
        self.assertEqual(analyze_file_manifest(
            manifest, _spec(), self.structures)["status"], "invalid_manifest")

    def test_validator_raises_for_invalid_manifest(self):
        manifest = _manifest(entries=[{"path": "../bad.py", "kind": "file"}])
        with self.assertRaises(FileManifestViolation):
            validate_file_manifest(manifest, _spec(), self.structures)


if __name__ == "__main__":
    unittest.main()
