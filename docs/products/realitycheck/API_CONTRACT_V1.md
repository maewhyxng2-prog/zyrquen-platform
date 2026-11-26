# RealityCheck — RestoreProof API Contract v1

## 1. Core Principles
- **Fail-Closed & No Fabrication:**
  - Insufficient evidence never produces `PASS`.
  - Unreachable backend must surface `UNREACHABLE` on clients (never stale cached `PASS`).
  - Active jobs report `RUNNING` (and `/v1/reports/{id}` returns `409 Conflict` until finished).
  - Restore/completeness failures report `FAIL`.
  - Missing dump, unsafe target DB name, or missing `pg_restore`/`psql`/Docker worker binaries report `BLOCKED`.
- **Traceable Evidence:** Every result is keyed by `run_id` and records `backup_artifact.sha256_actual`, `pg_restore_exit_code`, `health_query_exit_code`, `tables_found`, `missing_tables`, `total_rows_observed`, `discrepancies`, and UTC timestamps.
- **Standalone / Zero-AI:** Independent from ZYRQUEN's AI / Native Model components.

## 2. Standard Enums
- **RunStatus:** `RUNNING` | `PASS` | `FAIL` | `BLOCKED` (plus `UNREACHABLE` client-side state)
- **backup_format:** `postgresql_custom` (`.dump` for `pg_restore`)
- **target_isolation.mode:** `isolated_db` (create/restore/drop ephemeral DB on isolated Postgres) | `docker_ephemeral` (ephemeral `postgres` container with `--rm`)

## 3. Endpoints (v1)
1. `GET /v1/health` → `200 OK` (`service`, `version`, `status`, `isolated_worker_ready`, `checked_at`)
2. `POST /v1/verifications` → `202 Accepted` (`run_id`, `status: "RUNNING"`, `evidence_ref`)
3. `GET /v1/runs?limit=20&status=...` → `200 OK` (`items`, `total`)
4. `GET /v1/runs/{id}` → `200 OK` (`steps`, `discrepancies`, `report_id`)
5. `GET /v1/reports/{id}` → `200 OK` (or `409 Conflict` if `RUNNING`)
6. `GET /v1/reports/{id}/export` → `200 OK` downloadable JSON (`Content-Disposition: attachment; filename="restoreproof_{run_id}.json"`)
