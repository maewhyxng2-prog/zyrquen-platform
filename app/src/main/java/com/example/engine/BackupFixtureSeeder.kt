package com.example.engine

import android.content.Context
import com.example.domain.BackupArchiveTarget
import com.example.domain.SyncPairTarget
import java.io.File
import java.io.FileOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Seeds deterministic on-disk .zip backup archives and sync directories inside app storage
 * so the RestoreProof Worker executes real ZipInputStream extraction, SHA-256 checks,
 * missing-file detection, and Zip-Slip traversal blocking.
 */
object BackupFixtureSeeder {

    data class SeededWorkspace(
        val backups: List<BackupArchiveTarget>,
        val syncPairs: List<SyncPairTarget>
    )

    fun ensureSeeded(rootDir: File): SeededWorkspace {
        val backupsDir = File(rootDir, "realitycheck/backups").apply { mkdirs() }
        val syncDir = File(rootDir, "realitycheck/sync").apply { mkdirs() }

        val ledgerBytes = "tx_id=1001,amount=450.00,status=COMMITTED\ntx_id=1002,amount=980.00,status=COMMITTED\n".toByteArray()
        val configGoodBytes = """{"mode":"strict","restore_ready":true,"schema":"v4"}""".toByteArray()
        val indexBytes = """{"snapshot":"2026-11-26T07:00:00Z","entries":2}""".toByteArray()

        val expectedProdManifest = mapOf(
            "ledger.txt" to RestoreProofWorker.sha256Bytes(ledgerBytes),
            "config.json" to RestoreProofWorker.sha256Bytes(configGoodBytes),
            "ledger_index.json" to RestoreProofWorker.sha256Bytes(indexBytes)
        )

        // 1. Healthy Production Backup
        val prodZip = File(backupsDir, "prod_ledger_20261126.zip")
        writeZip(
            prodZip,
            listOf(
                "ledger.txt" to ledgerBytes,
                "config.json" to configGoodBytes,
                "ledger_index.json" to indexBytes
            )
        )

        // 2. Tampered / Corrupt Checksum + Disabled Config Backup
        val corruptZip = File(backupsDir, "analytics_corrupt_20261126.zip")
        val corruptConfigBytes = """{"mode":"disabled","restore_ready":false,"schema":"v4"}""".toByteArray()
        writeZip(
            corruptZip,
            listOf(
                "ledger.txt" to ledgerBytes,
                "config.json" to corruptConfigBytes,
                "ledger_index.json" to indexBytes
            )
        )

        // 3. Incomplete Backup (missing ledger_index.json)
        val incompleteZip = File(backupsDir, "incomplete_snapshot_20261125.zip")
        writeZip(
            incompleteZip,
            listOf(
                "ledger.txt" to ledgerBytes,
                "config.json" to configGoodBytes
            )
        )

        // 4. Zip-Slip Path Traversal Probe Archive (../../etc/shadow)
        val zipSlipZip = File(backupsDir, "malicious_zipslip_probe.zip")
        writeZip(
            zipSlipZip,
            listOf(
                "../../etc/shadow_escape" to "escape_attempt".toByteArray(),
                "config.json" to configGoodBytes
            )
        )

        // Sync Pair 1: Source vs Mirror with silent config drift
        val srcA = File(syncDir, "primary_ledger").apply { mkdirs() }
        val dstA = File(syncDir, "replica_node_b").apply { mkdirs() }
        File(srcA, "ledger.txt").writeBytes(ledgerBytes)
        File(srcA, "config.json").writeBytes(configGoodBytes)
        File(dstA, "ledger.txt").writeBytes(ledgerBytes)
        File(dstA, "config.json").writeBytes("""{"mode":"permissive","restore_ready":true}""".toByteArray())

        // Sync Pair 2: Healthy exact mirror
        val srcB = File(syncDir, "primary_auth_cfg").apply { mkdirs() }
        val dstB = File(syncDir, "replica_auth_cfg").apply { mkdirs() }
        File(srcB, "policy.json").writeText("""{"require_approval":true,"tier":2}""")
        File(dstB, "policy.json").writeText("""{"require_approval":true,"tier":2}""")

        return SeededWorkspace(
            backups = listOf(
                BackupArchiveTarget(
                    id = "bk_prod_ledger",
                    displayName = "prod_ledger_20261126.zip",
                    description = "ชุดสำรองข้อมูลบัญชีหลัก (คาดหวังผล PASS พร้อมตรวจ SHA-256 ครบ 3 ไฟล์)",
                    archivePath = prodZip.absolutePath,
                    minFilesRequired = 3,
                    expectedManifestHashes = expectedProdManifest
                ),
                BackupArchiveTarget(
                    id = "bk_analytics_corrupt",
                    displayName = "analytics_corrupt_20261126.zip",
                    description = "ชุดสำรองข้อมูลที่ถูกแก้ไข config.json (คาดหวัง Hash Mismatch + Health Probe Fail)",
                    archivePath = corruptZip.absolutePath,
                    minFilesRequired = 3,
                    expectedManifestHashes = expectedProdManifest
                ),
                BackupArchiveTarget(
                    id = "bk_incomplete",
                    displayName = "incomplete_snapshot_20261125.zip",
                    description = "ชุดสำรองข้อมูลไม่ครบไฟล์ ledger_index.json (คาดหวัง Completeness Fail)",
                    archivePath = incompleteZip.absolutePath,
                    minFilesRequired = 3,
                    expectedManifestHashes = expectedProdManifest
                ),
                BackupArchiveTarget(
                    id = "bk_zipslip_probe",
                    displayName = "malicious_zipslip_probe.zip",
                    description = "ไฟล์ทดสอบความปลอดภัย Zip-Slip Traversal (../../) — ต้องถูกบล็อก Fail-Closed",
                    archivePath = zipSlipZip.absolutePath,
                    minFilesRequired = 1,
                    expectedManifestHashes = emptyMap()
                )
            ),
            syncPairs = listOf(
                SyncPairTarget(
                    id = "sync_ledger_replica",
                    displayName = "primary_ledger → replica_node_b",
                    sourceDirPath = srcA.absolutePath,
                    targetDirPath = dstA.absolutePath,
                    description = "ตรวจการซิงก์ข้อมูลระหว่างโหนดหลักและโหนดสำรอง (พบ Config Drift)"
                ),
                SyncPairTarget(
                    id = "sync_auth_policy",
                    displayName = "primary_auth_cfg → replica_auth_cfg",
                    sourceDirPath = srcB.absolutePath,
                    targetDirPath = dstB.absolutePath,
                    description = "ตรวจการซิงก์นโยบายความปลอดภัยและสิทธิ์ (ตรงกันสมบูรณ์)"
                )
            )
        )
    }

    fun importUserZip(context: Context, uri: android.net.Uri, displayName: String): BackupArchiveTarget {
        val importsDir = File(context.filesDir, "realitycheck/imports").apply { mkdirs() }
        val safeName = displayName.replace(Regex("[^a-zA-Z0-9._-]"), "_").ifBlank { "imported_backup.zip" }
        val destFile = File(importsDir, "${System.currentTimeMillis()}_$safeName")
        context.contentResolver.openInputStream(uri)?.use { input ->
            FileOutputStream(destFile).use { output ->
                input.copyTo(output)
            }
        } ?: throw IllegalStateException("ไม่สามารถเปิดอ่านไฟล์ที่เลือกได้")

        return BackupArchiveTarget(
            id = "bk_import_${System.currentTimeMillis()}",
            displayName = safeName,
            description = "ไฟล์ Backup ที่นำเข้าจากเครื่องเพื่อตรวจสอบแบบ Read-Only",
            archivePath = destFile.absolutePath,
            minFilesRequired = 1,
            expectedManifestHashes = emptyMap(),
            requireConfigHealthCheck = false,
            isUserImported = true
        )
    }

    private fun writeZip(dest: File, entries: List<Pair<String, ByteArray>>) {
        ZipOutputStream(FileOutputStream(dest).buffered()).use { zos ->
            for ((name, bytes) in entries) {
                zos.putNextEntry(ZipEntry(name))
                zos.write(bytes)
                zos.closeEntry()
            }
        }
    }
}
