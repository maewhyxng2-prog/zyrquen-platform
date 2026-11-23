import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

SCHEMA = "zyrquen.checkpoint-manifest.v1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _torch_save(obj: Any, path: str) -> None:
    import torch
    torch.save(obj, path)


def _safe_torch_load(path: str) -> Any:
    import torch
    return torch.load(path, map_location="cpu", weights_only=True)


def _torch_load(path: str) -> Any:
    """Default checkpoint loader enforces weights_only=True."""
    return _safe_torch_load(path)


def _normalize_python_rng_state(raw_state: Any) -> tuple:
    if not isinstance(raw_state, (tuple, list)) or len(raw_state) != 3:
        raise ValueError("invalid Python RNG state in checkpoint")
    version, internal_state, gauss_next = raw_state
    if not isinstance(version, int) or not isinstance(internal_state, (tuple, list)):
        raise ValueError("invalid Python RNG internal state in checkpoint")
    return (version, tuple(internal_state), gauss_next)


def capture_rng_state() -> dict:
    state = {"python": random.getstate()}
    try:
        import torch
        state["torch"] = torch.get_rng_state()
        if torch.cuda.is_available():
            state["cuda"] = torch.cuda.get_rng_state_all()
    except ImportError:
        pass
    return state


def restore_rng_state(state: dict) -> None:
    if not isinstance(state, dict) or "python" not in state:
        raise ValueError("checkpoint RNG state is missing 'python'")
    random.setstate(_normalize_python_rng_state(state["python"]))
    if "torch" in state:
        import torch
        torch.set_rng_state(state["torch"])
        if "cuda" in state and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(state["cuda"])


class CheckpointManager:
    """Atomic checkpoints with SHA-256 manifests and safe-only deserialization.

    Checkpoints are loaded exclusively with torch.load(weights_only=True).
    Legacy pickle fallback is intentionally unsupported: a matching SHA-256
    proves file consistency, not that a pickle payload is trusted.
    """

    def __init__(self, directory: str | Path, keep_last: int = 3,
                 save_fn: Callable[[Any, str], None] = _torch_save,
                 load_fn: Callable[[str], Any] = _safe_torch_load,
                 *, allow_unsafe_pickle: bool = False):
        if keep_last < 1:
            raise ValueError("keep_last must be >= 1")
        if allow_unsafe_pickle:
            raise ValueError("allow_unsafe_pickle is disabled; legacy pickle loading is prohibited")
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep_last = keep_last
        self._save, self._load = save_fn, load_fn
        self._allow_unsafe_pickle = False

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    def _safe_checkpoint_path(self, filename: Any) -> Path | None:
        if not isinstance(filename, str) or not filename.strip():
            return None
        rel = Path(filename)
        if rel.is_absolute() or len(rel.parts) != 1:
            return None
        if self.dir.is_symlink():
            return None
        candidate = self.dir / rel
        if candidate.is_symlink():
            return None
        resolved_dir = self.dir.resolve()
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_dir):
            return None
        return resolved_candidate

    def _read_manifest(self) -> list[dict]:
        if not self.manifest_path.is_file() or self.manifest_path.is_symlink():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data["checkpoints"] if data.get("schema") == SCHEMA else []
        except (json.JSONDecodeError, KeyError, OSError):
            return []

    def _write_manifest(self, entries: list[dict]) -> None:
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": SCHEMA, "checkpoints": entries}, indent=2), encoding="utf-8")
        os.replace(tmp, self.manifest_path)

    def save(self, step: int, state: Any) -> Path:
        name = f"ckpt_{step:08d}.pt"
        final, tmp = self.dir / name, self.dir / (name + ".tmp")
        self._save(state, str(tmp))
        os.replace(tmp, final)
        entries = [e for e in self._read_manifest() if e["step"] != step]
        entries.append({"step": step, "file": name, "size_bytes": final.stat().st_size,
                        "sha256": _sha256(final)})
        entries.sort(key=lambda e: e["step"])
        for old in entries[:-self.keep_last]:
            old_path = self._safe_checkpoint_path(old.get("file"))
            if old_path is not None:
                old_path.unlink(missing_ok=True)
        self._write_manifest(entries[-self.keep_last:])
        return final

    def verify(self, entry: dict) -> bool:
        if not isinstance(entry, dict):
            return False
        p = self._safe_checkpoint_path(entry.get("file"))
        if p is None or not p.is_file():
            return False
        return p.stat().st_size == entry.get("size_bytes") and _sha256(p) == entry.get("sha256")

    def latest_valid(self) -> dict | None:
        for entry in reversed(self._read_manifest()):
            if self.verify(entry):
                return entry
        return None

    def load_latest(self) -> tuple[int, Any] | None:
        entry = self.latest_valid()
        if entry is None:
            return None
        p = self._safe_checkpoint_path(entry["file"])
        if p is None:
            return None
        return entry["step"], self._load(str(p))
