from dataclasses import dataclass
from typing import Optional
from .analyzer import FailureDiagnosis

# Guardrail list: files that should never be edited automatically
FORBIDDEN_FILES = {
    ".github/workflows/ci.yml",
    "package.json",
    "bun.lock",
    "tsconfig.json",
    "vite.config.ts",
}

@dataclass(frozen=True)
class PatchPlan:
    target_file: str
    line_number: Optional[int]
    suggested_patch: str
    is_safe: bool
    reason: str


def create_patch_plan(diagnosis: FailureDiagnosis) -> PatchPlan:
    """Generates a plan specifying which file to modify and checks safety guardrails."""
    if not diagnosis.target_file:
        return PatchPlan(
            target_file="",
            line_number=None,
            suggested_patch="",
            is_safe=False,
            reason="No target file identified from the failure analysis."
        )

    # Guardrail checks
    file_path = diagnosis.target_file.strip()
    if any(forbidden in file_path for forbidden in FORBIDDEN_FILES):
        return PatchPlan(
            target_file=file_path,
            line_number=diagnosis.line_number,
            suggested_patch="",
            is_safe=False,
            reason=f"Modification of {file_path} is prohibited by safety guardrails."
        )

    # Generate simulated rule-based deterministic plan recommendations
    suggested_patch = ""
    reason = "Deterministic plan created for offline repair analysis."
    
    if diagnosis.category == "syntax_error":
        suggested_patch = "# TODO: Fix syntax structure near this block"
        reason = "Plan targets syntax error resolution in isolated sandbox."
    elif diagnosis.category == "assertion_error":
        suggested_patch = "# TODO: Verify correct logic implementation matching assertion requirements"
        reason = "Plan targets assertion criteria logic alignment."

    return PatchPlan(
        target_file=file_path,
        line_number=diagnosis.line_number,
        suggested_patch=suggested_patch,
        is_safe=True,
        reason=reason
    )
