package com.example.domain

import kotlinx.serialization.Serializable

@Serializable
enum class ProbeType {
    RESTORE_PROOF,
    SYNC_TRUTH,
    EXECUTION_REALITY,
    ISOLATION_SUITE
}

@Serializable
enum class OperatorRole(val label: String, val badge: String) {
    OPERATOR("Operator (ตรวจอ่าน + เสนอแผน)", "OPERATOR"),
    ADMIN("Admin (อนุมัติ Gate + จัดการสิทธิ์)", "ADMIN")
}

@Serializable
enum class ApprovalStatus {
    PENDING_APPROVAL,
    APPROVED,
    REJECTED
}

@Serializable
enum class IsolationGateState {
    LOCKED,
    ISOLATION_TESTS_PASSED_RESTORE_GATED
}

@Serializable
data class BackupArchiveTarget(
    val id: String,
    val displayName: String,
    val description: String,
    val archivePath: String,
    val minFilesRequired: Int,
    val expectedManifestHashes: Map<String, String> = emptyMap(),
    val requireConfigHealthCheck: Boolean = true,
    val isUserImported: Boolean = false
)

@Serializable
data class SyncPairTarget(
    val id: String,
    val displayName: String,
    val sourceDirPath: String,
    val targetDirPath: String,
    val description: String
)

@Serializable
data class RestoreProofMetrics(
    val backupExists: Boolean,
    val backupSha256: String,
    val restoredFileCount: Int,
    val minFilesRequired: Int,
    val missingFiles: List<String> = emptyList(),
    val hashMismatches: List<String> = emptyList(),
    val extraFiles: List<String> = emptyList(),
    val tempWorkspaceCleaned: Boolean = true,
    val isolationSandboxPath: String = ""
)

@Serializable
data class RestoreProofReport(
    val runId: String,
    val probeType: ProbeType,
    val targetId: String,
    val targetName: String,
    val verifiedRestorable: Boolean,
    val completenessOk: Boolean,
    val healthCheckOk: Boolean,
    val overallPassed: Boolean,
    val discrepancies: List<String>,
    val metrics: RestoreProofMetrics,
    val workerLogs: List<String>,
    val checkedAtIso: String,
    val verdictAuthority: String = "RestoreProofVerificationEngine"
)

@Serializable
data class ApprovalRequest(
    val id: String,
    val title: String,
    val actionType: String,
    val targetRunId: String?,
    val rationale: String,
    val recommendedCommand: String,
    val riskLevel: String,
    val proposedBy: String,
    val status: ApprovalStatus = ApprovalStatus.PENDING_APPROVAL,
    val decidedBy: String? = null,
    val decisionNote: String? = null,
    val createdAtIso: String,
    val decidedAtIso: String? = null
)

@Serializable
data class AuditLogEntry(
    val id: String,
    val actor: String,
    val role: OperatorRole,
    val action: String,
    val target: String,
    val outcome: String,
    val detail: String,
    val timestampIso: String
)

@Serializable
data class AiPlanStep(
    val stepOrder: Int,
    val title: String,
    val toolName: String,
    val status: String,
    val detail: String
)

@Serializable
data class AiOperationPlan(
    val intentSummary: String,
    val riskLevel: String,
    val readinessCheck: String,
    val requiresApproval: Boolean,
    val steps: List<AiPlanStep>,
    val toolsToInvoke: List<String>,
    val targetHint: String? = null,
    val proposedRemediationTitle: String? = null,
    val proposedRemediationCommand: String? = null,
    val proposedRemediationReason: String? = null
)

@Serializable
data class AssistantTurn(
    val id: String,
    val userPrompt: String,
    val plan: AiOperationPlan? = null,
    val executedRunIds: List<String> = emptyList(),
    val executedReports: List<RestoreProofReport> = emptyList(),
    val proposedApprovalId: String? = null,
    val aiSummary: String = "",
    val isStreaming: Boolean = false,
    val errorMessage: String? = null,
    val createdAtIso: String
)
