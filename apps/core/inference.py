
import asyncio
from threading import Lock

from .context import InferenceContext
from .exceptions import InferenceError, ResourceLimitExceeded
from .model_loader import NativeModelLoader


class NativeInferenceEngine:
    def __init__(
        self,
        loader: NativeModelLoader,
        max_concurrent_requests: int = 1,
    ):
        self.loader = loader
        self._generation_lock = Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

    def _generate_sync(self, context: InferenceContext) -> str:
        if not self.loader.is_ready():
            raise InferenceError("Native model is not ready.")

        try:
            import torch

            tokenizer = self.loader.tokenizer
            model = self.loader.model

            inputs = tokenizer(
                context.prompt,
                return_tensors="pt",
                truncation=False,
            )

            input_tokens = inputs["input_ids"].shape[1]

            if input_tokens > 2048:
                raise ResourceLimitExceeded(
                    "Input exceeds the 2048-token limit."
                )

            device = next(model.parameters()).device

            inputs = {
                key: value.to(device)
                for key, value in inputs.items()
            }

            generation_options = {
                "max_new_tokens": context.max_tokens,
                "do_sample": context.temperature > 0,
                "pad_token_id": (
                    tokenizer.pad_token_id
                    if tokenizer.pad_token_id is not None
                    else tokenizer.eos_token_id
                ),
            }

            if context.temperature > 0:
                generation_options["temperature"] = context.temperature

            with self._generation_lock:
                with torch.inference_mode():
                    outputs = model.generate(
                        **inputs,
                        **generation_options,
                    )

            generated_tokens = outputs[:, input_tokens:]

            result = tokenizer.decode(
                generated_tokens[0],
                skip_special_tokens=True,
            )

            if not result.strip():
                raise InferenceError("Native model returned an empty result.")

            return result

        except (ResourceLimitExceeded, InferenceError):
            raise
        except Exception as exc:
            raise InferenceError(
                "Native inference execution failed."
            ) from exc

    async def execute(
        self,
        context: InferenceContext,
        timeout_sec: float = 30.0,
    ) -> str:
        if not self.loader.is_ready():
            raise InferenceError("Native model is not ready.")

        try:
            async with asyncio.timeout(timeout_sec):
                async with self._semaphore:
                    return await asyncio.to_thread(
                        self._generate_sync,
                        context,
                    )

        except TimeoutError as exc:
            raise InferenceError(
                "Native inference timed out."
            ) from exc
        except (InferenceError, ResourceLimitExceeded):
            raise
        except Exception as exc:
            raise InferenceError(
                "Native inference execution failed."
            ) from exc
