#!/usr/bin/env python3
"""ZYRQUEN Autonomous Repository Maintainer CLI (Layer 1 / 2 / 3 entrypoint).

Usage:
  python tools/maintainer_bot.py --mode audit [--run-tests] [--json] [--out report.json]
  python tools/maintainer_bot.py --mode propose [--branch bot/maintainer-fix] [--out-dir /tmp/maintainer-out]
  python tools/maintainer_bot.py --mode policy-check --files file1.py file2.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.core.maintainer import (  # noqa: E402
    MaintainerPolicyError,
    ZyrquenMaintainerBot,
    is_protected_path,
    validate_patch_proposal,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZYRQUEN Autonomous Repository Maintainer CLI")
    parser.add_argument(
        "--mode",
        choices=("audit", "propose", "policy-check"),
        default="audit",
        help="Execution mode (read-only audit, safe PR proposal bundle, or protected-path policy check).",
    )
    parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repository root path")
    parser.add_argument("--run-tests", action="store_true", help="Also execute pure-stdlib unit tests")
    parser.add_argument("--branch", default=None, help="Proposed remediation branch name (never main)")
    parser.add_argument("--out", default=None, help="Write JSON output to specified file")
    parser.add_argument("--out-dir", default=None, help="Directory for remediation plan + diff artifacts")
    parser.add_argument("--json", action="store_true", help="Emit JSON output to stdout")
    parser.add_argument("--files", nargs="*", default=[], help="Relative file paths for --mode policy-check")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    bot = ZyrquenMaintainerBot(repo_root)

    if args.mode == "policy-check":
        blocked: list[dict[str, str]] = []
        for raw_path in args.files:
            try:
                if is_protected_path(raw_path):
                    blocked.append({"file": raw_path, "reason": "protected_gate_or_baseline_path"})
                else:
                    full = (repo_root / raw_path).resolve()
                    if full.is_file() and full.is_relative_to(repo_root):
                        text = full.read_text(encoding="utf-8", errors="replace")
                        validate_patch_proposal(raw_path, "", text)
            except MaintainerPolicyError as exc:
                blocked.append({"file": raw_path, "reason": str(exc)})
        payload = {"verdict": "FAIL" if blocked else "PASS", "checked": len(args.files), "blocked": blocked}
        if args.out:
            Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2) if args.json else f"policy-check: {payload['verdict']} ({len(blocked)} blocked)")
        return 1 if blocked else 0

    report = bot.run_audit(run_tests=args.run_tests)

    if args.mode == "audit":
        payload = report.to_dict()
        if args.out:
            Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"ZYRQUEN Maintainer Audit: {report.overall_verdict} | "
                f"files={report.files_scanned} | findings={len(report.findings)} | "
                f"native_only={report.checks.get('native_only_compliance')} | "
                f"dependabot={report.checks.get('dependabot_config')}"
            )
            for f in report.findings[:20]:
                loc = f"{f.file_path}:{f.line}" if f.line else f.file_path
                print(f"  - [{f.severity.upper()}] {loc} ({f.root_cause}): {f.message}")
        return 1 if report.overall_verdict == "FAIL" else 0

    if args.branch == "main":
        print("MaintainerPolicyError: refusing to target main directly as bot branch.", file=sys.stderr)
        return 2

    plan = bot.propose_remediation(report, branch_name=args.branch, verify_in_sandbox=True)
    plan_dict = plan.to_dict()

    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "remediation_plan.json").write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")
        (out_dir / "PR_DESCRIPTION.md").write_text(plan.pr_body_markdown, encoding="utf-8")
        for p in plan.proposals:
            (out_dir / f"{p.proposal_id}.patch").write_text(p.unified_diff, encoding="utf-8")

    if args.out:
        Path(args.out).write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(plan_dict, indent=2))
    else:
        print(plan.pr_body_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
