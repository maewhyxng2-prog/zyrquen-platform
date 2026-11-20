import subprocess
from dataclasses import dataclass
from typing import Callable

_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
    "--format=csv,noheader,nounits",
]


@dataclass(frozen=True)
class GpuInfo:
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    utilization_pct: int


def _default_runner(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True).stdout


class ResourceManager:
    """Detects real NVIDIA GPUs via nvidia-smi. Returns [] when none/unavailable."""

    def __init__(self, runner: Callable[[list[str]], str] = _default_runner):
        self._runner = runner

    def list_gpus(self) -> list[GpuInfo]:
        try:
            out = self._runner(_QUERY)
        except (OSError, subprocess.SubprocessError):
            return []
        gpus = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 5:
                continue
            try:
                gpus.append(GpuInfo(int(parts[0]), parts[1], int(parts[2]), int(parts[3]), int(parts[4])))
            except ValueError:
                continue
        return gpus

    def select_device(self) -> str:
        return "cuda" if self.list_gpus() else "cpu"

    def free_memory_mb(self, index: int = 0) -> int | None:
        for g in self.list_gpus():
            if g.index == index:
                return g.memory_total_mb - g.memory_used_mb
        return None
