"""Sandbox Evaluator for ZYRQUEN AEL Experiment.

Executes generated code and test assertions in an isolated subprocess sandbox,
tracks first-attempt vs post-self-correction outcomes, classifies errors, and
accounts every sandbox invocation (including retries) in BudgetController.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from v2.zyrquen_v2_trainer import (  # noqa: E402
    CodingTask,
    EvalReport,
    extract_first_python_function,
    run_code_in_sandbox,
)
from zyrquen_ael_experiment.budget_controller import BudgetController  # noqa: E402
from zyrquen_ael_experiment.experience_store import ERROR_TYPES, SandboxExperienceRecord  # noqa: E402


def classify_sandbox_error(passed: bool, info: str) -> str:
    if passed:
        return "passed"
    txt = str(info or "")
    if txt == "timeout":
        return "timeout"
    if "BudgetExhausted" in txt:
        return "other"
    if "IndentationError" in txt or "TabError" in txt or "SyntaxError" in txt:
        return "SyntaxError"
    for err in ("NameError", "TypeError", "AssertionError"):
        if err in txt:
            return err
    return "other"


def _error_breakdown(details: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(
        classify_sandbox_error(bool(d.get("passed")), str(d.get("info", ""))) for d in details
    )
    return {k: int(counts.get(k, 0)) for k in ERROR_TYPES}


class AELSandboxEvaluator:
    """Budget-aware sandbox evaluator supporting first-pass and self-correction metrics."""

    def __init__(
        self,
        generate_fn: Callable[[str], str],
        loss_fn: Callable[[List[str]], Optional[float]],
        *,
        max_attempts: int = 2,
        timeout_sec: float = 2.0,
    ) -> None:
        self.generate_fn = generate_fn
        self.loss_fn = loss_fn
        self.max_attempts = max(1, int(max_attempts))
        self.timeout_sec = float(timeout_sec)

    def evaluate(
        self,
        tasks: List[CodingTask],
        *,
        round_idx: int,
        split: str,
        budget: Optional[BudgetController] = None,
        retry_priority: float = 1.0,
        count_in_budget: bool = True,
    ) -> Tuple[EvalReport, EvalReport, List[SandboxExperienceRecord]]:
        if not tasks:
            empty = EvalReport(
                avg_loss=None,
                exec_pass_rate=0.0,
                passed_count=0,
                total_count=0,
                details=[],
                error_breakdown={k: 0 for k in ERROR_TYPES},
            )
            return empty, empty, []

        loss_texts = [t.reference_solution if t.reference_solution else t.prompt for t in tasks]
        avg_loss = self.loss_fn(loss_texts)

        first_passed = 0
        final_passed = 0
        first_details: List[Dict[str, Any]] = []
        final_details: List[Dict[str, Any]] = []
        records: List[SandboxExperienceRecord] = []

        for task in tasks:
            if count_in_budget and budget is not None:
                allowed_first = budget.try_consume_sandbox_run(is_retry=False)
            else:
                allowed_first = True

            if not allowed_first:
                raw_1 = ""
                extracted_1 = ""
                ok_1, info_1 = False, "BudgetExhausted: max_sandbox_runs reached"
            else:
                raw_1 = self.generate_fn(task.prompt)
                extracted_1 = extract_first_python_function(raw_1)
                ok_1, info_1 = run_code_in_sandbox(
                    raw_1, task.test_code, timeout_sec=self.timeout_sec
                )

            err_1 = classify_sandbox_error(ok_1, info_1)
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
            retries_used = 0
            prompt_lines = task.prompt.splitlines()
            last_line = prompt_lines[-1] if prompt_lines else ""

            while (not cur_ok) and (cur_attempt < self.max_attempts):
                if float(retry_priority) <= 0.15:
                    if count_in_budget and budget is not None:
                        budget.record_skipped_retry()
                    break
                if count_in_budget and budget is not None and not budget.try_consume_sandbox_run(is_retry=True):
                    budget.record_skipped_retry()
                    break

                cur_attempt += 1
                retries_used += 1
                repair_prompt = (
                    f"{task.prompt.rstrip()}\n"
                    f"# Fix [{cur_err}]: {cur_info} -> Self-Correction attempt {cur_attempt}\n"
                    f"{last_line} "
                )
                cur_raw = self.generate_fn(repair_prompt)
                cur_extracted = extract_first_python_function(cur_raw)
                cur_ok, cur_info = run_code_in_sandbox(
                    cur_raw, task.test_code, timeout_sec=self.timeout_sec
                )
                cur_err = classify_sandbox_error(cur_ok, cur_info)

            if cur_ok:
                final_passed += 1

            recovered = bool((not ok_1) and cur_ok)
            final_details.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "attempts_used": cur_attempt,
                    "retries_used": retries_used,
                    "first_attempt_passed": ok_1,
                    "recovered_on_retry": recovered,
                    "passed": cur_ok,
                    "error_type": cur_err,
                    "info": cur_info,
                    "raw_output": cur_raw,
                    "extracted_code": cur_extracted,
                }
            )
            records.append(
                SandboxExperienceRecord(
                    round_idx=int(round_idx),
                    split=split,
                    task_id=task.task_id,
                    task_family=task.family,
                    first_attempt_passed=ok_1,
                    passed=cur_ok,
                    recovered_on_retry=recovered,
                    attempts_used=cur_attempt,
                    retries_used=retries_used,
                    first_error_type=err_1,
                    final_error_type=cur_err,
                    info=cur_info,
                    raw_output=cur_raw,
                )
            )

        rounded_loss = round(avg_loss, 4) if avg_loss is not None else None
        first_rep = EvalReport(
            avg_loss=rounded_loss,
            exec_pass_rate=round(first_passed / len(tasks), 4),
            passed_count=first_passed,
            total_count=len(tasks),
            details=first_details,
            error_breakdown=_error_breakdown(first_details),
        )
        final_rep = EvalReport(
            avg_loss=rounded_loss,
            exec_pass_rate=round(final_passed / len(tasks), 4),
            passed_count=final_passed,
            total_count=len(tasks),
            details=final_details,
            error_breakdown=_error_breakdown(final_details),
        )
        return first_rep, final_rep, records
