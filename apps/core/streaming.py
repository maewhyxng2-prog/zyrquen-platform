import asyncio
from pydantic import BaseModel, Field

from .context import InferenceContext
from .exceptions import InferenceError
from .exceptions import ResourceLimitExceeded
from .model_loader import NativeModelLoader, native_generation_lock

class StreamChunk(BaseModel):
    text: str
    index: int = Field(ge=0)
    is_final: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

def _filter_logits(logits, temp, top_k, top_p):
    import torch

    out = logits.clone()
    if temp > 0:
        out = out / temp
    if top_k and top_k > 0:
        k = min(top_k, out.size(-1))
        vals, _ = torch.topk(out, k)
        cut = vals[:, -1]
        out = torch.where(
            out < cut.unsqueeze(-1),
            torch.tensor(float("-inf")),
            out,
        )
    if top_p is not None and 0.0 < top_p < 1.0:
        sorted_logits, sorted_idx = torch.sort(
            out,
            descending=True,
            dim=-1,
        )
        probs = torch.softmax(
            sorted_logits,
            dim=-1,
        )
        cum = torch.cumsum(probs, dim=-1)
        mask = cum - probs > top_p
        sorted_logits = torch.where(
            mask,
            torch.tensor(float("-inf")),
            sorted_logits,
        )
        out = torch.zeros_like(out)
        out.scatter_(
            -1,
            sorted_idx,
            sorted_logits,
        )
    return out

class StreamingInferenceEngine:
    def __init__(
        self,
        loader: NativeModelLoader,
    ):
        self.loader = loader

    def _step(
        self,
        model,
        input_ids,
        context: InferenceContext,
    ):
        import torch

        with native_generation_lock:
            with torch.inference_mode():
                logits = model(
                    input_ids,
                ).logits[:, -1, :]
        filt = _filter_logits(
            logits,
            context.temperature,
            getattr(context, "top_k", 0),
            getattr(context, "top_p", 1.0),
        )
        if context.temperature == 0:
            tok = torch.argmax(
                filt,
                dim=-1,
            )
        else:
            probs = torch.softmax(
                filt,
                dim=-1,
            )
            tok = torch.multinomial(
                probs,
                num_samples=1,
            ).squeeze(-1)
        return int(tok.item()), tok

    async def stream(
        self,
        context: InferenceContext,
    ):
        if not self.loader.is_ready():
            raise InferenceError(
                "Native model is not ready.",
            )
        try:
            import torch

            tokenizer = self.loader.tokenizer
            model = self.loader.model
            inputs = tokenizer(
                context.prompt,
                return_tensors="pt",
                truncation=False,
            )
            input_ids = inputs["input_ids"]
            if input_ids.shape[1] > 2048:
                raise ResourceLimitExceeded(
                    "Input exceeds the 2048-token limit.",
                )
            device = next(
                model.parameters(),
            ).device
            input_ids = input_ids.to(device)
            eos = tokenizer.eos_token_id
            input_tokens = int(input_ids.shape[1])
            output_tokens = 0
            for i in range(context.max_tokens):
                tok_id, tok_t = await asyncio.to_thread(
                    self._step,
                    model,
                    input_ids,
                    context,
                )
                if eos is not None and tok_id == eos:
                    break
                output_tokens += 1
                text = tokenizer.decode(
                    [tok_id],
                    skip_special_tokens=True,
                )
                input_ids = torch.cat(
                    [
                        input_ids,
                        tok_t.reshape(1, 1).to(device),
                    ],
                    dim=1,
                )
                yield StreamChunk(
                    text=text,
                    index=i,
                    is_final=False,
                )
            yield StreamChunk(
                text="",
                index=context.max_tokens,
                is_final=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except (ResourceLimitExceeded, InferenceError):
            raise
        except Exception as exc:
            raise InferenceError(
                "Native streaming failed.",
            ) from exc

    async def collect(
        self,
        context: InferenceContext,
    ) -> str:
        parts = []
        async for chunk in self.stream(context):
            if not chunk.is_final:
                parts.append(chunk.text)
        return "".join(parts)
