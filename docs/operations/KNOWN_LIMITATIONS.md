# Known Limitations and Unverified Capabilities

## Remaining Phase 6 blockers

1. PostgreSQL quota concurrency: not verified against real PostgreSQL
2. PostgreSQL migration execution: not verified against safe Test PostgreSQL
3. HTTP E2E and multi-user production-like testing: not verified

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
