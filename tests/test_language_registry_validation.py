import unittest

from apps.core.intelligence.language_registry import (
    LanguageRegistryViolation,
    ProgrammingLanguageRegistry,
)
from apps.core.intelligence.static_validation import (
    PythonSyntaxValidator,
    StaticValidationContractViolation,
    StaticValidationInterface,
    UnsupportedStaticValidationError,
)


class _InvalidValidator:
    def validate(self, source):
        return {"status": "valid", "problems": [], "executed": True}


class _MalformedProblemValidator:
    def validate(self, source):
        return {"status": "invalid", "problems": [object()], "executed": False}


class TestLanguageRegistryAndStaticValidation(unittest.TestCase):
    def test_registry_starts_with_python_and_returns_sorted_metadata(self):
        languages = ProgrammingLanguageRegistry()
        languages.register("typescript", (".ts", ".tsx"))
        self.assertEqual([language.name for language in languages.list_languages()],
                         ["python", "typescript"])
        self.assertEqual(languages.get("python").extensions, (".py",))

    def test_registry_rejects_duplicate_or_invalid_definitions(self):
        languages = ProgrammingLanguageRegistry()
        for name, extensions in (
                ("python", (".py",)),
                ("Bad Name", (".bad",)),
                ("rust", (".rs", ".RS")),
                ("rust", ())):
            with self.subTest(name=name, extensions=extensions):
                with self.assertRaises(LanguageRegistryViolation):
                    languages.register(name, extensions)

    def test_registry_lookup_failure_is_explicit(self):
        with self.assertRaises(KeyError):
            ProgrammingLanguageRegistry().get("unknown")

    def test_python_syntax_validation_does_not_execute_source(self):
        result = StaticValidationInterface(
            ProgrammingLanguageRegistry()).validate("python", "value = 1\n")
        self.assertEqual(result["status"], "valid")
        self.assertIs(result["code_executed"], False)

    def test_python_syntax_error_has_location_and_does_not_execute(self):
        result = PythonSyntaxValidator().validate("def broken(:\n    pass")
        self.assertEqual(result["status"], "invalid")
        self.assertIsNotNone(result["problems"][0]["line"])
        self.assertIs(result["executed"], False)

    def test_unknown_language_and_missing_validator_are_explicit(self):
        languages = ProgrammingLanguageRegistry()
        languages.register("rust", (".rs",))
        interface = StaticValidationInterface(languages)
        with self.assertRaises(KeyError):
            interface.validate("unknown", "fn main() {}")
        with self.assertRaises(UnsupportedStaticValidationError):
            interface.validate("rust", "fn main() {}")

    def test_validator_result_contract_is_enforced(self):
        for validator in (_InvalidValidator(), _MalformedProblemValidator()):
            with self.subTest(validator=validator):
                interface = StaticValidationInterface(
                    ProgrammingLanguageRegistry(), {"python": validator})
                with self.assertRaises(StaticValidationContractViolation):
                    interface.validate("python", "pass")

    def test_validator_requires_source_text(self):
        with self.assertRaises(TypeError):
            StaticValidationInterface(
                ProgrammingLanguageRegistry()).validate("python", None)


if __name__ == "__main__":
    unittest.main()
