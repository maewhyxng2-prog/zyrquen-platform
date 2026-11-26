package com.example.data

import android.content.Context
import android.net.Uri
import com.example.domain.ApprovalRequest
import com.example.domain.ApprovalStatus
import com.example.domain.AuditLogEntry
import com.example.domain.BackupArchiveTarget
import com.example.domain.IsolationGateState
import com.example.domain.OperatorRole
import com.example.domain.ProbeType
import com.example.domain.RestoreProofMetrics
import com.example.domain.RestoreProofReport
import com.example.domain.SyncPairTarget
import com.example.engine.BackupFixtureSeeder
import com.example.engine.RestoreProofWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.time.Instant
import java.util.concurrent.atomic.AtomicInteger

@Serializable
private data class PersistedStoreSnapshot(
    val runCounter: Int = 0,
    val reports: List<RestoreProofReport> = emptyList(),
    val approvals: List<ApprovalRequest> = emptyList(),
    val auditLogs: List<AuditLogEntry> = emptyList(),
    val importedBackups: List<BackupArchiveTarget> = emptyList(),
    val operatorRole: OperatorRole = OperatorRole.OPERATOR,
    val isolationGateState: IsolationGateState = IsolationGateState.LOCKED
)

class EvidenceRepository(private val appContext: Context) {

    private val json = Json {
        prettyPrint = true
        ignoreUnknownKeys = true
    }
    private val storeMutex = Mutex()
    private val storeFile = File(appContext.filesDir, "realitycheck/evidence_store.json")
    private val sandboxParentDir = File(appContext.cacheDir, "restoreproof_sandboxes")
    private val runSeq = AtomicInteger(0)

    private val _backupTargets = MutableStateFlow<List<BackupArchiveTarget>>(emptyList())
    val backupTargets: StateFlow<List<BackupArchiveTarget>> = _backupTargets.asStateFlow()

    private val _syncTargets = MutableStateFlow<List<SyncPairTarget>>(emptyList())
    val syncTargets: StateFlow<List<SyncPairTarget>> = _syncTargets.asStateFlow()

    private val _reports = MutableStateFlow<List<RestoreProofReport>>(emptyList())
    val reports: StateFlow<List<RestoreProofReport>> = _reports.asStateFlow()

    private val _approvals = MutableStateFlow<List<ApprovalRequest>>(emptyList())
    val approvals: StateFlow<List<ApprovalRequest>> = _approvals.asStateFlow()

    private val _auditLogs = MutableStateFlow<List<AuditLogEntry>>(emptyList())
    val auditLogs: StateFlow<List<AuditLogEntry>> = _auditLogs.asStateFlow()

    private val _operatorRole = MutableStateFlow(OperatorRole.OPERATOR)
    val operatorRole: StateFlow<OperatorRole> = _operatorRole.asStateFlow()

    private val _isolationGateState = MutableStateFlow(IsolationGateState.LOCKED)
    val isolationGateState: StateFlow<IsolationGateState> = _isolationGateState.asStateFlow()

    suspend fun initialize() = withContext(Dispatchers.IO) {
        val seeded = BackupFixtureSeeder.ensureSeeded(appContext.filesDir)
        val snapshot = loadSnapshot()

        runSeq.set(snapshot.runCounter)
        _backupTargets.value = seeded.backups + snapshot.importedBackups
        _syncTargets.value = seeded.syncPairs
        _reports.value = snapshot.reports
        _approvals.value = snapshot.approvals
        _auditLogs.value = snapshot.auditLogs
        _operatorRole.value = snapshot.operatorRole
        _isolationGateState.value = snapshot.isolationGateState

        if (snapshot.auditLogs.isEmpty()) {
            recordAudit(
                actor = "system_bootstrap",
                role = OperatorRole.ADMIN,
                action = "INITIALIZE_RESTOREPROOF_CORE",
                target = "RestoreProofWorker & EvidenceEngine",
                outcome = "READY",
                detail = "Initialized ${seeded.backups.size} backup archives, ${seeded.syncPairs.size} sync targets. Restore execution remains LOCKED pending isolation & recovery tests."
            )
        }
    }

    private fun nextRunId(prefix: String = "RP"): String {
        val seq = runSeq.incrementAndGet()
        return "$prefix-${seq.toString().padStart(4, '0')}"
    }

    suspend fun verifyBackupTarget(targetId: String, actor: String = "operator"): RestoreProofReport =
        withContext(Dispatchers.IO) {
            val target = _backupTargets.value.firstOrNull { it.id == targetId }
                ?: throw IllegalArgumentException("ไม่พบ Backup target: $targetId")
            val runId = nextRunId("RP")
            val report = RestoreProofWorker.verifyBackupArchive(
                runId = runId,
                target = target,
                sandboxParentDir = sandboxParentDir
            )
            appendReport(report)
            recordAudit(
                actor = actor,
                role = _operatorRole.value,
                action = "VERIFY_BACKUP_ARCHIVE",
                target = "${target.displayName} ($runId)",
                outcome = if (report.overallPassed) "PASS" else "FAIL",
                detail = "sha256=${report.metrics.backupSha256.take(12)}, discrepancies=${report.discrepancies.size}"
            )
            report
        }

    suspend fun verifyAllBackups(actor: String = "operator"): List<RestoreProofReport> =
        withContext(Dispatchers.IO) {
            val targets = _backupTargets.value
            val results = mutableListOf<RestoreProofReport>()
            for (target in targets) {
                val runId = nextRunId("RP")
                val report = RestoreProofWorker.verifyBackupArchive(
                    runId = runId,
                    target = target,
                    sandboxParentDir = sandboxParentDir
                )
                appendReport(report)
                results += report
            }
            val passed = results.count { it.overallPassed }
            val failed = results.size - passed
            recordAudit(
                actor = actor,
                role = _operatorRole.value,
                action = "VERIFY_ALL_BACKUPS",
                target = "${results.size} targets",
                outcome = if (failed == 0) "ALL_PASS" else "PARTIAL_FAIL",
                detail = "passed=$passed, failed=$failed, runs=${results.joinToString(",") { it.runId }}"
            )
            results
        }

    suspend fun verifySyncPair(syncId: String, actor: String = "operator"): RestoreProofReport =
        withContext(Dispatchers.IO) {
            val pair = _syncTargets.value.firstOrNull { it.id == syncId }
                ?: throw IllegalArgumentException("ไม่พบ Sync target: $syncId")
            val runId = nextRunId("SY")
            val report = RestoreProofWorker.verifySyncTruth(runId, pair)
            appendReport(report)
            recordAudit(
                actor = actor,
                role = _operatorRole.value,
                action = "VERIFY_SYNC_TRUTH",
                target = "${pair.displayName} ($runId)",
                outcome = if (report.overallPassed) "PASS" else "FAIL",
                detail = "discrepancies=${report.discrepancies.size}"
            )
            report
        }

    suspend fun verifyAllSyncPairs(actor: String = "operator"): List<RestoreProofReport> =
        withContext(Dispatchers.IO) {
            _syncTargets.value.map { verifySyncPair(it.id, actor) }
        }

    suspend fun importAndVerifyUri(uri: Uri, displayName: String): RestoreProofReport =
        withContext(Dispatchers.IO) {
            val imported = BackupFixtureSeeder.importUserZip(appContext, uri, displayName)
            _backupTargets.value = _backupTargets.value + imported
            verifyBackupTarget(imported.id, actor = "user_saf_import")
        }

    /**
     * Executes the 4 mandatory isolation & failure detection checks:
     * 1. Valid backup passes restore + SHA-256 + health probe.
     * 2. Corrupt backup is caught with hash mismatch / health failure.
     * 3. Incomplete backup is caught with missing files.
     * 4. Zip-Slip path traversal archive is blocked fail-closed.
     * 5. Isolated temp workspaces leave zero leftover directories.
     */
    suspend fun runIsolationVerificationSuite(actor: String = "operator"): RestoreProofReport =
        withContext(Dispatchers.IO) {
            val runId = nextRunId("ISO")
            val checkedAt = Instant.now().toString()
            val logs = mutableListOf<String>()
            val discrepancies = mutableListOf<String>()

            logs += "[$runId] Running Mandatory Isolation & Failure-Detection Verification Suite..."
            val prod = _backupTargets.value.firstOrNull { it.id == "bk_prod_ledger" }
            val corrupt = _backupTargets.value.firstOrNull { it.id == "bk_analytics_corrupt" }
            val incomplete = _backupTargets.value.firstOrNull { it.id == "bk_incomplete" }
            val zipSlip = _backupTargets.value.firstOrNull { it.id == "bk_zipslip_probe" }

            val rProd = prod?.let { RestoreProofWorker.verifyBackupArchive("$runId-A", it, sandboxParentDir) }
            val rCorrupt = corrupt?.let { RestoreProofWorker.verifyBackupArchive("$runId-B", it, sandboxParentDir) }
            val rIncomplete = incomplete?.let { RestoreProofWorker.verifyBackupArchive("$runId-C", it, sandboxParentDir) }
            val rZipSlip = zipSlip?.let { RestoreProofWorker.verifyBackupArchive("$runId-D", it, sandboxParentDir) }

            val leftoverDirs = sandboxParentDir.listFiles()?.count() ?: 0
            val c1 = rProd?.overallPassed == true
            val c2 = rCorrupt != null && !rCorrupt.overallPassed && rCorrupt.metrics.hashMismatches.isNotEmpty()
            val c3 = rIncomplete != null && !rIncomplete.overallPassed && rIncomplete.metrics.missingFiles.isNotEmpty()
            val c4 = rZipSlip != null && !rZipSlip.verifiedRestorable && rZipSlip.discrepancies.any { it.contains("traversal", ignoreCase = true) || it.contains("Security gate", ignoreCase = true) }
            val c5 = leftoverDirs == 0

            logs += "[$runId] Check 1 (Healthy restore + SHA-256): ${if (c1) "PASS" else "FAIL"}"
            logs += "[$runId] Check 2 (Tampered hash mismatch caught): ${if (c2) "PASS" else "FAIL"}"
            logs += "[$runId] Check 3 (Incomplete snapshot caught): ${if (c3) "PASS" else "FAIL"}"
            logs += "[$runId] Check 4 (Zip-Slip ../../ blocked fail-closed): ${if (c4) "PASS" else "FAIL"}"
            logs += "[$runId] Check 5 (Sandbox temp cleanup zero leftovers): ${if (c5) "PASS" else "FAIL (leftover=$leftoverDirs)"}"

            if (!c1) discrepancies += "Healthy backup probe did not pass"
            if (!c2) discrepancies += "Corrupt backup hash mismatch was not detected"
            if (!c3) discrepancies += "Incomplete snapshot missing file was not detected"
            if (!c4) discrepancies += "Zip-Slip path traversal was not blocked fail-closed"
            if (!c5) discrepancies += "Isolation sandbox cleanup left $leftoverDirs directory(ies)"

            val allOk = c1 && c2 && c3 && c4 && c5
            if (allOk) {
                _isolationGateState.value = IsolationGateState.ISOLATION_TESTS_PASSED_RESTORE_GATED
            }

            val suiteReport = RestoreProofReport(
                runId = runId,
                probeType = ProbeType.ISOLATION_SUITE,
                targetId = "isolation_suite_mvp",
                targetName = "Isolation & Recovery Verification Suite (4-Wave)",
                verifiedRestorable = c1 && c4,
                completenessOk = c2 && c3,
                healthCheckOk = c5,
                overallPassed = allOk,
                discrepancies = discrepancies,
                metrics = RestoreProofMetrics(
                    backupExists = true,
                    backupSha256 = RestoreProofWorker.sha256Bytes(logs.joinToString("\n").toByteArray()),
                    restoredFileCount = 4,
                    minFilesRequired = 4,
                    tempWorkspaceCleaned = c5,
                    isolationSandboxPath = sandboxParentDir.name
                ),
                workerLogs = logs,
                checkedAtIso = checkedAt
            )
            appendReport(suiteReport)
            recordAudit(
                actor = actor,
                role = _operatorRole.value,
                action = "RUN_ISOLATION_SUITE",
                target = runId,
                outcome = if (allOk) "PASS" else "FAIL",
                detail = "checks_passed=${listOf(c1, c2, c3, c4, c5).count { it }}/5, gate=${_isolationGateState.value}"
            )
            suiteReport
        }

    suspend fun proposeApprovalAction(
        title: String,
        actionType: String,
        targetRunId: String?,
        rationale: String,
        recommendedCommand: String,
        riskLevel: String,
        proposedBy: String = "ai_operations_assistant"
    ): ApprovalRequest = withContext(Dispatchers.IO) {
        val id = "APR-${(approvals.value.size + 1).toString().padStart(4, '0')}"
        val request = ApprovalRequest(
            id = id,
            title = title,
            actionType = actionType,
            targetRunId = targetRunId,
            rationale = rationale,
            recommendedCommand = recommendedCommand,
            riskLevel = riskLevel,
            proposedBy = proposedBy,
            status = ApprovalStatus.PENDING_APPROVAL,
            createdAtIso = Instant.now().toString()
        )
        storeMutex.withLock {
            _approvals.value = listOf(request) + _approvals.value
            persistLocked()
        }
        recordAudit(
            actor = proposedBy,
            role = _operatorRole.value,
            action = "PROPOSE_APPROVAL_ACTION",
            target = "$id ($actionType)",
            outcome = "PENDING_APPROVAL",
            detail = title
        )
        request
    }

    suspend fun decideApproval(
        approvalId: String,
        approve: Boolean,
        note: String = ""
    ): Result<ApprovalRequest> = withContext(Dispatchers.IO) {
        val currentRole = _operatorRole.value
        if (currentRole != OperatorRole.ADMIN) {
            recordAudit(
                actor = "current_user",
                role = currentRole,
                action = if (approve) "APPROVE_REQUEST" else "REJECT_REQUEST",
                target = approvalId,
                outcome = "DENIED_RBAC",
                detail = "Permission denied: ADMIN role required for Tier-2 approval decisions"
            )
            return@withContext Result.failure(
                SecurityException("สิทธิ์ไม่เพียงพอ: ต้องใช้บทบาท Admin เพื่ออนุมัติหรือปฏิเสธคำขอ Tier-2")
            )
        }

        var updatedItem: ApprovalRequest? = null
        storeMutex.withLock {
            val nextList = _approvals.value.map { req ->
                if (req.id == approvalId && req.status == ApprovalStatus.PENDING_APPROVAL) {
                    val decided = req.copy(
                        status = if (approve) ApprovalStatus.APPROVED else ApprovalStatus.REJECTED,
                        decidedBy = "admin_console",
                        decisionNote = note.ifBlank {
                            if (approve) "Approved after reviewing Evidence & Run ID" else "Rejected by Admin"
                        },
                        decidedAtIso = Instant.now().toString()
                    )
                    updatedItem = decided
                    decided
                } else {
                    req
                }
            }
            _approvals.value = nextList
            persistLocked()
        }

        val finalItem = updatedItem
            ?: return@withContext Result.failure(IllegalStateException("ไม่พบคำขอที่รออนุมัติ: $approvalId"))

        recordAudit(
            actor = "admin_console",
            role = currentRole,
            action = if (approve) "APPROVE_TIER2_GATE" else "REJECT_TIER2_GATE",
            target = "${finalItem.id} (${finalItem.actionType})",
            outcome = finalItem.status.name,
            detail = finalItem.decisionNote ?: ""
        )
        Result.success(finalItem)
    }

    suspend fun switchOperatorRole(role: OperatorRole) = withContext(Dispatchers.IO) {
        _operatorRole.value = role
        storeMutex.withLock {
            persistLocked()
        }
        recordAudit(
            actor = "session_role_switch",
            role = role,
            action = "SWITCH_OPERATOR_ROLE",
            target = role.name,
            outcome = "UPDATED",
            detail = "Active permission profile changed to ${role.label}"
        )
    }

    fun getLatestFailureReport(): RestoreProofReport? =
        _reports.value.firstOrNull { !it.overallPassed }

    fun getReportById(runId: String): RestoreProofReport? =
        _reports.value.firstOrNull { it.runId.equals(runId, ignoreCase = true) }

    fun exportReportJson(report: RestoreProofReport): String =
        json.encodeToString(report)

    private suspend fun appendReport(report: RestoreProofReport) {
        storeMutex.withLock {
            _reports.value = (listOf(report) + _reports.value).take(60)
            persistLocked()
        }
    }

    private suspend fun recordAudit(
        actor: String,
        role: OperatorRole,
        action: String,
        target: String,
        outcome: String,
        detail: String
    ) {
        val entry = AuditLogEntry(
            id = "AUD-${System.currentTimeMillis().toString().takeLast(6)}",
            actor = actor,
            role = role,
            action = action,
            target = target,
            outcome = outcome,
            detail = detail,
            timestampIso = Instant.now().toString()
        )
        storeMutex.withLock {
            _auditLogs.value = (listOf(entry) + _auditLogs.value).take(100)
            persistLocked()
        }
    }

    private fun loadSnapshot(): PersistedStoreSnapshot {
        if (!storeFile.exists()) return PersistedStoreSnapshot()
        return try {
            json.decodeFromString<PersistedStoreSnapshot>(storeFile.readText(Charsets.UTF_8))
        } catch (_: Exception) {
            PersistedStoreSnapshot()
        }
    }

    private fun persistLocked() {
        storeFile.parentFile?.mkdirs()
        val imported = _backupTargets.value.filter { it.isUserImported }
        val snapshot = PersistedStoreSnapshot(
            runCounter = runSeq.get(),
            reports = _reports.value,
            approvals = _approvals.value,
            auditLogs = _auditLogs.value,
            importedBackups = imported,
            operatorRole = _operatorRole.value,
            isolationGateState = _isolationGateState.value
        )
        storeFile.writeText(json.encodeToString(snapshot), Charsets.UTF_8)
    }
}
