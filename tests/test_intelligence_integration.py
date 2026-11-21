import ast
from pathlib import Path

import pytest

from apps.core.intelligence import (
    IntegrationContractViolation,
    IntelligenceRuntime,
    validate_integration_result,
)


def test_runtime_validates_integrated_contracts_without_external_effects():
    result = IntelligenceRuntime().validate_contracts()
    assert result["status"] == "contracts_validated"
    assert {item["status"] for item in result["components"].values()} == {"passed"}
    assert result["model_inference"] is False
    assert result["external_tools_called"] is False
    assert result["code_executed"] is False
    assert result["files_created"] is False
    assert result["model_weights_changed"] is False


def test_reasoning_and_planning_are_composed_without_claiming_generation():
    runtime = IntelligenceRuntime()
    runtime.knowledge.add_entity("phase9", {"kind": "phase"})
    runtime.knowledge.add_entity("planning", {"kind": "capability"})
    runtime.knowledge.add_relation("phase9", "planning")
    result = runtime.reason_and_validate_plan(
        context="phase9",
        question="What is related?",
        goal="Validate a supplied plan",
        steps=[{
            "id": "inspect",
            "description": "Inspect the supplied structure",
            "depends_on": [],
            "success_criteria": "valid structure",
        }],
    )
    assert result["reasoning"]["reasoning_path"] == ["planning"]
    assert result["plan"]["status"] == "valid_structure"
    assert result["model_inference"] is False


def test_feedback_submission_is_summarized_from_the_same_log():
    runtime = IntelligenceRuntime()
    result = runtime.submit_feedback({
        "id": "feedback-1",
        "target": "planning",
        "rating": "correct",
        "comment": "",
        "source": "user",
        "created_at": "2026-01-01T00:00:00Z",
    })
    assert result["stored"] is True
    assert runtime.summarize_feedback()["overall"]["total"] == 1


def test_application_validation_uses_workspace_policy_without_creating_files():
    runtime = IntelligenceRuntime()
    runtime.project_structures.register(
        "python_basic", "python", ["src"], [".py"])
    specification = {
        "application_id": "sample-app",
        "name": "Sample",
        "description": "A contract-only sample",
        "language": "python",
        "structure_id": "python_basic",
        "requirements": ["Provide a module"],
        "dependencies": [],
    }
    manifest = {
        "application_id": "sample-app",
        "structure_id": "python_basic",
        "entries": [{"path": "src/main.py", "kind": "file"}],
    }
    assert runtime.analyze_application(specification)["status"] == (
        "valid_specification")
    assert runtime.analyze_manifest(manifest, specification)["status"] == (
        "valid_manifest")
    with pytest.raises(ValueError):
        runtime.workspace_policy.require_relative_path("../outside")


def test_integration_contract_rejects_claims_outside_the_safety_boundary():
    result = IntelligenceRuntime().validate_contracts()
    result["external_tools_called"] = True
    with pytest.raises(IntegrationContractViolation, match="external_tools_called"):
        validate_integration_result(result)


def _intelligence_import_graph():
    package_dir = Path(__file__).parents[1] / "apps" / "core" / "intelligence"
    module_names = {
        "__init__" if path.name == "__init__.py" else path.stem
        for path in package_dir.glob("*.py")
    }
    graph = {name: set() for name in module_names}
    for path in package_dir.glob("*.py"):
        source_name = "__init__" if path.name == "__init__.py" else path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            if node.module:
                target = node.module.split(".", 1)[0]
                if target in module_names:
                    graph[source_name].add(target)
            else:
                for alias in node.names:
                    if alias.name in module_names:
                        graph[source_name].add(alias.name)
    return graph


def test_intelligence_module_dependencies_are_acyclic():
    graph = _intelligence_import_graph()
    visiting = set()
    visited = set()

    def visit(module):
        assert module not in visiting, f"circular import involving {module}"
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)
