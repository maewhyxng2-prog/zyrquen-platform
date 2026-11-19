"""
ZYRQUEN Native Model Provisioning - Step 1
File: apps/core/download_model.py

หน้าที่เดียว: จัดเตรียม Model Artifact จริง จากแหล่งจริง
- ไม่แตะ apps/api/main.py
- ไม่สร้างไฟล์ที่มีอยู่แล้วซ้ำ
- ไม่เอา Weights เข้า Git / Docker Image

Base Model ในเฟสนี้:
  Qwen/Qwen2.5-0.5B = Open-Source Base Model (Qwen)
  ใช้เป็นฐานสำหรับทดสอบ Runtime ได้
  *** ไม่ใช่โมเดลที่ ZYRQUEN ฝึกและเป็นเจ้าของเอง ***
  ZYRQUEN Native Model Development เป็นเฟสแยกต่างหาก

สถานะที่ใช้: ready / degraded เท่านั้น
ห้ามใช้ is_healthy / online เพราะไม่มีใน Runtime เดิม
Runtime เดิมมีแค่: runtime.is_ready() และ runtime.get_health_status()
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Default: Cloud Volume / Local Data dir ไม่ใช่ใน repo
DEFAULT_MODEL_ID = "Qwen/Qwen2.5-0.5B"
DEFAULT_REVISION = "main"
DEFAULT_DEST = os.environ.get("ZYRQUEN_MODEL_DIR", "/data/models/qwen2.5-0.5b")
# ถ้ารันบนเครื่อง dev ที่ไม่มี /data ให้ใช้ ./models แทนได้ด้วย env นี้

def log(msg: str):
    print(f"[download_model] {msg}", flush=True)

def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def build_manifest(model_id: str, revision: str, dest: Path, files: list[str]) -> dict:
    entries = []
    for name in files:
        p = dest / name
        if p.is_file():
            entries.append({
                "file": name,
                "size_bytes": p.stat().st_size,
                "sha256": sha256_of_file(p),
            })
    return {
        "schema": "zyrquen.model-manifest.v1",
        "model_id": model_id,
        "revision": revision,
        "source": "huggingface-open-source-base-model",
        "ownership_note": "Base model for runtime testing only. NOT a ZYRQUEN-owned trained model.",
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "destination": str(dest),
        "storage_policy": "weights-on-cloud-volume-only, never-in-git, never-in-docker-image",
        "status": "ready" if entries else "degraded",
        "files": entries,
    }

def download_model(model_id: str, revision: str, dest: Path, force: bool = False) -> Path:
    """
    ดาวน์โหลดจริงจาก Hugging Face เท่านั้น ต้องมีเน็ต
    ห้ามจำลอง ห้ามสร้างไฟล์ปลอม
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        log("ERROR: huggingface_hub ยังไม่ติดตั้ง -> pip install huggingface_hub")
        sys.exit(1)

    dest.mkdir(parents=True, exist_ok=True)

    # ถ้ามี manifest + config ครบแล้ว และไม่ force ให้ข้าม ไม่โหลดซ้ำ
    manifest_path = dest / "manifest.json"
    config_path = dest / "config.json"
    if manifest_path.exists() and config_path.exists() and not force:
        log(f"Model มีอยู่แล้วที่ {dest} -> ข้ามการดาวน์โหลด (ใช้ --force ถ้าต้องการโหลดใหม่)")
        return dest

    log(f"Downloading {model_id}@{revision} -> {dest}")
    log("Source: Hugging Face (online only)")

    # snapshot_download จะโหลดไฟล์จริงทั้งหมดของโมเดลนี้
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=str(dest),
        local_dir_use_symlinks=False,
    )

    # Verify: ต้องมีไฟล์หลักจริง ไม่ใช่ไฟล์เปล่า
    required = ["config.json"]
    missing = [f for f in required if not (dest / f).exists()]
    if missing:
        log(f"ERROR: โหลดไม่ครบ ขาดไฟล์: {missing} -> status=degraded")
        sys.exit(1)

    # สร้าง manifest จากไฟล์จริงที่โหลดมา
    all_files = sorted(
        [str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file() and p.name != "manifest.json"]
    )
    manifest = build_manifest(model_id, revision, dest, all_files)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    log(f"OK status={manifest['status']} files={len(all_files)}")
    log(f"Manifest: {manifest_path}")
    return dest

def check_only(dest: Path) -> int:
    """เช็คเฉยๆ ไม่โหลด - ใช้ตอน Deploy ว่า Model พร้อมไหม"""
    manifest_path = dest / "manifest.json"
    config_path = dest / "config.json"
    if manifest_path.exists() and config_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            log(f"status=ready model={m.get('model_id')} files={len(m.get('files', []))} dest={dest}")
            return 0
        except Exception as e:
            log(f"status=degraded manifest อ่านไม่ได้: {e}")
            return 1
    log(f"status=degraded model ยังไม่พร้อมที่ {dest} - ต้องรัน download ก่อน")
    return 1

def main():
    parser = argparse.ArgumentParser(description="ZYRQUEN Model Provisioning - download real model artifact")
    parser.add_argument("--model", default=DEFAULT_MODEL_ID, help="HF repo id")
    parser.add_argument("--revision", default=DEFAULT_REVISION, help="HF revision / branch")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="ปลายทาง Cloud Volume เช่น /data/models/qwen2.5-0.5b")
    parser.add_argument("--force", action="store_true", help="โหลดใหม่ทับของเดิม")
    parser.add_argument("--check", action="store_true", help="เช็คอย่างเดียว ไม่โหลด")
    args = parser.parse_args()

    dest = Path(args.dest)

    if args.check:
        sys.exit(check_only(dest))

    download_model(args.model, args.revision, dest, force=args.force)
    sys.exit(check_only(dest))

if __name__ == "__main__":
    main()
