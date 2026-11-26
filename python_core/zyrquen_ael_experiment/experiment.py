"""Orchestrator for ZYRQUEN Adaptive Experience-driven Learning (AEL) vs Baseline Experiment.

Enforces:
- Does NOT modify NativeTransformerLM, build_ablation_datasets(), or original checkpoints
- Clones identical initial random weights per seed into isolated Baseline and AEL arms
- Enforces identical ComputeBudget across both arms (steps, batch_size, sandbox runs)
- Strict held-out isolation (AEL never reads held-out to adapt)
- Honest multi-seed reporting including seeds where AEL ties or loses to Baseline
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from v2.run_v2_full_general_skills import (  # noqa: E402
    STAGE_ORDER,
    build_rich_10_skill_corpus,
    verify_full_general_skills_leakage,
)
from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config  # noqa: E402
from v2.zyrquen_v2_pure import PureNativeTransformerLMV2, PureZyrquenV2Config  # noqa: E402
from v2.zyrquen_v2_trainer import ByteTokenizer, CodingTask  # noqa: E402
from zyrquen_ael_experiment.ael_runner import run_ael_arm_pure, run_ael_arm_pytorch  # noqa: E402
from zyrquen_ael_experiment.baseline_runner import (  # noqa: E402
    run_baseline_arm_pure,
    run_baseline_arm_pytorch,
)
from zyrquen_ael_experiment.budget_controller import ComputeBudget  # noqa: E402

DEFAULT_SEEDS: Tuple[int, ...] = (42, 1337, 2026)


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
                "STATUS: BLOCKED — --backend pytorch requested but 'torch' is not installed."
            )
        return "pytorch", True
    if requested == "auto" and has_torch:
        return "pytorch", True
    return "pure", has_torch


def _build_experiment_splits() -> (
    Tuple[Dict[str, List[CodingTask]], List[CodingTask], List[CodingTask], int]
):
    train_items, val_items, heldout_items = build_rich_10_skill_corpus()
    leaks = verify_full_general_skills_leakage(train_items, val_items, heldout_items)
    if leaks:
        raise RuntimeError(f"BLOCKED: leakage detected in AEL splits: {leaks}")

    stage_train: Dict[str, List[CodingTask]] = {stg: [] for stg in STAGE_ORDER}
    for ex in train_items:
        stage_train[ex.stage_group].append(
            CodingTask(
                task_id=ex.task_id,
                family=ex.family,
                prompt=ex.prompt,
                test_code=ex.test_code,
                reference_solution=ex.full_text,
                category="train",
            )
        )

    val_tasks = [
        CodingTask(
            task_id=ex.task_id,
            family=ex.family,
            prompt=ex.prompt,
            test_code=ex.test_code,
            reference_solution=ex.full_text,
            category="validation",
        )
        for ex in val_items
    ]
    heldout_tasks = [
        CodingTask(
            task_id=ex.task_id,
            family=ex.family,
            prompt=ex.prompt,
            test_code=ex.test_code,
            reference_solution=ex.full_text,
            category="unseen",
        )
        for ex in heldout_items
    ]
    return stage_train, val_tasks, heldout_tasks, len(leaks)


def _compare_seed_arms(baseline: Dict[str, Any], ael: Dict[str, Any]) -> Dict[str, Any]:
    b_post = baseline["post_final"]
    a_post = ael["post_final"]
    delta_first = round(
        float(a_post["heldout_first_pass_rate"]) - float(b_post["heldout_first_pass_rate"]), 4
    )
    delta_final = round(
        float(a_post["heldout_final_pass_rate"]) - float(b_post["heldout_final_pass_rate"]), 4
    )
    delta_val_final = round(
        float(a_post["val_final_pass_rate"]) - float(b_post["val_final_pass_rate"]), 4
    )

    if delta_final > 0:
        outcome = "AEL_WON"
    elif delta_final < 0:
        outcome = "AEL_LOST_TO_BASELINE"
    elif delta_val_final > 0:
        outcome = "TIE_HELDOUT_AEL_HIGHER_VAL"
    elif delta_val_final < 0:
        outcome = "TIE_HELDOUT_BASELINE_HIGHER_VAL"
    else:
        outcome = "TIE"

    return {
        "seed": baseline["seed"],
        "outcome": outcome,
        "baseline_heldout_first_pass": b_post["heldout_first_pass_rate"],
        "ael_heldout_first_pass": a_post["heldout_first_pass_rate"],
        "delta_heldout_first_pass": delta_first,
        "baseline_heldout_final_pass": b_post["heldout_final_pass_rate"],
        "ael_heldout_final_pass": a_post["heldout_final_pass_rate"],
        "delta_heldout_final_pass": delta_final,
        "baseline_val_final_pass": b_post["val_final_pass_rate"],
        "ael_val_final_pass": a_post["val_final_pass_rate"],
        "delta_val_final_pass": delta_val_final,
        "baseline_approved": bool(b_post["approved"]),
        "ael_approved": bool(a_post["approved"]),
        "baseline_training_steps": baseline["budget"]["training_steps_used"],
        "ael_training_steps": ael["budget"]["training_steps_used"],
        "baseline_sandbox_runs": baseline["budget"]["sandbox_runs_used"],
        "ael_sandbox_runs": ael["budget"]["sandbox_runs_used"],
    }


def _render_markdown_report(summary: Dict[str, Any]) -> str:
    lines = [
        "# ZYRQUEN AEL vs Baseline Experiment Report",
        "",
        f"- Backend: `{summary['backend']}`",
        f"- External AI models used: `{summary['external_models_used']}`",
        f"- Data leakage count: `{summary['leakage_count']}`",
        f"- Budget: `steps={summary['budget']['max_training_steps']}`, `batch_size={summary['budget']['batch_size']}`, `max_sandbox_runs={summary['budget']['max_sandbox_runs']}`",
        "",
        "## Per-Seed Honest Comparison (All Seeds)",
        "",
        "| Seed | Outcome | Baseline Held-out (1st -> Final) | AEL Held-out (1st -> Final) | Delta Final | Baseline Gate | AEL Gate | Sandbox Runs (B vs A) |",
        "|---:|---|---|---|---:|---|---|---|",
    ]
    for c in summary["comparisons"]:
        lines.append(
            f"| {c['seed']} | {c['outcome']} | "
            f"{c['baseline_heldout_first_pass']:.2%} -> {c['baseline_heldout_final_pass']:.2%} | "
            f"{c['ael_heldout_first_pass']:.2%} -> {c['ael_heldout_final_pass']:.2%} | "
            f"{c['delta_heldout_final_pass']:+.4f} | "
            f"{'APPROVED' if c['baseline_approved'] else 'REJECTED'} | "
            f"{'APPROVED' if c['ael_approved'] else 'REJECTED'} | "
            f"{c['baseline_sandbox_runs']} vs {c['ael_sandbox_runs']} |"
        )
    lines.append("")
    lines.append(
        f"- Summary counts: `ael_won={summary['aggregate']['ael_won']}`, "
        f"`ael_lost={summary['aggregate']['ael_lost']}`, "
        f"`tie={summary['aggregate']['tie']}`"
    )
    return "\n".join(lines) + "\n"


def run_ael_experiment(
    *,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    backend: str = "auto",
    steps_per_stage: Tuple[int, int, int] = (300, 300, 300),
    pure_steps_per_stage: Tuple[int, int, int] = (6, 6, 6),
    batch_size: int = 2,
    max_attempts_per_task: int = 2,
    max_sandbox_runs: Optional[int] = None,
    pure_max_new_tokens: int = 20,
    pytorch_max_new_tokens: int = 96,
    reports_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    resolved_backend, torch_available = _resolve_backend(backend)
    use_pytorch = resolved_backend == "pytorch"

    eff_steps: Tuple[int, int, int] = (
        steps_per_stage
        if use_pytorch
        else (
            min(steps_per_stage[0], pure_steps_per_stage[0]),
            min(steps_per_stage[1], pure_steps_per_stage[1]),
            min(steps_per_stage[2], pure_steps_per_stage[2]),
        )
    )
    total_steps = sum(eff_steps)
    stage_train, val_tasks, heldout_tasks, leak_count = _build_experiment_splits()

    probe_per_stage = 4 if use_pytorch else 2
    default_sandbox_budget = len(STAGE_ORDER) * (len(val_tasks) + probe_per_stage) * max_attempts_per_task
    eff_sandbox_budget = (
        int(max_sandbox_runs) if max_sandbox_runs is not None else default_sandbox_budget
    )
    budget = ComputeBudget(
        max_training_steps=total_steps,
        batch_size=int(batch_size),
        max_sandbox_runs=eff_sandbox_budget,
        max_attempts_per_task=int(max_attempts_per_task),
    )

    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    base_reports = (
        Path(reports_dir)
        if reports_dir is not None
        else Path(__file__).resolve().parent / "reports"
    )
    run_root = base_reports / f"ael_run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    tok = ByteTokenizer()
    t0 = time.time()
    seed_results: List[Dict[str, Any]] = []
    comparisons: List[Dict[str, Any]] = []

    for seed in seeds:
        s_int = int(seed)
        seed_dir = run_root / f"seed_{s_int}"
        if use_pytorch:
            import torch

            torch.manual_seed(s_int)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            cfg = ZyrquenV2Config(
                vocab_size=tok.vocab_size,
                d_model=128,
                n_heads=4,
                n_layers=4,
                d_ff=384,
                base_seq_len=256,
                max_seq_len=256,
            )
            init_model = NativeTransformerLMV2(cfg).to(device)
            base_res = run_baseline_arm_pytorch(
                seed=s_int,
                initial_model=init_model,
                tokenizer=tok,
                stage_groups=STAGE_ORDER,
                stage_train_tasks=stage_train,
                val_tasks=val_tasks,
                heldout_tasks=heldout_tasks,
                budget=budget,
                steps_per_stage=eff_steps,
                max_new_tokens=pytorch_max_new_tokens,
                leak_count=leak_count,
                out_dir=seed_dir / "baseline",
            )
            ael_res = run_ael_arm_pytorch(
                seed=s_int,
                initial_model=init_model,
                tokenizer=tok,
                stage_groups=STAGE_ORDER,
                stage_train_tasks=stage_train,
                val_tasks=val_tasks,
                heldout_tasks=heldout_tasks,
                budget=budget,
                steps_per_stage=eff_steps,
                max_new_tokens=pytorch_max_new_tokens,
                leak_count=leak_count,
                out_dir=seed_dir / "ael",
                probe_train_per_stage=probe_per_stage,
            )
        else:
            cfg_p = PureZyrquenV2Config(
                vocab_size=tok.vocab_size,
                d_model=16,
                n_heads=2,
                n_layers=1,
                d_ff=32,
                base_seq_len=256,
                max_seq_len=256,
                seed=s_int,
            )
            init_model_p = PureNativeTransformerLMV2(cfg_p)
            base_res = run_baseline_arm_pure(
                seed=s_int,
                initial_model=init_model_p,
                tokenizer=tok,
                stage_groups=STAGE_ORDER,
                stage_train_tasks=stage_train,
                val_tasks=val_tasks,
                heldout_tasks=heldout_tasks,
                budget=budget,
                steps_per_stage=eff_steps,
                max_new_tokens=pure_max_new_tokens,
                leak_count=leak_count,
                out_dir=seed_dir / "baseline",
            )
            ael_res = run_ael_arm_pure(
                seed=s_int,
                initial_model=init_model_p,
                tokenizer=tok,
                stage_groups=STAGE_ORDER,
                stage_train_tasks=stage_train,
                val_tasks=val_tasks,
                heldout_tasks=heldout_tasks,
                budget=budget,
                steps_per_stage=eff_steps,
                max_new_tokens=pure_max_new_tokens,
                leak_count=leak_count,
                out_dir=seed_dir / "ael",
                probe_train_per_stage=probe_per_stage,
            )

        cmp_row = _compare_seed_arms(base_res, ael_res)
        comparisons.append(cmp_row)
        seed_results.append({"seed": s_int, "baseline": base_res, "ael": ael_res, "comparison": cmp_row})

    won = sum(1 for c in comparisons if c["outcome"] == "AEL_WON")
    lost = sum(1 for c in comparisons if c["outcome"] == "AEL_LOST_TO_BASELINE")
    tie = len(comparisons) - won - lost

    summary: Dict[str, Any] = {
        "experiment": "zyrquen_ael_vs_baseline",
        "backend": "pytorch" if use_pytorch else "pure_python_3.11_stdlib",
        "torch_available": torch_available,
        "external_models_used": False,
        "init_mode": "cloned_random_initialization_per_seed",
        "leakage_count": leak_count,
        "elapsed_sec": round(time.time() - t0, 3),
        "budget": {
            "max_training_steps": budget.max_training_steps,
            "batch_size": budget.batch_size,
            "max_sandbox_runs": budget.max_sandbox_runs,
            "max_attempts_per_task": budget.max_attempts_per_task,
        },
        "aggregate": {
            "total_seeds": len(comparisons),
            "ael_won": won,
            "ael_lost": lost,
            "tie": tie,
            "mean_baseline_heldout_final": round(
                sum(c["baseline_heldout_final_pass"] for c in comparisons) / max(len(comparisons), 1), 4
            ),
            "mean_ael_heldout_final": round(
                sum(c["ael_heldout_final_pass"] for c in comparisons) / max(len(comparisons), 1), 4
            ),
        },
        "comparisons": comparisons,
        "seed_results": seed_results,
    }

    json_path = run_root / "ael_experiment_report.json"
    md_path = run_root / "ael_experiment_report.md"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_markdown_report(summary), encoding="utf-8")
    summary["report_json_path"] = str(json_path)
    summary["report_md_path"] = str(md_path)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run ZYRQUEN AEL vs Baseline Experiment")
    parser.add_argument("--backend", choices=["auto", "pytorch", "pure"], default="auto")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--pure-steps", type=int, nargs=3, default=[6, 6, 6])
    parser.add_argument("--steps", type=int, nargs=3, default=[300, 300, 300])
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--max-sandbox-runs", type=int, default=None)
    parser.add_argument("--pure-max-new-tokens", type=int, default=20)
    parser.add_argument("--reports-dir", type=str, default=None)
    args = parser.parse_args(argv)

    res = run_ael_experiment(
        seeds=tuple(args.seeds),
        backend=args.backend,
        steps_per_stage=tuple(args.steps),
        pure_steps_per_stage=tuple(args.pure_steps),
        batch_size=args.batch_size,
        max_attempts_per_task=args.max_attempts,
        max_sandbox_runs=args.max_sandbox_runs,
        pure_max_new_tokens=args.pure_max_new_tokens,
        reports_dir=args.reports_dir,
    )
    print(json.dumps(
        {
            "experiment": res["experiment"],
            "backend": res["backend"],
            "leakage_count": res["leakage_count"],
            "aggregate": res["aggregate"],
            "comparisons": res["comparisons"],
            "report_json_path": res["report_json_path"],
            "report_md_path": res["report_md_path"],
        },
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
