"""ZYRQUEN V2 Execution Skills Training & Sandbox Runner (Code Exec + Debugging).

Trains Native ZYRQUEN V2 from random initialization only (zero external models):
  Stage 1: `code_exec` skill corpus
  Stage 2: Continual `debugging` skill corpus (snapshot consolidation + SHA-256 checkpoint
           continuity + replay_ratio=0.5 + RoPE context extension)

Evaluates pre-training (random init), post-Stage-1 (`after_code_exec_only`), and
post-Stage-2 (`post_exec_and_debug`) on strictly disjoint task-family Validation and
Held-out Test splits inside the isolated Python sandbox, recording full `raw_output`,
`val_errors`, `heldout_errors`, and fail-closed `ApprovalGate` verdicts.
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

DEFAULT_EXEC_DEBUG_SEEDS: Tuple[int, ...] = (42, 1337, 2026)


@dataclass(frozen=True)
class SkillExample:
    task_id: str
    skill: str  # "code_exec" | "debugging"
    family: str
    prompt: str
    target_code: str
    test_code: str

    @property
    def full_text(self) -> str:
        return self.prompt + self.target_code

    def to_coding_task(self, category: str) -> CodingTask:
        return CodingTask(
            task_id=self.task_id,
            prompt=self.prompt,
            reference_solution=self.full_text,
            test_code=self.test_code,
            family=self.family,
            category=category,
        )


def build_exec_debug_splits() -> Tuple[
    List[SkillExample], List[SkillExample], List[SkillExample]
]:
    """Strictly disjoint Train / Validation / Held-out Test splits grouped by task family."""

    # --- TRAIN FAMILIES: arithmetic_logic, list_ops, text_ops, guard_clauses ---
    train_examples: List[SkillExample] = [
        # Skill 1: Code Execution (synthesis from spec)
        SkillExample(
            task_id="tr_arith_1",
            skill="code_exec",
            family="arithmetic_logic",
            prompt="def sum_even(nums):\n    ",
            target_code=(
                "total = 0\n"
                "    for x in nums:\n"
                "        if x % 2 == 0:\n"
                "            total += x\n"
                "    return total\n"
            ),
            test_code="assert sum_even([1, 2, 3, 4, 6]) == 12 and sum_even([]) == 0",
        ),
        SkillExample(
            task_id="tr_arith_2",
            skill="code_exec",
            family="arithmetic_logic",
            prompt="def clamp_val(x, low, high):\n    ",
            target_code=(
                "if x < low:\n"
                "        return low\n"
                "    if x > high:\n"
                "        return high\n"
                "    return x\n"
            ),
            test_code="assert clamp_val(-5, 0, 10) == 0 and clamp_val(15, 0, 10) == 10 and clamp_val(4, 0, 10) == 4",
        ),
        SkillExample(
            task_id="tr_arith_3",
            skill="code_exec",
            family="arithmetic_logic",
            prompt="def count_pos(nums):\n    ",
            target_code=(
                "c = 0\n"
                "    for n in nums:\n"
                "        if n > 0:\n"
                "            c += 1\n"
                "    return c\n"
            ),
            test_code="assert count_pos([-2, 0, 3, 5]) == 2 and count_pos([]) == 0",
        ),
        SkillExample(
            task_id="tr_list_1",
            skill="code_exec",
            family="list_ops",
            prompt="def tail_or_default(seq, default=None):\n    ",
            target_code=(
                "if not seq:\n"
                "        return default\n"
                "    return seq[-1]\n"
            ),
            test_code="assert tail_or_default([10, 20]) == 20 and tail_or_default([], -1) == -1",
        ),
        SkillExample(
            task_id="tr_list_2",
            skill="code_exec",
            family="list_ops",
            prompt="def square_nonneg(nums):\n    ",
            target_code="return [x * x for x in nums if x >= 0]\n",
            test_code="assert square_nonneg([-3, 0, 2, 4]) == [0, 4, 16]",
        ),
        SkillExample(
            task_id="tr_list_3",
            skill="code_exec",
            family="list_ops",
            prompt="def flatten_pairs(pairs):\n    ",
            target_code=(
                "out = []\n"
                "    for a, b in pairs:\n"
                "        out.append(a)\n"
                "        out.append(b)\n"
                "    return out\n"
            ),
            test_code="assert flatten_pairs([(1, 2), (3, 4)]) == [1, 2, 3, 4] and flatten_pairs([]) == []",
        ),
        SkillExample(
            task_id="tr_text_1",
            skill="code_exec",
            family="text_ops",
            prompt="def clean_lower(text):\n    ",
            target_code='return (text or "").strip().lower()\n',
            test_code='assert clean_lower("  HeLLo  ") == "hello" and clean_lower("") == ""',
        ),
        SkillExample(
            task_id="tr_text_2",
            skill="code_exec",
            family="text_ops",
            prompt="def count_words(text):\n    ",
            target_code='return len([w for w in (text or "").split() if w])\n',
            test_code='assert count_words("  one   two three ") == 3 and count_words("") == 0',
        ),
        SkillExample(
            task_id="tr_guard_1",
            skill="code_exec",
            family="guard_clauses",
            prompt="def safe_ratio(num, den):\n    ",
            target_code=(
                "if den == 0:\n"
                "        return 0.0\n"
                "    return num / den\n"
            ),
            test_code="assert safe_ratio(6, 3) == 2.0 and safe_ratio(5, 0) == 0.0",
        ),
        # Skill 2: Debugging (given buggy code, produce fixed implementation)
        SkillExample(
            task_id="tr_dbg_arith_1",
            skill="debugging",
            family="arithmetic_logic",
            prompt=(
                "# Fix the off-by-one / boundary bug:\n"
                "# BUGGY:\n"
                "# def sum_below(nums, limit):\n"
                "#     return sum(x for x in nums if x <= limit)\n"
                "def sum_below(nums, limit):\n    "
            ),
            target_code="return sum(x for x in nums if x < limit)\n",
            test_code="assert sum_below([1, 5, 10], 5) == 1",
        ),
        SkillExample(
            task_id="tr_dbg_arith_2",
            skill="debugging",
            family="arithmetic_logic",
            prompt=(
                "# Fix the comparison operator bug:\n"
                "# BUGGY:\n"
                "# def is_in_range(x, low, high):\n"
                "#     return low < x < high\n"
                "def is_in_range(x, low, high):\n    "
            ),
            target_code="return low <= x <= high\n",
            test_code="assert is_in_range(0, 0, 5) and is_in_range(5, 0, 5) and not is_in_range(6, 0, 5)",
        ),
        SkillExample(
            task_id="tr_dbg_arith_3",
            skill="debugging",
            family="arithmetic_logic",
            prompt=(
                "# Fix the accumulator initialization bug:\n"
                "# BUGGY:\n"
                "# def product_all(nums):\n"
                "#     total = 0\n"
                "#     for x in nums:\n"
                "#         total *= x\n"
                "#     return total\n"
                "def product_all(nums):\n    "
            ),
            target_code=(
                "total = 1\n"
                "    for x in nums:\n"
                "        total *= x\n"
                "    return total\n"
            ),
            test_code="assert product_all([2, 3, 4]) == 24 and product_all([]) == 1",
        ),
        SkillExample(
            task_id="tr_dbg_list_1",
            skill="debugging",
            family="list_ops",
            prompt=(
                "# Fix the empty-list crash bug:\n"
                "# BUGGY:\n"
                "# def head_or_none(seq):\n"
                "#     return seq[0]\n"
                "def head_or_none(seq):\n    "
            ),
            target_code=(
                "if not seq:\n"
                "        return None\n"
                "    return seq[0]\n"
            ),
            test_code="assert head_or_none([7, 8]) == 7 and head_or_none([]) is None",
        ),
        SkillExample(
            task_id="tr_dbg_list_2",
            skill="debugging",
            family="list_ops",
            prompt=(
                "# Fix the in-place mutation bug:\n"
                "# BUGGY:\n"
                "# def append_tag(items, tag):\n"
                "#     items.append(tag)\n"
                "#     return items\n"
                "def append_tag(items, tag):\n    "
            ),
            target_code=(
                "out = list(items)\n"
                "    out.append(tag)\n"
                "    return out\n"
            ),
            test_code="src = [1, 2]; out = append_tag(src, 3); assert src == [1, 2] and out == [1, 2, 3]",
        ),
        SkillExample(
            task_id="tr_dbg_list_3",
            skill="debugging",
            family="list_ops",
            prompt=(
                "# Fix the wrong index slice bug:\n"
                "# BUGGY:\n"
                "# def last_n(seq, n):\n"
                "#     return seq[:n]\n"
                "def last_n(seq, n):\n    "
            ),
            target_code=(
                "if n <= 0:\n"
                "        return []\n"
                "    return seq[-n:]\n"
            ),
            test_code="assert last_n([1, 2, 3, 4], 2) == [3, 4] and last_n([1, 2], 0) == []",
        ),
        SkillExample(
            task_id="tr_dbg_text_1",
            skill="debugging",
            family="text_ops",
            prompt=(
                "# Fix the None-input AttributeError bug:\n"
                "# BUGGY:\n"
                "# def first_token(text):\n"
                "#     return text.strip().split()[0]\n"
                "def first_token(text):\n    "
            ),
            target_code=(
                'parts = (text or "").strip().split()\n'
                '    return parts[0] if parts else ""\n'
            ),
            test_code='assert first_token("  hi all ") == "hi" and first_token(None) == "" and first_token("   ") == ""',
        ),
        SkillExample(
            task_id="tr_dbg_text_2",
            skill="debugging",
            family="text_ops",
            prompt=(
                "# Fix the missing delimiter normalization bug:\n"
                "# BUGGY:\n"
                '# def join_nonempty(words):\n'
                '#     return ",".join(words)\n'
                "def join_nonempty(words):\n    "
            ),
            target_code='return ",".join(w for w in words if w)\n',
            test_code='assert join_nonempty(["a", "", "b", None]) == "a,b"',
        ),
        SkillExample(
            task_id="tr_dbg_guard_1",
            skill="debugging",
            family="guard_clauses",
            prompt=(
                "# Fix the ZeroDivisionError / empty bug:\n"
                "# BUGGY:\n"
                "# def mean_val(nums):\n"
                "#     return sum(nums) / len(nums)\n"
                "def mean_val(nums):\n    "
            ),
            target_code=(
                "if not nums:\n"
                "        return 0.0\n"
                "    return sum(nums) / len(nums)\n"
            ),
            test_code="assert mean_val([2.0, 4.0]) == 3.0 and mean_val([]) == 0.0",
        ),
    ]

    # --- VALIDATION FAMILY (unseen family: dict_summary) ---
    val_examples: List[SkillExample] = [
        SkillExample(
            task_id="val_dict_1",
            skill="code_exec",
            family="dict_summary",
            prompt="def sum_numeric_values(d):\n    ",
            target_code=(
                "vals = [v for v in (d or {}).values() if isinstance(v, (int, float))]\n"
                "    return sum(vals) if vals else 0\n"
            ),
            test_code='assert sum_numeric_values({"a": 2, "b": "x", "c": 3}) == 5 and sum_numeric_values({}) == 0',
        ),
        SkillExample(
            task_id="val_dict_2",
            skill="debugging",
            family="dict_summary",
            prompt=(
                "# Fix the KeyError when key is missing:\n"
                "# BUGGY:\n"
                "# def get_int_or_zero(d, k):\n"
                "#     return int(d[k])\n"
                "def get_int_or_zero(d, k):\n    "
            ),
            target_code=(
                "if not isinstance(d, dict) or k not in d or d[k] is None:\n"
                "        return 0\n"
                "    return int(d[k])\n"
            ),
            test_code='assert get_int_or_zero({"x": "4"}, "x") == 4 and get_int_or_zero({"x": 1}, "y") == 0',
        ),
    ]

    # --- HELD-OUT TEST FAMILIES (completely unseen: safe_aggregation, ordered_dedup, bounded_range) ---
    heldout_examples: List[SkillExample] = [
        SkillExample(
            task_id="test_safe_agg_1",
            skill="code_exec",
            family="safe_aggregation",
            prompt="def avg_valid_numbers(nums):\n    ",
            target_code=(
                "valid = [x for x in (nums or []) if isinstance(x, (int, float)) and not isinstance(x, bool)]\n"
                "    return (sum(valid) / len(valid)) if valid else 0.0\n"
            ),
            test_code='assert abs(avg_valid_numbers([2, "bad", True, 6]) - 4.0) < 1e-6 and avg_valid_numbers([]) == 0.0',
        ),
        SkillExample(
            task_id="test_dedup_dbg_1",
            skill="debugging",
            family="ordered_dedup",
            prompt=(
                "# Fix the bug that destroys order and crashes on None:\n"
                "# BUGGY:\n"
                "# def unique_in_order(seq):\n"
                "#     return list(set(seq))\n"
                "def unique_in_order(seq):\n    "
            ),
            target_code=(
                "seen = set()\n"
                "    out = []\n"
                "    for x in (seq or []):\n"
                "        if x not in seen:\n"
                "            seen.add(x)\n"
                "            out.append(x)\n"
                "    return out\n"
            ),
            test_code="assert unique_in_order([3, 1, 3, 2, 1]) == [3, 1, 2] and unique_in_order(None) == []",
        ),
        SkillExample(
            task_id="test_range_dbg_1",
            skill="debugging",
            family="bounded_range",
            prompt=(
                "# Fix the empty-input ValueError and negative-clamp bug:\n"
                "# BUGGY:\n"
                "# def clipped_span(nums, max_span):\n"
                "#     return min(max(nums) - min(nums), max_span)\n"
                "def clipped_span(nums, max_span):\n    "
            ),
            target_code=(
                "if not nums:\n"
                "        return 0\n"
                "    span = max(nums) - min(nums)\n"
                "    return min(span, max(0, max_span))\n"
            ),
            test_code="assert clipped_span([3, 11, 2], 5) == 5 and clipped_span([], 5) == 0 and clipped_span([1, 4], -2) == 0",
        ),
    ]

    train_fams = {e.family for e in train_examples}
    val_fams = {e.family for e in val_examples}
    test_fams = {e.family for e in heldout_examples}
    assert not (train_fams & val_fams), f"Family leakage train/val: {train_fams & val_fams}"
    assert not (train_fams & test_fams), f"Family leakage train/test: {train_fams & test_fams}"
    assert not (val_fams & test_fams), f"Family leakage val/test: {val_fams & test_fams}"

    return train_examples, val_examples, heldout_examples


def verify_exec_debug_leakage(
    train_examples: Sequence[SkillExample],
    val_examples: Sequence[SkillExample],
    heldout_examples: Sequence[SkillExample],
) -> List[Dict[str, str]]:
    train_texts = [e.full_text for e in train_examples]
    eval_tasks = [e.to_coding_task("validation") for e in val_examples] + [
        e.to_coding_task("unseen") for e in heldout_examples
    ]
    return detect_task_leakage(train_texts, eval_tasks)


def classify_error(passed: bool, info: str) -> str:
    if passed:
        return "passed"
    txt = str(info or "")
    if txt == "timeout":
        return "timeout"
    if "IndentationError" in txt or "TabError" in txt or "SyntaxError" in txt:
        return "SyntaxError"
    for name in ("NameError", "TypeError", "AssertionError"):
        if name in txt:
            return name
    return "other"


class SkillSandboxEvaluator:
    """Runs isolated sandbox checks and records full raw_output, info, and error breakdown."""

    def __init__(
        self,
        generate_fn: Callable[[str], str],
        loss_fn: Callable[[List[str]], Optional[float]],
    ) -> None:
        self.generate_fn = generate_fn
        self.loss_fn = loss_fn

    def evaluate(self, examples: Sequence[SkillExample], *, category: str) -> EvalReport:
        loss_texts = [ex.full_text for ex in examples]
        avg_loss = self.loss_fn(loss_texts)
        details: List[Dict[str, Any]] = []
        passed = 0
        counts: Counter[str] = Counter()

        for ex in examples:
            raw_out = self.generate_fn(ex.prompt)
            extracted = extract_first_python_function(raw_out)
            ok, msg = run_code_in_sandbox(raw_out, ex.test_code)
            err = classify_error(ok, msg)
            counts[err] += 1
            if ok:
                passed += 1
            details.append(
                {
                    "task_id": ex.task_id,
                    "skill": ex.skill,
                    "family": ex.family,
                    "category": category,
                    "passed": ok,
                    "error_type": err,
                    "info": msg,
                    "raw_output": raw_out,
                    "extracted_code": extracted,
                }
            )

        breakdown = {k: int(counts.get(k, 0)) for k in ERROR_TYPES}
        return EvalReport(
            avg_loss=round(avg_loss, 4) if avg_loss is not None else None,
            exec_pass_rate=round(passed / max(len(examples), 1), 4),
            passed_count=passed,
            total_count=len(examples),
            details=details,
            error_breakdown=breakdown,
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
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
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


def _report_snapshot(rep: EvalReport) -> Dict[str, Any]:
    return {
        "exec_pass_rate": rep.exec_pass_rate,
        "passed_count": rep.passed_count,
        "total_count": rep.total_count,
        "avg_loss": rep.avg_loss,
        "error_breakdown": rep.error_breakdown,
        "details": rep.details,
    }


def _run_seed_pytorch(
    seed: int,
    steps_exec: int,
    steps_debug: int,
    ckpt_every: int,
    max_new_tokens: int,
    exec_texts: List[str],
    debug_texts: List[str],
    val_examples: Sequence[SkillExample],
    heldout_examples: Sequence[SkillExample],
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

    cfg = ZyrquenV2Config(
        vocab_size=tok.vocab_size,
        d_model=256,
        n_heads=8,
        n_layers=6,
        d_ff=768,
        base_seq_len=512,
        max_seq_len=512,
        dropout=0.05,
    )
    trainer = ContinualTrainerV2(
        NativeTransformerLMV2(cfg),
        tok,
        lr=8e-4,
        warmup_steps=40,
        total_decay_steps=steps_exec + steps_debug + 80,
        consolidation_lambda=0.01,
        seed=seed,
        device=device,
    )

    def make_eval(m: NativeTransformerLMV2) -> SkillSandboxEvaluator:
        def gen(prompt: str) -> str:
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
            return sum(vals) / max(len(vals), 1)

        return SkillSandboxEvaluator(gen, loss_fn)

    pre_ev = make_eval(trainer.model)
    pre_val = pre_ev.evaluate(val_examples, category="validation")
    pre_test = pre_ev.evaluate(heldout_examples, category="unseen")

    periodic_ckpts: List[Dict[str, Any]] = []
    done = 0
    while done < steps_exec:
        chunk = min(ckpt_every, steps_exec - done)
        trainer.train_steps(exec_texts, steps=chunk, batch_size=4, replay_ratio=0.0)
        done += chunk
        c_path, c_sha = trainer.save_checkpoint(ckpt_dir / f"p1_exec_step_{done}.pt")
        periodic_ckpts.append({"phase": "code_exec", "step": done, "path": str(c_path), "sha256": c_sha})

    trainer.snapshot_consolidation_state(exec_texts, batch_size=4)
    p1_ckpt, p1_sha = trainer.save_checkpoint(ckpt_dir / "stage1_code_exec_final.pt")

    p1_ev = make_eval(trainer.model)
    p1_val = p1_ev.evaluate(val_examples, category="validation")
    p1_test = p1_ev.evaluate(heldout_examples, category="unseen")

    resumed = ContinualTrainerV2.load_checkpoint(
        p1_ckpt,
        tok,
        expected_sha256=p1_sha,
        resume_optimizer=True,
        restore_continual_state=True,
        consolidation_lambda=0.01,
        device=device,
    )
    resumed.model.extend_context(1024)

    done = 0
    while done < steps_debug:
        chunk = min(ckpt_every, steps_debug - done)
        resumed.train_steps(debug_texts, steps=chunk, batch_size=4, replay_ratio=0.5)
        done += chunk
        c_path, c_sha = resumed.save_checkpoint(ckpt_dir / f"p2_debug_step_{done}.pt")
        periodic_ckpts.append({"phase": "debugging", "step": done, "path": str(c_path), "sha256": c_sha})

    resumed.snapshot_consolidation_state(exec_texts + debug_texts, batch_size=4)
    p2_ckpt, p2_sha = resumed.save_checkpoint(ckpt_dir / "stage2_exec_debug_final.pt")

    post_ev = make_eval(resumed.model)
    post_val = post_ev.evaluate(val_examples, category="validation")
    post_test = post_ev.evaluate(heldout_examples, category="unseen")

    gate = ApprovalGate(
        min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True
    ).evaluate(pre_test, post_test, p1_test, post_test, leakage_count=leak_count)
    approval = record_checkpoint_approval(
        p2_ckpt,
        p2_sha,
        gate,
        metadata={"seed": seed, "skills": ["code_exec", "debugging"], "backend": "pytorch"},
    )

    return {
        "seed": seed,
        "backend": "pytorch",
        "device": device.type,
        "steps_exec": steps_exec,
        "steps_debug": steps_debug,
        "global_step_final": resumed.global_step,
        "checkpoints": {
            "stage1_code_exec": {"path": str(p1_ckpt), "sha256": p1_sha},
            "stage2_exec_debug": {
                "path": str(p2_ckpt),
                "sha256": p2_sha,
                "approved": approval["approved"],
                "status": approval["status"],
                "approval_record": approval["approval_record_path"],
            },
            "periodic": periodic_ckpts,
        },
        "pre_random_init": {
            "val": _report_snapshot(pre_val),
            "heldout": _report_snapshot(pre_test),
        },
        "after_code_exec_only": {
            "val": _report_snapshot(p1_val),
            "heldout": _report_snapshot(p1_test),
        },
        "post_exec_and_debug": {
            "val": _report_snapshot(post_val),
            "heldout": _report_snapshot(post_test),
        },
        "gate": asdict(gate),
        "approved": bool(approval["approved"]),
        "approval_status": approval["status"],
    }


def _run_seed_pure(
    seed: int,
    steps_exec: int,
    steps_debug: int,
    ckpt_every: int,
    max_new_tokens: int,
    exec_texts: List[str],
    debug_texts: List[str],
    val_examples: Sequence[SkillExample],
    heldout_examples: Sequence[SkillExample],
    leak_count: int,
    seed_dir: Path,
) -> Dict[str, Any]:
    ckpt_dir = seed_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    random.seed(seed)
    tok = ByteTokenizer()

    # Pure-Python RoPE + SwiGLU + RMSNorm V2 architecture (seq_len >= 256 fits full train texts)
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
        total_decay_steps=max(steps_exec + steps_debug + 8, 24),
        consolidation_lambda=0.01,
        seed=seed,
    )

    def make_eval(m: PureNativeTransformerLMV2) -> SkillSandboxEvaluator:
        return SkillSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tok, prompt, max_new_tokens=max_new_tokens
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tok, texts)["loss"]),
        )

    pre_ev = make_eval(trainer.model)
    pre_val = pre_ev.evaluate(val_examples, category="validation")
    pre_test = pre_ev.evaluate(heldout_examples, category="unseen")

    periodic_ckpts: List[Dict[str, Any]] = []
    done = 0
    while done < steps_exec:
        chunk = min(ckpt_every, steps_exec - done)
        trainer.train_steps(exec_texts, steps=chunk, batch_size=2, replay_ratio=0.0)
        done += chunk
        c_path, c_sha = trainer.save_checkpoint(ckpt_dir / f"p1_exec_step_{done}.json.gz")
        periodic_ckpts.append({"phase": "code_exec", "step": done, "path": str(c_path), "sha256": c_sha})

    trainer.snapshot_consolidation_state(exec_texts)
    p1_ckpt, p1_sha = trainer.save_checkpoint(ckpt_dir / "stage1_code_exec_final.json.gz")

    p1_ev = make_eval(trainer.model)
    p1_val = p1_ev.evaluate(val_examples, category="validation")
    p1_test = p1_ev.evaluate(heldout_examples, category="unseen")

    resumed = PureContinualTrainerV2.load_checkpoint(
        p1_ckpt,
        tokenizer=tok,
        expected_sha256=p1_sha,
        resume_optimizer=True,
        restore_continual_state=True,
        consolidation_lambda=0.01,
    )
    resumed.model.extend_context(512)

    done = 0
    while done < steps_debug:
        chunk = min(ckpt_every, steps_debug - done)
        resumed.train_steps(debug_texts, steps=chunk, batch_size=2, replay_ratio=0.5)
        done += chunk
        c_path, c_sha = resumed.save_checkpoint(ckpt_dir / f"p2_debug_step_{done}.json.gz")
        periodic_ckpts.append({"phase": "debugging", "step": done, "path": str(c_path), "sha256": c_sha})

    if _has_non_finite_pure(resumed.model.params):
        raise RuntimeError("Training halted: NaN/Inf detected in pure model parameters")

    resumed.snapshot_consolidation_state(exec_texts + debug_texts)
    p2_ckpt, p2_sha = resumed.save_checkpoint(ckpt_dir / "stage2_exec_debug_final.json.gz")

    post_ev = make_eval(resumed.model)
    post_val = post_ev.evaluate(val_examples, category="validation")
    post_test = post_ev.evaluate(heldout_examples, category="unseen")

    gate = ApprovalGate(
        min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True
    ).evaluate(pre_test, post_test, p1_test, post_test, leakage_count=leak_count)
    approval = record_checkpoint_approval(
        p2_ckpt,
        p2_sha,
        gate,
        metadata={
            "seed": seed,
            "skills": ["code_exec", "debugging"],
            "backend": "pure_python_3.11_stdlib",
        },
    )

    return {
        "seed": seed,
        "backend": "pure_python_3.11_stdlib",
        "device": "pure_python_3.11_stdlib",
        "steps_exec": steps_exec,
        "steps_debug": steps_debug,
        "global_step_final": resumed.global_step,
        "checkpoints": {
            "stage1_code_exec": {"path": str(p1_ckpt), "sha256": p1_sha},
            "stage2_exec_debug": {
                "path": str(p2_ckpt),
                "sha256": p2_sha,
                "approved": approval["approved"],
                "status": approval["status"],
                "approval_record": approval["approval_record_path"],
            },
            "periodic": periodic_ckpts,
        },
        "pre_random_init": {
            "val": _report_snapshot(pre_val),
            "heldout": _report_snapshot(pre_test),
        },
        "after_code_exec_only": {
            "val": _report_snapshot(p1_val),
            "heldout": _report_snapshot(p1_test),
        },
        "post_exec_and_debug": {
            "val": _report_snapshot(post_val),
            "heldout": _report_snapshot(post_test),
        },
        "gate": asdict(gate),
        "approved": bool(approval["approved"]),
        "approval_status": approval["status"],
    }


def _aggregate_error_breakdowns(items: Sequence[Dict[str, int]]) -> Dict[str, int]:
    return {
        err_type: sum(int(item.get(err_type, 0)) for item in items)
        for err_type in ERROR_TYPES
    }


def run_exec_debug_experiment(
    *,
    seeds: Sequence[int] = DEFAULT_EXEC_DEBUG_SEEDS,
    steps_exec: int = 800,
    steps_debug: int = 800,
    ckpt_every: int = 200,
    pure_steps_exec: int = 24,
    pure_steps_debug: int = 24,
    pure_ckpt_every: int = 12,
    pure_max_new_tokens: int = 48,
    pytorch_max_new_tokens: int = 128,
    out_dir: Optional[str] = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    train_ex, val_ex, heldout_ex = build_exec_debug_splits()
    leaks = verify_exec_debug_leakage(train_ex, val_ex, heldout_ex)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in exec/debug splits: {leaks}")

    resolved_backend, torch_available = _resolve_backend(backend)
    use_pytorch = resolved_backend == "pytorch"

    eff_steps_exec = steps_exec if use_pytorch else min(steps_exec, pure_steps_exec)
    eff_steps_debug = steps_debug if use_pytorch else min(steps_debug, pure_steps_debug)
    eff_ckpt_every = ckpt_every if use_pytorch else min(ckpt_every, pure_ckpt_every)
    eff_max_new_tokens = pytorch_max_new_tokens if use_pytorch else pure_max_new_tokens

    exec_texts = [e.full_text for e in train_ex if e.skill == "code_exec"]
    debug_texts = [e.full_text for e in train_ex if e.skill == "debugging"]

    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_dir = Path(out_dir) if out_dir is not None else default_output_root("zyrquen_exec_debug")
    run_root = base_dir / f"run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    seed_runner = _run_seed_pytorch if use_pytorch else _run_seed_pure
    per_seed = [
        seed_runner(
            seed=int(s),
            steps_exec=eff_steps_exec,
            steps_debug=eff_steps_debug,
            ckpt_every=eff_ckpt_every,
            max_new_tokens=eff_max_new_tokens,
            exec_texts=exec_texts,
            debug_texts=debug_texts,
            val_examples=val_ex,
            heldout_examples=heldout_ex,
            leak_count=len(leaks),
            seed_dir=run_root / f"seed_{s}",
        )
        for s in seeds
    ]

    approved_seeds = [r["seed"] for r in per_seed if r["approved"]]
    rejected_seeds = [r["seed"] for r in per_seed if not r["approved"]]

    def stage_summary(stage_key: str) -> Dict[str, Any]:
        val_rates = [float(r[stage_key]["val"]["exec_pass_rate"]) for r in per_seed]
        test_rates = [float(r[stage_key]["heldout"]["exec_pass_rate"]) for r in per_seed]
        val_losses = [
            float(r[stage_key]["val"]["avg_loss"])
            for r in per_seed
            if r[stage_key]["val"]["avg_loss"] is not None
        ]
        test_losses = [
            float(r[stage_key]["heldout"]["avg_loss"])
            for r in per_seed
            if r[stage_key]["heldout"]["avg_loss"] is not None
        ]
        return {
            "mean_val_pass_rate": round(sum(val_rates) / max(len(val_rates), 1), 4),
            "mean_heldout_pass_rate": round(sum(test_rates) / max(len(test_rates), 1), 4),
            "mean_val_loss": round(sum(val_losses) / max(len(val_losses), 1), 4) if val_losses else None,
            "mean_heldout_loss": round(sum(test_losses) / max(len(test_losses), 1), 4) if test_losses else None,
            "val_error_breakdown": _aggregate_error_breakdowns(
                [r[stage_key]["val"]["error_breakdown"] for r in per_seed]
            ),
            "heldout_error_breakdown": _aggregate_error_breakdowns(
                [r[stage_key]["heldout"]["error_breakdown"] for r in per_seed]
            ),
        }

    all_approved = len(per_seed) > 0 and len(approved_seeds) == len(per_seed)
    summary = {
        "pre_random_init": stage_summary("pre_random_init"),
        "after_code_exec_only": stage_summary("after_code_exec_only"),
        "post_exec_and_debug": stage_summary("post_exec_and_debug"),
        "approved_seeds": approved_seeds,
        "rejected_seeds": rejected_seeds,
        "all_seeds_approved": all_approved,
        "overall_approval_status": "APPROVED" if all_approved else "REJECTED_BY_GATE",
    }

    manifest: Dict[str, Any] = {
        "suite": "zyrquen_v2_exec_debug_skills",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "torch_available": torch_available,
        "external_models_used": False,
        "initialization": "random_from_scratch",
        "elapsed_sec": round(time.time() - t0, 2),
        "seeds": [int(s) for s in seeds],
        "effective_steps": {
            "code_exec": eff_steps_exec,
            "debugging": eff_steps_debug,
            "checkpoint_every": eff_ckpt_every,
            "max_new_tokens": eff_max_new_tokens,
        },
        "splits": {
            "train_count": len(train_ex),
            "train_families": sorted({e.family for e in train_ex}),
            "val_count": len(val_ex),
            "val_families": sorted({e.family for e in val_ex}),
            "heldout_count": len(heldout_ex),
            "heldout_families": sorted({e.family for e in heldout_ex}),
        },
        "leakage_count": len(leaks),
        "summary": summary,
        "runs": per_seed,
    }
    manifest_path = run_root / "manifest_exec_debug.json"
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
    ap = argparse.ArgumentParser(description="Run ZYRQUEN V2 Execution & Debugging Skills Experiment")
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--seeds", default="42,1337,2026")
    ap.add_argument("--steps-exec", type=int, default=800)
    ap.add_argument("--steps-debug", type=int, default=800)
    ap.add_argument("--ckpt-every", type=int, default=200)
    ap.add_argument("--pure-steps-exec", type=int, default=24)
    ap.add_argument("--pure-steps-debug", type=int, default=24)
    ap.add_argument("--pure-ckpt-every", type=int, default=12)
    ap.add_argument("--pure-max-new-tokens", type=int, default=48)
    ap.add_argument("--pytorch-max-new-tokens", type=int, default=128)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    try:
        res = run_exec_debug_experiment(
            seeds=_parse_seeds(args.seeds),
            steps_exec=args.steps_exec,
            steps_debug=args.steps_debug,
            ckpt_every=args.ckpt_every,
            pure_steps_exec=args.pure_steps_exec,
            pure_steps_debug=args.pure_steps_debug,
            pure_ckpt_every=args.pure_ckpt_every,
            pure_max_new_tokens=args.pure_max_new_tokens,
            pytorch_max_new_tokens=args.pytorch_max_new_tokens,
            out_dir=args.out_dir,
            backend=args.backend,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    compact_summary = {
        "suite": res["suite"],
        "backend": res["backend"],
        "torch_available": res["torch_available"],
        "elapsed_sec": res["elapsed_sec"],
        "leakage_count": res["leakage_count"],
        "effective_steps": res["effective_steps"],
        "manifest_path": res["manifest_path"],
        "manifest_sha256": res["manifest_sha256"],
        "summary": res["summary"],
        "per_seed_overview": [
            {
                "seed": r["seed"],
                "global_step_final": r["global_step_final"],
                "pre_val": r["pre_random_init"]["val"]["exec_pass_rate"],
                "pre_heldout": r["pre_random_init"]["heldout"]["exec_pass_rate"],
                "after_exec_val": r["after_code_exec_only"]["val"]["exec_pass_rate"],
                "after_exec_heldout": r["after_code_exec_only"]["heldout"]["exec_pass_rate"],
                "post_val": r["post_exec_and_debug"]["val"]["exec_pass_rate"],
                "post_heldout": r["post_exec_and_debug"]["heldout"]["exec_pass_rate"],
                "post_val_loss": r["post_exec_and_debug"]["val"]["avg_loss"],
                "post_heldout_loss": r["post_exec_and_debug"]["heldout"]["avg_loss"],
                "val_errors": r["post_exec_and_debug"]["val"]["error_breakdown"],
                "heldout_errors": r["post_exec_and_debug"]["heldout"]["error_breakdown"],
                "approval_status": r["approval_status"],
                "gate_reason": r["gate"]["reason"],
            }
            for r in res["runs"]
        ],
    }
    print(json.dumps(compact_summary, indent=2, ensure_ascii=False))
    for r in res["runs"]:
        print(f"\n=== RAW SANDBOX OUTPUTS (seed={r['seed']}, stage=post_exec_and_debug) ===")
        for split_name in ("val", "heldout"):
            for d in r["post_exec_and_debug"][split_name]["details"]:
                print(
                    f"[{split_name}] {d['task_id']} ({d['family']}) "
                    f"passed={d['passed']} err={d['error_type']} info={d['info']!r}"
                )
                print(f"raw_output={d['raw_output']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
