# Health & Readiness Reference

## `/livez`

- HTTP 200: API process รับคำขอ
- ไม่เชื่อม database
- ไม่โหลด model
- ไม่เรียก inference
- ใช้ container/orchestrator liveness เท่านั้น

## `/readyz`

HTTP 200 เฉพาะเมื่อ database และ native runtime พร้อมจริง
HTTP 503 เมื่อ dependency unavailable หรือ degraded

Response fields:

- `database.status`: `healthy` หรือ `unavailable`
- `database.database`: `available` หรือ `unavailable`
- `native_ai.runtime_status`: `ready`, `degraded`, หรือ `not_configured`
- `native_ai.native_model_loaded`: boolean ที่ loader ตรวจจริง
- `native_ai.inference_available`: boolean

## `/health`

Endpoint backward-compatible aggregate ระดับ service มี dependency fields เดียวกับ `/readyz`
เมื่อไม่ healthy ให้ HTTP 503

## Database probe

ใช้ SQLAlchemy connection และ `SELECT 1`
Environment `test` ต้องผ่าน identity verification ใน table `public.zyrquen_environment_identity`
Configuration ไม่มีผลบังคับว่า database พร้อม
Endpoint ไม่ทำ migration
