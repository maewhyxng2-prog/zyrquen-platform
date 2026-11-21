# ZYRQUEN — Phase 10.9.9 Patch Status

* **Patch Format:** **`Full File Snapshot`** (สำเนาไฟล์ฉบับเต็มทั้ง 11 ไฟล์)
* **Unified Diff Generated:** **`NO`** (`NOT GENERATED — NO VERIFIED ORIGINAL BASELINE`)
* **Sync / Commit / Push Status:** **`NOT EXECUTED`** (รอดำเนินการตรวจสอบโดยเจ้าของโครงการใน GitHub Codespaces)

---

## คำอธิบายข้อจำกัด

1. **ไม่มี Original Baseline ที่ตรวจสอบได้จริงใน AI Studio:**
   เนื่องจาก `/app/applet` ไม่มี `.git` และไม่มีสำเนาไฟล์เดิมก่อนแก้ไขที่มี SHA-256 ยืนยันร่วมกับ `origin/main` การสร้าง Unified Diff ใน AI Studio จะเป็นการเดา Baseline ซึ่งขัดต่อข้อกำหนดความปลอดภัยด้านวิศวกรรม
2. **แนวทางที่ปลอดภัยที่สุด (Full File Snapshot + SHA-256 Verification):**
   ชุดส่งมอบนี้จึงจัดทำเป็นสำเนาไฟล์ฉบับเต็มที่ผ่านการตรวจเทียบ byte-for-byte กับ Workspace และยืนยันด้วย `SHA256SUMS` เพื่อให้ Codespaces ใช้ `git diff` กับฐานโค้ดจริงของ `main` ได้อย่างแม่นยำ

---

## ขั้นตอนนำเข้าและตรวจสอบใน GitHub Codespaces (Manual Owner Workflow)

1. ตรวจให้แน่ใจว่า Working Tree ใน Codespaces สะอาดและอยู่บน `main` ล่าสุด:
   ```bash
   cd /workspaces/zyrquen-platform
   git status
   git pull --ff-only origin main
   ```
2. นำโฟลเดอร์ `handoff/phase-10.9.9/` เข้า Codespaces แล้วตรวจสอบ SHA-256 ก่อนคัดลอก:
   ```bash
   (cd handoff/phase-10.9.9 && sha256sum -c SHA256SUMS)
   ```
3. คัดลอกเฉพาะ 11 ไฟล์ Python จาก `handoff/phase-10.9.9/apps/` ทับลงใน Repository Root:
   ```bash
   cp -v handoff/phase-10.9.9/apps/api/migrations/env.py apps/api/migrations/env.py
   cp -v handoff/phase-10.9.9/apps/api/test_migration_chain.py apps/api/test_migration_chain.py
   cp -v handoff/phase-10.9.9/apps/api/main.py apps/api/main.py
   cp -v handoff/phase-10.9.9/apps/api/routers/training.py apps/api/routers/training.py
   cp -v handoff/phase-10.9.9/apps/api/routers/inference.py apps/api/routers/inference.py
   cp -v handoff/phase-10.9.9/apps/api/training_jobs.py apps/api/training_jobs.py
   cp -v handoff/phase-10.9.9/apps/api/test_pg_integration.py apps/api/test_pg_integration.py
   cp -v handoff/phase-10.9.9/apps/api/test_main.py apps/api/test_main.py
   cp -v handoff/phase-10.9.9/apps/api/test_auth_gate.py apps/api/test_auth_gate.py
   cp -v handoff/phase-10.9.9/apps/api/test_training.py apps/api/test_training.py
   cp -v handoff/phase-10.9.9/apps/api/test_training_registry.py apps/api/test_training_registry.py
   ```
4. ตรวจสอบ `SHA256SUMS` ที่ Root และดู `git diff` เพื่อตรวจสอบทุกบรรทัดก่อน Commit:
   ```bash
   sha256sum -c handoff/phase-10.9.9/SHA256SUMS
   git diff -- apps/api/
   ```
5. หลังตรวจสอบ Diff และได้รับความเห็นชอบแล้ว จึงค่อย Commit, Push และตรวจสอบผล GitHub Actions `ZYRQUEN API Tests` ครบทั้ง 4 jobs (`web`, `docker`, `test`, `postgres-integration`)
