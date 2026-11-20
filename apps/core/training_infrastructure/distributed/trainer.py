"""Distributed-training environment helpers. Single GPU is the default; multi-GPU is
used only when the launcher (e.g. torchrun) sets WORLD_SIZE > 1."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DistConfig:
    rank: int = 0
    world_size: int = 1
    local_rank: int = 0

    def __post_init__(self):
        if self.world_size < 1 or not (0 <= self.rank < self.world_size) or self.local_rank < 0:
            raise ValueError("invalid distributed configuration")

    @property
    def is_distributed(self) -> bool:
        return self.world_size > 1

    @property
    def is_main(self) -> bool:
        return self.rank == 0

    @classmethod
    def from_env(cls, env=None) -> "DistConfig":
        env = os.environ if env is None else env
        return cls(int(env.get("RANK", 0)), int(env.get("WORLD_SIZE", 1)), int(env.get("LOCAL_RANK", 0)))


def init_distributed(cfg: DistConfig, backend: str = "nccl") -> None:
    if not cfg.is_distributed:
        return
    import torch
    import torch.distributed as dist
    dist.init_process_group(backend=backend)
    if torch.cuda.is_available():
        torch.cuda.set_device(cfg.local_rank)


def shutdown_distributed(cfg: DistConfig) -> None:
    if cfg.is_distributed:
        import torch.distributed as dist
        dist.destroy_process_group()
