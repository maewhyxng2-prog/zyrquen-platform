"""Permission Matrix and Anti-Gate-Tamper / V10 / Native-Only Policy for ZYRQUEN Maintainer."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any


class MaintainerPolicyError(PermissionError):
    """Raised when a proposed action or patch violates Maintainer governance or gate integrity."""


# Actions permitted automatically (Tier-1) vs gated by explicit human approval (Tier-2).
MAINTAINER_PERMISSION_MATRIX: dict[str, dict[str, Any]] = {
    "repo.read": {"tier": "tier1_auto", "auto_allowed": True, "description": "Read and inspect repository files"},
    "repo.audit": {"tier": "tier1_auto", "auto_allowed": True, "description": "Run static/security/structure/CI audit"},
    "tests.run": {"tier": "tier1_auto", "auto_allowed": True, "description": "Run unit tests, compileall, and lint"},
    "branch.create": {"tier": "tier1_auto", "auto_allowed": True, "description": "Create isolated bot remediation branch"},
    "pr.propose": {"tier": "tier1_auto", "auto_allowed": True, "description": "Generate verified patch and open PR draft"},
    "git.merge_main": {"tier": "tier2_approval", "auto_allowed": False, "description": "Merge changes into main branch"},
    "git.push": {"tier": "tier2_approval", "auto_allowed": False, "description": "Push directly to protected remote branch"},
    "training.execute": {"tier": "tier2_approval", "auto_allowed": False, "description": "Execute model training run"},
    "deploy.production": {"tier": "tier2_approval", "auto_allowed": False, "description": "Deploy to production environment"},
    "compute.paid_gpu": {"tier": "tier2_approval", "auto_allowed": False, "description": "Provision or spend paid cloud GPU compute"},
    "architecture.modify": {"tier": "tier2_approval", "auto_allowed": False, "description": "Alter approved model architecture"},
    "data.delete": {"tier": "tier2_approval", "auto_allowed": False, "description": "Delete datasets or checkpoints"},
}


# Immutable baselines, security gates, governance contracts, and CI gate definitions.
# Automated patches MUST NEVER touch these paths.
PROTECTED_GATE_PATHS: tuple[str, ...] = (
    "apps/core/native/closure_audit.py",
    "apps/core/native/registry.py",
    "apps/core/native/sft.py",
    "apps/core/native/tokenizer.py",
    "apps/core/native/config.py",
    "apps/core/workflow/governance.py",
    "apps/core/workflow/orchestrator.py",
    "apps/core/maintainer/policy.py",
    "approve_v10.py",
    "tools/close_v10d.py",
    "tools/audit_leakage_v9.py",
    "tools/audit_leakage_v10.py",
    "tools/eval_nagi_v9.py",
    "tools/eval_nagi_v10.py",
    ".github/workflows/security.yml",
    ".github/workflows/capability-development.yml",
    ".github/workflows/data-quality.yml",
    ".github/workflows/api-tests.yml",
    ".github/workflows/maintainer-audit.yml",
    ".github/workflows/maintainer-pr-review.yml",
)

PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "docs/v10/",
    "checkpoints/",
)

# Forbidden content mutations anywhere in proposed patches to stop gate weakening or external LLM sneaking.
FORBIDDEN_MUTATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "gate_verdict_override",
        re.compile(r"""(?:verdict\s*=\s*["']PASS["']\s*#\s*(?:bypass|force|override)|return\s+["']PASS["']\s*#)""", re.IGNORECASE),
    ),
    (
        "fail_to_pass_rewrite",
        re.compile(r"""(?:["']FAIL["']\s*->\s*["']PASS["']|if\s+verdict\s*==\s*["']FAIL["']\s*:\s*verdict\s*=\s*["']PASS["'])""", re.IGNORECASE),
    ),
    (
        "tier2_gate_bypass",
        re.compile(r"""(?:requires_human_approval\s*=\s*False|enforce_evaluation_gate\s*=\s*False|TIER2_GATED_ACTIONS\s*=\s*(?:frozenset\(\)|set\(\)|\{\}))"""),
    ),
    (
        "external_llm_import_in_native_core",
        re.compile(r"""(?:^|\n)\s*(?:import|from)\s+(?:openai|anthropic|google\.generativeai|google\.genai|groq|together|mistralai)\b"""),
    ),
)


def normalize_repo_path(rel_path: str | Path) -> str:
    """Normalize a repository-relative POSIX path and reject traversal attempts."""
    raw = str(rel_path).replace("\\", "/").strip()
    if not raw or raw.startswith("/"):
        raise MaintainerPolicyError(f"Absolute or empty path is not allowed: {rel_path!r}")
    pure = PurePosixPath(raw)
    if ".." in pure.parts:
        raise MaintainerPolicyError(f"Path traversal ('..') is forbidden: {rel_path!r}")
    normalized = pure.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_protected_path(rel_path: str | Path) -> bool:
    """Return True if rel_path points to an immutable gate, governance, CI, or V7-V10 baseline file."""
    norm = normalize_repo_path(rel_path)
    if norm in PROTECTED_GATE_PATHS:
        return True
    for prefix in PROTECTED_PATH_PREFIXES:
        if norm.startswith(prefix):
            return True
    # Protect frozen historical V7-V10 modules/docs explicitly
    lowered = norm.lower()
    if lowered.startswith("apps/core/native/") and any(tag in lowered for tag in ("_v7", "_v8", "_v9", "_v10")):
        return True
    return False


def authorize_action(action_type: str, *, has_tier2_approval: bool = False) -> dict[str, Any]:
    """Validate whether an action can proceed under Tier-1 auto or requires Tier-2 human approval."""
    spec = MAINTAINER_PERMISSION_MATRIX.get(action_type)
    if spec is None:
        raise MaintainerPolicyError(f"Unknown maintainer action: {action_type!r} (fail-closed)")
    if spec["auto_allowed"]:
        return {"allowed": True, "tier": spec["tier"], "action_type": action_type}
    if not has_tier2_approval:
        raise MaintainerPolicyError(
            f"Action {action_type!r} requires explicit Tier-2 human approval ({spec['description']})."
        )
    return {"allowed": True, "tier": spec["tier"], "action_type": action_type, "approved": True}


def validate_patch_proposal(
    rel_path: str | Path,
    original_text: str,
    proposed_text: str,
) -> None:
    """Verify a proposed patch does not touch protected paths, weaken gates, or violate Native-Only policy."""
    norm = normalize_repo_path(rel_path)
    if is_protected_path(norm):
        raise MaintainerPolicyError(
            f"Automated patch blocked for protected gate/baseline path: {norm}"
        )

    # Check only newly introduced lines when possible so pre-existing context doesn't false-trigger.
    orig_lines = set(original_text.splitlines())
    added_lines = "\n".join(
        line for line in proposed_text.splitlines() if line not in orig_lines
    )

    # Specifically forbid introducing external LLM clients into ZYRQUEN runtime/core code.
    is_native_or_runtime = norm.startswith(("apps/core/", "apps/api/", "phases/"))
    for rule_name, pattern in FORBIDDEN_MUTATION_PATTERNS:
        if rule_name == "external_llm_import_in_native_core" and not is_native_or_runtime:
            continue
        if pattern.search(added_lines):
            raise MaintainerPolicyError(
                f"Automated patch blocked by anti-tamper rule {rule_name!r} on {norm}."
            )

    # Forbid turning pytest/unittest assertions or gate checks into unconditional pass/True.
    if norm.startswith("tests/") and "assert" in original_text:
        orig_asserts = len(re.findall(r"^\s*(?:self\.)?assert", original_text, re.MULTILINE))
        prop_asserts = len(re.findall(r"^\s*(?:self\.)?assert", proposed_text, re.MULTILINE))
        if prop_asserts < orig_asserts:
            raise MaintainerPolicyError(
                f"Automated patch blocked: cannot reduce assertions in test file {norm} "
                f"({orig_asserts} -> {prop_asserts})."
            )
