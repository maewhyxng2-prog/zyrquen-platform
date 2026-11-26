# RealityCheck — RestoreProof MVP Product Specification

- Status: Product discovery / MVP proposal
- Product: RealityCheck
- First module: RestoreProof
- Implementation status: NOT IMPLEMENTED
- Decision rule: Do not claim a backup is recoverable until an isolated restore and post-restore checks have actually passed.

## 1. Product thesis

Backup status indicators and checksum validation do not prove recoverability. A checksum can prove that a file matches a recorded digest; it cannot prove that the backup can be restored, that the restored database is structurally usable, or that dependent services can operate against it.

RealityCheck is an independent verification tool. RestoreProof is its first narrow workflow: safely test a backup by restoring it into an isolated disposable environment and produce a verifiable evidence report.

The product must not claim that no competitors exist. Market differentiation and willingness to pay require customer interviews and competitor research before commercial launch.

## 2. Initial customer and problem

Initial target users:
- Small software teams operating PostgreSQL-backed services without a dedicated SRE team.
- Agencies and SaaS operators who need evidence that scheduled backups are actually recoverable.
- Managed service providers who need repeatable restore-test evidence for multiple customer environments.

Problem to validate:
- Teams may monitor backup job success and checksums but rarely rehearse complete restores.
- Manual restore drills are operationally risky, time-consuming, and difficult to repeat consistently.
- Teams need an auditable report that distinguishes file integrity from actual restore success.

## 3. MVP scope

### In scope

1. Accept a PostgreSQL custom-format dump as an input artifact.
2. Verify file presence, size, and SHA-256 against an explicit sidecar or manifest.
3. Start an isolated, disposable PostgreSQL test target with no route to production.
4. Restore only into that isolated target.
5. Run bounded post-restore checks:
   - database connection succeeds;
   - expected schemas/tables exist when supplied by the operator;
   - row-count or invariant checks run only when explicitly configured;
   - configured read-only smoke queries complete;
   - restore duration and check outcomes are recorded.
6. Produce a machine-readable JSON report and a concise human-readable summary.
7. Preserve evidence: input artifact digest, tool version, database version, timestamps, checks performed, results, and sanitized failure details.
8. Return distinct outcomes: PASS, FAIL, BLOCKED, NOT_RUN.

### Explicitly out of scope for MVP

- Restoring into production or modifying a live database.
- Automatic deletion or mutation of source backups.
- Cloud-provider account management.
- Generic verification of every system, API, security control, or business workflow.
- AI/LLM-based diagnosis or decision-making.
- Compliance certification or guarantees of RPO/RTO.
- Multi-cloud orchestration and enterprise dashboards.

## 4. Safety and isolation requirements

- Source backup is read-only; compute its digest before and after the test and require equality.
- Restore target must be disposable and isolated from production networks and credentials.
- Never read, print, log, or export secrets from environment files.
- Do not accept arbitrary shell commands from an untrusted report or backup.
- Apply strict CPU, memory, disk, and wall-clock limits.
- Enforce bounded input size and reject unsupported dump formats.
- Require explicit operator configuration for any external resource.
- Never automatically promote a test restore into production.
- Cleanup only resources created by the current run, after evidence is persisted; cleanup failure must be reported.
- Missing evidence must fail closed; never convert NOT_RUN or BLOCKED into PASS.

## 5. Evidence report contract

Each run must record:
- schema/version identifier;
- run ID and UTC start/end timestamps;
- tool version and source revision;
- backup filename (basename only), byte size, and SHA-256;
- expected digest source (sidecar or manifest);
- database engine/version and isolated target identity (non-secret);
- restore command profile (not raw credentials);
- restore duration;
- named checks with PASS/FAIL/BLOCKED/NOT_RUN and measured output;
- sanitized error category and message;
- source digest before/after;
- cleanup status;
- final verdict and reasons.

Do not include passwords, connection strings, tokens, full environment dumps, or sensitive row contents.

## 6. Acceptance criteria

The MVP is not complete until automated tests demonstrate:

1. Valid backup + valid digest + successful isolated restore => PASS.
2. Missing backup or digest => BLOCKED or FAIL, never PASS.
3. Digest mismatch => FAIL before restore.
4. Corrupt or unsupported dump => FAIL with a bounded, sanitized error.
5. Restore failure => FAIL.
6. Post-restore invariant failure => FAIL.
7. Timeout/resource-limit breach => BLOCKED or FAIL and safe cleanup.
8. Production target configuration is rejected by default; no production restore path exists in MVP.
9. Source backup digest remains unchanged.
10. Report schema is deterministic and contains no secrets.
11. Re-running the same fixture produces equivalent verdicts and evidence fields, excluding timestamps/run IDs.
12. Tests cover cleanup failure and partial restore failure.

## 7. Architecture proposal

Keep the first implementation small and independently testable:

- `realitycheck/restoreproof/cli.py`: command-line interface and explicit operator inputs.
- `realitycheck/restoreproof/manifest.py`: backup metadata and digest verification.
- `realitycheck/restoreproof/runner.py`: bounded run lifecycle.
- `realitycheck/restoreproof/postgres.py`: PostgreSQL dump inspection and isolated restore adapter.
- `realitycheck/restoreproof/checks.py`: post-restore checks.
- `realitycheck/restoreproof/report.py`: versioned JSON evidence report.
- `tests/restoreproof/`: unit, integration, failure-path, and safety tests.

Prefer standard, auditable system tools and direct deterministic checks. Keep product code separate from the existing Native Model / AEL training modules. Do not add UI until the CLI workflow and evidence contract are proven.

## 8. Commercial validation before expansion

Before building a hosted service or broad platform:
- Interview at least 8–12 target operators.
- Ask how they currently test restores, how often, what failures they have experienced, and what evidence they need.
- Identify current tools they already pay for and why those tools are insufficient.
- Test a landing page or pilot offer with a clear deliverable: scheduled restore drills plus signed evidence reports.
- Estimate per-run infrastructure cost and support burden.
- Continue only if several target users agree to run a pilot and at least some show willingness to pay.

## 9. Roadmap gates

- Gate 0 — Discovery: validate target customer, pain severity, alternatives, and willingness to pay.
- Gate 1 — CLI prototype: verify local fixture dumps in an isolated disposable PostgreSQL target.
- Gate 2 — Safety and reliability: pass failure-path, isolation, resource-limit, and cleanup tests.
- Gate 3 — Pilot: run with explicit operator approval on non-production backups.
- Gate 4 — Commercial decision: use pilot evidence, retention, support cost, and willingness to pay to decide whether to expand.

No later gate may be marked PASS without its required evidence.
