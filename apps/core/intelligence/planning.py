"""Planning runtime enforcement (Phase 9.4.5).

Validates plans supplied by the caller. It does NOT generate steps and does
NOT run any model, so model_inference is always False.
"""
import copy

from .plan_contract import PlanViolation, validate_plan  # noqa: F401


class PlanningEngine:
    ENGINE_TYPE = "plan_validator"

    def build_plan(self, goal, context, steps, generated_by="manual",
                   native_model_evidence=None):
        plan = {
            "goal": goal,
            "context": copy.deepcopy(context),
            "steps": copy.deepcopy(steps),
            "generated_by": generated_by,
        }
        analysis = validate_plan(plan, native_model_evidence)
        result = dict(plan)
        result["status"] = analysis["status"]
        result["step_order"] = analysis["step_order"]
        result["engine_type"] = self.ENGINE_TYPE
        result["model_inference"] = False
        return result
