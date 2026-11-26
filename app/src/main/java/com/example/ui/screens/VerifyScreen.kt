package com.example.ui.screens

import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Security
import androidx.compose.material.icons.rounded.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.example.domain.BackupArchiveTarget
import com.example.domain.RestoreProofReport
import com.example.domain.SyncPairTarget
import com.example.ui.components.ReportSummaryCard
import com.example.ui.components.StatusPill
import com.example.ui.components.StatusTone
import com.example.ui.theme.CoolGray
import com.example.ui.theme.ElectricBlue
import com.example.ui.theme.MutedGray
import com.example.ui.theme.NeonCyan
import com.example.ui.theme.SlateBorder
import com.example.ui.theme.SlateRaised
import com.example.ui.theme.SlateSurface
import com.example.ui.theme.SoftWhite

@Composable
fun VerifyScreen(
    backupTargets: List<BackupArchiveTarget>,
    syncTargets: List<SyncPairTarget>,
    reports: List<RestoreProofReport>,
    workerBusy: Boolean,
    onVerifyBackup: (String) -> Unit,
    onVerifyAllBackups: () -> Unit,
    onVerifySync: (String) -> Unit,
    onRunIsolationSuite: () -> Unit,
    onImportAndVerifyUri: (android.net.Uri, String) -> Unit,
    onSelectReport: (RestoreProofReport) -> Unit
) {
    var selectedTab by rememberSaveable { mutableIntStateOf(0) }
    val context = LocalContext.current

    val zipPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            val name = context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && cursor.moveToFirst()) cursor.getString(idx) else null
            } ?: "user_backup.zip"
            onImportAndVerifyUri(uri, name)
        }
    }

    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.TopCenter
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .widthIn(max = 760.dp)
        ) {
            if (workerBusy) {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth(),
                    color = NeonCyan,
                    trackColor = SlateSurface
                )
            }

            // Action Toolbar
            Column(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Button(
                        onClick = onVerifyAllBackups,
                        enabled = !workerBusy,
                        modifier = Modifier
                            .weight(1f)
                            .minimumInteractiveComponentSize()
                            .testTag("verify_all_backups_button"),
                        colors = ButtonDefaults.buttonColors(containerColor = ElectricBlue)
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.PlayArrow,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("ตรวจ Backup ทั้งหมด", maxLines = 1)
                    }

                    OutlinedButton(
                        onClick = {
                            zipPicker.launch(arrayOf("application/zip", "application/x-zip-compressed"))
                        },
                        enabled = !workerBusy,
                        modifier = Modifier
                            .weight(1f)
                            .minimumInteractiveComponentSize()
                            .testTag("import_zip_button"),
                        border = BorderStroke(1.dp, NeonCyan.copy(alpha = 0.55f))
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.FolderOpen,
                            contentDescription = null,
                            tint = NeonCyan,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("เลือกไฟล์ .zip", color = NeonCyan, maxLines = 1)
                    }
                }

                OutlinedButton(
                    onClick = onRunIsolationSuite,
                    enabled = !workerBusy,
                    modifier = Modifier
                        .fillMaxWidth()
                        .minimumInteractiveComponentSize()
                        .testTag("run_isolation_suite_button"),
                    border = BorderStroke(1.dp, SlateBorder)
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Security,
                        contentDescription = null,
                        tint = SoftWhite,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("รันชุดทดสอบ Isolation & 4-Wave Failure Detection", color = SoftWhite)
                }

                // Filter Tabs
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    val tabs = listOf(
                        "Backups (${backupTargets.size})",
                        "Sync Truth (${syncTargets.size})",
                        "Evidence (${reports.size})"
                    )
                    tabs.forEachIndexed { idx, label ->
                        FilterChip(
                            selected = selectedTab == idx,
                            onClick = { selectedTab = idx },
                            label = { Text(label, style = MaterialTheme.typography.labelLarge) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = ElectricBlue,
                                selectedLabelColor = SoftWhite,
                                containerColor = SlateSurface,
                                labelColor = CoolGray
                            ),
                            border = BorderStroke(1.dp, SlateBorder),
                            modifier = Modifier.testTag("verify_tab_$idx")
                        )
                    }
                }
            }

            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                when (selectedTab) {
                    0 -> {
                        items(backupTargets, key = { it.id }) { target ->
                            val latestReport = reports.firstOrNull { it.targetId == target.id }
                            Card(
                                shape = RoundedCornerShape(16.dp),
                                colors = CardDefaults.cardColors(containerColor = SlateRaised),
                                border = BorderStroke(1.dp, SlateBorder)
                            ) {
                                Column(modifier = Modifier.padding(14.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            text = target.displayName,
                                            style = MaterialTheme.typography.titleMedium,
                                            color = SoftWhite,
                                            modifier = Modifier.weight(1f)
                                        )
                                        if (latestReport != null) {
                                            StatusPill(
                                                label = if (latestReport.overallPassed) "PASS (${latestReport.runId})" else "FAIL (${latestReport.runId})",
                                                tone = if (latestReport.overallPassed) StatusTone.PASS else StatusTone.FAIL
                                            )
                                        } else {
                                            StatusPill(label = "NOT RUN", tone = StatusTone.INFO)
                                        }
                                    }
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = target.description,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = CoolGray
                                    )
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = "Min files: ${target.minFilesRequired} • Manifest entries: ${target.expectedManifestHashes.size}",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MutedGray
                                    )
                                    Spacer(modifier = Modifier.height(10.dp))
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                                    ) {
                                        Button(
                                            onClick = { onVerifyBackup(target.id) },
                                            enabled = !workerBusy,
                                            modifier = Modifier
                                                .weight(1f)
                                                .minimumInteractiveComponentSize()
                                                .testTag("verify_target_${target.id}"),
                                            colors = ButtonDefaults.buttonColors(containerColor = ElectricBlue)
                                        ) {
                                            Text("ตรวจใน Sandbox", maxLines = 1)
                                        }
                                        if (latestReport != null) {
                                            OutlinedButton(
                                                onClick = { onSelectReport(latestReport) },
                                                modifier = Modifier.minimumInteractiveComponentSize(),
                                                border = BorderStroke(1.dp, SlateBorder)
                                            ) {
                                                Text("ดูหลักฐาน", color = NeonCyan)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    1 -> {
                        items(syncTargets, key = { it.id }) { pair ->
                            val latestSync = reports.firstOrNull { it.targetId == pair.id }
                            Card(
                                shape = RoundedCornerShape(16.dp),
                                colors = CardDefaults.cardColors(containerColor = SlateRaised),
                                border = BorderStroke(1.dp, SlateBorder)
                            ) {
                                Column(modifier = Modifier.padding(14.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            text = pair.displayName,
                                            style = MaterialTheme.typography.titleMedium,
                                            color = SoftWhite,
                                            modifier = Modifier.weight(1f)
                                        )
                                        if (latestSync != null) {
                                            StatusPill(
                                                label = if (latestSync.overallPassed) "SYNC OK" else "DRIFT",
                                                tone = if (latestSync.overallPassed) StatusTone.PASS else StatusTone.FAIL
                                            )
                                        } else {
                                            StatusPill(label = "NOT RUN", tone = StatusTone.INFO)
                                        }
                                    }
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = pair.description,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = CoolGray
                                    )
                                    Spacer(modifier = Modifier.height(10.dp))
                                    Button(
                                        onClick = { onVerifySync(pair.id) },
                                        enabled = !workerBusy,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .minimumInteractiveComponentSize()
                                            .testTag("verify_sync_${pair.id}"),
                                        colors = ButtonDefaults.buttonColors(containerColor = ElectricBlue)
                                    ) {
                                        Icon(
                                            imageVector = Icons.Rounded.Sync,
                                            contentDescription = null,
                                            modifier = Modifier.size(16.dp)
                                        )
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Text("ตรวจ SHA-256 Sync Truth")
                                    }
                                }
                            }
                        }
                    }
                    else -> {
                        if (reports.isEmpty()) {
                            item {
                                Text(
                                    text = "ยังไม่มี Evidence Report กดตรวจสอบ Backup เพื่อสร้างหลักฐานจริง",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = CoolGray,
                                    modifier = Modifier.padding(12.dp)
                                )
                            }
                        } else {
                            items(reports, key = { it.runId }) { report ->
                                ReportSummaryCard(
                                    report = report,
                                    onClick = { onSelectReport(report) }
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
