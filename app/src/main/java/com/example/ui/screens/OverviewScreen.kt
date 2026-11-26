package com.example.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Security
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.example.domain.ApprovalRequest
import com.example.domain.ApprovalStatus
import com.example.domain.BackupArchiveTarget
import com.example.domain.IsolationGateState
import com.example.domain.OperatorRole
import com.example.domain.RestoreProofReport
import com.example.ui.components.ReportSummaryCard
import com.example.ui.components.RestoreSafetyGateBanner
import com.example.ui.components.StatusPill
import com.example.ui.components.StatusTone
import com.example.ui.components.TelemetryMetricCard
import com.example.ui.components.TemporalVerificationCoreCanvas
import com.example.ui.theme.CoolGray
import com.example.ui.theme.DeepGraphite
import com.example.ui.theme.ElectricBlue
import com.example.ui.theme.MutedGray
import com.example.ui.theme.NeonCyan
import com.example.ui.theme.SlateBorder
import com.example.ui.theme.SlateRaised
import com.example.ui.theme.SlateSurface
import com.example.ui.theme.SoftWhite
import com.example.ui.theme.StatusFail
import com.example.ui.theme.StatusPass
import com.example.ui.theme.StatusWarn
import com.example.ui.theme.VioletHighlight

@Composable
fun OverviewScreen(
    backupTargets: List<BackupArchiveTarget>,
    reports: List<RestoreProofReport>,
    approvals: List<ApprovalRequest>,
    operatorRole: OperatorRole,
    isolationGateState: IsolationGateState,
    workerBusy: Boolean,
    onLaunchAiCommand: (String) -> Unit,
    onVerifyAllBackups: () -> Unit,
    onRunIsolationSuite: () -> Unit,
    onSelectReport: (RestoreProofReport) -> Unit,
    onNavigateVerify: () -> Unit
) {
    var quickCommand by rememberSaveable { mutableStateOf("") }
    val pendingApprovals = approvals.count { it.status == ApprovalStatus.PENDING_APPROVAL }
    val passedRuns = reports.count { it.overallPassed }
    val failedRuns = reports.count { !it.overallPassed }
    val isolationPassed = isolationGateState == IsolationGateState.ISOLATION_TESTS_PASSED_RESTORE_GATED

    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.TopCenter
    ) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .widthIn(max = 760.dp),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            // Hero Operations Core Card
            item {
                Card(
                    shape = RoundedCornerShape(22.dp),
                    colors = CardDefaults.cardColors(containerColor = SlateRaised),
                    border = BorderStroke(1.dp, ElectricBlue.copy(alpha = 0.4f))
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(14.dp)
                        ) {
                            TemporalVerificationCoreCanvas(
                                active = workerBusy,
                                size = 70.dp
                            )
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = "REALITYCHECK · RESTOREPROOF",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = NeonCyan
                                )
                                Text(
                                    text = "ศูนย์ควบคุมตรวจสอบและกู้คืนข้อมูล",
                                    style = MaterialTheme.typography.titleLarge,
                                    color = SoftWhite
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                StatusPill(
                                    label = "ROLE: ${operatorRole.badge}",
                                    tone = if (operatorRole == OperatorRole.ADMIN) StatusTone.INFO else StatusTone.WARN
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(14.dp))
                        RestoreSafetyGateBanner(isolationPassed = isolationPassed)
                    }
                }
            }

            // Quick AI Operations Assistant Launcher
            item {
                Card(
                    shape = RoundedCornerShape(18.dp),
                    colors = CardDefaults.cardColors(containerColor = SlateSurface),
                    border = BorderStroke(1.dp, SlateBorder)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.AutoAwesome,
                                contentDescription = null,
                                tint = NeonCyan,
                                modifier = Modifier.size(18.dp)
                            )
                            Text(
                                text = "สั่งงาน AI Operations Assistant",
                                style = MaterialTheme.typography.titleMedium,
                                color = SoftWhite
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "AI วางแผน เรียก Worker ตรวจจริง และวิเคราะห์ข้อผิดพลาดจาก Logs/Evidence เท่านั้น",
                            style = MaterialTheme.typography.bodyMedium,
                            color = CoolGray
                        )
                        Spacer(modifier = Modifier.height(10.dp))

                        OutlinedTextField(
                            value = quickCommand,
                            onValueChange = { quickCommand = it },
                            placeholder = {
                                Text(
                                    "เช่น ตรวจสอบ Backup ล่าสุดทั้งหมด หรือ วิเคราะห์ Run ที่ล้มเหลว",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MutedGray
                                )
                            },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                            keyboardActions = KeyboardActions(
                                onSend = {
                                    val cmd = quickCommand.trim().ifEmpty { "ตรวจสอบ Backup ล่าสุดทั้งหมด" }
                                    quickCommand = ""
                                    onLaunchAiCommand(cmd)
                                }
                            ),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = NeonCyan,
                                unfocusedBorderColor = SlateBorder,
                                focusedTextColor = SoftWhite,
                                unfocusedTextColor = SoftWhite,
                                focusedContainerColor = DeepGraphite,
                                unfocusedContainerColor = DeepGraphite
                            ),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier
                                .fillMaxWidth()
                                .testTag("overview_ai_input")
                        )

                        Spacer(modifier = Modifier.height(10.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            Button(
                                onClick = {
                                    val cmd = quickCommand.trim().ifEmpty { "ตรวจสอบ Backup ล่าสุดทั้งหมด" }
                                    quickCommand = ""
                                    onLaunchAiCommand(cmd)
                                },
                                modifier = Modifier
                                    .weight(1f)
                                    .minimumInteractiveComponentSize()
                                    .testTag("overview_ai_submit"),
                                colors = ButtonDefaults.buttonColors(containerColor = ElectricBlue)
                            ) {
                                Icon(
                                    imageVector = Icons.AutoMirrored.Rounded.Send,
                                    contentDescription = null,
                                    modifier = Modifier.size(16.dp)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("ส่งคำสั่งให้ AI", fontWeight = FontWeight.SemiBold)
                            }
                        }
                    }
                }
            }

            // Telemetry Metrics Grid (2x2)
            item {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        TelemetryMetricCard(
                            label = "BACKUP TARGETS",
                            value = "${backupTargets.size}",
                            caption = "ชุดสำรองข้อมูลที่พร้อมตรวจ",
                            accentColor = NeonCyan,
                            modifier = Modifier.weight(1f)
                        )
                        TelemetryMetricCard(
                            label = "EVIDENCE RUNS",
                            value = "${reports.size}",
                            caption = "PASS $passedRuns • FAIL $failedRuns",
                            accentColor = if (failedRuns > 0) StatusFail else StatusPass,
                            modifier = Modifier.weight(1f)
                        )
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        TelemetryMetricCard(
                            label = "APPROVAL GATE",
                            value = "$pendingApprovals",
                            caption = "รายการรออนุมัติจาก Admin",
                            accentColor = if (pendingApprovals > 0) StatusWarn else VioletHighlight,
                            modifier = Modifier.weight(1f)
                        )
                        TelemetryMetricCard(
                            label = "ISOLATION TEST",
                            value = if (isolationPassed) "VERIFIED" else "PENDING",
                            caption = if (isolationPassed) "ผ่านการตรวจ 4-Wave แล้ว" else "ต้องรันทดสอบแยกสภาพแวดล้อม",
                            accentColor = if (isolationPassed) StatusPass else StatusWarn,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }

            // Direct Worker Actions
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Button(
                        onClick = onVerifyAllBackups,
                        enabled = !workerBusy,
                        modifier = Modifier
                            .weight(1f)
                            .minimumInteractiveComponentSize()
                            .testTag("overview_verify_all_button"),
                        colors = ButtonDefaults.buttonColors(containerColor = ElectricBlue)
                    ) {
                        if (workerBusy) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                                color = SoftWhite
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Rounded.PlayArrow,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("ตรวจ Backup ทั้งหมด", maxLines = 1)
                    }

                    OutlinedButton(
                        onClick = onRunIsolationSuite,
                        enabled = !workerBusy,
                        modifier = Modifier
                            .weight(1f)
                            .minimumInteractiveComponentSize()
                            .testTag("overview_isolation_suite_button"),
                        border = BorderStroke(1.dp, NeonCyan.copy(alpha = 0.55f))
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Security,
                            contentDescription = null,
                            tint = NeonCyan,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("ทดสอบ Isolation", color = NeonCyan, maxLines = 1)
                    }
                }
            }

            // Clear Separation of Responsibilities Matrix
            item {
                Surface(
                    shape = RoundedCornerShape(16.dp),
                    color = SlateSurface,
                    border = BorderStroke(1.dp, SlateBorder)
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.Shield,
                                contentDescription = null,
                                tint = VioletHighlight,
                                modifier = Modifier.size(16.dp)
                            )
                            Text(
                                text = "การแบ่งหน้าที่ความรับผิดชอบ (Zero Fake Capability)",
                                style = MaterialTheme.typography.titleMedium,
                                color = SoftWhite
                            )
                        }
                        ResponsibilityRow("AI Assistant", "เข้าใจคำสั่ง วางแผน วิเคราะห์ Logs (ไม่มีสิทธิ์แต่ง PASS)")
                        ResponsibilityRow("Backend Gate", "ตรวจสิทธิ์ RBAC และควบคุม Tier-2 Approval")
                        ResponsibilityRow("Verification & Worker", "แตกไฟล์ใน Sandbox + ตรวจ SHA-256 จริง")
                        ResponsibilityRow("Evidence Engine", "ออก Run ID และหลักฐาน JSON ที่ตรวจย้อนหลังได้")
                    }
                }
            }

            // Recent Evidence Runs
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "ผลตรวจสอบล่าสุดจาก Worker",
                        style = MaterialTheme.typography.titleMedium,
                        color = SoftWhite
                    )
                    OutlinedButton(
                        onClick = onNavigateVerify,
                        modifier = Modifier.minimumInteractiveComponentSize(),
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Text("ดูทั้งหมด", color = NeonCyan)
                    }
                }
            }

            if (reports.isEmpty()) {
                item {
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = SlateSurface,
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(20.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(
                                text = "ยังไม่มีประวัติการตรวจสอบ",
                                style = MaterialTheme.typography.titleMedium,
                                color = SoftWhite
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "กด \"ตรวจ Backup ทั้งหมด\" หรือสั่ง AI Operations Assistant เพื่อเริ่มรัน RestoreProof Worker จริง",
                                style = MaterialTheme.typography.bodyMedium,
                                color = CoolGray
                            )
                        }
                    }
                }
            } else {
                items(reports.take(4), key = { it.runId }) { report ->
                    ReportSummaryCard(
                        report = report,
                        onClick = { onSelectReport(report) }
                    )
                }
            }
        }
    }
}

@Composable
private fun ResponsibilityRow(role: String, duty: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            text = role,
            style = MaterialTheme.typography.labelMedium,
            color = NeonCyan,
            modifier = Modifier.width(126.dp)
        )
        Text(
            text = duty,
            style = MaterialTheme.typography.bodyMedium,
            color = CoolGray,
            modifier = Modifier.weight(1f)
        )
    }
}
