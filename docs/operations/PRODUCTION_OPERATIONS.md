# คู่มือปฏิบัติการ Production Operations

เอกสารนี้อธิบายการปฏิบัติงานที่มีอยู่จริงใน repository; ไม่ใช่การรับรองว่าได้ deploy หรือผ่านการทดสอบ production

## ขอบเขตและสถานะ

- **Implemented**: health/readiness, structured JSON logging, correlation headers, security headers, liveness probe และ CI static/build checks
- **Locally tested**: unit tests และ static checks เมื่อคำสั่งในส่วน test ถูกรันสำเร็จ
- **Static-only verified**: Dockerfile, Compose และ GitHub Actions
- **Not configured**: ระบบ metrics collector, backup storage และ external alert delivery
- **Blocked pending infrastructure**: PostgreSQL concurrency, Test PostgreSQL migration, HTTP E2E และ production-like multi-user testing

## Service lifecycle

API startup เรียก native runtime initialize แบบ asynchronous และ degraded เมื่อไม่มี model artifact; ไม่ fallback ไป external provider.
Shutdown unloads native model และ disposes SQLAlchemy engine pool.

ใช้ `/livez` สำหรับ process liveness และ `/readyz` สำหรับ readiness.
ห้ามใช้ `/livez` เป็น readiness และห้ามใช้ inference เพื่อ health probe.

## Operational routine

1. ตรวจ `/readyz` และ parse ค่า `status`, `database.status`, `native_ai.runtime_status`
2. ตรวจ logs สำหรับ `correlation_id`, `status_code`, `duration_ms`
3. ตรวจ native model mount และ database target โดย process configuration; ห้าม print secret
4. รักษา retry แบบ bounded และไม่ retry POST ที่ไม่ guaranteed idempotent
5. หยุดรับ traffic ผ่าน orchestrator ก่อน shutdown; uvicorn graceful shutdown เป็น 30 วินาที

## ความรับผิดชอบที่แยกต่างหาก

GitHub และ CI ไม่ใช่ production runtime
Docker Compose เป็น local/single-host stack เท่านั้น
Production deployment และ cloud provisioning ต้องมี authorization, target validation และ evidence แยก
