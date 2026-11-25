import re
from dataclasses import dataclass, field
from typing import Optional
from .models import CIJob

@dataclass(frozen=True)
class FailureDiagnosis:
    category: str  # "syntax_error", "assertion_error", "dependency_error", "unknown"
    error_message: str
    target_file: Optional[str] = None
    line_number: Optional[int] = None
    context_lines: list[str] = field(default_factory=list)


def analyze_log(job: CIJob) -> FailureDiagnosis:
    """Analyze raw logs to extract error messages, files, line numbers, and classify the failure."""
    logs = job.logs or ""
    
    # Common regex patterns to catch errors
    python_traceback_re = re.compile(r'File "([^\n"]+)", line (\d+)')
    js_traceback_re = re.compile(r'([^\s\n]+):(\d+):(\d+)')

    target_file = None
    line_number = None
    category = "unknown"
    error_message = "No explicit error signature detected in logs."

    py_match = list(python_traceback_re.finditer(logs))
    if py_match:
        last_frame = py_match[-1]
        target_file = last_frame.group(1)
        line_number = int(last_frame.group(2))
    else:
        js_match = list(js_traceback_re.finditer(logs))
        if js_match:
            last_frame = js_match[-1]
            target_file = last_frame.group(1)
            line_number = int(last_frame.group(2))

    if "SyntaxError" in logs or "invalid syntax" in logs.lower():
        category = "syntax_error"
        error_message = "Syntax error detected in codebase."
    elif "AssertionError" in logs or "failed assertion" in logs.lower():
        category = "assertion_error"
        error_message = "Test assertion failure."
    elif "ModuleNotFoundError" in logs or "npm ERR!" in logs or "ImportError" in logs:
        category = "dependency_error"
        error_message = "Missing dependency or import issue."
    
    lines = logs.splitlines()
    context = []
    for idx, line in enumerate(lines):
        if "error" in line.lower() or "fail" in line.lower() or "exception" in line.lower():
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            context = lines[start:end]
            if error_message == "No explicit error signature detected in logs.":
                error_message = line.strip()
            break

    return FailureDiagnosis(
        category=category,
        error_message=error_message,
        target_file=target_file,
        line_number=line_number,
        context_lines=context
    )
