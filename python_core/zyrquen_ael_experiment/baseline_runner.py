"""Fixed-policy Baseline Runner for ZYRQUEN AEL vs Baseline fair comparison.

Starts from an exact clone of the seed's random-init model, uses fixed static
hyperparameters (replay_ratio, consolidation_lambda, uniform task order, fixed lr),
and operates strictly within the shared ComputeBudget.
"""

from __future__ import annotations

import copy
import math
import random
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from v2.zyrquen_v2_pure import PureContinualTrainerV2, PureNativeTransformerLMV2  # noqa: E402
from v2.zyrquen_v2_trainer import ByteTokenizer, CodingTask, ContinualTrainerV2  # noqa: E402
from zyrquen_ael_experiment.approval_gate import AELApprovalGate  # noqa: E402
from zyrquen_ael_experiment.budget_controller import BudgetController, ComputeBudget  # noqa: E402
from zyrquen_ael_experiment.sandbox_evaluator import AELSandboxEvaluator  # noqa: E402


def _has_non_finite_pure(obj: Any) -> bool:
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(_has_non_finite_pure(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_non_finite_pure(v) for v in obj)
    return False


def _extend_context_for_stage(model: Any, stage_idx: int) -> None:
    if stage_idx == 0:
        model.extend_context(512)
    else:
        model.extend_context(768)


def run_baseline_arm_pure(
    *,
    seed: int,
    initial_model: PureNativeTransformerLMV2,
    tokenizer: ByteTokenizer,
    stage_groups: Tuple[str, ...],
    stage_train_tasks: Dict[str, List[CodingTask]],
    val_tasks: List[CodingTask],
    heldout_tasks: List[CodingTask],
    budget: ComputeBudget,
    steps_per_stage: Tuple[int, ...],
    max_new_tokens: int,
    leak_count: int,
    out_dir: Path,
    base_lr: float = 0.015,
    fixed_replay_ratio: float = 0.35,
    fixed_consolidation_lambda: float = 0.01,
) -> Dict[str, Any]:
    ckpt_dir = Path(out_dir) / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    model_clone = copy.deepcopy(initial_model)
    trainer = PureContinualTrainerV2(
        model=model_clone,
        tokenizer=tokenizer,
        lr=base_lr,
        warmup_steps=4,
        total_decay_steps=max(budget.max_training_steps + 6, 24),
        consolidation_lambda=fixed_consolidation_lambda,
        seed=seed,
    )
    budget_ctrl = BudgetController(budget, arm_name="baseline")

    def make_eval(m: PureNativeTransformerLMV2) -> AELSandboxEvaluator:
        return AELSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tokenizer, prompt, max_new_tokens=max_new_tokens
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tokenizer, texts)["loss"]),
            max_attempts=budget.max_attempts_per_task,
        )

    pre_ev = make_eval(trainer.model)
    pre_v1, pre_vf, _ = pre_ev.evaluate(
        val_tasks, round_idx=0, split="val", budget=None, count_in_budget=False
    )
    pre_h1, pre_hf, _ = pre_ev.evaluate(
        heldout_tasks, round_idx=0, split="heldout", budget=None, count_in_budget=False
    )

    checkpoints: List[Dict[str, Any]] = []
    round_logs: List[Dict[str, Any]] = []
    baseline_val_report = pre_vf

    for idx, (stg, req_steps) in enumerate(zip(stage_groups, steps_per_stage)):
        tasks = stage_train_tasks[stg]
        texts = [t.reference_solution for t in tasks]
        alloc = budget_ctrl.allocate_training_steps(req_steps)
        if alloc > 0:
            trainer.train_steps(
                texts,
                steps=alloc,
                batch_size=budget.batch_size,
                replay_ratio=0.0 if idx == 0 else fixed_replay_ratio,
            )
            budget_ctrl.record_training_steps(alloc, budget.batch_size)

        if _has_non_finite_pure(trainer.model.params):
            raise RuntimeError(f"Baseline halted: NaN/Inf detected at stage {stg}")

        trainer.snapshot_consolidation_state(texts)
        ckpt_path, ckpt_sha = trainer.save_checkpoint(ckpt_dir / f"baseline_{stg}_final.json.gz")
        checkpoints.append({"stage": stg, "path": str(ckpt_path), "sha256": ckpt_sha})

        ev = make_eval(trainer.model)
        cur_v1, cur_vf, _ = ev.evaluate(
            val_tasks,
            round_idx=idx + 1,
            split="val",
            budget=budget_ctrl,
            retry_priority=1.0,
            count_in_budget=True,
        )
        if idx == 0:
            baseline_val_report = cur_vf

        round_logs.append(
            {
                "round_idx": idx + 1,
                "stage": stg,
                "steps_executed": alloc,
                "replay_ratio": 0.0 if idx == 0 else fixed_replay_ratio,
                "consolidation_lambda": fixed_consolidation_lambda,
                "lr": base_lr,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
            }
        )

        if idx < len(stage_groups) - 1:
            trainer = PureContinualTrainerV2.load_checkpoint(
                ckpt_path,
                tokenizer=tokenizer,
                expected_sha256=ckpt_sha,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=fixed_consolidation_lambda,
            )
            _extend_context_for_stage(trainer.model, idx)

    final_ckpt = Path(checkpoints[-1]["path"])
    final_sha = str(checkpoints[-1]["sha256"])

    post_ev = make_eval(trainer.model)
    post_v1, post_vf, _ = post_ev.evaluate(
        val_tasks, round_idx=len(stage_groups) + 1, split="val", budget=None, count_in_budget=False
    )
    post_h1, post_hf, _ = post_ev.evaluate(
        heldout_tasks,
        round_idx=len(stage_groups) + 1,
        split="heldout",
        budget=None,
        count_in_budget=False,
    )
    budget_ctrl.finish()
    budget_summary = budget_ctrl.summary()

    gate = AELApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    approval = gate.verify_and_record(
        checkpoint_path=final_ckpt,
        expected_sha256=final_sha,
        baseline_heldout=pre_hf,
        candidate_heldout=post_hf,
        baseline_val=baseline_val_report,
        candidate_val=post_vf,
        leakage_count=leak_count,
        within_budget=bool(
            budget_summary["within_training_budget"] and budget_summary["within_sandbox_budget"]
        ),
        metadata={"arm": "baseline", "seed": seed, "backend": "pure_python_3.11_stdlib"},
    )

    return {
        "arm": "baseline",
        "seed": seed,
        "backend": "pure_python_3.11_stdlib",
        "global_step_final": trainer.global_step,
        "checkpoints": checkpoints,
        "final_checkpoint": {
            "path": str(final_ckpt),
            "sha256": final_sha,
            "approval_record": approval["approval_record_path"],
            "status": approval["status"],
        },
        "budget": budget_summary,
        "pre_init": {
            "val_first_pass_rate": pre_v1.exec_pass_rate,
            "val_final_pass_rate": pre_vf.exec_pass_rate,
            "heldout_first_pass_rate": pre_h1.exec_pass_rate,
            "heldout_final_pass_rate": pre_hf.exec_pass_rate,
        },
        "round_logs": round_logs,
        "post_final": {
            "val_first_pass_rate": post_v1.exec_pass_rate,
            "val_final_pass_rate": post_vf.exec_pass_rate,
            "val_loss": post_vf.avg_loss,
            "val_first_errors": post_v1.error_breakdown,
            "val_final_errors": post_vf.error_breakdown,
            "heldout_first_pass_rate": post_h1.exec_pass_rate,
            "heldout_final_pass_rate": post_hf.exec_pass_rate,
            "heldout_loss": post_hf.avg_loss,
            "heldout_first_errors": post_h1.error_breakdown,
            "heldout_final_errors": post_hf.error_breakdown,
            "heldout_details": post_hf.details,
            "gate": approval["decision"],
            "approved": bool(approval["approved"]),
            "status": approval["status"],
        },
    }


def run_baseline_arm_pytorch(
    *,
    seed: int,
    initial_model: Any,
    tokenizer: ByteTokenizer,
    stage_groups: Tuple[str, ...],
    stage_train_tasks: Dict[str, List[CodingTask]],
    val_tasks: List[CodingTask],
    heldout_tasks: List[CodingTask],
    budget: ComputeBudget,
    steps_per_stage: Tuple[int, ...],
    max_new_tokens: int,
    leak_count: int,
    out_dir: Path,
    base_lr: float = 1e-3,
    fixed_replay_ratio: float = 0.50,
    fixed_consolidation_lambda: float = 0.01,
) -> Dict[str, Any]:
    import torch

    device = next(initial_model.parameters()).device
    ckpt_dir = Path(out_dir) / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    torch.manual_seed(seed)
    model_clone = copy.deepcopy(initial_model).to(device)
    trainer = ContinualTrainerV2(
        model=model_clone,
        tokenizer=tokenizer,
        lr=base_lr,
        warmup_steps=20,
        total_decay_steps=max(budget.max_training_steps + 20, 100),
        consolidation_lambda=fixed_consolidation_lambda,
        device=device,
        seed=seed,
    )
    budget_ctrl = BudgetController(budget, arm_name="baseline")

    def make_eval(m: Any) -> AELSandboxEvaluator:
        return AELSandboxEvaluator(
            generate_fn=lambda prompt: m.generate_text(
                tokenizer, prompt, max_new_tokens=max_new_tokens, device=device
            ),
            loss_fn=lambda texts: float(m.evaluate_texts(tokenizer, texts, device=device)["loss"]),
            max_attempts=budget.max_attempts_per_task,
        )

    pre_ev = make_eval(trainer.model)
    pre_v1, pre_vf, _ = pre_ev.evaluate(
        val_tasks, round_idx=0, split="val", budget=None, count_in_budget=False
    )
    pre_h1, pre_hf, _ = pre_ev.evaluate(
        heldout_tasks, round_idx=0, split="heldout", budget=None, count_in_budget=False
    )

    checkpoints: List[Dict[str, Any]] = []
    round_logs: List[Dict[str, Any]] = []
    baseline_val_report = pre_vf

    for idx, (stg, req_steps) in enumerate(zip(stage_groups, steps_per_stage)):
        tasks = stage_train_tasks[stg]
        texts = [t.reference_solution for t in tasks]
        alloc = budget_ctrl.allocate_training_steps(req_steps)
        if alloc > 0:
            trainer.train_steps(
                texts,
                steps=alloc,
                batch_size=budget.batch_size,
                replay_ratio=0.0 if idx == 0 else fixed_replay_ratio,
            )
            budget_ctrl.record_training_steps(alloc, budget.batch_size)

        trainer.snapshot_consolidation_state(texts)
        ckpt_path, ckpt_sha = trainer.save_checkpoint(ckpt_dir / f"baseline_{stg}_final.pt")
        checkpoints.append({"stage": stg, "path": str(ckpt_path), "sha256": ckpt_sha})

        ev = make_eval(trainer.model)
        cur_v1, cur_vf, _ = ev.evaluate(
            val_tasks,
            round_idx=idx + 1,
            split="val",
            budget=budget_ctrl,
            retry_priority=1.0,
            count_in_budget=True,
        )
        if idx == 0:
            baseline_val_report = cur_vf

        round_logs.append(
            {
                "round_idx": idx + 1,
                "stage": stg,
                "steps_executed": alloc,
                "replay_ratio": 0.0 if idx == 0 else fixed_replay_ratio,
                "consolidation_lambda": fixed_consolidation_lambda,
                "lr": base_lr,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
            }
        )

        if idx < len(stage_groups) - 1:
            trainer = ContinualTrainerV2.load_checkpoint(
                ckpt_path,
                tokenizer=tokenizer,
                expected_sha256=ckpt_sha,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=fixed_consolidation_lambda,
                device=device,
            )
            _extend_context_for_stage(trainer.model, idx)

    final_ckpt = Path(checkpoints[-1]["path"])
    final_sha = str(checkpoints[-1]["sha256"])

    post_ev = make_eval(trainer.model)
    post_v1, post_vf, _ = post_ev.evaluate(
        val_tasks, round_idx=len(stage_groups) + 1, split="val", budget=None, count_in_budget=False
    )
    post_h1, post_hf, _ = post_ev.evaluate(
        heldout_tasks,
        round_idx=len(stage_groups) + 1,
        split="heldout",
        budget=None,
        count_in_budget=False,
    )
    budget_ctrl.finish()
    budget_summary = budget_ctrl.summary()

    gate = AELApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05, require_non_zero_unseen=True)
    approval = gate.verify_and_record(
        checkpoint_path=final_ckpt,
        expected_sha256=final_sha,
        baseline_heldout=pre_hf,
        candidate_heldout=post_hf,
        baseline_val=baseline_val_report,
        candidate_val=post_vf,
        leakage_count=leak_count,
        within_budget=bool(
            budget_summary["within_training_budget"] and budget_summary["within_sandbox_budget"]
        ),
        metadata={"arm": "baseline", "seed": seed, "backend": "pytorch"},
    )

    return {
        "arm": "baseline",
        "seed": seed,
        "backend": "pytorch",
        "global_step_final": trainer.global_step,
        "checkpoints": checkpoints,
        "final_checkpoint": {
            "path": str(final_ckpt),
            "sha256": final_sha,
            "approval_record": approval["approval_record_path"],
            "status": approval["status"],
        },
        "budget": budget_summary,
        "pre_init": {
            "val_first_pass_rate": pre_v1.exec_pass_rate,
            "val_final_pass_rate": pre_vf.exec_pass_rate,
            "heldout_first_pass_rate": pre_h1.exec_pass_rate,
            "heldout_final_pass_rate": pre_hf.exec_pass_rate,
        },
        "round_logs": round_logs,
        "post_final": {
            "val_first_pass_rate": post_v1.exec_pass_rate,
            "val_final_pass_rate": post_vf.exec_pass_rate,
            "val_loss": post_vf.avg_loss,
            "val_first_errors": post_v1.error_breakdown,
            "val_final_errors": post_vf.error_breakdown,
            "heldout_first_pass_rate": post_h1.exec_pass_rate,
            "heldout_final_pass_rate": post_hf.exec_pass_rate,
            "heldout_loss": post_hf.avg_loss,
            "heldout_first_errors": post_h1.error_breakdown,
            "heldout_final_errors": post_hf.error_breakdown,
            "heldout_details": post_hf.details,
            "gate": approval["decision"],
            "approved": bool(approval["approved"]),
            "status": approval["status"],
        },
    }
