# ZYRQUEN API - Dockerfile
# Build Context ต้องเป็น Repository Root เท่านั้น
# ห้าม Build จากใน apps/api/ เพราะจะมองไม่เห็น apps/core
# คำสั่ง Build ที่ถูกต้อง (รันที่ Root):
# docker build -f apps/api/Dockerfile -t zyrquen-api:test .

FROM python:3.11-slim

# ไม่สร้าง .pyc / ให้ log ออกทันที
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/apps/api \
    ZYRQUEN_MODEL_PATH=/data/models/zyrquen-native-v1 \
    PORT=8000

WORKDIR /app

# ติดตั้ง lib ระบบที่จำเป็นสำหรับ healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 1. ติดตั้ง Dependencies จาก apps/api ก่อน (เพื่อใช้ Docker Layer Cache)
COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

# 2. Copy โค้ดทั้ง 2 ฝั่งจาก Root - ห้าม Copy แค่ฝั่งเดียว
COPY apps/api ./apps/api
COPY apps/core ./apps/core

# 3. Prepare the native-model mount path and run the service without root.
RUN groupadd --system --gid 10001 zyrquen \
    && useradd --system --uid 10001 --gid zyrquen --home-dir /home/zyrquen \
        --create-home --shell /usr/sbin/nologin zyrquen \
    && mkdir -p /data/models /data/datasets /data/tokenizers /data/training \
    && chown -R 10001:10001 \
        /data/models /data/datasets /data/tokenizers /data/training /home/zyrquen

# 4. เปิดพอร์ต API
EXPOSE 8000

# 5. Healthcheck - ใช้ endpoint เดิมที่มีอยู่แล้วใน main.py
# main.py เดิมมี / และ /health อยู่แล้ว ไม่ต้องสร้าง endpoint ใหม่
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 6. รัน API จาก Root Path - PYTHONPATH รวม /app (apps.core) และ /app/apps/api
#    (routers, database, security ที่ main.py import แบบ top-level)
USER 10001:10001
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
