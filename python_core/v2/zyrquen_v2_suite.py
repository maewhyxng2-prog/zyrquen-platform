"""ZYRQUEN V2 3-Arm Ablation Suite (Baseline V1 vs Candidate V2 Full vs Ablation V2).

Supports both:
- PyTorch backend (--backend pytorch, or auto when torch is installed; full d_model=192, 6 layers)
- Pure-Python 3.11 stdlib backend (--backend pure, or auto fallback when torch is unavailable)

Strictly enforces zero data leakage, SHA-256 checkpoint verification, and fail-closed ApprovalGate.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

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
    SandboxEvaluator,
    detect_task_leakage,
)


def default_output_root(name: str = "zyrquen_v2_run") -> Path:
    base = Path("/content") if Path("/content").exists() else Path("/tmp")
    return base / name


def build_ablation_datasets() -> (
    Tuple[List[str], List[str], List[CodingTask], List[CodingTask]]
):
    """Build strictly disjoint Phase-1, Phase-2, Retention (Reg), and Unseen evaluation sets."""
    phase1_texts = [
        "def add_nums(a, b):\n    return a + b\n",
        "def is_even(n):\n    return n % 2 == 0\n",
        "def clamp_val(x, lo, hi):\n    return max(lo, min(hi, x))\n",
    ]
    phase2_texts = [
        "def safe_ratio(a, b):\n    return 0.0 if b == 0 else a / b\n",
        "def count_vowels(s):\n    return sum(1 for ch in s.lower() if ch in 'aeiou')\n",
        "def reverse_words(text):\n    return ' '.join(reversed(text.split()))\n",
    ]
    retention_tasks = [
        CodingTask(
            task_id="ret_add",
            family="arithmetic",
            prompt="def add_nums(a, b):\n    return ",
            reference_solution="def add_nums(a, b):\n    return a + b\n",
            test_code="assert add_nums(7, 8) == 15",
            category="regression",
        ),
        CodingTask(
            task_id="ret_even",
            family="parity",
            prompt="def is_even(n):\n    return ",
            reference_solution="def is_even(n):\n    return n % 2 == 0\n",
            test_code="assert is_even(10) is True and is_even(9) is False",
            category="regression",
        ),
        CodingTask(
            task_id="ret_clamp",
            family="bounds",
            prompt="def clamp_val(x, lo, hi):\n    return ",
            reference_solution="def clamp_val(x, lo, hi):\n    return max(lo, min(hi, x))\n",
            test_code="assert clamp_val(15, 0, 10) == 10 and clamp_val(-2, 0, 10) == 0",
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
            test_code="assert distinct_ordered([4, 2, 4, 1]) == [1, 2, 4]",
            category="unseen",
        ),
        CodingTask(
            task_id="unseen_span",
            family="range_span",
            prompt="def diff_range(nums):\n    return ",
            reference_solution="def diff_range(nums):\n    return max(nums) - min(nums) if nums else 0\n",
            test_code="assert diff_range([3, 11, 2, 8]) == 9 and diff_range([]) == 0",
            category="unseen",
        ),
    ]
    return phase1_texts, phase2_texts, retention_tasks, unseen_tasks


def _run_pure_suite(
    p1_texts: List[str],
    p2_texts: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[Dict[str, str]],
    run_root: Path,
) -> Dict[str, Any]:
    t0 = time.time()
    grad_check = verify_v2_gradients()

    # --- Arm 1: Baseline V1 (NativeTransformerLM: Learned PosEmb, d_model=16, 1 layer, cold restart) ---
    v1_tok = NativeBPETokenizer.train(
        p1_texts + p2_texts, target_vocab_size=290, min_pair_freq=2, version=1
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

    def _train_v1_cold(texts: List[str], steps: int, seed: int) -> None:
        m_st = v1_model.zero_grads()
        v_st = v1_model.zero_grads()
        rng = random.Random(seed)
        seqs = [v1_tok.encode(t, add_bos=True, add_eos=True)[:64] for t in texts]
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

    _train_v1_cold(p1_texts, steps=18, seed=42)
    _train_v1_cold(p2_texts, steps=18, seed=43)

    base_eval = SandboxEvaluator(
        generate_fn=lambda prompt: prompt
        + (
            v1_model.generate_continuation(
                v1_tok, prompt, max_new_tokens=20, min_confidence=0.0
            ).get("generated")
            or ""
        ),
        loss_fn=lambda texts: float(
            v1_model.evaluate_sequences(
                [v1_tok.encode(t, add_bos=True, add_eos=True)[:64] for t in texts]
            )["loss"]
        ),
    )
    base_reg = base_eval.evaluate(reg_tasks)
    base_unseen = base_eval.evaluate(unseen_tasks)

    # --- Arm 2: Candidate V2 Full (RoPE + SwiGLU + NTK + Full Resume + Replay + Consolidation) ---
    tok_v2 = ByteTokenizer()
    cfg_v2 = PureZyrquenV2Config(
        vocab_size=tok_v2.vocab_size,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        base_seq_len=64,
        max_seq_len=128,
        seed=42,
    )
    trainer_full = PureContinualTrainerV2(
        model=PureNativeTransformerLMV2(cfg_v2),
        tokenizer=tok_v2,
        lr=0.015,
        total_decay_steps=40,
        consolidation_lambda=0.02,
        seed=42,
    )
    p1_stats = trainer_full.train_steps(p1_texts, steps=10, batch_size=2, replay_ratio=0.0)
    trainer_full.snapshot_consolidation_state(p1_texts)
    ckpt_p1, sha_p1 = trainer_full.save_checkpoint(run_root / "cand_full_p1.json.gz")

    resumed_full = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tokenizer=tok_v2,
        expected_sha256=sha_p1,
        resume_optimizer=True,
        restore_continual_state=True,
    )
    resumed_full.model.extend_context(256)
    p2_stats = resumed_full.train_steps(p2_texts, steps=10, batch_size=2, replay_ratio=0.5)
    ckpt_p2, sha_p2 = resumed_full.save_checkpoint(run_root / "cand_full_p2.json.gz")

    full_eval = SandboxEvaluator(
        generate_fn=lambda p: resumed_full.model.generate_text(
            tok_v2, p, max_new_tokens=20
        ),
        loss_fn=lambda texts: float(
            resumed_full.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    full_reg = full_eval.evaluate(reg_tasks)
    full_unseen = full_eval.evaluate(unseen_tasks)

    # --- Arm 3: Ablation V2 (Same V2 Architecture, NO optimizer resume, NO replay/consolidation) ---
    abl_trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tokenizer=tok_v2,
        expected_sha256=sha_p1,
        resume_optimizer=False,
        restore_continual_state=False,
        consolidation_lambda=0.0,
    )
    abl_trainer.model.extend_context(256)
    abl_stats = abl_trainer.train_steps(p2_texts, steps=10, batch_size=2, replay_ratio=0.0)
    ckpt_abl, sha_abl = abl_trainer.save_checkpoint(run_root / "ablation_v2_p2.json.gz")

    abl_eval = SandboxEvaluator(
        generate_fn=lambda p: abl_trainer.model.generate_text(
            tok_v2, p, max_new_tokens=20
        ),
        loss_fn=lambda texts: float(
            abl_trainer.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    abl_reg = abl_eval.evaluate(reg_tasks)
    abl_unseen = abl_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)
    full_gate = gate.evaluate(
        base_unseen, full_unseen, base_reg, full_reg, leakage_count=len(leaks)
    )
    abl_gate = gate.evaluate(
        base_unseen, abl_unseen, base_reg, abl_reg, leakage_count=len(leaks)
    )

    manifest = {
        "suite": "zyrquen_v2_ablation_suite",
        "backend": "pure_python_3.11_stdlib",
        "pytorch_available": False,
        "elapsed_sec": round(time.time() - t0, 2),
        "leakage_count": len(leaks),
        "rope_grad_check": {
            "passed": grad_check["passed"],
            "max_relative_error": grad_check["max_relative_error"],
        },
        "checkpoints": {
            "cand_full_p1": {"path": str(ckpt_p1), "sha256": sha_p1},
            "cand_full_p2": {"path": str(ckpt_p2), "sha256": sha_p2},
            "ablation_v2_p2": {"path": str(ckpt_abl), "sha256": sha_abl},
        },
        "training_steps": {
            "cand_full_p1_step": p1_stats["global_step"],
            "cand_full_p2_step": p2_stats["global_step"],
            "ablation_p2_step": abl_stats["global_step"],
        },
        "results": {
            "baseline_v1": {
                "reg_pass_rate": base_reg.exec_pass_rate,
                "reg_loss": base_reg.avg_loss,
                "unseen_pass_rate": base_unseen.exec_pass_rate,
                "unseen_loss": base_unseen.avg_loss,
            },
            "candidate_v2_full": {
                "reg_pass_rate": full_reg.exec_pass_rate,
                "reg_loss": full_reg.avg_loss,
                "unseen_pass_rate": full_unseen.exec_pass_rate,
                "unseen_loss": full_unseen.avg_loss,
                "gate": asdict(full_gate),
            },
            "ablation_v2_no_resume_no_replay": {
                "reg_pass_rate": abl_reg.exec_pass_rate,
                "reg_loss": abl_reg.avg_loss,
                "unseen_pass_rate": abl_unseen.exec_pass_rate,
                "unseen_loss": abl_unseen.avg_loss,
                "gate": asdict(abl_gate),
            },
        },
    }
    (run_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def _run_pytorch_suite(
    p1_texts: List[str],
    p2_texts: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[Dict[str, str]],
    run_root: Path,
) -> Dict[str, Any]:
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
            layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=2,
                dim_feedforward=32,
                dropout=0.0,
                batch_first=True,
            )
            self.enc = nn.TransformerEncoder(layer, num_layers=1)
            self.head = nn.Linear(d_model, vocab_size, bias=False)

        def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
            seq_len = min(input_ids.shape[1], self.max_seq_len)
            x = input_ids[:, :seq_len]
            pos = torch.arange(seq_len, device=x.device).unsqueeze(0)
            h = self.tok_emb(x) + self.pos_emb(pos)
            mask = nn.Transformer.generate_square_subsequent_mask(
                seq_len, device=x.device
            )
            return self.head(self.enc(h, mask=mask, is_causal=True))

    t0 = time.time()
    torch.manual_seed(42)
    random.seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = ByteTokenizer()

    def _loss_over_texts(
        forward_fn: Callable[[torch.Tensor], torch.Tensor], texts: List[str], max_len: int
    ) -> float:
        vals: List[float] = []
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
            vals.append(
                float(
                    F.cross_entropy(
                        logits.reshape(-1, logits.shape[-1]),
                        y.reshape(-1),
                        ignore_index=IGNORE_INDEX,
                    ).item()
                )
            )
        return round(sum(vals) / max(len(vals), 1), 4)

    # --- Arm 1: Baseline V1 (cold restart between phases) ---
    base_model = TinyBaselineLM(
        vocab_size=tok.vocab_size, d_model=16, max_seq_len=256
    ).to(device)
    for phase_texts in (p1_texts, p2_texts):
        base_opt = torch.optim.AdamW(base_model.parameters(), lr=1e-3)
        for _ in range(60):
            for s in phase_texts:
                ids = tok.encode(s, add_eos=True)[:256]
                if len(ids) < 2:
                    continue
                x = torch.tensor([ids[:-1]], device=device)
                y = torch.tensor([ids[1:]], device=device)
                base_opt.zero_grad()
                loss = F.cross_entropy(
                    base_model(x).reshape(-1, tok.vocab_size), y.reshape(-1)
                )
                loss.backward()
                base_opt.step()

    def base_gen(prompt: str) -> str:
        cur = torch.tensor([tok.encode(prompt)[:200]], device=device)
        base_model.eval()
        with torch.no_grad():
            for _ in range(72):
                nxt = torch.argmax(base_model(cur)[:, -1, :], dim=-1, keepdim=True)
                cur = torch.cat([cur, nxt], dim=-1)
                if int(nxt.item()) == tok.eos_id:
                    break
        return tok.decode(cur[0].tolist())

    base_eval = SandboxEvaluator(
        base_gen, lambda texts: _loss_over_texts(base_model, texts, 256)
    )
    base_reg = base_eval.evaluate(reg_tasks)
    base_unseen = base_eval.evaluate(unseen_tasks)

    # --- Arm 2: Candidate V2 Full ---
    cfg = ZyrquenV2Config(
        vocab_size=tok.vocab_size,
        d_model=192,
        n_heads=6,
        n_layers=6,
        d_ff=512,
        base_seq_len=256,
        max_seq_len=512,
        dropout=0.02,
    )
    trainer_full = ContinualTrainerV2(
        NativeTransformerLMV2(cfg),
        tok,
        lr=1e-3,
        total_decay_steps=450,
        consolidation_lambda=0.01,
        device=device,
    )
    p1_stats = trainer_full.train_steps(p1_texts, steps=180, batch_size=4, replay_ratio=0.0)
    trainer_full.snapshot_consolidation_state(p1_texts, batch_size=4)
    ckpt_p1, sha_p1 = trainer_full.save_checkpoint(run_root / "cand_full_p1.pt")

    resumed_full = ContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tok,
        expected_sha256=sha_p1,
        resume_optimizer=True,
        restore_continual_state=True,
        consolidation_lambda=0.01,
        device=device,
    )
    resumed_full.model.extend_context(1024)
    p2_stats = resumed_full.train_steps(p2_texts, steps=220, batch_size=4, replay_ratio=0.5)
    ckpt_p2, sha_p2 = resumed_full.save_checkpoint(run_root / "cand_full_p2.pt")

    def full_gen(prompt: str) -> str:
        cur = torch.tensor([tok.encode(prompt)[:512]], device=device)
        out = resumed_full.model.generate(cur, max_new_tokens=72, temperature=0.0)[0].tolist()
        return tok.decode(out)

    full_eval = SandboxEvaluator(
        full_gen, lambda texts: _loss_over_texts(resumed_full.model, texts, 1024)
    )
    full_reg = full_eval.evaluate(reg_tasks)
    full_unseen = full_eval.evaluate(unseen_tasks)

    # --- Arm 3: Ablation V2 (No Resume, No Replay, No Consolidation) ---
    abl_trainer = ContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tok,
        expected_sha256=sha_p1,
        resume_optimizer=False,
        restore_continual_state=False,
        consolidation_lambda=0.0,
        device=device,
    )
    abl_trainer.model.extend_context(1024)
    abl_stats = abl_trainer.train_steps(p2_texts, steps=220, batch_size=4, replay_ratio=0.0)
    ckpt_abl, sha_abl = abl_trainer.save_checkpoint(run_root / "ablation_v2_p2.pt")

    def abl_gen(prompt: str) -> str:
        cur = torch.tensor([tok.encode(prompt)[:512]], device=device)
        out = abl_trainer.model.generate(cur, max_new_tokens=72, temperature=0.0)[0].tolist()
        return tok.decode(out)

    abl_eval = SandboxEvaluator(
        abl_gen, lambda texts: _loss_over_texts(abl_trainer.model, texts, 1024)
    )
    abl_reg = abl_eval.evaluate(reg_tasks)
    abl_unseen = abl_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)
    full_gate = gate.evaluate(
        base_unseen, full_unseen, base_reg, full_reg, leakage_count=len(leaks)
    )
    abl_gate = gate.evaluate(
        base_unseen, abl_unseen, base_reg, abl_reg, leakage_count=len(leaks)
    )

    manifest = {
        "suite": "zyrquen_v2_ablation_suite",
        "backend": f"pytorch ({device.type})",
        "pytorch_available": True,
        "elapsed_sec": round(time.time() - t0, 2),
        "leakage_count": len(leaks),
        "checkpoints": {
            "cand_full_p1": {"path": str(ckpt_p1), "sha256": sha_p1},
            "cand_full_p2": {"path": str(ckpt_p2), "sha256": sha_p2},
            "ablation_v2_p2": {"path": str(ckpt_abl), "sha256": sha_abl},
        },
        "training_steps": {
            "cand_full_p1_step": p1_stats["global_step"],
            "cand_full_p2_step": p2_stats["global_step"],
            "ablation_p2_step": abl_stats["global_step"],
        },
        "results": {
            "baseline_v1": {
                "reg_pass_rate": base_reg.exec_pass_rate,
                "reg_loss": base_reg.avg_loss,
                "unseen_pass_rate": base_unseen.exec_pass_rate,
                "unseen_loss": base_unseen.avg_loss,
            },
            "candidate_v2_full": {
                "reg_pass_rate": full_reg.exec_pass_rate,
                "reg_loss": full_reg.avg_loss,
                "unseen_pass_rate": full_unseen.exec_pass_rate,
                "unseen_loss": full_unseen.avg_loss,
                "gate": asdict(full_gate),
            },
            "ablation_v2_no_resume_no_replay": {
                "reg_pass_rate": abl_reg.exec_pass_rate,
                "reg_loss": abl_reg.avg_loss,
                "unseen_pass_rate": abl_unseen.exec_pass_rate,
                "unseen_loss": abl_unseen.avg_loss,
                "gate": asdict(abl_gate),
            },
        },
    }
    (run_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def run_suite(
    out_dir: str | Path | None = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    p1_texts, p2_texts, reg_tasks, unseen_tasks = build_ablation_datasets()
    leaks = detect_task_leakage(p1_texts + p2_texts, unseen_tasks)
    if leaks:
        raise RuntimeError(f"Data leakage detected in unseen tasks: {leaks}")

    has_torch = False
    try:
        import torch  # noqa: F401

        has_torch = True
    except ModuleNotFoundError:
        has_torch = False

    if backend == "pytorch" and not has_torch:
        raise RuntimeError("STATUS: BLOCKED — PyTorch requested but not installed.")

    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_v2_run")
    run_root = base_dir / f"suite_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    if backend == "pytorch" or (backend == "auto" and has_torch):
        return _run_pytorch_suite(
            p1_texts, p2_texts, reg_tasks, unseen_tasks, leaks, run_root
        )
    return _run_pure_suite(
        p1_texts, p2_texts, reg_tasks, unseen_tasks, leaks, run_root
    )


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run ZYRQUEN V2 3-Arm Ablation Suite")
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    try:
        report = run_suite(out_dir=args.out_dir, backend=args.backend)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
