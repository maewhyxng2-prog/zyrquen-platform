# Known Limitations and Unverified Capabilities

## Remaining Phase 6 blockers

1. PostgreSQL quota concurrency: not verified against real PostgreSQL
2. PostgreSQL migration execution: not verified against safe Test PostgreSQL
3. HTTP E2E and multi-user production-like testing: not verified

## Phase 6-7 blocker closure status

- **Quota concurrency:** BLOCKED locally because no explicitly identified, safe Test PostgreSQL configuration was available. A PostgreSQL integration test module and fail-on-missing CI job are implemented, but no real-PG PASS result exists yet.
- **Alembic migration:** BLOCKED locally because no explicitly identified, safe Test PostgreSQL configuration was available. Migration-chain static tests pass and rev 01 now bootstraps an empty `users` baseline only when the table is absent; real upgrade/downgrade evidence remains pending.
- **HTTP E2E:** BLOCKED locally because no explicitly identified, safe Test PostgreSQL configuration was available. Test preparation exists for real FastAPI HTTP behavior, but no real-PG E2E PASS result exists yet.

## Phase 7 static-only areas

- Dockerfile/Compose configuration
- GitHub Actions workflow syntax/configuration
- migration static compilation

## Not configured

- Prometheus/OpenTelemetry metrics collector
- external log aggregation
- backup storage/schedules
- alert delivery
- cloud deployment

## Explicitly not performed

- production database access
- migrations
- production backup/restore
- infrastructure provisioning
- paid resources
- Git commit/push
- deployment or image publishing
