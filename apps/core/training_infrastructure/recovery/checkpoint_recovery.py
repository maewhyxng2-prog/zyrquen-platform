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


def _torch_load(path: str) -> Any:
    import torch
    return torch.load(path, map_location="cpu", weights_only=False)


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
    random.setstate(state["python"])
    if "torch" in state:
        import torch
        torch.set_rng_state(state["torch"])
        if "cuda" in state and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(state["cuda"])


class CheckpointManager:
    """Atomic checkpoints + SHA-256 manifest. The caller supplies the state dict
    (model, optimizer, scheduler, step, rng ...). Corrupt checkpoints are skipped."""

    def __init__(self, directory: str | Path, keep_last: int = 3,
                 save_fn: Callable[[Any, str], None] = _torch_save,
                 load_fn: Callable[[str], Any] = _torch_load):
        if keep_last < 1:
            raise ValueError("keep_last must be >= 1")
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep_last = keep_last
        self._save, self._load = save_fn, load_fn

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    def _read_manifest(self) -> list[dict]:
        if not self.manifest_path.is_file():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data["checkpoints"] if data.get("schema") == SCHEMA else []
        except (json.JSONDecodeError, KeyError):
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
            (self.dir / old["file"]).unlink(missing_ok=True)
        self._write_manifest(entries[-self.keep_last:])
        return final

    def verify(self, entry: dict) -> bool:
        p = self.dir / entry["file"]
        return p.is_file() and p.stat().st_size == entry["size_bytes"] and _sha256(p) == entry["sha256"]

    def latest_valid(self) -> dict | None:
        for entry in reversed(self._read_manifest()):
            if self.verify(entry):
                return entry
        return None

    def load_latest(self) -> tuple[int, Any] | None:
        entry = self.latest_valid()
        if entry is None:
            return None
        return entry["step"], self._load(str(self.dir / entry["file"]))
