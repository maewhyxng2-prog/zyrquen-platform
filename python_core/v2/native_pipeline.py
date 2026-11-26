"""ZYRQUEN Native-Only Training & Gate Pipeline CLI.

Stages (strict sequential order):
  1. train      : Random-init NativeTransformerLMV2 / PureNativeTransformerLMV2 training
                  with continual snapshot, replay, non-overwriting checkpoint + SHA-256,
                  and disjoint baseline evaluation.
  2. evaluate   : Verify checkpoint SHA-256, confirm zero train/unseen leakage, and run
                  isolated sandbox evaluation on unseen tasks.
  3. regression : Verify checkpoint SHA-256 and evaluate regression retention vs baseline.
  4. approve    : Fail-closed checkpoint validation (SHA-256 + reload + NaN check +
                  ApprovalGate) producing `<checkpoint>.approval.json`.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from native_neural import NativeTransformerLM, _adamw_step, _grad_l2_norm  # noqa: E402
from native_tokenizer import NativeBPETokenizer  # noqa: E402
from v2.run_zyrquen_v2_experiment import build_leak_free_datasets  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_texts(texts: Sequence[str]) -> str:
    payload = json.dumps(list(texts), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _has_non_finite_pure(obj: Any) -> bool:
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(_has_non_finite_pure(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_non_finite_pure(v) for v in obj)
    return False


def _resolve_backend(requested: str) -> str:
    has_torch = False
    try:
        import torch  # noqa: F401

        has_torch = True
    except ModuleNotFoundError:
        has_torch = False

    if requested == "pytorch":
        if not has_torch:
            raise RuntimeError("BLOCKED: PyTorch ('torch') requested but not installed.")
        return "pytorch"
    if requested == "auto" and has_torch:
        return "pytorch"
    return "pure"


def _verify_checkpoint_integrity(
    artifact_dir: Path,
    manifest: Dict[str, Any],
) -> Tuple[Path, str]:
    ckpt_rel = manifest.get("candidate_checkpoint")
    expected_sha = manifest.get("candidate_sha256")
    if not ckpt_rel or not expected_sha:
        raise ValueError("train_manifest.json is missing candidate_checkpoint or candidate_sha256")

    ckpt_path = artifact_dir / str(ckpt_rel)
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"Candidate checkpoint not found: {ckpt_path}")

    sidecar_path = ckpt_path.with_suffix(ckpt_path.suffix + ".sha256")
    if not sidecar_path.is_file():
        raise FileNotFoundError(f"Checkpoint SHA-256 sidecar missing: {sidecar_path}")

    sidecar_sha = sidecar_path.read_text(encoding="utf-8").strip()
    actual_sha = _sha256_file(ckpt_path)
    if actual_sha != expected_sha or sidecar_sha != expected_sha:
        raise ValueError(
            f"Checkpoint SHA-256 mismatch (actual={actual_sha[:16]}, "
            f"sidecar={sidecar_sha[:16]}, manifest={expected_sha[:16]})"
        )
    return ckpt_path, actual_sha


def _eval_report_from_dict(data: Dict[str, Any]) -> EvalReport:
    return EvalReport(
        avg_loss=data.get("avg_loss"),
        exec_pass_rate=float(data["exec_pass_rate"]),
        passed_count=int(data["passed_count"]),
        total_count=int(data["total_count"]),
        details=list(data.get("details", [])),
        error_breakdown=dict(data.get("error_breakdown", {})),
    )


def _train_and_eval_baseline_pure(
    p1_train: List[str],
    p2_train: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    *,
    seed: int,
    steps: int,
) -> Tuple[EvalReport, EvalReport]:
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
        seed=seed,
    )

    def _train_cold(texts: List[str], phase_steps: int, phase_seed: int) -> None:
        m_st = v1_model.zero_grads()
        v_st = v1_model.zero_grads()
        rng = random.Random(phase_seed)
        seqs = [v1_tok.encode(t, add_bos=True, add_eos=True)[:64] for t in texts]
        for step in range(1, phase_steps + 1):
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

    _train_cold(p1_train, steps, seed)
    _train_cold(p2_train, steps, seed + 1)

    evaluator = SandboxEvaluator(
        generate_fn=lambda prompt: prompt
        + (v1_model.generate_continuation(v1_tok, prompt, max_new_tokens=32, min_confidence=0.0).get("generated") or ""),
        loss_fn=lambda texts: float(
            v1_model.evaluate_sequences(
                [v1_tok.encode(t, add_bos=True, add_eos=True)[:64] for t in texts]
            )["loss"]
        ),
    )
    return evaluator.evaluate(reg_tasks), evaluator.evaluate(unseen_tasks)


def _train_and_eval_baseline_pytorch(
    p1_train: List[str],
    p2_train: List[str],
    reg_tasks: List[CodingTask],
    unseen_tasks: List[CodingTask],
    *,
    seed: int,
    steps: int,
) -> Tuple[EvalReport, EvalReport]:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class TinyBaselineLM(nn.Module):
        def __init__(self, vocab_size: int = 258, d_model: int = 16, max_seq_len: int = 256) -> None:
            super().__init__()
            self.max_seq_len = max_seq_len
            self.tok_emb = nn.Embedding(vocab_size, d_model, padding_idx=256)
            self.pos_emb = nn.Embedding(max_seq_len, d_model)
            enc_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=2, dim_feedforward=32, dropout=0.0, batch_first=True
            )
            self.enc = nn.TransformerEncoder(enc_layer, num_layers=1)
            self.head = nn.Linear(d_model, vocab_size, bias=False)

        def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
            seq_len = min(input_ids.shape[1], self.max_seq_len)
            x = input_ids[:, :seq_len]
            pos = torch.arange(seq_len, device=x.device).unsqueeze(0)
            h = self.tok_emb(x) + self.pos_emb(pos)
            mask = nn.Transformer.generate_square_subsequent_mask(seq_len, device=x.device)
            return self.head(self.enc(h, mask=mask, is_causal=True))

    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = ByteTokenizer()
    base_model = TinyBaselineLM(vocab_size=tok.vocab_size).to(device)
    base_opt = torch.optim.AdamW(base_model.parameters(), lr=1e-3)
    for _ in range(steps):
        for sample in p1_train + p2_train:
            ids = tok.encode(sample, add_eos=True)[:256]
            x = torch.tensor([ids[:-1]], device=device)
            y = torch.tensor([ids[1:]], device=device)
            base_opt.zero_grad()
            loss = F.cross_entropy(base_model(x).reshape(-1, tok.vocab_size), y.reshape(-1))
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

    def base_loss(texts: List[str]) -> float:
        losses: List[float] = []
        for t in texts:
            ids = tok.encode(t, add_eos=True)[:256]
            if len(ids) < 2:
                continue
            x = torch.tensor([ids[:-1]], dtype=torch.long, device=device)
            y = torch.tensor([[tid if tid != tok.pad_id else IGNORE_INDEX for tid in ids[1:]]], dtype=torch.long, device=device)
            logits = base_model(x)
            losses.append(float(F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1), ignore_index=IGNORE_INDEX).item()))
        return sum(losses) / max(len(losses), 1)

    evaluator = SandboxEvaluator(generate_fn=base_gen, loss_fn=base_loss)
    return evaluator.evaluate(reg_tasks), evaluator.evaluate(unseen_tasks)


def stage_train(
    artifact_dir: Path,
    *,
    backend: str = "auto",
    seed: int = 42,
    steps_p1: int = 20,
    steps_p2: int = 25,
    replay_ratio: float = 0.5,
) -> Dict[str, Any]:
    resolved_backend = _resolve_backend(backend)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = artifact_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    p1_train, p2_train, reg_tasks, unseen_tasks = build_leak_free_datasets()
    leaks = detect_task_leakage(p1_train + p2_train, unseen_tasks)
    if leaks:
        raise RuntimeError(f"BLOCKED: train/unseen leakage detected: {leaks}")

    run_id = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    tok = ByteTokenizer()

    if resolved_backend == "pytorch":
        import torch
        from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config

        torch.manual_seed(seed)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        base_reg, base_unseen = _train_and_eval_baseline_pytorch(
            p1_train, p2_train, reg_tasks, unseen_tasks, seed=seed, steps=max(4, steps_p1 + steps_p2)
        )
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
            seed=seed,
            device=device,
        )
        p1_stats = trainer.train_steps(p1_train, steps=steps_p1, batch_size=3, replay_ratio=0.0)
        trainer.snapshot_consolidation_state(p1_train, batch_size=3)
        p1_path, p1_sha = trainer.save_checkpoint(ckpt_dir / f"v2_p1_{run_id}_s{seed}.pt")
        resumed = ContinualTrainerV2.load_checkpoint(
            p1_path, tokenizer=tok, expected_sha256=p1_sha, resume_optimizer=True, device=device
        )
        resumed.model.extend_context(1024)
        p2_stats = resumed.train_steps(p2_train, steps=steps_p2, batch_size=3, replay_ratio=replay_ratio)
        p2_path, p2_sha = resumed.save_checkpoint(ckpt_dir / f"v2_cand_{run_id}_s{seed}.pt")
    else:
        base_reg, base_unseen = _train_and_eval_baseline_pure(
            p1_train, p2_train, reg_tasks, unseen_tasks, seed=seed, steps=max(2, steps_p1 + steps_p2)
        )
        cfg = PureZyrquenV2Config(
            vocab_size=tok.vocab_size,
            d_model=24,
            n_heads=2,
            n_layers=2,
            d_ff=48,
            base_seq_len=64,
            max_seq_len=128,
            seed=seed,
        )
        trainer = PureContinualTrainerV2(
            model=PureNativeTransformerLMV2(cfg),
            tokenizer=tok,
            lr=0.015,
            total_decay_steps=max(steps_p1 + steps_p2 + 10, 40),
            consolidation_lambda=0.02,
            seed=seed,
        )
        p1_stats = trainer.train_steps(p1_train, steps=steps_p1, batch_size=2, replay_ratio=0.0)
        trainer.snapshot_consolidation_state(p1_train)
        p1_path, p1_sha = trainer.save_checkpoint(ckpt_dir / f"v2_p1_{run_id}_s{seed}.json.gz")
        resumed = PureContinualTrainerV2.load_checkpoint(
            p1_path, tokenizer=tok, expected_sha256=p1_sha, resume_optimizer=True
        )
        resumed.model.extend_context(256)
        p2_stats = resumed.train_steps(p2_train, steps=steps_p2, batch_size=2, replay_ratio=replay_ratio)
        p2_path, p2_sha = resumed.save_checkpoint(ckpt_dir / f"v2_cand_{run_id}_s{seed}.json.gz")
        if _has_non_finite_pure(resumed.model.params):
            raise RuntimeError("NaN/Inf detected in trained pure model parameters")

    baseline_payload = {
        "schema": "zyrquen.v2.baseline_metrics",
        "backend": resolved_backend,
        "seed": seed,
        "regression": asdict(base_reg),
        "unseen": asdict(base_unseen),
    }
    (artifact_dir / "baseline_metrics.json").write_text(
        json.dumps(baseline_payload, indent=2), encoding="utf-8"
    )

    manifest = {
        "schema": "zyrquen.v2.train_manifest",
        "run_id": run_id,
        "backend": resolved_backend,
        "seed": seed,
        "initialization": "random_from_scratch",
        "external_models_used": False,
        "replay_ratio": replay_ratio,
        "phase1_dataset_sha256": _sha256_texts(p1_train),
        "phase2_dataset_sha256": _sha256_texts(p2_train),
        "leakage_count": len(leaks),
        "phase1_checkpoint": p1_path.relative_to(artifact_dir).as_posix(),
        "phase1_sha256": p1_sha,
        "candidate_checkpoint": p2_path.relative_to(artifact_dir).as_posix(),
        "candidate_sha256": p2_sha,
        "p1_stats": p1_stats,
        "p2_stats": p2_stats,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (artifact_dir / "train_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def _load_candidate_evaluator(
    ckpt_path: Path, ckpt_sha: str, backend: str
) -> Tuple[SandboxEvaluator, Any]:
    tok = ByteTokenizer()
    if backend == "pytorch":
        import torch
        import torch.nn.functional as F

        trainer = ContinualTrainerV2.load_checkpoint(
            ckpt_path, tokenizer=tok, expected_sha256=ckpt_sha, resume_optimizer=True
        )
        device = trainer.device

        def gen_fn(prompt: str) -> str:
            ids = tok.encode(prompt)[: trainer.model.cfg.max_seq_len]
            cur = torch.tensor([ids], device=device)
            out_ids = trainer.model.generate(cur, max_new_tokens=64, temperature=0.0)[0].tolist()
            return tok.decode(out_ids)

        def loss_fn(texts: List[str]) -> float:
            losses: List[float] = []
            for t in texts:
                ids = tok.encode(t, add_eos=True)[: trainer.model.cfg.max_seq_len]
                if len(ids) < 2:
                    continue
                x = torch.tensor([ids[:-1]], dtype=torch.long, device=device)
                y = torch.tensor(
                    [[tid if tid != tok.pad_id else IGNORE_INDEX for tid in ids[1:]]],
                    dtype=torch.long,
                    device=device,
                )
                logits = trainer.model(x)
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

        return SandboxEvaluator(generate_fn=gen_fn, loss_fn=loss_fn), trainer

    trainer = PureContinualTrainerV2.load_checkpoint(
        ckpt_path, tokenizer=tok, expected_sha256=ckpt_sha, resume_optimizer=True
    )
    if _has_non_finite_pure(trainer.model.params):
        raise ValueError("Checkpoint contains NaN or Inf weights")

    evaluator = SandboxEvaluator(
        generate_fn=lambda prompt: trainer.model.generate_text(tok, prompt, max_new_tokens=36),
        loss_fn=lambda texts: float(trainer.model.evaluate_texts(tok, texts)["loss"]),
    )
    return evaluator, trainer



def stage_evaluate(artifact_dir: Path) -> Dict[str, Any]:
    manifest = json.loads((artifact_dir / "train_manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads((artifact_dir / "baseline_metrics.json").read_text(encoding="utf-8"))
    ckpt_path, ckpt_sha = _verify_checkpoint_integrity(artifact_dir, manifest)

    p1_train, p2_train, _, unseen_tasks = build_leak_free_datasets()
    leaks = detect_task_leakage(p1_train + p2_train, unseen_tasks)
    if leaks:
        raise RuntimeError(f"BLOCKED: train/unseen leakage detected: {leaks}")

    evaluator, _ = _load_candidate_evaluator(ckpt_path, ckpt_sha, manifest["backend"])
    cand_unseen = evaluator.evaluate(unseen_tasks)
    base_unseen = _eval_report_from_dict(baseline["unseen"])

    payload = {
        "schema": "zyrquen.v2.eval_report",
        "backend": manifest["backend"],
        "checkpoint": manifest["candidate_checkpoint"],
        "checkpoint_sha256": ckpt_sha,
        "leakage_count": len(leaks),
        "baseline_unseen": asdict(base_unseen),
        "candidate_unseen": asdict(cand_unseen),
        "unseen_gain": round(cand_unseen.exec_pass_rate - base_unseen.exec_pass_rate, 6),
        "evaluated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (artifact_dir / "eval_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def stage_regression(artifact_dir: Path) -> Dict[str, Any]:
    manifest = json.loads((artifact_dir / "train_manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads((artifact_dir / "baseline_metrics.json").read_text(encoding="utf-8"))
    ckpt_path, ckpt_sha = _verify_checkpoint_integrity(artifact_dir, manifest)

    _, _, reg_tasks, _ = build_leak_free_datasets()
    evaluator, _ = _load_candidate_evaluator(ckpt_path, ckpt_sha, manifest["backend"])
    cand_reg = evaluator.evaluate(reg_tasks)
    base_reg = _eval_report_from_dict(baseline["regression"])

    payload = {
        "schema": "zyrquen.v2.regression_report",
        "backend": manifest["backend"],
        "checkpoint": manifest["candidate_checkpoint"],
        "checkpoint_sha256": ckpt_sha,
        "baseline_regression": asdict(base_reg),
        "candidate_regression": asdict(cand_reg),
        "regression_drop": round(base_reg.exec_pass_rate - cand_reg.exec_pass_rate, 6),
        "evaluated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (artifact_dir / "regression_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


def stage_approve(
    artifact_dir: Path,
    *,
    min_unseen_gain: float = 0.01,
    max_regression_drop: float = 0.05,
) -> Dict[str, Any]:
    manifest = json.loads((artifact_dir / "train_manifest.json").read_text(encoding="utf-8"))
    eval_data = json.loads((artifact_dir / "eval_report.json").read_text(encoding="utf-8"))
    reg_data = json.loads((artifact_dir / "regression_report.json").read_text(encoding="utf-8"))

    ckpt_path, ckpt_sha = _verify_checkpoint_integrity(artifact_dir, manifest)
    if eval_data.get("checkpoint_sha256") != ckpt_sha:
        raise ValueError("eval_report.json checkpoint_sha256 mismatch")
    if reg_data.get("checkpoint_sha256") != ckpt_sha:
        raise ValueError("regression_report.json checkpoint_sha256 mismatch")

    # Re-verify checkpoint loads and contains finite weights
    _load_candidate_evaluator(ckpt_path, ckpt_sha, manifest["backend"])

    leakage_count = int(manifest.get("leakage_count", 0)) + int(eval_data.get("leakage_count", 0))
    base_unseen = _eval_report_from_dict(eval_data["baseline_unseen"])
    cand_unseen = _eval_report_from_dict(eval_data["candidate_unseen"])
    base_reg = _eval_report_from_dict(reg_data["baseline_regression"])
    cand_reg = _eval_report_from_dict(reg_data["candidate_regression"])

    gate = ApprovalGate(
        min_unseen_gain=min_unseen_gain,
        max_regression_drop=max_regression_drop,
        require_non_zero_unseen=True,
    )
    decision = gate.evaluate(
        baseline_unseen=base_unseen,
        candidate_unseen=cand_unseen,
        baseline_regression=base_reg,
        candidate_regression=cand_reg,
        leakage_count=leakage_count,
    )
    approval = record_checkpoint_approval(
        ckpt_path,
        ckpt_sha,
        decision,
        metadata={
            "backend": manifest["backend"],
            "seed": manifest["seed"],
            "run_id": manifest["run_id"],
            "external_models_used": False,
        },
    )
    (artifact_dir / "gate_summary.json").write_text(
        json.dumps(approval, indent=2), encoding="utf-8"
    )
    return approval


def stage_resume(
    artifact_dir: Path,
    *,
    steps: int = 5,
    replay_ratio: float = 0.5,
) -> Dict[str, Any]:
    """Verify checkpoint continuity by loading the saved candidate checkpoint (SHA-256 verified)
    and resuming training without resetting weights or overwriting the candidate checkpoint.
    """
    manifest = json.loads((artifact_dir / "train_manifest.json").read_text(encoding="utf-8"))
    ckpt_path, ckpt_sha = _verify_checkpoint_integrity(artifact_dir, manifest)
    backend = manifest["backend"]
    p1_train, p2_train, _, _ = build_leak_free_datasets()
    tok = ByteTokenizer()

    ckpt_dir = artifact_dir / "checkpoints"
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

    if backend == "pytorch":
        resumed = ContinualTrainerV2.load_checkpoint(
            ckpt_path, tokenizer=tok, expected_sha256=ckpt_sha, resume_optimizer=True
        )
        step_before = int(resumed.global_step)
        stats = resumed.train_steps(
            p2_train, steps=steps, batch_size=3, replay_ratio=replay_ratio
        )
        out_name = f"v2_resumed_{stamp}_step{stats['global_step']}.pt"
        resumed_path, resumed_sha = resumed.save_checkpoint(ckpt_dir / out_name)
    else:
        resumed = PureContinualTrainerV2.load_checkpoint(
            ckpt_path, tokenizer=tok, expected_sha256=ckpt_sha, resume_optimizer=True
        )
        step_before = int(resumed.global_step)
        stats = resumed.train_steps(
            p2_train, steps=steps, batch_size=2, replay_ratio=replay_ratio
        )
        if _has_non_finite_pure(resumed.model.params):
            raise RuntimeError("NaN/Inf detected after resumed training")
        out_name = f"v2_resumed_{stamp}_step{stats['global_step']}.json.gz"
        resumed_path, resumed_sha = resumed.save_checkpoint(ckpt_dir / out_name)

    source_sha_after = _sha256_file(ckpt_path)
    if source_sha_after != ckpt_sha:
        raise RuntimeError("Source candidate checkpoint changed during resume verification")

    if backend == "pytorch":
        reloaded = ContinualTrainerV2.load_checkpoint(
            resumed_path, tokenizer=tok, expected_sha256=resumed_sha,
            resume_optimizer=True, restore_continual_state=True,
        )
    else:
        reloaded = PureContinualTrainerV2.load_checkpoint(
            resumed_path, tokenizer=tok, expected_sha256=resumed_sha,
            resume_optimizer=True, restore_continual_state=True,
        )
    if int(reloaded.global_step) != int(stats["global_step"]):
        raise RuntimeError("Resumed checkpoint global_step failed reload verification")

    continuity = {
        "schema": "zyrquen.v2.checkpoint_continuity",
        "backend": backend,
        "source_checkpoint": ckpt_path.relative_to(artifact_dir).as_posix(),
        "source_sha256": ckpt_sha,
        "source_sha256_after": source_sha_after,
        "source_checkpoint_unchanged": source_sha_after == ckpt_sha,
        "resumed_checkpoint_reload_verified": True,
        "global_step_before": step_before,
        "global_step_after": int(stats["global_step"]),
        "resumed_steps": int(steps),
        "final_loss_after_resume": stats["final_loss"],
        "resumed_checkpoint": resumed_path.relative_to(artifact_dir).as_posix(),
        "resumed_sha256": resumed_sha,
        "weights_preserved_continuity": int(stats["global_step"]) == step_before + int(steps),
        "verified_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (artifact_dir / "continuity_report.json").write_text(
        json.dumps(continuity, indent=2), encoding="utf-8"
    )
    return continuity


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ZYRQUEN Native-Only Pipeline CLI")
    sub = parser.add_subparsers(dest="stage", required=True)

    p_train = sub.add_parser("train", help="Train Native V2 model from random weights")
    p_train.add_argument("--artifact-dir", required=True)
    p_train.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    p_train.add_argument("--seed", type=int, default=42)
    p_train.add_argument("--steps-p1", type=int, default=20)
    p_train.add_argument("--steps-p2", type=int, default=25)
    p_train.add_argument("--replay-ratio", type=float, default=0.5)

    p_cont = sub.add_parser("resume-checkpoint", help="Verify checkpoint continuity without overwriting source")
    p_cont.add_argument("--artifact-dir", required=True)
    p_cont.add_argument("--steps", type=int, default=5)
    p_cont.add_argument("--replay-ratio", type=float, default=0.5)

    p_eval = sub.add_parser("evaluate", help="Evaluate checkpoint on disjoint unseen tasks")
    p_eval.add_argument("--artifact-dir", required=True)

    p_reg = sub.add_parser("regression", help="Evaluate checkpoint retention vs baseline")
    p_reg.add_argument("--artifact-dir", required=True)

    p_app = sub.add_parser("approve", help="Run fail-closed ApprovalGate & SHA-256 check")
    p_app.add_argument("--artifact-dir", required=True)
    p_app.add_argument("--min-unseen-gain", type=float, default=0.01)
    p_app.add_argument("--max-regression-drop", type=float, default=0.05)
    p_app.add_argument(
        "--report-only",
        action="store_true",
        help="Write REJECTED_BY_GATE/APPROVED record without returning exit code 3 on gate rejection.",
    )

    p_res = sub.add_parser("resume", help="Verify checkpoint continuity by loading and training further")
    p_res.add_argument("--artifact-dir", required=True)
    p_res.add_argument("--steps", type=int, default=5)
    p_res.add_argument("--replay-ratio", type=float, default=0.5)

    args = parser.parse_args(argv)
    artifact_dir = Path(args.artifact_dir)

    try:
        if args.stage == "train":
            res = stage_train(
                artifact_dir,
                backend=args.backend,
                seed=args.seed,
                steps_p1=args.steps_p1,
                steps_p2=args.steps_p2,
                replay_ratio=args.replay_ratio,
            )
            print(json.dumps(res, indent=2))
            return 0
        if args.stage == "resume-checkpoint":
            res = stage_checkpoint_continuity(
                artifact_dir, steps=args.steps, replay_ratio=args.replay_ratio
            )
            print(json.dumps(res, indent=2))
            return 0
        if args.stage == "evaluate":
            res = stage_evaluate(artifact_dir)
            print(json.dumps(res, indent=2))
            return 0
        if args.stage == "regression":
            res = stage_regression(artifact_dir)
            print(json.dumps(res, indent=2))
            return 0
        if args.stage == "approve":
            res = stage_approve(
                artifact_dir,
                min_unseen_gain=args.min_unseen_gain,
                max_regression_drop=args.max_regression_drop,
            )
            print(json.dumps(res, indent=2))
            if not res["approved"] and not args.report_only:
                return 3
            return 0
        if args.stage == "resume":
            res = stage_resume(
                artifact_dir,
                steps=args.steps,
                replay_ratio=args.replay_ratio,
            )
            print(json.dumps(res, indent=2))
            return 0
    except Exception as exc:
        print(f"PIPELINE ERROR ({args.stage}): {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
