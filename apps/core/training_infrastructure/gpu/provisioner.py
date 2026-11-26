from abc import ABC, abstractmethod
from dataclasses import dataclass

from .resource_manager import GpuInfo, ResourceManager


class ProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class Machine:
    provider: str
    gpus: tuple[GpuInfo, ...]
    status: str  # "ready" | "released"


class GpuProvider(ABC):
    """Interface for a compute provider. Cloud adapters (rent/release a GPU VM)
    must implement this; none is implemented yet - they need provider credentials."""

    @abstractmethod
    def provision(self) -> Machine: ...

    @abstractmethod
    def release(self, machine: Machine) -> Machine: ...


class LocalProvider(GpuProvider):
    """Uses GPUs already attached to the current machine (e.g. a Codespace/VM)."""

    def __init__(self, resources: ResourceManager | None = None, min_gpus: int = 1):
        self.resources = resources or ResourceManager()
        self.min_gpus = min_gpus

    def provision(self) -> Machine:
        gpus = self.resources.list_gpus()
        if len(gpus) < self.min_gpus:
            raise ProvisioningError(f"need {self.min_gpus} GPU(s), found {len(gpus)}")
        return Machine("local", tuple(gpus), "ready")

    def release(self, machine: Machine) -> Machine:
        return Machine(machine.provider, machine.gpus, "released")
