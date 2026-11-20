import json
import math
import time
from pathlib import Path
from typing import Callable


class TrainingMonitor:
    """Append-only JSONL log of training metrics (one record per logged step)."""

    def __init__(self, path: str | Path, clock: Callable[[], float] = time.monotonic):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._last_time: float | None = None

    def log(self, step: int, loss: float, lr: float, tokens: int | None = None,
            gpu: dict | None = None) -> dict:
        now = self._clock()
        record = {"step": step, "loss": loss, "lr": lr, "wall_time": time.time()}
        if tokens is not None and self._last_time is not None and now > self._last_time:
            record["tokens_per_sec"] = tokens / (now - self._last_time)
        if gpu:
            record["gpu"] = gpu
        record["diverged"] = not math.isfinite(loss)
        self._last_time = now
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, allow_nan=True) + "\n")
        return record

    def history(self) -> list[dict]:
        if not self.path.is_file():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerate a torn last line after a crash
        return records

    def summary(self) -> dict:
        h = self.history()
        if not h:
            return {"records": 0}
        finite = [r["loss"] for r in h if math.isfinite(r["loss"])]
        return {
            "records": len(h),
            "last_step": h[-1]["step"],
            "last_loss": h[-1]["loss"],
            "best_loss": min(finite) if finite else None,
            "diverged": any(r["diverged"] for r in h),
        }
