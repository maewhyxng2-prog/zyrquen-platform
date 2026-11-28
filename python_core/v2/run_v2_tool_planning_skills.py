"""ZYRQUEN V2 Tool Usage + Task Planning Training & Sandbox Runner.

Trains Native ZYRQUEN V2 from random initialization only (zero external models):
  Stage 1: `tool_usage` skill corpus (tool contracts, context guards, dispatch)
  Stage 2: Continual `task_planning` corpus (multi-step pipelines + guarded aggregation,
           snapshot consolidation + SHA-256 checkpoint continuity + replay_ratio=0.5 +
           RoPE context extension)

Evaluates pre-training (random init), post-Stage-1 (`after_tool_usage_only`), and
post-Stage-2 (`post_tool_and_planning`) on strictly disjoint task-family Validation
(`tool_plan_dict_lookup`) and Held-out Test splits (`tool_plan_weighted_score`,
`tool_plan_clean_summary`, `tool_plan_bounded_step`), capturing `summary`,
`val_errors`, `heldout_errors`, `raw_output`, and fail-closed `ApprovalGate` verdicts.
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

DEFAULT_TOOL_PLAN_SEEDS: Tuple[int, ...] = (42, 1337, 2026)


@dataclass(frozen=True)
class ToolPlanExample:
    task_id: str
    family: str
    split: str  # "train" | "val" | "heldout"
    skill_mode: str  # "tool_usage" | "task_planning"
    prompt: str
    target_code: str
    test_code: str

    @property
    def full_text(self) -> str:
        return self.prompt + self.target_code


def build_tool_planning_splits() -> (
    Tuple[List[ToolPlanExample], List[ToolPlanExample], List[ToolPlanExample]]
):
    """Build disjoint train / val / heldout tasks for Tool Usage + Task Planning."""
    train_items: List[ToolPlanExample] = [
        # --- Family: tool_math_dispatch (Tool Usage) ---
        ToolPlanExample(
            "tp_tmath_1",
            "tool_math_dispatch",
            "train",
            "tool_usage",
            "# Tool: add_fn(x, y), mul_fn(x, y)\n# Call add_fn if op=='add' else mul_fn\ndef run_math_tool(op, a, b, add_fn, mul_fn):\n    return ",
            "add_fn(a, b) if op == 'add' else mul_fn(a, b)\n",
            "assert run_math_tool('add', 3, 4, lambda x,y: x+y, lambda x,y: x*y) == 7 and run_math_tool('mul', 3, 4, lambda x,y: x+y, lambda x,y: x*y) == 12",
        ),
        ToolPlanExample(
            "tp_tmath_2",
            "tool_math_dispatch",
            "train",
            "tool_usage",
            "# Tool: clamp_fn(val, lo, hi)\n# Apply clamp_fn to each item in seq\ndef clamp_with_tool(seq, lo, hi, clamp_fn):\n    return ",
            "[clamp_fn(x, lo, hi) for x in seq]\n",
            "assert clamp_with_tool([-2, 5, 20], 0, 10, lambda v,a,b: max(a, min(b, v))) == [0, 5, 10]",
        ),
        ToolPlanExample(
            "tp_tmath_3",
            "tool_math_dispatch",
            "train",
            "tool_usage",
            "# Tool: safe_div(num, den, zero_val=0.0)\n# Guard den==0 before calling safe_div\ndef ratio_tool(a, b, safe_div):\n    return ",
            "0.0 if b == 0 else safe_div(a, b, 0.0)\n",
            "assert ratio_tool(10, 0, lambda n,d,z: z if d==0 else n/d) == 0.0 and ratio_tool(8, 2, lambda n,d,z: z if d==0 else n/d) == 4.0",
        ),
        # --- Family: tool_list_filter (Tool Usage) ---
        ToolPlanExample(
            "tp_tlist_1",
            "tool_list_filter",
            "train",
            "tool_usage",
            "# Tool: pred_fn(item) -> bool\n# Keep items where pred_fn is True, then count them\ndef count_by_tool(items, pred_fn):\n    return ",
            "sum(1 for x in items if pred_fn(x))\n",
            "assert count_by_tool([1, 2, 3, 4, 5], lambda x: x % 2 == 1) == 3",
        ),
        ToolPlanExample(
            "tp_tlist_2",
            "tool_list_filter",
            "train",
            "tool_usage",
            "# Tool: norm_fn(s) -> str\n# Normalize non-empty strings using norm_fn\ndef norm_non_empty_tool(items, norm_fn):\n    return ",
            "[norm_fn(s) for s in items if s]\n",
            "assert norm_non_empty_tool([' A ', '', ' B '], lambda s: s.strip().lower()) == ['a', 'b']",
        ),
        ToolPlanExample(
            "tp_tlist_3",
            "tool_list_filter",
            "train",
            "tool_usage",
            "# Tool: score_fn(x) -> int\n# Return max score_fn(x) over non-empty items, or 0 if empty\ndef max_score_tool(items, score_fn):\n    return ",
            "0 if not items else max(score_fn(x) for x in items)\n",
            "assert max_score_tool(['a', 'abc', 'ab'], len) == 3 and max_score_tool([], len) == 0",
        ),
        # --- Family: plan_pipeline_steps (Task Planning) ---
        ToolPlanExample(
            "tp_pstep_1",
            "plan_pipeline_steps",
            "train",
            "task_planning",
            "# Plan: 1) filter positive nums 2) double each 3) return list\ndef plan_double_positives(nums):\n    return ",
            "[n * 2 for n in nums if n > 0]\n",
            "assert plan_double_positives([-1, 2, 0, 5]) == [4, 10]",
        ),
        ToolPlanExample(
            "tp_pstep_2",
            "plan_pipeline_steps",
            "train",
            "task_planning",
            "# Plan: 1) split by space 2) strip/lower tokens 3) return count\ndef plan_word_count(text):\n    return ",
            "len([w.strip().lower() for w in text.split() if w.strip()])\n",
            "assert plan_word_count('Hello   WORLD  ') == 2 and plan_word_count('   ') == 0",
        ),
        ToolPlanExample(
            "tp_pstep_3",
            "plan_pipeline_steps",
            "train",
            "task_planning",
            "# Plan: 1) remove None 2) sort ascending 3) take first k\ndef plan_clean_top_k(vals, k):\n    return ",
            "[] if k <= 0 else sorted(v for v in vals if v is not None)[:k]\n",
            "assert plan_clean_top_k([5, None, 1, 3, None], 2) == [1, 3]",
        ),
        # --- Family: plan_guarded_agg (Task Planning) ---
        ToolPlanExample(
            "tp_pagg_1",
            "plan_guarded_agg",
            "train",
            "task_planning",
            "# Plan: 1) check empty list -> return 0 2) sum squares\ndef plan_sum_squares(vals):\n    return ",
            "0 if len(vals) == 0 else sum(v * v for v in vals)\n",
            "assert plan_sum_squares([2, 3]) == 13 and plan_sum_squares([]) == 0",
        ),
        ToolPlanExample(
            "tp_pagg_2",
            "plan_guarded_agg",
            "train",
            "task_planning",
            "# Plan: 1) filter > 0 2) if none return 0 3) return min\ndef plan_min_positive(vals):\n    return ",
            "0 if not [v for v in vals if v > 0] else min(v for v in vals if v > 0)\n",
            "assert plan_min_positive([-4, 7, 2, 9]) == 2 and plan_min_positive([-1, -2]) == 0",
        ),
        ToolPlanExample(
            "tp_pagg_3",
            "plan_guarded_agg",
            "train",
            "task_planning",
            "# Plan: 1) check empty -> return 0.0 2) sum(vals) / len(vals)\ndef plan_mean_or_zero(vals):\n    return ",
            "0.0 if len(vals) == 0 else sum(vals) / len(vals)\n",
            "assert abs(plan_mean_or_zero([2.0, 6.0]) - 4.0) < 1e-6 and plan_mean_or_zero([]) == 0.0",
        ),
    ]

    val_items: List[ToolPlanExample] = [
        ToolPlanExample(
            "val_tp_1",
            "tool_plan_dict_lookup",
            "val",
            "tool_usage",
            "# Tool: lookup_fn(mapping, k) -> val or None\n# Plan: 1) lookup key via lookup_fn 2) return fallback if None\ndef resolve_key_tool(mapping, k, fallback, lookup_fn):\n    return ",
            "fallback if lookup_fn(mapping, k) is None else lookup_fn(mapping, k)\n",
            "assert resolve_key_tool({'a': 5}, 'a', 0, lambda m,k: m.get(k)) == 5 and resolve_key_tool({'a': 5}, 'b', -1, lambda m,k: m.get(k)) == -1",
        ),
        ToolPlanExample(
            "val_tp_2",
            "tool_plan_dict_lookup",
            "val",
            "task_planning",
            "# Plan: 1) collect non-empty keys 2) return sorted list\ndef sorted_active_keys(mapping):\n    return ",
            "sorted(k for k, v in mapping.items() if v)\n",
            "assert sorted_active_keys({'b': 1, 'a': 0, 'c': True}) == ['b', 'c']",
        ),
    ]

    heldout_items: List[ToolPlanExample] = [
        ToolPlanExample(
            "held_tp_1",
            "tool_plan_weighted_score",
            "heldout",
            "tool_usage",
            "# Tool: weight_fn(x) -> float\n# Plan: 1) guard empty list -> 0.0 2) sum(weight_fn(x) for x in items)\ndef total_weighted_tool(items, weight_fn):\n    return ",
            "0.0 if len(items) == 0 else sum(weight_fn(x) for x in items)\n",
            "assert abs(total_weighted_tool([2, 3], lambda x: x * 1.5) - 7.5) < 1e-6 and total_weighted_tool([], lambda x: x * 1.5) == 0.0",
        ),
        ToolPlanExample(
            "held_tp_2",
            "tool_plan_clean_summary",
            "heldout",
            "task_planning",
            "# Plan: 1) filter non-empty strings 2) deduplicate and sort ascending\ndef unique_sorted_non_empty(items):\n    return ",
            "sorted({s for s in items if s})\n",
            "assert unique_sorted_non_empty(['b', '', 'a', 'b', '']) == ['a', 'b'] and unique_sorted_non_empty([]) == []",
        ),
        ToolPlanExample(
            "held_tp_3",
            "tool_plan_bounded_step",
            "heldout",
            "task_planning",
            "# Plan: 1) guard empty -> 0 2) compute max(vals) - min(vals)\ndef planned_spread(vals):\n    return ",
            "0 if len(vals) == 0 else max(vals) - min(vals)\n",
            "assert planned_spread([4, 10, 2, 7]) == 8 and planned_spread([]) == 0",
        ),
    ]

    tr_fams = {x.family for x in train_items}
    val_fams = {x.family for x in val_items}
    ho_fams = {x.family for x in heldout_items}
    if (tr_fams & val_fams) or (tr_fams & ho_fams) or (val_fams & ho_fams):
        raise RuntimeError(
            f"Family overlap detected: train={tr_fams}, val={val_fams}, heldout={ho_fams}"
        )

    return train_items, val_items, heldout_items


def _to_coding_tasks(items: Sequence[ToolPlanExample], *, category: str) -> List[CodingTask]:
    return [
        CodingTask(
            task_id=ex.task_id,
            family=f"{ex.family}:{ex.skill_mode}",
            prompt=ex.prompt,
            test_code=ex.test_code,
            reference_solution=ex.full_text,
            category=category,
        )
        for ex in items
    ]


def verify_tool_planning_leakage(
    train_items: Sequence[ToolPlanExample],
    val_items: Sequence[ToolPlanExample],
    heldout_items: Sequence[ToolPlanExample],
) -> List[Dict[str, str]]:
    train_texts = [x.full_text for x in train_items]
    eval_tasks = _to_coding_tasks(val_items, category="validation") + _to_coding_tasks(
        heldout_items, category="unseen"
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


class ToolPlanSandboxEvaluator:
    """Evaluates Tool Usage + Task Planning tasks in sandbox with raw_output and info."""

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
    steps_tool: int,
    steps_plan: int,
    ckpt_every: int,
    max_new_tokens: int,
    train_items: List[ToolPlanExample],
    val_tasks: List[CodingTask],
    heldout_tasks: List[CodingTask],
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

    tool_texts = [x.full_text for x in train_items if x.skill_mode == "tool_usage"]
    plan_texts = [x.full_text for x in train_items if x.skill_mode == "task_planning"]

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
    active_trainer = ContinualTrainerV2(
        NativeTransformerLMV2(cfg),
        tok,
        lr=1e-3,
        total_decay_steps=steps_tool + steps_plan + 100,
        consolidation_lambda=0.01,
        seed=seed,
        device=device,
    )

    def make_eval(m: NativeTransformerLMV2) -> ToolPlanSandboxEvaluator:
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

        return ToolPlanSandboxEvaluator(gen_fn, loss_fn)

    pre_ev = make_eval(active_trainer.model)
    pre_val = pre_ev.evaluate(val_tasks)
    pre_heldout = pre_ev.evaluate(heldout_tasks)

    checkpoints: List[Dict[str, Any]] = []
    done = 0
    while done < steps_tool:
        chunk = min(ckpt_every, steps_tool - done)
        active_trainer.train_steps(tool_texts, steps=chunk, batch_size=4, replay_ratio=0.0)
        done += chunk
        p, sha = active_trainer.save_checkpoint(ckpt_dir / f"tool_step_{done}.pt")
        checkpoints.append({"stage": "tool_usage", "step": done, "path": str(p), "sha256": sha})

    active_trainer.snapshot_consolidation_state(tool_texts, batch_size=4)
    p_tool_final, sha_tool_final = active_trainer.save_checkpoint(ckpt_dir / "stage1_tool_final.pt")
    p1_ev = make_eval(active_trainer.model)
    val_after_tool = p1_ev.evaluate(val_tasks)
    ho_after_tool = p1_ev.evaluate(heldout_tasks)

    active_trainer = ContinualTrainerV2.load_checkpoint(
        p_tool_final,
        tok,
        expected_sha256=sha_tool_final,
        resume_optimizer=True,
        restore_continual_state=True,
        consolidation_lambda=0.01,
        device=device,
    )
    active_trainer.model.extend_context(1024)

    done_plan = 0
    while done_plan < steps_plan:
        chunk = min(ckpt_every, steps_plan - done_plan)
        active_trainer.train_steps(plan_texts, steps=chunk, batch_size=4, replay_ratio=0.5)
        done_plan += chunk
        p, sha = active_trainer.save_checkpoint(ckpt_dir / f"plan_step_{done_plan}.pt")
        checkpoints.append(
            {"stage": "task_planning", "step": done_plan, "path": str(p), "sha256": sha}
        )

    active_trainer.snapshot_consolidation_state(tool_texts + plan_texts, batch_size=4)
    p_final, sha_final = active_trainer.save_checkpoint(ckpt_dir / "stage2_tool_plan_final.pt")

    post_ev = make_eval(active_trainer.model)
    post_val = post_ev.evaluate(val_tasks)
    post_heldout = post_ev.evaluate(heldout_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(pre_heldout, post_heldout, val_after_tool, post_val, leakage_count=leak_count)
    approval = record_checkpoint_approval(
        p_final,
        sha_final,
        gate_res,
        metadata={"seed": seed, "skills": ["tool_usage", "task_planning"], "backend": "pytorch"},
    )

    return {
        "seed": seed,
        "backend": "pytorch",
        "device": device.type,
        "global_step_final": active_trainer.global_step,
        "checkpoints": checkpoints,
        "final_checkpoint": {
            "path": str(p_final),
            "sha256": sha_final,
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
        "after_tool_usage_only": {
            "val_pass_rate": val_after_tool.exec_pass_rate,
            "val_loss": val_after_tool.avg_loss,
            "heldout_pass_rate": ho_after_tool.exec_pass_rate,
            "heldout_loss": ho_after_tool.avg_loss,
            "val_details": val_after_tool.details,
        },
        "post_tool_and_planning": {
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
    steps_tool: int,
    steps_plan: int,
    ckpt_every: int,
    max_new_tokens: int,
    train_items: List[ToolPlanExample],
    val_tasks: List[CodingTask],
    heldout_tasks: List[CodingTask],
    leak_count: int,
    seed_dir: Path,
) -> Dict[str, Any]:
    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    tok = ByteTokenizer()

    tool_texts = [x.full_text for x in train_items if x.skill_mode == "tool_usage"]
    plan_texts = [x.full_text for x in train_items if x.skill_mode == "task_planning"]

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
    active_trainer = PureContinualTrainerV2(
        model=PureNativeTransformerLMV2(cfg),
        tokenizer=tok,
        lr=0.015,
        warmup_steps=4,
        total_decay_steps=max(steps_tool + steps_plan + 8, 24),
        consolidation_lambda=0.01,
        seed=seed,
    )

    def make_eval(m: PureNativeTransformerLMV2) -> ToolPlanSandboxEvaluator:
        return ToolPlanSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tok, prompt, max_new_tokens=max_new_tokens
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tok, texts)["loss"]),
        )

    pre_ev = make_eval(active_trainer.model)
    pre_val = pre_ev.evaluate(val_tasks)
    pre_heldout = pre_ev.evaluate(heldout_tasks)

    checkpoints: List[Dict[str, Any]] = []
    done = 0
    while done < steps_tool:
        chunk = min(ckpt_every, steps_tool - done)
        active_trainer.train_steps(tool_texts, steps=chunk, batch_size=2, replay_ratio=0.0)
        done += chunk
        p, sha = active_trainer.save_checkpoint(ckpt_dir / f"tool_step_{done}.json.gz")
        checkpoints.append({"stage": "tool_usage", "step": done, "path": str(p), "sha256": sha})

    active_trainer.snapshot_consolidation_state(tool_texts)
    p_tool_final, sha_tool_final = active_trainer.save_checkpoint(
        ckpt_dir / "stage1_tool_final.json.gz"
    )
    p1_ev = make_eval(active_trainer.model)
    val_after_tool = p1_ev.evaluate(val_tasks)
    ho_after_tool = p1_ev.evaluate(heldout_tasks)

    active_trainer = PureContinualTrainerV2.load_checkpoint(
        p_tool_final,
        tokenizer=tok,
        expected_sha256=sha_tool_final,
        resume_optimizer=True,
        restore_continual_state=True,
        consolidation_lambda=0.01,
    )
    active_trainer.model.extend_context(512)

    done_plan = 0
    while done_plan < steps_plan:
        chunk = min(ckpt_every, steps_plan - done_plan)
        active_trainer.train_steps(plan_texts, steps=chunk, batch_size=2, replay_ratio=0.5)
        done_plan += chunk
        p, sha = active_trainer.save_checkpoint(ckpt_dir / f"plan_step_{done_plan}.json.gz")
        checkpoints.append(
            {"stage": "task_planning", "step": done_plan, "path": str(p), "sha256": sha}
        )

    if _has_non_finite_pure(active_trainer.model.params):
        raise RuntimeError("Training halted: NaN/Inf detected in pure model parameters")

    active_trainer.snapshot_consolidation_state(tool_texts + plan_texts)
    p_final, sha_final = active_trainer.save_checkpoint(
        ckpt_dir / "stage2_tool_plan_final.json.gz"
    )

    post_ev = make_eval(active_trainer.model)
    post_val = post_ev.evaluate(val_tasks)
    post_heldout = post_ev.evaluate(heldout_tasks)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(pre_heldout, post_heldout, val_after_tool, post_val, leakage_count=leak_count)
    approval = record_checkpoint_approval(
        p_final,
        sha_final,
        gate_res,
        metadata={
            "seed": seed,
            "skills": ["tool_usage", "task_planning"],
            "backend": "pure_python_3.11_stdlib",
        },
    )

    return {
        "seed": seed,
        "backend": "pure_python_3.11_stdlib",
        "device": "pure_python_3.11_stdlib",
        "global_step_final": active_trainer.global_step,
        "checkpoints": checkpoints,
        "final_checkpoint": {
            "path": str(p_final),
            "sha256": sha_final,
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
        "after_tool_usage_only": {
            "val_pass_rate": val_after_tool.exec_pass_rate,
            "val_loss": val_after_tool.avg_loss,
            "heldout_pass_rate": ho_after_tool.exec_pass_rate,
            "heldout_loss": ho_after_tool.avg_loss,
            "val_details": val_after_tool.details,
        },
        "post_tool_and_planning": {
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


def run_tool_planning_skill_training(
    seeds: Sequence[int] = DEFAULT_TOOL_PLAN_SEEDS,
    steps_tool: int = 800,
    steps_plan: int = 800,
    ckpt_every: int = 400,
    pure_steps_tool: int = 16,
    pure_steps_plan: int = 16,
    pure_ckpt_every: int = 8,
    pure_max_new_tokens: int = 32,
    pytorch_max_new_tokens: int = 96,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    train_items, val_items, heldout_items = build_tool_planning_splits()
    leaks = verify_tool_planning_leakage(train_items, val_items, heldout_items)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in tool/planning splits: {leaks}")

    resolved_backend, torch_available = _resolve_backend(backend)
    use_pytorch = resolved_backend == "pytorch"

    eff_steps_tool = steps_tool if use_pytorch else min(steps_tool, pure_steps_tool)
    eff_steps_plan = steps_plan if use_pytorch else min(steps_plan, pure_steps_plan)
    eff_ckpt_every = ckpt_every if use_pytorch else min(ckpt_every, pure_ckpt_every)
    eff_max_new_tokens = pytorch_max_new_tokens if use_pytorch else pure_max_new_tokens

    val_tasks = _to_coding_tasks(val_items, category="validation")
    heldout_tasks = _to_coding_tasks(heldout_items, category="unseen")

    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_tool_planning")
    run_root = base_dir / f"run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    runner = _run_seed_pytorch if use_pytorch else _run_seed_pure
    runs = [
        runner(
            seed=int(s),
            steps_tool=eff_steps_tool,
            steps_plan=eff_steps_plan,
            ckpt_every=eff_ckpt_every,
            max_new_tokens=eff_max_new_tokens,
            train_items=train_items,
            val_tasks=val_tasks,
            heldout_tasks=heldout_tasks,
            leak_count=len(leaks),
            seed_dir=run_root / f"seed_{s}",
        )
        for s in seeds
    ]

    val_rates = [r["post_tool_and_planning"]["val_pass_rate"] for r in runs]
    ho_rates = [r["post_tool_and_planning"]["heldout_pass_rate"] for r in runs]
    val_losses = [
        float(r["post_tool_and_planning"]["val_loss"])
        for r in runs
        if r["post_tool_and_planning"]["val_loss"] is not None
    ]
    ho_losses = [
        float(r["post_tool_and_planning"]["heldout_loss"])
        for r in runs
        if r["post_tool_and_planning"]["heldout_loss"] is not None
    ]
    approved_seeds = [r["seed"] for r in runs if r["post_tool_and_planning"]["approved"]]
    all_approved = bool(runs) and len(approved_seeds) == len(runs)

    manifest: Dict[str, Any] = {
        "suite": "zyrquen_tool_planning_skills",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "torch_available": torch_available,
        "external_models_used": False,
        "init_mode": "random_initialization_native_only",
        "elapsed_sec": round(time.time() - t0, 2),
        "seeds": [int(s) for s in seeds],
        "leakage_count": len(leaks),
        "effective_steps": {
            "tool_usage": eff_steps_tool,
            "task_planning": eff_steps_plan,
            "checkpoint_every": eff_ckpt_every,
            "max_new_tokens": eff_max_new_tokens,
        },
        "split_counts": {
            "train": len(train_items),
            "val": len(val_items),
            "heldout": len(heldout_items),
        },
        "summary": {
            "mean_val_pass_rate": round(sum(val_rates) / max(len(val_rates), 1), 4),
            "min_val_pass_rate": round(min(val_rates), 4) if val_rates else 0.0,
            "mean_val_loss": round(sum(val_losses) / max(len(val_losses), 1), 4) if val_losses else None,
            "mean_heldout_pass_rate": round(sum(ho_rates) / max(len(ho_rates), 1), 4),
            "min_heldout_pass_rate": round(min(ho_rates), 4) if ho_rates else 0.0,
            "mean_heldout_loss": round(sum(ho_losses) / max(len(ho_losses), 1), 4) if ho_losses else None,
            "val_error_breakdown": {
                k: sum(int(r["post_tool_and_planning"]["val_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "heldout_error_breakdown": {
                k: sum(int(r["post_tool_and_planning"]["heldout_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "approved_seeds": approved_seeds,
            "any_approved": bool(approved_seeds),
            "overall_approval_status": "APPROVED" if all_approved else "REJECTED_BY_GATE",
        },
        "runs": runs,
    }
    manifest_path = run_root / "manifest_tool_planning.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    manifest["manifest_sha256"] = _sha256_file(manifest_path)
    return manifest


def _parse_seeds(raw: str) -> Tuple[int, ...]:
    vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not vals:
        raise ValueError("Expected comma-separated seed integers")
    return tuple(vals)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run ZYRQUEN V2 Tool Usage & Task Planning Experiment")
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--steps-tool", type=int, default=800)
    ap.add_argument("--steps-plan", type=int, default=800)
    ap.add_argument("--ckpt-every", type=int, default=400)
    ap.add_argument("--pure-steps-tool", type=int, default=16)
    ap.add_argument("--pure-steps-plan", type=int, default=16)
    ap.add_argument("--pure-ckpt-every", type=int, default=8)
    ap.add_argument("--pure-max-new-tokens", type=int, default=32)
    ap.add_argument("--pytorch-max-new-tokens", type=int, default=96)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    try:
        res = run_tool_planning_skill_training(
            seeds=_parse_seeds(args.seeds),
            steps_tool=args.steps_tool,
            steps_plan=args.steps_plan,
            ckpt_every=args.ckpt_every,
            pure_steps_tool=args.pure_steps_tool,
            pure_steps_plan=args.pure_steps_plan,
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
                "leakage_count": res["leakage_count"],
                "effective_steps": res["effective_steps"],
                "manifest_path": res["manifest_path"],
                "manifest_sha256": res["manifest_sha256"],
                "elapsed_sec": res["elapsed_sec"],
                "split_counts": res["split_counts"],
                "summary": res["summary"],
                "per_seed_overview": [
                    {
                        "seed": r["seed"],
                        "global_step_final": r["global_step_final"],
                        "pre_val_loss": r["pre_random_init"]["val_loss"],
                        "pre_heldout_loss": r["pre_random_init"]["heldout_loss"],
                        "post_val_loss": r["post_tool_and_planning"]["val_loss"],
                        "post_heldout_loss": r["post_tool_and_planning"]["heldout_loss"],
                        "post_val_pass_rate": r["post_tool_and_planning"]["val_pass_rate"],
                        "post_heldout_pass_rate": r["post_tool_and_planning"]["heldout_pass_rate"],
                        "val_errors": r["post_tool_and_planning"]["val_errors"],
                        "heldout_errors": r["post_tool_and_planning"]["heldout_errors"],
                        "status": r["post_tool_and_planning"]["status"],
                    }
                    for r in res["runs"]
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    for r in res["runs"]:
        p = r["post_tool_and_planning"]
        print(f"\n=== SEED {r['seed']} (status={p['status']}) ===")
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
