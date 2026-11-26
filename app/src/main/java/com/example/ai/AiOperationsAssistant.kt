package com.example.ai

import android.util.Log
import com.example.data.EvidenceRepository
import com.example.domain.AiOperationPlan
import com.example.domain.AiPlanStep
import com.example.domain.RestoreProofReport
import com.google.firebase.Firebase
import com.google.firebase.ai.ai
import com.google.firebase.ai.type.Schema
import com.google.firebase.ai.type.generationConfig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.json.JSONObject

private const val TAG = "AiOperationsAssistant"

sealed interface AssistantExecutionEvent {
    data class Planned(val plan: AiOperationPlan) : AssistantExecutionEvent
    data class ToolExecuted(
        val reports: List<RestoreProofReport>,
        val proposedApprovalId: String?
    ) : AssistantExecutionEvent
    data class StreamingSummary(val accumulatedText: String) : AssistantExecutionEvent
    data class Completed(val finalText: String) : AssistantExecutionEvent
    data class Error(val message: String) : AssistantExecutionEvent
}

class AiOperationsAssistant(
    private val repository: EvidenceRepository
) {
    private val json = Json {
        prettyPrint = true
        ignoreUnknownKeys = true
    }

    private val planSchema = Schema.obj(
        properties = mapOf(
            "intentSummary" to Schema.string(description = "Concise Thai summary of what the operator wants"),
            "riskLevel" to Schema.enumeration(
                values = listOf("LOW", "MEDIUM", "HIGH"),
                description = "Operational risk level"
            ),
            "readinessCheck" to Schema.string(description = "Pre-execution readiness & isolation note in Thai"),
            "requiresApproval" to Schema.boolean(description = "True if any system change or remediation approval proposal is needed"),
            "toolsToInvoke" to Schema.array(
                items = Schema.enumeration(
                    values = listOf(
                        "VERIFY_ALL_BACKUPS",
                        "VERIFY_BACKUP_BY_HINT",
                        "VERIFY_ALL_SYNCS",
                        "RUN_ISOLATION_SUITE",
                        "INSPECT_LATEST_FAILURE",
                        "INSPECT_EVIDENCE_HISTORY",
                        "PROPOSE_REMEDIATION"
                    )
                ),
                description = "Deterministic backend verification tools to invoke"
            ),
            "targetHint" to Schema.string(description = "Optional target name/id or Run ID mentioned by user", nullable = true),
            "steps" to Schema.array(
                items = Schema.obj(
                    properties = mapOf(
                        "stepOrder" to Schema.integer(),
                        "title" to Schema.string(),
                        "toolName" to Schema.string(),
                        "detail" to Schema.string()
                    )
                ),
                description = "Sequential execution plan steps"
            ),
            "proposedRemediationTitle" to Schema.string(description = "Title for Approval Gate proposal if needed", nullable = true),
            "proposedRemediationCommand" to Schema.string(description = "Safe proposed command/action string if needed", nullable = true),
            "proposedRemediationReason" to Schema.string(description = "Technical rationale for proposed remediation", nullable = true)
        ),
        optionalProperties = listOf(
            "targetHint",
            "proposedRemediationTitle",
            "proposedRemediationCommand",
            "proposedRemediationReason"
        )
    )

    private val plannerModel by lazy {
        Firebase.ai.generativeModel(
            modelName = "gemini-3.8-flash",
            generationConfig = generationConfig {
                responseMimeType = "application/json"
                responseSchema = planSchema
            }
        )
    }

    private val analystModel by lazy {
        Firebase.ai.generativeModel(
            modelName = "gemini-3.8-flash"
        )
    }

    fun executeCommand(userPrompt: String): Flow<AssistantExecutionEvent> = flow {
        val availableBackups = repository.backupTargets.value.joinToString("\n") {
            "- id=${it.id}, name=${it.displayName}, desc=${it.description}"
        }
        val availableSyncs = repository.syncTargets.value.joinToString("\n") {
            "- id=${it.id}, name=${it.displayName}"
        }
        val recentRuns = repository.reports.value.take(6).joinToString("\n") {
            "- runId=${it.runId}, type=${it.probeType}, target=${it.targetName}, passed=${it.overallPassed}, discrepancies=${it.discrepancies.joinToString("; ")}"
        }.ifBlank { "ยังไม่มีประวัติ Run ในระบบ" }

        val systemContext = """
            คุณคือ RealityCheck AI Operations Assistant (ไม่ใช่แชตบอตทั่วไป)
            หน้าที่ของคุณ:
            1. เข้าใจคำสั่งภาษาธรรมชาติของผู้ปฏิบัติการ
            2. วางแผนขั้นตอนและประเมินความพร้อมและความเสี่ยงก่อนสั่งงานเครื่องมือจริง
            3. เลือกเรียกเครื่องมือที่เหมาะสมจากรายการที่อนุญาต (ห้ามแต่งผล PASS/FAIL เอง และห้ามสั่ง Restore ที่แก้ระบบจริงโดยไม่ได้รับอนุมัติ)

            สถานะระบบปัจจุบัน:
            - บทบาทผู้ใช้งาน: ${repository.operatorRole.value.name}
            - สถานะ Restore Gate: ${repository.isolationGateState.value.name} (คำสั่ง Restore จริงถูกล็อกจนกว่าจะผ่าน Isolation Test และ Admin Approval)

            Backup Targets ที่มีจริง:
            $availableBackups

            Sync Targets ที่มีจริง:
            $availableSyncs

            ประวัติ Evidence Runs ล่าสุด:
            $recentRuns

            คำสั่งจากผู้ปฏิบัติการ: "$userPrompt"
        """.trimIndent()

        // Phase 1: Structured Planning via Gemini 3.8 Flash
        val plan = try {
            val planResponse = withTimeout(45_000L) {
                plannerModel.generateContent(systemContext)
            }
            val rawJson = planResponse.text ?: throw IllegalStateException("AI planner returned empty plan")
            parsePlanJson(rawJson)
        } catch (e: TimeoutCancellationException) {
            Log.e(TAG, "AI planning timed out", e)
            emit(AssistantExecutionEvent.Error("การวางแผนงานของ AI ใช้เวลานานเกินกำหนด (45 วินาที)"))
            return@flow
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "AI planning failed", e)
            emit(
                AssistantExecutionEvent.Error(
                    e.localizedMessage ?: "ไม่สามารถเชื่อมต่อ Firebase AI Logic เพื่อวางแผนงานได้"
                )
            )
            return@flow
        }

        emit(AssistantExecutionEvent.Planned(plan))

        // Phase 2: Deterministic Tool Execution by RestoreProof Worker & Evidence Engine
        val executedReports = mutableListOf<RestoreProofReport>()
        val tools = plan.toolsToInvoke.distinct()
        var proposedApprovalId: String? = null

        for (tool in tools) {
            when (tool) {
                "VERIFY_ALL_BACKUPS" -> {
                    executedReports += repository.verifyAllBackups(actor = "ai_assistant_orchestrator")
                }
                "VERIFY_BACKUP_BY_HINT" -> {
                    val hint = plan.targetHint.orEmpty().lowercase()
                    val matched = repository.backupTargets.value.firstOrNull {
                        it.id.lowercase().contains(hint) || it.displayName.lowercase().contains(hint)
                    }
                    if (matched != null) {
                        executedReports += repository.verifyBackupTarget(matched.id, actor = "ai_assistant_orchestrator")
                    } else {
                        executedReports += repository.verifyAllBackups(actor = "ai_assistant_orchestrator")
                    }
                }
                "VERIFY_ALL_SYNCS" -> {
                    executedReports += repository.verifyAllSyncPairs(actor = "ai_assistant_orchestrator")
                }
                "RUN_ISOLATION_SUITE" -> {
                    executedReports += repository.runIsolationVerificationSuite(actor = "ai_assistant_orchestrator")
                }
                "INSPECT_LATEST_FAILURE" -> {
                    val hint = plan.targetHint.orEmpty()
                    val byId = if (hint.isNotBlank()) repository.getReportById(hint) else null
                    val targetReport = byId ?: repository.getLatestFailureReport()
                    if (targetReport != null) {
                        executedReports += targetReport
                    } else {
                        // Run real checks first if no failure exists in store yet
                        executedReports += repository.verifyAllBackups(actor = "ai_assistant_orchestrator")
                    }
                }
                "INSPECT_EVIDENCE_HISTORY" -> {
                    if (repository.reports.value.isNotEmpty()) {
                        executedReports += repository.reports.value.take(5)
                    } else {
                        executedReports += repository.verifyAllBackups(actor = "ai_assistant_orchestrator")
                    }
                }
                "PROPOSE_REMEDIATION" -> {
                    // Handled below after reports are gathered
                }
            }
        }

        val uniqueReports = executedReports.distinctBy { it.runId }
        val failedReports = uniqueReports.filter { !it.overallPassed }

        if (plan.requiresApproval || tools.contains("PROPOSE_REMEDIATION") || failedReports.isNotEmpty()) {
            val primaryFail = failedReports.firstOrNull()
            val reqTitle = plan.proposedRemediationTitle?.takeIf { it.isNotBlank() }
                ?: if (primaryFail != null) {
                    "กักกันและตรวจสอบซ้ำ: ${primaryFail.targetName} (${primaryFail.runId})"
                } else {
                    "อนุมัติดำเนินการตามแผน: ${plan.intentSummary}"
                }
            val reqCmd = plan.proposedRemediationCommand?.takeIf { it.isNotBlank() }
                ?: if (primaryFail != null) {
                    "quarantine --run-id ${primaryFail.runId} --target ${primaryFail.targetName} && regenerate-manifest"
                } else {
                    "restore-gate --verify-approval --isolation-checked"
                }
            val reqReason = plan.proposedRemediationReason?.takeIf { it.isNotBlank() }
                ?: if (primaryFail != null) {
                    "ตรวจพบความล้มเหลวจาก Verification Engine (${primaryFail.discrepancies.joinToString("; ")}) เสนอกักกันไฟล์และสร้าง Manifest ใหม่โดยต้องรอ Admin อนุมัติ"
                } else {
                    plan.readinessCheck
                }

            val approval = repository.proposeApprovalAction(
                title = reqTitle,
                actionType = if (primaryFail != null) "QUARANTINE_AND_REMEDIATE" else "OPERATIONAL_GATE_PROPOSAL",
                targetRunId = primaryFail?.runId ?: uniqueReports.firstOrNull()?.runId,
                rationale = reqReason,
                recommendedCommand = reqCmd,
                riskLevel = plan.riskLevel,
                proposedBy = "ai_operations_assistant"
            )
            proposedApprovalId = approval.id
        }

        emit(AssistantExecutionEvent.ToolExecuted(uniqueReports, proposedApprovalId))

        // Phase 3: Grounded Streaming Root-Cause Analysis & Summary from Real Evidence
        val evidenceJson = json.encodeToString(uniqueReports)
        val analysisPrompt = """
            คุณคือ RealityCheck AI Operations Assistant
            กฎเหล็ก:
            - ห้ามแต่งผล PASS เองเด็ดขาด ให้รายงานผล PASS/FAIL ตามหลักฐานจริงจาก Verification Engine ด้านล่างเท่านั้น
            - อ้างอิง Run ID, ชื่อ Target, ค่า SHA-256 (ย่อ 12 ตัวแรก), และ Logs/Discrepancies จริงเสมอ
            - หากพบความล้มเหลว ให้วิเคราะห์สาเหตุเชิงเทคนิค (Root Cause) จาก Discrepancies และ Worker Logs
            - แนะนำแนวทางแก้ไขพร้อมเหตุผล และย้ำว่าต้องผ่าน Approval Gate (รหัสคำขอ: ${proposedApprovalId ?: "ไม่มี"}) และยังไม่มีการแก้ระบบอัตโนมัติ
            - ตอบเป็นภาษาไทยที่กระชับ ชัดเจน อ่านง่าย แบ่งหัวข้อสั้นๆ

            คำสั่งผู้ปฏิบัติการ: "$userPrompt"
            แผนงานที่วางไว้: ${plan.intentSummary} (Risk: ${plan.riskLevel})
            สถานะ Restore Gate: ${repository.isolationGateState.value.name}

            หลักฐานจริงจาก RestoreProof Verification Engine & Evidence Engine:
            $evidenceJson
        """.trimIndent()

        val accumulated = StringBuilder()
        try {
            withTimeout(60_000L) {
                analystModel.generateContentStream(analysisPrompt).collect { chunk ->
                    val piece = chunk.text.orEmpty()
                    if (piece.isNotEmpty()) {
                        accumulated.append(piece)
                        emit(AssistantExecutionEvent.StreamingSummary(accumulated.toString()))
                    }
                }
            }
            val finalSummary = accumulated.toString()
            if (finalSummary.isNotBlank()) {
                emit(AssistantExecutionEvent.Completed(finalSummary))
            } else {
                emit(AssistantExecutionEvent.Error("โมเดลส่งผลวิเคราะห์กลับมาเป็นค่าว่าง"))
            }
        } catch (e: TimeoutCancellationException) {
            Log.e(TAG, "AI streaming timed out", e)
            emit(AssistantExecutionEvent.Error("การสรุปผลของ AI หมดเวลาหลังจาก 60 วินาที"))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "AI streaming failed", e)
            emit(
                AssistantExecutionEvent.Error(
                    e.localizedMessage ?: "การวิเคราะห์ผลลัพธ์ผ่าน Firebase AI Logic ล้มเหลว"
                )
            )
        }
    }

    private fun parsePlanJson(rawJson: String): AiOperationPlan {
        val obj = JSONObject(rawJson)
        val stepsArray = obj.optJSONArray("steps")
        val steps = if (stepsArray != null) {
            (0 until stepsArray.length()).map { idx ->
                val item = stepsArray.getJSONObject(idx)
                AiPlanStep(
                    stepOrder = item.optInt("stepOrder", idx + 1),
                    title = item.optString("title", "ขั้นตอนที่ ${idx + 1}"),
                    toolName = item.optString("toolName", "INSPECT_EVIDENCE_HISTORY"),
                    status = "PLANNED",
                    detail = item.optString("detail", "")
                )
            }
        } else {
            emptyList()
        }

        val toolsArray = obj.optJSONArray("toolsToInvoke")
        val tools = if (toolsArray != null) {
            (0 until toolsArray.length()).map { toolsArray.getString(it) }
        } else {
            listOf("INSPECT_EVIDENCE_HISTORY")
        }

        return AiOperationPlan(
            intentSummary = obj.optString("intentSummary", "ตรวจสอบสถานะและความปลอดภัยระบบ"),
            riskLevel = obj.optString("riskLevel", "LOW"),
            readinessCheck = obj.optString("readinessCheck", "พร้อมตรวจสอบแบบ Read-Only ในพื้นที่แยก (Isolated Sandbox)"),
            requiresApproval = obj.optBoolean("requiresApproval", false),
            steps = steps,
            toolsToInvoke = tools,
            targetHint = obj.optString("targetHint").takeIf { it.isNotBlank() && it != "null" },
            proposedRemediationTitle = obj.optString("proposedRemediationTitle").takeIf { it.isNotBlank() && it != "null" },
            proposedRemediationCommand = obj.optString("proposedRemediationCommand").takeIf { it.isNotBlank() && it != "null" },
            proposedRemediationReason = obj.optString("proposedRemediationReason").takeIf { it.isNotBlank() && it != "null" }
        )
    }
}
