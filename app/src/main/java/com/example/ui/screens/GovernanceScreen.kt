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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AdminPanelSettings
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.History
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.example.domain.ApprovalRequest
import com.example.domain.ApprovalStatus
import com.example.domain.AuditLogEntry
import com.example.domain.IsolationGateState
import com.example.domain.OperatorRole
import com.example.ui.components.RestoreSafetyGateBanner
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
import com.example.ui.theme.StatusPass
import com.example.ui.theme.VioletHighlight

@Composable
fun GovernanceScreen(
    operatorRole: OperatorRole,
    isolationGateState: IsolationGateState,
    approvals: List<ApprovalRequest>,
    auditLogs: List<AuditLogEntry>,
    onSwitchRole: (OperatorRole) -> Unit,
    onDecideApproval: (String, Boolean) -> Unit
) {
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
            item {
                RestoreSafetyGateBanner(isolationPassed = isolationPassed)
            }

            // RBAC Permission Profile Selector
            item {
                Card(
                    shape = RoundedCornerShape(18.dp),
                    colors = CardDefaults.cardColors(containerColor = SlateRaised),
                    border = BorderStroke(1.dp, SlateBorder)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.AdminPanelSettings,
                                contentDescription = null,
                                tint = NeonCyan,
                                modifier = Modifier.size(20.dp)
                            )
                            Text(
                                text = "บทบาทสิทธิ์ผู้ใช้งาน (RBAC Permission Gate)",
                                style = MaterialTheme.typography.titleMedium,
                                color = SoftWhite
                            )
                        }
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = "Operator สามารถสั่งตรวจ Read-Only และให้ AI วิเคราะห์ได้ แต่การอนุมัติคำขอแก้ไข/กักกัน (Tier-2 Gate) ต้องใช้สิทธิ์ Admin เท่านั้น",
                            style = MaterialTheme.typography.bodyMedium,
                            color = CoolGray
                        )
                        Spacer(modifier = Modifier.height(10.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            OperatorRole.entries.forEach { role ->
                                FilterChip(
                                    selected = operatorRole == role,
                                    onClick = { onSwitchRole(role) },
                                    label = { Text(role.badge) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = ElectricBlue,
                                        selectedLabelColor = SoftWhite,
                                        containerColor = SlateSurface,
                                        labelColor = CoolGray
                                    ),
                                    border = BorderStroke(1.dp, SlateBorder),
                                    modifier = Modifier.testTag("role_chip_${role.name}")
                                )
                            }
                        }
                    }
                }
            }

            // Tier-2 Approval Queue
            item {
                Text(
                    text = "คิวรออนุมัติ (Tier-2 Approval Gate)",
                    style = MaterialTheme.typography.titleMedium,
                    color = SoftWhite
                )
            }

            if (approvals.isEmpty()) {
                item {
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = SlateSurface,
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Text(
                            text = "ยังไม่มีคำขออนุมัติ เมื่อ AI Assistant หรือผู้ปฏิบัติการตรวจพบความผิดปกติและเสนอวิธีแก้ไข รายการจะมาปรากฏที่นี่เพื่อรอ Admin อนุมัติ",
                            style = MaterialTheme.typography.bodyMedium,
                            color = CoolGray,
                            modifier = Modifier.padding(16.dp)
                        )
                    }
                }
            } else {
                items(approvals, key = { it.id }) { req ->
                    Card(
                        shape = RoundedCornerShape(16.dp),
                        colors = CardDefaults.cardColors(containerColor = SlateRaised),
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Column(
                            modifier = Modifier.padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "${req.id} · ${req.actionType}",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = NeonCyan
                                )
                                StatusPill(
                                    label = req.status.name,
                                    tone = when (req.status) {
                                        ApprovalStatus.APPROVED -> StatusTone.PASS
                                        ApprovalStatus.REJECTED -> StatusTone.FAIL
                                        ApprovalStatus.PENDING_APPROVAL -> StatusTone.WARN
                                    }
                                )
                            }
                            Text(
                                text = req.title,
                                style = MaterialTheme.typography.titleMedium,
                                color = SoftWhite
                            )
                            Text(
                                text = req.rationale,
                                style = MaterialTheme.typography.bodyMedium,
                                color = CoolGray
                            )
                            Surface(
                                color = DeepGraphite,
                                shape = RoundedCornerShape(8.dp),
                                border = BorderStroke(1.dp, SlateBorder)
                            ) {
                                Text(
                                    text = req.recommendedCommand,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = VioletHighlight,
                                    modifier = Modifier.padding(8.dp)
                                )
                            }
                            if (req.status == ApprovalStatus.PENDING_APPROVAL) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    Button(
                                        onClick = { onDecideApproval(req.id, true) },
                                        modifier = Modifier
                                            .weight(1f)
                                            .minimumInteractiveComponentSize()
                                            .testTag("approve_${req.id}"),
                                        colors = ButtonDefaults.buttonColors(containerColor = StatusPass)
                                    ) {
                                        Icon(
                                            imageVector = Icons.Rounded.Check,
                                            contentDescription = null,
                                            tint = DeepGraphite,
                                            modifier = Modifier.size(16.dp)
                                        )
                                        Spacer(modifier = Modifier.width(4.dp))
                                        Text("อนุมัติ", color = DeepGraphite)
                                    }
                                    OutlinedButton(
                                        onClick = { onDecideApproval(req.id, false) },
                                        modifier = Modifier
                                            .weight(1f)
                                            .minimumInteractiveComponentSize()
                                            .testTag("reject_${req.id}"),
                                        border = BorderStroke(1.dp, StatusFail.copy(alpha = 0.6f))
                                    ) {
                                        Icon(
                                            imageVector = Icons.Rounded.Close,
                                            contentDescription = null,
                                            tint = StatusFail,
                                            modifier = Modifier.size(16.dp)
                                        )
                                        Spacer(modifier = Modifier.width(4.dp))
                                        Text("ปฏิเสธ", color = StatusFail)
                                    }
                                }
                            } else if (!req.decisionNote.isNullOrBlank()) {
                                Text(
                                    text = "บันทึกการตัดสินใจ (${req.decidedBy}): ${req.decisionNote}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MutedGray
                                )
                            }
                        }
                    }
                }
            }

            // Immutable Audit Trail
            item {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Icon(
                        imageVector = Icons.Rounded.History,
                        contentDescription = null,
                        tint = NeonCyan,
                        modifier = Modifier.size(18.dp)
                    )
                    Text(
                        text = "บันทึกตรวจสอบย้อนหลัง (Audit Trail)",
                        style = MaterialTheme.typography.titleMedium,
                        color = SoftWhite
                    )
                }
            }

            items(auditLogs.take(20), key = { it.id + it.timestampIso }) { log ->
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = SlateSurface,
                    border = BorderStroke(1.dp, SlateBorder)
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(
                                text = "${log.action} · ${log.outcome}",
                                style = MaterialTheme.typography.labelMedium,
                                color = when {
                                    log.outcome.contains("PASS") || log.outcome.contains("APPROVED") -> StatusPass
                                    log.outcome.contains("FAIL") || log.outcome.contains("DENIED") -> StatusFail
                                    else -> NeonCyan
                                }
                            )
                            Text(
                                text = log.role.badge,
                                style = MaterialTheme.typography.labelSmall,
                                color = MutedGray
                            )
                        }
                        Text(
                            text = "Target: ${log.target}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = SoftWhite
                        )
                        if (log.detail.isNotBlank()) {
                            Text(
                                text = log.detail,
                                style = MaterialTheme.typography.labelSmall,
                                color = CoolGray
                            )
                        }
                    }
                }
            }
        }
    }
}
