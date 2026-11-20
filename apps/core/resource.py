import os
import sys
import time

class ResourceLimitExceededError(Exception):
    pass

def _ram_mb():
    try:
        import psutil
        p = psutil.Process(os.getpid())
        return p.memory_info().rss / 1024 / 1024
    except Exception:
        pass
    try:
        import resource
        v = resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss
        if sys.platform == "darwin":
            return v / 1024 / 1024
        return v / 1024
    except Exception:
        return 0.0

def _vram_mb():
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0, False
        total = 0.0
        for i in range(
            torch.cuda.device_count()
        ):
            total += (
                torch.cuda.memory_allocated(i)
                / 1024 / 1024
            )
        return total, True
    except Exception:
        return 0.0, False

class ResourceManager:
    def __init__(
        self,
        max_ram_mb=4096,
        max_vram_mb=4096,
        max_tokens_per_request=1024,
        max_seconds_per_request=60,
    ):
        self.max_ram_mb = max_ram_mb
        self.max_vram_mb = max_vram_mb
        self.max_tokens_per_request = (
            max_tokens_per_request
        )
        self.max_seconds_per_request = (
            max_seconds_per_request
        )

    def snapshot(self):
        ram = _ram_mb()
        vram, vram_ok = _vram_mb()
        return {
            "ram_mb": round(ram, 2),
            "vram_mb": round(vram, 2),
            "vram_available": vram_ok,
            "timestamp": time.time(),
        }

    def check_request(
        self, tokens=0, started_at=None
    ):
        if tokens > self.max_tokens_per_request:
            raise ResourceLimitExceededError(
                "token limit exceeded"
            )
        if started_at is not None:
            elapsed = time.time() - started_at
            if elapsed > self.max_seconds_per_request:
                raise ResourceLimitExceededError(
                    "time limit exceeded"
                )
        snap = self.snapshot()
        if (
            self.max_ram_mb
            and snap["ram_mb"] > self.max_ram_mb
        ):
            raise ResourceLimitExceededError(
                "ram limit exceeded"
            )
        if (
            snap["vram_available"]
            and self.max_vram_mb
            and snap["vram_mb"] > self.max_vram_mb
        ):
            raise ResourceLimitExceededError(
                "vram limit exceeded"
            )
        return snap
