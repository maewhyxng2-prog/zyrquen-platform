from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ClaimSpec:
    """A claim made by a system that RealityCheck must actively test rather than trust."""

    claim_id: str
    probe_type: str  # "restore" | "sync" | "execution"
    claimed_status: str
    target: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceItem:
    claim_id: str
    probe_type: str
    claimed_status: str
    verified_real: bool
    discrepancy: str
    observed: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class RealityReport:
    suite_name: str
    total_claims: int
    verified_true_count: int
    contradiction_count: int
    all_verified_true: bool
    evidence: List[EvidenceItem]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save_json(self, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return out_path
