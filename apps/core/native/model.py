"""ZYRQUEN decoder-only Transformer, randomly initialised (no external weights)."""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import ZyrquenConfig


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        norm = x.float().pow(2).mean(-1, keepdim=True).add(self.eps).rsqrt()
        return (x.float() * norm).type_as(x) * self.weight


def _rope_cache(seq_len: int, head_dim: int, theta: float):
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2).float() / head_dim))
    angles = torch.outer(torch.arange(seq_len).float(), inv_freq)
    return angles.cos(), angles.sin()


def _apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    # x: (B, H, T, D); cos/sin: (T, D/2)
    x1, x2 = x[..., 0::2], x[..., 1::2]
    cos, sin = cos[None, None], sin[None, None]
    out = torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)
    return out.flatten(-2).type_as(x)


class CausalSelfAttention(nn.Module):
    def __init__(self, cfg: ZyrquenConfig):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.head_dim = cfg.d_model // cfg.n_heads
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model, bias=False)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)
        self.dropout = cfg.dropout

    def forward(self, x, cos, sin):
        b, t, c = x.shape
        q, k, v = self.qkv(x).view(b, t, 3, self.n_heads, self.head_dim).permute(2, 0, 3, 1, 4)
        q, k = _apply_rope(q, cos[:t], sin[:t]), _apply_rope(k, cos[:t], sin[:t])
        y = F.scaled_dot_product_attention(
            q, k, v, is_causal=True,
            dropout_p=self.dropout if self.training else 0.0,
        )
        return self.proj(y.transpose(1, 2).reshape(b, t, c))


class FeedForward(nn.Module):
    """SwiGLU feed-forward network."""

    def __init__(self, cfg: ZyrquenConfig):
        super().__init__()
        self.gate = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)
        self.up = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)
        self.down = nn.Linear(cfg.d_ff, cfg.d_model, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))


class Block(nn.Module):
    def __init__(self, cfg: ZyrquenConfig):
        super().__init__()
        self.attn_norm = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.attn = CausalSelfAttention(cfg)
        self.ffn_norm = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.ffn = FeedForward(cfg)

    def forward(self, x, cos, sin):
        x = x + self.attn(self.attn_norm(x), cos, sin)
        return x + self.ffn(self.ffn_norm(x))


class ZyrquenModel(nn.Module):
    def __init__(self, cfg: ZyrquenConfig):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.final_norm = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        if cfg.tie_embeddings:
            self.lm_head.weight = self.embed.weight

        cos, sin = _rope_cache(cfg.max_seq_len, cfg.d_model // cfg.n_heads, cfg.rope_theta)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)

        self.apply(self._init_weights)
        for name, p in self.named_parameters():  # scaled init for residual projections
            if name.endswith(("attn.proj.weight", "ffn.down.weight")):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers))

    @staticmethod
    def _init_weights(module: nn.Module) -> None:
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def forward(self, input_ids: torch.Tensor, targets: torch.Tensor | None = None):
        if input_ids.size(1) > self.cfg.max_seq_len:
            raise ValueError("sequence longer than max_seq_len")
        x = self.embed(input_ids)
        for block in self.blocks:
            x = block(x, self.rope_cos, self.rope_sin)
        logits = self.lm_head(self.final_norm(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-100)
        return logits, loss

    @torch.no_grad()
    def generate(self, input_ids: torch.Tensor, max_new_tokens: int,
                 temperature: float = 1.0, top_k: int | None = None) -> torch.Tensor:
        was_training = self.training
        self.eval()
        for _ in range(max_new_tokens):
            window = input_ids[:, -self.cfg.max_seq_len:]
            logits, _ = self(window)
            logits = logits[:, -1, :]
            if temperature <= 0:
                next_id = logits.argmax(-1, keepdim=True)
            else:
                logits = logits / temperature
                if top_k is not None:
                    kth = torch.topk(logits, min(top_k, logits.size(-1))).values[:, -1, None]
                    logits = logits.masked_fill(logits < kth, float("-inf"))
                next_id = torch.multinomial(F.softmax(logits, dim=-1), 1)
            input_ids = torch.cat((input_ids, next_id), dim=1)
        self.train(was_training)
        return input_ids
