import unittest

from apps.core.intelligence.application_contract import (
    ApplicationSpecificationViolation,
    analyze_application_specification,
    validate_application_specification,
)
from apps.core.intelligence.dependency_policy import (
    DependencyDeclarationPolicy,
    DependencyPolicyViolation,
)
from apps.core.intelligence.language_registry import ProgrammingLanguageRegistry
from apps.core.intelligence.project_structure_registry import (
    ProjectStructureRegistry,
    ProjectStructureViolation,
)


def _specification(**overrides):
    specification = {
        "application_id": "sample-app",
        "name": "Sample App",
        "description": "A small application.",
        "language": "python",
        "structure_id": "python_package",
        "requirements": ["Provide a health endpoint"],
        "dependencies": [{"name": "fastapi", "version": "0.115.0"}],
    }
    specification.update(overrides)
    return specification


class TestApplicationSpecificationAndDependencies(unittest.TestCase):
    def setUp(self):
        self.languages = ProgrammingLanguageRegistry()
        self.structures = ProjectStructureRegistry(self.languages)
        self.structures.register(
            "python_package", "python", ("src", "tests"), (".py", ".md"))
        self.policy = DependencyDeclarationPolicy()

    def test_valid_specification_with_pinned_dependencies(self):
        result = analyze_application_specification(
            _specification(), self.languages, self.structures, self.policy)
        self.assertEqual(result["status"], "valid_specification")
        self.assertIs(result["dependencies_installed"], False)

    def test_specification_rejects_missing_extra_and_unknown_structure(self):
        missing = _specification()
        del missing["name"]
        for invalid in (
                missing,
                _specification(extra=True),
                _specification(structure_id="missing"),
                _specification(language="unknown"),
                _specification(requirements=[])):
            with self.subTest(specification=invalid):
                self.assertEqual(analyze_application_specification(
                    invalid, self.languages, self.structures)["status"],
                    "invalid_specification")

    def test_specification_rejects_mismatched_structure_language(self):
        self.languages.register("javascript", (".js",))
        self.structures.register("js_project", "javascript", ("src",), (".js",))
        result = analyze_application_specification(
            _specification(language="javascript"),
            self.languages,
            self.structures,
        )
        self.assertEqual(result["status"], "invalid_specification")

    def test_specification_validator_raises_on_invalid_input(self):
        with self.assertRaises(ApplicationSpecificationViolation):
            validate_application_specification(
                _specification(application_id="../escape"),
                self.languages,
                self.structures,
            )

    def test_dependency_policy_accepts_empty_or_exact_pins(self):
        for dependencies in (
                [],
                [{"name": "package_name", "version": "1.2.3"}],
                [{"name": "package-name", "version": "2.0.0-rc1"}]):
            with self.subTest(dependencies=dependencies):
                result = self.policy.analyze(dependencies)
                self.assertEqual(result["status"], "valid_declarations")
                self.assertIs(result["installation_performed"], False)

    def test_dependency_policy_rejects_unpinned_url_and_unknown_fields(self):
        for dependency in (
                {"name": "package", "version": "*"},
                {"name": "package", "version": "https://example.invalid/pkg"},
                {"name": "package", "version": "1.0", "index": "external"}):
            with self.subTest(dependency=dependency):
                self.assertEqual(
                    self.policy.analyze([dependency])["status"],
                    "invalid_declarations")

    def test_dependency_policy_rejects_duplicates_and_invalid_collection(self):
        result = self.policy.analyze([
            {"name": "Package", "version": "1.0"},
            {"name": "package", "version": "2.0"},
        ])
        self.assertEqual(result["status"], "invalid_declarations")
        self.assertEqual(self.policy.analyze(None)["status"],
                         "invalid_declarations")

    def test_dependency_validator_raises(self):
        with self.assertRaises(DependencyPolicyViolation):
            self.policy.validate([{"name": "bad", "version": "../1"}])

    def test_structure_registry_rejects_duplicate_and_unregistered_language(self):
        with self.assertRaises(ProjectStructureViolation):
            self.structures.register(
                "python_package", "python", (), (".py",))
        with self.assertRaises(ProjectStructureViolation):
            self.structures.register("unknown", "unknown", (), (".x",))


if __name__ == "__main__":
    unittest.main()
