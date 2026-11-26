package com.example.engine

import com.example.domain.BackupArchiveTarget
import com.example.domain.ProbeType
import com.example.domain.RestoreProofMetrics
import com.example.domain.RestoreProofReport
import com.example.domain.SyncPairTarget
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import java.util.zip.ZipInputStream

/**
 * Deterministic RestoreProof Worker & Verification Engine.
 *
 * Strictly read-only on production artifacts:
 * - Unpacks archives inside an isolated temporary workspace (`restoreproof_iso_*`).
 * - Rejects Zip-Slip / path traversal before writing bytes.
 * - Verifies SHA-256 checksums and completeness against expected manifests.
 * - Cleans up the isolated workspace inside a `finally` block.
 * - AI has NO authority to fabricate PASS results; verdicts come strictly from here.
 */
object RestoreProofWorker {

    fun sha256File(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    fun sha256Bytes(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256")
        return digest.digest(bytes).joinToString("") { "%02x".format(it) }
    }

    /**
     * Prevents Zip-Slip / path traversal attacks fail-closed.
     */
    fun validateArchiveTarget(destRoot: File, entryName: String): File {
        if (entryName.isBlank() || entryName.startsWith("/") || entryName.startsWith("\\")) {
            throw SecurityException("Unsafe absolute archive member path: '$entryName'")
        }
        val normalizedSegments = entryName.replace('\\', '/').split('/')
        if (normalizedSegments.any { it == ".." }) {
            throw SecurityException("Archive path traversal detected: '$entryName'")
        }
        val rootCanonical = destRoot.canonicalFile
        val targetCanonical = File(rootCanonical, entryName).canonicalFile
        val rootPath = rootCanonical.path
        val targetPath = targetCanonical.path
        if (targetPath != rootPath && !targetPath.startsWith(rootPath + File.separator)) {
            throw SecurityException("Archive path traversal outside sandbox: '$entryName'")
        }
        return targetCanonical
    }

    fun safeUnpackZip(archiveFile: File, destDir: File, log: (String) -> Unit): Int {
        var entryCount = 0
        ZipInputStream(FileInputStream(archiveFile).buffered()).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                val target = validateArchiveTarget(destDir, entry.name)
                if (entry.isDirectory) {
                    if (!target.exists() && !target.mkdirs()) {
                        throw IllegalStateException("Failed to create directory: ${target.name}")
                    }
                } else {
                    target.parentFile?.let { parent ->
                        if (!parent.exists() && !parent.mkdirs()) {
                            throw IllegalStateException("Failed to create parent directory for ${entry.name}")
                        }
                    }
                    FileOutputStream(target).use { fos ->
                        val buffer = ByteArray(16384)
                        while (true) {
                            val read = zis.read(buffer)
                            if (read <= 0) break
                            fos.write(buffer, 0, read)
                        }
                    }
                    entryCount += 1
                    log("Extracted entry '${entry.name}' (${target.length()} bytes) in isolated sandbox")
                }
                zis.closeEntry()
            }
        }
        return entryCount
    }

    private fun collectFileHashes(root: File): Map<String, String> {
        if (!root.exists()) return emptyMap()
        val result = sortedMapOf<String, String>()
        val rootPath = root.toPath()
        root.walkTopDown()
            .filter { it.isFile }
            .sortedBy { it.path }
            .forEach { file ->
                val rel = rootPath.relativize(file.toPath()).toString().replace('\\', '/')
                result[rel] = sha256File(file)
            }
        return result
    }

    fun verifyBackupArchive(
        runId: String,
        target: BackupArchiveTarget,
        sandboxParentDir: File
    ): RestoreProofReport {
        val checkedAt = Instant.now().toString()
        val logs = mutableListOf<String>()
        val discrepancies = mutableListOf<String>()
        val archiveFile = File(target.archivePath)

        logs += "[$runId] Starting RestoreProof Worker on '${target.displayName}'"
        logs += "[$runId] Target path: ${archiveFile.absolutePath} (read-only mode)"

        if (!archiveFile.exists() || !archiveFile.isFile) {
            val msg = "Backup artifact not found: ${archiveFile.absolutePath}"
            discrepancies += msg
            logs += "[$runId] FAIL: $msg"
            return RestoreProofReport(
                runId = runId,
                probeType = ProbeType.RESTORE_PROOF,
                targetId = target.id,
                targetName = target.displayName,
                verifiedRestorable = false,
                completenessOk = false,
                healthCheckOk = false,
                overallPassed = false,
                discrepancies = discrepancies,
                metrics = RestoreProofMetrics(
                    backupExists = false,
                    backupSha256 = "",
                    restoredFileCount = 0,
                    minFilesRequired = target.minFilesRequired,
                    tempWorkspaceCleaned = true
                ),
                workerLogs = logs,
                checkedAtIso = checkedAt
            )
        }

        val backupSha256 = sha256File(archiveFile)
        logs += "[$runId] Archive SHA-256: $backupSha256"

        if (!sandboxParentDir.exists()) {
            sandboxParentDir.mkdirs()
        }
        val tmpDir = File(sandboxParentDir, "restoreproof_iso_${UUID.randomUUID().toString().take(8)}")
        tmpDir.mkdirs()
        logs += "[$runId] Created isolated temp workspace: ${tmpDir.name}"

        var restoredOk = false
        var completenessOk = false
        var healthOk = false
        var restoredHashes: Map<String, String> = emptyMap()
        val missingFiles = mutableListOf<String>()
        val hashMismatches = mutableListOf<String>()
        val extraFiles = mutableListOf<String>()

        try {
            try {
                val unpackedEntries = safeUnpackZip(archiveFile, tmpDir) { entryLog ->
                    logs += "[$runId] $entryLog"
                }
                if (unpackedEntries == 0) {
                    discrepancies += "Archive unpack succeeded but archive contained 0 files"
                    logs += "[$runId] FAIL: Archive contains 0 files"
                } else {
                    restoredOk = true
                    logs += "[$runId] Safe unpack passed ($unpackedEntries entries)"
                }
            } catch (sec: SecurityException) {
                val msg = "Security gate blocked unsafe archive: ${sec.message}"
                discrepancies += msg
                logs += "[$runId] BLOCKED: $msg"
            } catch (ex: Exception) {
                val msg = "Archive unpack failed: ${ex::class.simpleName}: ${ex.message}"
                discrepancies += msg
                logs += "[$runId] FAIL: $msg"
            }

            if (restoredOk) {
                restoredHashes = collectFileHashes(tmpDir)
                val fileCount = restoredHashes.size

                if (target.expectedManifestHashes.isNotEmpty()) {
                    for ((rel, expectedHash) in target.expectedManifestHashes) {
                        val normRel = rel.removePrefix("./")
                        val actualHash = restoredHashes[normRel]
                        if (actualHash == null) {
                            missingFiles += normRel
                        } else if (!actualHash.equals(expectedHash, ignoreCase = true)) {
                            hashMismatches += normRel
                            logs += "[$runId] HASH MISMATCH on '$normRel': expected=${expectedHash.take(12)} actual=${actualHash.take(12)}"
                        }
                    }
                    extraFiles += (restoredHashes.keys - target.expectedManifestHashes.keys).sorted()
                }

                completenessOk =
                    fileCount >= target.minFilesRequired &&
                    missingFiles.isEmpty() &&
                    hashMismatches.isEmpty()

                if (fileCount < target.minFilesRequired) {
                    discrepancies += "Restored file count $fileCount below minimum required ${target.minFilesRequired}"
                }
                if (missingFiles.isNotEmpty()) {
                    discrepancies += "Missing files after restore: $missingFiles"
                }
                if (hashMismatches.isNotEmpty()) {
                    discrepancies += "Hash mismatches after restore: $hashMismatches"
                }

                // Isolated readiness health check
                if (!target.requireConfigHealthCheck) {
                    healthOk = true
                    logs += "[$runId] Health check bypassed per target policy (file verification only)"
                } else {
                    val configFile = File(tmpDir, "config.json")
                    if (!configFile.exists()) {
                        healthOk = false
                        discrepancies += "Health check failed: required config.json missing in restored workspace"
                        logs += "[$runId] FAIL: config.json missing for readiness probe"
                    } else {
                        try {
                            val json = JSONObject(configFile.readText(Charsets.UTF_8))
                            val mode = json.optString("mode", "")
                            val integrityReady = json.optBoolean("restore_ready", true)
                            if (mode == "disabled" || !integrityReady) {
                                healthOk = false
                                discrepancies += "Health check failed: config.json reports mode='$mode', restore_ready=$integrityReady"
                                logs += "[$runId] FAIL: Health probe failed (mode=$mode, restore_ready=$integrityReady)"
                            } else {
                                healthOk = true
                                logs += "[$runId] Isolated readiness health probe PASSED (mode=$mode)"
                            }
                        } catch (ex: Exception) {
                            healthOk = false
                            discrepancies += "Health check failed: malformed config.json (${ex.message})"
                            logs += "[$runId] FAIL: Malformed config.json"
                        }
                    }
                }
            } else {
                discrepancies += "Skipped completeness & health check because restore unpack failed"
            }

            val overallPassed = restoredOk && completenessOk && healthOk
            logs += "[$runId] Final Engine Verdict: ${if (overallPassed) "PASS" else "FAIL"}"

            return RestoreProofReport(
                runId = runId,
                probeType = ProbeType.RESTORE_PROOF,
                targetId = target.id,
                targetName = target.displayName,
                verifiedRestorable = restoredOk,
                completenessOk = completenessOk,
                healthCheckOk = healthOk,
                overallPassed = overallPassed,
                discrepancies = discrepancies,
                metrics = RestoreProofMetrics(
                    backupExists = true,
                    backupSha256 = backupSha256,
                    restoredFileCount = restoredHashes.size,
                    minFilesRequired = target.minFilesRequired,
                    missingFiles = missingFiles,
                    hashMismatches = hashMismatches,
                    extraFiles = extraFiles,
                    tempWorkspaceCleaned = true,
                    isolationSandboxPath = tmpDir.name
                ),
                workerLogs = logs,
                checkedAtIso = checkedAt
            )
        } finally {
            val cleaned = tmpDir.deleteRecursively()
            logs += "[$runId] Isolated temp workspace cleanup: ${if (cleaned && !tmpDir.exists()) "CLEANED" else "WARN"}"
        }
    }

    fun verifySyncTruth(
        runId: String,
        syncTarget: SyncPairTarget
    ): RestoreProofReport {
        val checkedAt = Instant.now().toString()
        val logs = mutableListOf<String>()
        val discrepancies = mutableListOf<String>()
        val srcDir = File(syncTarget.sourceDirPath)
        val dstDir = File(syncTarget.targetDirPath)

        logs += "[$runId] Starting Sync Truth Probe on '${syncTarget.displayName}'"
        if (!srcDir.exists() || !dstDir.exists()) {
            val msg = "Missing source (${srcDir.exists()}) or target (${dstDir.exists()}) directory"
            discrepancies += msg
            logs += "[$runId] FAIL: $msg"
            return RestoreProofReport(
                runId = runId,
                probeType = ProbeType.SYNC_TRUTH,
                targetId = syncTarget.id,
                targetName = syncTarget.displayName,
                verifiedRestorable = false,
                completenessOk = false,
                healthCheckOk = false,
                overallPassed = false,
                discrepancies = discrepancies,
                metrics = RestoreProofMetrics(
                    backupExists = srcDir.exists(),
                    backupSha256 = "",
                    restoredFileCount = 0,
                    minFilesRequired = 1,
                    tempWorkspaceCleaned = true
                ),
                workerLogs = logs,
                checkedAtIso = checkedAt
            )
        }

        val srcHashes = collectFileHashes(srcDir)
        val dstHashes = collectFileHashes(dstDir)
        val missingInDst = (srcHashes.keys - dstHashes.keys).sorted()
        val extraInDst = (dstHashes.keys - srcHashes.keys).sorted()
        val contentDiff = (srcHashes.keys intersect dstHashes.keys)
            .filter { srcHashes[it] != dstHashes[it] }
            .sorted()

        if (missingInDst.isNotEmpty()) discrepancies += "Missing in target: $missingInDst"
        if (extraInDst.isNotEmpty()) discrepancies += "Stale/extra in target: $extraInDst"
        if (contentDiff.isNotEmpty()) discrepancies += "Content hash differs: $contentDiff"

        val ok = missingInDst.isEmpty() && extraInDst.isEmpty() && contentDiff.isEmpty() && srcHashes.isNotEmpty()
        logs += "[$runId] Source files=${srcHashes.size}, Target files=${dstHashes.size}"
        contentDiff.forEach { rel ->
            logs += "[$runId] DRIFT DETECTED on '$rel': src=${srcHashes[rel]?.take(12)} dst=${dstHashes[rel]?.take(12)}"
        }
        logs += "[$runId] Sync Truth Verdict: ${if (ok) "PASS" else "FAIL"}"

        val digestSummary = sha256Bytes(
            srcHashes.entries.joinToString("\n") { "${it.key}:${it.value}" }.toByteArray()
        )

        return RestoreProofReport(
            runId = runId,
            probeType = ProbeType.SYNC_TRUTH,
            targetId = syncTarget.id,
            targetName = syncTarget.displayName,
            verifiedRestorable = srcDir.exists() && dstDir.exists(),
            completenessOk = missingInDst.isEmpty() && extraInDst.isEmpty(),
            healthCheckOk = contentDiff.isEmpty(),
            overallPassed = ok,
            discrepancies = discrepancies,
            metrics = RestoreProofMetrics(
                backupExists = true,
                backupSha256 = digestSummary,
                restoredFileCount = dstHashes.size,
                minFilesRequired = srcHashes.size,
                missingFiles = missingInDst,
                hashMismatches = contentDiff,
                extraFiles = extraInDst,
                tempWorkspaceCleaned = true
            ),
            workerLogs = logs,
            checkedAtIso = checkedAt
        )
    }
}
