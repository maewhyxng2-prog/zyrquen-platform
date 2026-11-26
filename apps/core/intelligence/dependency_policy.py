"""Dependency declaration checks only; dependencies are never installed."""
import re

DEPENDENCY_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
PINNED_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,3}"
    r"(?:[-+][A-Za-z0-9][A-Za-z0-9.-]*)?\Z")
DEPENDENCY_KEYS = frozenset({"name", "version"})


class DependencyPolicyViolation(ValueError):
    pass


class DependencyDeclarationPolicy:
    def analyze(self, dependencies):
        if not isinstance(dependencies, list):
            return {
                "status": "invalid_declarations",
                "problems": ["dependencies must be a list"],
                "installation_performed": False,
            }
        problems = []
        seen = set()
        for index, dependency in enumerate(dependencies):
            if not isinstance(dependency, dict):
                problems.append(f"dependencies[{index}] must be a dict")
                continue
            missing = DEPENDENCY_KEYS - set(dependency)
            extra = set(dependency) - DEPENDENCY_KEYS
            if missing:
                problems.append(
                    f"dependencies[{index}] missing keys: {sorted(missing)}")
            if extra:
                problems.append(
                    f"dependencies[{index}] unknown keys: {sorted(map(repr, extra))}")
            name = dependency.get("name")
            version = dependency.get("version")
            if (not isinstance(name, str)
                    or DEPENDENCY_NAME_PATTERN.fullmatch(name) is None):
                problems.append(f"dependencies[{index}].name is invalid")
            else:
                key = name.casefold()
                if key in seen:
                    problems.append(f"duplicate dependency name: {name}")
                seen.add(key)
            if (not isinstance(version, str)
                    or PINNED_VERSION_PATTERN.fullmatch(version) is None):
                problems.append(
                    f"dependencies[{index}].version must be an exact pinned version")
        return {
            "status": "valid_declarations" if not problems else "invalid_declarations",
            "problems": problems,
            "installation_performed": False,
        }

    def validate(self, dependencies):
        result = self.analyze(dependencies)
        if result["status"] != "valid_declarations":
            raise DependencyPolicyViolation("; ".join(result["problems"]))
        return dependencies
