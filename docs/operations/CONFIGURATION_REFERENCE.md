# Configuration Reference

## Required runtime

- `ZYRQUEN_ENV`: `unit_test`, `test`, `development`, หรือ `production`
- `DATABASE_URL`: database URL ที่ผ่าน database target validation
- `JWT_SECRET_KEY`: production อย่างน้อย 32 characters
- `ZYRQUEN_MODEL_PATH`: local native model directory

## Database safety

Development: host/port/name ต้องตรงกับ:
`ZYRQUEN_DEVELOPMENT_DATABASE_HOST`, `PORT`, `NAME`

Production: host/port/name ต้องตรงกับ:
`ZYRQUEN_PRODUCTION_DATABASE_HOST`, `PORT`, `NAME`

Test: ระบุ test host/port/name/id และ protected production deny lists

## Security

- `ZYRQUEN_CORS_ALLOW_ORIGINS`: exact origins, comma-separated
- `ZYRQUEN_TRUSTED_PROXY_IPS`: exact proxies, comma-separated IP/CIDR
- `ZYRQUEN_ADMIN_USER_IDS`: trusted user UUID IDs
- `ZYRQUEN_TRAINING_ADMIN_EMAILS`: admin allowlist when used

## Data paths

- `ZYRQUEN_DATASET_DIR`
- `ZYRQUEN_TOKENIZER_PATH`
- `ZYRQUEN_TRAINING_ROOT`
- `ZYRQUEN_MODEL_REGISTRY_ROOT`

## Unsupported or unconfigured

- OpenTelemetry/Prometheus endpoint
- backup storage
- alert delivery
- external inference providers
