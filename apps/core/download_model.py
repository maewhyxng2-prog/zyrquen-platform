
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-0.5B"
DEFAULT_REVISION = "main"
DEFAULT_DEST = os.environ.get(
    "ZYRQUEN_MODEL_DIR",
    "/data/models/qwen2.5-0.5b",
)


def log(message: str) -> None:
    print(f"[download_model] {message}", flush=True)


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def collect_model_files(dest: Path) -> list[Path]:
    return sorted(
        path for path in dest.rglob("*")
        if path.is_file()
        and path.name != "manifest.json"
        and ".cache" not in path.parts
    )


def build_manifest(
    model_id: str,
    revision: str,
    dest: Path,
    files: list[Path],
) -> dict:
    entries = []

    for path in files:
        entries.append({
            "file": str(path.relative_to(dest)),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_of_file(path),
        })

    has_weights = any(
        path.suffix.lower() in {".safetensors", ".bin", ".gguf"}
        for path in files
    )

    ready = (
        any(path.name == "config.json" for path in files)
        and has_weights
        and bool(entries)
        and all(entry["size_bytes"] > 0 for entry in entries)
    )

    return {
        "schema": "zyrquen.model-manifest.v1",
        "model_id": model_id,
        "revision": revision,
        "source": "huggingface-open-source-base-model",
        "ownership_note": (
            "Open-source base model for runtime testing only. "
            "Not a ZYRQUEN-owned trained model."
        ),
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "destination": str(dest),
        "storage_policy": (
            "weights-on-cloud-volume-only; "
            "never-in-git; never-in-docker-image"
        ),
        "status": "ready" if ready else "degraded",
        "files": entries,
    }


def download_model(
    model_id: str,
    revision: str,
    dest: Path,
    force: bool = False,
) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Install huggingface_hub before downloading."
        ) from exc

    manifest_path = dest / "manifest.json"

    if manifest_path.exists() and not force:
        if check_only(dest) == 0:
            log(f"Verified model already exists: {dest}")
            return dest

    dest.mkdir(parents=True, exist_ok=True)

    log(f"Downloading {model_id}@{revision}")
    log(f"Destination: {dest}")
    log("Source: Hugging Face; internet connection required.")

    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=str(dest),
    )

    files = collect_model_files(dest)

    manifest = build_manifest(
        model_id,
        revision,
        dest,
        files,
    )

    temporary_manifest = dest / "manifest.json.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)

    log(
        f"Provisioning status: {manifest['status']}; "
        f"files: {len(files)}"
    )

    if manifest["status"] != "ready":
        raise RuntimeError(
            "Model verification failed. Status: degraded."
        )

    return dest


def check_only(dest: Path) -> int:
    manifest_path = dest / "manifest.json"

    if not manifest_path.is_file():
        log("status=degraded; manifest not found.")
        return 1

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        if manifest.get("schema") != "zyrquen.model-manifest.v1":
            raise ValueError("Unsupported manifest schema.")

        if not manifest.get("files"):
            raise ValueError("Manifest contains no model files.")

        for entry in manifest["files"]:
            path = dest / entry["file"]

            if not path.is_file():
                raise ValueError(f"Missing file: {entry['file']}")

            if path.stat().st_size != entry["size_bytes"]:
                raise ValueError(f"Size mismatch: {entry['file']}")

            if sha256_of_file(path) != entry["sha256"]:
                raise ValueError(f"SHA-256 mismatch: {entry['file']}")

        has_config = (dest / "config.json").is_file()

        has_weights = any(
            (dest / entry["file"]).suffix.lower()
            in {".safetensors", ".bin", ".gguf"}
            for entry in manifest["files"]
        )

        if not has_config or not has_weights:
            raise ValueError("Model configuration or weights missing.")

        log(
            f"status=ready model={manifest['model_id']} "
            f"files={len(manifest['files'])} destination={dest}"
        )
        return 0

    except Exception as exc:
        log(f"status=degraded; verification failed: {exc}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ZYRQUEN Native Model Provisioning"
    )

    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")

    args = parser.parse_args()
    dest = Path(args.dest)

    if args.check:
        raise SystemExit(check_only(dest))

    try:
        download_model(
            args.model,
            args.revision,
            dest,
            force=args.force,
        )
    except Exception as exc:
        log(f"status=degraded; {exc}")
        raise SystemExit(1)

    raise SystemExit(check_only(dest))


if __name__ == "__main__":
    main()
