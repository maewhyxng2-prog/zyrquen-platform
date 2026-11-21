import asyncio
import codecs
from dataclasses import dataclass

from pydantic import BaseModel, Field

from apps.core.native.tokenizer import N_SPECIAL

from .context import InferenceContext
from .exceptions import InferenceError, ResourceLimitExceeded
from .model_loader import NativeModelLoader, native_generation_lock


class StreamChunk(BaseModel):
    text: str
    index: int = Field(ge=0)
    is_final: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int
    stopped_reason: str
    model_version: str | None = None


def _max_seq_len_for(loader: NativeModelLoader, model) -> int:
    cfg = getattr(model, "cfg", None) or getattr(loader, "model_config", None)
    max_seq_len = getattr(cfg, "max_seq_len", None)
    if not isinstance(max_seq_len, int) or max_seq_len <= 0:
        raise InferenceError("Native model configuration (max_seq_len) is unavailable.")
    return max_seq_len


def _encode_prompt(tokenizer, prompt: str) -> list[int]:
    if not hasattr(tokenizer, "encode"):
        raise InferenceError("Native tokenizer does not expose encode().")
    token_ids = tokenizer.encode(prompt, add_bos=False, add_eos=False)
    if not isinstance(token_ids, list) or not token_ids:
        raise InferenceError("Prompt produced zero native tokens.")
    return [int(tok) for tok in token_ids]


class _IncrementalTokenDecoder:
    def __init__(self, tokenizer):
        self._tokenizer = tokenizer
        self._has_byte_table = isinstance(getattr(tokenizer, "_bytes", None), dict)
        self._utf8 = codecs.getincrementaldecoder("utf-8")("replace")

    def decode_token(self, token_id: int) -> str:
        if self._has_byte_table:
            if token_id < N_SPECIAL:
                return ""
            raw = self._tokenizer._bytes.get(token_id)
            if raw is None:
                raise InferenceError(f"Unknown token id produced by model: {token_id}")
            return self._utf8.decode(raw, final=False)
        return self._tokenizer.decode([token_id], skip_special=True)

    def flush(self) -> str:
        if self._has_byte_table:
            return self._utf8.decode(b"", final=True)
        return ""


def _extract_next_logits(output):
    if isinstance(output, tuple):
        logits = output[0]
    elif hasattr(output, "logits"):
        logits = output.logits
    else:
        logits = output
    return logits[:, -1, :]


def _filter_logits(logits, temp: float, top_k: int, top_p: float | None):
    import torch

    out = logits.clone()
    if temp > 0:
        out = out / temp
    neg_inf = torch.tensor(float("-inf"), device=out.device, dtype=out.dtype)
    if top_k and top_k > 0:
        k = min(top_k, out.size(-1))
        vals, _ = torch.topk(out, k)
        cut = vals[:, -1]
        out = torch.where(out < cut.unsqueeze(-1), neg_inf, out)
    if top_p is not None and 0.0 < top_p < 1.0:
        sorted_logits, sorted_idx = torch.sort(out, descending=True, dim=-1)
        probs = torch.softmax(sorted_logits, dim=-1)
        cum = torch.cumsum(probs, dim=-1)
        mask = cum - probs > top_p
        sorted_logits = torch.where(mask, neg_inf, sorted_logits)
        out = torch.zeros_like(out)
        out.scatter_(-1, sorted_idx, sorted_logits)
    return out


def _sample_step(model, input_ids, max_seq_len: int, context: InferenceContext):
    import torch

    window = input_ids[:, -max_seq_len:]
    if window.size(1) > max_seq_len:
        raise ResourceLimitExceeded(
            f"Context window exceeded model max_seq_len ({max_seq_len})."
        )

    with native_generation_lock:
        with torch.inference_mode():
            logits = _extract_next_logits(model(window))

    if not torch.isfinite(logits).all():
        raise InferenceError("Native model produced non-finite logits.")

    filt = _filter_logits(
        logits,
        context.temperature,
        getattr(context, "top_k", 0),
        getattr(context, "top_p", 1.0),
    )
    if context.temperature <= 0:
        tok = torch.argmax(filt, dim=-1)
    else:
        probs = torch.softmax(filt, dim=-1)
        tok = torch.multinomial(probs, num_samples=1).squeeze(-1)
    return int(tok.item()), tok


class StreamingInferenceEngine:
    def __init__(self, loader: NativeModelLoader):
        self.loader = loader

    def _step(
        self,
        model,
        input_ids,
        context: InferenceContext,
        max_seq_len: int | None = None,
    ):
        limit = (
            max_seq_len
            if max_seq_len is not None
            else _max_seq_len_for(self.loader, model)
        )
        return _sample_step(model, input_ids, limit, context)

    async def stream(self, context: InferenceContext):
        if not self.loader.is_ready():
            raise InferenceError("Native model is not ready.")
        try:
            import torch

            tokenizer = self.loader.tokenizer
            model = self.loader.model
            max_seq_len = _max_seq_len_for(self.loader, model)
            prompt_ids = _encode_prompt(tokenizer, context.prompt)
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
            decoder = _IncrementalTokenDecoder(tokenizer)
            output_tokens = 0
            chunk_index = 0

            for _ in range(context.max_tokens):
                tok_id, tok_t = await asyncio.to_thread(
                    self._step,
                    model,
                    input_ids,
                    context,
                    max_seq_len,
                )
                if eos_id is not None and tok_id == eos_id:
                    break
                output_tokens += 1
                text = decoder.decode_token(tok_id)
                input_ids = torch.cat(
                    [input_ids, tok_t.reshape(1, 1).to(device)],
                    dim=1,
                )
                yield StreamChunk(
                    text=text,
                    index=chunk_index,
                    is_final=False,
                )
                chunk_index += 1

            trailing = decoder.flush()
            if trailing:
                yield StreamChunk(
                    text=trailing,
                    index=chunk_index,
                    is_final=False,
                )
                chunk_index += 1

            yield StreamChunk(
                text="",
                index=chunk_index,
                is_final=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except (ResourceLimitExceeded, InferenceError):
            raise
        except Exception as exc:
            raise InferenceError("Native streaming failed.") from exc

    async def collect(self, context: InferenceContext) -> str:
        parts = []
        async for chunk in self.stream(context):
            if not chunk.is_final:
                parts.append(chunk.text)
        return "".join(parts)
