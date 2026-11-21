"""Phase 15 — Native Model Readiness — pure logic only.

No training, no dataset, no weights, no GPU, no deploy, no auto-promotion.
Config + compatibility + lifecycle only — no real model yet.
"""
from dataclasses import dataclass

@dataclass
class ModelConfig:
    vocab: int = 32000
    hidden: int = 256
    layers: int = 4
    kv_cache_size: int = 1024

    def to_dict(self):
        return {
            "vocab": self.vocab,
            "hidden": self.hidden,
            "layers": self.layers,
            "kv_cache_size": self.kv_cache_size,
        }

def check_compatibility(config, checkpoint_meta):
    """Training-to-Inference — config must match checkpoint, else BLOCK."""
    if not checkpoint_meta:
        return {"compatible": False, "reason": "missing checkpoint_meta"}
    for key in ["vocab", "hidden", "layers"]:
        if config.to_dict().get(key) != checkpoint_meta.get(key):
            return {
                "compatible": False,
                "reason": f"mismatch {key}: config={config.to_dict().get(key)} checkpoint={checkpoint_meta.get(key)}",
            }
    return {"compatible": True, "reason": ""}

class ModelRegistry:
    """Versioning & Lifecycle — registered -> validated -> promoted / rolled_back."""

    def __init__(self):
        self._models = {}

    def register_model(self, version, checkpoint_id, config):
        if version in self._models:
            return {"status": "blocked", "reason": f"version {version} already exists"}
        self._models[version] = {
            "version": version,
            "checkpoint_id": checkpoint_id,
            "config": config.to_dict(),
            "status": "registered",
            "reason": "",
        }
        return {"status": "registered", "version": version}

    def validate(self, version, checkpoint_meta=None):
        m = self._models.get(version)
        if not m:
            return {"status": "blocked", "reason": f"version {version} not found"}
        if m["status"] != "registered":
            return {"status": "blocked", "reason": f"cannot validate from {m['status']}"}
        # Rebuild config from stored dict for compatibility check
        cfg = ModelConfig(**m["config"])
        chk = check_compatibility(cfg, checkpoint_meta or m["config"])
        if not chk["compatible"]:
            m["status"] = "blocked"
            m["reason"] = chk["reason"]
            return {"status": "blocked", "reason": chk["reason"]}
        m["status"] = "validated"
        m["reason"] = ""
        return {"status": "validated", "version": version}

    def promote(self, version):
        m = self._models.get(version)
        if not m:
            return {"status": "blocked", "reason": f"version {version} not found"}
        if m["status"] != "validated":
            return {"status": "blocked", "reason": f"cannot promote from {m['status']} — must validate first"}
        m["status"] = "promoted"
        return {"status": "promoted", "version": version}

    def rollback(self, version, reason=""):
        m = self._models.get(version)
        if not m:
            return {"status": "blocked", "reason": f"version {version} not found"}
        m["status"] = "rolled_back"
        m["reason"] = reason or "rolled back"
        return {"status": "rolled_back", "version": version}

    def get(self, version):
        return self._models.get(version)
