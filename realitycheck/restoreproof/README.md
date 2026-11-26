# RestoreProof Worker (initial local worker)

This worker accepts only a PostgreSQL custom-format dump and an explicit JSON digest manifest. It checks the source digest, starts a disposable PostgreSQL container with no network, bounded CPU/memory/PIDs and read-only root filesystem, restores into that container, checks that user schemas exist, removes only the container created by the run, re-hashes the source, and writes a versioned JSON evidence report.

## Manifest

```json
{
  "schema": "realitycheck.restoreproof.manifest.v1",
  "filename": "backup.dump",
  "size_bytes": 123456,
  "sha256": "<64 lowercase hex characters>"
}
```

## Requirements

- Docker Engine available to the worker host.
- PostgreSQL image pre-pulled and referenced by immutable digest: `postgres@sha256:<64 hex>`.
- Never mount the Docker socket into an untrusted container. This worker itself runs on the trusted host and invokes Docker.
- Run as a dedicated unprivileged service account with access only to the designated backup and report directories.
- Worker host must have no production database credentials or production network route.

## Run

```bash
python -m realitycheck.restoreproof.worker \
  --backup /srv/restoreproof/input/backup.dump \
  --manifest /srv/restoreproof/input/backup.manifest.json \
  --report /srv/restoreproof/reports/run.json \
  --postgres-image postgres@sha256:<pinned-digest>
```

Exit code 0 is emitted only for PASS. All other verdicts exit non-zero.

## Current limitations

- The initial worker checks successful restore and presence of at least one user schema. Operator-configured invariants, table expectations, row counts, smoke queries, asynchronous job queueing, and multi-tenant target management are not yet implemented.
- This is a local worker CLI, not yet a hosted worker service. Do not expose it directly to the internet.
- The container runtime is a privileged boundary: only trusted operators may configure the image or invoke the worker.
- No production target or network attachment option exists.
