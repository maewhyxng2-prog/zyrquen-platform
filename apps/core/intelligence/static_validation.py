"""Static source validation interface; validators must not execute source."""
import ast
from typing import Protocol


class UnsupportedStaticValidationError(ValueError):
    pass


class StaticValidationContractViolation(ValueError):
    pass


class StaticValidator(Protocol):
    def validate(self, source: str) -> dict:
        ...


class PythonSyntaxValidator:
    def validate(self, source):
        if not isinstance(source, str):
            raise TypeError("source must be text")
        try:
            ast.parse(source, mode="exec")
        except SyntaxError as error:
            problem = {
                "message": error.msg,
                "line": error.lineno,
                "column": error.offset,
            }
            return {
                "status": "invalid",
                "problems": [problem],
                "executed": False,
            }
        return {"status": "valid", "problems": [], "executed": False}


class StaticValidationInterface:
    def __init__(self, languages, validators=None):
        self._languages = languages
        self._validators = (
            {"python": PythonSyntaxValidator()} if validators is None
            else dict(validators)
        )

    def validate(self, language, source):
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language must be non-empty text")
        self._languages.get(language)
        if not isinstance(source, str):
            raise TypeError("source must be text")
        validator = self._validators.get(language)
        if validator is None:
            raise UnsupportedStaticValidationError(
                f"no static validator registered for language: {language}")
        result = validator.validate(source)
        if not isinstance(result, dict) or set(result) != {
                "status", "problems", "executed"}:
            raise StaticValidationContractViolation(
                "validator returned an invalid result contract")
        status = result.get("status")
        problems = result.get("problems")
        if (not isinstance(status, str) or status not in {"valid", "invalid"}
                or not isinstance(problems, list)
                or any(not self._valid_problem(problem) for problem in problems)
                or result.get("executed") is not False):
            raise StaticValidationContractViolation(
                "validator returned an invalid result contract")
        if result["status"] == "valid" and result["problems"]:
            raise StaticValidationContractViolation(
                "valid validation result must not contain problems")
        if result["status"] == "invalid" and not result["problems"]:
            raise StaticValidationContractViolation(
                "invalid validation result must contain problems")
        return {
            "language": language,
            "status": result["status"],
            "problems": result["problems"],
            "code_executed": False,
        }

    @staticmethod
    def _valid_problem(problem):
        if not isinstance(problem, dict) or set(problem) != {
                "message", "line", "column"}:
            return False
        if not isinstance(problem["message"], str) or not problem["message"].strip():
            return False
        return all(
            value is None or (
                isinstance(value, int) and not isinstance(value, bool) and value > 0)
            for value in (problem["line"], problem["column"])
        )
