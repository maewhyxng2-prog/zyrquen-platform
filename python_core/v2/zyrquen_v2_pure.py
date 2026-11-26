"""Pure-Python 3.11 Standard Library V2 Native Transformer with RoPE, SwiGLU,
NTK Context Extension, Exact Analytical Backprop, and Full Optimizer/Replay Resume.

Zero external AI models, zero PyTorch/NumPy dependency.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.zyrquen_v2_trainer import (
    BYTE_VOCAB_SIZE,
    EOS_TOKEN_ID,
    IGNORE_INDEX,
    PAD_TOKEN_ID,
    ByteTokenizer,
)


@dataclass
class PureZyrquenV2Config:
    vocab_size: int = BYTE_VOCAB_SIZE
    pad_token_id: int = PAD_TOKEN_ID
    eos_token_id: int = EOS_TOKEN_ID
    d_model: int = 24
    n_heads: int = 2
    n_layers: int = 2
    d_ff: int = 48
    base_seq_len: int = 64
    max_seq_len: int = 128
    rope_base: float = 10000.0
    seed: int = 42

    def __post_init__(self) -> None:
        if self.d_model % self.n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        if (self.d_model // self.n_heads) % 2 != 0:
            raise ValueError("head_dim must be even for RoPE")
        if self.max_seq_len < self.base_seq_len:
            raise ValueError("max_seq_len must be >= base_seq_len")


def _zeros(n: int) -> List[float]:
    return [0.0] * n


def _zeros_2d(rows: int, cols: int) -> List[List[float]]:
    return [[0.0] * cols for _ in range(rows)]


def _randn_matrix(
    rows: int, cols: int, std: float, rng: random.Random
) -> List[List[float]]:
    return [[rng.gauss(0.0, std) for _ in range(cols)] for _ in range(rows)]


def _precompute_rope(
    head_dim: int,
    max_seq_len: int,
    base_seq_len: int,
    rope_base: float,
) -> Tuple[List[List[float]], List[List[float]]]:
    """Compute RoPE cos/sin caches with NTK-aware scaling when max_seq_len > base_seq_len."""
    if max_seq_len > base_seq_len:
        scale_factor = max_seq_len / float(base_seq_len)
        eff_base = rope_base * (scale_factor ** (head_dim / max(head_dim - 2, 2)))
    else:
        eff_base = rope_base

    half = head_dim // 2
    inv_freq = [1.0 / (eff_base ** ((2.0 * i) / head_dim)) for i in range(half)]
    cos_tab: List[List[float]] = []
    sin_tab: List[List[float]] = []
    for pos in range(max_seq_len):
        c_row: List[float] = []
        s_row: List[float] = []
        for f in inv_freq:
            ang = pos * f
            c_row.append(math.cos(ang))
            s_row.append(math.sin(ang))
        cos_tab.append(c_row)
        sin_tab.append(s_row)
    return cos_tab, sin_tab


def _rmsnorm_forward(
    x: List[List[float]], gamma: List[float], eps: float = 1e-5
) -> Tuple[List[List[float]], Tuple[List[List[float]], List[float]]]:
    T = len(x)
    D = len(gamma)
    out = _zeros_2d(T, D)
    inv_rms = [0.0] * T
    u_cache = _zeros_2d(T, D)
    for t in range(T):
        xt = x[t]
        mean_sq = sum(v * v for v in xt) / D
        ir = 1.0 / math.sqrt(mean_sq + eps)
        inv_rms[t] = ir
        ut = u_cache[t]
        ot = out[t]
        for d in range(D):
            u = xt[d] * ir
            ut[d] = u
            ot[d] = u * gamma[d]
    return out, (u_cache, inv_rms)


def _rmsnorm_backward(
    dout: List[List[float]],
    gamma: List[float],
    cache: Tuple[List[List[float]], List[float]],
    dgamma: List[float],
) -> List[List[float]]:
    u_cache, inv_rms = cache
    T = len(dout)
    D = len(gamma)
    dx = _zeros_2d(T, D)
    for t in range(T):
        dot_t = dout[t]
        ut = u_cache[t]
        ir = inv_rms[t]
        dot_gu = 0.0
        for d in range(D):
            dgamma[d] += dot_t[d] * ut[d]
            dot_gu += (dot_t[d] * gamma[d]) * ut[d]
        mean_gu = dot_gu / D
        dxt = dx[t]
        for d in range(D):
            gu = dot_t[d] * gamma[d]
            dxt[d] = ir * (gu - ut[d] * mean_gu)
    return dx


def _linear_forward(
    x: List[List[float]], w: List[List[float]]
) -> List[List[float]]:
    T = len(x)
    in_d = len(w)
    out_d = len(w[0])
    out = _zeros_2d(T, out_d)
    for t in range(T):
        xt = x[t]
        ot = out[t]
        for i in range(in_d):
            xi = xt[i]
            if xi == 0.0:
                continue
            wi = w[i]
            for j in range(out_d):
                ot[j] += xi * wi[j]
    return out


def _linear_backward(
    dout: List[List[float]],
    x: List[List[float]],
    w: List[List[float]],
    dw: List[List[float]],
) -> List[List[float]]:
    T = len(dout)
    in_d = len(w)
    out_d = len(w[0])
    dx = _zeros_2d(T, in_d)
    for t in range(T):
        dt = dout[t]
        xt = x[t]
        dxt = dx[t]
        for i in range(in_d):
            xi = xt[i]
            wi = w[i]
            dwi = dw[i]
            acc = 0.0
            for j in range(out_d):
                dj = dt[j]
                acc += dj * wi[j]
                dwi[j] += xi * dj
            dxt[i] = acc
    return dx


def _silu(x: float) -> Tuple[float, float]:
    if x >= 0.0:
        z = math.exp(-x)
        sig = 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        sig = z / (1.0 + z)
    return x * sig, sig * (1.0 + x * (1.0 - sig))


class PureNativeTransformerLMV2:
    """Pure-Python Decoder Transformer V2 with RoPE, NTK Context Extension, and SwiGLU."""

    def __init__(self, cfg: PureZyrquenV2Config) -> None:
        self.cfg = cfg
        rng = random.Random(cfg.seed)
        V, D, F_dim = cfg.vocab_size, cfg.d_model, cfg.d_ff
        emb_std = 0.02
        proj_std = 1.0 / math.sqrt(D)
        res_scale = 1.0 / math.sqrt(2 * cfg.n_layers)

        self.params: Dict[str, Any] = {
            "tok_emb": _randn_matrix(V, D, emb_std, rng),
            "layers": [
                {
                    "gamma1": [1.0] * D,
                    "wq": _randn_matrix(D, D, proj_std, rng),
                    "wk": _randn_matrix(D, D, proj_std, rng),
                    "wv": _randn_matrix(D, D, proj_std, rng),
                    "wo": _randn_matrix(D, D, proj_std * res_scale, rng),
                    "gamma2": [1.0] * D,
                    "w_gate": _randn_matrix(D, F_dim, proj_std, rng),
                    "w_up": _randn_matrix(D, F_dim, proj_std, rng),
                    "w_down": _randn_matrix(F_dim, D, (1.0 / math.sqrt(F_dim)) * res_scale, rng),
                }
                for _ in range(cfg.n_layers)
            ],
            "final_gamma": [1.0] * D,
            "lm_head_w": _randn_matrix(D, V, proj_std, rng),
        }
        self.rope_cos, self.rope_sin = _precompute_rope(
            cfg.d_model // cfg.n_heads,
            cfg.max_seq_len,
            cfg.base_seq_len,
            cfg.rope_base,
        )

    def extend_context(self, new_max_seq_len: int) -> None:
        if new_max_seq_len <= self.cfg.max_seq_len:
            return
        self.cfg.max_seq_len = int(new_max_seq_len)
        self.rope_cos, self.rope_sin = _precompute_rope(
            self.cfg.d_model // self.cfg.n_heads,
            self.cfg.max_seq_len,
            self.cfg.base_seq_len,
            self.cfg.rope_base,
        )

    def parameter_count(self) -> int:
        total = 0

        def _count(obj: Any) -> None:
            nonlocal total
            if isinstance(obj, list):
                if obj and isinstance(obj[0], float):
                    total += len(obj)
                else:
                    for item in obj:
                        _count(item)
            elif isinstance(obj, dict):
                for val in obj.values():
                    _count(val)

        _count(self.params)
        return total

    def zero_grads(self) -> Dict[str, Any]:
        V, D, F_dim = self.cfg.vocab_size, self.cfg.d_model, self.cfg.d_ff
        return {
            "tok_emb": _zeros_2d(V, D),
            "layers": [
                {
                    "gamma1": _zeros(D),
                    "wq": _zeros_2d(D, D),
                    "wk": _zeros_2d(D, D),
                    "wv": _zeros_2d(D, D),
                    "wo": _zeros_2d(D, D),
                    "gamma2": _zeros(D),
                    "w_gate": _zeros_2d(D, F_dim),
                    "w_up": _zeros_2d(D, F_dim),
                    "w_down": _zeros_2d(F_dim, D),
                }
                for _ in range(self.cfg.n_layers)
            ],
            "final_gamma": _zeros(D),
            "lm_head_w": _zeros_2d(D, V),
        }

    def forward(
        self, token_ids: List[int], *, record_cache: bool = False
    ) -> Tuple[List[List[float]], Optional[Dict[str, Any]]]:
        T = len(token_ids)
        if T > self.cfg.max_seq_len:
            raise ValueError(
                f"Sequence length {T} exceeds max_seq_len={self.cfg.max_seq_len}"
            )
        D = self.cfg.d_model
        H = self.cfg.n_heads
        dh = D // H
        half = dh // 2
        scale = 1.0 / math.sqrt(dh)

        tok_emb = self.params["tok_emb"]
        h = [list(tok_emb[tid]) for tid in token_ids]

        layer_caches: List[Dict[str, Any]] = []
        for lyr in self.params["layers"]:
            norm1, rms1_cache = _rmsnorm_forward(h, lyr["gamma1"])
            Q_raw = _linear_forward(norm1, lyr["wq"])
            K_raw = _linear_forward(norm1, lyr["wk"])
            V_mat = _linear_forward(norm1, lyr["wv"])

            # Apply RoPE per head per position
            Q_rot = _zeros_2d(T, D)
            K_rot = _zeros_2d(T, D)
            for t in range(T):
                ct = self.rope_cos[t]
                st = self.rope_sin[t]
                qt_raw = Q_raw[t]
                kt_raw = K_raw[t]
                qt_rot = Q_rot[t]
                kt_rot = K_rot[t]
                for hd in range(H):
                    off = hd * dh
                    for p in range(half):
                        i0 = off + 2 * p
                        i1 = i0 + 1
                        c = ct[p]
                        s = st[p]
                        q0, q1 = qt_raw[i0], qt_raw[i1]
                        k0, k1 = kt_raw[i0], kt_raw[i1]
                        qt_rot[i0] = q0 * c - q1 * s
                        qt_rot[i1] = q0 * s + q1 * c
                        kt_rot[i0] = k0 * c - k1 * s
                        kt_rot[i1] = k0 * s + k1 * c

            ctx = _zeros_2d(T, D)
            attn_weights: List[List[List[float]]] = []
            for hd in range(H):
                off = hd * dh
                hd_w: List[List[float]] = []
                for t in range(T):
                    scores: List[float] = []
                    max_s = -1e30
                    qt = Q_rot[t]
                    for s in range(t + 1):
                        ks = K_rot[s]
                        dot = (
                            sum(qt[off + k] * ks[off + k] for k in range(dh))
                            * scale
                        )
                        scores.append(dot)
                        if dot > max_s:
                            max_s = dot
                    exps = [math.exp(sc - max_s) for sc in scores]
                    denom = sum(exps) or 1.0
                    probs = [e / denom for e in exps]
                    hd_w.append(probs)
                    ct = ctx[t]
                    for s, pr in enumerate(probs):
                        vs = V_mat[s]
                        for k in range(dh):
                            ct[off + k] += pr * vs[off + k]
                attn_weights.append(hd_w)

            attn_out = _linear_forward(ctx, lyr["wo"])
            h_mid = [[h[t][d] + attn_out[t][d] for d in range(D)] for t in range(T)]

            norm2, rms2_cache = _rmsnorm_forward(h_mid, lyr["gamma2"])
            gate_pre = _linear_forward(norm2, lyr["w_gate"])
            up_pre = _linear_forward(norm2, lyr["w_up"])
            F_dim = self.cfg.d_ff
            gate_act = _zeros_2d(T, F_dim)
            gate_deriv = _zeros_2d(T, F_dim)
            swiglu = _zeros_2d(T, F_dim)
            for t in range(T):
                for j in range(F_dim):
                    val, dv = _silu(gate_pre[t][j])
                    gate_act[t][j] = val
                    gate_deriv[t][j] = dv
                    swiglu[t][j] = val * up_pre[t][j]
            ff_out = _linear_forward(swiglu, lyr["w_down"])
            h = [[h_mid[t][d] + ff_out[t][d] for d in range(D)] for t in range(T)]

            if record_cache:
                layer_caches.append(
                    {
                        "norm1": norm1,
                        "rms1_cache": rms1_cache,
                        "Q_rot": Q_rot,
                        "K_rot": K_rot,
                        "V": V_mat,
                        "ctx": ctx,
                        "attn_weights": attn_weights,
                        "norm2": norm2,
                        "rms2_cache": rms2_cache,
                        "gate_act": gate_act,
                        "gate_deriv": gate_deriv,
                        "up_pre": up_pre,
                        "swiglu": swiglu,
                    }
                )

        h_final, final_rms_cache = _rmsnorm_forward(h, self.params["final_gamma"])
        logits = _linear_forward(h_final, self.params["lm_head_w"])
        if not record_cache:
            return logits, None
        return logits, {
            "ids": list(token_ids),
            "h_final": h_final,
            "final_rms_cache": final_rms_cache,
            "layer_caches": layer_caches,
        }

    def forward_loss_and_backward(
        self,
        input_ids: List[int],
        target_ids: List[int],
        grads: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, int, Dict[str, Any]]:
        if grads is None:
            grads = self.zero_grads()
        T = min(len(input_ids), len(target_ids))
        if T <= 0:
            return 0.0, 0, grads

        logits, cache = self.forward(input_ids[:T], record_cache=True)
        assert cache is not None
        V = self.cfg.vocab_size
        D = self.cfg.d_model
        H = self.cfg.n_heads
        dh = D // H
        half = dh // 2
        scale = 1.0 / math.sqrt(dh)

        valid_count = sum(1 for t in range(T) if target_ids[t] != IGNORE_INDEX)
        if valid_count == 0:
            return 0.0, 0, grads
        inv_valid = 1.0 / valid_count

        dlogits = _zeros_2d(T, V)
        total_loss = 0.0
        correct = 0
        for t in range(T):
            tgt = target_ids[t]
            if tgt == IGNORE_INDEX:
                continue
            lt = logits[t]
            max_l = max(lt)
            exps = [math.exp(v - max_l) for v in lt]
            denom = sum(exps) or 1.0
            probs = [e / denom for e in exps]
            pred = max(range(V), key=lambda idx: probs[idx])
            if pred == tgt:
                correct += 1
            total_loss += -math.log(max(probs[tgt], 1e-12))
            dt = dlogits[t]
            for v in range(V):
                dt[v] = (probs[v] - (1.0 if v == tgt else 0.0)) * inv_valid

        dh_final = _linear_backward(
            dlogits,
            cache["h_final"],
            self.params["lm_head_w"],
            grads["lm_head_w"],
        )
        dh_curr = _rmsnorm_backward(
            dh_final,
            self.params["final_gamma"],
            cache["final_rms_cache"],
            grads["final_gamma"],
        )

        for l_idx in range(self.cfg.n_layers - 1, -1, -1):
            lyr = self.params["layers"][l_idx]
            g_lyr = grads["layers"][l_idx]
            lc = cache["layer_caches"][l_idx]
            F_dim = self.cfg.d_ff

            # SwiGLU FFN backward
            dswiglu = _linear_backward(
                dh_curr, lc["swiglu"], lyr["w_down"], g_lyr["w_down"]
            )
            dgate_pre = _zeros_2d(T, F_dim)
            dup_pre = _zeros_2d(T, F_dim)
            for t in range(T):
                for j in range(F_dim):
                    ds = dswiglu[t][j]
                    dgate_pre[t][j] = ds * lc["up_pre"][t][j] * lc["gate_deriv"][t][j]
                    dup_pre[t][j] = ds * lc["gate_act"][t][j]

            dn2_gate = _linear_backward(
                dgate_pre, lc["norm2"], lyr["w_gate"], g_lyr["w_gate"]
            )
            dn2_up = _linear_backward(
                dup_pre, lc["norm2"], lyr["w_up"], g_lyr["w_up"]
            )
            dnorm2 = [
                [dn2_gate[t][d] + dn2_up[t][d] for d in range(D)] for t in range(T)
            ]
            dh_mid = _rmsnorm_backward(
                dnorm2, lyr["gamma2"], lc["rms2_cache"], g_lyr["gamma2"]
            )
            for t in range(T):
                for d in range(D):
                    dh_mid[t][d] += dh_curr[t][d]

            # Causal Attention + RoPE backward
            dctx = _linear_backward(dh_mid, lc["ctx"], lyr["wo"], g_lyr["wo"])
            dQ_rot = _zeros_2d(T, D)
            dK_rot = _zeros_2d(T, D)
            dV = _zeros_2d(T, D)
            Q_rot, K_rot, V_mat = lc["Q_rot"], lc["K_rot"], lc["V"]

            for hd in range(H):
                off = hd * dh
                hd_w = lc["attn_weights"][hd]
                for t in range(T):
                    probs = hd_w[t]
                    dct = dctx[t]
                    d_att = [0.0] * (t + 1)
                    for s in range(t + 1):
                        vs = V_mat[s]
                        pr = probs[s]
                        dvs = dV[s]
                        acc = 0.0
                        for k in range(dh):
                            gc = dct[off + k]
                            acc += gc * vs[off + k]
                            dvs[off + k] += pr * gc
                        d_att[s] = acc
                    dot_ap = sum(d_att[s] * probs[s] for s in range(t + 1))
                    qt = Q_rot[t]
                    dqt = dQ_rot[t]
                    for s in range(t + 1):
                        d_score = probs[s] * (d_att[s] - dot_ap) * scale
                        ks = K_rot[s]
                        dks = dK_rot[s]
                        for k in range(dh):
                            dqt[off + k] += d_score * ks[off + k]
                            dks[off + k] += d_score * qt[off + k]

            # Inverse RoPE rotation for dQ and dK
            dQ_raw = _zeros_2d(T, D)
            dK_raw = _zeros_2d(T, D)
            for t in range(T):
                ct = self.rope_cos[t]
                st = self.rope_sin[t]
                for hd in range(H):
                    off = hd * dh
                    for p in range(half):
                        i0 = off + 2 * p
                        i1 = i0 + 1
                        c = ct[p]
                        s = st[p]
                        gq0, gq1 = dQ_rot[t][i0], dQ_rot[t][i1]
                        gk0, gk1 = dK_rot[t][i0], dK_rot[t][i1]
                        dQ_raw[t][i0] = gq0 * c + gq1 * s
                        dQ_raw[t][i1] = -gq0 * s + gq1 * c
                        dK_raw[t][i0] = gk0 * c + gk1 * s
                        dK_raw[t][i1] = -gk0 * s + gk1 * c

            dn1_q = _linear_backward(dQ_raw, lc["norm1"], lyr["wq"], g_lyr["wq"])
            dn1_k = _linear_backward(dK_raw, lc["norm1"], lyr["wk"], g_lyr["wk"])
            dn1_v = _linear_backward(dV, lc["norm1"], lyr["wv"], g_lyr["wv"])
            dnorm1 = [
                [dn1_q[t][d] + dn1_k[t][d] + dn1_v[t][d] for d in range(D)]
                for t in range(T)
            ]
            dh_attn = _rmsnorm_backward(
                dnorm1, lyr["gamma1"], lc["rms1_cache"], g_lyr["gamma1"]
            )
            dh_curr = [[dh_mid[t][d] + dh_attn[t][d] for d in range(D)] for t in range(T)]

        g_tok = grads["tok_emb"]
        for t, tid in enumerate(cache["ids"]):
            dt = dh_curr[t]
            gt = g_tok[tid]
            for d in range(D):
                gt[d] += dt[d]

        return total_loss * inv_valid, correct, grads

    def evaluate_texts(
        self, tokenizer: ByteTokenizer, texts: List[str]
    ) -> Dict[str, Any]:
        total_loss = 0.0
        total_tokens = 0
        total_correct = 0
        V = self.cfg.vocab_size
        for text in texts:
            ids = tokenizer.encode(text, add_eos=True)[: self.cfg.max_seq_len]
            if len(ids) < 2:
                continue
            inp = ids[:-1]
            tgt = ids[1:]
            logits, _ = self.forward(inp, record_cache=False)
            for t, y in enumerate(tgt):
                if y == IGNORE_INDEX or y == tokenizer.pad_id:
                    continue
                lt = logits[t]
                max_l = max(lt)
                exps = [math.exp(v - max_l) for v in lt]
                denom = sum(exps) or 1.0
                probs = [e / denom for e in exps]
                total_loss += -math.log(max(probs[y], 1e-12))
                total_tokens += 1
                pred = max(range(V), key=lambda idx: probs[idx])
                if pred == y:
                    total_correct += 1
        if total_tokens == 0:
            return {"loss": 0.0, "perplexity": 1.0, "accuracy": 0.0, "tokens": 0}
        avg_loss = total_loss / total_tokens
        return {
            "loss": round(avg_loss, 4),
            "perplexity": round(math.exp(min(avg_loss, 20.0)), 3),
            "accuracy": round(total_correct / total_tokens, 4),
            "tokens": total_tokens,
        }

    def generate_text(
        self, tokenizer: ByteTokenizer, prompt: str, max_new_tokens: int = 64
    ) -> str:
        ids = tokenizer.encode(prompt, add_eos=False)
        cur = list(ids)
        for _ in range(max_new_tokens):
            window = cur[-self.cfg.max_seq_len :]
            logits, _ = self.forward(window, record_cache=False)
            last_lt = logits[-1]
            best_id = max(range(len(last_lt)), key=lambda i: last_lt[i])
            if best_id == tokenizer.eos_id or best_id == tokenizer.pad_id:
                break
            cur.append(best_id)
        return tokenizer.decode(cur, stop_at_eos=True)


def _grad_l2_norm(grads: Any, grad_scale: float) -> float:
    sq = 0.0

    def _walk(g: Any) -> None:
        nonlocal sq
        if isinstance(g, dict):
            for v in g.values():
                _walk(v)
        elif isinstance(g, list):
            if g and isinstance(g[0], float):
                for val in g:
                    gv = val * grad_scale
                    sq += gv * gv
            else:
                for item in g:
                    _walk(item)

    _walk(grads)
    return math.sqrt(sq)


def _adamw_step(
    params: Any,
    grads: Any,
    m_state: Any,
    v_state: Any,
    *,
    lr: float,
    beta1: float,
    beta2: float,
    eps: float,
    weight_decay: float,
    step_num: int,
    grad_scale: float,
    clip_scale: float,
) -> None:
    bc1 = 1.0 - (beta1**step_num)
    bc2 = 1.0 - (beta2**step_num)

    def _walk(p: Any, g: Any, m: Any, v: Any) -> None:
        if isinstance(p, dict):
            for k in p:
                _walk(p[k], g[k], m[k], v[k])
        elif isinstance(p, list):
            if p and isinstance(p[0], list):
                for r in range(len(p)):
                    _walk(p[r], g[r], m[r], v[r])
            elif p and isinstance(p[0], float):
                for i in range(len(p)):
                    gi = g[i] * grad_scale * clip_scale
                    mi = beta1 * m[i] + (1.0 - beta1) * gi
                    vi = beta2 * v[i] + (1.0 - beta2) * (gi * gi)
                    m[i] = mi
                    v[i] = vi
                    m_hat = mi / bc1
                    v_hat = vi / bc2
                    p[i] = p[i] * (1.0 - lr * weight_decay) - lr * (
                        m_hat / (math.sqrt(v_hat) + eps)
                    )

    _walk(params, grads, m_state, v_state)


def _add_consolidation_grads(
    params: Any,
    anchor_params: Any,
    importance_diag: Any,
    grads: Any,
    l2_lambda: float,
) -> None:
    if l2_lambda <= 0.0 or not anchor_params:
        return

    def _walk(p: Any, ap: Any, imp: Any, g: Any) -> None:
        if isinstance(p, dict):
            for k in p:
                _walk(p[k], ap[k], imp[k] if imp else None, g[k])
        elif isinstance(p, list):
            if p and isinstance(p[0], list):
                for r in range(len(p)):
                    _walk(p[r], ap[r], imp[r] if imp else None, g[r])
            elif p and isinstance(p[0], float):
                for i in range(len(p)):
                    w_imp = imp[i] if imp is not None else 1.0
                    g[i] += l2_lambda * w_imp * (p[i] - ap[i])

    _walk(params, anchor_params, importance_diag, grads)


class PureContinualTrainerV2:
    """Pure-Python V2 trainer with full Optimizer (m, v, step) + Replay + Consolidation resume."""

    def __init__(
        self,
        model: PureNativeTransformerLMV2,
        tokenizer: ByteTokenizer,
        *,
        lr: float = 0.008,
        min_lr_ratio: float = 0.15,
        warmup_steps: int = 10,
        total_decay_steps: int = 240,
        weight_decay: float = 0.01,
        replay_capacity: int = 128,
        consolidation_lambda: float = 0.02,
        seed: int = 42,
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.lr = lr
        self.min_lr_ratio = min_lr_ratio
        self.warmup_steps = max(1, warmup_steps)
        self.total_decay_steps = max(self.warmup_steps + 1, total_decay_steps)
        self.weight_decay = weight_decay
        self.replay_capacity = replay_capacity
        self.consolidation_lambda = consolidation_lambda
        self.rng = random.Random(seed)

        self.m_state: Dict[str, Any] = model.zero_grads()
        self.v_state: Dict[str, Any] = model.zero_grads()
        self.global_step: int = 0
        self.replay_buffer: List[str] = []
        self.anchor_params: Dict[str, Any] = {}
        self.importance_diag: Dict[str, Any] = {}

    def _current_lr(self, step: int) -> float:
        if step <= self.warmup_steps:
            ratio = max(self.min_lr_ratio, float(step) / float(self.warmup_steps))
        elif step >= self.total_decay_steps:
            ratio = self.min_lr_ratio
        else:
            prog = float(step - self.warmup_steps) / float(
                self.total_decay_steps - self.warmup_steps
            )
            cosine = 0.5 * (1.0 + math.cos(math.pi * prog))
            ratio = self.min_lr_ratio + (1.0 - self.min_lr_ratio) * cosine
        return self.lr * ratio

    def add_replay_samples(self, samples: List[str]) -> None:
        for s in samples:
            if s in self.replay_buffer:
                continue
            if len(self.replay_buffer) < self.replay_capacity:
                self.replay_buffer.append(s)
            else:
                self.replay_buffer[self.rng.randrange(self.replay_capacity)] = s

    def snapshot_consolidation_state(self, texts: List[str]) -> None:
        self.anchor_params = copy.deepcopy(self.model.params)
        acc = self.model.zero_grads()
        count = 0
        for text in texts:
            ids = self.tokenizer.encode(text, add_eos=True)[: self.model.cfg.max_seq_len]
            if len(ids) < 2:
                continue
            _, _, g = self.model.forward_loss_and_backward(ids[:-1], ids[1:])

            def _accum_sq(dst: Any, src: Any) -> None:
                if isinstance(dst, dict):
                    for k in dst:
                        _accum_sq(dst[k], src[k])
                elif isinstance(dst, list):
                    if dst and isinstance(dst[0], list):
                        for r in range(len(dst)):
                            _accum_sq(dst[r], src[r])
                    elif dst and isinstance(dst[0], float):
                        for i in range(len(dst)):
                            dst[i] += src[i] * src[i]

            _accum_sq(acc, g)
            count += 1

        if count > 0:
            inv = 1.0 / count

            def _scale(dst: Any) -> None:
                if isinstance(dst, dict):
                    for k in dst:
                        _scale(dst[k])
                elif isinstance(dst, list):
                    if dst and isinstance(dst[0], list):
                        for r in range(len(dst)):
                            _scale(dst[r])
                    elif dst and isinstance(dst[0], float):
                        for i in range(len(dst)):
                            dst[i] *= inv

            _scale(acc)
        self.importance_diag = acc

    def train_steps(
        self,
        train_texts: List[str],
        *,
        steps: int = 40,
        batch_size: int = 3,
        replay_ratio: float = 0.5,
        max_grad_norm: float = 1.0,
    ) -> Dict[str, Any]:
        if not train_texts:
            return {"steps": 0, "final_loss": 0.0, "global_step": self.global_step}

        last_loss = 0.0
        for _ in range(steps):
            chosen = self.rng.choices(train_texts, k=batch_size)
            if self.replay_buffer and replay_ratio > 0.0:
                n_rep = min(
                    int(round(batch_size * replay_ratio)),
                    len(self.replay_buffer),
                    batch_size,
                )
                if n_rep > 0:
                    chosen = chosen[: batch_size - n_rep] + self.rng.sample(
                        self.replay_buffer, n_rep
                    )

            accum = self.model.zero_grads()
            batch_loss = 0.0
            valid_items = 0
            for text in chosen:
                ids = self.tokenizer.encode(text, add_eos=True)[
                    : self.model.cfg.max_seq_len
                ]
                if len(ids) < 2:
                    continue
                loss_val, _, accum = self.model.forward_loss_and_backward(
                    ids[:-1], ids[1:], grads=accum
                )
                if math.isnan(loss_val) or math.isinf(loss_val):
                    raise RuntimeError("Training halted: NaN/Inf loss detected")
                batch_loss += loss_val
                valid_items += 1

            if valid_items == 0:
                continue

            self.global_step += 1
            _add_consolidation_grads(
                self.model.params,
                self.anchor_params,
                self.importance_diag,
                accum,
                self.consolidation_lambda * valid_items,
            )
            g_scale = 1.0 / valid_items
            gnorm = _grad_l2_norm(accum, g_scale)
            clip_scale = (
                min(1.0, max_grad_norm / gnorm)
                if gnorm > max_grad_norm and gnorm > 0.0
                else 1.0
            )
            cur_lr = self._current_lr(self.global_step)
            _adamw_step(
                self.model.params,
                accum,
                self.m_state,
                self.v_state,
                lr=cur_lr,
                beta1=0.9,
                beta2=0.95,
                eps=1e-8,
                weight_decay=self.weight_decay,
                step_num=self.global_step,
                grad_scale=g_scale,
                clip_scale=clip_scale,
            )
            last_loss = batch_loss / valid_items

        self.add_replay_samples(train_texts)
        return {
            "steps": steps,
            "final_loss": round(last_loss, 4),
            "global_step": self.global_step,
        }

    def save_checkpoint(self, path: str | Path) -> Tuple[Path, str]:
        out_path = Path(path)
        if out_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing checkpoint: {out_path}"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "zyrquen.v2.pure_checkpoint",
            "config": asdict(self.model.cfg),
            "params": self.model.params,
            "m_state": self.m_state,
            "v_state": self.v_state,
            "global_step": self.global_step,
            "replay_buffer": self.replay_buffer,
            "anchor_params": self.anchor_params,
            "importance_diag": self.importance_diag,
            "trainer_hparams": {
                "lr": self.lr,
                "min_lr_ratio": self.min_lr_ratio,
                "warmup_steps": self.warmup_steps,
                "total_decay_steps": self.total_decay_steps,
                "weight_decay": self.weight_decay,
                "replay_capacity": self.replay_capacity,
                "consolidation_lambda": self.consolidation_lambda,
            },
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with gzip.open(out_path, "wb") as fh:
            fh.write(raw)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        out_path.with_suffix(out_path.suffix + ".sha256").write_text(
            digest, encoding="utf-8"
        )
        return out_path, digest

    @classmethod
    def load_checkpoint(
        cls,
        path: str | Path,
        tokenizer: ByteTokenizer,
        *,
        expected_sha256: Optional[str] = None,
        resume_optimizer: bool = True,
        restore_continual_state: bool = True,
        consolidation_lambda: Optional[float] = None,
    ) -> "PureContinualTrainerV2":
        ckpt_path = Path(path)
        if expected_sha256 is not None:
            actual = hashlib.sha256(ckpt_path.read_bytes()).hexdigest()
            if actual != expected_sha256:
                raise ValueError("Checkpoint SHA-256 verification failed")

        with gzip.open(ckpt_path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))

        cfg = PureZyrquenV2Config(**data["config"])
        model = PureNativeTransformerLMV2(cfg)
        model.params = data["params"]
        hp = data.get("trainer_hparams") or {}

        c_lambda = (
            float(hp.get("consolidation_lambda", 0.02))
            if consolidation_lambda is None
            else float(consolidation_lambda)
        )
        trainer = cls(
            model=model,
            tokenizer=tokenizer,
            lr=float(hp.get("lr", 0.008)),
            min_lr_ratio=float(hp.get("min_lr_ratio", 0.15)),
            warmup_steps=int(hp.get("warmup_steps", 10)),
            total_decay_steps=int(hp.get("total_decay_steps", 240)),
            weight_decay=float(hp.get("weight_decay", 0.01)),
            replay_capacity=int(hp.get("replay_capacity", 128)),
            consolidation_lambda=c_lambda,
        )
        if restore_continual_state:
            trainer.replay_buffer = list(data.get("replay_buffer", []))
            trainer.anchor_params = data.get("anchor_params") or {}
            trainer.importance_diag = data.get("importance_diag") or {}
        if resume_optimizer:
            trainer.m_state = data["m_state"]
            trainer.v_state = data["v_state"]
            trainer.global_step = int(data.get("global_step", 0))
        return trainer


def verify_v2_gradients(seed: int = 7) -> Dict[str, Any]:
    """Finite-difference gradient verification for RoPE + SwiGLU + RMSNorm analytical backprop."""
    cfg = PureZyrquenV2Config(
        vocab_size=258,
        d_model=8,
        n_heads=2,
        n_layers=1,
        d_ff=16,
        base_seq_len=8,
        max_seq_len=16,
        seed=seed,
    )
    model = PureNativeTransformerLMV2(cfg)
    inp = [65, 66, 67, 68]
    tgt = [66, 67, 68, EOS_TOKEN_ID]
    _, _, grads = model.forward_loss_and_backward(inp, tgt)

    eps = 1e-5
    probes = [
        ("tok_emb[66][1]", model.params["tok_emb"][66], 1, grads["tok_emb"][66][1]),
        ("wq[0][2]", model.params["layers"][0]["wq"][0], 2, grads["layers"][0]["wq"][0][2]),
        ("wk[1][3]", model.params["layers"][0]["wk"][1], 3, grads["layers"][0]["wk"][1][3]),
        ("wv[2][1]", model.params["layers"][0]["wv"][2], 1, grads["layers"][0]["wv"][2][1]),
        ("wo[3][0]", model.params["layers"][0]["wo"][3], 0, grads["layers"][0]["wo"][3][0]),
        ("w_gate[1][4]", model.params["layers"][0]["w_gate"][1], 4, grads["layers"][0]["w_gate"][1][4]),
        ("w_up[2][5]", model.params["layers"][0]["w_up"][2], 5, grads["layers"][0]["w_up"][2][5]),
        ("w_down[4][1]", model.params["layers"][0]["w_down"][4], 1, grads["layers"][0]["w_down"][4][1]),
        ("gamma1[0]", model.params["layers"][0]["gamma1"], 0, grads["layers"][0]["gamma1"][0]),
        ("lm_head_w[2][67]", model.params["lm_head_w"][2], 67, grads["lm_head_w"][2][67]),
    ]

    max_rel_err = 0.0
    checks = []
    for name, vec, idx, anal_grad in probes:
        orig = vec[idx]
        vec[idx] = orig + eps
        l_plus, _, _ = model.forward_loss_and_backward(inp, tgt)
        vec[idx] = orig - eps
        l_minus, _, _ = model.forward_loss_and_backward(inp, tgt)
        vec[idx] = orig
        num_grad = (l_plus - l_minus) / (2.0 * eps)
        denom = max(1e-7, abs(num_grad) + abs(anal_grad))
        rel_err = abs(num_grad - anal_grad) / denom
        if rel_err > max_rel_err:
            max_rel_err = rel_err
        checks.append((name, round(anal_grad, 6), round(num_grad, 6), round(rel_err, 8)))

    return {
        "passed": max_rel_err < 1e-4,
        "max_relative_error": max_rel_err,
        "probes": checks,
    }
