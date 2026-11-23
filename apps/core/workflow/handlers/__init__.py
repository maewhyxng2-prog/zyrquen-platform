"""Registration helper wiring the 8 canonical workflow definitions and handlers."""

from __future__ import annotations

from apps.core.workflow.handlers.groups import (
    handle_data_verify_and_audit,
    handle_evaluation_gate,
    handle_evaluation_verify,
    handle_improvement_analyze,
    handle_knowledge_validate,
    handle_project_dev_maintainer_audit,
    handle_project_dev_maintainer_merge,
    handle_project_dev_maintainer_propose,
    handle_project_dev_sync,
    handle_security_audit,
    handle_system_ops_health,
    handle_system_ops_report,
    handle_training_execute,
    handle_training_preflight,
)
from apps.core.workflow.models import WorkflowDefinition, WorkflowStepSpec
from apps.core.workflow.registry import WorkflowRegistry


def register_builtin_workflows(registry: WorkflowRegistry) -> list[WorkflowDefinition]:
    registry.register_handler("system_ops.health", handle_system_ops_health)
    registry.register_handler("system_ops.report", handle_system_ops_report)
    registry.register_handler("data.verify_and_audit", handle_data_verify_and_audit)
    registry.register_handler("training.preflight", handle_training_preflight)
    registry.register_handler("training.execute", handle_training_execute)
    registry.register_handler("evaluation.verify", handle_evaluation_verify)
    registry.register_handler("evaluation.gate", handle_evaluation_gate)
    registry.register_handler("knowledge.validate", handle_knowledge_validate)
    registry.register_handler("improvement.analyze", handle_improvement_analyze)
    registry.register_handler("security.audit", handle_security_audit)
    registry.register_handler("project_dev.sync", handle_project_dev_sync)
    registry.register_handler("project_dev.maintainer_audit", handle_project_dev_maintainer_audit)
    registry.register_handler("project_dev.maintainer_propose", handle_project_dev_maintainer_propose)
    registry.register_handler("project_dev.maintainer_merge", handle_project_dev_maintainer_merge)

    definitions = [
        WorkflowDefinition(
            workflow_key="system_ops.health_check",
            version="1.0.0",
            group_name="system_ops",
            title="System Operations Health & Resource Check",
            description="Check API/NativeRuntime readiness, CPU/RAM/Disk snapshots, and compile daily status report.",
            default_tier="tier1_auto",
            schedule_interval_sec=3600,
            event_triggers=("api.startup", "health.degraded"),
            steps=(
                WorkflowStepSpec(
                    step_key="check_health",
                    handler_key="system_ops.health",
                    description="Probe NativeRuntime health and ResourceManager/Disk snapshot.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
                WorkflowStepSpec(
                    step_key="daily_report",
                    handler_key="system_ops.report",
                    description="Generate daily operational status summary.",
                    depends_on=("check_health",),
                    lane="control_ops",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="data.ingestion_and_leakage_gate",
            version="1.0.0",
            group_name="data",
            title="Data Validation & Leakage Audit Gate",
            description="Verify dataset manifest SHA-256 and execute 4-layer zero-tolerance leakage audit.",
            default_tier="tier1_auto",
            event_triggers=("dataset.ingested",),
            steps=(
                WorkflowStepSpec(
                    step_key="verify_and_audit",
                    handler_key="data.verify_and_audit",
                    description="Verify manifest checksum and run data leakage gate.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="training.native_controlled_run",
            version="1.0.0",
            group_name="training",
            title="Controlled Native Training Pipeline",
            description="Pre-flight dataset/resource caps check followed by mandatory Tier-2 human approval before training.",
            default_tier="tier2_approval",
            event_triggers=(),
            steps=(
                WorkflowStepSpec(
                    step_key="preflight",
                    handler_key="training.preflight",
                    description="Check dataset availability and CPU compute caps.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
                WorkflowStepSpec(
                    step_key="execute_training",
                    handler_key="training.execute",
                    description="Execute approved native training run with atomic checkpointing.",
                    depends_on=("preflight",),
                    lane="compute_heavy",
                    tier="tier2_approval",
                    action_type="training.execute",
                    max_attempts=1,
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="evaluation.model_verification",
            version="1.0.0",
            group_name="evaluation",
            title="Native Model Evaluation & Regression Gate",
            description="Verify registered artifact SHA-256, audit evaluation report evidence, and update registry verified/quarantined state.",
            default_tier="tier1_auto",
            event_triggers=("training.completed",),
            steps=(
                WorkflowStepSpec(
                    step_key="verify_artifact",
                    handler_key="evaluation.verify",
                    description="Verify ModelRegistry artifact SHA-256 hashes.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
                WorkflowStepSpec(
                    step_key="evaluate_gate",
                    handler_key="evaluation.gate",
                    description="Inspect real evaluation report evidence and transition ModelRegistry lifecycle.",
                    depends_on=("verify_artifact",),
                    lane="compute_heavy",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="knowledge.memory_ingestion",
            version="1.0.0",
            group_name="knowledge_memory",
            title="Knowledge & Memory Isolation Check",
            description="Validate tenant isolation, scrub PII patterns, and index grounded knowledge hashes.",
            default_tier="tier1_auto",
            steps=(
                WorkflowStepSpec(
                    step_key="validate_knowledge",
                    handler_key="knowledge.validate",
                    description="Validate tenant boundary and scrub PII before indexing.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="improvement.offline_proposal",
            version="1.0.0",
            group_name="improvement_proposal",
            title="Autonomous Improvement Hypothesis Draft",
            description="Analyze evaluation reports for weak capabilities and draft offline proposals (never auto-mutates weights).",
            default_tier="tier1_auto",
            event_triggers=("evaluation.completed",),
            steps=(
                WorkflowStepSpec(
                    step_key="analyze_weaknesses",
                    handler_key="improvement.analyze",
                    description="Inspect evaluation metrics and propose offline experiment plan.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="security.integrity_audit",
            version="1.0.0",
            group_name="security_governance",
            title="Security Configuration & Critical File Integrity Audit",
            description="Check production secret requirements and verify SHA-256 digests of core API/Registry modules.",
            default_tier="tier1_auto",
            schedule_interval_sec=3600,
            event_triggers=("auth.anomaly", "file.modified"),
            steps=(
                WorkflowStepSpec(
                    step_key="audit_security",
                    handler_key="security.audit",
                    description="Verify environment security rules and core module checksums.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="project_dev.roadmap_sync",
            version="1.0.0",
            group_name="project_dev",
            title="Roadmap 11–20 & Repository Readiness Audit",
            description="Verify Roadmap 11–20 phase modules, v9 scripts, and block unapproved push/deploy actions.",
            default_tier="tier1_auto",
            steps=(
                WorkflowStepSpec(
                    step_key="check_repo_sync",
                    handler_key="project_dev.sync",
                    description="Check presence of roadmap phase modules and experiment scripts.",
                    lane="control_ops",
                    tier="tier1_auto",
                ),
            ),
        ),
        WorkflowDefinition(
            workflow_key="project_dev.autonomous_maintainer",
            version="1.0.0",
            group_name="project_dev",
            title="Autonomous Repository Maintainer (Audit -> PR Proposal -> Tier-2 Merge Gate)",
            description=(
                "Tier-1 auto-audits code/security/dependencies and prepares sandbox-verified remediation PR drafts "
                "on isolated branches; merging into main strictly requires Tier-2 human approval."
            ),
            default_tier="tier2_approval",
            event_triggers=("ci.failure", "security.alert"),
            steps=(
                WorkflowStepSpec(
                    step_key="audit_repo",
                    handler_key="project_dev.maintainer_audit",
                    description="Read-only repository structure, AST bug, security, Native-Only, and CI audit.",
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="read_only",
                ),
                WorkflowStepSpec(
                    step_key="propose_remediation",
                    handler_key="project_dev.maintainer_propose",
                    description="Analyze root causes, validate non-protected safe patches in sandbox, and draft PR evidence.",
                    depends_on=("audit_repo",),
                    lane="control_ops",
                    tier="tier1_auto",
                    action_type="pr.propose",
                ),
                WorkflowStepSpec(
                    step_key="merge_to_main",
                    handler_key="project_dev.maintainer_merge",
                    description="Tier-2 human approval gate required before any maintainer branch merges into main.",
                    depends_on=("propose_remediation",),
                    lane="control_ops",
                    tier="tier2_approval",
                    action_type="git.merge_main",
                    max_attempts=1,
                ),
            ),
        ),
    ]

    for defn in definitions:
        registry.register_definition(defn)
    return definitions
