"""Contract-level integration for Phase 9 intelligence components."""
from .application_contract import (
    analyze_application_specification,
    validate_application_specification,
)
from .file_manifest_contract import (
    analyze_file_manifest,
    validate_file_manifest,
)
from .feedback_contract import analyze_feedback
from .feedback_log import FeedbackLog
from .feedback_summary import summarize
from .knowledge import KnowledgeSystem
from .language_registry import ProgrammingLanguageRegistry
from .plan_contract import validate_plan
from .planning import PlanningEngine
from .project_structure_registry import ProjectStructureRegistry
from .reasoning import ReasoningEngine
from .tool_policy import PermissionGate
from .tool_registry import ToolRegistry
from .code_policy import ExecutionSafetyPolicy
from .workspace_policy import WorkspaceBoundaryPolicy

INTEGRATION_COMPONENTS = frozenset({
    "knowledge_reasoning_planning",
    "feedback",
    "tool_permission",
    "coding_safety",
    "application_workspace",
})
_INTEGRATION_KEYS = frozenset({
    "status",
    "components",
    "model_inference",
    "external_tools_called",
    "code_executed",
    "files_created",
    "model_weights_changed",
})


class IntegrationContractViolation(ValueError):
    pass


def validate_integration_result(result):
    if not isinstance(result, dict) or set(result) != _INTEGRATION_KEYS:
        raise IntegrationContractViolation(
            "integration result does not match the closed contract")
    components = result["components"]
    if not isinstance(components, dict) or set(components) != INTEGRATION_COMPONENTS:
        raise IntegrationContractViolation(
            "integration result must include every required component")
    for name, component in components.items():
        if (not isinstance(component, dict)
                or set(component) != {"status", "evidence"}
                or not isinstance(component["status"], str)
                or component["status"] not in {"passed", "failed"}
                or not isinstance(component["evidence"], list)
                or not component["evidence"]
                or any(not isinstance(item, str) or not item.strip()
                       for item in component["evidence"])):
            raise IntegrationContractViolation(
                f"invalid integration component result: {name}")
    expected_status = (
        "contracts_validated"
        if all(item["status"] == "passed" for item in components.values())
        else "validation_failed"
    )
    if result["status"] != expected_status:
        raise IntegrationContractViolation(
            f"integration status must be {expected_status}")
    for key in (
            "model_inference", "external_tools_called", "code_executed",
            "files_created", "model_weights_changed"):
        if result[key] is not False:
            raise IntegrationContractViolation(f"{key} must be False")
    return result


class IntelligenceRuntime:
    """Wire existing Phase 9 contracts without external effects or inference."""

    def __init__(self):
        self.knowledge = KnowledgeSystem()
        self.reasoning = ReasoningEngine(self.knowledge)
        self.planning = PlanningEngine()
        self.feedback_log = FeedbackLog()
        self.tool_registry = ToolRegistry()
        self.permission_gate = PermissionGate(self.tool_registry)
        self.code_safety_policy = ExecutionSafetyPolicy()
        self.workspace_policy = WorkspaceBoundaryPolicy()
        self.languages = ProgrammingLanguageRegistry()
        self.project_structures = ProjectStructureRegistry(
            self.languages, self.workspace_policy)

    def reason_and_validate_plan(self, context, question, goal, steps):
        reasoning_result = self.reasoning.deduce(context=context, question=question)
        plan = self.planning.build_plan(
            goal=goal,
            context={"reasoning_result": reasoning_result},
            steps=steps,
        )
        return {
            "reasoning": reasoning_result,
            "plan": plan,
            "model_inference": False,
        }

    def submit_feedback(self, record):
        return self.feedback_log.submit(record)

    def summarize_feedback(self):
        return summarize(self.feedback_log.records())

    def analyze_application(self, specification):
        return analyze_application_specification(
            specification, self.languages, self.project_structures)

    def validate_application(self, specification):
        return validate_application_specification(
            specification, self.languages, self.project_structures)

    def analyze_manifest(self, manifest, specification):
        return analyze_file_manifest(
            manifest, specification, self.project_structures, self.workspace_policy)

    def validate_manifest(self, manifest, specification):
        return validate_file_manifest(
            manifest, specification, self.project_structures, self.workspace_policy)

    def validate_contracts(self):
        probe_knowledge = KnowledgeSystem()
        probe_knowledge.add_entity("phase9", {"kind": "probe"})
        probe_knowledge.add_entity("knowledge", {"kind": "probe"})
        probe_knowledge.add_relation("phase9", "knowledge")
        reasoning = ReasoningEngine(probe_knowledge).deduce(
            context="phase9", question="integration contract probe")
        validate_plan({
            "goal": "validate contract wiring",
            "context": {"reasoning_status": reasoning["status"]},
            "steps": [{
                "id": "validate",
                "description": "Validate structure only",
                "depends_on": [],
                "success_criteria": "valid structure",
            }],
            "generated_by": "manual",
        })

        feedback = {
            "id": "integration-probe",
            "target": "reasoning",
            "rating": "correct",
            "comment": "",
            "source": "automated_test",
            "created_at": "2026-01-01T00:00:00Z",
        }
        feedback_valid = analyze_feedback(feedback)["status"] == "accepted_for_log"
        feedback_log = FeedbackLog()
        logged = feedback_log.submit(feedback)
        feedback_summary = summarize(feedback_log.records())
        feedback_connected = (
            feedback_valid
            and logged["stored"] is True
            and feedback_summary["overall"]["total"] == 1
        )

        tools = ToolRegistry()
        tools.register({
            "name": "integration_read",
            "description": "Read-only integration check",
            "effect": "read_only",
            "required_permission": "integration:read",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        })
        authorization = PermissionGate(tools).authorize({
            "call_id": "integration-check",
            "tool_name": "integration_read",
            "arguments": {},
        }, {"integration:read"})

        code_policy = ExecutionSafetyPolicy().evaluate("execute_generated_code")
        workspace = WorkspaceBoundaryPolicy().analyze_path("src/main.py")

        checks = {
            "knowledge_reasoning_planning": (
                reasoning["status"] == "lookup_only"
                and reasoning["model_inference"] is False,
                ["KnowledgeSystem -> ReasoningEngine -> PlanningEngine contracts"],
            ),
            "feedback": (
                feedback_connected,
                ["FeedbackLog -> read-only feedback summary"],
            ),
            "tool_permission": (
                authorization["status"] == "authorized"
                and authorization["execution_performed"] is False,
                ["PermissionGate authorization only; no tool invocation"],
            ),
            "coding_safety": (
                code_policy["status"] == "blocked"
                and code_policy["code_executed"] is False,
                ["generated-code execution remains blocked"],
            ),
            "application_workspace": (
                workspace["status"] == "valid_relative_path"
                and workspace["filesystem_accessed"] is False,
                ["WorkspaceBoundaryPolicy lexical check only"],
            ),
        }
        result = {
            "status": (
                "contracts_validated"
                if all(passed for passed, _ in checks.values())
                else "validation_failed"
            ),
            "components": {
                name: {
                    "status": "passed" if passed else "failed",
                    "evidence": evidence,
                }
                for name, (passed, evidence) in checks.items()
            },
            "model_inference": False,
            "external_tools_called": False,
            "code_executed": False,
            "files_created": False,
            "model_weights_changed": False,
        }
        return validate_integration_result(result)
