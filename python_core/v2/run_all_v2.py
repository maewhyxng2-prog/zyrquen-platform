"""One-Shot ZYRQUEN V2 Runner (Ablation Suite + Long-Context & Retention Stress Test).

Usage:
    python3 python_core/v2/run_all_v2.py
    python3 python_core/v2/run_all_v2.py --backend pytorch --out-dir /content/zyrquen_v2_all
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from v2.zyrquen_v2_longctx_bench import run_longctx_experiment  # noqa: E402
from v2.zyrquen_v2_suite import default_output_root, run_suite  # noqa: E402


def run_all(
    out_dir: str | Path | None = None,
    backend: str = "auto",
) -> Dict[str, Any]:
    t0 = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    root = (
        Path(out_dir)
        if out_dir is not None
        else default_output_root("zyrquen_v2_all") / f"all_{stamp}"
    )
    root.mkdir(parents=True, exist_ok=True)

    suite_report = run_suite(out_dir=root / "suite", backend=backend)
    longctx_report = run_longctx_experiment(out_dir=root / "longctx", backend=backend)

    combined = {
        "runner": "zyrquen_v2_one_shot",
        "backend": suite_report["backend"],
        "total_elapsed_sec": round(time.time() - t0, 2),
        "ablation_suite": suite_report,
        "longctx_retention_benchmark": longctx_report,
    }
    report_path = root / "all_v2_report.json"
    report_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    combined["report_path"] = str(report_path)
    return combined


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One-Shot Runner for ZYRQUEN V2 Benchmarks")
    ap.add_argument("--backend", choices=("auto", "pytorch", "pure"), default="auto")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    try:
        result = run_all(out_dir=args.out_dir, backend=args.backend)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
