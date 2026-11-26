from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    TORCH_AVAILABLE = True
except ModuleNotFoundError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False

from v2.zyrquen_v2_pure import PureNativeTransformerLMV2, PureZyrquenV2Config


@dataclass
class ZyrquenV2Config:
    vocab_size: int = 258  # 0..255 UTF-8 bytes + 256 PAD + 257 EOS
    pad_token_id: int = 256
    eos_token_id: int = 257
    d_model: int = 128
    n_heads: int = 4
    n_layers: int = 4
    d_ff: int = 384
    base_seq_len: int = 256
    max_seq_len: int = 1024
    rope_base: float = 10000.0
    dropout: float = 0.05

    def __post_init__(self) -> None:
        if self.d_model % self.n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        if (self.d_model // self.n_heads) % 2 != 0:
            raise ValueError("head_dim must be even for RoPE")
        if self.max_seq_len < self.base_seq_len:
            raise ValueError("max_seq_len must be >= base_seq_len")
        if self.vocab_size < 258:
            raise ValueError("vocab_size must be >= 258 (256 bytes + PAD + EOS)")


if TORCH_AVAILABLE:

    def precompute_rope_freqs(
        head_dim: int,
        max_seq_len: int,
        base_seq_len: int = 256,
        base: float = 10000.0,
        device: Optional[torch.device] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Compute RoPE cos/sin with NTK-aware scaling when max_seq_len > base_seq_len."""
        if max_seq_len > base_seq_len:
            scale_factor = max_seq_len / float(base_seq_len)
            effective_base = base * (
                scale_factor ** (head_dim / max(head_dim - 2, 2))
            )
        else:
            effective_base = base

        inv_freq = 1.0 / (
            effective_base
            ** (
                torch.arange(0, head_dim, 2, device=device, dtype=torch.float32)
                / head_dim
            )
        )
        positions = torch.arange(max_seq_len, device=device, dtype=torch.float32)
        freqs = torch.outer(positions, inv_freq)
        emb = torch.cat([freqs, freqs], dim=-1)
        return emb.cos(), emb.sin()

    def rotate_half(x: torch.Tensor) -> torch.Tensor:
        half = x.shape[-1] // 2
        x1, x2 = x[..., :half], x[..., half:]
        return torch.cat([-x2, x1], dim=-1)

    def apply_rope(
        q: torch.Tensor,
        k: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        seq_len = q.shape[-2]
        c = cos[:seq_len].unsqueeze(0).unsqueeze(0).to(dtype=q.dtype, device=q.device)
        s = sin[:seq_len].unsqueeze(0).unsqueeze(0).to(dtype=q.dtype, device=q.device)
        return (q * c) + (rotate_half(q) * s), (k * c) + (rotate_half(k) * s)

    class RoPESelfAttention(nn.Module):
        def __init__(self, cfg: ZyrquenV2Config) -> None:
            super().__init__()
            self.n_heads = cfg.n_heads
            self.head_dim = cfg.d_model // cfg.n_heads
            self.scale = 1.0 / math.sqrt(self.head_dim)

            self.qkv = nn.Linear(cfg.d_model, cfg.d_model * 3, bias=False)
            self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)
            self.attn_drop = nn.Dropout(cfg.dropout)
            self.proj_drop = nn.Dropout(cfg.dropout)

        def forward(
            self,
            x: torch.Tensor,
            cos: torch.Tensor,
            sin: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
        ) -> torch.Tensor:
            bsz, seq_len, d_model = x.shape
            qkv = self.qkv(x).view(bsz, seq_len, 3, self.n_heads, self.head_dim)
            q, k, v = qkv.unbind(dim=2)
            q = q.transpose(1, 2)
            k = k.transpose(1, 2)
            v = v.transpose(1, 2)

            q, k = apply_rope(q, k, cos, sin)

            attn_scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale
            causal_mask = torch.triu(
                torch.ones(seq_len, seq_len, device=x.device, dtype=torch.bool),
                diagonal=1,
            )
            attn_scores = attn_scores.masked_fill(
                causal_mask.unsqueeze(0).unsqueeze(0), float("-inf")
            )
            if attention_mask is not None:
                key_pad = (~attention_mask).unsqueeze(1).unsqueeze(2)
                attn_scores = attn_scores.masked_fill(key_pad, float("-inf"))

            attn_probs = F.softmax(attn_scores, dim=-1)
            attn_probs = self.attn_drop(attn_probs)

            out = (
                torch.matmul(attn_probs, v)
                .transpose(1, 2)
                .contiguous()
                .view(bsz, seq_len, d_model)
            )
            return self.proj_drop(self.proj(out))

    class SwiGLUFFN(nn.Module):
        def __init__(self, d_model: int, d_ff: int, dropout: float = 0.05) -> None:
            super().__init__()
            hidden = (d_ff * 2) // 3 if d_ff > 0 else d_model * 4
            hidden = max(hidden, d_model)
            self.w_gate = nn.Linear(d_model, hidden, bias=False)
            self.w_up = nn.Linear(d_model, hidden, bias=False)
            self.w_down = nn.Linear(hidden, d_model, bias=False)
            self.drop = nn.Dropout(dropout)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.drop(self.w_down(F.silu(self.w_gate(x)) * self.w_up(x)))

    class TransformerBlockV2(nn.Module):
        def __init__(self, cfg: ZyrquenV2Config) -> None:
            super().__init__()
            self.norm1 = nn.RMSNorm(cfg.d_model)
            self.attn = RoPESelfAttention(cfg)
            self.norm2 = nn.RMSNorm(cfg.d_model)
            self.ffn = SwiGLUFFN(cfg.d_model, cfg.d_ff, cfg.dropout)

        def forward(
            self,
            x: torch.Tensor,
            cos: torch.Tensor,
            sin: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
        ) -> torch.Tensor:
            x = x + self.attn(self.norm1(x), cos, sin, attention_mask=attention_mask)
            x = x + self.ffn(self.norm2(x))
            return x

    class NativeTransformerLMV2(nn.Module):
        """Random-initialized Native Transformer V2 with RoPE, explicit context extension, and padding mask."""

        def __init__(self, cfg: ZyrquenV2Config) -> None:
            super().__init__()
            self.cfg = cfg
            self.tok_emb = nn.Embedding(
                cfg.vocab_size, cfg.d_model, padding_idx=cfg.pad_token_id
            )
            self.drop = nn.Dropout(cfg.dropout)
            self.blocks = nn.ModuleList(
                [TransformerBlockV2(cfg) for _ in range(cfg.n_layers)]
            )
            self.norm_out = nn.RMSNorm(cfg.d_model)
            self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
            self.lm_head.weight = self.tok_emb.weight

            head_dim = cfg.d_model // cfg.n_heads
            cos, sin = precompute_rope_freqs(
                head_dim=head_dim,
                max_seq_len=cfg.max_seq_len,
                base_seq_len=cfg.base_seq_len,
                base=cfg.rope_base,
                device=self.tok_emb.weight.device,
            )
            self.register_buffer("rope_cos", cos, persistent=False)
            self.register_buffer("rope_sin", sin, persistent=False)

            self.apply(self._init_weights)
            for name, p in self.named_parameters():
                if name.endswith(("attn.proj.weight", "ffn.w_down.weight")):
                    nn.init.normal_(
                        p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers)
                    )

        @staticmethod
        def _init_weights(module: nn.Module) -> None:
            if isinstance(module, (nn.Linear, nn.Embedding)):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)

        def num_parameters(self) -> int:
            return sum(p.numel() for p in self.parameters())

        def extend_context(self, new_max_seq_len: int) -> None:
            if new_max_seq_len <= self.cfg.max_seq_len:
                return
            head_dim = self.cfg.d_model // self.cfg.n_heads
            cos, sin = precompute_rope_freqs(
                head_dim=head_dim,
                max_seq_len=new_max_seq_len,
                base_seq_len=self.cfg.base_seq_len,
                base=self.cfg.rope_base,
                device=self.tok_emb.weight.device,
            )
            self.cfg.max_seq_len = new_max_seq_len
            self.rope_cos = cos.to(device=self.tok_emb.weight.device)
            self.rope_sin = sin.to(device=self.tok_emb.weight.device)

        def forward(
            self,
            input_ids: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
        ) -> torch.Tensor:
            seq_len = input_ids.shape[1]
            if seq_len > self.cfg.max_seq_len:
                raise ValueError(
                    f"Sequence length {seq_len} exceeds max_seq_len={self.cfg.max_seq_len}. "
                    "Call extend_context() explicitly before training/evaluating longer sequences."
                )

            x = self.drop(self.tok_emb(input_ids))
            for block in self.blocks:
                x = block(
                    x, self.rope_cos, self.rope_sin, attention_mask=attention_mask
                )
            x = self.norm_out(x)
            return self.lm_head(x)

        @torch.no_grad()
        def generate(
            self,
            prompt_ids: torch.Tensor,
            max_new_tokens: int = 128,
            temperature: float = 0.0,
            stop_on_eos: bool = True,
        ) -> torch.Tensor:
            was_training = self.training
            self.eval()
            out = prompt_ids.clone()
            eos_id = self.cfg.eos_token_id
            for _ in range(max_new_tokens):
                window = out[:, -self.cfg.max_seq_len :]
                logits = self.forward(window)[:, -1, :]
                if temperature <= 1e-6:
                    next_tok = torch.argmax(logits, dim=-1, keepdim=True)
                else:
                    probs = F.softmax(logits / temperature, dim=-1)
                    next_tok = torch.multinomial(probs, num_samples=1)
                out = torch.cat([out, next_tok], dim=-1)
                if (
                    stop_on_eos
                    and out.shape[0] == 1
                    and int(next_tok.item()) == eos_id
                ):
                    break
            self.train(was_training)
            return out

else:

    class NativeTransformerLMV2:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                "PyTorch ('torch') is not installed. Use PureNativeTransformerLMV2 for stdlib execution."
            )


__all__ = [
    "TORCH_AVAILABLE",
    "ZyrquenV2Config",
    "NativeTransformerLMV2",
    "PureZyrquenV2Config",
    "PureNativeTransformerLMV2",
]
