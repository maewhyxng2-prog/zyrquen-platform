import ast
import unittest
from pathlib import Path

from apps.core.intelligence import (
    IntegrationContractViolation,
    IntelligenceRuntime,
    validate_integration_result,
)


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


class TestIntelligenceIntegration(unittest.TestCase):
    def test_runtime_validates_integrated_contracts_without_external_effects(self):
        result = IntelligenceRuntime().validate_contracts()
        self.assertEqual(result["status"], "contracts_validated")
        self.assertEqual({item["status"] for item in result["components"].values()}, {"passed"})
        self.assertIs(result["model_inference"], False)
        self.assertIs(result["external_tools_called"], False)
        self.assertIs(result["code_executed"], False)
        self.assertIs(result["files_created"], False)
        self.assertIs(result["model_weights_changed"], False)

    def test_reasoning_and_planning_are_composed_without_claiming_generation(self):
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
        self.assertEqual(result["reasoning"]["reasoning_path"], ["planning"])
        self.assertEqual(result["plan"]["status"], "valid_structure")
        self.assertIs(result["model_inference"], False)

    def test_feedback_submission_is_summarized_from_the_same_log(self):
        runtime = IntelligenceRuntime()
        result = runtime.submit_feedback({
            "id": "feedback-1",
            "target": "planning",
            "rating": "correct",
            "comment": "",
            "source": "user",
            "created_at": "2026-01-01T00:00:00Z",
        })
        self.assertIs(result["stored"], True)
        self.assertEqual(runtime.summarize_feedback()["overall"]["total"], 1)

    def test_application_validation_uses_workspace_policy_without_creating_files(self):
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
        self.assertEqual(
            runtime.analyze_application(specification)["status"],
            "valid_specification",
        )
        self.assertEqual(
            runtime.analyze_manifest(manifest, specification)["status"],
            "valid_manifest",
        )
        with self.assertRaises(ValueError):
            runtime.workspace_policy.require_relative_path("../outside")

    def test_integration_contract_rejects_claims_outside_the_safety_boundary(self):
        result = IntelligenceRuntime().validate_contracts()
        result["external_tools_called"] = True
        with self.assertRaisesRegex(IntegrationContractViolation, "external_tools_called"):
            validate_integration_result(result)

    def test_intelligence_module_dependencies_are_acyclic(self):
        graph = _intelligence_import_graph()
        visiting = set()
        visited = set()

        def visit(module):
            self.assertNotIn(module, visiting, f"circular import involving {module}")
            if module in visited:
                return
            visiting.add(module)
            for dependency in graph[module]:
                visit(dependency)
            visiting.remove(module)
            visited.add(module)

        for module in graph:
            visit(module)


if __name__ == "__main__":
    unittest.main()
