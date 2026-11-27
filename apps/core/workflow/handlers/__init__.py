"""Workflow handler packages and built-in workflow registration across all 8 groups."""

from __future__ import annotations

from typing import Any

from apps.core.workflow.handlers.groups import (
    _V10_EXPECTED_CAPABILITIES,
    _V10_REPORT_SCHEMA,
    handle_data_verify_and_audit,
    handle_dataset_ingest,
    handle_evaluation_gate,
    handle_evaluation_verify,
    handle_improvement_proposal,
    handle_knowledge_memory_ingest,
    handle_maintainer_audit,
    handle_maintainer_merge,
    handle_maintainer_propose,
    handle_project_dev_roadmap_sync,
    handle_security_integrity_audit,
    handle_system_ops_daily_report,
    handle_system_ops_health,
    handle_training_execute,
    handle_training_preflight,
)
from apps.core.workflow.models import WorkflowDefinition, WorkflowStepSpec
from apps.core.workflow.resource_guard import MIN_DISK_RESERVE_GB  # noqa: F401

__all__ = [
    "_V10_EXPECTED_CAPABILITIES",
    "_V10_REPORT_SCHEMA",
    "handle_data_verify_and_audit",
    "handle_dataset_ingest",
    "handle_evaluation_gate",
    "handle_evaluation_verify",
    "handle_improvement_proposal",
    "handle_knowledge_memory_ingest",
    "handle_maintainer_audit",
    "handle_maintainer_merge",
    "handle_maintainer_propose",
    "handle_project_dev_roadmap_sync",
    "handle_security_integrity_audit",
    "handle_system_ops_daily_report",
    "handle_system_ops_health",
    "handle_training_execute",
    "handle_training_preflight",
    "register_builtin_workflows",
]


def register_builtin_workflows(registry: Any) -> list[WorkflowDefinition]:
    """Register built-in workflow handlers and definitions across all 8 WORKFLOW_GROUPS."""
    handlers: dict[str, Any] = {
        "system_ops.check_health": handle_system_ops_health,
        "system_ops.daily_report": handle_system_ops_daily_report,
        "dataset.ingest": handle_dataset_ingest,
        "data.verify_and_audit": handle_data_verify_and_audit,
        "training.preflight": handle_training_preflight,
        "training.execute": handle_training_execute,
        "evaluation.gate": handle_evaluation_gate,
        "evaluation.verify": handle_evaluation_verify,
        "knowledge.memory_ingest": handle_knowledge_memory_ingest,
        "improvement.propose": handle_improvement_proposal,
        "security.integrity_audit": handle_security_integrity_audit,
        "project_dev.roadmap_sync": handle_project_dev_roadmap_sync,
        "project_dev.maintainer_audit": handle_maintainer_audit,
        "project_dev.maintainer_propose": handle_maintainer_propose,
        "project_dev.maintainer_merge": handle_maintainer_merge,
    }
    for handler_key, fn in handlers.items():
        registry.register_handler(handler_key, fn)

    definitions: list[WorkflowDefinition] = [
        # 1. system_ops
        WorkflowDefinition(
            workflow_key="system_ops.health_check",
            version="1.0.0",
            group_name="system_ops",
            title="System Operations Health Check",
            description="Check API, runtime health, disk, and RAM telemetry and record daily operational status.",
            default_tier="tier1_auto",
            schedule_interval_sec=300,
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="check_health",
                    handler_key="system_ops.check_health",
                    description="Collect verified runtime RAM and disk snapshot.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
                WorkflowStepSpec(
                    step_key="daily_report",
                    handler_key="system_ops.daily_report",
                    description="Emit operational health status report.",
                    depends_on=("check_health",),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        # 2. data
        WorkflowDefinition(
            workflow_key="data.ingestion_and_leakage_gate",
            version="1.0.0",
            group_name="data",
            title="Data Ingestion & Leakage Gate",
            description="Validate dataset manifest, SHA-256 checksums, and train/val/test/OOD leakage boundaries.",
            default_tier="tier1_auto",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="verify_and_audit",
                    handler_key="data.verify_and_audit",
                    description="Verify manifest integrity and run leakage gate.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        # 3. training
        WorkflowDefinition(
            workflow_key="training.native_controlled_run",
            version="1.0.0",
            group_name="training",
            title="Governed Native CPU Training Run",
            description="Run Tier-1 preflight, enforce Tier-2 HMAC admin gate, execute bounded native training, and gate evaluation.",
            default_tier="tier2_approval",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="preflight",
                    handler_key="training.preflight",
                    description="Validate dataset directory and runtime readiness before training.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
                WorkflowStepSpec(
                    step_key="execute_training",
                    handler_key="training.execute",
                    description="Execute bounded CPU native model training after Tier-2 approval.",
                    depends_on=("preflight",),
                    lane="compute_heavy",
                    tier="tier2_approval",
                    action_type="training.execute",
                    max_attempts=1,
                    min_disk_gb=MIN_DISK_RESERVE_GB,
                ),
                WorkflowStepSpec(
                    step_key="evaluate_model",
                    handler_key="evaluation.gate",
                    description="Run evaluation gate on generated model evidence.",
                    depends_on=("execute_training",),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                    condition_step="execute_training",
                    condition_verdict="PASS",
                ),
            ),
        ),
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
                    action_type="training.execute",
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
        # 4. evaluation
        WorkflowDefinition(
            workflow_key="evaluation.model_verification",
            version="1.0.0",
            group_name="evaluation",
            title="V10 Evaluation Report & Registry Gate",
            description="Verify evaluation report integrity and attach certified evidence to ModelRegistry.",
            default_tier="tier1_auto",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="verify_eval_gate",
                    handler_key="evaluation.gate",
                    description="Validate evaluation report against anti-False-PASS gates and attach registry evidence.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="evaluation.suite_run",
            version="1.0.0",
            group_name="evaluation",
            title="Evaluation Artifact Verification Suite",
            description="Verify versioned checkpoint & registry artifacts honestly.",
            default_tier="tier1_auto",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="verify_artifacts",
                    handler_key="evaluation.verify",
                    description="Verify checkpoint SHA-256 and registry alignment.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        # 5. knowledge_memory
        WorkflowDefinition(
            workflow_key="knowledge.memory_ingestion",
            version="1.0.0",
            group_name="knowledge_memory",
            title="Tenant-Isolated Knowledge & Memory Ingestion",
            description="Enforce tenant isolation and PII scrubbing prior to memory indexing.",
            default_tier="tier1_auto",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="ingest_memory",
                    handler_key="knowledge.memory_ingest",
                    description="Validate workspace isolation and scrub PII from memory input.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        # 6. improvement_proposal
        WorkflowDefinition(
            workflow_key="improvement.proposal",
            version="1.0.0",
            group_name="improvement_proposal",
            title="Autonomous Improvement Hypothesis Proposal",
            description="Propose bounded evaluation-backed improvement hypotheses without unapproved mutations.",
            default_tier="tier1_auto",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="propose_improvement",
                    handler_key="improvement.propose",
                    description="Formulate experiment hypothesis from verified metrics.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        # 7. security_governance
        WorkflowDefinition(
            workflow_key="security.integrity_audit",
            version="1.0.0",
            group_name="security_governance",
            title="Security & Governance Integrity Audit",
            description="Verify Tier-2 HMAC gate discipline, audit trail integrity, and policy compliance.",
            default_tier="tier1_auto",
            schedule_interval_sec=600,
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="audit_security",
                    handler_key="security.integrity_audit",
                    description="Verify governance boundaries and security invariants.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        # 8. project_dev
        WorkflowDefinition(
            workflow_key="project_dev.roadmap_sync",
            version="1.0.0",
            group_name="project_dev",
            title="Project Roadmap & CI Verification Sync",
            description="Track repository verification status while keeping pushes and deployments Tier-2 gated.",
            default_tier="tier1_auto",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="roadmap_sync",
                    handler_key="project_dev.roadmap_sync",
                    description="Sync repository status and enforce Tier-2 push/deploy boundaries.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="project_dev.autonomous_maintainer",
            version="1.0.0",
            group_name="project_dev",
            title="Autonomous Repository Maintainer Workflow",
            description="Run read-only audit, propose sandbox-verified patches, and enforce Tier-2 gate on main merge.",
            default_tier="tier2_approval",
            is_active=True,
            steps=(
                WorkflowStepSpec(
                    step_key="audit_repo",
                    handler_key="project_dev.maintainer_audit",
                    description="Run read-only repository audit.",
                    depends_on=(),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="repo.audit",
                ),
                WorkflowStepSpec(
                    step_key="propose_remediation",
                    handler_key="project_dev.maintainer_propose",
                    description="Draft policy-checked remediation patches in isolated sandbox.",
                    depends_on=("audit_repo",),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="pr.propose",
                ),
                WorkflowStepSpec(
                    step_key="merge_to_main",
                    handler_key="project_dev.maintainer_merge",
                    description="Require Tier-2 HMAC admin approval before merging to main.",
                    depends_on=("propose_remediation",),
                    lane="control_ops",
                    tier="tier2_approval",
                    action_type="git.merge_main",
                ),
            ),
        ),
    ]

    for defn in definitions:
        registry.register_definition(defn)

    return definitions
