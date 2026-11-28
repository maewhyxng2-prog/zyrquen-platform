"""ZYRQUEN V2 Full 10-General-Skills Continual Suite with Self-Correction & Verification Loop.

Extends the 10-General-Skills evaluation with:
  - Expanded corpus (~29 tasks: 24 train across 7 disjoint families, 2 val, 3 held-out)
  - `SelfCorrectingSandboxEvaluator(max_attempts=2)` tracking both `first_pass`
    and `final_pass` after sandbox error feedback
  - Strict family isolation and `detect_task_leakage == []` verification
  - Random-initialization Native-Only training (`NativeTransformerLMV2` / `ContinualTrainerV2`
    or `PureNativeTransformerLMV2` / `PureContinualTrainerV2` when PyTorch is absent)
  - Multi-stage continual training with `replay_ratio=0.5`, `consolidation_lambda=0.01`,
    SHA-256 checkpoint verification, NaN/Inf halt, and fail-closed `ApprovalGate`
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

DEFAULT_FULL_GENERAL_SEEDS: Tuple[int, ...] = (42, 1337, 2026)
STAGE_ORDER: Tuple[str, str, str] = (
    "reasoning_math_prog",
    "tool_research_file_comp",
    "learn_recovery_gen",
)


@dataclass(frozen=True)
class RichSkillTask:
    task_id: str
    family: str
    skills: Tuple[str, ...]
    split: str  # "train" | "val" | "heldout"
    stage_group: str  # "reasoning_math_prog" | "tool_research_file_comp" | "learn_recovery_gen"
    prompt: str
    target_code: str
    test_code: str

    @property
    def full_text(self) -> str:
        return self.prompt + self.target_code


def build_rich_10_skill_corpus() -> (
    Tuple[List[RichSkillTask], List[RichSkillTask], List[RichSkillTask]]
):
    """Build rich train / val / heldout tasks covering 10 general skills with strict family isolation."""
    train_tasks: List[RichSkillTask] = [
        # --- Family: reasoning_math (Reasoning, Mathematics) ---
        RichSkillTask(
            "r10_rm_1",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "reasoning_math_prog",
            "# Skills [Reasoning, Mathematics]: fee is 0 if x<=0, 5 if x<=100, else 15\ndef calc_fee(x):\n    return ",
            "0 if x <= 0 else (5 if x <= 100 else 15)\n",
            "assert calc_fee(-5) == 0 and calc_fee(0) == 0 and calc_fee(80) == 5 and calc_fee(150) == 15",
        ),
        RichSkillTask(
            "r10_rm_2",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "reasoning_math_prog",
            "# Skills [Reasoning, Mathematics]: sum squares of positive numbers\ndef pos_squares_sum(nums):\n    return ",
            "sum(n * n for n in nums if n > 0)\n",
            "assert pos_squares_sum([-2, 3, 4]) == 25 and pos_squares_sum([]) == 0",
        ),
        RichSkillTask(
            "r10_rm_3",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "reasoning_math_prog",
            "# Skills [Reasoning, Mathematics]: clamp integer into [lo, hi]\ndef clamp_int(v, lo, hi):\n    return ",
            "max(lo, min(hi, v))\n",
            "assert clamp_int(-10, 0, 50) == 0 and clamp_int(90, 0, 50) == 50 and clamp_int(25, 0, 50) == 25",
        ),
        RichSkillTask(
            "r10_rm_4",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "reasoning_math_prog",
            "# Skills [Reasoning, Mathematics]: count odd numbers in list\ndef count_odds(vals):\n    return ",
            "sum(1 for v in vals if v % 2 != 0)\n",
            "assert count_odds([1, 2, 3, 4, 5]) == 3 and count_odds([2, 4]) == 0",
        ),
        RichSkillTask(
            "r10_rm_5",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "reasoning_math_prog",
            "# Skills [Reasoning, Mathematics]: weighted total sum(x * w) or 0 if empty\ndef weighted_sum(xs, w):\n    return ",
            "0 if not xs else sum(x * w for x in xs)\n",
            "assert weighted_sum([2, 5], 3) == 21 and weighted_sum([], 3) == 0",
        ),
        # --- Family: prog_debug (Programming) ---
        RichSkillTask(
            "r10_pd_1",
            "prog_debug",
            ("Programming",),
            "train",
            "reasoning_math_prog",
            "# Skill [Programming]: reverse space-separated words\ndef rev_words(s):\n    return ",
            "' '.join(reversed(s.split()))\n",
            "assert rev_words('alpha beta gamma') == 'gamma beta alpha'",
        ),
        RichSkillTask(
            "r10_pd_2",
            "prog_debug",
            ("Programming",),
            "train",
            "reasoning_math_prog",
            "# Skill [Programming]: count vowels case-insensitively\ndef num_vowels(text):\n    return ",
            "sum(1 for ch in text.lower() if ch in 'aeiou')\n",
            "assert num_vowels('AEIOUbc') == 5 and num_vowels('') == 0",
        ),
        RichSkillTask(
            "r10_pd_3",
            "prog_debug",
            ("Programming",),
            "train",
            "reasoning_math_prog",
            "# Skill [Programming]: filter out None items\ndef strip_none(items):\n    return ",
            "[x for x in items if x is not None]\n",
            "assert strip_none([1, None, 2, None, 3]) == [1, 2, 3]",
        ),
        RichSkillTask(
            "r10_pd_4",
            "prog_debug",
            ("Programming",),
            "train",
            "reasoning_math_prog",
            "# Skill [Programming]: take first k items after sorting ascending\ndef top_k_asc(vals, k):\n    return ",
            "[] if k <= 0 else sorted(vals)[:k]\n",
            "assert top_k_asc([9, 3, 7, 1], 2) == [1, 3] and top_k_asc([4, 2], 0) == []",
        ),
        # --- Family: tool_research (Tool Use, Research) ---
        RichSkillTask(
            "r10_tr_1",
            "tool_research",
            ("Tool Use", "Research"),
            "train",
            "tool_research_file_comp",
            "# Skills [Tool Use, Research]: call lookup_fn(key) and return default if None\ndef lookup_or_default(lookup_fn, key, default):\n    return ",
            "default if lookup_fn(key) is None else lookup_fn(key)\n",
            "assert lookup_or_default(lambda k: {'k1': 42}.get(k), 'k1', 0) == 42 and lookup_or_default(lambda k: {'k1': 42}.get(k), 'miss', -1) == -1",
        ),
        RichSkillTask(
            "r10_tr_2",
            "tool_research",
            ("Tool Use", "Research"),
            "train",
            "tool_research_file_comp",
            "# Skills [Tool Use, Research]: keep items where pred_fn(item) is True\ndef filter_by_pred(items, pred_fn):\n    return ",
            "[it for it in items if pred_fn(it)]\n",
            "assert filter_by_pred(['err_1', 'ok_2', 'err_3'], lambda s: s.startswith('err_')) == ['err_1', 'err_3']",
        ),
        RichSkillTask(
            "r10_tr_3",
            "tool_research",
            ("Tool Use", "Research"),
            "train",
            "tool_research_file_comp",
            "# Skills [Tool Use, Research]: max metric_fn(x) over non-empty items or 0\ndef best_metric(items, metric_fn):\n    return ",
            "0 if not items else max(metric_fn(x) for x in items)\n",
            "assert best_metric(['a', 'abcd', 'ab'], len) == 4 and best_metric([], len) == 0",
        ),
        # --- Family: file_data (File & Data) ---
        RichSkillTask(
            "r10_fd_1",
            "file_data",
            ("File & Data",),
            "train",
            "tool_research_file_comp",
            "# Skill [File & Data]: split comma line, trim whitespace, drop empty tokens\ndef clean_csv_row(line):\n    return ",
            "[p.strip() for p in line.split(',') if p.strip()]\n",
            "assert clean_csv_row(' col1 , , col2 , col3 ') == ['col1', 'col2', 'col3']",
        ),
        RichSkillTask(
            "r10_fd_2",
            "file_data",
            ("File & Data",),
            "train",
            "tool_research_file_comp",
            "# Skill [File & Data]: count records where status == 'ok'\ndef count_ok_records(rows):\n    return ",
            "sum(1 for r in rows if r.get('status') == 'ok')\n",
            "assert count_ok_records([{'status': 'ok'}, {'status': 'fail'}, {'status': 'ok'}]) == 2",
        ),
        RichSkillTask(
            "r10_fd_3",
            "file_data",
            ("File & Data",),
            "train",
            "tool_research_file_comp",
            "# Skill [File & Data]: extract non-empty lowercase tags sorted ascending\ndef normalize_tags(tags):\n    return ",
            "sorted({t.strip().lower() for t in tags if t and t.strip()})\n",
            "assert normalize_tags([' Beta ', '', 'ALPHA', 'beta']) == ['alpha', 'beta']",
        ),
        # --- Family: comp_ops (Computer Operations) ---
        RichSkillTask(
            "r10_co_1",
            "comp_ops",
            ("Computer Operations",),
            "train",
            "tool_research_file_comp",
            "# Skill [Computer Operations]: return unique sorted command steps\ndef sorted_unique_steps(cmds):\n    return ",
            "sorted(set(cmds))\n",
            "assert sorted_unique_steps(['build', 'test', 'build', 'eval']) == ['build', 'eval', 'test']",
        ),
        RichSkillTask(
            "r10_co_2",
            "comp_ops",
            ("Computer Operations",),
            "train",
            "tool_research_file_comp",
            "# Skill [Computer Operations]: first element or fallback if sequence is empty\ndef first_or_fallback(seq, fallback):\n    return ",
            "seq[0] if len(seq) > 0 else fallback\n",
            "assert first_or_fallback([10, 20], 0) == 10 and first_or_fallback([], 0) == 0",
        ),
        RichSkillTask(
            "r10_co_3",
            "comp_ops",
            ("Computer Operations",),
            "train",
            "tool_research_file_comp",
            "# Skill [Computer Operations]: return non-empty strings up to limit k\ndef limit_non_empty(items, k):\n    return ",
            "[] if k <= 0 else [s for s in items if s][:k]\n",
            "assert limit_non_empty(['', 'a', 'b', 'c'], 2) == ['a', 'b']",
        ),
        # --- Family: learning_recovery (Learning, Recovery) ---
        RichSkillTask(
            "r10_lr_1",
            "learning_recovery",
            ("Learning", "Recovery"),
            "train",
            "learn_recovery_gen",
            "# Skills [Learning, Recovery]: safe division returning fallback when den == 0\ndef safe_div(a, b, fallback=0.0):\n    return ",
            "fallback if b == 0 else a / b\n",
            "assert safe_div(12, 4, -1.0) == 3.0 and safe_div(12, 0, -1.0) == -1.0",
        ),
        RichSkillTask(
            "r10_lr_2",
            "learning_recovery",
            ("Learning", "Recovery"),
            "train",
            "learn_recovery_gen",
            "# Skills [Learning, Recovery]: transform items with step_fn(x)\ndef map_with_step(items, step_fn):\n    return ",
            "[step_fn(x) for x in items]\n",
            "assert map_with_step([1, 2, 3], lambda x: x * 10) == [10, 20, 30]",
        ),
        RichSkillTask(
            "r10_lr_3",
            "learning_recovery",
            ("Learning", "Recovery"),
            "train",
            "learn_recovery_gen",
            "# Skills [Learning, Recovery]: sum values after replacing None with 0\ndef sum_with_zero_default(vals):\n    return ",
            "sum(0 if v is None else v for v in vals)\n",
            "assert sum_with_zero_default([5, None, 7, None]) == 12",
        ),
        # --- Family: generalization_core (Generalization) ---
        RichSkillTask(
            "r10_gc_1",
            "generalization_core",
            ("Generalization",),
            "train",
            "learn_recovery_gen",
            "# Skill [Generalization]: count items strictly greater than threshold\ndef count_above(nums, threshold):\n    return ",
            "sum(1 for n in nums if n > threshold)\n",
            "assert count_above([1, 5, 8, 2], 4) == 2 and count_above([], 0) == 0",
        ),
        RichSkillTask(
            "r10_gc_2",
            "generalization_core",
            ("Generalization",),
            "train",
            "learn_recovery_gen",
            "# Skill [Generalization]: join non-empty trimmed words with single space\ndef join_clean_words(words):\n    return ",
            "' '.join(w.strip() for w in words if w and w.strip())\n",
            "assert join_clean_words([' hi ', '', '  ', 'there ']) == 'hi there'",
        ),
        RichSkillTask(
            "r10_gc_3",
            "generalization_core",
            ("Generalization",),
            "train",
            "learn_recovery_gen",
            "# Skill [Generalization]: absolute difference between two numbers\ndef abs_gap(a, b):\n    return ",
            "abs(a - b)\n",
            "assert abs_gap(3, 10) == 7 and abs_gap(8, 2) == 6",
        ),
    ]

    val_tasks: List[RichSkillTask] = [
        RichSkillTask(
            "val_r10_1",
            "val_math_recovery",
            ("Reasoning", "Mathematics", "Recovery"),
            "val",
            "reasoning_math_prog",
            "# Skills [Reasoning, Mathematics, Recovery]: mean of nums or 0.0 if empty\ndef safe_avg(nums):\n    return ",
            "0.0 if len(nums) == 0 else sum(nums) / len(nums)\n",
            "assert abs(safe_avg([2.0, 6.0]) - 4.0) < 1e-6 and safe_avg([]) == 0.0",
        ),
        RichSkillTask(
            "val_r10_2",
            "val_data_gen",
            ("File & Data", "Generalization"),
            "val",
            "tool_research_file_comp",
            "# Skills [File & Data, Generalization]: sorted unique non-empty items\ndef sorted_dedup_items(items):\n    return ",
            "sorted({it for it in items if it})\n",
            "assert sorted_dedup_items(['b', '', 'a', 'b']) == ['a', 'b']",
        ),
    ]

    heldout_tasks: List[RichSkillTask] = [
        RichSkillTask(
            "held_r10_1",
            "held_reasoning_math",
            ("Reasoning", "Mathematics", "Recovery"),
            "heldout",
            "learn_recovery_gen",
            "# Skills [Reasoning, Mathematics, Recovery]: mean of numbers or 0.0 if empty\ndef avg_or_zero(vals):\n    return ",
            "0.0 if len(vals) == 0 else sum(vals) / len(vals)\n",
            "assert abs(avg_or_zero([2.0, 4.0, 6.0]) - 4.0) < 1e-6 and avg_or_zero([]) == 0.0",
        ),
        RichSkillTask(
            "held_r10_2",
            "held_data_generalization",
            ("File & Data", "Generalization", "Learning"),
            "heldout",
            "learn_recovery_gen",
            "# Skills [File & Data, Generalization, Learning]: unique items sorted ascending\ndef distinct_ordered(seq):\n    return ",
            "sorted(set(seq))\n",
            "assert distinct_ordered([4, 2, 4, 1, 2]) == [1, 2, 4] and distinct_ordered([]) == []",
        ),
        RichSkillTask(
            "held_r10_3",
            "held_comp_recovery_math",
            ("Computer Operations", "Recovery", "Mathematics"),
            "heldout",
            "learn_recovery_gen",
            "# Skills [Computer Operations, Recovery, Mathematics]: max minus min or 0 if empty\ndef diff_range(nums):\n    return ",
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


def _as_coding_tasks(items: Sequence[RichSkillTask], *, category: str) -> List[CodingTask]:
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


def verify_full_general_skills_leakage(
    train_tasks: Sequence[RichSkillTask],
    val_tasks: Sequence[RichSkillTask],
    heldout_tasks: Sequence[RichSkillTask],
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


class SelfCorrectingSandboxEvaluator:
    """Evaluates tasks with verification + self-correction retry loop in sandbox."""

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
        """Returns (first_pass_report, final_after_self_correction_report)."""
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
            tail_line = prompt_lines[-1] if prompt_lines else ""
            while (not cur_ok) and (cur_attempt < self.max_attempts):
                cur_attempt += 1
                repair_prompt = (
                    f"{task.prompt.rstrip()}\n# Self-Correction attempt {cur_attempt} after {cur_info}\n"
                    f"{tail_line} "
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
        first_report = EvalReport(
            avg_loss=rounded_loss,
            exec_pass_rate=round(first_passed / len(tasks), 4),
            passed_count=first_passed,
            total_count=len(tasks),
            details=first_details,
            error_breakdown=_error_summary(first_details),
        )
        final_report = EvalReport(
            avg_loss=rounded_loss,
            exec_pass_rate=round(final_passed / len(tasks), 4),
            passed_count=final_passed,
            total_count=len(tasks),
            details=final_details,
            error_breakdown=_error_summary(final_details),
        )
        return first_report, final_report


def _run_seed_pytorch(
    *,
    seed: int,
    stage_steps: Tuple[int, int, int],
    ckpt_every: int,
    max_new_tokens: int,
    max_attempts: int,
    train_tasks: List[RichSkillTask],
    val_coding: List[CodingTask],
    heldout_coding: List[CodingTask],
    leak_count: int,
    seed_dir: Path,
) -> Dict[str, Any]:
    import torch
    import torch.nn.functional as F
    from v2.tpu_backend import resolve_torch_device
    from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config

    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(seed)
    random.seed(seed)
    device = resolve_torch_device()
    tok = ByteTokenizer()

    stage_texts = {
        stg: [x.full_text for x in train_tasks if x.stage_group == stg]
        for stg in STAGE_ORDER
    }

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
        total_decay_steps=sum(stage_steps) + 150,
        consolidation_lambda=0.01,
        seed=seed,
        device=device,
    )

    def make_eval(m: NativeTransformerLMV2) -> SelfCorrectingSandboxEvaluator:
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

        return SelfCorrectingSandboxEvaluator(gen_fn, loss_fn, max_attempts=max_attempts)

    pre_ev = make_eval(trainer.model)
    pre_val_1, pre_val_final = pre_ev.evaluate(val_coding)
    pre_ho_1, pre_ho_final = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    stage_history: List[Dict[str, Any]] = []
    baseline_val_report = pre_val_final

    for idx, (stg, n_steps) in enumerate(zip(STAGE_ORDER, stage_steps)):
        texts = stage_texts[stg]
        done = 0
        while done < n_steps:
            chunk = min(ckpt_every, n_steps - done)
            trainer.train_steps(
                texts, steps=chunk, batch_size=4, replay_ratio=0.0 if idx == 0 else 0.5
            )
            done += chunk
            p, sha = trainer.save_checkpoint(ckpt_dir / f"{stg}_step_{done}.pt")
            checkpoints.append({"stage": stg, "step": done, "path": str(p), "sha256": sha})

        trainer.snapshot_consolidation_state(texts, batch_size=4)
        p_stg, sha_stg = trainer.save_checkpoint(ckpt_dir / f"{stg}_final.pt")
        ev = make_eval(trainer.model)
        cur_v1, cur_vf = ev.evaluate(val_coding)
        cur_h1, cur_hf = ev.evaluate(heldout_coding)
        if idx == 0:
            baseline_val_report = cur_vf
        stage_history.append(
            {
                "stage": stg,
                "checkpoint": str(p_stg),
                "sha256": sha_stg,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
                "heldout_first_pass_rate": cur_h1.exec_pass_rate,
                "heldout_final_pass_rate": cur_hf.exec_pass_rate,
                "heldout_loss": cur_hf.avg_loss,
                "heldout_final_errors": cur_hf.error_breakdown,
            }
        )
        if idx < len(STAGE_ORDER) - 1:
            trainer = ContinualTrainerV2.load_checkpoint(
                p_stg,
                tok,
                expected_sha256=sha_stg,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=0.01,
                device=device,
            )
            trainer.model.extend_context(1024)

    final_ckpt = Path(stage_history[-1]["checkpoint"])
    final_sha = str(stage_history[-1]["sha256"])
    post_ev = make_eval(trainer.model)
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
            "suite": "zyrquen_full_10_general_skills_self_correct",
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
        "stage_history": stage_history,
        "post_all_stages": {
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
    stage_steps: Tuple[int, int, int],
    ckpt_every: int,
    max_new_tokens: int,
    max_attempts: int,
    train_tasks: List[RichSkillTask],
    val_coding: List[CodingTask],
    heldout_coding: List[CodingTask],
    leak_count: int,
    seed_dir: Path,
) -> Dict[str, Any]:
    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    tok = ByteTokenizer()

    stage_texts = {
        stg: [x.full_text for x in train_tasks if x.stage_group == stg]
        for stg in STAGE_ORDER
    }

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
        total_decay_steps=max(sum(stage_steps) + 12, 36),
        consolidation_lambda=0.01,
        seed=seed,
    )

    def make_eval(m: PureNativeTransformerLMV2) -> SelfCorrectingSandboxEvaluator:
        return SelfCorrectingSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tok, prompt, max_new_tokens=max_new_tokens
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tok, texts)["loss"]),
            max_attempts=max_attempts,
        )

    pre_ev = make_eval(trainer.model)
    pre_val_1, pre_val_final = pre_ev.evaluate(val_coding)
    pre_ho_1, pre_ho_final = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    stage_history: List[Dict[str, Any]] = []
    baseline_val_report = pre_val_final

    for idx, (stg, n_steps) in enumerate(zip(STAGE_ORDER, stage_steps)):
        texts = stage_texts[stg]
        done = 0
        while done < n_steps:
            chunk = min(ckpt_every, n_steps - done)
            trainer.train_steps(
                texts, steps=chunk, batch_size=2, replay_ratio=0.0 if idx == 0 else 0.5
            )
            done += chunk
            p, sha = trainer.save_checkpoint(ckpt_dir / f"{stg}_step_{done}.json.gz")
            checkpoints.append({"stage": stg, "step": done, "path": str(p), "sha256": sha})

        if _has_non_finite_pure(trainer.model.params):
            raise RuntimeError(f"Training halted: NaN/Inf detected during stage {stg}")

        trainer.snapshot_consolidation_state(texts)
        p_stg, sha_stg = trainer.save_checkpoint(ckpt_dir / f"{stg}_final.json.gz")
        ev = make_eval(trainer.model)
        cur_v1, cur_vf = ev.evaluate(val_coding)
        cur_h1, cur_hf = ev.evaluate(heldout_coding)
        if idx == 0:
            baseline_val_report = cur_vf
        stage_history.append(
            {
                "stage": stg,
                "checkpoint": str(p_stg),
                "sha256": sha_stg,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
                "heldout_first_pass_rate": cur_h1.exec_pass_rate,
                "heldout_final_pass_rate": cur_hf.exec_pass_rate,
                "heldout_loss": cur_hf.avg_loss,
                "heldout_final_errors": cur_hf.error_breakdown,
            }
        )
        if idx < len(STAGE_ORDER) - 1:
            trainer = PureContinualTrainerV2.load_checkpoint(
                p_stg,
                tokenizer=tok,
                expected_sha256=sha_stg,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=0.01,
            )
            trainer.model.extend_context(512 if idx == 0 else 768)

    final_ckpt = Path(stage_history[-1]["checkpoint"])
    final_sha = str(stage_history[-1]["sha256"])
    post_ev = make_eval(trainer.model)
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
            "suite": "zyrquen_full_10_general_skills_self_correct",
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
        "stage_history": stage_history,
        "post_all_stages": {
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


def run_full_general_skills_suite(
    seeds: Sequence[int] = DEFAULT_FULL_GENERAL_SEEDS,
    stage_steps: Tuple[int, int, int] = (900, 900, 900),
    ckpt_every: int = 450,
    pure_stage_steps: Tuple[int, int, int] = (12, 12, 12),
    pure_ckpt_every: int = 6,
    pure_max_new_tokens: int = 32,
    pytorch_max_new_tokens: int = 96,
    max_attempts: int = 2,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    train_tasks, val_tasks, heldout_tasks = build_rich_10_skill_corpus()
    leaks = verify_full_general_skills_leakage(train_tasks, val_tasks, heldout_tasks)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in full general skills corpus: {leaks}")

    resolved_backend, torch_available = _resolve_backend(backend)
    use_pytorch = resolved_backend == "pytorch"

    eff_stage_steps: Tuple[int, int, int] = (
        stage_steps
        if use_pytorch
        else (
            min(stage_steps[0], pure_stage_steps[0]),
            min(stage_steps[1], pure_stage_steps[1]),
            min(stage_steps[2], pure_stage_steps[2]),
        )
    )
    eff_ckpt_every = ckpt_every if use_pytorch else min(ckpt_every, pure_ckpt_every)
    eff_max_new_tokens = pytorch_max_new_tokens if use_pytorch else pure_max_new_tokens

    val_coding = _as_coding_tasks(val_tasks, category="validation")
    heldout_coding = _as_coding_tasks(heldout_tasks, category="unseen")
    all_skills = sorted({s for t in (train_tasks + val_tasks + heldout_tasks) for s in t.skills})

    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_full_10_skills")
    run_root = base_dir / f"run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    runner = _run_seed_pytorch if use_pytorch else _run_seed_pure
    runs = [
        runner(
            seed=int(s),
            stage_steps=eff_stage_steps,
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

    val_first = [r["post_all_stages"]["val_first_pass_rate"] for r in runs]
    val_final = [r["post_all_stages"]["val_final_pass_rate"] for r in runs]
    ho_first = [r["post_all_stages"]["heldout_first_pass_rate"] for r in runs]
    ho_final = [r["post_all_stages"]["heldout_final_pass_rate"] for r in runs]
    val_losses = [
        float(r["post_all_stages"]["val_loss"])
        for r in runs
        if r["post_all_stages"]["val_loss"] is not None
    ]
    ho_losses = [
        float(r["post_all_stages"]["heldout_loss"])
        for r in runs
        if r["post_all_stages"]["heldout_loss"] is not None
    ]
    approved_seeds = [r["seed"] for r in runs if r["post_all_stages"]["approved"]]
    all_approved = bool(runs) and len(approved_seeds) == len(runs)

    manifest: Dict[str, Any] = {
        "suite": "zyrquen_full_10_general_skills_self_correct",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "torch_available": torch_available,
        "external_models_used": False,
        "init_mode": "random_initialization_native_only",
        "covered_skills": all_skills,
        "leakage_count": len(leaks),
        "max_attempts": max_attempts,
        "effective_stage_steps": list(eff_stage_steps),
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
                k: sum(int(r["post_all_stages"]["heldout_first_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "heldout_final_error_breakdown": {
                k: sum(int(r["post_all_stages"]["heldout_final_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "approved_seeds": approved_seeds,
            "any_approved": bool(approved_seeds),
            "overall_approval_status": "APPROVED" if all_approved else "REJECTED_BY_GATE",
        },
        "runs": runs,
    }
    manifest_path = run_root / "manifest_full_10_skills.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    manifest["manifest_sha256"] = _sha256_file(manifest_path)
    return manifest


def _parse_seeds(raw: str) -> Tuple[int, ...]:
    vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not vals:
        raise ValueError("Expected comma-separated seed integers")
    return tuple(vals)


def _parse_stage_steps(raw: str) -> Tuple[int, int, int]:
    vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if len(vals) != 3:
        raise ValueError("Expected 3 comma-separated integers for stage steps")
    return (vals[0], vals[1], vals[2])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run ZYRQUEN V2 Full 10-General-Skills Continual Suite with Self-Correction"
    )
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--stage-steps", default="900,900,900")
    ap.add_argument("--ckpt-every", type=int, default=450)
    ap.add_argument("--pure-stage-steps", default="12,12,12")
    ap.add_argument("--pure-ckpt-every", type=int, default=6)
    ap.add_argument("--pure-max-new-tokens", type=int, default=32)
    ap.add_argument("--pytorch-max-new-tokens", type=int, default=96)
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    try:
        res = run_full_general_skills_suite(
            seeds=_parse_seeds(args.seeds),
            stage_steps=_parse_stage_steps(args.stage_steps),
            ckpt_every=args.ckpt_every,
            pure_stage_steps=_parse_stage_steps(args.pure_stage_steps),
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
                "effective_stage_steps": res["effective_stage_steps"],
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
        p = r["post_all_stages"]
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
