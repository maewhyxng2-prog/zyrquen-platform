"""ZYRQUEN V2 Compositional Generalization & Continual Consolidation Suite.

Evaluates compositional transfer across 3 continual stages
(atomic_primitives -> multi_skill_composition -> transfer_consolidation) with
strict family isolation (Held-out tasks never enter Train or Replay).

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

DEFAULT_COMPOSITIONAL_SEEDS: Tuple[int, ...] = (42, 1337, 2026)
STAGE_ORDER: Tuple[str, str, str] = (
    "atomic_primitives",
    "multi_skill_composition",
    "transfer_consolidation",
)


@dataclass(frozen=True)
class CompositionalTask:
    task_id: str
    family: str
    skills: Tuple[str, ...]
    split: str  # "train" | "val" | "heldout"
    stage: str  # "atomic_primitives" | "multi_skill_composition" | "transfer_consolidation"
    prompt: str
    target_code: str
    test_code: str

    @property
    def full_text(self) -> str:
        return self.prompt + self.target_code


def build_compositional_generalization_splits() -> (
    Tuple[List[CompositionalTask], List[CompositionalTask], List[CompositionalTask]]
):
    """Build disjoint train / val / heldout tasks testing compositional generalization across skills."""
    train_items: List[CompositionalTask] = [
        # --- Stage 1: atomic_primitives ---
        CompositionalTask(
            "cg_prim_1",
            "prim_sum_guard",
            ("Mathematics", "Recovery"),
            "train",
            "atomic_primitives",
            "# Primitive: sum positive values or 0 when empty\ndef prim_pos_sum(vals):\n    return ",
            "0 if not vals else sum(v for v in vals if v > 0)\n",
            "assert prim_pos_sum([-3, 4, 6]) == 10 and prim_pos_sum([]) == 0",
        ),
        CompositionalTask(
            "cg_prim_2",
            "prim_sum_guard",
            ("Mathematics", "Reasoning"),
            "train",
            "atomic_primitives",
            "# Primitive: bound value between min_v and max_v\ndef prim_bound(val, min_v, max_v):\n    return ",
            "max(min_v, min(max_v, val))\n",
            "assert prim_bound(15, 1, 10) == 10 and prim_bound(-4, 1, 10) == 1",
        ),
        CompositionalTask(
            "cg_prim_3",
            "prim_text_clean",
            ("Programming", "File & Data"),
            "train",
            "atomic_primitives",
            "# Primitive: non-empty trimmed strings from comma text\ndef prim_csv_items(text):\n    return ",
            "[s.strip() for s in text.split(',') if s.strip()]\n",
            "assert prim_csv_items(' x , , y ') == ['x', 'y']",
        ),
        CompositionalTask(
            "cg_prim_4",
            "prim_text_clean",
            ("Programming", "Generalization"),
            "train",
            "atomic_primitives",
            "# Primitive: reverse space-separated words\ndef prim_rev_words(s):\n    return ",
            "' '.join(reversed(s.split()))\n",
            "assert prim_rev_words('one two three') == 'three two one'",
        ),
        # --- Stage 2: multi_skill_composition ---
        CompositionalTask(
            "cg_comp_1",
            "comp_tool_filter",
            ("Tool Use", "Research", "Task Planning"),
            "train",
            "multi_skill_composition",
            "# Compose [Tool Use, Research, Task Planning]: select items passing filter_fn then sort\ndef comp_filter_sort(items, filter_fn):\n    return ",
            "sorted(x for x in items if filter_fn(x))\n",
            "assert comp_filter_sort([9, 3, 7, 1], lambda x: x >= 3) == [3, 7, 9]",
        ),
        CompositionalTask(
            "cg_comp_2",
            "comp_tool_filter",
            ("Tool Use", "Recovery", "Reasoning"),
            "train",
            "multi_skill_composition",
            "# Compose [Tool Use, Recovery, Reasoning]: call lookup_fn(k) or fallback if None\ndef comp_lookup_or(lookup_fn, k, fallback):\n    return ",
            "fallback if lookup_fn(k) is None else lookup_fn(k)\n",
            "assert comp_lookup_or(lambda k: {'a': 5}.get(k), 'a', 0) == 5 and comp_lookup_or(lambda k: {'a': 5}.get(k), 'b', -1) == -1",
        ),
        CompositionalTask(
            "cg_comp_3",
            "comp_ops_guard",
            ("Computer Operations", "File & Data", "Recovery"),
            "train",
            "multi_skill_composition",
            "# Compose [Computer Operations, File & Data, Recovery]: first item or fallback if empty\ndef comp_head_or(seq, fallback):\n    return ",
            "seq[0] if len(seq) > 0 else fallback\n",
            "assert comp_head_or([10, 20], 0) == 10 and comp_head_or([], 0) == 0",
        ),
        CompositionalTask(
            "cg_comp_4",
            "comp_ops_guard",
            ("Computer Operations", "Mathematics", "Verification"),
            "train",
            "multi_skill_composition",
            "# Compose [Computer Operations, Mathematics, Verification]: safe division with fallback on zero den\ndef comp_safe_div(a, b, fallback=0.0):\n    return ",
            "fallback if b == 0 else a / b\n",
            "assert comp_safe_div(8, 2, -1.0) == 4.0 and comp_safe_div(8, 0, -1.0) == -1.0",
        ),
        # --- Stage 3: transfer_consolidation ---
        CompositionalTask(
            "cg_trans_1",
            "trans_learn_adapt",
            ("Learning", "Generalization", "Mathematics"),
            "train",
            "transfer_consolidation",
            "# Transfer [Learning, Generalization, Mathematics]: count elements matching pred\ndef trans_count_match(seq, pred):\n    return ",
            "sum(1 for item in seq if pred(item))\n",
            "assert trans_count_match([1, 2, 3, 4], lambda x: x % 2 == 0) == 2",
        ),
        CompositionalTask(
            "cg_trans_2",
            "trans_learn_adapt",
            ("Learning", "Generalization", "Programming"),
            "train",
            "transfer_consolidation",
            "# Transfer [Learning, Generalization, Programming]: count lowercase vowels a,e,i,o,u\ndef trans_vowel_count(text):\n    return ",
            "sum(1 for ch in text.lower() if ch in 'aeiou')\n",
            "assert trans_vowel_count('AEIOUxyz') == 5",
        ),
        CompositionalTask(
            "cg_trans_3",
            "trans_cap_slice",
            ("Generalization", "Task Planning", "Recovery"),
            "train",
            "transfer_consolidation",
            "# Transfer [Generalization, Task Planning, Recovery]: first k items or [] when k <= 0\ndef trans_take_k(items, k):\n    return ",
            "[] if k <= 0 else list(items)[:k]\n",
            "assert trans_take_k([4, 5, 6], 2) == [4, 5] and trans_take_k([4, 5], 0) == []",
        ),
        CompositionalTask(
            "cg_trans_4",
            "trans_cap_slice",
            ("Generalization", "Computer Operations", "Verification"),
            "train",
            "transfer_consolidation",
            "# Transfer [Generalization, Computer Operations, Verification]: drop None entries\ndef trans_drop_none(items):\n    return ",
            "[x for x in items if x is not None]\n",
            "assert trans_drop_none([1, None, 2, None]) == [1, 2]",
        ),
    ]

    val_items: List[CompositionalTask] = [
        CompositionalTask(
            "val_cg_1",
            "val_comp_mean",
            ("Mathematics", "Recovery", "Verification"),
            "val",
            "multi_skill_composition",
            "# Val Compose: mean of numbers or 0.0 when empty\ndef val_avg_or_zero(vals):\n    return ",
            "0.0 if len(vals) == 0 else sum(vals) / len(vals)\n",
            "assert abs(val_avg_or_zero([2.0, 6.0]) - 4.0) < 1e-6 and val_avg_or_zero([]) == 0.0",
        ),
        CompositionalTask(
            "val_cg_2",
            "val_comp_dedup",
            ("File & Data", "Generalization", "Learning"),
            "val",
            "transfer_consolidation",
            "# Val Compose: unique items sorted ascending\ndef val_distinct_sorted(items):\n    return ",
            "sorted(set(items))\n",
            "assert val_distinct_sorted([3, 1, 3, 2]) == [1, 2, 3]",
        ),
    ]

    heldout_items: List[CompositionalTask] = [
        CompositionalTask(
            "held_cg_1",
            "held_comp_avg",
            ("Reasoning", "Mathematics", "Recovery", "Verification"),
            "heldout",
            "transfer_consolidation",
            "# Held-out Composition: mean of numbers or 0.0 if empty\ndef avg_or_zero(vals):\n    return ",
            "0.0 if len(vals) == 0 else sum(vals) / len(vals)\n",
            "assert abs(avg_or_zero([2.0, 4.0, 6.0]) - 4.0) < 1e-6 and avg_or_zero([]) == 0.0",
        ),
        CompositionalTask(
            "held_cg_2",
            "held_comp_distinct",
            ("File & Data", "Generalization", "Learning", "Self-Correction"),
            "heldout",
            "transfer_consolidation",
            "# Held-out Composition: unique items sorted ascending\ndef distinct_ordered(seq):\n    return ",
            "sorted(set(seq))\n",
            "assert distinct_ordered([4, 2, 4, 1, 2]) == [1, 2, 4] and distinct_ordered([]) == []",
        ),
        CompositionalTask(
            "held_cg_3",
            "held_comp_span",
            ("Task Planning", "Computer Operations", "Mathematics", "Recovery"),
            "heldout",
            "transfer_consolidation",
            "# Held-out Composition: max minus min or 0 if empty\ndef diff_range(nums):\n    return ",
            "0 if len(nums) == 0 else max(nums) - min(nums)\n",
            "assert diff_range([3, 11, 2, 8]) == 9 and diff_range([]) == 0",
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


def _to_coding_tasks(items: Sequence[CompositionalTask], *, category: str) -> List[CodingTask]:
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


def verify_compositional_leakage(
    train_items: Sequence[CompositionalTask],
    val_items: Sequence[CompositionalTask],
    heldout_items: Sequence[CompositionalTask],
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


class CompositionalSandboxEvaluator:
    """Evaluates compositional generalization tasks with sandbox verification and retry."""

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
                    f"{task.prompt.rstrip()}\n# Composition retry {cur_attempt} after {cur_info}\n"
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
    stage_steps: Tuple[int, int, int],
    ckpt_every: int,
    max_new_tokens: int,
    max_attempts: int,
    train_items: List[CompositionalTask],
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
        stg: [x.full_text for x in train_items if x.stage == stg] for stg in STAGE_ORDER
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

    def make_eval(m: NativeTransformerLMV2) -> CompositionalSandboxEvaluator:
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

        return CompositionalSandboxEvaluator(gen_fn, loss_fn, max_attempts=max_attempts)

    pre_ev = make_eval(trainer.model)
    pre_v1, pre_vf = pre_ev.evaluate(val_coding)
    pre_h1, pre_hf = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    stage_logs: List[Dict[str, Any]] = []
    baseline_val_report = pre_vf

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
        stage_logs.append(
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

    final_ckpt = Path(stage_logs[-1]["checkpoint"])
    final_sha = str(stage_logs[-1]["sha256"])
    post_ev = make_eval(trainer.model)
    post_v1, post_vf = post_ev.evaluate(val_coding)
    post_h1, post_hf = post_ev.evaluate(heldout_coding)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(pre_hf, post_hf, baseline_val_report, post_vf, leakage_count=leak_count)
    approval = record_checkpoint_approval(
        final_ckpt,
        final_sha,
        gate_res,
        metadata={
            "seed": seed,
            "suite": "zyrquen_compositional_generalization",
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
            "val_first_pass_rate": pre_v1.exec_pass_rate,
            "val_final_pass_rate": pre_vf.exec_pass_rate,
            "val_loss": pre_vf.avg_loss,
            "heldout_first_pass_rate": pre_h1.exec_pass_rate,
            "heldout_final_pass_rate": pre_hf.exec_pass_rate,
            "heldout_loss": pre_hf.avg_loss,
        },
        "stage_logs": stage_logs,
        "post_compositional": {
            "val_first_pass_rate": post_v1.exec_pass_rate,
            "val_final_pass_rate": post_vf.exec_pass_rate,
            "val_loss": post_vf.avg_loss,
            "val_first_errors": post_v1.error_breakdown,
            "val_final_errors": post_vf.error_breakdown,
            "val_details": post_vf.details,
            "heldout_first_pass_rate": post_h1.exec_pass_rate,
            "heldout_final_pass_rate": post_hf.exec_pass_rate,
            "heldout_loss": post_hf.avg_loss,
            "heldout_first_errors": post_h1.error_breakdown,
            "heldout_final_errors": post_hf.error_breakdown,
            "heldout_details": post_hf.details,
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
    train_items: List[CompositionalTask],
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
        stg: [x.full_text for x in train_items if x.stage == stg] for stg in STAGE_ORDER
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

    def make_eval(m: PureNativeTransformerLMV2) -> CompositionalSandboxEvaluator:
        return CompositionalSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tok, prompt, max_new_tokens=max_new_tokens
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tok, texts)["loss"]),
            max_attempts=max_attempts,
        )

    pre_ev = make_eval(trainer.model)
    pre_v1, pre_vf = pre_ev.evaluate(val_coding)
    pre_h1, pre_hf = pre_ev.evaluate(heldout_coding)

    checkpoints: List[Dict[str, Any]] = []
    stage_logs: List[Dict[str, Any]] = []
    baseline_val_report = pre_vf

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
        stage_logs.append(
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

    final_ckpt = Path(stage_logs[-1]["checkpoint"])
    final_sha = str(stage_logs[-1]["sha256"])
    post_ev = make_eval(trainer.model)
    post_v1, post_vf = post_ev.evaluate(val_coding)
    post_h1, post_hf = post_ev.evaluate(heldout_coding)

    gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    gate_res = gate.evaluate(pre_hf, post_hf, baseline_val_report, post_vf, leakage_count=leak_count)
    approval = record_checkpoint_approval(
        final_ckpt,
        final_sha,
        gate_res,
        metadata={
            "seed": seed,
            "suite": "zyrquen_compositional_generalization",
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
            "val_first_pass_rate": pre_v1.exec_pass_rate,
            "val_final_pass_rate": pre_vf.exec_pass_rate,
            "val_loss": pre_vf.avg_loss,
            "heldout_first_pass_rate": pre_h1.exec_pass_rate,
            "heldout_final_pass_rate": pre_hf.exec_pass_rate,
            "heldout_loss": pre_hf.avg_loss,
        },
        "stage_logs": stage_logs,
        "post_compositional": {
            "val_first_pass_rate": post_v1.exec_pass_rate,
            "val_final_pass_rate": post_vf.exec_pass_rate,
            "val_loss": post_vf.avg_loss,
            "val_first_errors": post_v1.error_breakdown,
            "val_final_errors": post_vf.error_breakdown,
            "val_details": post_vf.details,
            "heldout_first_pass_rate": post_h1.exec_pass_rate,
            "heldout_final_pass_rate": post_hf.exec_pass_rate,
            "heldout_loss": post_hf.avg_loss,
            "heldout_first_errors": post_h1.error_breakdown,
            "heldout_final_errors": post_hf.error_breakdown,
            "heldout_details": post_hf.details,
            "gate": asdict(gate_res),
            "approved": bool(approval["approved"]),
            "status": approval["status"],
            "approved_checkpoint": approval["approved_checkpoint"],
        },
    }


def run_compositional_generalization_suite(
    seeds: Sequence[int] = DEFAULT_COMPOSITIONAL_SEEDS,
    stage_steps: Tuple[int, int, int] = (900, 900, 900),
    ckpt_every: int = 450,
    pure_stage_steps: Tuple[int, int, int] = (8, 8, 8),
    pure_ckpt_every: int = 4,
    pure_max_new_tokens: int = 24,
    pytorch_max_new_tokens: int = 96,
    max_attempts: int = 2,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    train_items, val_items, heldout_items = build_compositional_generalization_splits()
    leaks = verify_compositional_leakage(train_items, val_items, heldout_items)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in compositional corpus: {leaks}")

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

    val_coding = _to_coding_tasks(val_items, category="validation")
    heldout_coding = _to_coding_tasks(heldout_items, category="unseen")
    all_skills = sorted({s for t in (train_items + val_items + heldout_items) for s in t.skills})

    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_comp_big2")
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
            train_items=train_items,
            val_coding=val_coding,
            heldout_coding=heldout_coding,
            leak_count=len(leaks),
            seed_dir=run_root / f"seed_{s}",
        )
        for s in seeds
    ]

    val_1 = [r["post_compositional"]["val_first_pass_rate"] for r in runs]
    val_f = [r["post_compositional"]["val_final_pass_rate"] for r in runs]
    ho_1 = [r["post_compositional"]["heldout_first_pass_rate"] for r in runs]
    ho_f = [r["post_compositional"]["heldout_final_pass_rate"] for r in runs]
    val_losses = [
        float(r["post_compositional"]["val_loss"])
        for r in runs
        if r["post_compositional"]["val_loss"] is not None
    ]
    ho_losses = [
        float(r["post_compositional"]["heldout_loss"])
        for r in runs
        if r["post_compositional"]["heldout_loss"] is not None
    ]
    approved_seeds = [r["seed"] for r in runs if r["post_compositional"]["approved"]]
    all_approved = bool(runs) and len(approved_seeds) == len(runs)

    manifest: Dict[str, Any] = {
        "suite": "zyrquen_compositional_generalization",
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
            "train": len(train_items),
            "val": len(val_items),
            "heldout": len(heldout_items),
        },
        "summary": {
            "mean_val_first_pass_rate": round(sum(val_1) / max(len(val_1), 1), 4),
            "mean_val_final_pass_rate": round(sum(val_f) / max(len(val_f), 1), 4),
            "mean_val_loss": round(sum(val_losses) / max(len(val_losses), 1), 4) if val_losses else None,
            "mean_heldout_first_pass_rate": round(sum(ho_1) / max(len(ho_1), 1), 4),
            "mean_heldout_final_pass_rate": round(sum(ho_f) / max(len(ho_f), 1), 4),
            "min_heldout_final_pass_rate": round(min(ho_f), 4) if ho_f else 0.0,
            "mean_heldout_loss": round(sum(ho_losses) / max(len(ho_losses), 1), 4) if ho_losses else None,
            "heldout_first_error_breakdown": {
                k: sum(int(r["post_compositional"]["heldout_first_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "heldout_final_error_breakdown": {
                k: sum(int(r["post_compositional"]["heldout_final_errors"].get(k, 0)) for r in runs)
                for k in ERROR_TYPES
            },
            "approved_seeds": approved_seeds,
            "any_approved": bool(approved_seeds),
            "overall_approval_status": "APPROVED" if all_approved else "REJECTED_BY_GATE",
        },
        "runs": runs,
    }
    manifest_path = run_root / "manifest_comp_big2.json"
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
        description="Run ZYRQUEN V2 Compositional Generalization & Continual Consolidation Suite"
    )
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--stage-steps", default="900,900,900")
    ap.add_argument("--ckpt-every", type=int, default=450)
    ap.add_argument("--pure-stage-steps", default="8,8,8")
    ap.add_argument("--pure-ckpt-every", type=int, default=4)
    ap.add_argument("--pure-max-new-tokens", type=int, default=24)
    ap.add_argument("--pytorch-max-new-tokens", type=int, default=96)
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    try:
        ss = _parse_int_tuple(args.stage_steps, 3)
        pss = _parse_int_tuple(args.pure_stage_steps, 3)
        res = run_compositional_generalization_suite(
            seeds=_parse_int_tuple(args.seeds),
            stage_steps=(ss[0], ss[1], ss[2]),
            ckpt_every=args.ckpt_every,
            pure_stage_steps=(pss[0], pss[1], pss[2]),
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
        p = r["post_compositional"]
        print(f"\n=== SEED {r['seed']} (status={p['status']}) ===")
        print("heldout_first_errors:", p["heldout_first_errors"])
        print("heldout_final_errors:", p["heldout_final_errors"])
        for item in p["heldout_details"]:
            print(
                f"  [heldout] {item['task_id']} first={item['first_attempt_passed']} "
                f"final={item['passed']} attempts={item['attempts_used']} info={item['info']!r}"
            )
            print(f"    raw_output: {item['raw_output']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
