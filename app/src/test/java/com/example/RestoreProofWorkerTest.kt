package com.example

import com.example.engine.BackupFixtureSeeder
import com.example.engine.RestoreProofWorker
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class RestoreProofWorkerTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    @Test
    fun healthyBackupPassesAndCleansIsolatedSandbox() {
        val workspaceRoot = tempFolder.newFolder("workspace")
        val sandboxParent = tempFolder.newFolder("sandboxes")
        val seeded = BackupFixtureSeeder.ensureSeeded(workspaceRoot)
        val prod = seeded.backups.first { it.id == "bk_prod_ledger" }

        val report = RestoreProofWorker.verifyBackupArchive(
            runId = "TEST-0001",
            target = prod,
            sandboxParentDir = sandboxParent
        )

        assertTrue(report.verifiedRestorable)
        assertTrue(report.completenessOk)
        assertTrue(report.healthCheckOk)
        assertTrue(report.overallPassed)
        assertTrue(report.discrepancies.isEmpty())
        assertEquals(3, report.metrics.restoredFileCount)
        assertTrue(report.metrics.tempWorkspaceCleaned)
        assertEquals(0, sandboxParent.listFiles()?.size ?: 0)
    }

    @Test
    fun tamperedBackupFailsHashMismatchAndHealthCheck() {
        val workspaceRoot = tempFolder.newFolder("workspace")
        val sandboxParent = tempFolder.newFolder("sandboxes")
        val seeded = BackupFixtureSeeder.ensureSeeded(workspaceRoot)
        val corrupt = seeded.backups.first { it.id == "bk_analytics_corrupt" }

        val report = RestoreProofWorker.verifyBackupArchive(
            runId = "TEST-0002",
            target = corrupt,
            sandboxParentDir = sandboxParent
        )

        assertTrue(report.verifiedRestorable)
        assertFalse(report.completenessOk)
        assertFalse(report.healthCheckOk)
        assertFalse(report.overallPassed)
        assertTrue(report.metrics.hashMismatches.contains("config.json"))
        assertEquals(0, sandboxParent.listFiles()?.size ?: 0)
    }

    @Test
    fun incompleteBackupFailsWithMissingFiles() {
        val workspaceRoot = tempFolder.newFolder("workspace")
        val sandboxParent = tempFolder.newFolder("sandboxes")
        val seeded = BackupFixtureSeeder.ensureSeeded(workspaceRoot)
        val incomplete = seeded.backups.first { it.id == "bk_incomplete" }

        val report = RestoreProofWorker.verifyBackupArchive(
            runId = "TEST-0003",
            target = incomplete,
            sandboxParentDir = sandboxParent
        )

        assertTrue(report.verifiedRestorable)
        assertFalse(report.completenessOk)
        assertFalse(report.overallPassed)
        assertTrue(report.metrics.missingFiles.contains("ledger_index.json"))
        assertEquals(0, sandboxParent.listFiles()?.size ?: 0)
    }

    @Test
    fun zipSlipTraversalIsBlockedFailClosedWithoutWritingOutsideSandbox() {
        val workspaceRoot = tempFolder.newFolder("workspace")
        val sandboxParent = tempFolder.newFolder("sandboxes")
        val seeded = BackupFixtureSeeder.ensureSeeded(workspaceRoot)
        val zipSlip = seeded.backups.first { it.id == "bk_zipslip_probe" }

        val report = RestoreProofWorker.verifyBackupArchive(
            runId = "TEST-0004",
            target = zipSlip,
            sandboxParentDir = sandboxParent
        )

        assertFalse(report.verifiedRestorable)
        assertFalse(report.completenessOk)
        assertFalse(report.healthCheckOk)
        assertFalse(report.overallPassed)
        assertTrue(
            report.discrepancies.any {
                it.contains("traversal", ignoreCase = true) ||
                    it.contains("Security gate", ignoreCase = true)
            }
        )
        assertEquals(0, sandboxParent.listFiles()?.size ?: 0)
        assertFalse(File(workspaceRoot, "etc/shadow_escape").exists())
    }

    @Test
    fun syncTruthDetectsConfigDriftAndPassesOnExactMirror() {
        val workspaceRoot = tempFolder.newFolder("workspace")
        val seeded = BackupFixtureSeeder.ensureSeeded(workspaceRoot)

        val driftedPair = seeded.syncPairs.first { it.id == "sync_ledger_replica" }
        val driftReport = RestoreProofWorker.verifySyncTruth("SY-0001", driftedPair)
        assertFalse(driftReport.overallPassed)
        assertTrue(driftReport.metrics.hashMismatches.contains("config.json"))

        val healthyPair = seeded.syncPairs.first { it.id == "sync_auth_policy" }
        val okReport = RestoreProofWorker.verifySyncTruth("SY-0002", healthyPair)
        assertTrue(okReport.overallPassed)
        assertTrue(okReport.discrepancies.isEmpty())
    }
}
