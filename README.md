# RealityCheck (Android)

RealityCheck is a native Android (Kotlin + Jetpack Compose) verification and operations application centered on the **RestoreProof Worker**, **Evidence Engine**, **Tier-2 Governance Gate**, and **AI Operations Assistant** (powered by Firebase AI Logic).

## Architecture & Separation of Responsibilities

| Component | Package | Responsibility |
| --- | --- | --- |
| **RestoreProof Worker** | `com.example.engine.RestoreProofWorker` | Real read-only `.zip` extraction inside isolated temporary sandboxes (`restoreproof_iso_*`), Zip-Slip path traversal blocking (fail-closed), SHA-256 checksum & completeness verification, config readiness probes, Sync Truth drift detection, and guaranteed `finally` sandbox cleanup. |
| **Evidence Engine & Store** | `com.example.data.EvidenceRepository` | Generates immutable `RestoreProofReport` records with sequential `Run ID`s (`RP-*`, `SY-*`, `ISO-*`), persists reports, approval queue, and audit logs locally, and exports JSON evidence. |
| **AI Operations Assistant** | `com.example.ai.AiOperationsAssistant` | Powered by Firebase AI Logic (`gemini-3.8-flash` + App Check). Parses natural-language commands into structured execution plans, invokes real `RestoreProofWorker` tools, streams root-cause analysis referencing verified `Run ID`s and SHA-256 digests, and submits remediation proposals to the Approval Gate. **AI has zero authority to fabricate `PASS` results or execute live restores.** |
| **Governance & Approval Gate** | `com.example.ui.screens.GovernanceScreen` | Enforces RBAC (`OPERATOR` vs `ADMIN`), keeps production restore execution `LOCKED` (`ISOLATION_TESTS_PASSED_RESTORE_GATED`) until isolation verification passes and Admin approval is recorded, and maintains an immutable Audit Trail. |

## Verification & Testing

Run local JVM unit tests for `RestoreProofWorker` (healthy backup, tampered hash detection, missing file detection, Zip-Slip fail-closed blocking, and Sync Truth drift checks):

```bash
gradle :app:testDebugUnitTest
```

Build debug APK:

```bash
gradle :app:assembleDebug
```
