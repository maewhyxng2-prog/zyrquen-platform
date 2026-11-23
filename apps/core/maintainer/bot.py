"""Layer 3 ZYRQUEN Autonomous Repository Maintainer Bot.

Performs root-cause analysis, generates policy-checked patch proposals on isolated branches,
re-runs verification in a sandboxed workspace, prepares PR evidence, and enforces Tier-2 human
approval before merging to main, pushing, training, deploying, or spending paid compute.
"""

from __future__ import annotations

import ast
import difflib
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.maintainer.auditor import AuditFinding, AuditReport, RepositoryAuditor
from apps.core.maintainer.policy import (
    MaintainerPolicyError,
    authorize_action,
    is_protected_path,
    normalize_repo_path,
    validate_patch_proposal,
)


@dataclass
class PatchProposal:
    proposal_id: str
    file_path: str
    finding_ids: list[str]
    root_cause: str
    description: str
    unified_diff: str
    proposed_content: str
    policy_status: str  # ALLOWED | BLOCKED_PROTECTED_PATH | BLOCKED_ANTI_TAMPER
    verification_status: str = "NOT RUN"  # PASS | FAIL | NOT RUN

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "file_path": self.file_path,
            "finding_ids": list(self.finding_ids),
            "root_cause": self.root_cause,
            "description": self.description,
            "unified_diff": self.unified_diff,
            "policy_status": self.policy_status,
            "verification_status": self.verification_status,
        }


@dataclass
class RemediationPlan:
    schema: str
    generated_at: str
    branch_name: str
    target_base_branch: str
    pr_title: str
    pr_body_markdown: str
    tier1_actions_used: list[str]
    tier2_required_before_merge: bool
    root_cause_summary: dict[str, int]
    proposals: list[PatchProposal] = field(default_factory=list)
    unresolved_findings: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "branch_name": self.branch_name,
            "target_base_branch": self.target_base_branch,
            "pr_title": self.pr_title,
            "pr_body_markdown": self.pr_body_markdown,
            "tier1_actions_used": list(self.tier1_actions_used),
            "tier2_required_before_merge": self.tier2_required_before_merge,
            "root_cause_summary": dict(self.root_cause_summary),
            "proposals": [p.to_dict() for p in self.proposals],
            "unresolved_findings": list(self.unresolved_findings),
            "verification": dict(self.verification),
        }


class ZyrquenMaintainerBot:
    """Layer-3 Maintainer orchestrating audits, root-cause diagnostics, safe patches, and PR drafts."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.auditor = RepositoryAuditor(self.repo_root)

    def run_audit(self, *, run_tests: bool = False, test_pattern: str = "test_*.py") -> AuditReport:
        authorize_action("repo.audit")
        return self.auditor.run_audit(run_tests=run_tests, test_pattern=test_pattern)

    @staticmethod
    def analyze_root_causes(findings: list[AuditFinding]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.root_cause] = counts.get(f.root_cause, 0) + 1
        return counts

    def build_patch_for_candidate(
        self,
        rel_path: str | Path,
        proposed_text: str,
        *,
        proposal_id: str = "PATCH-0001",
        finding_ids: list[str] | None = None,
        root_cause: str = "manual_remediation_candidate",
        description: str = "Proposed maintainer remediation patch",
    ) -> PatchProposal:
        """Validate a candidate file change against policy and verify syntax in an isolated sandbox."""
        authorize_action("pr.propose")
        norm = normalize_repo_path(rel_path)
        target = (self.repo_root / norm).resolve()
        if not target.is_relative_to(self.repo_root):
            raise MaintainerPolicyError(f"Path escapes repository root: {rel_path!r}")
        original_text = target.read_text(encoding="utf-8") if target.is_file() else ""

        if is_protected_path(norm):
            raise MaintainerPolicyError(
                f"Refusing automated patch on protected path {norm}: human review required."
            )

        validate_patch_proposal(norm, original_text, proposed_text)

        diff = "".join(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                proposed_text.splitlines(keepends=True),
                fromfile=f"a/{norm}",
                tofile=f"b/{norm}",
            )
        )

        verif = "NOT RUN"
        if norm.endswith(".py"):
            try:
                ast.parse(proposed_text, filename=norm)
                verif = "PASS"
            except SyntaxError:
                verif = "FAIL"

        return PatchProposal(
            proposal_id=proposal_id,
            file_path=norm,
            finding_ids=finding_ids or [],
            root_cause=root_cause,
            description=description,
            unified_diff=diff,
            proposed_content=proposed_text,
            policy_status="ALLOWED",
            verification_status=verif,
        )

    def propose_remediation(
        self,
        report: AuditReport,
        *,
        branch_name: str | None = None,
        verify_in_sandbox: bool = True,
    ) -> RemediationPlan:
        """Analyze AuditReport, generate safe fixes for auto-fixable non-protected findings, and verify."""
        authorize_action("branch.create")
        authorize_action("pr.propose")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        resolved_branch = branch_name or f"bot/maintainer-{stamp}"
        root_causes = self.analyze_root_causes(report.findings)

        proposals: list[PatchProposal] = []
        unresolved: list[dict[str, Any]] = []
        handled_ids: set[str] = set()

        # Group auto-fixable findings by file
        by_file: dict[str, list[AuditFinding]] = {}
        for f in report.findings:
            if f.protected_path or not f.auto_fixable:
                unresolved.append(
                    {
                        **f.to_dict(),
                        "disposition": (
                            "BLOCKED_PROTECTED_PATH"
                            if f.protected_path
                            else "REQUIRES_HUMAN_OR_DESIGN_REVIEW"
                        ),
                    }
                )
                continue
            by_file.setdefault(f.file_path, []).append(f)

        patch_seq = 0
        for rel_path, file_findings in sorted(by_file.items()):
            full_path = (self.repo_root / rel_path).resolve()
            if not full_path.is_file() or not full_path.is_relative_to(self.repo_root):
                for f in file_findings:
                    unresolved.append({**f.to_dict(), "disposition": "FILE_UNAVAILABLE"})
                continue

            original_text = full_path.read_text(encoding="utf-8")
            updated_text = original_text
            applied_findings: list[AuditFinding] = []

            for f in file_findings:
                if f.root_cause == "unsafe_torch_load":
                    candidate_text = self._patch_torch_load_weights_only(updated_text)
                    if candidate_text != updated_text:
                        updated_text = candidate_text
                        applied_findings.append(f)

            if not applied_findings or updated_text == original_text:
                for f in file_findings:
                    unresolved.append({**f.to_dict(), "disposition": "NO_SAFE_DETERMINISTIC_PATCH"})
                continue

            patch_seq += 1
            try:
                proposal = self.build_patch_for_candidate(
                    rel_path,
                    updated_text,
                    proposal_id=f"PATCH-{patch_seq:04d}",
                    finding_ids=[f.finding_id for f in applied_findings],
                    root_cause=applied_findings[0].root_cause,
                    description=(
                        f"Add explicit weights_only=True to torch.load calls in {rel_path}"
                    ),
                )
                proposals.append(proposal)
                handled_ids.update(f.finding_id for f in applied_findings)
            except MaintainerPolicyError as exc:
                for f in file_findings:
                    unresolved.append(
                        {
                            **f.to_dict(),
                            "disposition": "BLOCKED_BY_POLICY",
                            "policy_reason": str(exc),
                        }
                    )

        # Verify patched copy in an isolated temporary directory (never touching main or live workspace)
        verification_summary: dict[str, Any] = {
            "sandbox_verified": False,
            "verdict": "NOT RUN",
            "fixed_finding_ids": sorted(handled_ids),
            "unresolved_count": len(unresolved),
        }
        if verify_in_sandbox and proposals:
            verification_summary = self._verify_proposals_in_sandbox(
                proposals,
                handled_ids=handled_ids,
                unresolved_count=len(unresolved),
            )
        elif not proposals:
            verification_summary["reason"] = "no_auto_patch_generated"

        pr_title = f"[ZYRQUEN Maintainer] Automated Audit & Safe Remediation ({len(proposals)} patch(es))"
        pr_body = self._render_pr_markdown(
            report=report,
            branch_name=resolved_branch,
            proposals=proposals,
            unresolved=unresolved,
            verification=verification_summary,
        )

        return RemediationPlan(
            schema="zyrquen.maintainer.remediation.v1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            branch_name=resolved_branch,
            target_base_branch="main",
            pr_title=pr_title,
            pr_body_markdown=pr_body,
            tier1_actions_used=["repo.audit", "branch.create", "pr.propose"],
            tier2_required_before_merge=True,
            root_cause_summary=root_causes,
            proposals=proposals,
            unresolved_findings=unresolved,
            verification=verification_summary,
        )

    def merge_to_main(self, *, has_tier2_approval: bool = False) -> dict[str, Any]:
        """Protected Tier-2 gate: automated maintainer can never merge to main without approval."""
        auth = authorize_action("git.merge_main", has_tier2_approval=has_tier2_approval)
        return {
            "authorized": True,
            "tier": auth["tier"],
            "action": "git.merge_main",
            "note": "Tier-2 approval verified; ready for controlled repository merge.",
        }

    def _verify_proposals_in_sandbox(
        self,
        proposals: list[PatchProposal],
        *,
        handled_ids: set[str],
        unresolved_count: int,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "repo"
            shutil.copytree(
                self.repo_root,
                sandbox,
                ignore=shutil.ignore_patterns(".git", "node_modules", ".next", "__pycache__", ".venv", "dist"),
                symlinks=False,
            )
            for prop in proposals:
                dest = (sandbox / prop.file_path).resolve()
                if not dest.is_relative_to(sandbox.resolve()):
                    prop.verification_status = "FAIL"
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(prop.proposed_content, encoding="utf-8")

            re_audit = RepositoryAuditor(sandbox).run_audit(run_tests=False)
            remaining_ids = {
                (f.file_path, f.line, f.root_cause) for f in re_audit.findings
            }
            all_props_pass = all(p.verification_status == "PASS" for p in proposals)
            return {
                "sandbox_verified": True,
                "verdict": "PASS" if all_props_pass and re_audit.checks["python_syntax_errors"] == 0 else "FAIL",
                "fixed_finding_ids": sorted(handled_ids),
                "post_patch_finding_count": len(re_audit.findings),
                "post_patch_syntax_errors": re_audit.checks["python_syntax_errors"],
                "unresolved_count": unresolved_count,
                "remaining_sample": [list(x) for x in sorted(remaining_ids)[:10]],
            }

    @staticmethod
    def _patch_torch_load_weights_only(source: str) -> str:
        """Safely insert weights_only=True into simple single-line torch.load(...) calls."""
        pattern = re.compile(r"torch\.load\(([^()\n]+)\)")

        def _repl(match: re.Match[str]) -> str:
            inner = match.group(1).strip()
            if "weights_only" in inner:
                return match.group(0)
            return f"torch.load({inner}, weights_only=True)"

        return pattern.sub(_repl, source)

    @staticmethod
    def _render_pr_markdown(
        *,
        report: AuditReport,
        branch_name: str,
        proposals: list[PatchProposal],
        unresolved: list[dict[str, Any]],
        verification: dict[str, Any],
    ) -> str:
        lines = [
            "## ZYRQUEN Autonomous Repository Maintainer Report",
            "",
            f"- **Branch**: `{branch_name}` -> Target: `main` (Tier-2 Approval Required Before Merge)",
            f"- **Audit Verdict**: `{report.overall_verdict}` ({len(report.findings)} findings across {report.files_scanned} files)",
            f"- **Native-Only Policy**: `{report.checks.get('native_only_compliance', 'UNKNOWN')}`",
            f"- **Dependabot Config**: `{report.checks.get('dependabot_config', 'UNKNOWN')}`",
            f"- **Sandbox Verification**: `{verification.get('verdict', 'NOT RUN')}`",
            "",
            "### Proposed Safe Patches",
        ]
        if proposals:
            for p in proposals:
                lines.append(f"- `{p.proposal_id}` `{p.file_path}` ({p.root_cause}) — {p.description} [verify: `{p.verification_status}`]")
        else:
            lines.append("- None (no deterministic non-protected auto-fixes generated).")

        lines.extend(["", "### Unresolved / Human-Review Items"])
        if unresolved:
            for item in unresolved[:20]:
                lines.append(
                    f"- [{item['severity'].upper()}] `{item['file_path']}` ({item['disposition']}): {item['message']}"
                )
        else:
            lines.append("- None.")

        lines.extend(
            [
                "",
                "### Governance Guarantee",
                "- Tier-1 auto executed only read/audit/sandbox verification/PR drafting.",
                "- Protected V7–V10 baselines, evaluation gates, and `TIER2_GATED_ACTIONS` remain untouched.",
                "- Merging to `main`, pushing to protected branches, training, deploy, and paid GPU remain Tier-2 gated.",
            ]
        )
        return "\n".join(lines)
