# Incident Response Runbook

## Classification

- API liveness failure
- readiness/database failure
- native model degraded/not_configured
- authentication/rate-limit failure
- backup/recovery failure
- suspected credential or API-key exposure

## Immediate actions

1. Preserve correlation IDs and affected timestamps
2. Check `/livez`, `/readyz`, `/health`
3. Identify database and runtime status; do not infer from configuration
4. Rate-limit or isolate failing traffic
5. Stop background/retraining work if it consumes resources
6. Escalate database/native model incidents to service owners

## Security incidents

ยกเลิก access/API tokens ผ่าน backend, rotate secret ด้วย approved process
ห้ามแก้ code เพื่อปิด security checks
ห้าม paste credential/URL/token ลง ticket

## Recovery

ใช้ Backup & Recovery Runbook
ตรวจ evidence ก่อนประกาศ recovered
บันทึก blockers และยืนยันว่าไม่ได้ทำ fake backup/health/alert
