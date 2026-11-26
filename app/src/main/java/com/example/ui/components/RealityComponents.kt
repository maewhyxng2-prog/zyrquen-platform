package com.example.ui.components

import android.content.Intent
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.domain.RestoreProofReport
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
import com.example.ui.theme.StatusInfo
import com.example.ui.theme.StatusInfoBg
import com.example.ui.theme.StatusPass
import com.example.ui.theme.StatusPassBg
import com.example.ui.theme.StatusWarn
import com.example.ui.theme.StatusWarnBg
import com.example.ui.theme.VioletHighlight

enum class StatusTone {
    PASS,
    WARN,
    FAIL,
    INFO
}

@Composable
fun StatusPill(
    label: String,
    tone: StatusTone,
    modifier: Modifier = Modifier
) {
    val (fg, bg, icon) = when (tone) {
        StatusTone.PASS -> Triple(StatusPass, StatusPassBg, Icons.Rounded.CheckCircle)
        StatusTone.WARN -> Triple(StatusWarn, StatusWarnBg, Icons.Rounded.Schedule)
        StatusTone.FAIL -> Triple(StatusFail, StatusFailBg, Icons.Rounded.ErrorOutline)
        StatusTone.INFO -> Triple(StatusInfo, StatusInfoBg, Icons.Rounded.VerifiedUser)
    }

    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(999.dp),
        color = bg,
        border = BorderStroke(1.dp, fg.copy(alpha = 0.4f))
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = fg,
                modifier = Modifier.size(13.dp)
            )
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = fg,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

@Composable
fun TemporalVerificationCoreCanvas(
    active: Boolean,
    size: Dp = 76.dp,
    modifier: Modifier = Modifier
) {
    val transition = rememberInfiniteTransition(label = "core_orbit")
    val angle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = if (active) 4000 else 12000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "orbit_angle"
    )

    Canvas(modifier = modifier.size(size)) {
        val center = Offset(this.size.width / 2f, this.size.height / 2f)
        val outerR = this.size.minDimension * 0.44f
        val innerR = this.size.minDimension * 0.28f

        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(NeonCyan.copy(alpha = 0.22f), Color.Transparent),
                center = center,
                radius = outerR * 1.15f
            ),
            radius = outerR * 1.15f,
            center = center
        )

        rotate(angle, pivot = center) {
            drawCircle(
                color = ElectricBlue.copy(alpha = 0.75f),
                radius = outerR,
                center = center,
                style = Stroke(
                    width = 2.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(18f, 10f), 0f)
                )
            )
        }

        rotate(-angle * 1.4f, pivot = center) {
            drawCircle(
                color = NeonCyan.copy(alpha = 0.85f),
                radius = innerR,
                center = center,
                style = Stroke(
                    width = 1.6.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f), 0f)
                )
            )
        }

        drawCircle(
            brush = Brush.linearGradient(listOf(ElectricBlue, NeonCyan, VioletHighlight)),
            radius = this.size.minDimension * 0.13f,
            center = center
        )
    }
}

@Composable
fun TelemetryMetricCard(
    label: String,
    value: String,
    caption: String,
    accentColor: Color,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SlateRaised),
        border = BorderStroke(1.dp, SlateBorder)
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(accentColor)
                )
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = CoolGray,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = value,
                style = MaterialTheme.typography.headlineMedium,
                color = SoftWhite,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = caption,
                style = MaterialTheme.typography.bodyMedium,
                color = MutedGray,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

@Composable
fun ReportSummaryCard(
    report: RestoreProofReport,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .clickable(onClick = onClick)
            .testTag("report_card_${report.runId}"),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SlateRaised),
        border = BorderStroke(
            1.dp,
            if (report.overallPassed) StatusPass.copy(alpha = 0.35f) else StatusFail.copy(alpha = 0.4f)
        )
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Surface(
                        color = DeepGraphite,
                        shape = RoundedCornerShape(8.dp),
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Text(
                            text = report.runId,
                            style = MaterialTheme.typography.labelMedium,
                            color = NeonCyan,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                        )
                    }
                    Text(
                        text = report.targetName,
                        style = MaterialTheme.typography.titleMedium,
                        color = SoftWhite,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                StatusPill(
                    label = if (report.overallPassed) "PASS" else "FAIL",
                    tone = if (report.overallPassed) StatusTone.PASS else StatusTone.FAIL
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (report.discrepancies.isEmpty()) {
                    "ตรวจสอบ Restore & SHA-256 ครบถ้วนใน Isolated Sandbox (${report.metrics.restoredFileCount} ไฟล์)"
                } else {
                    report.discrepancies.joinToString(" • ")
                },
                style = MaterialTheme.typography.bodyMedium,
                color = if (report.overallPassed) CoolGray else StatusFail,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )

            if (report.metrics.backupSha256.isNotBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "SHA-256: ${report.metrics.backupSha256.take(18)}…",
                    style = MaterialTheme.typography.labelSmall,
                    color = MutedGray
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EvidenceReportDetailDialog(
    report: RestoreProofReport,
    exportJson: String,
    onDismiss: () -> Unit
) {
    val context = LocalContext.current

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth(0.94f)
                .heightIn(max = 680.dp),
            shape = RoundedCornerShape(20.dp),
            color = SlateSurface,
            border = BorderStroke(1.dp, SlateBorder)
        ) {
            Column(modifier = Modifier.padding(18.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "EVIDENCE REPORT · ${report.runId}",
                            style = MaterialTheme.typography.labelMedium,
                            color = NeonCyan
                        )
                        Text(
                            text = report.targetName,
                            style = MaterialTheme.typography.titleLarge,
                            color = SoftWhite,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                    IconButton(
                        onClick = onDismiss,
                        modifier = Modifier
                            .minimumInteractiveComponentSize()
                            .testTag("close_evidence_dialog")
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Close,
                            contentDescription = "ปิดหน้าต่างหลักฐาน",
                            tint = CoolGray
                        )
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    StatusPill(
                        label = if (report.overallPassed) "VERDICT: PASS" else "VERDICT: FAIL",
                        tone = if (report.overallPassed) StatusTone.PASS else StatusTone.FAIL
                    )
                    StatusPill(
                        label = if (report.verifiedRestorable) "Unpack OK" else "Unpack Blocked/Fail",
                        tone = if (report.verifiedRestorable) StatusTone.PASS else StatusTone.FAIL
                    )
                    StatusPill(
                        label = if (report.completenessOk) "Manifest SHA-256 OK" else "Completeness Fail",
                        tone = if (report.completenessOk) StatusTone.PASS else StatusTone.FAIL
                    )
                    StatusPill(
                        label = if (report.healthCheckOk) "Health Probe OK" else "Health Probe Fail",
                        tone = if (report.healthCheckOk) StatusTone.PASS else StatusTone.FAIL
                    )
                    StatusPill(
                        label = if (report.metrics.tempWorkspaceCleaned) "Sandbox Cleaned" else "Sandbox Warn",
                        tone = StatusTone.INFO
                    )
                }

                Spacer(modifier = Modifier.height(12.dp))
                HorizontalDivider(color = SlateBorder)
                Spacer(modifier = Modifier.height(10.dp))

                Column(
                    modifier = Modifier
                        .weight(1f, fill = false)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Text(
                        text = "Authority: ${report.verdictAuthority} • ${report.checkedAtIso}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MutedGray
                    )
                    Text(
                        text = "Backup SHA-256: ${report.metrics.backupSha256.ifBlank { "N/A" }}",
                        style = MaterialTheme.typography.labelMedium,
                        color = CoolGray
                    )
                    Text(
                        text = "Restored Files: ${report.metrics.restoredFileCount} / Required: ${report.metrics.minFilesRequired}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = SoftWhite
                    )

                    if (report.discrepancies.isNotEmpty()) {
                        Surface(
                            color = StatusFailBg,
                            shape = RoundedCornerShape(12.dp),
                            border = BorderStroke(1.dp, StatusFail.copy(alpha = 0.45f))
                        ) {
                            Column(modifier = Modifier.padding(12.dp)) {
                                Text(
                                    text = "Discrepancies (สาเหตุที่ตรวจพบ)",
                                    style = MaterialTheme.typography.labelLarge,
                                    color = StatusFail
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                report.discrepancies.forEach { d ->
                                    Text(
                                        text = "• $d",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = SoftWhite
                                    )
                                }
                            }
                        }
                    }

                    Surface(
                        color = DeepGraphite,
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text(
                                text = "RestoreProof Worker Logs",
                                style = MaterialTheme.typography.labelLarge,
                                color = NeonCyan
                            )
                            Spacer(modifier = Modifier.height(6.dp))
                            report.workerLogs.forEach { line ->
                                Text(
                                    text = line,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = CoolGray
                                )
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    OutlinedButton(
                        onClick = {
                            val shareIntent = Intent(Intent.ACTION_SEND).apply {
                                type = "application/json"
                                putExtra(Intent.EXTRA_SUBJECT, "RealityCheck Evidence ${report.runId}")
                                putExtra(Intent.EXTRA_TEXT, exportJson)
                            }
                            context.startActivity(
                                Intent.createChooser(shareIntent, "แชร์รายงานหลักฐาน JSON")
                            )
                        },
                        modifier = Modifier
                            .weight(1f)
                            .minimumInteractiveComponentSize()
                            .testTag("share_evidence_button"),
                        border = BorderStroke(1.dp, SlateBorder)
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Share,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                            tint = NeonCyan
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("แชร์ JSON", color = SoftWhite)
                    }

                    Button(
                        onClick = onDismiss,
                        modifier = Modifier
                            .weight(1f)
                            .minimumInteractiveComponentSize(),
                        colors = ButtonDefaults.buttonColors(containerColor = ElectricBlue)
                    ) {
                        Text("ปิด", fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}

@Composable
fun RestoreSafetyGateBanner(
    isolationPassed: Boolean,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = if (isolationPassed) StatusInfoBg else StatusWarnBg,
        border = BorderStroke(
            1.dp,
            if (isolationPassed) StatusInfo.copy(alpha = 0.4f) else StatusWarn.copy(alpha = 0.45f)
        )
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Icon(
                imageVector = Icons.Rounded.Lock,
                contentDescription = "Restore Execution Locked",
                tint = if (isolationPassed) StatusInfo else StatusWarn,
                modifier = Modifier.size(20.dp)
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (isolationPassed) {
                        "Isolation Tests Passed · คำสั่ง Restore จริงยังต้องผ่าน Admin Gate"
                    } else {
                        "Restore Execution LOCKED · ยังไม่เปิดคำสั่ง Restore จริง"
                    },
                    style = MaterialTheme.typography.labelLarge,
                    color = if (isolationPassed) StatusInfo else StatusWarn
                )
                Text(
                    text = "Worker ทำงานแบบ Read-Only ในพื้นที่แยก (Isolated Sandbox) เท่านั้น จนกว่าการทดสอบแยกสภาพแวดล้อมและการกู้คืนจริงจะผ่านครบ",
                    style = MaterialTheme.typography.bodyMedium,
                    color = CoolGray
                )
            }
        }
    }
}
