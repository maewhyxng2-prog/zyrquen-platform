#!/usr/bin/env python3
"""Load Step 6000 candidate and Step 5000 baseline in a fresh runtime, verify
SHA-256 digests and embedded states, run held-out transfer-validation evaluation,
and print a side-by-side metric comparison.

Policy:
- Native PureNativeTransformerLMV2 / PureContinualTrainerV2 only.
- Never fabricates metrics if the held-out validation dataset is missing.
- Keeps Step 6000 as CANDIDATE — NOT PROMOTED; emits an evidence report only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_CORE = REPO_ROOT / "python_core"
for p in (str(PYTHON_CORE), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.resume_v2_lab import (  # noqa: E402
    DEFAULT_OUT_DIR,
    KNOWN_CHECKPOINT_SHA256,
    load_texts_from_file,
    verify_and_reload,
)

STEP5000_FILENAME = "v2_teacher_transfer_step5000.json.gz"
STEP6000_FILENAME = "v2_teacher_transfer_run5000_step6000.json.gz"


def compare_step6000_vs_step5000(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    val_texts: List[str],
    baseline_path: Optional[Path] = None,
    candidate_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not val_texts:
        raise ValueError(
            "Held-out transfer-validation dataset is required (cannot fabricate metrics)."
        )

    base_ckpt = baseline_path or (out_dir / STEP5000_FILENAME)
    cand_ckpt = candidate_path or (out_dir / STEP6000_FILENAME)

    base_info = verify_and_reload(
        base_ckpt, expected_sha256=KNOWN_CHECKPOINT_SHA256.get(base_ckpt.name)
    )
    cand_info = verify_and_reload(
        cand_ckpt, expected_sha256=KNOWN_CHECKPOINT_SHA256.get(cand_ckpt.name)
    )

    base_metrics = base_info["trainer"].model.evaluate_texts(
        base_info["tokenizer"], val_texts
    )
    cand_metrics = cand_info["trainer"].model.evaluate_texts(
        cand_info["tokenizer"], val_texts
    )

    delta_loss = round(float(cand_metrics["loss"]) - float(base_metrics["loss"]), 4)
    delta_ppl = round(
        float(cand_metrics["perplexity"]) - float(base_metrics["perplexity"]), 3
    )
    delta_acc = round(
        float(cand_metrics["accuracy"]) - float(base_metrics["accuracy"]), 4
    )

    zero_regression = (
        float(cand_metrics["loss"]) <= float(base_metrics["loss"])
        and float(cand_metrics["accuracy"]) >= float(base_metrics["accuracy"])
    )

    return {
        "schema": "zyrquen.v2.step6000_eval_comparison.v1",
        "validation_examples": len(val_texts),
        "baseline": {
            "file": base_ckpt.name,
            "sha256": base_info["sha256"],
            "global_step": base_info["global_step"],
            "replay_buffer_len": base_info["replay_buffer_len"],
            "metrics": base_metrics,
        },
        "candidate": {
            "file": cand_ckpt.name,
            "sha256": cand_info["sha256"],
            "global_step": cand_info["global_step"],
            "replay_buffer_len": cand_info["replay_buffer_len"],
            "metrics": cand_metrics,
        },
        "delta": {
            "loss": delta_loss,
            "perplexity": delta_ppl,
            "accuracy": delta_acc,
        },
        "zero_regression_on_transfer_val": zero_regression,
        "promotion_note": (
            "Transfer-validation check passed; still require independent held-out & task-level regression checks before promotion."
            if zero_regression
            else "Candidate did not improve or regressed on transfer-validation; keep as CANDIDATE — NOT PROMOTED."
        ),
    }


def print_comparison_table(report: Dict[str, Any]) -> None:
    b = report["baseline"]
    c = report["candidate"]
    d = report["delta"]
    bm = b["metrics"]
    cm = c["metrics"]

    print("=== ZYRQUEN V2 Held-Out Transfer-Validation Comparison ===")
    print(f"Examples   : {report['validation_examples']}")
    print(f"Baseline   : {b['file']} (step={b['global_step']}, sha256={b['sha256'][:12]}...)")
    print(f"Candidate  : {c['file']} (step={c['global_step']}, sha256={c['sha256'][:12]}...)")
    print("-" * 64)
    print(f"{'Metric':<16} {'Step 5000':>14} {'Step 6000':>14} {'Delta':>14}")
    print("-" * 64)
    print(f"{'loss':<16} {bm['loss']:>14.4f} {cm['loss']:>14.4f} {d['loss']:>+14.4f}")
    print(
        f"{'perplexity':<16} {bm['perplexity']:>14.3f} {cm['perplexity']:>14.3f} {d['perplexity']:>+14.3f}"
    )
    print(
        f"{'accuracy':<16} {bm['accuracy']:>14.4f} {cm['accuracy']:>14.4f} {d['accuracy']:>+14.4f}"
    )
    print(f"{'tokens':<16} {bm['tokens']:>14d} {cm['tokens']:>14d} {cm['tokens'] - bm['tokens']:>+14d}")
    print("-" * 64)
    print(f"Zero-regression on transfer-val: {report['zero_regression_on_transfer_val']}")
    print(f"Note: {report['promotion_note']}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare Step 6000 candidate against Step 5000 baseline on held-out transfer-validation data."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--val-file", type=Path, required=True, help="Held-out validation JSON/JSONL/JSON.GZ file")
    parser.add_argument("--val-split", type=str, default=None, help="Optional split key when --val-file is a JSON dict")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--candidate", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args(argv)

    val_texts = load_texts_from_file(args.val_file, split=args.val_split)
    report = compare_step6000_vs_step5000(
        out_dir=args.out_dir,
        val_texts=val_texts,
        baseline_path=args.baseline,
        candidate_path=args.candidate,
    )
    print_comparison_table(report)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Saved JSON report to: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
