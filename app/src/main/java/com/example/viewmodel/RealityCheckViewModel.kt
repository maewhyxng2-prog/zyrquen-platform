package com.example.viewmodel

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.ai.AiOperationsAssistant
import com.example.ai.AssistantExecutionEvent
import com.example.data.EvidenceRepository
import com.example.domain.ApprovalRequest
import com.example.domain.AssistantTurn
import com.example.domain.AuditLogEntry
import com.example.domain.BackupArchiveTarget
import com.example.domain.IsolationGateState
import com.example.domain.OperatorRole
import com.example.domain.RestoreProofReport
import com.example.domain.SyncPairTarget
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.Instant
import java.util.UUID

class RealityCheckViewModel(application: Application) : AndroidViewModel(application) {

    private val repository = EvidenceRepository(application.applicationContext)
    private val aiAssistant = AiOperationsAssistant(repository)

    val backupTargets: StateFlow<List<BackupArchiveTarget>> = repository.backupTargets
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val syncTargets: StateFlow<List<SyncPairTarget>> = repository.syncTargets
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val reports: StateFlow<List<RestoreProofReport>> = repository.reports
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val approvals: StateFlow<List<ApprovalRequest>> = repository.approvals
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val auditLogs: StateFlow<List<AuditLogEntry>> = repository.auditLogs
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val operatorRole: StateFlow<OperatorRole> = repository.operatorRole
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), OperatorRole.OPERATOR)

    val isolationGateState: StateFlow<IsolationGateState> = repository.isolationGateState
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), IsolationGateState.LOCKED)

    private val _selectedReport = MutableStateFlow<RestoreProofReport?>(null)
    val selectedReport: StateFlow<RestoreProofReport?> = _selectedReport.asStateFlow()

    private val _workerBusy = MutableStateFlow(false)
    val workerBusy: StateFlow<Boolean> = _workerBusy.asStateFlow()

    private val _assistantBusy = MutableStateFlow(false)
    val assistantBusy: StateFlow<Boolean> = _assistantBusy.asStateFlow()

    private val _assistantTurns = MutableStateFlow<List<AssistantTurn>>(emptyList())
    val assistantTurns: StateFlow<List<AssistantTurn>> = _assistantTurns.asStateFlow()

    private val _bannerNotice = MutableStateFlow<String?>(null)
    val bannerNotice: StateFlow<String?> = _bannerNotice.asStateFlow()

    init {
        viewModelScope.launch {
            repository.initialize()
            _selectedReport.value = repository.reports.value.firstOrNull()
        }
    }

    fun selectReport(report: RestoreProofReport?) {
        _selectedReport.value = report
    }

    fun clearBannerNotice() {
        _bannerNotice.value = null
    }

    fun verifyBackup(targetId: String) {
        if (_workerBusy.value) return
        viewModelScope.launch {
            _workerBusy.value = true
            try {
                val report = repository.verifyBackupTarget(targetId)
                _selectedReport.value = report
                _bannerNotice.value =
                    "Run ${report.runId}: ${report.targetName} -> ${if (report.overallPassed) "PASS" else "FAIL"}"
            } catch (e: Exception) {
                _bannerNotice.value = e.localizedMessage ?: "การตรวจสอบล้มเหลว"
            } finally {
                _workerBusy.value = false
            }
        }
    }

    fun verifyAllBackups() {
        if (_workerBusy.value) return
        viewModelScope.launch {
            _workerBusy.value = true
            try {
                val results = repository.verifyAllBackups()
                _selectedReport.value = results.lastOrNull() ?: results.firstOrNull()
                val passed = results.count { it.overallPassed }
                _bannerNotice.value = "ตรวจสอบ Backup ทั้งหมด ${results.size} ชุดเสร็จสิ้น (PASS $passed / FAIL ${results.size - passed})"
            } catch (e: Exception) {
                _bannerNotice.value = e.localizedMessage ?: "ไม่สามารถตรวจสอบทั้งหมดได้"
            } finally {
                _workerBusy.value = false
            }
        }
    }

    fun verifySyncPair(syncId: String) {
        if (_workerBusy.value) return
        viewModelScope.launch {
            _workerBusy.value = true
            try {
                val report = repository.verifySyncPair(syncId)
                _selectedReport.value = report
                _bannerNotice.value =
                    "Sync Probe ${report.runId}: ${if (report.overallPassed) "PASS" else "DRIFT/FAIL"}"
            } catch (e: Exception) {
                _bannerNotice.value = e.localizedMessage ?: "ตรวจสอบ Sync ล้มเหลว"
            } finally {
                _workerBusy.value = false
            }
        }
    }

    fun runIsolationSuite() {
        if (_workerBusy.value) return
        viewModelScope.launch {
            _workerBusy.value = true
            try {
                val report = repository.runIsolationVerificationSuite()
                _selectedReport.value = report
                _bannerNotice.value = if (report.overallPassed) {
                    "Isolation Suite ${report.runId} PASS — ยืนยันการแยกสภาพแวดล้อมและตรวจจับความล้มเหลวครบ 4 รูปแบบแล้ว"
                } else {
                    "Isolation Suite ${report.runId} FAIL — ${report.discrepancies.joinToString("; ")}"
                }
            } catch (e: Exception) {
                _bannerNotice.value = e.localizedMessage ?: "การทดสอบ Isolation ล้มเหลว"
            } finally {
                _workerBusy.value = false
            }
        }
    }

    fun importAndVerifyUserArchive(uri: Uri, displayName: String) {
        if (_workerBusy.value) return
        viewModelScope.launch {
            _workerBusy.value = true
            try {
                val report = repository.importAndVerifyUri(uri, displayName)
                _selectedReport.value = report
                _bannerNotice.value = "นำเข้าและตรวจไฟล์ '$displayName' (${report.runId}): ${if (report.overallPassed) "PASS" else "FAIL"}"
            } catch (e: Exception) {
                _bannerNotice.value = e.localizedMessage ?: "ไม่สามารถอ่านไฟล์ Backup ที่เลือกได้"
            } finally {
                _workerBusy.value = false
            }
        }
    }

    fun sendAssistantCommand(prompt: String) {
        val trimmed = prompt.trim()
        if (trimmed.isEmpty() || _assistantBusy.value) return

        val turnId = "TURN-${UUID.randomUUID().toString().take(8)}"
        val initialTurn = AssistantTurn(
            id = turnId,
            userPrompt = trimmed,
            isStreaming = true,
            createdAtIso = Instant.now().toString()
        )
        _assistantTurns.value = listOf(initialTurn) + _assistantTurns.value
        _assistantBusy.value = true

        viewModelScope.launch {
            try {
                aiAssistant.executeCommand(trimmed).collect { event ->
                    when (event) {
                        is AssistantExecutionEvent.Planned -> {
                            updateTurn(turnId) { it.copy(plan = event.plan) }
                        }
                        is AssistantExecutionEvent.ToolExecuted -> {
                            val updatedPlan = _assistantTurns.value.firstOrNull { it.id == turnId }?.plan?.let { p ->
                                p.copy(steps = p.steps.map { s -> s.copy(status = "EXECUTED") })
                            }
                            if (event.reports.isNotEmpty()) {
                                _selectedReport.value = event.reports.first()
                            }
                            updateTurn(turnId) {
                                it.copy(
                                    plan = updatedPlan,
                                    executedRunIds = event.reports.map { r -> r.runId },
                                    executedReports = event.reports,
                                    proposedApprovalId = event.proposedApprovalId
                                )
                            }
                        }
                        is AssistantExecutionEvent.StreamingSummary -> {
                            updateTurn(turnId) {
                                it.copy(aiSummary = event.accumulatedText, isStreaming = true)
                            }
                        }
                        is AssistantExecutionEvent.Completed -> {
                            updateTurn(turnId) {
                                it.copy(aiSummary = event.finalText, isStreaming = false)
                            }
                        }
                        is AssistantExecutionEvent.Error -> {
                            updateTurn(turnId) {
                                it.copy(errorMessage = event.message, isStreaming = false)
                            }
                        }
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                updateTurn(turnId) {
                    it.copy(
                        errorMessage = e.localizedMessage ?: "เกิดข้อผิดพลาดระหว่างประมวลผล AI Assistant",
                        isStreaming = false
                    )
                }
            } finally {
                _assistantBusy.value = false
            }
        }
    }

    fun switchRole(role: OperatorRole) {
        viewModelScope.launch {
            repository.switchOperatorRole(role)
            _bannerNotice.value = "เปลี่ยนบทบาทปัจจุบันเป็น ${role.badge}"
        }
    }

    fun decideApproval(approvalId: String, approve: Boolean) {
        viewModelScope.launch {
            val result = repository.decideApproval(approvalId, approve)
            result.onSuccess { req ->
                _bannerNotice.value =
                    "คำขอ ${req.id}: ${if (approve) "อนุมัติแล้ว" else "ปฏิเสธแล้ว"} โดย Admin"
            }.onFailure { err ->
                _bannerNotice.value = err.localizedMessage ?: "ไม่สามารถบันทึกผลการอนุมัติได้"
            }
        }
    }

    fun exportReportJson(report: RestoreProofReport): String =
        repository.exportReportJson(report)

    private fun updateTurn(turnId: String, transform: (AssistantTurn) -> AssistantTurn) {
        _assistantTurns.value = _assistantTurns.value.map { turn ->
            if (turn.id == turnId) transform(turn) else turn
        }
    }
}
