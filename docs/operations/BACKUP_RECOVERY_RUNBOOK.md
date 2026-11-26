# Backup & Recovery Runbook

## สถานะ

- **not_configured**: backup storage, schedule และ encrypted off-host storage
- **not_executed**: production backup/restore
- **safe tooling**: SHA-256 backup integrity verifier ภายใน `scripts/verify_backup_integrity.py`

## RPO/RTO

RPO และ RTO เป็น operational targets ที่ผู้รับผิดชอบกำหนด ไม่ใช่ guarantee
ตัวอย่างให้ตั้งเป็นค่าเป็นชั่วโมงและทดสอบจริงก่อนประกาศ

## Database backup

ดำเนินเฉพาะบน approved Test/Production environment โดย operator ที่ได้รับอนุญาต
ตัวอย่างแนวทาง PostgreSQL:

```bash
pg_dump --format=custom --no-owner --no-acl "$DATABASE_URL"
sha256sum zyrquen.dump > zyrquen.dump.sha256
```

ห้ามอ่านหรือพิมพ์ `.env`
ห้ามใช้ API startup หรือ migration เพื่อแทน backup procedure

## Integrity verification

```bash
python scripts/verify_backup_integrity.py zyrquen.dump
```

Tool ตรวจ file/hash เท่านั้น ไม่มีการเชื่อม database
สำหรับ manifest:

```bash
python scripts/verify_backup_integrity.py zyrquen.dump --manifest SHA256SUMS
```

## Restore

1. หยุด write traffic
2. ยืนยัน recovery target และ safety identity
3. ยืนยัน backup checksum
4. restore ลง isolated Test database ก่อน
5. smoke-test schema/API/native health
6. มี dual approval ก่อน restore production
7. บันทึกเวลาเริ่มต้นและสิ้นสุดจริงเพื่อวัด RTO

ห้ามใช้ repository tool เพื่อ restore; ส่วนนี้บังคับผ่าน approved runbook/control plane
