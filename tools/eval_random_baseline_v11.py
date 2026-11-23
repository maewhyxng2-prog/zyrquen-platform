#!/usr/bin/env python3
"""
ZYRQUEN Native Model v11 — Untrained Random-Weights Guessing Floor Evaluator

Runs real native `ZyrquenModel` evaluation using newly initialized random
weights (`seed=1337` default, zero external pretrained weights/APIs) paired with
the verified native `data/nagi_v11/tokenizer.json`, and saves the Guessing Floor
baseline report atomically to `artifacts/baselines/random_init_baseline.json`.

Safety:
  - Never fabricates metrics or scores when PyTorch is unavailable (exits 3 / BLOCKED).
  - Never mutates ModelRegistry or V7-V10 historical artifacts.
  - Verifies dataset SHA-256 + <=5% cross-split n-gram leakage audit before running.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import eval_nagi_v11  # noqa: E402

DEFAULT_BASELINE_PATH = PROJECT_ROOT / "artifacts" / "baselines" / "random_init_baseline.json"
DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v11"
DEFAULT_TOKENIZER_PATH = DEFAULT_DATASET_DIR / "tokenizer.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate untrained random-weights ZyrquenModel with native tokenizer and save Guessing Floor to artifacts/baselines/random_init_baseline.json."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--tokenizer-path", type=Path, default=DEFAULT_TOKENIZER_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--max-seq-len", type=int, default=256)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--include-train-diagnostic", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    argv = [
        "eval_nagi_v11.py",
        "--dataset-dir",
        str(args.dataset_dir),
        "--tokenizer-path",
        str(args.tokenizer_path),
        "--output-file",
        str(args.output),
        "--random-init",
        "--experiment-id",
        "p11-random-init-guessing-floor",
        "--seed",
        str(args.seed),
        "--max-seq-len",
        str(args.max_seq_len),
        "--max-new-tokens",
        str(args.max_new_tokens),
    ]
    if args.max_examples is not None:
        argv.extend(["--max-examples", str(args.max_examples)])
    if args.include_train_diagnostic:
        argv.append("--include-train-diagnostic")
    if args.overwrite:
        argv.append("--overwrite")

    sys.argv = argv
    return eval_nagi_v11.main()


if __name__ == "__main__":
    raise SystemExit(main())
