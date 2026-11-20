# Deployment Readiness Checklist

รายการนี้เป็น checklist ไม่ใช่คำรับรอง readiness

## Pre-deployment

- [ ] กำหนด `ZYRQUEN_ENV=production`
- [ ] กำหนด `JWT_SECRET_KEY` ความยาวอย่างน้อย 32 characters โดยไม่บันทึกลง source
- [ ] ตรวจ PostgreSQL target ด้วย database safety guards และ verified target settings
- [ ] กำหนด `ZYRQUEN_CORS_ALLOW_ORIGINS` รายชื่อ exact origins; ห้าม `*`
- [ ] กำหนด trusted proxy exact IP/CIDR
- [ ] mount native model artifact แบบอ่านได้และตรวจ native runtime ready จริง
- [ ] ตรวจ resource limits, storage และ backup target
- [ ] ตรวจ `/livez` และ `/readyz`
- [ ] รัน unit test suite บน SQLite และ static Docker/CI checks

## Deployment evidence required

- [ ] Safe Test PostgreSQL migration evidence
- [ ] PostgreSQL concurrency evidence
- [ ] HTTP E2E and multi-user evidence
- [ ] backup creation/restoration verification evidence
- [ ] alert delivery verification evidence
- [ ] metrics collector configuration evidence

## Rollback

หยุด traffic, รักษา database state และ rollback application artifact/revision
ห้ามทำ destructive database operation
หาก schema ไม่ compatible ให้หยุด deployment และดำเนิน incident process
