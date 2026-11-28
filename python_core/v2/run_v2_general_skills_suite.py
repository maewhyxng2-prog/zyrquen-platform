"""ZYRQUEN V2 10-General-Skills Continual Training & Sandbox Suite.

Covers 10 general skills across strictly isolated Task Families:
  - Skills: Reasoning, Programming, Tool Use, Research, Mathematics,
            File & Data, Computer Operations, Learning, Recovery, Generalization
  - Stage 1 (`core_reasoning_math_prog`): reasoning_math, prog_recovery
  - Stage 2 (`ops_data_research_comp`): tool_research, file_data, comp_ops (replay=0.5)
  - Stage 3 (`learn_recovery_gen`): learning_adapt, generalization_core (replay=0.5)
  - Validation Family: val_multi_skill
  - Held-out Families: held_reasoning_math, held_recovery_data, held_generalization_ops

Enforces random initialization only (zero external models), `detect_task_leakage == []`,
SHA-256 checkpoint reload across stages, RoPE context extension, NaN/Inf halt,
per-stage `stage_history`, `val_errors`, `heldout_errors`, `raw_output`, and
fail-closed `ApprovalGate`.
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

DEFAULT_GENERAL_SEEDS: Tuple[int, ...] = (42, 1337, 2026)
STAGE_ORDER: Tuple[str, str, str] = (
    "core_reasoning_math_prog",
    "ops_data_research_comp",
    "learn_recovery_gen",
)


@dataclass(frozen=True)
class GeneralSkillTask:
    task_id: str
    family: str
    skills: Tuple[str, ...]
    split: str  # "train" | "val" | "heldout"
    stage_group: str  # "core_reasoning_math_prog" | "ops_data_research_comp" | "learn_recovery_gen"
    prompt: str
    target_code: str
    test_code: str

    @property
    def full_text(self) -> str:
        return self.prompt + self.target_code


def build_general_skills_corpus() -> (
    Tuple[List[GeneralSkillTask], List[GeneralSkillTask], List[GeneralSkillTask]]
):
    """Build train / val / heldout tasks across 10 general skills with strict family isolation."""
    train_tasks: List[GeneralSkillTask] = [
        # --- reasoning_math ---
        GeneralSkillTask(
            "gs_rm_1",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "core_reasoning_math_prog",
            "# Skill [Reasoning, Mathematics]: tier fee by amount (0 if <= 0, 5 if <= 100, else 15)\ndef tier_fee(amount):\n    return ",
            "0 if amount <= 0 else (5 if amount <= 100 else 15)\n",
            "assert tier_fee(0) == 0 and tier_fee(50) == 5 and tier_fee(200) == 15",
        ),
        GeneralSkillTask(
            "gs_rm_2",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "core_reasoning_math_prog",
            "# Skill [Reasoning, Mathematics]: sum of even numbers in vals\ndef sum_even_vals(vals):\n    return ",
            "sum(x for x in vals if x % 2 == 0)\n",
            "assert sum_even_vals([1, 2, 3, 4, 6]) == 12 and sum_even_vals([]) == 0",
        ),
        GeneralSkillTask(
            "gs_rm_3",
            "reasoning_math",
            ("Reasoning", "Mathematics"),
            "train",
            "core_reasoning_math_prog",
            "# Skill [Reasoning, Mathematics]: clamp score into [0, 100]\ndef norm_score(score):\n    return ",
            "max(0, min(100, score))\n",
            "assert norm_score(-10) == 0 and norm_score(120) == 100 and norm_score(75) == 75",
        ),
        # --- prog_recovery ---
        GeneralSkillTask(
            "gs_pr_1",
            "prog_recovery",
            ("Programming", "Recovery"),
            "train",
            "core_reasoning_math_prog",
            "# Skill [Programming, Recovery]: safe divide with fallback when denom is 0\ndef safe_div_fallback(num, den, fallback=0.0):\n    return ",
            "fallback if den == 0 else num / den\n",
            "assert safe_div_fallback(9, 3, -1.0) == 3.0 and safe_div_fallback(9, 0, -1.0) == -1.0",
        ),
        GeneralSkillTask(
            "gs_pr_2",
            "prog_recovery",
            ("Programming", "Recovery"),
            "train",
            "core_reasoning_math_prog",
            "# Skill [Programming, Recovery]: first element or fallback if empty\ndef first_or_default(items, default):\n    return ",
            "items[0] if len(items) > 0 else default\n",
            "assert first_or_default(['x', 'y'], 'none') == 'x' and first_or_default([], 'none') == 'none'",
        ),
        GeneralSkillTask(
            "gs_pr_3",
            "prog_recovery",
            ("Programming", "Recovery"),
            "train",
            "core_reasoning_math_prog",
            "# Skill [Programming, Recovery]: filter out None values before summing\ndef sum_non_none(items):\n    return ",
            "sum(x for x in items if x is not None)\n",
            "assert sum_non_none([2, None, 8, None]) == 10",
        ),
        # --- tool_research ---
        GeneralSkillTask(
            "gs_tr_1",
            "tool_research",
            ("Tool Use", "Research"),
            "train",
            "ops_data_research_comp",
            "# Skill [Tool Use, Research]: use lookup_fn(key) and return default if None\ndef query_or_default(lookup_fn, key, default):\n    return ",
            "default if lookup_fn(key) is None else lookup_fn(key)\n",
            "assert query_or_default(lambda k: {'a': 3}.get(k), 'a', 0) == 3 and query_or_default(lambda k: {'a': 3}.get(k), 'z', -1) == -1",
        ),
        GeneralSkillTask(
            "gs_tr_2",
            "tool_research",
            ("Tool Use", "Research"),
            "train",
            "ops_data_research_comp",
            "# Skill [Tool Use, Research]: collect matching items using match_fn(item) -> bool\ndef select_matches(items, match_fn):\n    return ",
            "[it for it in items if match_fn(it)]\n",
            "assert select_matches(['py_core', 'readme', 'py_test'], lambda s: s.startswith('py_')) == ['py_core', 'py_test']",
        ),
        # --- file_data ---
        GeneralSkillTask(
            "gs_fd_1",
            "file_data",
            ("File & Data",),
            "train",
            "ops_data_research_comp",
            "# Skill [File & Data]: clean comma-separated non-empty tokens\ndef parse_csv_tokens(raw_line):\n    return ",
            "[tok.strip() for tok in raw_line.split(',') if tok.strip()]\n",
            "assert parse_csv_tokens(' a , , b , c ') == ['a', 'b', 'c']",
        ),
        GeneralSkillTask(
            "gs_fd_2",
            "file_data",
            ("File & Data",),
            "train",
            "ops_data_research_comp",
            "# Skill [File & Data]: count active records where flag is truthy\ndef count_active(records):\n    return ",
            "sum(1 for r in records if r.get('active'))\n",
            "assert count_active([{'active': True}, {'active': False}, {'active': 1}]) == 2",
        ),
        # --- comp_ops ---
        GeneralSkillTask(
            "gs_co_1",
            "comp_ops",
            ("Computer Operations",),
            "train",
            "ops_data_research_comp",
            "# Skill [Computer Operations]: return sorted unique step names\ndef ordered_steps(steps):\n    return ",
            "sorted(set(steps))\n",
            "assert ordered_steps(['verify', 'plan', 'exec', 'plan']) == ['exec', 'plan', 'verify']",
        ),
        GeneralSkillTask(
            "gs_co_2",
            "comp_ops",
            ("Computer Operations",),
            "train",
            "ops_data_research_comp",
            "# Skill [Computer Operations]: take top k items after removing empty strings\ndef top_non_empty(items, k):\n    return ",
            "[] if k <= 0 else [s for s in items if s][:k]\n",
            "assert top_non_empty(['', 's1', 's2', 's3'], 2) == ['s1', 's2']",
        ),
        # --- learning_adapt ---
        GeneralSkillTask(
            "gs_la_1",
            "learning_adapt",
            ("Learning",),
            "train",
            "learn_recovery_gen",
            "# Skill [Learning]: apply rule_fn to each value in seq\ndef adapt_seq(seq, rule_fn):\n    return ",
            "[rule_fn(v) for v in seq]\n",
            "assert adapt_seq([1, 2, 3], lambda v: v + 10) == [11, 12, 13]",
        ),
        GeneralSkillTask(
            "gs_la_2",
            "learning_adapt",
            ("Learning",),
            "train",
            "learn_recovery_gen",
            "# Skill [Learning]: count items that pass verify_fn\ndef count_verified(items, verify_fn):\n    return ",
            "sum(1 for x in items if verify_fn(x))\n",
            "assert count_verified([10, -1, 5, 0], lambda x: x > 0) == 2",
        ),
        # --- generalization_core ---
        GeneralSkillTask(
            "gs_gc_1",
            "generalization_core",
            ("Generalization",),
            "train",
            "learn_recovery_gen",
            "# Skill [Generalization]: reverse words joined by single space\ndef invert_phrase(phrase):\n    return ",
            "' '.join(reversed(phrase.split()))\n",
            "assert invert_phrase('one two three') == 'three two one'",
        ),
        GeneralSkillTask(
            "gs_gc_2",
            "generalization_core",
            ("Generalization",),
            "train",
            "learn_recovery_gen",
            "# Skill [Generalization]: count lowercase vowels in text\ndef tally_vowels(text):\n    return ",
            "sum(1 for c in text.lower() if c in 'aeiou')\n",
            "assert tally_vowels('AbCdEf') == 2",
        ),
    ]

    val_tasks: List[GeneralSkillTask] = [
        GeneralSkillTask(
            "val_gs_1",
            "val_multi_skill",
            ("Reasoning", "Mathematics", "Recovery"),
            "val",
            "core_reasoning_math_prog",
            "# Skill [Reasoning, Mathematics, Recovery]: average of nums or 0.0 if empty\ndef safe_avg(nums):\n    return ",
            "0.0 if len(nums) == 0 else sum(nums) / len(nums)\n",
            "assert abs(safe_avg([2.0, 6.0]) - 4.0) < 1e-6 and safe_avg([]) == 0.0",
        ),
        GeneralSkillTask(
            "val_gs_2",
            "val_multi_skill",
            ("File & Data", "Generalization"),
            "val",
            "ops_data_research_comp",
            "# Skill [File & Data, Generalization]: sorted unique non-empty tags\ndef clean_tags(tags):\n    return ",
            "sorted({t.strip() for t in tags if t and t.strip()})\n",
            "assert clean_tags([' b ', '', ' a ', 'b']) == ['a', 'b']",
        ),
    ]

    heldout_tasks: List[GeneralSkillTask] = [
        GeneralSkillTask(
            "held_gs_1",
            "held_reasoning_math",
            ("Reasoning", "Mathematics"),
            "heldout",
            "learn_recovery_gen",
            "# Skill [Reasoning, Mathematics]: mean of numbers or 0.0 if empty\ndef avg_or_zero(vals):\n    return ",
            "0.0 if len(vals) == 0 else sum(vals) / len(vals)\n",
            "assert abs(avg_or_zero([2.0, 4.0, 6.0]) - 4.0) < 1e-6 and avg_or_zero([]) == 0.0",
        ),
        GeneralSkillTask(
            "held_gs_2",
            "held_recovery_data",
            ("Recovery", "File & Data", "Generalization"),
            "heldout",
            "learn_recovery_gen",
            "# Skill [Recovery, File & Data, Generalization]: unique items sorted ascending\ndef distinct_ordered(seq):\n    return ",
            "sorted(set(seq))\n",
            "assert distinct_ordered([4, 2, 4, 1, 2]) == [1, 2, 4] and distinct_ordered([]) == []",
        ),
        GeneralSkillTask(
            "held_gs_3",
            "held_generalization_ops",
            ("Generalization", "Computer Operations", "Mathematics"),
            "heldout",
            "learn_recovery_gen",
            "# Skill [Generalization, Computer Operations, Mathematics]: max minus min or 0 if empty\ndef diff_range(nums):\n    return ",
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


def _as_coding_tasks(items: Sequence[GeneralSkillTask], *, category: str) -> List[CodingTask]:
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


def verify_general_skills_leakage(
    train_tasks: Sequence[GeneralSkillTask],
    val_tasks: Sequence[GeneralSkillTask],
    heldout_tasks: Sequence[GeneralSkillTask],
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


class GeneralSkillSandboxEvaluator:
    """Evaluates general skill tasks in sandbox and captures raw_output and info."""

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
                error_breakdown={k: 0 for k in ERROR_TYPES},
            )
        loss_texts = [t.reference_solution if t.reference_solution else t.prompt for t in tasks]
        avg_loss = self.loss_fn(loss_texts)
        passed = 0
        details: List[Dict[str, Any]] = []
        for task in tasks:
            raw_out = self.generate_fn(task.prompt)
            extracted = extract_first_python_function(raw_out)
            ok, msg = run_code_in_sandbox(raw_out, task.test_code)
            err = classify_error(ok, msg)
            if ok:
                passed += 1
            details.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "passed": ok,
                    "error_type": err,
                    "info": msg,
                    "raw_output": raw_out,
                    "extracted_code": extracted,
                }
            )
        return EvalReport(
            avg_loss=round(avg_loss, 4) if avg_loss is not None else None,
            exec_pass_rate=round(passed / len(tasks), 4),
            passed_count=passed,
            total_count=len(tasks),
            details=details,
            error_breakdown=_error_summary(details),
        )


def _has_non_finite_pure(obj: Any) -> bool:
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(_has_non_finite_pure(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_non_finite_pure(v) for v in obj)
    return False


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _run_seed_pytorch(
    *,
    seed: int,
    stage_steps: Tuple[int, int, int],
    ckpt_every: int,
    max_new_tokens: int,
    train_tasks: List[GeneralSkillTask],
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
        total_decay_steps=sum(stage_steps) + 120,
        consolidation_lambda=0.01,
        seed=seed,
        device=device,
    )

    def make_eval(m: NativeTransformerLMV2) -> GeneralSkillSandboxEvaluator:
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

        return GeneralSkillSandboxEvaluator(gen_fn, loss_fn)

    pre_ev = make_eval(trainer.model)
    pre_val = pre_ev.evaluate(val_coding)
    pre_heldout = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    stage_history: List[Dict[str, Any]] = []

    baseline_val_report = pre_val
    for idx, (stg, n_steps) in enumerate(zip(STAGE_ORDER, stage_steps)):
        texts = stage_texts[stg]
        done = 0
        while done < n_steps:
            chunk = min(ckpt_every, n_steps - done)
            trainer.train_steps(texts, steps=chunk, batch_size=4, replay_ratio=0.0 if idx == 0 else 0.5)
            done += chunk
            p, sha = trainer.save_checkpoint(ckpt_dir / f"{stg}_step_{done}.pt")
            checkpoints.append({"stage": stg, "step": done, "path": str(p), "sha256": sha})

        trainer.snapshot_consolidation_state(texts, batch_size=4)
        p_stg, sha_stg = trainer.save_checkpoint(ckpt_dir / f"{stg}_final.pt")
        ev = make_eval(trainer.model)
        cur_val = ev.evaluate(val_coding)
        cur_ho = ev.evaluate(heldout_coding)
        if idx == 0:
            baseline_val_report = cur_val
        stage_history.append(
            {
                "stage": stg,
                "checkpoint": str(p_stg),
                "sha256": sha_stg,
                "val_pass_rate": cur_val.exec_pass_rate,
                "val_loss": cur_val.avg_loss,
                "heldout_pass_rate": cur_ho.exec_pass_rate,
                "heldout_loss": cur_ho.avg_loss,
                "heldout_errors": cur_ho.error_breakdown,
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
    post_val = post_ev.evaluate(val_coding)
    post_heldout = post_ev.evaluate(heldout_coding)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(
        pre_heldout, post_heldout, baseline_val_report, post_val, leakage_count=leak_count
    )
    approval = record_checkpoint_approval(
        final_ckpt,
        final_sha,
        gate_res,
        metadata={"seed": seed, "suite": "zyrquen_10_general_skills", "backend": "pytorch"},
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
            "val_pass_rate": pre_val.exec_pass_rate,
            "val_loss": pre_val.avg_loss,
            "heldout_pass_rate": pre_heldout.exec_pass_rate,
            "heldout_loss": pre_heldout.avg_loss,
            "heldout_errors": pre_heldout.error_breakdown,
        },
        "stage_history": stage_history,
        "post_all_stages": {
            "val_pass_rate": post_val.exec_pass_rate,
            "val_loss": post_val.avg_loss,
            "val_errors": post_val.error_breakdown,
            "val_details": post_val.details,
            "heldout_pass_rate": post_heldout.exec_pass_rate,
            "heldout_loss": post_heldout.avg_loss,
            "heldout_errors": post_heldout.error_breakdown,
            "heldout_details": post_heldout.details,
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
    train_tasks: List[GeneralSkillTask],
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

    def make_eval(m: PureNativeTransformerLMV2) -> GeneralSkillSandboxEvaluator:
        return GeneralSkillSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tok, prompt, max_new_tokens=max_new_tokens
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tok, texts)["loss"]),
        )

    pre_ev = make_eval(trainer.model)
    pre_val = pre_ev.evaluate(val_coding)
    pre_heldout = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    stage_history: List[Dict[str, Any]] = []

    baseline_val_report = pre_val
    for idx, (stg, n_steps) in enumerate(zip(STAGE_ORDER, stage_steps)):
        texts = stage_texts[stg]
        done = 0
        while done < n_steps:
            chunk = min(ckpt_every, n_steps - done)
            trainer.train_steps(texts, steps=chunk, batch_size=2, replay_ratio=0.0 if idx == 0 else 0.5)
            done += chunk
            p, sha = trainer.save_checkpoint(ckpt_dir / f"{stg}_step_{done}.json.gz")
            checkpoints.append({"stage": stg, "step": done, "path": str(p), "sha256": sha})

        if _has_non_finite_pure(trainer.model.params):
            raise RuntimeError(f"Training halted: NaN/Inf detected during stage {stg}")

        trainer.snapshot_consolidation_state(texts)
        p_stg, sha_stg = trainer.save_checkpoint(ckpt_dir / f"{stg}_final.json.gz")
        ev = make_eval(trainer.model)
        cur_val = ev.evaluate(val_coding)
        cur_ho = ev.evaluate(heldout_coding)
        if idx == 0:
            baseline_val_report = cur_val
        stage_history.append(
            {
                "stage": stg,
                "checkpoint": str(p_stg),
                "sha256": sha_stg,
                "val_pass_rate": cur_val.exec_pass_rate,
                "val_loss": cur_val.avg_loss,
                "heldout_pass_rate": cur_ho.exec_pass_rate,
                "heldout_loss": cur_ho.avg_loss,
                "heldout_errors": cur_ho.error_breakdown,
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
    post_val = post_ev.evaluate(val_coding)
    post_heldout = post_ev.evaluate(heldout_coding)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(
        pre_heldout, post_heldout, baseline_val_report, post_val, leakage_count=leak_count
    )
    approval = record_checkpoint_approval(
        final_ckpt,
        final_sha,
        gate_res,
        metadata={
            "seed": seed,
            "suite": "zyrquen_10_general_skills",
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
            "val_pass_rate": pre_val.exec_pass_rate,
            "val_loss": pre_val.avg_loss,
            "heldout_pass_rate": pre_heldout.exec_pass_rate,
            "heldout_loss": pre_heldout.avg_loss,
            "heldout_errors": pre_heldout.error_breakdown,
        },
        "stage_history": stage_history,
        "post_all_stages": {
            "val_pass_rate": post_val.exec_pass_rate,
            "val_loss": post_val.avg_loss,
            "val_errors": post_val.error_breakdown,
            "val_details": post_val.details,
            "heldout_pass_rate": post_heldout.exec_pass_rate,
            "heldout_loss": post_heldout.avg_loss,
            "heldout_errors": post_heldout.error_breakdown,
            "heldout_details": post_heldout.details,
            "gate": asdict(gate_res),
            "approved": bool(approval["approved"]),
            "status": approval["status"],
            "approved_checkpoint": approval["approved_checkpoint"],
        },
    }


def run_general_skills_suite(
    seeds: Sequence[int] = DEFAULT_GENERAL_SEEDS,
    stage_steps: Tuple[int, int, int] = (700, 700, 700),
    ckpt_every: int = 350,
    pure_stage_steps: Tuple[int, int, int] = (12, 12, 12),
    pure_ckpt_every: int = 6,
    pure_max_new_tokens: int = 32,
    pytorch_max_new_tokens: int = 96,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    train_tasks, val_tasks, heldout_tasks = build_general_skills_corpus()
    leaks = verify_general_skills_leakage(train_tasks, val_tasks, heldout_tasks)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in general skills corpus: {leaks}")

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
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_general_skills")
    run_root = base_dir / f"run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    runner = _run_seed_pytorch if use_pytorch else _run_seed_pure
    runs = [
        runner(
            seed=int(s),
            stage_steps=eff_stage_steps,
            ckpt_every=eff_ckpt_every,
            max_new_tokens=eff_max_new_tokens,
            train_tasks=train_tasks,
            val_coding=val_coding,
            heldout_coding=heldout_coding,
            leak_count=len(leaks),
            seed_dir=run_root / f"seed_{s}",
        )
        for s in seeds
    ]

    val_rates = [r["post_all_stages"]["val_pass_rate"] for r in runs]
    ho_rates = [r["post_all_stages"]["heldout_pass_rate"] for r in runs]
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
        "suite": "zyrquen_10_general_skills",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "torch_available": torch_available,
        "external_models_used": False,
        "init_mode": "random_initialization_native_only",
        "covered_skills": all_skills,
        "leakage_count": len(leaks),
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
            "mean_val_pass_rate": round(sum(val_rates) / max(len(val_rates), 1), 4),
            "min_val_pass_rate": round(min(val_rates), 4) if val_rates else 0.0,
            "mean_val_loss": round(sum(val_losses) / max(len(val_losses), 1), 4) if val_losses else None,
            "mean_heldout_pass_rate": round(sum(ho_rates) / max(len(ho_rates), 1), 4),
            "min_heldout_pass_rate": round(min(ho_rates), 4) if ho_rates else 0.0,
            "mean_heldout_loss": round(sum(ho_losses) / max(len(ho_losses), 1), 4) if ho_losses else None,
            "val_error_breakdown": {
                k: sum(int(r["post_all_stages"]["val_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "heldout_error_breakdown": {
                k: sum(int(r["post_all_stages"]["heldout_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "approved_seeds": approved_seeds,
            "any_approved": bool(approved_seeds),
            "overall_approval_status": "APPROVED" if all_approved else "REJECTED_BY_GATE",
        },
        "runs": runs,
    }
    manifest_path = run_root / "manifest_general_skills.json"
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
    ap = argparse.ArgumentParser(description="Run ZYRQUEN V2 10-General-Skills Continual Suite")
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--stage-steps", default="700,700,700")
    ap.add_argument("--ckpt-every", type=int, default=350)
    ap.add_argument("--pure-stage-steps", default="12,12,12")
    ap.add_argument("--pure-ckpt-every", type=int, default=6)
    ap.add_argument("--pure-max-new-tokens", type=int, default=32)
    ap.add_argument("--pytorch-max-new-tokens", type=int, default=96)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    try:
        res = run_general_skills_suite(
            seeds=_parse_seeds(args.seeds),
            stage_steps=_parse_stage_steps(args.stage_steps),
            ckpt_every=args.ckpt_every,
            pure_stage_steps=_parse_stage_steps(args.pure_stage_steps),
            pure_ckpt_every=args.pure_ckpt_every,
            pure_max_new_tokens=args.pure_max_new_tokens,
            pytorch_max_new_tokens=args.pytorch_max_new_tokens,
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
        print("stage_history:", json.dumps(r["stage_history"], ensure_ascii=False))
        print("val_errors:", p["val_errors"])
        print("heldout_errors:", p["heldout_errors"])
        for split_name in ("val_details", "heldout_details"):
            for item in p[split_name]:
                print(
                    f"  [{split_name}] {item['task_id']} ({item['family']}) "
                    f"passed={item['passed']} err={item['error_type']} info={item['info']!r}"
                )
                print(f"    raw_output: {item['raw_output']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
