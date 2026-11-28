"""Expanded Multi-Seed ZYRQUEN V2 Experiment Runner (Colab PyTorch + Pure-Python Fallback).

Preserves strictly:
- ByteTokenizer (vocab_size=258)
- replay_ratio=0.5, consolidation_lambda=0.01, optimizer resume
- Original 3 unseen_tasks (avg_or_zero, distinct_ordered, diff_range) untouched & disjoint
- ApprovalGate (min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
- Multi-seed evaluation (42, 1337, 2026) across ALL seeds (no best-seed cherry-picking)
- Full raw_output capture + categorized error breakdown
- Fail-closed checkpoint approval records (failed checkpoints are NEVER approved)
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve()
for _candidate in (
    _HERE.parent.parent,
    Path("/content/gh_zyrquen_platform/python_core"),
    Path("/content/gh_zyrquen_platform"),
):
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from native_neural import NativeTransformerLM, _adamw_step, _grad_l2_norm  # noqa: E402
from native_tokenizer import NativeBPETokenizer  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
)
from v2.zyrquen_v2_suite import (  # noqa: E402
    build_ablation_datasets,
    build_diverse_training_corpus,
    default_output_root,
)
from v2.zyrquen_v2_trainer import (  # noqa: E402
    IGNORE_INDEX,
    ApprovalGate,
    ByteTokenizer,
    CodingTask,
    ContinualTrainerV2,
    EvalReport,
    detect_task_leakage,
    record_checkpoint_approval,
    run_code_in_sandbox,
)

DEFAULT_EXPANDED_SEEDS: Tuple[int, ...] = (42, 1337, 2026)


class DetailedSandboxEvaluator:
    """Evaluates tasks in isolated sandbox and stores raw_output, error_type, info, passed, and task_id."""

    def __init__(
        self,
        generate_fn: Callable[[str], str],
        loss_fn: Callable[[List[str]], Optional[float]],
    ) -> None:
        self.generate_fn = generate_fn
        self.loss_fn = loss_fn

    def evaluate(self, tasks: List[CodingTask]) -> EvalReport:
        if not tasks:
            return EvalReport(
                avg_loss=None,
                exec_pass_rate=0.0,
                passed_count=0,
                total_count=0,
                details=[],
                error_breakdown=_failure_breakdown([]),
            )
        loss_texts = [
            t.reference_solution if t.reference_solution else t.prompt for t in tasks
        ]
        avg_loss = self.loss_fn(loss_texts)
        passed = 0
        details: List[Dict[str, Any]] = []
        for task in tasks:
            raw_out = self.generate_fn(task.prompt)
            ok, msg = run_code_in_sandbox(raw_out, task.test_code)
            err_type = _classify_failure(ok, msg)
            if ok:
                passed += 1
            details.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "passed": ok,
                    "error_type": err_type,
                    "info": msg,
                    "raw_output": raw_out,
                }
            )
        return EvalReport(
            avg_loss=avg_loss,
            exec_pass_rate=passed / len(tasks),
            passed_count=passed,
            total_count=len(tasks),
            details=details,
            error_breakdown=_failure_breakdown(details),
        )


def _classify_failure(passed: bool, info: str) -> str:
    if passed:
        return "passed"
    text = str(info or "")
    if text == "timeout":
        return "timeout"
    if "IndentationError" in text or "TabError" in text or "SyntaxError" in text:
        return "SyntaxError"
    for err_type in ("NameError", "TypeError", "AssertionError"):
        if err_type in text:
            return err_type
    return "other"


def _failure_breakdown(details: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(
        _classify_failure(bool(d.get("passed")), str(d.get("info", "")))
        for d in details
    )
    return {
        "passed": int(counts["passed"]),
        "SyntaxError": int(counts["SyntaxError"]),
        "NameError": int(counts["NameError"]),
        "TypeError": int(counts["TypeError"]),
        "AssertionError": int(counts["AssertionError"]),
        "timeout": int(counts["timeout"]),
        "other": int(counts["other"]),
    }


def _sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_single_seed_pytorch(
    seed: int,
    steps_p1: int,
    steps_p2: int,
    checkpoint_every: int,
    p1_texts: List[str],
    p2_texts: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[Dict[str, str]],
    seed_dir: Path,
) -> Dict[str, Any]:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    from v2.tpu_backend import resolve_torch_device
    from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config

    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(seed)
    random.seed(seed)
    device = resolve_torch_device()
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

    base_model = TinyBaselineLM(
        vocab_size=tok.vocab_size, d_model=16, max_seq_len=256
    ).to(device)
    for phase_texts in (p1_texts, p2_texts):
        base_opt = torch.optim.AdamW(base_model.parameters(), lr=1e-3)
        for _ in range(150):
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
            for _ in range(96):
                nxt = torch.argmax(base_model(cur)[:, -1, :], dim=-1, keepdim=True)
                cur = torch.cat([cur, nxt], dim=-1)
                if int(nxt.item()) == tok.eos_id:
                    break
        return tok.decode(cur[0].tolist())

    base_eval = DetailedSandboxEvaluator(
        base_gen, lambda texts: _loss_over_texts(base_model, texts, 256)
    )
    base_reg = base_eval.evaluate(reg_tasks)
    base_unseen = base_eval.evaluate(unseen_tasks)

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
        total_decay_steps=steps_p1 + steps_p2 + 50,
        consolidation_lambda=0.01,
        seed=seed,
        device=device,
    )
    periodic_ckpts: List[Dict[str, Any]] = []

    done_p1 = 0
    p1_stats: Dict[str, Any] = {"global_step": 0}
    while done_p1 < steps_p1:
        chunk = min(checkpoint_every, steps_p1 - done_p1)
        p1_stats = trainer_full.train_steps(
            p1_texts, steps=chunk, batch_size=4, replay_ratio=0.0
        )
        done_p1 += chunk
        c_path, c_sha = trainer_full.save_checkpoint(
            ckpt_dir / f"full_p1_step_{done_p1}.pt"
        )
        periodic_ckpts.append(
            {"phase": "p1", "step": done_p1, "path": str(c_path), "sha256": c_sha}
        )

    trainer_full.snapshot_consolidation_state(p1_texts, batch_size=4)
    ckpt_p1, sha_p1 = trainer_full.save_checkpoint(ckpt_dir / "cand_full_p1_final.pt")

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

    done_p2 = 0
    p2_stats: Dict[str, Any] = {"global_step": p1_stats["global_step"]}
    while done_p2 < steps_p2:
        chunk = min(checkpoint_every, steps_p2 - done_p2)
        p2_stats = resumed_full.train_steps(
            p2_texts, steps=chunk, batch_size=4, replay_ratio=0.5
        )
        done_p2 += chunk
        c_path, c_sha = resumed_full.save_checkpoint(
            ckpt_dir / f"full_p2_step_{done_p2}.pt"
        )
        periodic_ckpts.append(
            {"phase": "p2", "step": done_p2, "path": str(c_path), "sha256": c_sha}
        )

    ckpt_p2, sha_p2 = resumed_full.save_checkpoint(ckpt_dir / "cand_full_p2_final.pt")

    def full_gen(prompt: str) -> str:
        cur = torch.tensor([tok.encode(prompt)[:512]], device=device)
        out = resumed_full.model.generate(cur, max_new_tokens=96, temperature=0.0)[
            0
        ].tolist()
        return tok.decode(out)

    full_eval = DetailedSandboxEvaluator(
        full_gen, lambda texts: _loss_over_texts(resumed_full.model, texts, 1024)
    )
    full_reg = full_eval.evaluate(reg_tasks)
    full_unseen = full_eval.evaluate(unseen_tasks)

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
    abl_stats = abl_trainer.train_steps(
        p2_texts, steps=steps_p2, batch_size=4, replay_ratio=0.0
    )
    ckpt_abl, sha_abl = abl_trainer.save_checkpoint(
        ckpt_dir / "ablation_v2_p2_final.pt"
    )

    def abl_gen(prompt: str) -> str:
        cur = torch.tensor([tok.encode(prompt)[:512]], device=device)
        out = abl_trainer.model.generate(cur, max_new_tokens=96, temperature=0.0)[
            0
        ].tolist()
        return tok.decode(out)

    abl_eval = DetailedSandboxEvaluator(
        abl_gen, lambda texts: _loss_over_texts(abl_trainer.model, texts, 1024)
    )
    abl_reg = abl_eval.evaluate(reg_tasks)
    abl_unseen = abl_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(
        min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True
    )
    full_gate = gate.evaluate(
        base_unseen, full_unseen, base_reg, full_reg, leakage_count=len(leaks)
    )
    abl_gate = gate.evaluate(
        base_unseen, abl_unseen, base_reg, abl_reg, leakage_count=len(leaks)
    )
    full_approval = record_checkpoint_approval(
        ckpt_p2, sha_p2, full_gate, metadata={"seed": seed, "arm": "candidate_v2_full"}
    )
    abl_approval = record_checkpoint_approval(
        ckpt_abl,
        sha_abl,
        abl_gate,
        metadata={"seed": seed, "arm": "ablation_v2_no_resume_no_replay"},
    )

    return {
        "seed": seed,
        "device": device.type,
        "checkpoints": {
            "cand_full_p1": {"path": str(ckpt_p1), "sha256": sha_p1},
            "cand_full_p2": {
                "path": str(ckpt_p2),
                "sha256": sha_p2,
                "approved": full_approval["approved"],
                "status": full_approval["status"],
                "approval_record": full_approval["approval_record_path"],
            },
            "ablation_v2_p2": {
                "path": str(ckpt_abl),
                "sha256": sha_abl,
                "approved": abl_approval["approved"],
                "status": abl_approval["status"],
                "approval_record": abl_approval["approval_record_path"],
            },
            "periodic": periodic_ckpts,
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
                "reg_error_breakdown": _failure_breakdown(base_reg.details),
                "unseen_error_breakdown": _failure_breakdown(base_unseen.details),
                "reg_details": base_reg.details,
                "unseen_details": base_unseen.details,
            },
            "candidate_v2_full": {
                "reg_pass_rate": full_reg.exec_pass_rate,
                "reg_loss": full_reg.avg_loss,
                "unseen_pass_rate": full_unseen.exec_pass_rate,
                "unseen_loss": full_unseen.avg_loss,
                "reg_error_breakdown": _failure_breakdown(full_reg.details),
                "unseen_error_breakdown": _failure_breakdown(full_unseen.details),
                "reg_details": full_reg.details,
                "unseen_details": full_unseen.details,
                "gate": asdict(full_gate),
                "approved": bool(full_approval["approved"]),
                "approval_status": full_approval["status"],
                "approved_checkpoint": full_approval["approved_checkpoint"],
            },
            "ablation_v2_no_resume_no_replay": {
                "reg_pass_rate": abl_reg.exec_pass_rate,
                "reg_loss": abl_reg.avg_loss,
                "unseen_pass_rate": abl_unseen.exec_pass_rate,
                "unseen_loss": abl_unseen.avg_loss,
                "reg_error_breakdown": _failure_breakdown(abl_reg.details),
                "unseen_error_breakdown": _failure_breakdown(abl_unseen.details),
                "reg_details": abl_reg.details,
                "unseen_details": abl_unseen.details,
                "gate": asdict(abl_gate),
                "approved": bool(abl_approval["approved"]),
                "approval_status": abl_approval["status"],
                "approved_checkpoint": abl_approval["approved_checkpoint"],
            },
        },
    }


def _run_single_seed_pure(
    seed: int,
    steps_p1: int,
    steps_p2: int,
    checkpoint_every: int,
    p1_texts: List[str],
    p2_texts: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    leaks: List[Dict[str, str]],
    seed_dir: Path,
) -> Dict[str, Any]:
    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    random.seed(seed)

    # 1. Baseline V1 (cold restart)
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
        seed=seed,
    )

    def _train_v1_cold(texts: List[str], steps: int, phase_seed: int) -> None:
        m_st = v1_model.zero_grads()
        v_st = v1_model.zero_grads()
        rng = random.Random(phase_seed)
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

    _train_v1_cold(p1_texts, steps=steps_p1, phase_seed=seed)
    _train_v1_cold(p2_texts, steps=steps_p2, phase_seed=seed + 1)

    base_eval = DetailedSandboxEvaluator(
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

    # 2. Candidate V2 Full
    tok_v2 = ByteTokenizer()
    cfg_v2 = PureZyrquenV2Config(
        vocab_size=tok_v2.vocab_size,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        base_seq_len=64,
        max_seq_len=128,
        seed=seed,
    )
    trainer_full = PureContinualTrainerV2(
        model=PureNativeTransformerLMV2(cfg_v2),
        tokenizer=tok_v2,
        lr=0.015,
        total_decay_steps=max(steps_p1 + steps_p2 + 8, 40),
        consolidation_lambda=0.01,
        seed=seed,
    )
    periodic_ckpts: List[Dict[str, Any]] = []
    done_p1 = 0
    p1_stats: Dict[str, Any] = {"global_step": 0}
    while done_p1 < steps_p1:
        chunk = min(checkpoint_every, steps_p1 - done_p1)
        p1_stats = trainer_full.train_steps(
            p1_texts, steps=chunk, batch_size=2, replay_ratio=0.0
        )
        done_p1 += chunk
        c_path, c_sha = trainer_full.save_checkpoint(
            ckpt_dir / f"full_p1_step_{done_p1}.json.gz"
        )
        periodic_ckpts.append(
            {"phase": "p1", "step": done_p1, "path": str(c_path), "sha256": c_sha}
        )

    trainer_full.snapshot_consolidation_state(p1_texts)
    ckpt_p1, sha_p1 = trainer_full.save_checkpoint(
        ckpt_dir / "cand_full_p1_final.json.gz"
    )

    resumed_full = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tokenizer=tok_v2,
        expected_sha256=sha_p1,
        resume_optimizer=True,
        restore_continual_state=True,
        consolidation_lambda=0.01,
    )
    resumed_full.model.extend_context(256)

    done_p2 = 0
    p2_stats: Dict[str, Any] = {"global_step": p1_stats["global_step"]}
    while done_p2 < steps_p2:
        chunk = min(checkpoint_every, steps_p2 - done_p2)
        p2_stats = resumed_full.train_steps(
            p2_texts, steps=chunk, batch_size=2, replay_ratio=0.5
        )
        done_p2 += chunk
        c_path, c_sha = resumed_full.save_checkpoint(
            ckpt_dir / f"full_p2_step_{done_p2}.json.gz"
        )
        periodic_ckpts.append(
            {"phase": "p2", "step": done_p2, "path": str(c_path), "sha256": c_sha}
        )

    ckpt_p2, sha_p2 = resumed_full.save_checkpoint(
        ckpt_dir / "cand_full_p2_final.json.gz"
    )

    full_eval = DetailedSandboxEvaluator(
        generate_fn=lambda p: resumed_full.model.generate_text(
            tok_v2, p, max_new_tokens=20
        ),
        loss_fn=lambda texts: float(
            resumed_full.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    full_reg = full_eval.evaluate(reg_tasks)
    full_unseen = full_eval.evaluate(unseen_tasks)

    # 3. Ablation V2
    abl_trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_p1,
        tokenizer=tok_v2,
        expected_sha256=sha_p1,
        resume_optimizer=False,
        restore_continual_state=False,
        consolidation_lambda=0.0,
    )
    abl_trainer.model.extend_context(256)
    abl_stats = abl_trainer.train_steps(
        p2_texts, steps=steps_p2, batch_size=2, replay_ratio=0.0
    )
    ckpt_abl, sha_abl = abl_trainer.save_checkpoint(
        ckpt_dir / "ablation_v2_p2_final.json.gz"
    )

    abl_eval = DetailedSandboxEvaluator(
        generate_fn=lambda p: abl_trainer.model.generate_text(
            tok_v2, p, max_new_tokens=20
        ),
        loss_fn=lambda texts: float(
            abl_trainer.model.evaluate_texts(tok_v2, texts)["loss"]
        ),
    )
    abl_reg = abl_eval.evaluate(reg_tasks)
    abl_unseen = abl_eval.evaluate(unseen_tasks)

    gate = ApprovalGate(
        min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True
    )
    full_gate = gate.evaluate(
        base_unseen, full_unseen, base_reg, full_reg, leakage_count=len(leaks)
    )
    abl_gate = gate.evaluate(
        base_unseen, abl_unseen, base_reg, abl_reg, leakage_count=len(leaks)
    )
    full_approval = record_checkpoint_approval(
        ckpt_p2, sha_p2, full_gate, metadata={"seed": seed, "arm": "candidate_v2_full"}
    )
    abl_approval = record_checkpoint_approval(
        ckpt_abl,
        sha_abl,
        abl_gate,
        metadata={"seed": seed, "arm": "ablation_v2_no_resume_no_replay"},
    )

    return {
        "seed": seed,
        "device": "pure_python_3.11_stdlib",
        "checkpoints": {
            "cand_full_p1": {"path": str(ckpt_p1), "sha256": sha_p1},
            "cand_full_p2": {
                "path": str(ckpt_p2),
                "sha256": sha_p2,
                "approved": full_approval["approved"],
                "status": full_approval["status"],
                "approval_record": full_approval["approval_record_path"],
            },
            "ablation_v2_p2": {
                "path": str(ckpt_abl),
                "sha256": sha_abl,
                "approved": abl_approval["approved"],
                "status": abl_approval["status"],
                "approval_record": abl_approval["approval_record_path"],
            },
            "periodic": periodic_ckpts,
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
                "reg_error_breakdown": _failure_breakdown(base_reg.details),
                "unseen_error_breakdown": _failure_breakdown(base_unseen.details),
                "reg_details": base_reg.details,
                "unseen_details": base_unseen.details,
            },
            "candidate_v2_full": {
                "reg_pass_rate": full_reg.exec_pass_rate,
                "reg_loss": full_reg.avg_loss,
                "unseen_pass_rate": full_unseen.exec_pass_rate,
                "unseen_loss": full_unseen.avg_loss,
                "reg_error_breakdown": _failure_breakdown(full_reg.details),
                "unseen_error_breakdown": _failure_breakdown(full_unseen.details),
                "reg_details": full_reg.details,
                "unseen_details": full_unseen.details,
                "gate": asdict(full_gate),
                "approved": bool(full_approval["approved"]),
                "approval_status": full_approval["status"],
                "approved_checkpoint": full_approval["approved_checkpoint"],
            },
            "ablation_v2_no_resume_no_replay": {
                "reg_pass_rate": abl_reg.exec_pass_rate,
                "reg_loss": abl_reg.avg_loss,
                "unseen_pass_rate": abl_unseen.exec_pass_rate,
                "unseen_loss": abl_unseen.avg_loss,
                "reg_error_breakdown": _failure_breakdown(abl_reg.details),
                "unseen_error_breakdown": _failure_breakdown(abl_unseen.details),
                "reg_details": abl_reg.details,
                "unseen_details": abl_unseen.details,
                "gate": asdict(abl_gate),
                "approved": bool(abl_approval["approved"]),
                "approval_status": abl_approval["status"],
                "approved_checkpoint": abl_approval["approved_checkpoint"],
            },
        },
    }


def _aggregate_breakdowns(items: List[Dict[str, int]]) -> Dict[str, int]:
    keys = ("passed", "SyntaxError", "NameError", "TypeError", "AssertionError", "timeout", "other")
    return {k: sum(int(item.get(k, 0)) for item in items) for k in keys}


def run_diverse_experiment(
    seeds: Sequence[int] = DEFAULT_EXPANDED_SEEDS,
    steps_p1: int = 480,
    steps_p2: int = 560,
    checkpoint_every: int = 160,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    _, _, reg_tasks, unseen_tasks = build_ablation_datasets()
    p1_texts, p2_texts = build_diverse_training_corpus()

    leaks = detect_task_leakage(p1_texts + p2_texts, unseen_tasks)
    if leaks:
        raise RuntimeError(f"Leakage detected against unseen tasks: {leaks}")

    has_torch = False
    try:
        import torch  # noqa: F401

        has_torch = True
    except ModuleNotFoundError:
        has_torch = False

    if backend == "pytorch" and not has_torch:
        raise RuntimeError("STATUS: BLOCKED — PyTorch requested but not installed.")

    use_pytorch = backend == "pytorch" or (backend == "auto" and has_torch)
    eff_steps_p1 = steps_p1 if use_pytorch else min(steps_p1, 16)
    eff_steps_p2 = steps_p2 if use_pytorch else min(steps_p2, 16)
    eff_ckpt_every = checkpoint_every if use_pytorch else min(checkpoint_every, 8)

    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = (
        Path(out_dir) if out_dir is not None else default_output_root("zyrquen_v2_diverse")
    )
    run_root = base_dir / f"exp_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    seed_runner = _run_single_seed_pytorch if use_pytorch else _run_single_seed_pure
    per_seed_runs = [
        seed_runner(
            seed=int(s),
            steps_p1=eff_steps_p1,
            steps_p2=eff_steps_p2,
            checkpoint_every=eff_ckpt_every,
            p1_texts=p1_texts,
            p2_texts=p2_texts,
            reg_tasks=reg_tasks,
            unseen_tasks=unseen_tasks,
            leaks=leaks,
            seed_dir=run_root / f"seed_{s}",
        )
        for s in seeds
    ]

    seed_summary: Dict[str, Any] = {}
    for arm in ("baseline_v1", "candidate_v2_full", "ablation_v2_no_resume_no_replay"):
        reg_rates = [float(r["results"][arm]["reg_pass_rate"]) for r in per_seed_runs]
        unseen_rates = [float(r["results"][arm]["unseen_pass_rate"]) for r in per_seed_runs]
        approved_seeds = [r["seed"] for r in per_seed_runs if r["results"][arm].get("approved")]
        rejected_seeds = [
            r["seed"] for r in per_seed_runs if not r["results"][arm].get("approved")
        ]
        reg_bd = _aggregate_breakdowns(
            [r["results"][arm]["reg_error_breakdown"] for r in per_seed_runs]
        )
        unseen_bd = _aggregate_breakdowns(
            [r["results"][arm]["unseen_error_breakdown"] for r in per_seed_runs]
        )
        entry: Dict[str, Any] = {
            "mean_reg_pass_rate": round(sum(reg_rates) / max(len(reg_rates), 1), 4),
            "min_reg_pass_rate": round(min(reg_rates), 4) if reg_rates else 0.0,
            "max_reg_pass_rate": round(max(reg_rates), 4) if reg_rates else 0.0,
            "mean_unseen_pass_rate": round(sum(unseen_rates) / max(len(unseen_rates), 1), 4),
            "min_unseen_pass_rate": round(min(unseen_rates), 4) if unseen_rates else 0.0,
            "max_unseen_pass_rate": round(max(unseen_rates), 4) if unseen_rates else 0.0,
            "reg_error_breakdown": reg_bd,
            "unseen_error_breakdown": unseen_bd,
        }
        if arm != "baseline_v1":
            all_ok = len(per_seed_runs) > 0 and len(approved_seeds) == len(per_seed_runs)
            entry["approved_seeds"] = approved_seeds
            entry["rejected_seeds"] = rejected_seeds
            entry["all_seeds_approved"] = all_ok
            entry["overall_approval_status"] = (
                "APPROVED" if all_ok else "REJECTED_BY_GATE"
            )
            entry["promoted_checkpoints"] = (
                [
                    r["results"][arm]["approved_checkpoint"]
                    for r in per_seed_runs
                    if r["results"][arm].get("approved_checkpoint")
                ]
                if all_ok
                else []
            )
        seed_summary[arm] = entry

    manifest = {
        "suite": "zyrquen_v2_diverse_multiseed",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "elapsed_sec": round(time.time() - t0, 2),
        "seeds": [int(s) for s in seeds],
        "leakage_count": len(leaks),
        "corpus_sizes": {"p1_texts": len(p1_texts), "p2_texts": len(p2_texts)},
        "seed_summary": seed_summary,
        "runs": per_seed_runs,
    }
    manifest_path = run_root / "manifest_diverse.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    manifest["manifest_sha256"] = _sha256_bytes(manifest_path)
    return manifest


def _parse_seeds(raw: str) -> Tuple[int, ...]:
    vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not vals:
        raise ValueError("Expected comma-separated seeds")
    return tuple(vals)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run ZYRQUEN V2 Expanded Multi-Seed Experiment"
    )
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--steps-p1", type=int, default=480)
    ap.add_argument("--steps-p2", type=int, default=560)
    ap.add_argument("--checkpoint-every", type=int, default=160)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    try:
        res = run_diverse_experiment(
            seeds=_parse_seeds(args.seeds),
            steps_p1=args.steps_p1,
            steps_p2=args.steps_p2,
            checkpoint_every=args.checkpoint_every,
            out_dir=args.out_dir,
            backend=args.backend,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "suite": res["suite"],
                "backend": res["backend"],
                "manifest_path": res["manifest_path"],
                "manifest_sha256": res["manifest_sha256"],
                "seeds": res["seeds"],
                "seed_summary": res["seed_summary"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
