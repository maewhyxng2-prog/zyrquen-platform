"""ZYRQUEN V2 Long-Context Cross-Reference & Continual Retention Stress Benchmark.

Tests two capabilities where small/short-context models without continual state fail:
1. Long-Context Cross-Reference (>256 bytes): module constants & helper functions declared at
   position 0..90 bytes must be referenced by functions placed beyond byte 256.
2. Continual Retention Stress Test: measures Phase-1 retention BEFORE and AFTER Phase-2
   plasticity training, comparing Baseline V1 vs Candidate V2 (Full Resume + Replay + EWC)
   vs Ablation V2 (No Resume / No Replay / No Consolidation).
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
)
from v2.zyrquen_v2_suite import default_output_root  # noqa: E402
from v2.zyrquen_v2_trainer import (  # noqa: E402
    IGNORE_INDEX,
    ApprovalGate,
    ByteTokenizer,
    CodingTask,
    ContinualTrainerV2,
    SandboxEvaluator,
    detect_task_leakage,
)


def _long_module_header(constants_block: str, tag: str) -> str:
    """Build a >256-byte Python module prefix with declarations at the very top."""
    spec_lines = [
        f"# Module Specification: {tag}",
        "# Pipeline invariant: downstream functions must apply top-of-file constants/helpers.",
        "# Section A: deterministic bounds, audit hash policy, and isolated execution guards.",
        "# Section B: preserve symbol integrity across multi-phase continual checkpoints.",
    ]
    header = constants_block.rstrip() + "\n" + "\n".join(spec_lines) + "\n"
    cur_len = len(header.encode("utf-8"))
    if cur_len <= 262:
        header += "# pad_" + ("x" * (262 - cur_len)) + "\n"
    return header


def build_longctx_benchmark() -> (
    Tuple[List[str], List[str], List[CodingTask], List[CodingTask]]
):
    """Build >256-byte cross-reference Phase-1, Phase-2, Retention, and leak-free Unseen tasks."""
    p1_header = _long_module_header(
        "BASE_OFFSET = 10\ndef _bump_val(v):\n    return v + BASE_OFFSET\n",
        "phase1_offset_rules",
    )
    p2_header = _long_module_header(
        "MIN_FLOOR = 5\nFACTOR_NUM = 3\ndef _floor_scale(v):\n    return max(MIN_FLOOR, v * FACTOR_NUM)\n",
        "phase2_floor_rules",
    )
    unseen_header = _long_module_header(
        "SCALE_BIAS = 4\ndef _cap_bound(v):\n    return min(100, v + SCALE_BIAS)\n",
        "unseen_cross_ref_eval",
    )

    phase1_texts = [
        p1_header + "def offset_sum(a, b):\n    return _bump_val(a + b)\n",
        p1_header + "def offset_clamp(x, hi):\n    return min(hi, _bump_val(x))\n",
    ]
    phase2_texts = [
        p2_header + "def scaled_floor(n):\n    return _floor_scale(n)\n",
        p2_header + "def floor_diff(a, b):\n    return _floor_scale(a - b)\n",
    ]

    retention_tasks = [
        CodingTask(
            task_id="ret_long_offset_sum",
            family="long_crossref_offset",
            prompt=p1_header + "def offset_sum(a, b):\n    return ",
            reference_solution=p1_header
            + "def offset_sum(a, b):\n    return _bump_val(a + b)\n",
            test_code="assert offset_sum(3, 4) == 17",
            category="regression",
        ),
        CodingTask(
            task_id="ret_long_offset_clamp",
            family="long_crossref_clamp",
            prompt=p1_header + "def offset_clamp(x, hi):\n    return ",
            reference_solution=p1_header
            + "def offset_clamp(x, hi):\n    return min(hi, _bump_val(x))\n",
            test_code="assert offset_clamp(5, 12) == 12 and offset_clamp(1, 20) == 11",
            category="regression",
        ),
    ]

    # Unseen functions & unseen constants NEVER appear in phase1_texts or phase2_texts
    unseen_tasks = [
        CodingTask(
            task_id="unseen_long_biased_scale",
            family="unseen_crossref_scale",
            prompt=unseen_header + "def compute_biased_scale(x):\n    return ",
            reference_solution=unseen_header
            + "def compute_biased_scale(x):\n    return _cap_bound(x * SCALE_BIAS)\n",
            test_code="assert compute_biased_scale(5) == 24 and compute_biased_scale(40) == 100",
            category="unseen",
        ),
        CodingTask(
            task_id="unseen_long_bounded_delta",
            family="unseen_crossref_delta",
            prompt=unseen_header + "def bounded_delta(a, b):\n    return ",
            reference_solution=unseen_header
            + "def bounded_delta(a, b):\n    return _cap_bound(abs(a - b))\n",
            test_code="assert bounded_delta(15, 3) == 16 and bounded_delta(0, 120) == 100",
            category="unseen",
        ),
    ]

    for task in retention_tasks + unseen_tasks:
        assert len(task.prompt.encode("utf-8")) > 256, (
            f"Task {task.task_id} prompt must exceed 256 bytes"
        )
    return phase1_texts, phase2_texts, retention_tasks, unseen_tasks


def _run_pure_longctx(
    p1_texts: List[str],
    p2_texts: List[str],
    ret_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[Dict[str, str]],
    run_root: Path,
) -> Dict[str, Any]:
    t0 = time.time()

    # --- 1. Baseline V1 (cap=64 tokens; loses top-of-file constants on >256B prompts) ---
    v1_tok = NativeBPETokenizer.train(
        p1_texts + p2_texts, target_vocab_size=300, min_pair_freq=2, version=1
    )
    v1_cap = 64
    v1_model = NativeTransformerLM(
        vocab_size=v1_tok.vocab_size,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        max_seq_len=v1_cap,
        seed=101,
    )

    def _train_v1_cold(texts: List[str], steps: int, seed: int) -> None:
        m_st = v1_model.zero_grads()
        v_st = v1_model.zero_grads()
        rng = random.Random(seed)
        seqs = [
            v1_tok.encode(t, add_bos=True, add_eos=True)[-v1_cap:] for t in texts
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

    _train_v1_cold(p1_texts, steps=12, seed=101)
    _train_v1_cold(p2_texts, steps=12, seed=102)

    base_eval = SandboxEvaluator(
        generate_fn=lambda prompt: prompt
        + (
            v1_model.generate_continuation(
                v1_tok, prompt[-120:], max_new_tokens=16, min_confidence=0.0
            ).get("generated")
            or ""
        ),
        loss_fn=lambda texts: float(
            v1_model.evaluate_sequences(
                [v1_tok.encode(t, add_bos=True, add_eos=True)[-v1_cap:] for t in texts]
            )["loss"]
        ),
    )
    base_ret = base_eval.evaluate(ret_tasks)
    base_unseen = base_eval.evaluate(unseen_tasks)

    # --- 2. Candidate V2 Full (RoPE + NTK 128 -> 512 + Full Resume + Replay + Consolidation) ---
    tok_v2 = ByteTokenizer()
    cfg_v2 = PureZyrquenV2Config(
        vocab_size=tok_v2.vocab_size,
        d_model=12,
        n_heads=2,
        n_layers=1,
        d_ff=24,
        base_seq_len=128,
        max_seq_len=512,
        seed=101,
    )
    trainer_full = PureContinualTrainerV2(
        model=PureNativeTransformerLMV2(cfg_v2),
        tokenizer=tok_v2,
        lr=0.012,
        total_decay_steps=20,
        consolidation_lambda=0.02,
        seed=101,
    )
    p1_stats = trainer_full.train_steps(p1_texts, steps=3, batch_size=2, replay_ratio=0.0)
    trainer_full.snapshot_consolidation_state(p1_texts)
    ckpt_p1, sha_p1 = trainer_full.save_checkpoint(run_root / "longctx_p1.json.gz")

    # Measure Pre-Phase-2 Retention baseline for V2
    pre_eval = SandboxEvaluator(
        generate_fn=lambda p: trainer_full.model.generate_text(
            tok_v2, p, max_new_tokens=8
        ),
        loss_fn=lambda texts: float(
            trainer_full.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    pre_ret = pre_eval.evaluate(ret_tasks)

    resumed_full = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tokenizer=tok_v2,
        expected_sha256=sha_p1,
        resume_optimizer=True,
        restore_continual_state=True,
    )
    resumed_full.model.extend_context(512)
    p2_stats = resumed_full.train_steps(p2_texts, steps=3, batch_size=2, replay_ratio=0.5)
    ckpt_p2, sha_p2 = resumed_full.save_checkpoint(run_root / "longctx_p2.json.gz")

    full_eval = SandboxEvaluator(
        generate_fn=lambda p: resumed_full.model.generate_text(
            tok_v2, p, max_new_tokens=8
        ),
        loss_fn=lambda texts: float(
            resumed_full.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    full_post_ret = full_eval.evaluate(ret_tasks)
    full_unseen = full_eval.evaluate(unseen_tasks)

    # --- 3. Ablation V2 (No Resume, No Replay, No Consolidation) ---
    abl_trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tokenizer=tok_v2,
        expected_sha256=sha_p1,
        resume_optimizer=False,
        restore_continual_state=False,
        consolidation_lambda=0.0,
    )
    abl_trainer.model.extend_context(512)
    abl_trainer.train_steps(p2_texts, steps=3, batch_size=2, replay_ratio=0.0)

    abl_eval = SandboxEvaluator(
        generate_fn=lambda p: abl_trainer.model.generate_text(
            tok_v2, p, max_new_tokens=8
        ),
        loss_fn=lambda texts: float(
            abl_trainer.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    abl_post_ret = abl_eval.evaluate(ret_tasks)
    abl_unseen = abl_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)
    full_gate = gate.evaluate(
        base_unseen, full_unseen, base_ret, full_post_ret, leakage_count=len(leaks)
    )

    max_prompt_bytes = max(len(t.prompt.encode("utf-8")) for t in ret_tasks + unseen_tasks)
    report = {
        "benchmark": "zyrquen_v2_longctx_and_retention",
        "backend": "pure_python_3.11_stdlib",
        "pytorch_available": False,
        "elapsed_sec": round(time.time() - t0, 2),
        "leakage_count": len(leaks),
        "max_prompt_bytes": max_prompt_bytes,
        "context_caps": {
            "baseline_v1_cap": v1_cap,
            "candidate_v2_max_seq_len": resumed_full.model.cfg.max_seq_len,
        },
        "checkpoints": {
            "longctx_p1": {"path": str(ckpt_p1), "sha256": sha_p1},
            "longctx_p2": {"path": str(ckpt_p2), "sha256": sha_p2},
        },
        "training_steps": {
            "phase1_step": p1_stats["global_step"],
            "phase2_step": p2_stats["global_step"],
        },
        "retention_stress_test": {
            "v2_pre_phase2_loss": pre_ret.avg_loss,
            "v2_pre_phase2_pass_rate": pre_ret.exec_pass_rate,
            "v2_full_post_phase2_loss": full_post_ret.avg_loss,
            "v2_full_post_phase2_pass_rate": full_post_ret.exec_pass_rate,
            "v2_full_retention_loss_delta": round(
                (full_post_ret.avg_loss or 0.0) - (pre_ret.avg_loss or 0.0), 4
            ),
            "v2_ablation_post_phase2_loss": abl_post_ret.avg_loss,
            "v2_ablation_post_phase2_pass_rate": abl_post_ret.exec_pass_rate,
            "v2_ablation_retention_loss_delta": round(
                (abl_post_ret.avg_loss or 0.0) - (pre_ret.avg_loss or 0.0), 4
            ),
        },
        "results": {
            "baseline_v1": {
                "retention_pass_rate": base_ret.exec_pass_rate,
                "retention_loss": base_ret.avg_loss,
                "unseen_longctx_pass_rate": base_unseen.exec_pass_rate,
                "unseen_longctx_loss": base_unseen.avg_loss,
            },
            "candidate_v2_full": {
                "retention_pass_rate": full_post_ret.exec_pass_rate,
                "retention_loss": full_post_ret.avg_loss,
                "unseen_longctx_pass_rate": full_unseen.exec_pass_rate,
                "unseen_longctx_loss": full_unseen.avg_loss,
                "gate": asdict(full_gate),
            },
            "ablation_v2_no_resume_no_replay": {
                "retention_pass_rate": abl_post_ret.exec_pass_rate,
                "retention_loss": abl_post_ret.avg_loss,
                "unseen_longctx_pass_rate": abl_unseen.exec_pass_rate,
                "unseen_longctx_loss": abl_unseen.avg_loss,
            },
        },
    }
    (run_root / "longctx_manifest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def _run_pytorch_longctx(
    p1_texts: List[str],
    p2_texts: List[str],
    ret_tasks: List[CodingTask],
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
    torch.manual_seed(101)
    random.seed(101)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = ByteTokenizer()

    def _loss_over_texts(
        forward_fn: Callable[[torch.Tensor], torch.Tensor],
        texts: List[str],
        max_len: int,
        tail_slice: bool = False,
    ) -> float:
        vals: List[float] = []
        for t in texts:
            ids = tok.encode(t, add_eos=True)
            ids = ids[-max_len:] if tail_slice else ids[:max_len]
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

    # --- 1. Baseline V1 (max_seq_len=256 tail window truncates >256B top-of-file constants) ---
    v1_cap = 256
    base_model = TinyBaselineLM(
        vocab_size=tok.vocab_size, d_model=16, max_seq_len=v1_cap
    ).to(device)
    for phase_texts in (p1_texts, p2_texts):
        base_opt = torch.optim.AdamW(base_model.parameters(), lr=1e-3)
        for _ in range(70):
            for s in phase_texts:
                ids = tok.encode(s, add_eos=True)[-v1_cap:]
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
        tail_ids = tok.encode(prompt)[-200:]
        cur = torch.tensor([tail_ids], device=device)
        base_model.eval()
        with torch.no_grad():
            for _ in range(72):
                nxt = torch.argmax(base_model(cur)[:, -1, :], dim=-1, keepdim=True)
                cur = torch.cat([cur, nxt], dim=-1)
                if int(nxt.item()) == tok.eos_id:
                    break
        completion = tok.decode(cur[0, len(tail_ids) :].tolist())
        return prompt + completion

    base_eval = SandboxEvaluator(
        base_gen, lambda texts: _loss_over_texts(base_model, texts, v1_cap, tail_slice=True)
    )
    base_ret = base_eval.evaluate(ret_tasks)
    base_unseen = base_eval.evaluate(unseen_tasks)

    # --- 2. Candidate V2 Full ---
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
        total_decay_steps=500,
        consolidation_lambda=0.01,
        device=device,
    )
    p1_stats = trainer_full.train_steps(p1_texts, steps=200, batch_size=4, replay_ratio=0.0)
    trainer_full.snapshot_consolidation_state(p1_texts, batch_size=4)
    ckpt_p1, sha_p1 = trainer_full.save_checkpoint(run_root / "longctx_p1.pt")

    def _cand_eval(model_obj: Any) -> SandboxEvaluator:
        def _gen(prompt: str) -> str:
            cur = torch.tensor([tok.encode(prompt)[:896]], device=device)
            out = model_obj.generate(cur, max_new_tokens=72, temperature=0.0)[0].tolist()
            return tok.decode(out)

        return SandboxEvaluator(
            _gen, lambda texts: _loss_over_texts(model_obj, texts, 1024, tail_slice=False)
        )

    pre_ret = _cand_eval(trainer_full.model).evaluate(ret_tasks)

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
    p2_stats = resumed_full.train_steps(p2_texts, steps=240, batch_size=4, replay_ratio=0.5)
    ckpt_p2, sha_p2 = resumed_full.save_checkpoint(run_root / "longctx_p2.pt")

    full_eval = _cand_eval(resumed_full.model)
    full_post_ret = full_eval.evaluate(ret_tasks)
    full_unseen = full_eval.evaluate(unseen_tasks)

    # --- 3. Ablation V2 (No Resume, No Replay, No Consolidation) ---
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
    abl_trainer.train_steps(p2_texts, steps=240, batch_size=4, replay_ratio=0.0)

    abl_eval = _cand_eval(abl_trainer.model)
    abl_post_ret = abl_eval.evaluate(ret_tasks)
    abl_unseen = abl_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)
    full_gate = gate.evaluate(
        base_unseen, full_unseen, base_ret, full_post_ret, leakage_count=len(leaks)
    )

    max_prompt_bytes = max(len(t.prompt.encode("utf-8")) for t in ret_tasks + unseen_tasks)
    report = {
        "benchmark": "zyrquen_v2_longctx_and_retention",
        "backend": f"pytorch ({device.type})",
        "pytorch_available": True,
        "elapsed_sec": round(time.time() - t0, 2),
        "leakage_count": len(leaks),
        "max_prompt_bytes": max_prompt_bytes,
        "context_caps": {
            "baseline_v1_cap": v1_cap,
            "candidate_v2_max_seq_len": resumed_full.model.cfg.max_seq_len,
        },
        "checkpoints": {
            "longctx_p1": {"path": str(ckpt_p1), "sha256": sha_p1},
            "longctx_p2": {"path": str(ckpt_p2), "sha256": sha_p2},
        },
        "training_steps": {
            "phase1_step": p1_stats["global_step"],
            "phase2_step": p2_stats["global_step"],
        },
        "retention_stress_test": {
            "v2_pre_phase2_loss": pre_ret.avg_loss,
            "v2_pre_phase2_pass_rate": pre_ret.exec_pass_rate,
            "v2_full_post_phase2_loss": full_post_ret.avg_loss,
            "v2_full_post_phase2_pass_rate": full_post_ret.exec_pass_rate,
            "v2_full_retention_loss_delta": round(
                (full_post_ret.avg_loss or 0.0) - (pre_ret.avg_loss or 0.0), 4
            ),
            "v2_ablation_post_phase2_loss": abl_post_ret.avg_loss,
            "v2_ablation_post_phase2_pass_rate": abl_post_ret.exec_pass_rate,
            "v2_ablation_retention_loss_delta": round(
                (abl_post_ret.avg_loss or 0.0) - (pre_ret.avg_loss or 0.0), 4
            ),
        },
        "results": {
            "baseline_v1": {
                "retention_pass_rate": base_ret.exec_pass_rate,
                "retention_loss": base_ret.avg_loss,
                "unseen_longctx_pass_rate": base_unseen.exec_pass_rate,
                "unseen_longctx_loss": base_unseen.avg_loss,
            },
            "candidate_v2_full": {
                "retention_pass_rate": full_post_ret.exec_pass_rate,
                "retention_loss": full_post_ret.avg_loss,
                "unseen_longctx_pass_rate": full_unseen.exec_pass_rate,
                "unseen_longctx_loss": full_unseen.avg_loss,
                "gate": asdict(full_gate),
            },
            "ablation_v2_no_resume_no_replay": {
                "retention_pass_rate": abl_post_ret.exec_pass_rate,
                "retention_loss": abl_post_ret.avg_loss,
                "unseen_longctx_pass_rate": abl_unseen.exec_pass_rate,
                "unseen_longctx_loss": abl_unseen.avg_loss,
            },
        },
    }
    (run_root / "longctx_manifest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def run_longctx_experiment(
    out_dir: str | Path | None = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    p1_texts, p2_texts, ret_tasks, unseen_tasks = build_longctx_benchmark()
    leaks = detect_task_leakage(p1_texts + p2_texts, unseen_tasks)
    if leaks:
        raise RuntimeError(f"Data leakage detected in longctx unseen tasks: {leaks}")

    has_torch = False
    try:
        import torch  # noqa: F401

        has_torch = True
    except ModuleNotFoundError:
        has_torch = False

    if backend == "pytorch" and not has_torch:
        raise RuntimeError("STATUS: BLOCKED — PyTorch requested but not installed.")

    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_v2_longctx_run")
    run_root = base_dir / f"longctx_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    if backend == "pytorch" or (backend == "auto" and has_torch):
        return _run_pytorch_longctx(
            p1_texts, p2_texts, ret_tasks, unseen_tasks, leaks, run_root
        )
    return _run_pure_longctx(
        p1_texts, p2_texts, ret_tasks, unseen_tasks, leaks, run_root
    )


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run ZYRQUEN V2 Long-Context Cross-Reference & Retention Stress Benchmark"
    )
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    try:
        report = run_longctx_experiment(out_dir=args.out_dir, backend=args.backend)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
