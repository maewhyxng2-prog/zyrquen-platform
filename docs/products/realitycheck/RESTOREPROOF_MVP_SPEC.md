# RealityCheck — RestoreProof MVP Specification

## 1. Product Positioning & Non-AI Architecture
- **Product Name:** RealityCheck (`RestoreProof` CLI & Verification Engine)
- **Category:** Software Testing, Verification & Operations Reliability Tool (Zero AI / Zero External API)
- **Core Principle:** *"Don't trust reported status — actively prove it in isolation."*
- **Independence:** Standalone deterministic verification toolkit. Uses standard library primitives (`hashlib`, `zipfile`, `tarfile`, `tempfile`, `subprocess`, `json`) with no LLM, no model training, and no external network calls.

## 2. Locked MVP Scope (3 Core Probes + RestoreProof CLI)

### A. RealityCheck Core Probes (`python_core/reality_check/`)
1. **Backup & Restore Proof (`restore`)**
   - Unpacks backup archive safely inside an isolated temporary workspace (rejecting path traversal / symlink escapes).
   - Verifies non-empty restored file set, required paths, and SHA-256 checksums against expected manifest hashes.
2. **Source-Target Sync Truth (`sync`)**
   - Walks source and target directories deterministically and compares relative paths + SHA-256 hashes.
   - Detects missing files, stale/extra files in target, and silent content corruption.
3. **Execution & Config Reality (`execution`)**
   - Executes an independent verification command with timeout bounds.
   - Checks exit code (`0`), expected stdout evidence, and required filesystem state.

### B. RestoreProof CLI (`python_core/restoreproof_cli/`)
Command:
```bash
python3 python_core/restoreproof_cli/cli.py verify \
  --backup <archive_path> \
  [--min-files 1] \
  [--manifest <manifest.json>] \
  [--restore-cmd "<command>"] \
  [--health-cmd "<command>"] \
  [--timeout-sec 30] \
  [--out <report.json>]
```

## 3. Production Safety & Fail-Closed Guarantees
- **Read-Only on Production Artifacts:** Never modifies the input backup archive or source files.
- **Isolated Workspace:** All extraction, `--restore-cmd`, and `--health-cmd` run inside a freshly created `tempfile.mkdtemp(...)` directory, always removed in a `finally` block.
- **Archive Extraction Safety:** Rejects Zip-Slip / Tar-Slip path traversal (`..` escapes, absolute member paths, and external symlinks/hardlinks) before writing bytes.
- **Fail-Closed Exit Codes:**
  - `0` — All enabled checks passed (`verified_restorable && completeness_ok && health_check_ok`).
  - `1` — Verification failed (missing/corrupt archive, missing files, SHA-256 mismatch, restore command failure, or health check failure).
  - `2` — Invalid CLI invocation or unreadable/invalid manifest schema.

## 4. Mandatory First-Wave Failure Scenarios
Automated verification must explicitly prove failure detection for:
1. Corrupted or unreadable backup archive (`verified_restorable = false`, exit code `1`).
2. Restored files missing or modified vs. manifest SHA-256 (`completeness_ok = false`, exit code `1`).
3. Restore succeeds at file level, but `--restore-cmd` or `--health-cmd` fails readiness (`health_check_ok = false`, exit code `1`).
4. Unsafe archive containing path traversal (`../`) blocked fail-closed.

## 5. JSON Evidence Report Schema (`RestoreProofReport`)
- `target`: Path to verified backup artifact
- `verified_restorable`: Boolean
- `completeness_ok`: Boolean
- `health_check_ok`: Boolean
- `overall_passed`: Boolean (`verified_restorable && completeness_ok && health_check_ok`)
- `discrepancies`: List of explicit failure reasons (empty when passed)
- `metrics`: `backup_exists`, `backup_sha256`, `restored_file_count`, `min_files_required`, `missing_files`, `hash_mismatches`, `restore_cmd_rc`, `health_cmd_rc`, stdout/stderr tails
- `checked_at`: UTC ISO-8601 timestamp
