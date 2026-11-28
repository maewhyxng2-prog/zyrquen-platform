#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Pure-Python Autoregressive Transformer Neural Engine (P2)
------------------------------------------------------------------------
100% Native Python 3.11 Standard Library implementation (zero external pretrained
models, zero PyTorch/NumPy dependency):
- Seeded Xavier/He Random Weight Initialization (never external weights)
- Token Embedding + Learned Positional Embedding
- Multi-Layer Causal Multi-Head Self-Attention (Q, K, V, O)
- RMSNorm + Residual Connections + SiLU Feed-Forward Network
- Autoregressive Cross-Entropy Loss + Exact Analytical Backpropagation
- Finite-Difference Gradient Verification Helper (`verify_gradients`)
- AdamW Optimizer + Gradient Accumulation + Gradient Clipping + Cosine LR Decay
- Versioned `.json.gz` Checkpoint Persistence & Honest Entropy Abstention
"""

from __future__ import annotations

import gzip
import json
import math
import random
from pathlib import Path
from typing import Any

from native_tokenizer import NativeBPETokenizer

try:
    from checkpoint_hash import save_checkpoint_sha256
except ImportError:
    from python_core.checkpoint_hash import save_checkpoint_sha256


def _zeros(n: int) -> list[float]:
    return [0.0] * n


def _zeros_2d(rows: int, cols: int) -> list[list[float]]:
    return [[0.0] * cols for _ in range(rows)]


def _randn_matrix(rows: int, cols: int, std: float, rng: random.Random) -> list[list[float]]:
    return [[rng.gauss(0.0, std) for _ in range(cols)] for _ in range(rows)]


def _rmsnorm_forward(x: list[list[float]], gamma: list[float], eps: float = 1e-5):
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
    dout: list[list[float]],
    gamma: list[float],
    cache: tuple[list[list[float]], list[float]],
    dgamma: list[float],
) -> list[list[float]]:
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
    x: list[list[float]],
    w: list[list[float]],
    b: list[float] | None = None,
) -> list[list[float]]:
    T = len(x)
    in_d = len(w)
    out_d = len(w[0])
    out = _zeros_2d(T, out_d)
    for t in range(T):
        xt = x[t]
        ot = out[t]
        if b is not None:
            for j in range(out_d):
                ot[j] = b[j]
        for i in range(in_d):
            xi = xt[i]
            if xi == 0.0:
                continue
            wi = w[i]
            for j in range(out_d):
                ot[j] += xi * wi[j]
    return out


def _linear_backward(
    dout: list[list[float]],
    x: list[list[float]],
    w: list[list[float]],
    dw: list[list[float]],
    db: list[float] | None = None,
) -> list[list[float]]:
    T = len(dout)
    in_d = len(w)
    out_d = len(w[0])
    dx = _zeros_2d(T, in_d)
    for t in range(T):
        dt = dout[t]
        xt = x[t]
        dxt = dx[t]
        if db is not None:
            for j in range(out_d):
                db[j] += dt[j]
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


def _silu(x: float) -> tuple[float, float]:
    if x >= 0:
        z = math.exp(-x)
        sig = 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        sig = z / (1.0 + z)
    val = x * sig
    deriv = sig * (1.0 + x * (1.0 - sig))
    return val, deriv


class NativeTransformerLM:
    """Random-initialized Autoregressive Causal Transformer LM."""

    def __init__(
        self,
        *,
        vocab_size: int,
        d_model: int = 32,
        n_heads: int = 4,
        n_layers: int = 2,
        d_ff: int = 64,
        max_seq_len: int = 48,
        seed: int = 42,
    ) -> None:
        if d_model % n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        self.config: dict[str, Any] = {
            "arch": "zyrquen_native_transformer_v1",
            "vocab_size": int(vocab_size),
            "d_model": int(d_model),
            "n_heads": int(n_heads),
            "n_layers": int(n_layers),
            "d_ff": int(d_ff),
            "max_seq_len": int(max_seq_len),
            "seed": int(seed),
            "initialized_from": "random_xavier_normal",
        }
        rng = random.Random(seed)
        V, D, M, F = vocab_size, d_model, max_seq_len, d_ff

        emb_std = 1.0 / math.sqrt(D)
        proj_std = 1.0 / math.sqrt(D)
        ff_std = 1.0 / math.sqrt(F)

        self.params: dict[str, Any] = {
            "tok_emb": _randn_matrix(V, D, emb_std, rng),
            "pos_emb": _randn_matrix(M, D, emb_std, rng),
            "layers": [],
            "final_gamma": [1.0] * D,
            "lm_head_w": _randn_matrix(D, V, proj_std, rng),
            "lm_head_b": _zeros(V),
        }

        for _ in range(n_layers):
            self.params["layers"].append(
                {
                    "gamma1": [1.0] * D,
                    "wq": _randn_matrix(D, D, proj_std, rng),
                    "wk": _randn_matrix(D, D, proj_std, rng),
                    "wv": _randn_matrix(D, D, proj_std, rng),
                    "wo": _randn_matrix(D, D, proj_std / math.sqrt(2 * n_layers), rng),
                    "gamma2": [1.0] * D,
                    "w1": _randn_matrix(D, F, proj_std, rng),
                    "b1": _zeros(F),
                    "w2": _randn_matrix(F, D, ff_std / math.sqrt(2 * n_layers), rng),
                    "b2": _zeros(D),
                }
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

    def zero_grads(self) -> dict[str, Any]:
        V = self.config["vocab_size"]
        D = self.config["d_model"]
        M = self.config["max_seq_len"]
        F = self.config["d_ff"]
        L = self.config["n_layers"]
        return {
            "tok_emb": _zeros_2d(V, D),
            "pos_emb": _zeros_2d(M, D),
            "layers": [
                {
                    "gamma1": _zeros(D),
                    "wq": _zeros_2d(D, D),
                    "wk": _zeros_2d(D, D),
                    "wv": _zeros_2d(D, D),
                    "wo": _zeros_2d(D, D),
                    "gamma2": _zeros(D),
                    "w1": _zeros_2d(D, F),
                    "b1": _zeros(F),
                    "w2": _zeros_2d(F, D),
                    "b2": _zeros(D),
                }
                for _ in range(L)
            ],
            "final_gamma": _zeros(D),
            "lm_head_w": _zeros_2d(D, V),
            "lm_head_b": _zeros(V),
        }

    def forward(
        self,
        token_ids: list[int],
        *,
        record_cache: bool = False,
    ) -> tuple[list[list[float]], dict[str, Any] | None]:
        T = min(len(token_ids), self.config["max_seq_len"])
        ids = token_ids[:T]
        D = self.config["d_model"]
        H = self.config["n_heads"]
        dh = D // H
        scale = 1.0 / math.sqrt(dh)

        tok_emb = self.params["tok_emb"]
        pos_emb = self.params["pos_emb"]
        h = [[tok_emb[ids[t]][d] + pos_emb[t][d] for d in range(D)] for t in range(T)]

        layer_caches: list[dict[str, Any]] = []
        for lyr in self.params["layers"]:
            norm1, rms1_cache = _rmsnorm_forward(h, lyr["gamma1"])
            Q = _linear_forward(norm1, lyr["wq"])
            K = _linear_forward(norm1, lyr["wk"])
            V_mat = _linear_forward(norm1, lyr["wv"])

            ctx = _zeros_2d(T, D)
            attn_weights: list[list[list[float]]] = []
            for hd in range(H):
                off = hd * dh
                hd_w: list[list[float]] = []
                for t in range(T):
                    scores: list[float] = []
                    max_s = -1e30
                    qt = Q[t]
                    for s in range(t + 1):
                        ks = K[s]
                        dot = sum(qt[off + k] * ks[off + k] for k in range(dh)) * scale
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
            ff_pre = _linear_forward(norm2, lyr["w1"], lyr["b1"])
            F = len(lyr["b1"])
            ff_act = _zeros_2d(T, F)
            ff_deriv = _zeros_2d(T, F)
            for t in range(T):
                for j in range(F):
                    val, dv = _silu(ff_pre[t][j])
                    ff_act[t][j] = val
                    ff_deriv[t][j] = dv
            ff_out = _linear_forward(ff_act, lyr["w2"], lyr["b2"])
            h = [[h_mid[t][d] + ff_out[t][d] for d in range(D)] for t in range(T)]

            if record_cache:
                layer_caches.append(
                    {
                        "norm1": norm1,
                        "rms1_cache": rms1_cache,
                        "Q": Q,
                        "K": K,
                        "V": V_mat,
                        "ctx": ctx,
                        "attn_weights": attn_weights,
                        "norm2": norm2,
                        "rms2_cache": rms2_cache,
                        "ff_act": ff_act,
                        "ff_deriv": ff_deriv,
                    }
                )

        h_final, final_rms_cache = _rmsnorm_forward(h, self.params["final_gamma"])
        logits = _linear_forward(h_final, self.params["lm_head_w"], self.params["lm_head_b"])

        if not record_cache:
            return logits, None
        return logits, {
            "ids": ids,
            "h_final": h_final,
            "final_rms_cache": final_rms_cache,
            "layer_caches": layer_caches,
        }

    def forward_loss_and_backward(
        self,
        input_ids: list[int],
        target_ids: list[int],
        grads: dict[str, Any] | None = None,
    ) -> tuple[float, int, dict[str, Any]]:
        if grads is None:
            grads = self.zero_grads()
        T = min(len(input_ids), len(target_ids), self.config["max_seq_len"])
        if T <= 0:
            return 0.0, 0, grads

        logits, cache = self.forward(input_ids[:T], record_cache=True)
        assert cache is not None
        V = self.config["vocab_size"]
        D = self.config["d_model"]
        H = self.config["n_heads"]
        dh = D // H
        scale = 1.0 / math.sqrt(dh)

        dlogits = _zeros_2d(T, V)
        total_loss = 0.0
        correct = 0
        inv_T = 1.0 / T
        for t in range(T):
            lt = logits[t]
            max_l = max(lt)
            exps = [math.exp(v - max_l) for v in lt]
            denom = sum(exps) or 1.0
            probs = [e / denom for e in exps]
            tgt = target_ids[t]
            pred = max(range(V), key=lambda idx: probs[idx])
            if pred == tgt:
                correct += 1
            total_loss += -math.log(max(probs[tgt], 1e-12))
            dt = dlogits[t]
            for v in range(V):
                dt[v] = (probs[v] - (1.0 if v == tgt else 0.0)) * inv_T

        dh_final = _linear_backward(
            dlogits,
            cache["h_final"],
            self.params["lm_head_w"],
            grads["lm_head_w"],
            grads["lm_head_b"],
        )
        dh_curr = _rmsnorm_backward(
            dh_final,
            self.params["final_gamma"],
            cache["final_rms_cache"],
            grads["final_gamma"],
        )

        for l_idx in range(self.config["n_layers"] - 1, -1, -1):
            lyr = self.params["layers"][l_idx]
            g_lyr = grads["layers"][l_idx]
            lc = cache["layer_caches"][l_idx]

            # FFN residual backward
            dff_act = _linear_backward(dh_curr, lc["ff_act"], lyr["w2"], g_lyr["w2"], g_lyr["b2"])
            F = len(lyr["b1"])
            dff_pre = [[dff_act[t][j] * lc["ff_deriv"][t][j] for j in range(F)] for t in range(T)]
            dnorm2 = _linear_backward(dff_pre, lc["norm2"], lyr["w1"], g_lyr["w1"], g_lyr["b1"])
            dh_mid = _rmsnorm_backward(dnorm2, lyr["gamma2"], lc["rms2_cache"], g_lyr["gamma2"])
            for t in range(T):
                for d in range(D):
                    dh_mid[t][d] += dh_curr[t][d]

            # Attention residual backward
            dctx = _linear_backward(dh_mid, lc["ctx"], lyr["wo"], g_lyr["wo"])
            dQ = _zeros_2d(T, D)
            dK = _zeros_2d(T, D)
            dV = _zeros_2d(T, D)
            Q, K, V_mat = lc["Q"], lc["K"], lc["V"]

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
                            g_c = dct[off + k]
                            acc += g_c * vs[off + k]
                            dvs[off + k] += pr * g_c
                        d_att[s] = acc
                    dot_ap = sum(d_att[s] * probs[s] for s in range(t + 1))
                    qt = Q[t]
                    dqt = dQ[t]
                    for s in range(t + 1):
                        d_score = probs[s] * (d_att[s] - dot_ap) * scale
                        ks = K[s]
                        dks = dK[s]
                        for k in range(dh):
                            dqt[off + k] += d_score * ks[off + k]
                            dks[off + k] += d_score * qt[off + k]

            dn1_q = _linear_backward(dQ, lc["norm1"], lyr["wq"], g_lyr["wq"])
            dn1_k = _linear_backward(dK, lc["norm1"], lyr["wk"], g_lyr["wk"])
            dn1_v = _linear_backward(dV, lc["norm1"], lyr["wv"], g_lyr["wv"])
            dnorm1 = [
                [dn1_q[t][d] + dn1_k[t][d] + dn1_v[t][d] for d in range(D)]
                for t in range(T)
            ]
            dh_attn = _rmsnorm_backward(dnorm1, lyr["gamma1"], lc["rms1_cache"], g_lyr["gamma1"])
            dh_curr = [[dh_mid[t][d] + dh_attn[t][d] for d in range(D)] for t in range(T)]

        # Embedding gradients
        ids = cache["ids"]
        g_tok = grads["tok_emb"]
        g_pos = grads["pos_emb"]
        for t in range(T):
            tid = ids[t]
            dt = dh_curr[t]
            gt = g_tok[tid]
            gp = g_pos[t]
            for d in range(D):
                gt[d] += dt[d]
                gp[d] += dt[d]

        return total_loss * inv_T, correct, grads

    def evaluate_sequences(self, sequences: list[list[int]]) -> dict[str, Any]:
        total_loss = 0.0
        total_tokens = 0
        total_correct = 0
        max_len = self.config["max_seq_len"]
        V = self.config["vocab_size"]
        for seq in sequences:
            if len(seq) < 2:
                continue
            inp = seq[:-1][:max_len]
            tgt = seq[1 : len(inp) + 1]
            T = len(inp)
            logits, _ = self.forward(inp, record_cache=False)
            for t in range(T):
                lt = logits[t]
                max_l = max(lt)
                exps = [math.exp(v - max_l) for v in lt]
                denom = sum(exps) or 1.0
                probs = [e / denom for e in exps]
                y = tgt[t]
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

    def generate_continuation(
        self,
        tokenizer: NativeBPETokenizer,
        prompt: str,
        *,
        max_new_tokens: int = 16,
        min_confidence: float = 0.06,
    ) -> dict[str, Any]:
        ids = tokenizer.encode(prompt, add_bos=True, add_eos=False)
        if not ids:
            return {"generated": None, "reason": "empty_tokens"}
        max_len = self.config["max_seq_len"]
        generated_ids: list[int] = []
        confidences: list[float] = []
        cur_ids = ids[-max_len:]

        for _ in range(max_new_tokens):
            logits, _ = self.forward(cur_ids[-max_len:], record_cache=False)
            last_lt = logits[-1]
            max_l = max(last_lt)
            exps = [math.exp(v - max_l) for v in last_lt]
            denom = sum(exps) or 1.0
            probs = [e / denom for e in exps]
            best_id = max(range(len(probs)), key=lambda i: probs[i])
            best_prob = probs[best_id]
            if not generated_ids and best_prob < min_confidence:
                return {
                    "generated": None,
                    "reason": "low_confidence",
                    "top_prob": round(best_prob, 4),
                }
            if best_id == tokenizer.eos_id or best_id == tokenizer.pad_id:
                break
            generated_ids.append(best_id)
            confidences.append(best_prob)
            cur_ids.append(best_id)
            if len(generated_ids) >= 3 and generated_ids[-1] == generated_ids[-2] == generated_ids[-3]:
                break

        text = tokenizer.decode(generated_ids, skip_special=True).strip()
        if not text:
            return {"generated": None, "reason": "empty_generation"}
        return {
            "generated": text,
            "tokens_generated": len(generated_ids),
            "mean_confidence": round(sum(confidences) / max(1, len(confidences)), 4),
        }

    def to_dict(self, tokenizer: NativeBPETokenizer | None = None, metrics: dict | None = None) -> dict[str, Any]:
        return {
            "config": self.config,
            "param_count": self.parameter_count(),
            "params": self.params,
            "tokenizer": tokenizer.to_dict() if tokenizer else None,
            "metrics": metrics or {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NativeTransformerLM":
        cfg = data["config"]
        model = cls(
            vocab_size=cfg["vocab_size"],
            d_model=cfg["d_model"],
            n_heads=cfg["n_heads"],
            n_layers=cfg["n_layers"],
            d_ff=cfg["d_ff"],
            max_seq_len=cfg["max_seq_len"],
            seed=cfg.get("seed", 42),
        )
        model.params = data["params"]
        return model

    def save_checkpoint(
        self,
        path: Path,
        tokenizer: NativeBPETokenizer,
        metrics: dict[str, Any] | None = None,
    ) -> tuple[Path, str]:
        ckpt_path = Path(path)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(tokenizer=tokenizer, metrics=metrics), ensure_ascii=False).encode("utf-8")
        with gzip.open(ckpt_path, "wb") as f:
            f.write(payload)
        _, digest = save_checkpoint_sha256(ckpt_path)
        return ckpt_path, digest

    @classmethod
    def load_checkpoint(cls, path: Path) -> tuple["NativeTransformerLM", NativeBPETokenizer, dict[str, Any]]:
        with gzip.open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        model = cls.from_dict(data)
        tok = NativeBPETokenizer.from_dict(data["tokenizer"])
        return model, tok, data.get("metrics") or {}


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
                    p[i] = p[i] * (1.0 - lr * weight_decay) - lr * (m_hat / (math.sqrt(v_hat) + eps))

    _walk(params, grads, m_state, v_state)


def _grad_l2_norm(grads: Any, grad_scale: float) -> float:
    sq_sum = 0.0

    def _walk(g: Any) -> None:
        nonlocal sq_sum
        if isinstance(g, dict):
            for val in g.values():
                _walk(val)
        elif isinstance(g, list):
            if g and isinstance(g[0], float):
                for v in g:
                    gv = v * grad_scale
                    sq_sum += gv * gv
            else:
                for item in g:
                    _walk(item)

    _walk(grads)
    return math.sqrt(sq_sum)


def train_neural_model(
    train_lines: list[str],
    val_lines: list[str],
    test_lines: list[str],
    *,
    d_model: int = 24,
    n_heads: int = 2,
    n_layers: int = 1,
    d_ff: int = 48,
    max_seq_len: int = 32,
    epochs: int = 8,
    lr: float = 0.015,
    grad_accum_steps: int = 2,
    max_grad_norm: float = 1.0,
    target_vocab_size: int = 340,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Full random-initialized autoregressive neural training pipeline:
    Tokenization -> Random Init -> Baseline Eval -> Forward/Loss/Backprop ->
    Grad Accum + Clip + AdamW + Cosine LR -> Held-Out Eval.
    """
    tokenizer = NativeBPETokenizer.train(
        train_lines,
        target_vocab_size=target_vocab_size,
        min_pair_freq=2,
        version=1,
    )
    tok_metrics = tokenizer.evaluate_corpus(train_lines)

    train_seqs = [tokenizer.encode(ln, add_bos=True, add_eos=True) for ln in train_lines if ln.strip()]
    val_seqs = [tokenizer.encode(ln, add_bos=True, add_eos=True) for ln in val_lines if ln.strip()]
    test_seqs = [tokenizer.encode(ln, add_bos=True, add_eos=True) for ln in test_lines if ln.strip()]

    model = NativeTransformerLM(
        vocab_size=tokenizer.vocab_size,
        d_model=d_model,
        n_heads=n_heads,
        n_layers=n_layers,
        d_ff=d_ff,
        max_seq_len=max_seq_len,
        seed=seed,
    )

    init_train_eval = model.evaluate_sequences(train_seqs)
    init_val_eval = model.evaluate_sequences(val_seqs) if val_seqs else init_train_eval
    init_test_eval = model.evaluate_sequences(test_seqs) if test_seqs else init_val_eval

    m_state = model.zero_grads()
    v_state = model.zero_grads()
    rng = random.Random(seed)
    opt_step = 0
    total_opt_steps = max(1, (len(train_seqs) * epochs + grad_accum_steps - 1) // grad_accum_steps)
    history: list[dict[str, Any]] = []

    accum_grads = model.zero_grads()
    accum_count = 0

    for ep in range(1, epochs + 1):
        order = list(range(len(train_seqs)))
        rng.shuffle(order)
        ep_loss = 0.0
        ep_items = 0

        for idx in order:
            seq = train_seqs[idx]
            if len(seq) < 2:
                continue
            inp = seq[:-1][:max_seq_len]
            tgt = seq[1 : len(inp) + 1]
            loss_val, _, accum_grads = model.forward_loss_and_backward(inp, tgt, grads=accum_grads)
            if math.isnan(loss_val) or math.isinf(loss_val):
                return {"ok": False, "error": "Training halted: NaN/Inf loss detected"}
            ep_loss += loss_val
            ep_items += 1
            accum_count += 1

            if accum_count >= grad_accum_steps:
                opt_step += 1
                g_scale = 1.0 / accum_count
                gnorm = _grad_l2_norm(accum_grads, g_scale)
                clip_scale = min(1.0, max_grad_norm / gnorm) if gnorm > max_grad_norm and gnorm > 0 else 1.0
                # Cosine LR decay with 10% linear warmup
                warmup = max(1, int(0.1 * total_opt_steps))
                if opt_step <= warmup:
                    cur_lr = lr * (opt_step / warmup)
                else:
                    prog = min(1.0, (opt_step - warmup) / max(1, total_opt_steps - warmup))
                    cur_lr = lr * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * prog)))
                _adamw_step(
                    model.params,
                    accum_grads,
                    m_state,
                    v_state,
                    lr=cur_lr,
                    beta1=0.9,
                    beta2=0.98,
                    eps=1e-8,
                    weight_decay=0.01,
                    step_num=opt_step,
                    grad_scale=g_scale,
                    clip_scale=clip_scale,
                )
                accum_grads = model.zero_grads()
                accum_count = 0

        if accum_count > 0:
            opt_step += 1
            g_scale = 1.0 / accum_count
            gnorm = _grad_l2_norm(accum_grads, g_scale)
            clip_scale = min(1.0, max_grad_norm / gnorm) if gnorm > max_grad_norm and gnorm > 0 else 1.0
            _adamw_step(
                model.params,
                accum_grads,
                m_state,
                v_state,
                lr=lr * 0.2,
                beta1=0.9,
                beta2=0.98,
                eps=1e-8,
                weight_decay=0.01,
                step_num=opt_step,
                grad_scale=g_scale,
                clip_scale=clip_scale,
            )
            accum_grads = model.zero_grads()
            accum_count = 0

        history.append(
            {
                "epoch": ep,
                "train_loss": round(ep_loss / max(1, ep_items), 4),
            }
        )

    final_train_eval = model.evaluate_sequences(train_seqs)
    final_val_eval = model.evaluate_sequences(val_seqs) if val_seqs else final_train_eval
    final_test_eval = model.evaluate_sequences(test_seqs) if test_seqs else final_val_eval

    return {
        "ok": True,
        "model": model,
        "tokenizer": tokenizer,
        "tokenizer_metrics": tok_metrics,
        "param_count": model.parameter_count(),
        "initial_train_loss": init_train_eval["loss"],
        "initial_val_loss": init_val_eval["loss"],
        "initial_test_loss": init_test_eval["loss"],
        "initial_test_perplexity": init_test_eval["perplexity"],
        "final_train_loss": final_train_eval["loss"],
        "final_val_loss": final_val_eval["loss"],
        "val_perplexity": final_val_eval["perplexity"],
        "test_loss": final_test_eval["loss"],
        "test_perplexity": final_test_eval["perplexity"],
        "test_accuracy": final_test_eval["accuracy"],
        "history": history,
    }


def verify_gradients(seed: int = 7) -> dict[str, Any]:
    """Finite-difference gradient verification against analytical backprop."""
    model = NativeTransformerLM(vocab_size=12, d_model=8, n_heads=2, n_layers=1, d_ff=16, max_seq_len=6, seed=seed)
    inp = [2, 4, 7, 5]
    tgt = [4, 7, 5, 3]
    _, _, grads = model.forward_loss_and_backward(inp, tgt)

    eps = 1e-5
    checks: list[tuple[str, float, float]] = []

    probes = [
        ("tok_emb[4][1]", model.params["tok_emb"][4], 1, grads["tok_emb"][4][1]),
        ("wq[0][2]", model.params["layers"][0]["wq"][0], 2, grads["layers"][0]["wq"][0][2]),
        ("w1[1][3]", model.params["layers"][0]["w1"][1], 3, grads["layers"][0]["w1"][1][3]),
        ("w2[2][1]", model.params["layers"][0]["w2"][2], 1, grads["layers"][0]["w2"][2][1]),
        ("gamma1[0]", model.params["layers"][0]["gamma1"], 0, grads["layers"][0]["gamma1"][0]),
        ("lm_head_w[2][5]", model.params["lm_head_w"][2], 5, grads["lm_head_w"][2][5]),
    ]

    max_rel_err = 0.0
    for name, vec, idx, anal_grad in probes:
        orig = vec[idx]
        vec[idx] = orig + eps
        l_plus, _, _ = model.forward_loss_and_backward(inp, tgt)
        vec[idx] = orig - eps
        l_minus, _, _ = model.forward_loss_and_backward(inp, tgt)
        vec[idx] = orig
        num_grad = (l_plus - l_minus) / (2 * eps)
        denom = max(1e-7, abs(num_grad) + abs(anal_grad))
        rel_err = abs(num_grad - anal_grad) / denom
        if rel_err > max_rel_err:
            max_rel_err = rel_err
        checks.append((name, round(anal_grad, 6), round(num_grad, 6)))

    return {
        "passed": max_rel_err < 1e-4,
        "max_relative_error": max_rel_err,
        "probes": checks,
    }
