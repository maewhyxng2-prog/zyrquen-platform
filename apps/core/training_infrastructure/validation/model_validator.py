import math
from dataclasses import dataclass, field
from pathlib import Path

from ..recovery.checkpoint_recovery import CheckpointManager


@dataclass
class ValidationReport:
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c["passed"] for c in self.checks)


class ModelValidator:
    """Gate before handing a checkpoint to Phase 5: integrity + evaluation thresholds."""

    def __init__(self, max_val_loss: float | None = None, max_perplexity: float | None = None):
        self.max_val_loss = max_val_loss
        self.max_perplexity = max_perplexity

    def validate(self, checkpoint_dir: str | Path, metrics: dict) -> ValidationReport:
        r = ValidationReport()
        mgr = CheckpointManager(checkpoint_dir)
        entry = mgr.latest_valid()
        r.add("checkpoint_integrity", entry is not None,
              entry["file"] if entry else "no checkpoint with a valid SHA-256")

        val = metrics.get("val_loss")
        ok = isinstance(val, (int, float)) and math.isfinite(val)
        r.add("val_loss_finite", ok, str(val))
        if ok and self.max_val_loss is not None:
            r.add("val_loss_threshold", val <= self.max_val_loss, f"{val} <= {self.max_val_loss}")
        if self.max_perplexity is not None:
            ppl = metrics.get("perplexity")
            ok_p = isinstance(ppl, (int, float)) and math.isfinite(ppl) and ppl <= self.max_perplexity
            r.add("perplexity_threshold", ok_p, f"{ppl} <= {self.max_perplexity}")
        return r
