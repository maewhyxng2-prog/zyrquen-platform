import os
from .planner import PatchPlan

def apply_patch(plan: PatchPlan) -> bool:
    """Safely applies the suggested patch to the target file if approved by guardrails."""
    if not plan.is_safe:
        print(f"Skipping patch application: {plan.reason}")
        return False

    file_path = plan.target_file
    if not os.path.exists(file_path):
        print(f"Error: Target file not found: {file_path}")
        return False

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if plan.line_number is not None and 1 <= plan.line_number <= len(lines):
            # Insert suggested patch before/at the exact target line safely
            idx = plan.line_number - 1
            original_line = lines[idx]
            lines[idx] = f"{plan.suggested_patch}\n{original_line}"
            print(f"Injected patch at line {plan.line_number} in {file_path}")
        else:
            # Append to file if line number is not specified
            lines.append(f"\n{plan.suggested_patch}\n")
            print(f"Appended patch to {file_path}")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        return True
    except Exception as e:
        print(f"Failed to write patch: {e}")
        return False
