"""Workflow handler packages and built-in workflow registration."""

from __future__ import annotations

from typing import Any

from apps.core.workflow.handlers.groups import (
    _V10_EXPECTED_CAPABILITIES,
    _V10_REPORT_SCHEMA,
    handle_dataset_ingest,
    handle_evaluation_gate,
    handle_training_execute,
)
from apps.core.workflow.models import WorkflowDefinition, WorkflowStepSpec

__all__ = [
    "_V10_EXPECTED_CAPABILITIES",
    "_V10_REPORT_SCHEMA",
    "handle_dataset_ingest",
    "handle_evaluation_gate",
    "handle_training_execute",
    "register_builtin_workflows",
]


def register_builtin_workflows(registry: Any) -> list[WorkflowDefinition]:
    """Register built-in workflow handlers and definitions into WorkflowRegistry."""
    handlers: dict[str, Any] = {
        "dataset.ingest": handle_dataset_ingest,
        "training.execute": handle_training_execute,
        "evaluation.gate": handle_evaluation_gate,
    }
    for handler_key, fn in handlers.items():
        registry.register_handler(handler_key, fn)

    definitions: list[WorkflowDefinition] = [
        WorkflowDefinition(
            workflow_key="nagi_v10_training_pipeline",
            version="1.0.0",
            group_name="training",
            title="NAGI v10 Governed Training Pipeline",
            description="Ingest verified dataset, execute governed training step, and run evaluation gate.",
            default_tier="tier2_approval",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="ingest_dataset",
                    handler_key="dataset.ingest",
                    description="Verify dataset readiness and ingestion gate.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
                WorkflowStepSpec(
                    step_key="execute_training",
                    handler_key="training.execute",
                    description="Execute governed NAGI v10 training step.",
                    depends_on=("ingest_dataset",),
                    lane="compute_heavy",
                    tier="tier2_approval",
                    action_type="mutation",
                ),
                WorkflowStepSpec(
                    step_key="evaluate_model",
                    handler_key="evaluation.gate",
                    description="Evaluate training output and gate readiness.",
                    depends_on=("execute_training",),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
    ]

    for defn in definitions:
        registry.register_definition(defn)

    return definitions
