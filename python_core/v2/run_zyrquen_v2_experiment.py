from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path
from typing import Any, List, Tuple

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from native_neural import NativeTransformerLM, _adamw_step, _grad_l2_norm  # noqa: E402
from native_tokenizer import NativeBPETokenizer  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
    verify_v2_gradients,
)
from v2.zyrquen_v2_trainer import (  # noqa: E402
    IGNORE_INDEX,
    ApprovalGate,
    ByteTokenizer,
    CodingTask,
    ContinualTrainerV2,
    EvalReport,
    SandboxEvaluator,
    detect_task_leakage,
    record_checkpoint_approval,
)


def build_leak_free_datasets() -> (
    Tuple[List[str], List[str], List[CodingTask], List[CodingTask]]
):
    """Build strictly disjoint train vs unseen evaluation task families (zero leakage)."""
    phase1_train = [
        "def add_nums(a, b):\n    return a + b\n",
        "def is_even(n):\n    return n % 2 == 0\n",
        "def clamp_val(x, lo, hi):\n    return max(lo, min(hi, x))\n",
    ]
    phase2_train = [
        "def safe_ratio(a, b):\n    return 0.0 if b == 0 else a / b\n",
        "def count_vowels(s):\n    return sum(1 for ch in s.lower() if ch in 'aeiou')\n",
        "def reverse_words(text):\n    return ' '.join(reversed(text.split()))\n",
    ]
    regression_tasks = [
        CodingTask(
            task_id="reg_add",
            family="arithmetic",
            prompt="def add_nums(a, b):\n    return ",
            reference_solution="def add_nums(a, b):\n    return a + b\n",
            test_code="assert add_nums(2, 3) == 5",
            category="regression",
        ),
        CodingTask(
            task_id="reg_even",
            family="parity",
            prompt="def is_even(n):\n    return ",
            reference_solution="def is_even(n):\n    return n % 2 == 0\n",
            test_code="assert is_even(4) is True and is_even(5) is False",
            category="regression",
        ),
    ]
    unseen_tasks = [
        CodingTask(
            task_id="unseen_avg",
            family="empty_safe_mean",
            prompt="def avg_or_zero(vals):\n    return ",
            reference_solution="def avg_or_zero(vals):\n    return sum(vals) / len(vals) if vals else 0.0\n",
            test_code="assert abs(avg_or_zero([2.0, 4.0, 6.0]) - 4.0) < 1e-6 and avg_or_zero([]) == 0.0",
            category="unseen",
        ),
        CodingTask(
            task_id="unseen_dedup_sort",
            family="dedup_order",
            prompt="def distinct_ordered(seq):\n    return ",
            reference_solution="def distinct_ordered(seq):\n    return sorted(set(seq))\n",
            test_code="assert distinct_ordered([3, 1, 2, 1]) == [1, 2, 3]",
            category="unseen",
        ),
    ]
    return phase1_train, phase2_train, regression_tasks, unseen_tasks


def _run_pure_python_experiment(
    p1_train: List[str],
    p2_train: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[dict],
) -> int:
    grad_check = verify_v2_gradients()
    run_stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    work_dir = Path("/tmp/zyrquen_v2_exp") / f"pure_{run_stamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Baseline V1 (NativeTransformerLM: Learned PosEmb, d_model=16, 1 layer, cold optimizer restart)
    v1_tok = NativeBPETokenizer.train(
        p1_train + p2_train, target_vocab_size=290, min_pair_freq=2, version=1
    )
    v1_model = NativeTransformerLM(
        vocab_size=v1_tok.vocab_size,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        max_seq_len=64,
        seed=42,
    )

    def _train_v1_cold_phase(texts: List[str], steps: int, seed: int) -> None:
        m_st = v1_model.zero_grads()
        v_st = v1_model.zero_grads()
        rng = random.Random(seed)
        seqs = [
            v1_tok.encode(t, add_bos=True, add_eos=True)[:64] for t in texts
        ]
        for step in range(1, steps + 1):
            seq = rng.choice(seqs)
            if len(seq) < 2:
                continue
            _, _, g = v1_model.forward_loss_and_backward(seq[:-1], seq[1:])
            gn = _grad_l2_norm(g, 1.0)
            clip = min(1.0, 1.0 / gn) if gn > 1.0 and gn > 0.0 else 1.0
            _adamw_step(
                v1_model.params,
                g,
                m_st,
                v_st,
                lr=0.008,
                beta1=0.9,
                beta2=0.95,
                eps=1e-8,
                weight_decay=0.01,
                step_num=step,
                grad_scale=1.0,
                clip_scale=clip,
            )

    _train_v1_cold_phase(p1_train, steps=45, seed=42)
    # V1 cold-starts optimizer in Phase 2 (no optimizer state resume, no replay/consolidation)
    _train_v1_cold_phase(p2_train, steps=45, seed=43)

    def v1_gen(prompt: str) -> str:
        res = v1_model.generate_continuation(
            v1_tok, prompt, max_new_tokens=32, min_confidence=0.0
        )
        cont = res.get("generated") or ""
        return prompt + cont

    def v1_loss(texts: List[str]) -> float:
        seqs = [v1_tok.encode(t, add_bos=True, add_eos=True)[:64] for t in texts]
        return float(v1_model.evaluate_sequences(seqs)["loss"])

    base_eval = SandboxEvaluator(generate_fn=v1_gen, loss_fn=v1_loss)
    base_reg_rep = base_eval.evaluate(reg_tasks)
    base_unseen_rep = base_eval.evaluate(unseen_tasks)

    # 2. Candidate V2 (PureNativeTransformerLMV2: RoPE + SwiGLU + NTK context extension + full resume)
    tok_v2 = ByteTokenizer()
    cfg_v2 = PureZyrquenV2Config(
        vocab_size=tok_v2.vocab_size,
        d_model=24,
        n_heads=2,
        n_layers=2,
        d_ff=48,
        base_seq_len=64,
        max_seq_len=128,
        seed=42,
    )
    trainer = PureContinualTrainerV2(
        model=PureNativeTransformerLMV2(cfg_v2),
        tokenizer=tok_v2,
        lr=0.015,
        total_decay_steps=60,
        consolidation_lambda=0.02,
        seed=42,
    )
    p1_stats = trainer.train_steps(p1_train, steps=20, batch_size=2, replay_ratio=0.0)
    trainer.snapshot_consolidation_state(p1_train)
    ckpt_p1, sha_p1 = trainer.save_checkpoint(work_dir / "cand_phase1.json.gz")

    resumed_trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1, tokenizer=tok_v2, expected_sha256=sha_p1, resume_optimizer=True
    )
    resumed_trainer.model.extend_context(256)
    p2_stats = resumed_trainer.train_steps(
        p2_train, steps=25, batch_size=2, replay_ratio=0.5
    )
    ckpt_p2, sha_p2 = resumed_trainer.save_checkpoint(work_dir / "cand_phase2.json.gz")

    # Verify V2 handles long context > V1's 64-token ceiling via NTK-scaled RoPE
    long_probe_ids = tok_v2.encode(("x = 1\n" * 20), add_eos=False)[:80]
    long_logits, _ = resumed_trainer.model.forward(long_probe_ids, record_cache=False)
    long_ctx_ok = len(long_logits) == len(long_probe_ids) and len(long_probe_ids) > 64

    cand_eval = SandboxEvaluator(
        generate_fn=lambda prompt: resumed_trainer.model.generate_text(
            tok_v2, prompt, max_new_tokens=36
        ),
        loss_fn=lambda texts: float(
            resumed_trainer.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    cand_reg_rep = cand_eval.evaluate(reg_tasks)
    cand_unseen_rep = cand_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)
    decision = gate.evaluate(
        baseline_unseen=base_unseen_rep,
        candidate_unseen=cand_unseen_rep,
        baseline_regression=base_reg_rep,
        candidate_regression=cand_reg_rep,
        leakage_count=len(leaks),
    )
    approval = record_checkpoint_approval(
        ckpt_p2, sha_p2, decision, metadata={"backend": "pure_python_3.11_stdlib"}
    )

    print("=== ZYRQUEN V2 EXPERIMENT REPORT ===", flush=True)
    print("Runtime Backend : pure_python_3.11_stdlib (PyTorch unavailable in container)", flush=True)
    print(
        f"RoPE Backprop   : grad_check_passed={grad_check['passed']} "
        f"(max_rel_err={grad_check['max_relative_error']:.2e})",
        flush=True,
    )
    print(
        f"Optimizer Resume: phase1_step={p1_stats['global_step']} -> "
        f"phase2_step={p2_stats['global_step']} (m/v state + replay restored)",
        flush=True,
    )
    print(
        f"Context Scaling : v1_cap=64 -> v2_max_seq_len={resumed_trainer.model.cfg.max_seq_len} "
        f"(long_probe_{len(long_probe_ids)}tok_ok={long_ctx_ok})",
        flush=True,
    )
    print(f"Leakage Check   : {len(leaks)} leaks", flush=True)
    print(
        f"Baseline  (V1)  | Reg Loss: {base_reg_rep.avg_loss:.4f} | Reg Pass: {base_reg_rep.exec_pass_rate:.2f} "
        f"| Unseen Loss: {base_unseen_rep.avg_loss:.4f} | Unseen Pass: {base_unseen_rep.exec_pass_rate:.2f} "
        f"| Unseen Errors: {base_unseen_rep.error_breakdown}",
        flush=True,
    )
    print(
        f"Candidate (V2)  | Reg Loss: {cand_reg_rep.avg_loss:.4f} | Reg Pass: {cand_reg_rep.exec_pass_rate:.2f} "
        f"| Unseen Loss: {cand_unseen_rep.avg_loss:.4f} | Unseen Pass: {cand_unseen_rep.exec_pass_rate:.2f} "
        f"| Unseen Errors: {cand_unseen_rep.error_breakdown}",
        flush=True,
    )
    print(f"Checkpoint saved: {ckpt_p2} (sha256:{sha_p2[:16]}...)", flush=True)
    print(
        f"Approval Gate   | Approved: {approval['approved']} ({approval['status']}) | Reason: {decision.reason}",
        flush=True,
    )
    return 0


def _run_pytorch_experiment(
    p1_train: List[str],
    p2_train: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[dict],
) -> int:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config

    class TinyBaselineLM(nn.Module):
        def __init__(
            self, vocab_size: int = 258, d_model: int = 16, max_seq_len: int = 256
        ) -> None:
            super().__init__()
            self.max_seq_len = max_seq_len
            self.tok_emb = nn.Embedding(vocab_size, d_model, padding_idx=256)
            self.pos_emb = nn.Embedding(max_seq_len, d_model)
            enc_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=2,
                dim_feedforward=32,
                dropout=0.0,
                batch_first=True,
            )
            self.enc = nn.TransformerEncoder(enc_layer, num_layers=1)
            self.head = nn.Linear(d_model, vocab_size, bias=False)

        def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
            seq_len = min(input_ids.shape[1], self.max_seq_len)
            x = input_ids[:, :seq_len]
            pos = torch.arange(seq_len, device=x.device).unsqueeze(0)
            h = self.tok_emb(x) + self.pos_emb(pos)
            mask = nn.Transformer.generate_square_subsequent_mask(
                seq_len, device=x.device
            )
            out = self.enc(h, mask=mask, is_causal=True)
            return self.head(out)

    from v2.tpu_backend import resolve_torch_device

    torch.manual_seed(42)
    device = resolve_torch_device()
    tok = ByteTokenizer()
    run_stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    work_dir = Path("/tmp/zyrquen_v2_exp") / f"torch_{run_stamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    def _completion_loss(forward_fn, texts: List[str], max_len: int) -> float:
        losses: List[float] = []
        for t in texts:
            ids = tok.encode(t, add_eos=True)[:max_len]
            if len(ids) < 2:
                continue
            x = torch.tensor([ids[:-1]], dtype=torch.long, device=device)
            y = torch.tensor(
                [[tid if tid != tok.pad_id else IGNORE_INDEX for tid in ids[1:]]],
                dtype=torch.long,
                device=device,
            )
            logits = forward_fn(x)
            losses.append(
                float(
                    F.cross_entropy(
                        logits.reshape(-1, logits.shape[-1]),
                        y.reshape(-1),
                        ignore_index=IGNORE_INDEX,
                    ).item()
                )
            )
        return sum(losses) / max(len(losses), 1)

    base_model = TinyBaselineLM(
        vocab_size=tok.vocab_size, d_model=16, max_seq_len=256
    ).to(device)
    base_opt = torch.optim.AdamW(base_model.parameters(), lr=1e-3)
    for _ in range(80):
        for sample in p1_train + p2_train:
            ids = tok.encode(sample, add_eos=True)[:256]
            x = torch.tensor([ids[:-1]], device=device)
            y = torch.tensor([ids[1:]], device=device)
            base_opt.zero_grad()
            loss = F.cross_entropy(
                base_model(x).reshape(-1, tok.vocab_size), y.reshape(-1)
            )
            loss.backward()
            base_opt.step()

    def base_gen(prompt: str) -> str:
        ids = tok.encode(prompt)[:200]
        cur = torch.tensor([ids], device=device)
        base_model.eval()
        with torch.no_grad():
            for _ in range(64):
                nxt = torch.argmax(base_model(cur)[:, -1, :], dim=-1, keepdim=True)
                cur = torch.cat([cur, nxt], dim=-1)
                if int(nxt.item()) == tok.eos_id:
                    break
        return tok.decode(cur[0].tolist())

    base_eval = SandboxEvaluator(
        generate_fn=base_gen,
        loss_fn=lambda texts: _completion_loss(base_model, texts, 256),
    )
    base_reg_rep = base_eval.evaluate(reg_tasks)
    base_unseen_rep = base_eval.evaluate(unseen_tasks)

    cfg = ZyrquenV2Config(
        vocab_size=tok.vocab_size,
        d_model=128,
        n_heads=4,
        n_layers=4,
        d_ff=384,
        base_seq_len=256,
        max_seq_len=512,
        dropout=0.02,
    )
    trainer = ContinualTrainerV2(
        model=NativeTransformerLMV2(cfg),
        tokenizer=tok,
        lr=8e-4,
        consolidation_lambda=0.02,
        device=device,
    )
    p1_stats = trainer.train_steps(p1_train, steps=120, batch_size=3, replay_ratio=0.0)
    trainer.snapshot_consolidation_state(p1_train, batch_size=3)
    ckpt_p1, sha_p1 = trainer.save_checkpoint(work_dir / "cand_phase1.pt")

    resumed_trainer = ContinualTrainerV2.load_checkpoint(
        ckpt_p1, tokenizer=tok, expected_sha256=sha_p1, resume_optimizer=True, device=device
    )
    resumed_trainer.model.extend_context(1024)
    p2_stats = resumed_trainer.train_steps(
        p2_train, steps=140, batch_size=3, replay_ratio=0.5
    )
    ckpt_p2, sha_p2 = resumed_trainer.save_checkpoint(work_dir / "cand_phase2.pt")

    def cand_gen(prompt: str) -> str:
        ids = tok.encode(prompt)[:512]
        cur = torch.tensor([ids], device=device)
        out_ids = resumed_trainer.model.generate(
            cur, max_new_tokens=64, temperature=0.0
        )[0].tolist()
        return tok.decode(out_ids)

    cand_eval = SandboxEvaluator(
        generate_fn=cand_gen,
        loss_fn=lambda texts: _completion_loss(resumed_trainer.model, texts, 512),
    )
    cand_reg_rep = cand_eval.evaluate(reg_tasks)
    cand_unseen_rep = cand_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)
    decision = gate.evaluate(
        baseline_unseen=base_unseen_rep,
        candidate_unseen=cand_unseen_rep,
        baseline_regression=base_reg_rep,
        candidate_regression=cand_reg_rep,
        leakage_count=len(leaks),
    )
    approval = record_checkpoint_approval(
        ckpt_p2, sha_p2, decision, metadata={"backend": f"pytorch ({device.type})"}
    )

    print("=== ZYRQUEN V2 EXPERIMENT REPORT ===")
    print(f"Runtime Backend : pytorch ({device.type})")
    print(
        f"Optimizer Resume: phase1_step={p1_stats['global_step']} -> "
        f"phase2_step={p2_stats['global_step']}"
    )
    print(f"Leakage Check   : {len(leaks)} leaks")
    print(
        f"Baseline  (V1)  | Reg Loss: {base_reg_rep.avg_loss:.4f} | Reg Pass: {base_reg_rep.exec_pass_rate:.2f} "
        f"| Unseen Loss: {base_unseen_rep.avg_loss:.4f} | Unseen Pass: {base_unseen_rep.exec_pass_rate:.2f} "
        f"| Unseen Errors: {base_unseen_rep.error_breakdown}"
    )
    print(
        f"Candidate (V2)  | Reg Loss: {cand_reg_rep.avg_loss:.4f} | Reg Pass: {cand_reg_rep.exec_pass_rate:.2f} "
        f"| Unseen Loss: {cand_unseen_rep.avg_loss:.4f} | Unseen Pass: {cand_unseen_rep.exec_pass_rate:.2f} "
        f"| Unseen Errors: {cand_unseen_rep.error_breakdown}"
    )
    print(f"Checkpoint saved: {ckpt_p2} (sha256:{sha_p2[:16]}...)")
    print(
        f"Approval Gate   | Approved: {approval['approved']} ({approval['status']}) | Reason: {decision.reason}"
    )
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run ZYRQUEN V2 Model-Centric Experiment")
    ap.add_argument(
        "--backend",
        choices=("auto", "pytorch", "pure"),
        default="auto",
        help="Select PyTorch or Pure-Python 3.11 stdlib V2 engine.",
    )
    args = ap.parse_args(argv)

    p1_train, p2_train, reg_tasks, unseen_tasks = build_leak_free_datasets()
    leaks = detect_task_leakage(p1_train + p2_train, unseen_tasks)
    if leaks:
        print(f"STATUS: BLOCKED — Data leakage detected in unseen tasks: {leaks}")
        return 1

    has_torch = False
    try:
        import torch  # noqa: F401

        has_torch = True
    except ModuleNotFoundError:
        has_torch = False

    if args.backend == "pytorch":
        if not has_torch:
            print("STATUS: BLOCKED — PyTorch ('torch') requested but not installed.")
            return 2
        return _run_pytorch_experiment(
            p1_train, p2_train, reg_tasks, unseen_tasks, leaks
        )

    if args.backend == "auto" and has_torch:
        return _run_pytorch_experiment(
            p1_train, p2_train, reg_tasks, unseen_tasks, leaks
        )

    return _run_pure_python_experiment(
        p1_train, p2_train, reg_tasks, unseen_tasks, leaks
    )


if __name__ == "__main__":
    raise SystemExit(main())
