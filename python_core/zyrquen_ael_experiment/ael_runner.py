"""Adaptive Experience-driven Learning (AEL) Runner for ZYRQUEN Experiment.

Starts from an exact clone of the same random-init model as Baseline, executes
under identical ComputeBudget, inspects ONLY train/validation sandbox outcomes
(never held-out!), adapts replay_ratio, consolidation_lambda, task_priority,
retry_priority, and learning_rate_scale via AdaptiveLearningController, and
logs every before -> after transition + reason_code + evidence.
"""

from __future__ import annotations

import copy
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from v2.zyrquen_v2_pure import PureContinualTrainerV2, PureNativeTransformerLMV2  # noqa: E402
from v2.zyrquen_v2_trainer import ByteTokenizer, CodingTask, ContinualTrainerV2  # noqa: E402
from zyrquen_ael_experiment.ael_controller import AdaptiveLearningController  # noqa: E402
from zyrquen_ael_experiment.approval_gate import AELApprovalGate  # noqa: E402
from zyrquen_ael_experiment.budget_controller import BudgetController, ComputeBudget  # noqa: E402
from zyrquen_ael_experiment.experience_analyzer import ExperienceAnalyzer  # noqa: E402
from zyrquen_ael_experiment.experience_store import ExperienceStore  # noqa: E402
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


def _build_prioritized_texts(
    tasks: List[CodingTask],
    task_priority: Dict[str, float],
) -> List[str]:
    """Expand stage training texts proportionally to task_priority while keeping all tasks represented."""
    if not tasks:
        return []
    out: List[str] = []
    n_fams = max(len({t.family for t in tasks}), 1)
    baseline_share = 1.0 / n_fams
    for t in tasks:
        w = float(task_priority.get(t.family, baseline_share))
        # Repeat count 1..3 purely ordering/weighting existing train texts
        reps = 1
        if w >= baseline_share * 1.45:
            reps = 3
        elif w >= baseline_share * 1.15:
            reps = 2
        for _ in range(reps):
            out.append(t.reference_solution)
    return out


def _select_train_probe_tasks(
    tasks: List[CodingTask],
    max_probe: int = 4,
) -> List[CodingTask]:
    """Select one representative task per family (up to max_probe) to measure train signals within budget."""
    seen_fams: set[str] = set()
    selected: List[CodingTask] = []
    for t in tasks:
        if t.family not in seen_fams:
            seen_fams.add(t.family)
            selected.append(t)
        if len(selected) >= max_probe:
            break
    return selected


def run_ael_arm_pure(
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
    probe_train_per_stage: int = 2,
) -> Dict[str, Any]:
    out_path = Path(out_dir)
    ckpt_dir = out_path / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    all_families = sorted(
        {t.family for tasks in stage_train_tasks.values() for t in tasks}
        | {t.family for t in val_tasks}
    )

    random.seed(seed)
    model_clone = copy.deepcopy(initial_model)
    controller = AdaptiveLearningController(all_families)
    analyzer = ExperienceAnalyzer()
    store = ExperienceStore(persist_path=out_path / "experience_store.json")
    budget_ctrl = BudgetController(budget, arm_name="ael")

    trainer = PureContinualTrainerV2(
        model=model_clone,
        tokenizer=tokenizer,
        lr=base_lr * controller.state.learning_rate_scale,
        warmup_steps=4,
        total_decay_steps=max(budget.max_training_steps + 6, 24),
        consolidation_lambda=controller.state.consolidation_lambda,
        seed=seed,
    )

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
        prioritized_texts = _build_prioritized_texts(tasks, controller.state.task_priority)

        # Apply current AEL control parameters strictly within ComputeBudget
        trainer.lr = base_lr * controller.state.learning_rate_scale
        trainer.consolidation_lambda = controller.state.consolidation_lambda
        eff_replay = 0.0 if idx == 0 else controller.state.replay_ratio

        alloc = budget_ctrl.allocate_training_steps(req_steps)
        if alloc > 0:
            trainer.train_steps(
                prioritized_texts,
                steps=alloc,
                batch_size=budget.batch_size,
                replay_ratio=eff_replay,
            )
            budget_ctrl.record_training_steps(alloc, budget.batch_size)

        if _has_non_finite_pure(trainer.model.params):
            raise RuntimeError(f"AEL halted: NaN/Inf detected at stage {stg}")

        trainer.snapshot_consolidation_state([t.reference_solution for t in tasks])
        ckpt_path, ckpt_sha = trainer.save_checkpoint(ckpt_dir / f"ael_{stg}_final.json.gz")
        checkpoints.append({"stage": stg, "path": str(ckpt_path), "sha256": ckpt_sha})

        # Evaluate ONLY train probe + validation inside sandbox (HELD-OUT IS FORBIDDEN HERE)
        ev = make_eval(trainer.model)
        round_num = idx + 1
        train_probe = _select_train_probe_tasks(tasks, max_probe=probe_train_per_stage)
        _, _, train_recs = ev.evaluate(
            train_probe,
            round_idx=round_num,
            split="train",
            budget=budget_ctrl,
            retry_priority=controller.state.retry_priority,
            count_in_budget=True,
        )
        cur_v1, cur_vf, val_recs = ev.evaluate(
            val_tasks,
            round_idx=round_num,
            split="val",
            budget=budget_ctrl,
            retry_priority=controller.state.retry_priority,
            count_in_budget=True,
        )
        if idx == 0:
            baseline_val_report = cur_vf

        store.add_round_records(round_num, train_recs + val_recs)
        analysis = analyzer.analyze(store, round_idx=round_num)
        adjustments = controller.update(analysis)

        round_logs.append(
            {
                "round_idx": round_num,
                "stage": stg,
                "steps_executed": alloc,
                "applied_replay_ratio": eff_replay,
                "applied_consolidation_lambda": trainer.consolidation_lambda,
                "applied_lr": round(trainer.lr, 6),
                "applied_retry_priority": controller.state.retry_priority,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
                "experience_analysis": analysis.to_dict(),
                "controller_adjustments": [a.to_dict() for a in adjustments],
                "control_state_after": controller.state.to_dict(),
            }
        )

        if idx < len(stage_groups) - 1:
            trainer = PureContinualTrainerV2.load_checkpoint(
                ckpt_path,
                tokenizer=tokenizer,
                expected_sha256=ckpt_sha,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=controller.state.consolidation_lambda,
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
        metadata={"arm": "ael", "seed": seed, "backend": "pure_python_3.11_stdlib"},
    )

    return {
        "arm": "ael",
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
        "controller_history": [a.to_dict() for a in controller.history],
        "experience_store_path": str(store.persist_path),
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


def run_ael_arm_pytorch(
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
    probe_train_per_stage: int = 4,
) -> Dict[str, Any]:
    import torch

    device = next(initial_model.parameters()).device
    out_path = Path(out_dir)
    ckpt_dir = out_path / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    all_families = sorted(
        {t.family for tasks in stage_train_tasks.values() for t in tasks}
        | {t.family for t in val_tasks}
    )

    random.seed(seed)
    torch.manual_seed(seed)
    model_clone = copy.deepcopy(initial_model).to(device)
    controller = AdaptiveLearningController(all_families)
    analyzer = ExperienceAnalyzer()
    store = ExperienceStore(persist_path=out_path / "experience_store.json")
    budget_ctrl = BudgetController(budget, arm_name="ael")

    trainer = ContinualTrainerV2(
        model=model_clone,
        tokenizer=tokenizer,
        lr=base_lr * controller.state.learning_rate_scale,
        warmup_steps=20,
        total_decay_steps=max(budget.max_training_steps + 20, 100),
        consolidation_lambda=controller.state.consolidation_lambda,
        device=device,
        seed=seed,
    )

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
        prioritized_texts = _build_prioritized_texts(tasks, controller.state.task_priority)

        trainer.base_lr = base_lr * controller.state.learning_rate_scale
        trainer.consolidation_lambda = controller.state.consolidation_lambda
        eff_replay = 0.0 if idx == 0 else controller.state.replay_ratio

        alloc = budget_ctrl.allocate_training_steps(req_steps)
        if alloc > 0:
            trainer.train_steps(
                prioritized_texts,
                steps=alloc,
                batch_size=budget.batch_size,
                replay_ratio=eff_replay,
            )
            budget_ctrl.record_training_steps(alloc, budget.batch_size)

        trainer.snapshot_consolidation_state([t.reference_solution for t in tasks])
        ckpt_path, ckpt_sha = trainer.save_checkpoint(ckpt_dir / f"ael_{stg}_final.pt")
        checkpoints.append({"stage": stg, "path": str(ckpt_path), "sha256": ckpt_sha})

        ev = make_eval(trainer.model)
        round_num = idx + 1
        train_probe = _select_train_probe_tasks(tasks, max_probe=probe_train_per_stage)
        _, _, train_recs = ev.evaluate(
            train_probe,
            round_idx=round_num,
            split="train",
            budget=budget_ctrl,
            retry_priority=controller.state.retry_priority,
            count_in_budget=True,
        )
        cur_v1, cur_vf, val_recs = ev.evaluate(
            val_tasks,
            round_idx=round_num,
            split="val",
            budget=budget_ctrl,
            retry_priority=controller.state.retry_priority,
            count_in_budget=True,
        )
        if idx == 0:
            baseline_val_report = cur_vf

        store.add_round_records(round_num, train_recs + val_recs)
        analysis = analyzer.analyze(store, round_idx=round_num)
        adjustments = controller.update(analysis)

        round_logs.append(
            {
                "round_idx": round_num,
                "stage": stg,
                "steps_executed": alloc,
                "applied_replay_ratio": eff_replay,
                "applied_consolidation_lambda": trainer.consolidation_lambda,
                "applied_lr": round(base_lr * controller.state.learning_rate_scale, 8),
                "applied_retry_priority": controller.state.retry_priority,
                "val_first_pass_rate": cur_v1.exec_pass_rate,
                "val_final_pass_rate": cur_vf.exec_pass_rate,
                "val_loss": cur_vf.avg_loss,
                "experience_analysis": analysis.to_dict(),
                "controller_adjustments": [a.to_dict() for a in adjustments],
                "control_state_after": controller.state.to_dict(),
            }
        )

        if idx < len(stage_groups) - 1:
            trainer = ContinualTrainerV2.load_checkpoint(
                ckpt_path,
                tokenizer=tokenizer,
                expected_sha256=ckpt_sha,
                resume_optimizer=True,
                restore_continual_state=True,
                consolidation_lambda=controller.state.consolidation_lambda,
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
        metadata={"arm": "ael", "seed": seed, "backend": "pytorch"},
    )

    return {
        "arm": "ael",
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
        "controller_history": [a.to_dict() for a in controller.history],
        "experience_store_path": str(store.persist_path),
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
