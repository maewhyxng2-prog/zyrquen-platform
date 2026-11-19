
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class InferenceRequest:
    prompt: str
    request_id: str
    created_at: datetime


@dataclass
class InferenceResult:
    request_id: str
    output: str
    engine: str
    completed_at: datetime
    metadata: dict[str, Any]


class NativeModelBackend(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Run inference using a native ZYRQUEN model."""
        raise NotImplementedError


class NativeAIEngine:
    def __init__(self, backend: NativeModelBackend):
        self.backend = backend

    def infer(self, prompt: str) -> InferenceResult:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty")

        request = InferenceRequest(
            prompt=prompt.strip(),
            request_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
        )

        output = self.backend.generate(request.prompt)

        if not isinstance(output, str) or not output.strip():
            raise RuntimeError("Native model returned an invalid response")

        return InferenceResult(
            request_id=request.request_id,
            output=output,
            engine="zyrquen-native",
            completed_at=datetime.now(timezone.utc),
            metadata={
                "mode": "online",
                "backend": "native",
            },
        )
