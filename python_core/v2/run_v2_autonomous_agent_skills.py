"""ZYRQUEN V2 Autonomous Agent Skills & Verified Experience Replay Suite.

Combines continual multi-phase training with a `VerifiedExperienceBuffer` that
records ONLY train examples verified by real sandbox execution (`passed == True`)
and NEVER touches Validation or Held-out tasks.

Supports both PyTorch (--backend pytorch) and Pure-Python 3.11 stdlib fallback
(--backend pure, or auto when PyTorch is absent).
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve()
for _cand in (
    _HERE.parent.parent,
    Path("/content/gh_zyrquen_platform/python_core"),
    Path("/content/gh_zyrquen_platform"),
):
    if _cand.exists() and str(_cand) not in sys.path:
        sys.path.insert(0, str(_cand))

from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
)
from v2.zyrquen_v2_suite import default_output_root  # noqa: E402
from v2.zyrquen_v2_trainer import (  # noqa: E402
    ERROR_TYPES,
    IGNORE_INDEX,
    ApprovalGate,
    ByteTokenizer,
    CodingTask,
    ContinualTrainerV2,
    EvalReport,
    detect_task_leakage,
    extract_first_python_function,
    record_checkpoint_approval,
    run_code_in_sandbox,
)

DEFAULT_AUTONOMOUS_SEEDS: Tuple[int, ...] = (42, 1337, 2026)
PHASE_ORDER: Tuple[str, str, str] = (
    "plan_exec_verify",
    "recovery_data_ops",
    "continual_generalize",
)


@dataclass(frozen=True)
class AutonomousSkillTask:
    task_id: str
    family: str
    skills: Tuple[str, ...]
    split: str  # "train" | "val" | "heldout"
    phase: str  # "plan_exec_verify" | "recovery_data_ops" | "continual_generalize"
    prompt: str
    target_code: str
    test_code: str

    @property
    def full_text(self) -> str:
        return self.prompt + self.target_code


def build_autonomous_skill_splits() -> (
    Tuple[List[AutonomousSkillTask], List[AutonomousSkillTask], List[AutonomousSkillTask]]
):
    """Build disjoint train / val / heldout tasks for multi-step execution and verified learning."""
    train_tasks: List[AutonomousSkillTask] = [
        # --- Family: plan_exec_verify (Task Planning, Programming, Verification) ---
        AutonomousSkillTask(
            "aut_pev_1",
            "plan_exec_verify",
            ("Task Planning", "Programming", "Verification"),
            "train",
            "plan_exec_verify",
            "# Plan: 1) keep positive ints 2) compute sum\ndef sum_pos_verified(nums):\n    return ",
            "sum(n for n in nums if n > 0)\n",
            "assert sum_pos_verified([-3, 4, 6, -1]) == 10 and sum_pos_verified([]) == 0",
        ),
        AutonomousSkillTask(
            "aut_pev_2",
            "plan_exec_verify",
            ("Task Planning", "Programming", "Verification"),
            "train",
            "plan_exec_verify",
            "# Plan: 1) clamp x to [lo, hi] 2) return int\ndef clamp_verified(x, lo, hi):\n    return ",
            "max(lo, min(hi, x))\n",
            "assert clamp_verified(20, 0, 10) == 10 and clamp_verified(-5, 0, 10) == 0 and clamp_verified(6, 0, 10) == 6",
        ),
        AutonomousSkillTask(
            "aut_pev_3",
            "plan_exec_verify",
            ("Task Planning", "Mathematics", "Verification"),
            "train",
            "plan_exec_verify",
            "# Plan: 1) filter even nums 2) return count\ndef count_even_verified(nums):\n    return ",
            "sum(1 for n in nums if n % 2 == 0)\n",
            "assert count_even_verified([1, 2, 4, 7, 8]) == 3 and count_even_verified([]) == 0",
        ),
        AutonomousSkillTask(
            "aut_pev_4",
            "plan_exec_verify",
            ("Task Planning", "Programming", "Verification"),
            "train",
            "plan_exec_verify",
            "# Plan: 1) remove None 2) return sorted list\ndef clean_sort_verified(vals):\n    return ",
            "sorted(v for v in vals if v is not None)\n",
            "assert clean_sort_verified([5, None, 1, 3, None]) == [1, 3, 5]",
        ),
        # --- Family: recovery_data_ops (Recovery, File & Data, Computer Operations) ---
        AutonomousSkillTask(
            "aut_rdo_1",
            "recovery_data_ops",
            ("Recovery", "File & Data", "Computer Operations"),
            "train",
            "recovery_data_ops",
            "# Recovery & Data: safe divide with fallback when den == 0\ndef safe_ratio_ops(num, den, fallback=0.0):\n    return ",
            "fallback if den == 0 else num / den\n",
            "assert safe_ratio_ops(10, 2, -1.0) == 5.0 and safe_ratio_ops(10, 0, -1.0) == -1.0",
        ),
        AutonomousSkillTask(
            "aut_rdo_2",
            "recovery_data_ops",
            ("Recovery", "File & Data", "Computer Operations"),
            "train",
            "recovery_data_ops",
            "# Recovery & Data: first element or fallback if empty\ndef head_or_fallback(seq, fallback):\n    return ",
            "seq[0] if len(seq) > 0 else fallback\n",
            "assert head_or_fallback(['a', 'b'], 'empty') == 'a' and head_or_fallback([], 'empty') == 'empty'",
        ),
        AutonomousSkillTask(
            "aut_rdo_3",
            "recovery_data_ops",
            ("Recovery", "File & Data", "Computer Operations"),
            "train",
            "recovery_data_ops",
            "# Recovery & Data: trim & drop blank lines/tokens\ndef clean_tokens_ops(raw_text):\n    return ",
            "[t.strip() for t in raw_text.split(',') if t.strip()]\n",
            "assert clean_tokens_ops(' x , , y , ') == ['x', 'y']",
        ),
        AutonomousSkillTask(
            "aut_rdo_4",
            "recovery_data_ops",
            ("Recovery", "File & Data", "Computer Operations"),
            "train",
            "recovery_data_ops",
            "# Recovery & Data: count items matching pred_fn\ndef count_where_ops(items, pred_fn):\n    return ",
            "sum(1 for it in items if pred_fn(it))\n",
            "assert count_where_ops([1, 2, 3, 4], lambda x: x > 2) == 2",
        ),
        # --- Family: continual_generalize (Tool Use, Research, Learning, Generalization) ---
        AutonomousSkillTask(
            "aut_cg_1",
            "continual_generalize",
            ("Tool Use", "Research", "Learning", "Generalization"),
            "train",
            "continual_generalize",
            "# Generalize: lookup via lookup_fn(k) or return fallback if None\ndef lookup_fallback(lookup_fn, k, fallback):\n    return ",
            "fallback if lookup_fn(k) is None else lookup_fn(k)\n",
            "assert lookup_fallback(lambda k: {'id': 7}.get(k), 'id', 0) == 7 and lookup_fallback(lambda k: {'id': 7}.get(k), 'x', -1) == -1",
        ),
        AutonomousSkillTask(
            "aut_cg_2",
            "continual_generalize",
            ("Tool Use", "Research", "Learning", "Generalization"),
            "train",
            "continual_generalize",
            "# Generalize: reverse words separated by spaces\ndef flip_words_gen(s):\n    return ",
            "' '.join(reversed(s.split()))\n",
            "assert flip_words_gen('step one two') == 'two one step'",
        ),
        AutonomousSkillTask(
            "aut_cg_3",
            "continual_generalize",
            ("Tool Use", "Research", "Learning", "Generalization"),
            "train",
            "continual_generalize",
            "# Generalize: count lowercase vowels in text\ndef count_vowels_gen(text):\n    return ",
            "sum(1 for ch in text.lower() if ch in 'aeiou')\n",
            "assert count_vowels_gen('AEIOUxyz') == 5",
        ),
        AutonomousSkillTask(
            "aut_cg_4",
            "continual_generalize",
            ("Tool Use", "Research", "Learning", "Generalization"),
            "train",
            "continual_generalize",
            "# Generalize: take first k items after sorting ascending\ndef top_k_gen(vals, k):\n    return ",
            "[] if k <= 0 else sorted(vals)[:k]\n",
            "assert top_k_gen([8, 2, 6, 4], 2) == [2, 4] and top_k_gen([1, 2], 0) == []",
        ),
    ]

    val_tasks: List[AutonomousSkillTask] = [
        AutonomousSkillTask(
            "val_aut_1",
            "val_safe_mean",
            ("Reasoning", "Mathematics", "Recovery", "Verification"),
            "val",
            "plan_exec_verify",
            "# Verify mean or 0.0 when empty\ndef safe_mean_val(nums):\n    return ",
            "0.0 if len(nums) == 0 else sum(nums) / len(nums)\n",
            "assert abs(safe_mean_val([2.0, 6.0]) - 4.0) < 1e-6 and safe_mean_val([]) == 0.0",
        ),
        AutonomousSkillTask(
            "val_aut_2",
            "val_unique_sorted",
            ("File & Data", "Generalization", "Learning"),
            "val",
            "continual_generalize",
            "# Unique non-empty items sorted ascending\ndef unique_non_empty_val(items):\n    return ",
            "sorted({x for x in items if x})\n",
            "assert unique_non_empty_val(['b', '', 'a', 'b']) == ['a', 'b']",
        ),
    ]

    heldout_tasks: List[AutonomousSkillTask] = [
        AutonomousSkillTask(
            "held_aut_1",
            "held_avg_or_zero",
            ("Reasoning", "Mathematics", "Recovery", "Verification"),
            "heldout",
            "continual_generalize",
            "# Held-out: mean of numbers or 0.0 if empty\ndef avg_or_zero(vals):\n    return ",
            "0.0 if len(vals) == 0 else sum(vals) / len(vals)\n",
            "assert abs(avg_or_zero([2.0, 4.0, 6.0]) - 4.0) < 1e-6 and avg_or_zero([]) == 0.0",
        ),
        AutonomousSkillTask(
            "held_aut_2",
            "held_distinct_ordered",
            ("File & Data", "Generalization", "Learning", "Self-Correction"),
            "heldout",
            "continual_generalize",
            "# Held-out: unique items sorted ascending\ndef distinct_ordered(seq):\n    return ",
            "sorted(set(seq))\n",
            "assert distinct_ordered([4, 2, 4, 1, 2]) == [1, 2, 4] and distinct_ordered([]) == []",
        ),
        AutonomousSkillTask(
            "held_aut_3",
            "held_diff_range",
            ("Task Planning", "Computer Operations", "Mathematics", "Recovery"),
            "heldout",
            "continual_generalize",
            "# Held-out: max minus min or 0 if empty\ndef diff_range(nums):\n    return ",
            "0 if len(nums) == 0 else max(nums) - min(nums)\n",
            "assert diff_range([3, 11, 2, 8]) == 9 and diff_range([]) == 0",
        ),
    ]

    tr_fams = {x.family for x in train_tasks}
    val_fams = {x.family for x in val_tasks}
    ho_fams = {x.family for x in heldout_tasks}
    if (tr_fams & val_fams) or (tr_fams & ho_fams) or (val_fams & ho_fams):
        raise RuntimeError(
            f"Family overlap detected: train={tr_fams}, val={val_fams}, heldout={ho_fams}"
        )

    return train_tasks, val_tasks, heldout_tasks


def _as_coding_tasks(items: Sequence[AutonomousSkillTask], *, category: str) -> List[CodingTask]:
    return [
        CodingTask(
            task_id=ex.task_id,
            family=f"{ex.family}:{'+'.join(ex.skills)}",
            prompt=ex.prompt,
            test_code=ex.test_code,
            reference_solution=ex.full_text,
            category=category,
        )
        for ex in items
    ]


def verify_autonomous_skills_leakage(
    train_tasks: Sequence[AutonomousSkillTask],
    val_tasks: Sequence[AutonomousSkillTask],
    heldout_tasks: Sequence[AutonomousSkillTask],
) -> List[Dict[str, str]]:
    train_texts = [x.full_text for x in train_tasks]
    eval_tasks = _as_coding_tasks(val_tasks, category="validation") + _as_coding_tasks(
        heldout_tasks, category="unseen"
    )
    return detect_task_leakage(train_texts, eval_tasks)


def classify_error(passed: bool, info: str) -> str:
    if passed:
        return "passed"
    txt = str(info or "")
    if txt == "timeout":
        return "timeout"
    if "IndentationError" in txt or "TabError" in txt or "SyntaxError" in txt:
        return "SyntaxError"
    for err in ("NameError", "TypeError", "AssertionError"):
        if err in txt:
            return err
    return "other"


def _error_summary(details: List[Dict[str, Any]]) -> Dict[str, int]:
    c = Counter(classify_error(bool(d.get("passed")), str(d.get("info", ""))) for d in details)
    return {k: int(c.get(k, 0)) for k in ERROR_TYPES}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _has_non_finite_pure(obj: Any) -> bool:
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(_has_non_finite_pure(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_non_finite_pure(v) for v in obj)
    return False


def _resolve_backend(requested: str) -> Tuple[str, bool]:
    has_torch = False
    try:
        import torch  # noqa: F401

        has_torch = True
    except ModuleNotFoundError:
        has_torch = False

    if requested == "pytorch":
        if not has_torch:
            raise RuntimeError(
                "STATUS: BLOCKED — --backend pytorch requested but 'torch' is not installed in this environment."
            )
        return "pytorch", True
    if requested == "auto" and has_torch:
        return "pytorch", True
    return "pure", has_torch


class VerifiedExperienceBuffer:
    """Stores ONLY train examples verified by sandbox execution (passed == True)."""

    def __init__(self) -> None:
        self._verified_texts: List[str] = []
        self._seen_ids: set[str] = set()

    def collect_verified(
        self,
        train_tasks: List[AutonomousSkillTask],
        generate_fn: Callable[[str], str],
    ) -> Dict[str, int]:
        checked = 0
        newly_verified = 0
        for item in train_tasks:
            if item.split != "train":
                raise ValueError(
                    f"Refusing non-train split item {item.task_id!r} (split={item.split!r}) in VerifiedExperienceBuffer"
                )
            checked += 1
            raw = generate_fn(item.prompt)
            ok, _ = run_code_in_sandbox(raw, item.test_code)
            if ok and item.task_id not in self._seen_ids:
                self._seen_ids.add(item.task_id)
                self._verified_texts.append(raw)
                newly_verified += 1
        return {
            "checked": checked,
            "newly_verified": newly_verified,
            "total_verified_buffer": len(self._verified_texts),
        }

    def texts(self) -> List[str]:
        return list(self._verified_texts)


class AutonomousSandboxEvaluator:
    """Evaluates tasks with self-correction retry in an isolated sandbox."""

    def __init__(
        self,
        generate_fn: Callable[[str], str],
        loss_fn: Callable[[List[str]], Optional[float]],
        max_attempts: int = 2,
    ) -> None:
        self.generate_fn = generate_fn
        self.loss_fn = loss_fn
        self.max_attempts = max(1, max_attempts)

    def evaluate(self, tasks: List[CodingTask]) -> Tuple[EvalReport, EvalReport]:
        if not tasks:
            empty = EvalReport(
                avg_loss=None,
                exec_pass_rate=0.0,
                passed_count=0,
                total_count=0,
                details=[],
                error_breakdown={k: 0 for k in ERROR_TYPES},
            )
            return empty, empty

        loss_texts = [t.reference_solution if t.reference_solution else t.prompt for t in tasks]
        avg_loss = self.loss_fn(loss_texts)

        first_passed = 0
        final_passed = 0
        first_details: List[Dict[str, Any]] = []
        final_details: List[Dict[str, Any]] = []

        for task in tasks:
            raw_1 = self.generate_fn(task.prompt)
            extracted_1 = extract_first_python_function(raw_1)
            ok_1, info_1 = run_code_in_sandbox(raw_1, task.test_code)
            err_1 = classify_error(ok_1, info_1)
            if ok_1:
                first_passed += 1

            first_details.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "attempt": 1,
                    "passed": ok_1,
                    "error_type": err_1,
                    "info": info_1,
                    "raw_output": raw_1,
                    "extracted_code": extracted_1,
                }
            )

            cur_ok, cur_info, cur_raw, cur_extracted, cur_err, cur_attempt = (
                ok_1,
                info_1,
                raw_1,
                extracted_1,
                err_1,
                1,
            )
            prompt_lines = task.prompt.splitlines()
            last_line = prompt_lines[-1] if prompt_lines else ""
            while (not cur_ok) and (cur_attempt < self.max_attempts):
                cur_attempt += 1
                repair_prompt = (
                    f"{task.prompt.rstrip()}\n# Recovery attempt {cur_attempt} after {cur_info}\n"
                    f"{last_line} "
                )
                cur_raw = self.generate_fn(repair_prompt)
                cur_extracted = extract_first_python_function(cur_raw)
                cur_ok, cur_info = run_code_in_sandbox(cur_raw, task.test_code)
                cur_err = classify_error(cur_ok, cur_info)

            if cur_ok:
                final_passed += 1

            final_details.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "attempts_used": cur_attempt,
                    "first_attempt_passed": ok_1,
                    "passed": cur_ok,
                    "error_type": cur_err,
                    "info": cur_info,
                    "raw_output": cur_raw,
                    "extracted_code": cur_extracted,
                }
            )

        rounded_loss = round(avg_loss, 4) if avg_loss is not None else None
        return (
            EvalReport(
                avg_loss=rounded_loss,
                exec_pass_rate=round(first_passed / len(tasks), 4),
                passed_count=first_passed,
                total_count=len(tasks),
                details=first_details,
                error_breakdown=_error_summary(first_details),
            ),
            EvalReport(
                avg_loss=rounded_loss,
                exec_pass_rate=round(final_passed / len(tasks), 4),
                passed_count=final_passed,
                total_count=len(tasks),
                details=final_details,
                error_breakdown=_error_summary(final_details),
            ),
        )


def _run_seed_pytorch(
    *,
    seed: int,
    phase_steps: Tuple[int, int, int],
    ckpt_every: int,
    max_new_tokens: int,
    max_attempts: int,
    train_tasks: List[AutonomousSkillTask],
    val_coding: List[CodingTask],
    heldout_coding: List[CodingTask],
    leak_count: int,
    seed_dir: Path,
) -> Dict[str, Any]:
    import torch
    import torch.nn.functional as F
    from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config

    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(seed)
    random.seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = ByteTokenizer()

    phase_texts = {
        ph: [x.full_text for x in train_tasks if x.phase == ph] for ph in PHASE_ORDER
    }
    verified_buf = VerifiedExperienceBuffer()

    cfg = ZyrquenV2Config(
        vocab_size=tok.vocab_size,
        d_model=256,
        n_heads=8,
        n_layers=6,
        d_ff=768,
        base_seq_len=256,
        max_seq_len=512,
        dropout=0.02,
    )
    trainer = ContinualTrainerV2(
        NativeTransformerLMV2(cfg),
        tok,
        lr=1e-3,
        total_decay_steps=sum(phase_steps) + 150,
        consolidation_lambda=0.01,
        seed=seed,
        device=device,
    )

    def make_eval(m: NativeTransformerLMV2) -> Tuple[Callable[[str], str], AutonomousSandboxEvaluator]:
        def gen_fn(prompt: str) -> str:
            cur = torch.tensor([tok.encode(prompt)[: m.cfg.max_seq_len]], device=device)
            out = m.generate(cur, max_new_tokens=max_new_tokens, temperature=0.0)[0].tolist()
            return tok.decode(out)

        def loss_fn(texts: List[str]) -> float:
            vals: List[float] = []
            m.eval()
            with torch.no_grad():
                for t in texts:
                    ids = tok.encode(t, add_eos=True)[: m.cfg.max_seq_len]
                    if len(ids) < 2:
                        continue
                    x = torch.tensor([ids[:-1]], dtype=torch.long, device=device)
                    y = torch.tensor(
                        [[tid if tid != tok.pad_id else IGNORE_INDEX for tid in ids[1:]]],
                        dtype=torch.long,
                        device=device,
                    )
                    logits = m(x)
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

        return gen_fn, AutonomousSandboxEvaluator(gen_fn, loss_fn, max_attempts=max_attempts)

    _, pre_ev = make_eval(trainer.model)
    pre_val_1, pre_val_final = pre_ev.evaluate(val_coding)
    pre_ho_1, pre_ho_final = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    phase_logs: List[Dict[str, Any]] = []
    baseline_val_report = pre_val_final

    for idx, (ph, n_steps) in enumerate(zip(PHASE_ORDER, phase_steps)):
        texts = list(phase_texts[ph]) + verified_buf.texts()
        done = 0
        while done < n_steps:
            chunk = min(ckpt_every, n_steps - done)
            trainer.train_steps(
                texts, steps=chunk, batch_size=4, replay_ratio=0.0 if idx == 0 else 0.5
            )
            done += chunk
            p, sha = trainer.save_checkpoint(ckpt_dir / f"{ph}_step_{done}.pt")
            checkpoints.append({"phase": ph, "step": done, "path": str(p), "sha256": sha})

        gen_fn, ev = make_eval(trainer.model)
        exp_stats = verified_buf.collect_verified(train_tasks, gen_fn)
        trainer.snapshot_consolidation_state(texts, batch_size=4)
        p_ph, sha_ph = trainer.save_checkpoint(ckpt_dir / f"{ph}_final.pt")

        cur_v1, cur_vf = ev.evaluate(val_coding)
        cur_h1, cur_hf = ev.evaluate(heldout_coding)
        if idx == 0:
            baseline_val_report = cur_vf
        phase_logs.append(
            {
                "phase": ph,
                "checkpoint": str(p_ph),
                "sha256": sha_ph,
                "verified_experience": exp_stats,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
                "heldout_first_pass_rate": cur_h1.exec_pass_rate,
                "heldout_final_pass_rate": cur_hf.exec_pass_rate,
                "heldout_loss": cur_hf.avg_loss,
                "heldout_final_errors": cur_hf.error_breakdown,
            }
        )
        if idx < len(PHASE_ORDER) - 1:
            trainer = ContinualTrainerV2.load_checkpoint(
                p_ph,
                tok,
                expected_sha256=sha_ph,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=0.01,
                device=device,
            )
            trainer.model.extend_context(1024)

    final_ckpt = Path(phase_logs[-1]["checkpoint"])
    final_sha = str(phase_logs[-1]["sha256"])
    _, post_ev = make_eval(trainer.model)
    post_val_1, post_val_final = post_ev.evaluate(val_coding)
    post_ho_1, post_ho_final = post_ev.evaluate(heldout_coding)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(
        pre_ho_final, post_ho_final, baseline_val_report, post_val_final, leakage_count=leak_count
    )
    approval = record_checkpoint_approval(
        final_ckpt,
        final_sha,
        gate_res,
        metadata={
            "seed": seed,
            "suite": "zyrquen_autonomous_agent_skills_verified_learning",
            "backend": "pytorch",
        },
    )

    return {
        "seed": seed,
        "backend": "pytorch",
        "device": device.type,
        "global_step_final": trainer.global_step,
        "checkpoints": checkpoints,
        "final_checkpoint": {
            "path": str(final_ckpt),
            "sha256": final_sha,
            "approval_record": approval["approval_record_path"],
            "status": approval["status"],
        },
        "pre_random_init": {
            "val_first_pass_rate": pre_val_1.exec_pass_rate,
            "val_final_pass_rate": pre_val_final.exec_pass_rate,
            "val_loss": pre_val_final.avg_loss,
            "heldout_first_pass_rate": pre_ho_1.exec_pass_rate,
            "heldout_final_pass_rate": pre_ho_final.exec_pass_rate,
            "heldout_loss": pre_ho_final.avg_loss,
        },
        "phase_logs": phase_logs,
        "post_autonomous_run": {
            "val_first_pass_rate": post_val_1.exec_pass_rate,
            "val_final_pass_rate": post_val_final.exec_pass_rate,
            "val_loss": post_val_final.avg_loss,
            "val_first_errors": post_val_1.error_breakdown,
            "val_final_errors": post_val_final.error_breakdown,
            "val_details": post_val_final.details,
            "heldout_first_pass_rate": post_ho_1.exec_pass_rate,
            "heldout_final_pass_rate": post_ho_final.exec_pass_rate,
            "heldout_loss": post_ho_final.avg_loss,
            "heldout_first_errors": post_ho_1.error_breakdown,
            "heldout_final_errors": post_ho_final.error_breakdown,
            "heldout_details": post_ho_final.details,
            "gate": asdict(gate_res),
            "approved": bool(approval["approved"]),
            "status": approval["status"],
            "approved_checkpoint": approval["approved_checkpoint"],
        },
    }


def _run_seed_pure(
    *,
    seed: int,
    phase_steps: Tuple[int, int, int],
    ckpt_every: int,
    max_new_tokens: int,
    max_attempts: int,
    train_tasks: List[AutonomousSkillTask],
    val_coding: List[CodingTask],
    heldout_coding: List[CodingTask],
    leak_count: int,
    seed_dir: Path,
) -> Dict[str, Any]:
    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    tok = ByteTokenizer()

    phase_texts = {
        ph: [x.full_text for x in train_tasks if x.phase == ph] for ph in PHASE_ORDER
    }
    verified_buf = VerifiedExperienceBuffer()

    cfg = PureZyrquenV2Config(
        vocab_size=tok.vocab_size,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        base_seq_len=256,
        max_seq_len=256,
        seed=seed,
    )
    trainer = PureContinualTrainerV2(
        model=PureNativeTransformerLMV2(cfg),
        tokenizer=tok,
        lr=0.015,
        warmup_steps=4,
        total_decay_steps=max(sum(phase_steps) + 12, 36),
        consolidation_lambda=0.01,
        seed=seed,
    )

    def make_eval(m: PureNativeTransformerLMV2) -> Tuple[Callable[[str], str], AutonomousSandboxEvaluator]:
        def gen_fn(prompt: str) -> str:
            return m.generate_text(tok, prompt, max_new_tokens=max_new_tokens)

        return gen_fn, AutonomousSandboxEvaluator(
            generate_fn=gen_fn,
            loss_fn=lambda texts: float(m.evaluate_texts(tok, texts)["loss"]),
            max_attempts=max_attempts,
        )

    _, pre_ev = make_eval(trainer.model)
    pre_val_1, pre_val_final = pre_ev.evaluate(val_coding)
    pre_ho_1, pre_ho_final = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    phase_logs: List[Dict[str, Any]] = []
    baseline_val_report = pre_val_final

    for idx, (ph, n_steps) in enumerate(zip(PHASE_ORDER, phase_steps)):
        texts = list(phase_texts[ph]) + verified_buf.texts()
        done = 0
        while done < n_steps:
            chunk = min(ckpt_every, n_steps - done)
            trainer.train_steps(
                texts, steps=chunk, batch_size=2, replay_ratio=0.0 if idx == 0 else 0.5
            )
            done += chunk
            p, sha = trainer.save_checkpoint(ckpt_dir / f"{ph}_step_{done}.json.gz")
            checkpoints.append({"phase": ph, "step": done, "path": str(p), "sha256": sha})

        if _has_non_finite_pure(trainer.model.params):
            raise RuntimeError(f"Training halted: NaN/Inf detected during phase {ph}")

        gen_fn, ev = make_eval(trainer.model)
        exp_stats = verified_buf.collect_verified(train_tasks, gen_fn)
        trainer.snapshot_consolidation_state(texts)
        p_ph, sha_ph = trainer.save_checkpoint(ckpt_dir / f"{ph}_final.json.gz")

        cur_v1, cur_vf = ev.evaluate(val_coding)
        cur_h1, cur_hf = ev.evaluate(heldout_coding)
        if idx == 0:
            baseline_val_report = cur_vf
        phase_logs.append(
            {
                "phase": ph,
                "checkpoint": str(p_ph),
                "sha256": sha_ph,
                "verified_experience": exp_stats,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
                "heldout_first_pass_rate": cur_h1.exec_pass_rate,
                "heldout_final_pass_rate": cur_hf.exec_pass_rate,
                "heldout_loss": cur_hf.avg_loss,
                "heldout_final_errors": cur_hf.error_breakdown,
            }
        )
        if idx < len(PHASE_ORDER) - 1:
            trainer = PureContinualTrainerV2.load_checkpoint(
                p_ph,
                tokenizer=tok,
                expected_sha256=sha_ph,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=0.01,
            )
            trainer.model.extend_context(512 if idx == 0 else 768)

    final_ckpt = Path(phase_logs[-1]["checkpoint"])
    final_sha = str(phase_logs[-1]["sha256"])
    _, post_ev = make_eval(trainer.model)
    post_val_1, post_val_final = post_ev.evaluate(val_coding)
    post_ho_1, post_ho_final = post_ev.evaluate(heldout_coding)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(
        pre_ho_final, post_ho_final, baseline_val_report, post_val_final, leakage_count=leak_count
    )
    approval = record_checkpoint_approval(
        final_ckpt,
        final_sha,
        gate_res,
        metadata={
            "seed": seed,
            "suite": "zyrquen_autonomous_agent_skills_verified_learning",
            "backend": "pure_python_3.11_stdlib",
        },
    )

    return {
        "seed": seed,
        "backend": "pure_python_3.11_stdlib",
        "device": "pure_python_3.11_stdlib",
        "global_step_final": trainer.global_step,
        "checkpoints": checkpoints,
        "final_checkpoint": {
            "path": str(final_ckpt),
            "sha256": final_sha,
            "approval_record": approval["approval_record_path"],
            "status": approval["status"],
        },
        "pre_random_init": {
            "val_first_pass_rate": pre_val_1.exec_pass_rate,
            "val_final_pass_rate": pre_val_final.exec_pass_rate,
            "val_loss": pre_val_final.avg_loss,
            "heldout_first_pass_rate": pre_ho_1.exec_pass_rate,
            "heldout_final_pass_rate": pre_ho_final.exec_pass_rate,
            "heldout_loss": pre_ho_final.avg_loss,
        },
        "phase_logs": phase_logs,
        "post_autonomous_run": {
            "val_first_pass_rate": post_val_1.exec_pass_rate,
            "val_final_pass_rate": post_val_final.exec_pass_rate,
            "val_loss": post_val_final.avg_loss,
            "val_first_errors": post_val_1.error_breakdown,
            "val_final_errors": post_val_final.error_breakdown,
            "val_details": post_val_final.details,
            "heldout_first_pass_rate": post_ho_1.exec_pass_rate,
            "heldout_final_pass_rate": post_ho_final.exec_pass_rate,
            "heldout_loss": post_ho_final.avg_loss,
            "heldout_first_errors": post_ho_1.error_breakdown,
            "heldout_final_errors": post_ho_final.error_breakdown,
            "heldout_details": post_ho_final.details,
            "gate": asdict(gate_res),
            "approved": bool(approval["approved"]),
            "status": approval["status"],
            "approved_checkpoint": approval["approved_checkpoint"],
        },
    }


def run_autonomous_agent_skills(
    seeds: Sequence[int] = DEFAULT_AUTONOMOUS_SEEDS,
    phase_steps: Tuple[int, int, int] = (900, 900, 900),
    ckpt_every: int = 450,
    pure_phase_steps: Tuple[int, int, int] = (8, 8, 8),
    pure_ckpt_every: int = 4,
    pure_max_new_tokens: int = 24,
    pytorch_max_new_tokens: int = 96,
    max_attempts: int = 2,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    train_tasks, val_tasks, heldout_tasks = build_autonomous_skill_splits()
    leaks = verify_autonomous_skills_leakage(train_tasks, val_tasks, heldout_tasks)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in autonomous skills corpus: {leaks}")

    resolved_backend, torch_available = _resolve_backend(backend)
    use_pytorch = resolved_backend == "pytorch"

    eff_phase_steps: Tuple[int, int, int] = (
        phase_steps
        if use_pytorch
        else (
            min(phase_steps[0], pure_phase_steps[0]),
            min(phase_steps[1], pure_phase_steps[1]),
            min(phase_steps[2], pure_phase_steps[2]),
        )
    )
    eff_ckpt_every = ckpt_every if use_pytorch else min(ckpt_every, pure_ckpt_every)
    eff_max_new_tokens = pytorch_max_new_tokens if use_pytorch else pure_max_new_tokens

    val_coding = _as_coding_tasks(val_tasks, category="validation")
    heldout_coding = _as_coding_tasks(heldout_tasks, category="unseen")
    all_skills = sorted({s for t in (train_tasks + val_tasks + heldout_tasks) for s in t.skills})

    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_autonomous_skills")
    run_root = base_dir / f"run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    runner = _run_seed_pytorch if use_pytorch else _run_seed_pure
    runs = [
        runner(
            seed=int(s),
            phase_steps=eff_phase_steps,
            ckpt_every=eff_ckpt_every,
            max_new_tokens=eff_max_new_tokens,
            max_attempts=max_attempts,
            train_tasks=train_tasks,
            val_coding=val_coding,
            heldout_coding=heldout_coding,
            leak_count=len(leaks),
            seed_dir=run_root / f"seed_{s}",
        )
        for s in seeds
    ]

    val_first = [r["post_autonomous_run"]["val_first_pass_rate"] for r in runs]
    val_final = [r["post_autonomous_run"]["val_final_pass_rate"] for r in runs]
    ho_first = [r["post_autonomous_run"]["heldout_first_pass_rate"] for r in runs]
    ho_final = [r["post_autonomous_run"]["heldout_final_pass_rate"] for r in runs]
    val_losses = [
        float(r["post_autonomous_run"]["val_loss"])
        for r in runs
        if r["post_autonomous_run"]["val_loss"] is not None
    ]
    ho_losses = [
        float(r["post_autonomous_run"]["heldout_loss"])
        for r in runs
        if r["post_autonomous_run"]["heldout_loss"] is not None
    ]
    approved_seeds = [r["seed"] for r in runs if r["post_autonomous_run"]["approved"]]
    all_approved = bool(runs) and len(approved_seeds) == len(runs)

    manifest: Dict[str, Any] = {
        "suite": "zyrquen_autonomous_agent_skills_verified_learning",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "torch_available": torch_available,
        "external_models_used": False,
        "init_mode": "random_initialization_native_only",
        "covered_skills": all_skills,
        "leakage_count": len(leaks),
        "max_attempts": max_attempts,
        "effective_phase_steps": list(eff_phase_steps),
        "checkpoint_every": eff_ckpt_every,
        "max_new_tokens": eff_max_new_tokens,
        "elapsed_sec": round(time.time() - t0, 2),
        "seeds": [int(s) for s in seeds],
        "split_counts": {
            "train": len(train_tasks),
            "val": len(val_tasks),
            "heldout": len(heldout_tasks),
        },
        "summary": {
            "mean_val_first_pass_rate": round(sum(val_first) / max(len(val_first), 1), 4),
            "mean_val_final_pass_rate": round(sum(val_final) / max(len(val_final), 1), 4),
            "mean_val_loss": round(sum(val_losses) / max(len(val_losses), 1), 4) if val_losses else None,
            "mean_heldout_first_pass_rate": round(sum(ho_first) / max(len(ho_first), 1), 4),
            "mean_heldout_final_pass_rate": round(sum(ho_final) / max(len(ho_final), 1), 4),
            "min_heldout_final_pass_rate": round(min(ho_final), 4) if ho_final else 0.0,
            "mean_heldout_loss": round(sum(ho_losses) / max(len(ho_losses), 1), 4) if ho_losses else None,
            "heldout_first_error_breakdown": {
                k: sum(int(r["post_autonomous_run"]["heldout_first_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "heldout_final_error_breakdown": {
                k: sum(int(r["post_autonomous_run"]["heldout_final_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "approved_seeds": approved_seeds,
            "any_approved": bool(approved_seeds),
            "overall_approval_status": "APPROVED" if all_approved else "REJECTED_BY_GATE",
        },
        "runs": runs,
    }
    manifest_path = run_root / "manifest_autonomous_skills.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    manifest["manifest_sha256"] = _sha256_file(manifest_path)
    return manifest


def _parse_int_tuple(raw: str, expected_len: Optional[int] = None) -> Tuple[int, ...]:
    vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not vals:
        raise ValueError("Expected comma-separated integers")
    if expected_len is not None and len(vals) != expected_len:
        raise ValueError(f"Expected {expected_len} comma-separated integers")
    return tuple(vals)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run ZYRQUEN V2 Autonomous Agent Skills & Verified Experience Replay Suite"
    )
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--phase-steps", default="900,900,900")
    ap.add_argument("--ckpt-every", type=int, default=450)
    ap.add_argument("--pure-phase-steps", default="8,8,8")
    ap.add_argument("--pure-ckpt-every", type=int, default=4)
    ap.add_argument("--pure-max-new-tokens", type=int, default=24)
    ap.add_argument("--pytorch-max-new-tokens", type=int, default=96)
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    try:
        ps = _parse_int_tuple(args.phase_steps, 3)
        pps = _parse_int_tuple(args.pure_phase_steps, 3)
        res = run_autonomous_agent_skills(
            seeds=_parse_int_tuple(args.seeds),
            phase_steps=(ps[0], ps[1], ps[2]),
            ckpt_every=args.ckpt_every,
            pure_phase_steps=(pps[0], pps[1], pps[2]),
            pure_ckpt_every=args.pure_ckpt_every,
            pure_max_new_tokens=args.pure_max_new_tokens,
            pytorch_max_new_tokens=args.pytorch_max_new_tokens,
            max_attempts=args.max_attempts,
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
                "torch_available": res["torch_available"],
                "init_mode": res["init_mode"],
                "covered_skills": res["covered_skills"],
                "leakage_count": res["leakage_count"],
                "max_attempts": res["max_attempts"],
                "effective_phase_steps": res["effective_phase_steps"],
                "manifest_path": res["manifest_path"],
                "manifest_sha256": res["manifest_sha256"],
                "elapsed_sec": res["elapsed_sec"],
                "split_counts": res["split_counts"],
                "summary": res["summary"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    for r in res["runs"]:
        p = r["post_autonomous_run"]
        print(f"\n=== SEED {r['seed']} (status={p['status']}) ===")
        print("heldout_first_errors:", p["heldout_first_errors"])
        print("heldout_final_errors:", p["heldout_final_errors"])
        for item in p["heldout_details"]:
            print(
                f"  [heldout] {item['task_id']} ({item['family']}) "
                f"first={item['first_attempt_passed']} final={item['passed']} "
                f"attempts={item['attempts_used']} info={item['info']!r}"
            )
            print(f"    raw_output: {item['raw_output']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
