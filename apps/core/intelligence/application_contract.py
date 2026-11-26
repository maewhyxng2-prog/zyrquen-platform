"""Contract for application specifications; it does not create applications."""
import re

from .dependency_policy import DependencyDeclarationPolicy

APPLICATION_SPEC_KEYS = frozenset({
    "application_id", "name", "description", "language",
    "structure_id", "requirements", "dependencies",
})
APPLICATION_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


class ApplicationSpecificationViolation(ValueError):
    pass


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def analyze_application_specification(
        specification, languages, structures, dependency_policy=None):
    if not isinstance(specification, dict):
        return {
            "status": "invalid_specification",
            "problems": ["specification must be a dict"],
        }
    dependency_policy = (
        dependency_policy if dependency_policy is not None
        else DependencyDeclarationPolicy()
    )
    problems = []
    missing = APPLICATION_SPEC_KEYS - set(specification)
    extra = set(specification) - APPLICATION_SPEC_KEYS
    if missing:
        problems.append(f"missing specification keys: {sorted(map(repr, missing))}")
    if extra:
        problems.append(f"unknown specification keys: {sorted(map(repr, extra))}")
    application_id = specification.get("application_id")
    if (not isinstance(application_id, str)
            or APPLICATION_ID_PATTERN.fullmatch(application_id) is None):
        problems.append("application_id must be a lowercase slug")
    if not _text(specification.get("name")):
        problems.append("name must be non-empty text")
    if not _text(specification.get("description")):
        problems.append("description must be non-empty text")
    language = specification.get("language")
    if not _text(language) or not languages.contains(language):
        problems.append("language must name a registered programming language")
    structure_id = specification.get("structure_id")
    if not _text(structure_id) or not structures.contains(structure_id):
        problems.append("structure_id must name a registered project structure")
    elif _text(language):
        structure = structures.get(structure_id)
        if structure.language != language:
            problems.append("project structure language does not match specification")
    requirements = specification.get("requirements")
    if (not isinstance(requirements, list) or not requirements
            or any(not _text(item) for item in requirements)):
        problems.append("requirements must be a non-empty list of non-empty text")
    dependency_result = dependency_policy.analyze(
        specification.get("dependencies"))
    if dependency_result["status"] != "valid_declarations":
        problems.extend(dependency_result["problems"])
    return {
        "status": "valid_specification" if not problems else "invalid_specification",
        "problems": problems,
        "dependencies_installed": False,
    }


def validate_application_specification(
        specification, languages, structures, dependency_policy=None):
    result = analyze_application_specification(
        specification, languages, structures, dependency_policy)
    if result["status"] != "valid_specification":
        raise ApplicationSpecificationViolation("; ".join(result["problems"]))
    return specification
