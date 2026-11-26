#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — v9 Native Trainer & Readiness Runner (Steps 2 & 3)
===============================================================
Supports 4 controlled architecture arms on data/nagi_v9/ under CPU bounds
(params <= 5,000,000, seq <= 256, batch <= 4, steps <= 1,000):

  - arm_a : v7 Baseline (TinyNGI 2-layer LSTM, unified v9 interface)
  - arm_b : v8-Ablation (BiGRU + Bahdanau Attention, NO Pointer-Copy)
  - arm_c : v8 Baseline (BiGRU + Bahdanau Attention + Pointer-Copy)
  - arm_d : v9 Candidate (ZyrquenSlotReasoner: 4L Enc / 2L Dec Slot-Transformer
            with RoPE/RMSNorm/SwiGLU, Ephemeral Local Entity Slots <slot_0..31>,
            Slot Permutation Equivariance, and Dual-Gated Pointer-Generator)

Modes:
  --mode readiness : Data Gate + Vocab Leakage EL-05 + Param Cap + Grad Flow +
                     Overfit 4/4 mini-batch test + Save/Reload Round-Trip test.
  --mode train     : Full controlled training loop with stratified batching,
                     validation evaluation (val_unseen + val_ood), early stop /
                     divergence guard, and versioned checkpoint persistence.

Purely native PyTorch from-scratch implementation. No external/pretrained models.
Does NOT modify v7/v8 files, checkpoints, apps/web, apps/api, or apps/core.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import platform
import random
import resource
import sys
import time
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from audit_leakage_v9 import (  # noqa: E402
    classify_entity_format,
    extract_entities_from_text,
    run_audit,
    tokenize_structural_text,
)

MAX_CPU_MODEL_PARAMETERS = 5_000_000
MAX_CPU_SEQUENCE_LENGTH = 256
MAX_CPU_BATCH_SIZE = 4
MAX_CPU_TRAINING_STEPS = 1_000
MAX_EPHEMERAL_SLOTS = 32

SPECIAL_TOKENS = ("<pad>", "<unk>", "<bos>", "<eos>")
PAD_ID = 0
UNK_ID = 1
BOS_ID = 2
EOS_ID = 3
SLOT_TOKENS = tuple(f"<slot_{i}>" for i in range(MAX_EPHEMERAL_SLOTS))

ARM_DESCRIPTIONS = {
    "arm_a": "v7 Baseline (TinyNGI 2-Layer LSTM)",
    "arm_b": "v8-Ablation (BiGRU + Bahdanau Attention, No Pointer-Copy)",
    "arm_c": "v8 Baseline (BiGRU + Bahdanau Attention + Pointer-Copy)",
    "arm_d": "v9 Candidate (ZyrquenSlotReasoner: 4L Enc / 2L Dec Slot-Transformer + Pointer)",
}


def require_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F

        return torch, nn, F
    except ModuleNotFoundError as exc:
        print(
            f"ERROR: PyTorch ('torch') is not installed in this Python environment ({sys.executable}).\n"
            "Static checks can run here, while readiness/training execution must run in an environment "
            "with PyTorch CPU/CUDA installed (e.g. GitHub Codespaces).",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def set_seed(seed: int, torch_mod=None) -> None:
    random.seed(seed)
    if torch_mod is not None:
        torch_mod.manual_seed(seed)
        if torch_mod.cuda.is_available():
            torch_mod.cuda.manual_seed_all(seed)
        if hasattr(torch_mod, "backends") and hasattr(torch_mod.backends, "cudnn"):
            torch_mod.backends.cudnn.deterministic = True
            torch_mod.backends.cudnn.benchmark = False


def collect_runtime_environment(torch_mod=None, device=None) -> dict[str, Any]:
    cuda_ok = bool(torch_mod.cuda.is_available()) if torch_mod is not None else False
    gpu_name = None
    gpu_total_mem_mb = None
    if cuda_ok and torch_mod is not None:
        try:
            gpu_name = torch_mod.cuda.get_device_name(0)
            props = torch_mod.cuda.get_device_properties(0)
            gpu_total_mem_mb = round(props.total_memory / (1024 * 1024), 2)
        except Exception:
            pass
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "torch_version": getattr(torch_mod, "__version__", None) if torch_mod is not None else None,
        "device": str(device) if device is not None else None,
        "cuda_available": cuda_ok,
        "gpu_name": gpu_name,
        "gpu_total_mem_mb": gpu_total_mem_mb,
        "cudnn_deterministic": (
            bool(torch_mod.backends.cudnn.deterministic)
            if torch_mod is not None and hasattr(torch_mod, "backends") and hasattr(torch_mod.backends, "cudnn")
            else None
        ),
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def atomic_torch_save(torch_mod, state: dict[str, Any], path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch_mod.save(state, tmp)
    tmp.replace(path)


def build_vocab(train_rows: list[dict[str, Any]], use_slots: bool) -> list[str]:
    """
    Build strictly train-only static vocabulary (EL-05 == 0).
    For slot-based Arm D, entity tokens are replaced by <slot_0..31> and never
    stored in the static vocabulary at all; structural/operator tokens come
    only from train_rows.
    """
    vocab: list[str] = list(SPECIAL_TOKENS)
    seen = set(vocab)
    if use_slots:
        for st in SLOT_TOKENS:
            if st not in seen:
                vocab.append(st)
                seen.add(st)

    extra_tokens: set[str] = set()
    for row in train_rows:
        for field in ("input", "target"):
            for tok in tokenize_structural_text(str(row.get(field, ""))):
                if use_slots and classify_entity_format(tok) is not None:
                    continue
                if tok not in seen:
                    extra_tokens.add(tok)

    vocab.extend(sorted(extra_tokens))
    return vocab


def verify_vocab_no_eval_leakage(
    vocab: list[str], eval_rows: list[dict[str, Any]]
) -> tuple[bool, list[str]]:
    """Enforce EL-05: static vocab contains zero entities from val/test splits."""
    vocab_set = set(vocab)
    eval_entities: set[str] = set()
    for row in eval_rows:
        eval_entities.update(extract_entities_from_text(str(row.get("input", ""))))
        eval_entities.update(extract_entities_from_text(str(row.get("target", ""))))
    overlap = sorted(vocab_set & eval_entities)
    return len(overlap) == 0, overlap


class SlotBinding:
    """Ephemeral per-prompt entity <-> <slot_k> bidirectional map."""

    def __init__(self, surface_to_slot: dict[str, str], slot_to_surface: dict[str, str]):
        self.surface_to_slot = surface_to_slot
        self.slot_to_surface = slot_to_surface


def bind_prompt_slots(
    inp_toks: list[str],
    stoi: dict[str, int],
    *,
    permute_slots: bool = False,
    rng: random.Random | None = None,
) -> SlotBinding:
    """
    Map every entity (or OOV slot candidate) in `inp_toks` to an ephemeral local slot
    <slot_0> .. <slot_31>. Reoccurrences of the same entity in the same prompt
    always receive the exact same slot ID, preserving graph/relational structure
    without leaking unseen entities into the static vocabulary.
    """
    slot_pool = list(range(MAX_EPHEMERAL_SLOTS))
    if permute_slots:
        (rng or random).shuffle(slot_pool)

    surface_to_slot: dict[str, str] = {}
    slot_to_surface: dict[str, str] = {}
    cursor = 0
    for tok in inp_toks:
        if tok in surface_to_slot:
            continue
        is_ent = classify_entity_format(tok) is not None
        is_oov_candidate = (tok not in stoi) and (tok not in SPECIAL_TOKENS)
        if is_ent or is_oov_candidate:
            if cursor >= MAX_EPHEMERAL_SLOTS:
                continue
            slot_tok = f"<slot_{slot_pool[cursor]}>"
            cursor += 1
            surface_to_slot[tok] = slot_tok
            slot_to_surface[slot_tok] = tok
    return SlotBinding(surface_to_slot, slot_to_surface)


def encode_pair_standard(
    inp_text: str,
    tgt_text: str,
    stoi: dict[str, int],
    max_seq: int,
) -> tuple[list[int], list[int]] | None:
    src_toks = [stoi.get(t, UNK_ID) for t in tokenize_structural_text(inp_text)]
    trg_ids = [BOS_ID] + [stoi.get(t, UNK_ID) for t in tokenize_structural_text(tgt_text)] + [EOS_ID]
    if len(trg_ids) > max_seq:
        return None
    max_src_body = max(0, max_seq - 2)
    if len(src_toks) > max_src_body:
        src_toks = src_toks[:max_src_body]
    src_ids = [BOS_ID] + src_toks + [EOS_ID]
    return src_ids, trg_ids


def encode_pair_slotted(
    inp_text: str,
    tgt_text: str,
    stoi: dict[str, int],
    max_seq: int,
    *,
    permute_slots: bool = False,
    rng: random.Random | None = None,
) -> tuple[list[int], list[int], SlotBinding] | None:
    inp_toks = tokenize_structural_text(inp_text)
    tgt_toks = tokenize_structural_text(tgt_text)
    binding = bind_prompt_slots(inp_toks, stoi, permute_slots=permute_slots, rng=rng)

    def _map_tok(t: str) -> int:
        if t in binding.surface_to_slot:
            return stoi[binding.surface_to_slot[t]]
        return stoi.get(t, UNK_ID)

    src_tok_ids = [_map_tok(t) for t in inp_toks]
    trg_ids = [BOS_ID] + [_map_tok(t) for t in tgt_toks] + [EOS_ID]
    if len(trg_ids) > max_seq:
        return None
    max_src_body = max(0, max_seq - 2)
    if len(src_tok_ids) > max_src_body:
        src_tok_ids = src_tok_ids[:max_src_body]
    src_ids = [BOS_ID] + src_tok_ids + [EOS_ID]
    return src_ids, trg_ids, binding


def build_models_namespace(torch_mod, nn, F):
    """Define all 4 native model architectures cleanly inside a factory."""

    class TinyNGI(nn.Module):
        """Arm A: v7 Baseline (2-layer LSTM causal seq model)."""

        def __init__(self, vocab_size: int, pad_id: int = PAD_ID, dim: int = 128, dropout: float = 0.2):
            super().__init__()
            self.vocab_size = vocab_size
            self.pad_id = pad_id
            self.emb = nn.Embedding(vocab_size, dim, padding_idx=pad_id)
            self.lstm = nn.LSTM(dim, dim, num_layers=2, batch_first=True, dropout=dropout)
            self.head = nn.Linear(dim, vocab_size)

        def forward(self, x):
            h = self.emb(x)
            o, _ = self.lstm(h)
            return self.head(o)

        @torch_mod.no_grad()
        def generate(self, src, max_len: int = 48, bos_idx: int = BOS_ID, eos_idx: int = EOS_ID):
            # src is expected to be [bos] + src_toks (no trailing eos) for causal continuation
            out_seq, hc = self.lstm(self.emb(src))
            nxt = self.head(out_seq[:, -1, :]).argmax(dim=-1)
            preds = []
            finished = torch_mod.zeros(src.size(0), dtype=torch_mod.bool, device=src.device)
            for _ in range(max_len):
                preds.append(nxt)
                finished = finished | (nxt == eos_idx)
                if finished.all():
                    break
                cur_emb = self.emb(nxt.unsqueeze(1))
                out_step, hc = self.lstm(cur_emb, hc)
                nxt = self.head(out_step[:, -1, :]).argmax(dim=-1)
            return torch_mod.stack(preds, dim=1) if preds else torch_mod.empty((src.size(0), 0), dtype=torch_mod.long, device=src.device)

    class BiGRUEncoder(nn.Module):
        def __init__(self, vocab_size: int, emb_dim: int, hid_dim: int):
            super().__init__()
            self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=PAD_ID)
            self.rnn = nn.GRU(emb_dim, hid_dim, batch_first=True, bidirectional=True)
            self.fc = nn.Linear(hid_dim * 2, hid_dim)

        def forward(self, src):
            embedded = self.embedding(src)
            outputs, hidden = self.rnn(embedded)
            hidden = torch_mod.tanh(self.fc(torch_mod.cat((hidden[-2, :, :], hidden[-1, :, :]), dim=1)))
            return outputs, hidden

    class BahdanauAttention(nn.Module):
        def __init__(self, hid_dim: int):
            super().__init__()
            self.attn = nn.Linear(hid_dim * 3, hid_dim)
            self.v = nn.Linear(hid_dim, 1, bias=False)

        def forward(self, hidden, encoder_outputs, src_mask=None):
            src_len = encoder_outputs.shape[1]
            hidden_rep = hidden.unsqueeze(1).repeat(1, src_len, 1)
            energy = torch_mod.tanh(self.attn(torch_mod.cat((hidden_rep, encoder_outputs), dim=2)))
            attention = self.v(energy).squeeze(2)
            if src_mask is not None:
                attention = attention.masked_fill(~src_mask, -1e9)
            return torch_mod.softmax(attention, dim=1)

    class AttnOnlyDecoder(nn.Module):
        """Arm B: v8-Ablation decoder (Attention without Pointer-Copy)."""

        def __init__(self, vocab_size: int, emb_dim: int, hid_dim: int):
            super().__init__()
            self.vocab_size = vocab_size
            self.attention = BahdanauAttention(hid_dim)
            self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=PAD_ID)
            self.rnn = nn.GRU(hid_dim * 2 + emb_dim, hid_dim, batch_first=True)
            self.fc_out = nn.Linear(hid_dim * 3 + emb_dim, vocab_size)

        def forward(self, input_tok, hidden, encoder_outputs, src, src_mask=None):
            input_step = input_tok.unsqueeze(1)
            embedded = self.embedding(input_step)
            a = self.attention(hidden, encoder_outputs, src_mask=src_mask).unsqueeze(1)
            context = torch_mod.bmm(a, encoder_outputs)
            rnn_input = torch_mod.cat((embedded, context), dim=2)
            output, hidden_next = self.rnn(rnn_input, hidden.unsqueeze(0))
            output = output.squeeze(1)
            context = context.squeeze(1)
            embedded = embedded.squeeze(1)
            hidden_squeezed = hidden_next.squeeze(0)
            pred = self.fc_out(torch_mod.cat((output, context, embedded), dim=1))
            vocab_dist = torch_mod.softmax(pred, dim=1)
            return vocab_dist, hidden_squeezed, None

    class PointerDecoder(nn.Module):
        """Arm C: v8 Baseline decoder (Attention + Pointer-Copy)."""

        def __init__(self, vocab_size: int, emb_dim: int, hid_dim: int):
            super().__init__()
            self.vocab_size = vocab_size
            self.attention = BahdanauAttention(hid_dim)
            self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=PAD_ID)
            self.rnn = nn.GRU(hid_dim * 2 + emb_dim, hid_dim, batch_first=True)
            self.fc_out = nn.Linear(hid_dim * 3 + emb_dim, vocab_size)
            self.p_gen = nn.Linear(hid_dim * 3 + emb_dim, 1)

        def forward(self, input_tok, hidden, encoder_outputs, src, src_mask=None):
            input_step = input_tok.unsqueeze(1)
            embedded = self.embedding(input_step)
            a = self.attention(hidden, encoder_outputs, src_mask=src_mask).unsqueeze(1)
            context = torch_mod.bmm(a, encoder_outputs)
            rnn_input = torch_mod.cat((embedded, context), dim=2)
            output, hidden_next = self.rnn(rnn_input, hidden.unsqueeze(0))
            output = output.squeeze(1)
            context = context.squeeze(1)
            embedded = embedded.squeeze(1)
            hidden_squeezed = hidden_next.squeeze(0)
            pred = self.fc_out(torch_mod.cat((output, context, embedded), dim=1))
            vocab_dist = torch_mod.softmax(pred, dim=1)
            p_gen = torch_mod.sigmoid(
                self.p_gen(torch_mod.cat((context, hidden_squeezed, embedded), dim=1))
            )
            attn_dist = a.squeeze(1)
            copy_dist = torch_mod.zeros_like(vocab_dist).scatter_add(1, src, attn_dist)
            final_dist = p_gen * vocab_dist + (1.0 - p_gen) * copy_dist
            return final_dist, hidden_squeezed, p_gen

    class RNNSeq2Seq(nn.Module):
        """Unified wrapper for Arm B (AttnOnly) and Arm C (Pointer)."""

        def __init__(self, vocab_size: int, emb_dim: int = 128, hid_dim: int = 128, use_pointer: bool = True):
            super().__init__()
            self.vocab_size = vocab_size
            self.use_pointer = use_pointer
            self.encoder = BiGRUEncoder(vocab_size, emb_dim, hid_dim)
            self.decoder = (
                PointerDecoder(vocab_size, emb_dim, hid_dim)
                if use_pointer
                else AttnOnlyDecoder(vocab_size, emb_dim, hid_dim)
            )

        def forward(self, src, trg, teacher_forcing_ratio: float = 0.5):
            batch_size, trg_len = trg.shape
            src_mask = src != PAD_ID
            outputs = torch_mod.zeros(batch_size, trg_len, self.vocab_size, device=src.device)
            p_gens = []
            encoder_outputs, hidden = self.encoder(src)
            input_tok = trg[:, 0]
            for t in range(1, trg_len):
                dist, hidden, p_gen = self.decoder(
                    input_tok, hidden, encoder_outputs, src, src_mask=src_mask
                )
                outputs[:, t, :] = dist
                if p_gen is not None:
                    p_gens.append(p_gen)
                teacher_force = random.random() < teacher_forcing_ratio
                top1 = dist.argmax(1)
                input_tok = trg[:, t] if teacher_force else top1
            mean_pg = (
                torch_mod.cat(p_gens, dim=1) if p_gens else None
            )
            return outputs, mean_pg

    class RMSNorm(nn.Module):
        def __init__(self, dim: int, eps: float = 1e-6):
            super().__init__()
            self.eps = eps
            self.weight = nn.Parameter(torch_mod.ones(dim))

        def forward(self, x):
            norm = x.float().pow(2).mean(-1, keepdim=True).add(self.eps).rsqrt()
            return (x.float() * norm).type_as(x) * self.weight

    def _rope_cache(seq_len: int, head_dim: int, theta: float = 10000.0):
        inv_freq = 1.0 / (theta ** (torch_mod.arange(0, head_dim, 2).float() / head_dim))
        angles = torch_mod.outer(torch_mod.arange(seq_len).float(), inv_freq)
        return angles.cos(), angles.sin()

    def _apply_rope(x, cos, sin):
        x1, x2 = x[..., 0::2], x[..., 1::2]
        cos_v, sin_v = cos[None, None], sin[None, None]
        out = torch_mod.stack((x1 * cos_v - x2 * sin_v, x1 * sin_v + x2 * cos_v), dim=-1)
        return out.flatten(-2).type_as(x)

    class SwiGLU(nn.Module):
        def __init__(self, d_model: int, d_ff: int, dropout: float):
            super().__init__()
            self.gate = nn.Linear(d_model, d_ff, bias=False)
            self.up = nn.Linear(d_model, d_ff, bias=False)
            self.down = nn.Linear(d_ff, d_model, bias=False)
            self.drop = nn.Dropout(dropout)

        def forward(self, x):
            return self.drop(self.down(F.silu(self.gate(x)) * self.up(x)))

    class RoPESelfAttention(nn.Module):
        def __init__(self, d_model: int, n_heads: int, dropout: float, is_causal: bool):
            super().__init__()
            assert d_model % n_heads == 0
            self.n_heads = n_heads
            self.head_dim = d_model // n_heads
            self.is_causal = is_causal
            self.qkv = nn.Linear(d_model, 3 * d_model, bias=False)
            self.proj = nn.Linear(d_model, d_model, bias=False)
            self.drop = nn.Dropout(dropout)

        def forward(self, x, cos, sin, pad_mask=None):
            b, t, c = x.shape
            q, k, v = (
                self.qkv(x)
                .view(b, t, 3, self.n_heads, self.head_dim)
                .permute(2, 0, 3, 1, 4)
            )
            q = _apply_rope(q, cos[:t], sin[:t])
            k = _apply_rope(k, cos[:t], sin[:t])
            scores = torch_mod.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
            if self.is_causal:
                causal = torch_mod.triu(
                    torch_mod.ones((t, t), dtype=torch_mod.bool, device=x.device), diagonal=1
                )
                scores = scores.masked_fill(causal[None, None, :, :], -1e9)
            if pad_mask is not None:
                # pad_mask: (B, T), True where PAD
                scores = scores.masked_fill(pad_mask[:, None, None, :], -1e9)
            attn = torch_mod.softmax(scores, dim=-1)
            attn = self.drop(attn)
            y = torch_mod.matmul(attn, v).transpose(1, 2).reshape(b, t, c)
            return self.proj(y)

    class CrossAttention(nn.Module):
        def __init__(self, d_model: int, n_heads: int, dropout: float):
            super().__init__()
            assert d_model % n_heads == 0
            self.n_heads = n_heads
            self.head_dim = d_model // n_heads
            self.q_proj = nn.Linear(d_model, d_model, bias=False)
            self.kv_proj = nn.Linear(d_model, 2 * d_model, bias=False)
            self.out_proj = nn.Linear(d_model, d_model, bias=False)
            self.drop = nn.Dropout(dropout)

        def forward(self, x, mem, mem_pad_mask=None):
            b, t, c = x.shape
            s = mem.shape[1]
            q = self.q_proj(x).view(b, t, self.n_heads, self.head_dim).transpose(1, 2)
            k, v = (
                self.kv_proj(mem)
                .view(b, s, 2, self.n_heads, self.head_dim)
                .permute(2, 0, 3, 1, 4)
            )
            scores = torch_mod.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
            if mem_pad_mask is not None:
                scores = scores.masked_fill(mem_pad_mask[:, None, None, :], -1e9)
            attn = torch_mod.softmax(scores, dim=-1)
            attn = self.drop(attn)
            y = torch_mod.matmul(attn, v).transpose(1, 2).reshape(b, t, c)
            return self.out_proj(y)

    class EncoderBlock(nn.Module):
        def __init__(self, d_model: int, n_heads: int, d_ff: int, dropout: float):
            super().__init__()
            self.norm1 = RMSNorm(d_model)
            self.attn = RoPESelfAttention(d_model, n_heads, dropout, is_causal=False)
            self.norm2 = RMSNorm(d_model)
            self.ffn = SwiGLU(d_model, d_ff, dropout)

        def forward(self, x, cos, sin, src_pad_mask=None):
            x = x + self.attn(self.norm1(x), cos, sin, pad_mask=src_pad_mask)
            x = x + self.ffn(self.norm2(x))
            return x

    class DecoderBlock(nn.Module):
        def __init__(self, d_model: int, n_heads: int, d_ff: int, dropout: float):
            super().__init__()
            self.norm1 = RMSNorm(d_model)
            self.self_attn = RoPESelfAttention(d_model, n_heads, dropout, is_causal=True)
            self.norm2 = RMSNorm(d_model)
            self.cross_attn = CrossAttention(d_model, n_heads, dropout)
            self.norm3 = RMSNorm(d_model)
            self.ffn = SwiGLU(d_model, d_ff, dropout)

        def forward(self, x, mem, cos, sin, trg_pad_mask=None, src_pad_mask=None):
            x = x + self.self_attn(self.norm1(x), cos, sin, pad_mask=trg_pad_mask)
            x = x + self.cross_attn(self.norm2(x), mem, mem_pad_mask=src_pad_mask)
            x = x + self.ffn(self.norm3(x))
            return x

    class ZyrquenSlotReasoner(nn.Module):
        """
        Arm D: v9 Candidate Model
        - 4 Bidirectional RoPE Transformer Encoder Layers (Relational Message Passing)
        - 2 Causal RoPE Transformer Decoder Layers with Cross-Attention
        - Ephemeral Local Entity Slots (<slot_0..31>) masked in vocab_dist so entities
          are copied cleanly via Cross-Attention Copy Head, guaranteeing true
          slot-permutation equivariance and clean copy/reasoning gate discipline.
        """

        def __init__(
            self,
            vocab_size: int,
            d_model: int = 128,
            n_heads: int = 4,
            d_ff: int = 304,
            enc_layers: int = 4,
            dec_layers: int = 2,
            dropout: float = 0.1,
            max_seq_len: int = MAX_CPU_SEQUENCE_LENGTH,
            use_slots: bool = True,
        ):
            super().__init__()
            self.vocab_size = vocab_size
            self.d_model = d_model
            self.n_heads = n_heads
            self.d_ff = d_ff
            self.enc_layers_count = enc_layers
            self.dec_layers_count = dec_layers
            self.max_seq_len = max_seq_len
            self.use_slots = use_slots

            self.embed = nn.Embedding(vocab_size, d_model, padding_idx=PAD_ID)
            self.emb_drop = nn.Dropout(dropout)

            self.enc_blocks = nn.ModuleList(
                [EncoderBlock(d_model, n_heads, d_ff, dropout) for _ in range(enc_layers)]
            )
            self.enc_norm = RMSNorm(d_model)

            self.dec_blocks = nn.ModuleList(
                [DecoderBlock(d_model, n_heads, d_ff, dropout) for _ in range(dec_layers)]
            )
            self.dec_norm = RMSNorm(d_model)

            self.copy_q = nn.Linear(d_model, d_model, bias=False)
            self.copy_k = nn.Linear(d_model, d_model, bias=False)
            self.vocab_head = nn.Linear(d_model, vocab_size, bias=False)
            self.p_gen_proj = nn.Linear(d_model * 3, 1)

            cos, sin = _rope_cache(max_seq_len, d_model // n_heads)
            self.register_buffer("rope_cos", cos, persistent=False)
            self.register_buffer("rope_sin", sin, persistent=False)

            # Mask out <pad>, <bos>, and <slot_0..31> from vocab_head logits when slots active
            vocab_mask = torch_mod.zeros(vocab_size, dtype=torch_mod.bool)
            vocab_mask[PAD_ID] = True
            vocab_mask[BOS_ID] = True
            if use_slots and vocab_size >= 4 + MAX_EPHEMERAL_SLOTS:
                vocab_mask[4 : 4 + MAX_EPHEMERAL_SLOTS] = True
            self.register_buffer("vocab_forbidden_mask", vocab_mask, persistent=False)

            self.apply(self._init_weights)

        @staticmethod
        def _init_weights(module) -> None:
            if isinstance(module, (nn.Linear, nn.Embedding)):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
                if getattr(module, "bias", None) is not None:
                    nn.init.zeros_(module.bias)

        def encode(self, src):
            src_pad_mask = src == PAD_ID
            x = self.emb_drop(self.embed(src))
            for blk in self.enc_blocks:
                x = blk(x, self.rope_cos, self.rope_sin, src_pad_mask=src_pad_mask)
            return self.enc_norm(x), src_pad_mask

        def decode_step_distributions(self, trg_in, enc_out, src, src_pad_mask):
            trg_emb = self.emb_drop(self.embed(trg_in))
            trg_pad_mask = trg_in == PAD_ID
            x = trg_emb
            for blk in self.dec_blocks:
                x = blk(
                    x,
                    enc_out,
                    self.rope_cos,
                    self.rope_sin,
                    trg_pad_mask=trg_pad_mask,
                    src_pad_mask=src_pad_mask,
                )
            dec_out = self.dec_norm(x)

            # Copy attention over source encoder states (mask <pad> and <bos>)
            q_c = self.copy_q(dec_out)
            k_c = self.copy_k(enc_out)
            copy_scores = torch_mod.matmul(q_c, k_c.transpose(-2, -1)) / math.sqrt(self.d_model)
            copy_invalid_mask = (src == PAD_ID) | (src == BOS_ID)
            # Ensure at least one valid token if degenerate input
            if copy_invalid_mask.all(dim=1).any():
                copy_invalid_mask = src == PAD_ID
            copy_scores = copy_scores.masked_fill(copy_invalid_mask[:, None, :], -1e9)
            copy_attn = torch_mod.softmax(copy_scores, dim=-1)  # (B, T_trg, S)
            context = torch_mod.matmul(copy_attn, enc_out)  # (B, T_trg, D)

            vocab_logits = self.vocab_head(dec_out)
            vocab_logits = vocab_logits.masked_fill(self.vocab_forbidden_mask[None, None, :], -1e9)
            vocab_dist = torch_mod.softmax(vocab_logits, dim=-1)

            p_gen = torch_mod.sigmoid(
                self.p_gen_proj(torch_mod.cat((dec_out, context, trg_emb), dim=-1))
            )  # (B, T_trg, 1)

            copy_dist = torch_mod.zeros_like(vocab_dist)
            src_expanded = src.unsqueeze(1).expand(-1, trg_in.size(1), -1)
            copy_dist.scatter_add_(2, src_expanded, copy_attn)

            final_dist = p_gen * vocab_dist + (1.0 - p_gen) * copy_dist
            return final_dist, p_gen

        def forward(self, src, trg_in):
            enc_out, src_pad_mask = self.encode(src)
            return self.decode_step_distributions(trg_in, enc_out, src, src_pad_mask)

        @torch_mod.no_grad()
        def generate(self, src, max_len: int = 48):
            was_training = self.training
            self.eval()
            enc_out, src_pad_mask = self.encode(src)
            b = src.size(0)
            cur = torch_mod.full((b, 1), BOS_ID, dtype=torch_mod.long, device=src.device)
            finished = torch_mod.zeros(b, dtype=torch_mod.bool, device=src.device)
            p_gens: list[list[float]] = [[] for _ in range(b)]
            preds: list[list[int]] = [[] for _ in range(b)]
            eos_pos = [-1 for _ in range(b)]

            for step_i in range(max_len):
                final_dist, p_gen = self.decode_step_distributions(cur, enc_out, src, src_pad_mask)
                step_dist = final_dist[:, -1, :]
                step_pgen = p_gen[:, -1, 0]
                nxt = step_dist.argmax(dim=-1)
                for bi in range(b):
                    if finished[bi]:
                        continue
                    tok_id = int(nxt[bi].item())
                    p_gens[bi].append(float(step_pgen[bi].item()))
                    if tok_id == EOS_ID:
                        finished[bi] = True
                        eos_pos[bi] = step_i
                    else:
                        preds[bi].append(tok_id)
                cur = torch_mod.cat((cur, nxt.unsqueeze(1)), dim=1)
                if finished.all() or cur.size(1) >= self.max_seq_len:
                    break

            self.train(was_training)
            return preds, eos_pos, p_gens

    return {
        "TinyNGI": TinyNGI,
        "RNNSeq2Seq": RNNSeq2Seq,
        "ZyrquenSlotReasoner": ZyrquenSlotReasoner,
    }


def instantiate_arm_model(
    arm: str,
    vocab_size: int,
    arch_cfg: dict[str, Any],
    torch_mod,
    nn,
    F,
    device,
):
    models = build_models_namespace(torch_mod, nn, F)
    if arm == "arm_a":
        model = models["TinyNGI"](
            vocab_size=vocab_size,
            pad_id=PAD_ID,
            dim=arch_cfg.get("hid_dim", 128),
            dropout=arch_cfg.get("lstm_dropout", 0.2),
        )
    elif arm == "arm_b":
        model = models["RNNSeq2Seq"](
            vocab_size=vocab_size,
            emb_dim=arch_cfg.get("emb_dim", 128),
            hid_dim=arch_cfg.get("hid_dim", 128),
            use_pointer=False,
        )
    elif arm == "arm_c":
        model = models["RNNSeq2Seq"](
            vocab_size=vocab_size,
            emb_dim=arch_cfg.get("emb_dim", 128),
            hid_dim=arch_cfg.get("hid_dim", 128),
            use_pointer=True,
        )
    elif arm == "arm_d":
        model = models["ZyrquenSlotReasoner"](
            vocab_size=vocab_size,
            d_model=arch_cfg.get("d_model", 128),
            n_heads=arch_cfg.get("n_heads", 4),
            d_ff=arch_cfg.get("d_ff", 304),
            enc_layers=arch_cfg.get("enc_layers", 4),
            dec_layers=arch_cfg.get("dec_layers", 2),
            dropout=arch_cfg.get("dropout", 0.1),
            max_seq_len=arch_cfg.get("seq_len", MAX_CPU_SEQUENCE_LENGTH),
            use_slots=arch_cfg.get("use_slots", True),
        )
    else:
        raise ValueError(f"Unsupported arm: {arm}")
    return model.to(device)


def pad_seq2seq_batch(torch_mod, pairs: list[tuple[list[int], list[int]]], device):
    max_s = max(len(s) for s, _ in pairs)
    max_t = max(len(t) for _, t in pairs)
    src_b = [s + [PAD_ID] * (max_s - len(s)) for s, _ in pairs]
    trg_b = [t + [PAD_ID] * (max_t - len(t)) for _, t in pairs]
    return (
        torch_mod.tensor(src_b, dtype=torch_mod.long, device=device),
        torch_mod.tensor(trg_b, dtype=torch_mod.long, device=device),
    )


def pad_causal_batch(torch_mod, pairs: list[tuple[list[int], list[int]]], max_seq: int, device):
    """Arm A causal prefix + target packaging with shift fix."""
    encoded = []
    for src_ids, trg_ids in pairs:
        # src_ids is [BOS, ...src..., EOS]; trg_ids is [BOS, ...tgt..., EOS]
        prefix = src_ids[:-1]  # [BOS, ...src...]
        tgt_body = trg_ids[1:]  # [...tgt..., EOS]
        if len(prefix) + len(tgt_body) > max_seq:
            keep = max(1, max_seq - len(tgt_body))
            prefix = prefix[:keep]
        ids = prefix + tgt_body
        labels = [-100] * len(prefix) + tgt_body
        encoded.append((ids, labels))
    max_len = max(len(ids) for ids, _ in encoded)
    xs = [ids + [PAD_ID] * (max_len - len(ids)) for ids, _ in encoded]
    ys = [labels + [-100] * (max_len - len(labels)) for _, labels in encoded]
    xs_shift = [row[:-1] for row in xs]
    ys_shift = [row[1:] for row in ys]
    return (
        torch_mod.tensor(xs_shift, dtype=torch_mod.long, device=device),
        torch_mod.tensor(ys_shift, dtype=torch_mod.long, device=device),
    )


def compute_batch_loss(
    arm: str,
    model,
    batch_rows: list[dict[str, Any]],
    stoi: dict[str, int],
    max_seq: int,
    step_idx: int,
    total_steps: int,
    use_slots: bool,
    permute_slots: bool,
    rng: random.Random,
    torch_mod,
    F,
    device,
    aux_pgen_weight: float = 0.05,
):
    if arm == "arm_d" and use_slots:
        pairs = []
        for r in batch_rows:
            enc = encode_pair_slotted(
                r["input"], r["target"], stoi, max_seq, permute_slots=permute_slots, rng=rng
            )
            if enc is not None:
                pairs.append((enc[0], enc[1]))
    else:
        pairs = []
        for r in batch_rows:
            enc = encode_pair_standard(r["input"], r["target"], stoi, max_seq)
            if enc is not None:
                pairs.append(enc)

    if not pairs:
        return None

    if arm == "arm_a":
        x, y = pad_causal_batch(torch_mod, pairs, max_seq, device)
        logits = model(x)
        return F.cross_entropy(logits.reshape(-1, model.vocab_size), y.reshape(-1), ignore_index=-100)

    src, trg = pad_seq2seq_batch(torch_mod, pairs, device)
    tf_ratio = max(0.5, 1.0 - 0.5 * (step_idx / max(1, total_steps)))

    if arm in ("arm_b", "arm_c"):
        probs, _ = model(src, trg, teacher_forcing_ratio=tf_ratio)
        log_probs = torch_mod.log(probs[:, 1:, :].clamp(min=1e-12))
        return F.nll_loss(log_probs.reshape(-1, model.vocab_size), trg[:, 1:].reshape(-1), ignore_index=PAD_ID)

    # arm_d: ZyrquenSlotReasoner with optional scheduled sampling + auxiliary p_gen discipline
    trg_in = trg[:, :-1]
    trg_out = trg[:, 1:]

    if model.training and total_steps > 0 and step_idx > int(0.3 * total_steps) and trg_in.size(1) > 1:
        sched_p = 0.35 * ((step_idx - 0.3 * total_steps) / max(1, 0.7 * total_steps))
        if rng.random() < sched_p:
            with torch_mod.no_grad():
                pred_dist, _ = model(src, trg_in)
                pred_toks = pred_dist.argmax(dim=-1)
            mix_mask = torch_mod.rand_like(trg_in.float()) < (sched_p * 0.5)
            mix_mask[:, 0] = False  # never corrupt <bos>
            mix_mask = mix_mask & (trg_in != PAD_ID)
            trg_in = torch_mod.where(mix_mask, pred_toks, trg_in)

    final_dist, p_gen = model(src, trg_in)
    log_probs = torch_mod.log(final_dist.clamp(min=1e-12))
    nll = F.nll_loss(log_probs.reshape(-1, model.vocab_size), trg_out.reshape(-1), ignore_index=PAD_ID)

    if aux_pgen_weight > 0.0 and use_slots:
        valid_mask = trg_out != PAD_ID
        if valid_mask.any():
            is_slot_tok = (trg_out >= 4) & (trg_out < 4 + MAX_EPHEMERAL_SLOTS)
            pgen_targets = 1.0 - is_slot_tok.float()
            p_clamped = p_gen.squeeze(-1).clamp(1e-6, 1.0 - 1e-6)
            bce = -(
                pgen_targets * torch_mod.log(p_clamped)
                + (1.0 - pgen_targets) * torch_mod.log(1.0 - p_clamped)
            )
            aux = (bce * valid_mask.float()).sum() / valid_mask.float().sum().clamp(min=1.0)
            return nll + aux_pgen_weight * aux
    return nll


def free_generate_row(
    arm: str,
    model,
    inp_text: str,
    vocab: list[str],
    stoi: dict[str, int],
    itos: dict[int, str],
    max_seq: int,
    max_gen_len: int,
    use_slots: bool,
    torch_mod,
    device,
) -> tuple[list[str], int, float | None]:
    """
    Shared deterministic autoregressive Free-Generation decoding for readiness & validation.
    Returns (predicted_tokens, eos_position_or_minus1, mean_p_gen_or_None).
    """
    inp_toks = tokenize_structural_text(inp_text)
    model.eval()

    if arm == "arm_a":
        prefix = [BOS_ID] + [stoi.get(t, UNK_ID) for t in inp_toks]
        if len(prefix) > max_seq - 2:
            prefix = prefix[: max_seq - 2]
        src_t = torch_mod.tensor([prefix], dtype=torch_mod.long, device=device)
        pred_t = model.generate(src_t, max_len=max_gen_len, bos_idx=BOS_ID, eos_idx=EOS_ID)
        pred_ids = pred_t[0].tolist()
        eos_pos = pred_ids.index(EOS_ID) if EOS_ID in pred_ids else -1
        body = pred_ids[:eos_pos] if eos_pos >= 0 else pred_ids
        return [itos.get(i, "<unk>") for i in body], eos_pos, None

    if arm in ("arm_b", "arm_c"):
        max_src_body = max(0, max_seq - 2)
        trimmed_toks = inp_toks[:max_src_body]
        model_src_ids = [BOS_ID] + [stoi.get(t, UNK_ID) for t in trimmed_toks] + [EOS_ID]
        src_t = torch_mod.tensor([model_src_ids], dtype=torch_mod.long, device=device)
        src_mask = src_t != PAD_ID

        local_stoi = dict(stoi)
        local_itos = dict(itos)
        next_idx = len(vocab)
        dyn_src_ids = [BOS_ID]
        if arm == "arm_c":
            for t in trimmed_toks:
                if t not in local_stoi:
                    local_stoi[t] = next_idx
                    local_itos[next_idx] = t
                    next_idx += 1
                dyn_src_ids.append(local_stoi[t])
        else:
            dyn_src_ids.extend(stoi.get(t, UNK_ID) for t in trimmed_toks)
        dyn_src_ids.append(EOS_ID)

        outs: list[int] = []
        eos_pos = -1
        p_gens: list[float] = []

        with torch_mod.no_grad():
            encoder_outputs, hidden = model.encoder(src_t)
            cur_tok = torch_mod.tensor([BOS_ID], dtype=torch_mod.long, device=device)
            for step_i in range(max_gen_len):
                if arm == "arm_b":
                    vocab_dist, hidden, _ = model.decoder(
                        cur_tok, hidden, encoder_outputs, src_t, src_mask=src_mask
                    )
                    nxt = int(vocab_dist.squeeze(0).argmax().item())
                else:
                    # Explicit pointer-copy extension with dynamic local vocab (v8 faithful)
                    input_step = cur_tok.unsqueeze(1)
                    embedded = model.decoder.embedding(input_step)
                    a = model.decoder.attention(hidden, encoder_outputs, src_mask=src_mask).unsqueeze(1)
                    context = torch_mod.bmm(a, encoder_outputs)
                    rnn_input = torch_mod.cat((embedded, context), dim=2)
                    output, hidden_next = model.decoder.rnn(rnn_input, hidden.unsqueeze(0))
                    output = output.squeeze(1)
                    context = context.squeeze(1)
                    embedded = embedded.squeeze(1)
                    hidden = hidden_next.squeeze(0)
                    pred = model.decoder.fc_out(torch_mod.cat((output, context, embedded), dim=1))
                    vocab_dist = torch_mod.softmax(pred, dim=1).squeeze(0)
                    p_gen_val = float(
                        torch_mod.sigmoid(
                            model.decoder.p_gen(torch_mod.cat((context, hidden, embedded), dim=1))
                        ).item()
                    )
                    p_gens.append(p_gen_val)
                    attn_w = a.squeeze(0).squeeze(0)
                    ext_dist = torch_mod.zeros(next_idx, device=device)
                    ext_dist[: len(vocab)] = p_gen_val * vocab_dist
                    for pos, dyn_id in enumerate(dyn_src_ids):
                        ext_dist[dyn_id] += (1.0 - p_gen_val) * attn_w[pos]
                    nxt = int(ext_dist.argmax().item())

                if nxt == EOS_ID:
                    eos_pos = step_i
                    break
                outs.append(nxt)
                mapped_id = stoi.get(local_itos.get(nxt, "<unk>"), UNK_ID)
                cur_tok = torch_mod.tensor([mapped_id], dtype=torch_mod.long, device=device)

        pred_toks = [local_itos.get(i, "<unk>") for i in outs]
        mean_pg = (sum(p_gens) / len(p_gens)) if p_gens else None
        return pred_toks, eos_pos, mean_pg

    # arm_d: ZyrquenSlotReasoner
    if use_slots:
        binding = bind_prompt_slots(inp_toks, stoi, permute_slots=False)
        src_body = [
            stoi[binding.surface_to_slot[t]] if t in binding.surface_to_slot else stoi.get(t, UNK_ID)
            for t in inp_toks
        ]
    else:
        binding = SlotBinding({}, {})
        src_body = [stoi.get(t, UNK_ID) for t in inp_toks]

    max_src_body = max(0, max_seq - 2)
    src_ids = [BOS_ID] + src_body[:max_src_body] + [EOS_ID]
    src_t = torch_mod.tensor([src_ids], dtype=torch_mod.long, device=device)
    preds, eos_list, pgen_list = model.generate(src_t, max_len=max_gen_len)
    pred_toks = []
    for tid in preds[0]:
        tok_str = itos.get(tid, "<unk>")
        if use_slots and tok_str in binding.slot_to_surface:
            tok_str = binding.slot_to_surface[tok_str]
        pred_toks.append(tok_str)
    p_vals = pgen_list[0]
    mean_pg = (sum(p_vals) / len(p_vals)) if p_vals else None
    return pred_toks, eos_list[0], mean_pg


def select_stratified_readiness_samples(train_rows: list[dict[str, Any]], k: int = 4) -> list[dict[str, Any]]:
    """Pick 4 diverse examples covering both entity-copy and reasoning/verdict capabilities."""
    preferred_caps = [
        "native_representation",
        "relational_reasoning",
        "planning_decomposition",
        "adaptive_learning",
    ]
    picked: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for cap in preferred_caps:
        for row in train_rows:
            if row.get("capability") == cap and row.get("id") not in used_ids:
                picked.append(row)
                used_ids.add(str(row.get("id")))
                break
    for row in train_rows:
        if len(picked) >= k:
            break
        if row.get("id") not in used_ids:
            picked.append(row)
            used_ids.add(str(row.get("id")))
    return picked[:k]


def evaluate_val_split(
    arm: str,
    model,
    val_rows: list[dict[str, Any]],
    vocab: list[str],
    stoi: dict[str, int],
    itos: dict[int, str],
    max_seq: int,
    use_slots: bool,
    torch_mod,
    F,
    device,
    fg_sample_limit: int = 60,
) -> dict[str, float]:
    model.eval()
    losses: list[float] = []
    rng_eval = random.Random(0)
    with torch_mod.no_grad():
        for i in range(0, len(val_rows), MAX_CPU_BATCH_SIZE):
            batch = val_rows[i : i + MAX_CPU_BATCH_SIZE]
            loss = compute_batch_loss(
                arm=arm,
                model=model,
                batch_rows=batch,
                stoi=stoi,
                max_seq=max_seq,
                step_idx=1,
                total_steps=1,
                use_slots=use_slots,
                permute_slots=False,
                rng=rng_eval,
                torch_mod=torch_mod,
                F=F,
                device=device,
                aux_pgen_weight=0.05,
            )
            if loss is not None:
                losses.append(float(loss.item()))

    fg_subset = val_rows[: min(fg_sample_limit, len(val_rows))]
    exact_hits = 0
    for row in fg_subset:
        pred_toks, _, _ = free_generate_row(
            arm=arm,
            model=model,
            inp_text=row["input"],
            vocab=vocab,
            stoi=stoi,
            itos=itos,
            max_seq=max_seq,
            max_gen_len=48,
            use_slots=use_slots,
            torch_mod=torch_mod,
            device=device,
        )
        if pred_toks == tokenize_structural_text(row["target"]):
            exact_hits += 1

    model.train()
    return {
        "val_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "val_fg_exact_sample": exact_hits / max(1, len(fg_subset)),
        "val_fg_sample_n": len(fg_subset),
    }


def make_stratified_batches(
    rows: list[dict[str, Any]], batch_size: int, total_steps: int, seed: int
) -> list[list[dict[str, Any]]]:
    rng = random.Random(seed)
    pool = list(rows)
    batches: list[list[dict[str, Any]]] = []
    cursor = len(pool)
    for _ in range(total_steps):
        batch: list[dict[str, Any]] = []
        while len(batch) < batch_size:
            if cursor >= len(pool):
                rng.shuffle(pool)
                cursor = 0
            batch.append(pool[cursor])
            cursor += 1
        batches.append(batch)
    return batches


def run_readiness(args, data_dir: Path, out_dir: Path, audit_report: dict[str, Any]) -> int:
    torch_mod, nn, F = require_torch()
    set_seed(args.seed, torch_mod)
    t0 = time.time()
    device = torch_mod.device("cuda" if torch_mod.cuda.is_available() else "cpu")

    train_rows = load_jsonl(data_dir / "train.jsonl")
    eval_rows = (
        load_jsonl(data_dir / "val_unseen.jsonl")
        + load_jsonl(data_dir / "val_ood.jsonl")
        + load_jsonl(data_dir / "test_unseen.jsonl")
        + load_jsonl(data_dir / "test_ood.jsonl")
    )

    use_slots = (args.arm == "arm_d") and (not args.no_slots)
    vocab = build_vocab(train_rows, use_slots=use_slots)
    stoi = {tok: idx for idx, tok in enumerate(vocab)}
    itos = {idx: tok for tok, idx in stoi.items()}

    el05_ok, el05_overlap = verify_vocab_no_eval_leakage(vocab, eval_rows)
    arch_cfg = {
        "emb_dim": 128,
        "hid_dim": 128,
        "lstm_dropout": 0.0,  # deterministic readiness memorization
        "d_model": args.d_model,
        "n_heads": args.n_heads,
        "d_ff": args.d_ff,
        "enc_layers": args.enc_layers,
        "dec_layers": args.dec_layers,
        "dropout": 0.0,
        "seq_len": args.seq,
        "use_slots": use_slots,
    }
    model = instantiate_arm_model(args.arm, len(vocab), arch_cfg, torch_mod, nn, F, device)
    total_params = sum(p.numel() for p in model.parameters())
    params_cap_ok = total_params <= MAX_CPU_MODEL_PARAMETERS

    mini_rows = select_stratified_readiness_samples(train_rows, k=4)
    init_snapshot = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    lr = args.lr if args.lr is not None else (0.002 if args.arm == "arm_d" else 0.0025)
    optimizer = torch_mod.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
    rng = random.Random(args.seed)

    initial_loss = None
    final_loss = None
    grad_flow_ok = False
    grad_nan_count = 0
    loss_nan_abort = False

    steps = args.steps if args.steps is not None else 250
    for step in range(1, steps + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = compute_batch_loss(
            arm=args.arm,
            model=model,
            batch_rows=mini_rows,
            stoi=stoi,
            max_seq=args.seq,
            step_idx=step,
            total_steps=steps,
            use_slots=use_slots,
            permute_slots=False,
            rng=rng,
            torch_mod=torch_mod,
            F=F,
            device=device,
            aux_pgen_weight=0.05,
        )
        if loss is None or not math.isfinite(float(loss.item())):
            loss_nan_abort = True
            break

        loss_val = float(loss.item())
        if initial_loss is None:
            initial_loss = loss_val
        final_loss = loss_val

        loss.backward()
        if step == 1:
            nonzero_grads = 0
            for p in model.parameters():
                if p.grad is not None:
                    if not torch_mod.isfinite(p.grad).all():
                        grad_nan_count += 1
                    elif float(p.grad.abs().sum().item()) > 0.0:
                        nonzero_grads += 1
            grad_flow_ok = nonzero_grads > 0 and grad_nan_count == 0

        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        if step % 50 == 0 or step == steps:
            print(f"[readiness:{args.arm}] step {step}/{steps} | loss={loss_val:.4f}")
            if step >= 100 and loss_val < 0.015:
                # Verify if already memorized 4/4 before finishing early
                hits = 0
                for r in mini_rows:
                    ptoks, _, _ = free_generate_row(
                        args.arm, model, r["input"], vocab, stoi, itos, args.seq, 48, use_slots, torch_mod, device
                    )
                    if ptoks == tokenize_structural_text(r["target"]):
                        hits += 1
                if hits == len(mini_rows):
                    print(f"[readiness:{args.arm}] early converged 4/4 at step {step}")
                    break

    params_updated = any(
        not torch_mod.equal(init_snapshot[k], v.detach().cpu())
        for k, v in model.state_dict().items()
        if k in init_snapshot
    )

    sample_results = []
    exact_ok = 0
    for r in mini_rows:
        pred_toks, eos_pos, mean_pg = free_generate_row(
            args.arm, model, r["input"], vocab, stoi, itos, args.seq, 48, use_slots, torch_mod, device
        )
        exp_toks = tokenize_structural_text(r["target"])
        is_exact = pred_toks == exp_toks
        if is_exact:
            exact_ok += 1
        sample_results.append(
            {
                "id": r.get("id"),
                "capability": r.get("capability"),
                "input": r["input"],
                "expected": r["target"],
                "predicted": " ".join(pred_toks),
                "exact_match": is_exact,
                "eos_pos": eos_pos,
                "mean_p_gen": round(mean_pg, 4) if mean_pg is not None else None,
            }
        )

    # Checkpoint save -> reload -> inference equivalence round-trip check
    out_dir.mkdir(parents=True, exist_ok=True)
    rt_ckpt_path = out_dir / "readiness_roundtrip.pt"
    ckpt_payload = {
        "format": "zyrquen_v9_ckpt_v1",
        "arm": args.arm,
        "mode": "readiness",
        "arch_cfg": arch_cfg,
        "vocab": vocab,
        "use_slots": use_slots,
        "model_state": model.state_dict(),
        "params": total_params,
    }
    atomic_torch_save(torch_mod, ckpt_payload, rt_ckpt_path)
    loaded_ckpt = torch_mod.load(rt_ckpt_path, map_location=device, weights_only=False)
    reloaded_model = instantiate_arm_model(
        loaded_ckpt["arm"],
        len(loaded_ckpt["vocab"]),
        loaded_ckpt["arch_cfg"],
        torch_mod,
        nn,
        F,
        device,
    )
    reloaded_model.load_state_dict(loaded_ckpt["model_state"])
    reloaded_model.eval()

    roundtrip_match = True
    for r, orig in zip(mini_rows, sample_results):
        p2, e2, _ = free_generate_row(
            args.arm, reloaded_model, r["input"], vocab, stoi, itos, args.seq, 48, use_slots, torch_mod, device
        )
        if " ".join(p2) != orig["predicted"] or e2 != orig["eos_pos"]:
            roundtrip_match = False
            break

    loss_decreased = (
        initial_loss is not None and final_loss is not None and final_loss < initial_loss
    )
    checks = {
        "data_leakage_gate": audit_report.get("overall_status") == "PASS",
        "el05_vocab_leakage_zero": el05_ok,
        "param_cap_under_5m": params_cap_ok,
        "seq_cap_under_256": args.seq <= MAX_CPU_SEQUENCE_LENGTH,
        "finite_loss": (not loss_nan_abort) and initial_loss is not None,
        "grad_flow": grad_flow_ok,
        "loss_decreased": loss_decreased,
        "parameters_updated": params_updated,
        "overfit_4_of_4": exact_ok == len(mini_rows),
        "checkpoint_roundtrip_match": roundtrip_match,
    }
    all_pass = all(checks.values())
    status = "PASS" if all_pass else "FAIL"

    report = {
        "mode": "readiness",
        "arm": args.arm,
        "description": ARM_DESCRIPTIONS[args.arm],
        "status": status,
        "verification_level": "RUNTIME_PASS" if all_pass else "RUNTIME_FAIL",
        "params": total_params,
        "vocab_size": len(vocab),
        "use_slots": use_slots,
        "el05_overlap_sample": el05_overlap[:10],
        "initial_loss": initial_loss,
        "final_loss": final_loss,
        "overfit_exact": f"{exact_ok}/{len(mini_rows)}",
        "checks": checks,
        "samples": sample_results,
        "environment": collect_runtime_environment(torch_mod, device),
        "elapsed_sec": round(time.time() - t0, 2),
        "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    report_path = out_dir / "readiness_report.json"
    atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print(
        f"READINESS [{status}] arm={args.arm} | params={total_params} | "
        f"loss {initial_loss} -> {final_loss} | overfit={exact_ok}/{len(mini_rows)} | "
        f"roundtrip={roundtrip_match}"
    )
    print(f"Report written to {report_path}")
    return 0 if all_pass else 1


def run_train(args, data_dir: Path, out_dir: Path, audit_report: dict[str, Any]) -> int:
    torch_mod, nn, F = require_torch()
    set_seed(args.seed, torch_mod)
    t0 = time.time()
    device = torch_mod.device("cuda" if torch_mod.cuda.is_available() else "cpu")

    if args.batch_size > MAX_CPU_BATCH_SIZE and not args.allow_exceed_cap:
        print(f"BLOCKED: batch_size={args.batch_size} exceeds MAX_CPU_BATCH_SIZE={MAX_CPU_BATCH_SIZE}")
        return 1
    if args.seq > MAX_CPU_SEQUENCE_LENGTH and not args.allow_exceed_cap:
        print(f"BLOCKED: seq={args.seq} exceeds MAX_CPU_SEQUENCE_LENGTH={MAX_CPU_SEQUENCE_LENGTH}")
        return 1

    total_steps = args.steps if args.steps is not None else 960
    if total_steps > MAX_CPU_TRAINING_STEPS and not args.allow_exceed_cap:
        print(f"BLOCKED: steps={total_steps} exceeds MAX_CPU_TRAINING_STEPS={MAX_CPU_TRAINING_STEPS}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    best_path = out_dir / "best.pt"
    last_path = out_dir / "last.pt"
    if best_path.exists() and not args.resume and not args.overwrite:
        print(
            f"BLOCKED: {best_path} already exists. Checkpoints are protected against accidental overwrite.\n"
            "Pass --resume <ckpt> to continue training, choose a new --out directory, or pass --overwrite."
        )
        return 1

    train_rows = load_jsonl(data_dir / "train.jsonl")
    val_unseen = load_jsonl(data_dir / "val_unseen.jsonl")
    val_ood = load_jsonl(data_dir / "val_ood.jsonl")
    val_rows = val_unseen + val_ood
    test_rows = load_jsonl(data_dir / "test_unseen.jsonl") + load_jsonl(data_dir / "test_ood.jsonl")

    if not train_rows or not val_rows:
        print(
            f"BLOCKED: invalid/empty dataset splits (train={len(train_rows)}, val={len(val_rows)}) in {data_dir}",
            file=sys.stderr,
        )
        return 1

    env_meta = collect_runtime_environment(torch_mod, device)

    use_slots = (args.arm == "arm_d") and (not args.no_slots)
    vocab = build_vocab(train_rows, use_slots=use_slots)
    el05_ok, el05_overlap = verify_vocab_no_eval_leakage(vocab, val_rows + test_rows)
    if not el05_ok:
        print(f"BLOCKED EL-05 violation: eval entity tokens found in vocab: {el05_overlap[:10]}")
        return 1

    stoi = {tok: idx for idx, tok in enumerate(vocab)}
    itos = {idx: tok for tok, idx in stoi.items()}

    arch_cfg = {
        "emb_dim": 128,
        "hid_dim": 128,
        "lstm_dropout": 0.2,
        "d_model": args.d_model,
        "n_heads": args.n_heads,
        "d_ff": args.d_ff,
        "enc_layers": args.enc_layers,
        "dec_layers": args.dec_layers,
        "dropout": args.dropout,
        "seq_len": args.seq,
        "use_slots": use_slots,
    }
    model = instantiate_arm_model(args.arm, len(vocab), arch_cfg, torch_mod, nn, F, device)
    total_params = sum(p.numel() for p in model.parameters())
    if total_params > MAX_CPU_MODEL_PARAMETERS and not args.allow_exceed_cap:
        print(f"BLOCKED: params={total_params} exceeds MAX_CPU_MODEL_PARAMETERS={MAX_CPU_MODEL_PARAMETERS}")
        return 1

    lr = args.lr if args.lr is not None else (0.0008 if args.arm == "arm_d" else 0.001)
    if args.arm == "arm_d":
        decay_p = [p for p in model.parameters() if p.requires_grad and p.dim() >= 2]
        nodecay_p = [p for p in model.parameters() if p.requires_grad and p.dim() < 2]
        optimizer = torch_mod.optim.AdamW(
            [{"params": decay_p, "weight_decay": 0.01}, {"params": nodecay_p, "weight_decay": 0.0}],
            lr=lr,
            betas=(0.9, 0.98),
        )
    else:
        optimizer = torch_mod.optim.Adam(model.parameters(), lr=lr, weight_decay=0.01)

    start_step = 0
    best_val_loss = float("inf")
    best_val_fg_exact = -1.0
    best_step = 0
    no_improve = 0
    train_losses: list[float] = []
    rng = random.Random(args.seed)

    if args.resume:
        res_path = Path(args.resume)
        if not res_path.is_file():
            print(f"BLOCKED: resume checkpoint not found at {res_path}")
            return 1
        r_ckpt = torch_mod.load(res_path, map_location=device, weights_only=False)
        if r_ckpt.get("arm") != args.arm:
            print(f"BLOCKED: resume arm mismatch ({r_ckpt.get('arm')} vs {args.arm})")
            return 1
        model.load_state_dict(r_ckpt["model_state"])
        if "optimizer_state" in r_ckpt and r_ckpt["optimizer_state"] is not None:
            optimizer.load_state_dict(r_ckpt["optimizer_state"])
        if "py_rng_state" in r_ckpt:
            rng.setstate(r_ckpt["py_rng_state"])
        if "torch_rng_state" in r_ckpt:
            torch_mod.set_rng_state(r_ckpt["torch_rng_state"].cpu())
        start_step = int(r_ckpt.get("step", 0))
        best_val_loss = float(r_ckpt.get("best_val_loss", float("inf")))
        best_val_fg_exact = float(r_ckpt.get("best_val_fg_exact", -1.0))
        best_step = int(r_ckpt.get("best_step", 0))
        no_improve = int(r_ckpt.get("no_improve", 0))
        print(f"Resumed {args.arm} from step {start_step} (best_val_loss={best_val_loss:.4f} at step {best_step})")

    manifest_path = data_dir / "manifest.json"
    manifest_sha = sha256_file(manifest_path) if manifest_path.is_file() else None
    manifest_seed = json.loads(manifest_path.read_text(encoding="utf-8")).get("seed") if manifest_path.is_file() else None

    def lr_schedule(step_i: int) -> float:
        if args.arm != "arm_d":
            return lr
        warmup = max(10, int(0.08 * total_steps))
        min_lr = lr * 0.1
        if step_i <= warmup:
            return lr * (step_i / warmup)
        progress = min(1.0, (step_i - warmup) / max(1, total_steps - warmup))
        return min_lr + 0.5 * (1.0 + math.cos(math.pi * progress)) * (lr - min_lr)

    batches = make_stratified_batches(
        train_rows, args.batch_size * args.grad_accum, total_steps, seed=args.seed
    )

    metrics_log_path = out_dir / "train_metrics.jsonl"
    if not args.resume and metrics_log_path.exists():
        metrics_log_path.unlink()

    print(
        f"Training {args.arm} ({ARM_DESCRIPTIONS[args.arm]}) | params={total_params} | "
        f"vocab={len(vocab)} | slots={use_slots} | steps={total_steps} | batch={args.batch_size}x{args.grad_accum} | device={device}"
    )

    stopped_reason = "completed"
    last_step = start_step
    best_state = None

    for step in range(start_step + 1, total_steps + 1):
        last_step = step
        model.train()
        cur_lr = lr_schedule(step)
        for pg in optimizer.param_groups:
            pg["lr"] = cur_lr

        optimizer.zero_grad(set_to_none=True)
        step_loss_sum = 0.0
        mega_batch = batches[step - 1]
        aborted_nan = False
        aborted_reason: str | None = None
        valid_microbatches = 0

        try:
            for acc_i in range(args.grad_accum):
                sub_batch = mega_batch[acc_i * args.batch_size : (acc_i + 1) * args.batch_size]
                loss = compute_batch_loss(
                    arm=args.arm,
                    model=model,
                    batch_rows=sub_batch,
                    stoi=stoi,
                    max_seq=args.seq,
                    step_idx=step,
                    total_steps=total_steps,
                    use_slots=use_slots,
                    permute_slots=use_slots,  # Slot Permutation Equivariance during training
                    rng=rng,
                    torch_mod=torch_mod,
                    F=F,
                    device=device,
                    aux_pgen_weight=0.05,
                )
                if loss is None:
                    continue
                loss_scaled = loss / args.grad_accum
                if not math.isfinite(float(loss_scaled.item())):
                    aborted_nan = True
                    aborted_reason = "abort_nan_inf_loss"
                    break
                loss_scaled.backward()
                step_loss_sum += float(loss_scaled.item())
                valid_microbatches += 1

            if not aborted_nan and valid_microbatches == 0:
                aborted_nan = True
                aborted_reason = "abort_invalid_batch_no_valid_rows"

            if not aborted_nan:
                for p in model.parameters():
                    if p.grad is not None and not torch_mod.isfinite(p.grad).all():
                        aborted_nan = True
                        aborted_reason = "abort_nan_inf_grad"
                        break
        except (MemoryError, RuntimeError) as exc:
            msg = str(exc).lower()
            if isinstance(exc, MemoryError) or "out of memory" in msg:
                optimizer.zero_grad(set_to_none=True)
                if torch_mod.cuda.is_available():
                    torch_mod.cuda.empty_cache()
                stopped_reason = "abort_oom"
                print(f"STOP CRITERIA TRIGGERED at step {step}: OutOfMemory ({exc})", file=sys.stderr)
                break
            raise

        if aborted_nan or not math.isfinite(step_loss_sum):
            optimizer.zero_grad(set_to_none=True)
            stopped_reason = aborted_reason or "abort_nan_inf_loss"
            print(f"STOP CRITERIA TRIGGERED at step {step}: {stopped_reason}", file=sys.stderr)
            break

        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        train_losses.append(step_loss_sum)

        if step % args.eval_every == 0 or step == total_steps:
            val_metrics = evaluate_val_split(
                arm=args.arm,
                model=model,
                val_rows=val_rows,
                vocab=vocab,
                stoi=stoi,
                itos=itos,
                max_seq=args.seq,
                use_slots=use_slots,
                torch_mod=torch_mod,
                F=F,
                device=device,
                fg_sample_limit=60,
            )
            vl = val_metrics["val_loss"]
            vfg = val_metrics["val_fg_exact_sample"]
            if not math.isfinite(vl):
                stopped_reason = "abort_nan_val_loss"
                print(f"STOP CRITERIA TRIGGERED at step {step}: NaN/Inf val_loss")
                break

            improved = vl < (best_val_loss - 1e-4)
            if improved:
                best_val_loss = vl
                best_val_fg_exact = vfg
                best_step = step
                no_improve = 0
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                best_payload = {
                    "format": "zyrquen_v9_ckpt_v1",
                    "arm": args.arm,
                    "description": ARM_DESCRIPTIONS[args.arm],
                    "arch_cfg": arch_cfg,
                    "model_state": best_state,
                    "vocab": vocab,
                    "vocab_source": "train-only",
                    "use_slots": use_slots,
                    "el05_verified_zero": True,
                    "dataset": str(data_dir),
                    "dataset_manifest_sha256": manifest_sha,
                    "dataset_seed": manifest_seed,
                    "seed": args.seed,
                    "from_scratch": True,
                    "step": step,
                    "best_step": best_step,
                    "best_val_loss": best_val_loss,
                    "best_val_fg_exact": best_val_fg_exact,
                    "params": total_params,
                    "environment": env_meta,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                }
                atomic_torch_save(torch_mod, best_payload, best_path)
            else:
                no_improve += 1

            last_payload = {
                "format": "zyrquen_v9_ckpt_v1",
                "arm": args.arm,
                "description": ARM_DESCRIPTIONS[args.arm],
                "arch_cfg": arch_cfg,
                "model_state": model.state_dict(),
                "optimizer_state": optimizer.state_dict(),
                "py_rng_state": rng.getstate(),
                "torch_rng_state": torch_mod.get_rng_state(),
                "vocab": vocab,
                "vocab_source": "train-only",
                "use_slots": use_slots,
                "el05_verified_zero": True,
                "dataset": str(data_dir),
                "dataset_manifest_sha256": manifest_sha,
                "dataset_seed": manifest_seed,
                "seed": args.seed,
                "from_scratch": True,
                "step": step,
                "best_step": best_step,
                "best_val_loss": best_val_loss,
                "best_val_fg_exact": best_val_fg_exact,
                "no_improve": no_improve,
                "params": total_params,
                "environment": env_meta,
                "elapsed_sec": round(time.time() - t0, 2),
                "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            }
            atomic_torch_save(torch_mod, last_payload, last_path)

            rec = {
                "step": step,
                "lr": round(cur_lr, 6),
                "train_loss": round(step_loss_sum, 4),
                "val_loss": round(vl, 4),
                "val_fg_exact_sample": round(vfg, 4),
                "best_val_loss": round(best_val_loss, 4),
                "best_step": best_step,
                "no_improve": no_improve,
                "elapsed_sec": round(time.time() - t0, 2),
                "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            }
            with metrics_log_path.open("a", encoding="utf-8") as mf:
                mf.write(json.dumps(rec) + "\n")

            print(
                f"step {step:4d}/{total_steps} | lr={cur_lr:.5f} | train_loss={step_loss_sum:.4f} | "
                f"val_loss={vl:.4f} | val_fg_sample={vfg:.4f} | best={best_val_loss:.4f}@{best_step}"
            )

            if args.patience > 0 and no_improve >= args.patience and step >= max(args.eval_every * 2, total_steps // 2):
                stopped_reason = f"early_stop_no_improve_{no_improve}"
                print(f"Early stopping at step {step} (no improvement for {no_improve} evals)")
                break

    best_state_restored = False
    if best_state is None and not best_path.exists():
        # Ensure best.pt exists even if run aborted early before first eval_every
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        best_payload = {
            "format": "zyrquen_v9_ckpt_v1",
            "arm": args.arm,
            "description": ARM_DESCRIPTIONS[args.arm],
            "arch_cfg": arch_cfg,
            "model_state": best_state,
            "vocab": vocab,
            "vocab_source": "train-only",
            "use_slots": use_slots,
            "el05_verified_zero": True,
            "dataset": str(data_dir),
            "dataset_manifest_sha256": manifest_sha,
            "dataset_seed": manifest_seed,
            "seed": args.seed,
            "from_scratch": True,
            "step": last_step,
            "best_step": best_step or last_step,
            "best_val_loss": best_val_loss if math.isfinite(best_val_loss) else None,
            "best_val_fg_exact": best_val_fg_exact,
            "params": total_params,
            "environment": env_meta,
            "elapsed_sec": round(time.time() - t0, 2),
            "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        atomic_torch_save(torch_mod, best_payload, best_path)

    # Restore best validation weights into model before closing out training
    if best_state is not None:
        model.load_state_dict({k: v.to(device) for k, v in best_state.items()})
        best_state_restored = True
    elif best_path.is_file():
        best_ckpt_disk = torch_mod.load(best_path, map_location=device, weights_only=False)
        if "model_state" in best_ckpt_disk:
            model.load_state_dict(best_ckpt_disk["model_state"])
            best_state_restored = True

    elapsed_sec = round(time.time() - t0, 2)
    max_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    last10 = train_losses[-10:] if train_losses else []
    avg_last10 = (sum(last10) / len(last10)) if last10 else None

    summary = {
        "mode": "train",
        "arm": args.arm,
        "description": ARM_DESCRIPTIONS[args.arm],
        "stopped_reason": stopped_reason,
        "step_completed": last_step,
        "target_steps": total_steps,
        "best_step": best_step,
        "best_val_loss": best_val_loss if math.isfinite(best_val_loss) else None,
        "best_val_fg_exact_sample": best_val_fg_exact if best_val_fg_exact >= 0 else None,
        "best_state_restored": best_state_restored,
        "train_loss_last10": round(avg_last10, 4) if avg_last10 is not None else None,
        "params": total_params,
        "vocab_size": len(vocab),
        "vocab_source": "train-only",
        "use_slots": use_slots,
        "el05_verified_zero": True,
        "from_scratch": True,
        "seed": args.seed,
        "arch_cfg": arch_cfg,
        "dataset": str(data_dir),
        "dataset_manifest_sha256": manifest_sha,
        "leakage_audit_status": audit_report.get("overall_status"),
        "best_checkpoint": str(best_path),
        "best_checkpoint_sha256": sha256_file(best_path) if best_path.is_file() else None,
        "last_checkpoint": str(last_path) if last_path.is_file() else None,
        "last_checkpoint_sha256": sha256_file(last_path) if last_path.is_file() else None,
        "environment": env_meta,
        "hardware": {
            "device": str(device),
            "cpu_count": env_meta.get("cpu_count"),
            "gpu_name": env_meta.get("gpu_name"),
            "gpu_total_mem_mb": env_meta.get("gpu_total_mem_mb"),
            "peak_cuda_mem_mb": (
                round(torch_mod.cuda.max_memory_allocated() / (1024 * 1024), 2)
                if torch_mod.cuda.is_available()
                else None
            ),
            "max_rss_kb": max_rss_kb,
        },
        "elapsed_sec": elapsed_sec,
        "max_rss_kb": max_rss_kb,
    }
    atomic_write_text(
        out_dir / "train_summary.json",
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
    )

    print(
        f"DONE [{args.arm}] reason={stopped_reason} | step={last_step} | best_step={best_step} | "
        f"best_val_loss={summary['best_val_loss']} | best_restored={best_state_restored} | "
        f"elapsed={elapsed_sec}s | rss={max_rss_kb}KB"
    )
    print(f"Summary saved to {out_dir / 'train_summary.json'}")
    return 1 if stopped_reason.startswith("abort_") else 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="ZYRQUEN v9 Controlled Trainer & Readiness Runner")
    ap.add_argument("--mode", choices=("readiness", "train"), default="readiness")
    ap.add_argument("--arm", choices=("arm_a", "arm_b", "arm_c", "arm_d"), default="arm_d")
    ap.add_argument("--data", default="data/nagi_v9", help="v9 dataset directory")
    ap.add_argument("--out", default=None, help="Output checkpoint dir (default: checkpoints/nagi_v9/<arm>)")
    ap.add_argument("--steps", type=int, default=None, help="Steps (default: 250 readiness, 960 train)")
    ap.add_argument("--batch_size", "--batch", dest="batch_size", type=int, default=4)
    ap.add_argument("--grad_accum", type=int, default=1)
    ap.add_argument("--seq", type=int, default=256)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--eval_every", type=int, default=120)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", default=None, help="Checkpoint path to resume training from")
    ap.add_argument("--overwrite", action="store_true", help="Allow overwriting existing best.pt/last.pt")
    ap.add_argument("--no-slots", action="store_true", help="Ablation for arm_d without slot binding")
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--n-heads", type=int, default=4)
    ap.add_argument("--d-ff", type=int, default=304)
    ap.add_argument("--enc-layers", type=int, default=4)
    ap.add_argument("--dec-layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--allow-exceed-cap", action="store_true", help="Explicit override for CPU resource caps")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0 or args.grad_accum <= 0 or args.eval_every <= 0:
        print("BLOCKED: --batch_size, --grad_accum, and --eval_every must be > 0", file=sys.stderr)
        return 1
    if args.seq < 16:
        print("BLOCKED: --seq must be >= 16", file=sys.stderr)
        return 1
    if args.steps is not None and args.steps <= 0:
        print("BLOCKED: --steps must be > 0", file=sys.stderr)
        return 1

    data_dir = Path(args.data)
    out_dir = Path(args.out) if args.out else Path("checkpoints/nagi_v9") / args.arm

    # Fail-closed Data Integrity & Leakage Gate before anything else
    if not (data_dir / "manifest.json").is_file():
        print(
            f"BLOCKED: Missing dataset manifest in {data_dir}.\n"
            "Generate and audit the v9 dataset first:\n"
            "  python3 tools/gen_nagi_v9.py\n"
            "  python3 tools/audit_leakage_v9.py",
            file=sys.stderr,
        )
        return 1

    audit_report = run_audit(data_dir)
    if audit_report.get("overall_status") != "PASS":
        failed = [gid for gid, info in audit_report["gates"].items() if not info.get("passed")]
        print(f"BLOCKED: Data Leakage Gate FAIL in {data_dir}. Failed gates: {failed}", file=sys.stderr)
        return 1

    if args.mode == "readiness":
        return run_readiness(args, data_dir, out_dir, audit_report)
    return run_train(args, data_dir, out_dir, audit_report)


if __name__ == "__main__":
    sys.exit(main())
