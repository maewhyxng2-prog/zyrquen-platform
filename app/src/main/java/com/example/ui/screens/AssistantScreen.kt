package com.example.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.GppMaybe
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import com.example.domain.AssistantTurn
import com.example.domain.RestoreProofReport
import com.example.ui.components.ReportSummaryCard
import com.example.ui.components.StatusPill
import com.example.ui.components.StatusTone
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
import com.example.ui.theme.StatusFailBg
import com.example.ui.theme.StatusInfoBg
import com.example.ui.theme.StatusWarn
import com.example.ui.theme.VioletHighlight

private val QUICK_PROMPTS = listOf(
    "ตรวจสอบ Backup ล่าสุดทั้งหมด",
    "วิเคราะห์สาเหตุที่ Restore ล้มเหลวล่าสุด",
    "ทดสอบการแยกสภาพแวดล้อม (Isolation Suite)",
    "ตรวจสอบ Sync Drift ระหว่าง Primary กับ Replica"
)

@Composable
fun AssistantScreen(
    turns: List<AssistantTurn>,
    assistantBusy: Boolean,
    onSendCommand: (String) -> Unit,
    onSelectReport: (RestoreProofReport) -> Unit,
    onOpenApprovals: () -> Unit
) {
    var input by rememberSaveable { mutableStateOf("") }

    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.TopCenter
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .widthIn(max = 760.dp)
        ) {
            // Integrity & Role Boundary Banner
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                shape = RoundedCornerShape(14.dp),
                color = StatusInfoBg,
                border = BorderStroke(1.dp, NeonCyan.copy(alpha = 0.35f))
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Icon(
                        imageVector = Icons.Rounded.VerifiedUser,
                        contentDescription = null,
                        tint = NeonCyan,
                        modifier = Modifier.size(18.dp)
                    )
                    Text(
                        text = "AI Operations Assistant (Gemini 3.8 Flash): วางแผน เรียก Worker ตรวจจริง และวิเคราะห์ Evidence — ไม่มีสิทธิ์แต่งผล PASS เอง",
                        style = MaterialTheme.typography.bodyMedium,
                        color = SoftWhite
                    )
                }
            }

            // Quick Operational Command Chips
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                QUICK_PROMPTS.forEachIndexed { idx, promptText ->
                    AssistChip(
                        onClick = { if (!assistantBusy) onSendCommand(promptText) },
                        label = {
                            Text(
                                text = promptText,
                                style = MaterialTheme.typography.bodyMedium,
                                color = SoftWhite
                            )
                        },
                        enabled = !assistantBusy,
                        colors = AssistChipDefaults.assistChipColors(containerColor = SlateRaised),
                        border = BorderStroke(1.dp, SlateBorder),
                        modifier = Modifier.testTag("assistant_chip_$idx")
                    )
                }
            }

            // Conversation & Execution Turns
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
                reverseLayout = true
            ) {
                if (turns.isEmpty()) {
                    item {
                        Card(
                            shape = RoundedCornerShape(18.dp),
                            colors = CardDefaults.cardColors(containerColor = SlateSurface),
                            border = BorderStroke(1.dp, SlateBorder)
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(20.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.AutoAwesome,
                                    contentDescription = null,
                                    tint = NeonCyan,
                                    modifier = Modifier.size(26.dp)
                                )
                                Text(
                                    text = "พร้อมรับคำสั่งปฏิบัติการ",
                                    style = MaterialTheme.typography.titleLarge,
                                    color = SoftWhite
                                )
                                Text(
                                    text = "ลองพิมพ์หรือกดคำสั่งด้านบน เพื่อให้ AI Assistant วางแผนงาน สั่ง RestoreProof Worker ตรวจ Backup จริง และสรุปผลพร้อม Run ID และหลักฐาน SHA-256",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = CoolGray
                                )
                            }
                        }
                    }
                } else {
                    items(turns, key = { it.id }) { turn ->
                        AssistantTurnCard(
                            turn = turn,
                            onSelectReport = onSelectReport,
                            onOpenApprovals = onOpenApprovals
                        )
                    }
                }
            }

            // Command Composer Bar
            Surface(
                color = SlateSurface,
                tonalElevation = 4.dp,
                border = BorderStroke(1.dp, SlateBorder)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedTextField(
                        value = input,
                        onValueChange = { input = it },
                        placeholder = {
                            Text(
                                "สั่งงาน AI Assistant (เช่น ตรวจสอบ Backup ล่าสุด)...",
                                color = MutedGray,
                                style = MaterialTheme.typography.bodyMedium
                            )
                        },
                        maxLines = 3,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                        keyboardActions = KeyboardActions(
                            onSend = {
                                val cmd = input.trim()
                                if (cmd.isNotEmpty() && !assistantBusy) {
                                    input = ""
                                    onSendCommand(cmd)
                                }
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
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier
                            .weight(1f)
                            .testTag("assistant_command_input")
                    )

                    IconButton(
                        onClick = {
                            val cmd = input.trim()
                            if (cmd.isNotEmpty() && !assistantBusy) {
                                input = ""
                                onSendCommand(cmd)
                            }
                        },
                        enabled = input.isNotBlank() && !assistantBusy,
                        modifier = Modifier
                            .minimumInteractiveComponentSize()
                            .size(48.dp)
                            .testTag("assistant_send_button")
                    ) {
                        if (assistantBusy) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                strokeWidth = 2.dp,
                                color = NeonCyan
                            )
                        } else {
                            Icon(
                                imageVector = Icons.AutoMirrored.Rounded.Send,
                                contentDescription = "ส่งคำสั่ง",
                                tint = if (input.isNotBlank()) NeonCyan else MutedGray
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AssistantTurnCard(
    turn: AssistantTurn,
    onSelectReport: (RestoreProofReport) -> Unit,
    onOpenApprovals: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // User Command Bubble
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End
        ) {
            Surface(
                shape = RoundedCornerShape(16.dp, 4.dp, 16.dp, 16.dp),
                color = ElectricBlue
            ) {
                Text(
                    text = turn.userPrompt,
                    style = MaterialTheme.typography.bodyLarge,
                    color = SoftWhite,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                )
            }
        }

        // Assistant Execution Pipeline Card
        Card(
            shape = RoundedCornerShape(18.dp),
            colors = CardDefaults.cardColors(containerColor = SlateRaised),
            border = BorderStroke(1.dp, SlateBorder)
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "AI OPERATIONS PIPELINE",
                        style = MaterialTheme.typography.labelMedium,
                        color = NeonCyan
                    )
                    if (turn.isStreaming) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(14.dp),
                                strokeWidth = 2.dp,
                                color = NeonCyan
                            )
                            Text(
                                text = "กำลังประมวลผล...",
                                style = MaterialTheme.typography.labelSmall,
                                color = CoolGray
                            )
                        }
                    }
                }

                // 1. Plan & Risk Assessment
                turn.plan?.let { plan ->
                    Surface(
                        color = DeepGraphite,
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "1) แผนปฏิบัติการ: ${plan.intentSummary}",
                                    style = MaterialTheme.typography.labelLarge,
                                    color = SoftWhite,
                                    modifier = Modifier.weight(1f)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                StatusPill(
                                    label = "RISK: ${plan.riskLevel}",
                                    tone = when (plan.riskLevel) {
                                        "HIGH" -> StatusTone.FAIL
                                        "MEDIUM" -> StatusTone.WARN
                                        else -> StatusTone.INFO
                                    }
                                )
                            }
                            Text(
                                text = "Readiness: ${plan.readinessCheck}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = CoolGray
                            )
                            plan.steps.forEach { step ->
                                Text(
                                    text = "• Step ${step.stepOrder} [${step.toolName}] (${step.status}): ${step.title}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MutedGray
                                )
                            }
                        }
                    }
                }

                // 2. Real Deterministic Tool Outputs
                if (turn.executedReports.isNotEmpty()) {
                    Text(
                        text = "2) ผลตรวจจริงจาก RestoreProof Worker (${turn.executedReports.size} Run)",
                        style = MaterialTheme.typography.labelLarge,
                        color = VioletHighlight
                    )
                    turn.executedReports.forEach { report ->
                        ReportSummaryCard(
                            report = report,
                            onClick = { onSelectReport(report) }
                        )
                    }
                }

                // 3. Proposed Approval Gate Card
                turn.proposedApprovalId?.let { approvalId ->
                    Surface(
                        color = SlateSurface,
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, StatusWarn.copy(alpha = 0.5f))
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                modifier = Modifier.weight(1f)
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.GppMaybe,
                                    contentDescription = null,
                                    tint = StatusWarn,
                                    modifier = Modifier.size(18.dp)
                                )
                                Column {
                                    Text(
                                        text = "ส่งข้อเสนอเข้า Approval Gate ($approvalId)",
                                        style = MaterialTheme.typography.labelLarge,
                                        color = StatusWarn
                                    )
                                    Text(
                                        text = "รออนุมัติจาก Admin ก่อนดำเนินการแก้ไขระบบ",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = CoolGray
                                    )
                                }
                            }
                            Spacer(modifier = Modifier.width(8.dp))
                            OutlinedButton(
                                onClick = onOpenApprovals,
                                modifier = Modifier.minimumInteractiveComponentSize(),
                                border = BorderStroke(1.dp, StatusWarn.copy(alpha = 0.6f))
                            ) {
                                Text("ตรวจสอบ", color = StatusWarn)
                            }
                        }
                    }
                }

                // 4. Error Banner or AI Grounded Analysis
                turn.errorMessage?.let { err ->
                    Surface(
                        color = StatusFailBg,
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, StatusFail.copy(alpha = 0.5f))
                    ) {
                        Text(
                            text = "AI Assistant Error: $err",
                            style = MaterialTheme.typography.bodyMedium,
                            color = StatusFail,
                            modifier = Modifier.padding(12.dp)
                        )
                    }
                }

                if (turn.aiSummary.isNotBlank()) {
                    HorizontalDivider(color = SlateBorder)
                    Text(
                        text = "3) การวิเคราะห์และข้อเสนอแนะ (อ้างอิง Run ID & Evidence)",
                        style = MaterialTheme.typography.labelLarge,
                        color = NeonCyan
                    )
                    Text(
                        text = turn.aiSummary,
                        style = MaterialTheme.typography.bodyLarge,
                        color = SoftWhite
                    )
                }
            }
        }
    }
}
