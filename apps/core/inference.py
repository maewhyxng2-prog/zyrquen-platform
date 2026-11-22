import asyncio

from .context import InferenceContext
from .exceptions import InferenceError, ResourceLimitExceeded
from .model_loader import NativeModelLoader
from .streaming import (
    GenerationResult,
    _encode_prompt,
    _max_seq_len_for,
    _sample_step,
)


class NativeInferenceEngine:
    def __init__(
        self,
        loader: NativeModelLoader,
        max_concurrent_requests: int = 1,
    ):
        self.loader = loader
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

    def count_tokens(self, text: str) -> int:
        if not self.loader.is_ready() or self.loader.tokenizer is None:
            raise InferenceError("Native tokenizer is not ready.")
        prompt_format = getattr(self.loader, "prompt_format", None)
        return len(_encode_prompt(self.loader.tokenizer, text, prompt_format=prompt_format))

    def _generate_with_usage_sync(
        self,
        context: InferenceContext,
    ) -> GenerationResult:
        if not self.loader.is_ready():
            raise InferenceError("Native model is not ready.")
        try:
            import torch

            tokenizer = self.loader.tokenizer
            model = self.loader.model
            max_seq_len = _max_seq_len_for(self.loader, model)
            prompt_format = getattr(self.loader, "prompt_format", None)
            prompt_ids = _encode_prompt(tokenizer, context.prompt, prompt_format=prompt_format)
            input_tokens = len(prompt_ids)
            if input_tokens > max_seq_len:
                raise ResourceLimitExceeded(
                    f"Input exceeds the {max_seq_len}-token context window."
                )

            device = next(model.parameters()).device
            input_ids = torch.tensor(
                [prompt_ids],
                dtype=torch.long,
                device=device,
            )
            eos_id = getattr(tokenizer, "eos_id", None)
            generated_ids: list[int] = []
            stopped_reason = "max_tokens"

            for _ in range(context.max_tokens):
                tok_id, tok_t = _sample_step(model, input_ids, max_seq_len, context)
                if eos_id is not None and tok_id == eos_id:
                    stopped_reason = "eos"
                    break
                generated_ids.append(tok_id)
                input_ids = torch.cat(
                    [input_ids, tok_t.reshape(1, 1).to(device)],
                    dim=1,
                )

            result_text = tokenizer.decode(generated_ids, skip_special=True)
            if not result_text.strip():
                raise InferenceError("Native model returned an empty result.")

            return GenerationResult(
                text=result_text,
                input_tokens=input_tokens,
                output_tokens=len(generated_ids),
                stopped_reason=stopped_reason,
                model_version=getattr(self.loader, "model_version", None),
            )
        except (ResourceLimitExceeded, InferenceError):
            raise
        except Exception as exc:
            raise InferenceError("Native inference execution failed.") from exc

    def _generate_sync(self, context: InferenceContext) -> str:
        return self._generate_with_usage_sync(context).text

    async def generate_with_usage(
        self,
        context: InferenceContext,
        timeout_sec: float = 30.0,
    ) -> GenerationResult:
        if not self.loader.is_ready():
            raise InferenceError("Native model is not ready.")
        try:
            async with asyncio.timeout(timeout_sec):
                async with self._semaphore:
                    return await asyncio.to_thread(
                        self._generate_with_usage_sync,
                        context,
                    )
        except (ResourceLimitExceeded, InferenceError):
            raise
        except Exception as exc:
            raise InferenceError("Native inference execution failed.") from exc

    async def execute(
        self,
        context: InferenceContext,
        timeout_sec: float = 30.0,
    ) -> str:
        result = await self.generate_with_usage(context, timeout_sec=timeout_sec)
        return result.text
