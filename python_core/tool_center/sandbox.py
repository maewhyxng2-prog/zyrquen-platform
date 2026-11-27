"""
Isolated Sandbox Execution Engine for ZYRQUEN Tool Center.
----------------------------------------------------------
Safely runs Python validation/test snippets in an isolated temporary directory
with:
  1. Pre-execution AST & Policy validation (blocks prohibited external LLM SDKs,
     shell/subprocess calls, network sockets, eval/exec, and file escapes).
  2. Clean environment (`python -I`, stripped env vars — zero parent secrets leaked).
  3. Wall-clock timeout, bounded stdout/stderr, and best-effort OS resource limits.
Pure Python 3.11 standard library.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from apps.core.intelligence.cognitive_core import (
    PROHIBITED_PYTHON_DOTTED_PREFIXES,
    PROHIBITED_PYTHON_LLM_MODULES,
)
from apps.core.intelligence.static_validation import PythonSyntaxValidator

_SANDBOX_BLOCKED_MODULES = frozenset({
    "subprocess",
    "os",
    "socket",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "ctypes",
    "multiprocessing",
    "pty",
    "fcntl",
    "shutil",
    "sqlite3",
    "webbrowser",
    "importlib",
    "builtins",
    "pathlib",
    "io",
})

_SANDBOX_BLOCKED_CALLS = frozenset({"eval", "exec", "compile", "__import__", "open", "input", "getattr"})
_SANDBOX_BLOCKED_ATTRS = frozenset({"open", "write_text", "write_bytes", "unlink", "rmdir", "system", "popen", "spawn", "execv"})


def inspect_sandbox_code_policy(source: str) -> dict[str, Any]:
    """Static AST inspection prior to running any code inside the isolated sandbox."""
    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "violations": ["Empty source code."], "syntax": {"status": "invalid"}}

    syntax = PythonSyntaxValidator().validate(source)
    if syntax.get("status") != "valid":
        return {"ok": False, "violations": [f"SyntaxError: {syntax.get('problems')}"], "syntax": syntax}

    violations: list[str] = []
    tree = ast.parse(source, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in PROHIBITED_PYTHON_LLM_MODULES or any(
                    alias.name.startswith(pref) for pref in PROHIBITED_PYTHON_DOTTED_PREFIXES
                ):
                    violations.append(f"Prohibited external AI module '{alias.name}' (line {node.lineno})")
                elif root in _SANDBOX_BLOCKED_MODULES:
                    violations.append(f"Module '{alias.name}' is restricted in isolated sandbox (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".", 1)[0]
            if root in PROHIBITED_PYTHON_LLM_MODULES or any(
                mod.startswith(pref) for pref in PROHIBITED_PYTHON_DOTTED_PREFIXES
            ):
                violations.append(f"Prohibited external AI import '{mod}' (line {node.lineno})")
            elif root in _SANDBOX_BLOCKED_MODULES:
                violations.append(f"Module '{mod}' is restricted in isolated sandbox (line {node.lineno})")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _SANDBOX_BLOCKED_CALLS:
                violations.append(f"Call '{node.func.id}()' is restricted inside sandbox (line {node.lineno})")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in _SANDBOX_BLOCKED_ATTRS:
                violations.append(f"Method '.{node.func.attr}()' is restricted inside sandbox (line {node.lineno})")

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "syntax": syntax,
    }


def _build_preexec_limiter(cpu_seconds: int, max_mem_mb: int, max_fsize_bytes: int):
    def _limit() -> None:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_fsize_bytes, max_fsize_bytes))
            mem_bytes = max_mem_mb * 1024 * 1024
            try:
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                if hard == resource.RLIM_INFINITY or mem_bytes <= hard:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, hard))
            except Exception:
                pass
        except Exception:
            pass

    return _limit


def run_python_sandbox(
    source: str,
    *,
    input_data: dict[str, Any] | None = None,
    timeout_s: float = 3.0,
    max_memory_mb: int = 256,
    max_output_chars: int = 8192,
) -> dict[str, Any]:
    """
    Execute AST-approved Python code in a fresh isolated directory (`python -I`)
    with minimal environment and resource limits. Never grants access to DB or secrets.
    """
    policy = inspect_sandbox_code_policy(source)
    if not policy["ok"]:
        return {
            "ok": False,
            "status": "BLOCKED",
            "sandbox_isolated": True,
            "timed_out": False,
            "returncode": None,
            "stdout": "",
            "stderr": "; ".join(policy["violations"]),
            "violations": policy["violations"],
            "duration_ms": 0.0,
            "external_models_used": False,
        }

    clamped_timeout = max(0.2, min(10.0, float(timeout_s)))
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="zyrquen_sandbox_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        harness = tmp_path / "sandbox_entry.py"
        # Pass optional JSON input safely via a constant literal inside harness;
        # hoist any `from __future__ import ...` lines to the very top so Python allows them.
        encoded_input = json.dumps(input_data or {}, ensure_ascii=False)
        future_lines: list[str] = []
        body_lines: list[str] = []
        for raw_ln in source.splitlines():
            stripped = raw_ln.strip()
            if stripped.startswith("from __future__ import "):
                if stripped not in future_lines:
                    future_lines.append(stripped)
            else:
                body_lines.append(raw_ln)

        prefix = ("\n".join(future_lines) + "\n") if future_lines else ""
        harness_code = (
            prefix
            + "import json\n"
            + f"SANDBOX_INPUT = json.loads({encoded_input!r})\n"
            + "\n".join(body_lines)
            + "\n"
        )
        harness.write_text(harness_code, encoding="utf-8")

        clean_env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        preexec = _build_preexec_limiter(
            cpu_seconds=max(1, int(clamped_timeout) + 1),
            max_mem_mb=max(64, int(max_memory_mb)),
            max_fsize_bytes=512 * 1024,
        )

        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(harness)],
                cwd=str(tmp_path),
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=clamped_timeout,
                preexec_fn=preexec if os.name == "posix" else None,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            stdout = (proc.stdout or "")[:max_output_chars]
            stderr = (proc.stderr or "")[:max_output_chars]
            ok = proc.returncode == 0
            return {
                "ok": ok,
                "status": "COMPLETED" if ok else "FAILED",
                "sandbox_isolated": True,
                "timed_out": False,
                "returncode": int(proc.returncode),
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "violations": [],
                "duration_ms": duration_ms,
                "external_models_used": False,
            }
        except subprocess.TimeoutExpired as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "ok": False,
                "status": "FAILED",
                "error_code": "TIMEOUT",
                "sandbox_isolated": True,
                "timed_out": True,
                "returncode": None,
                "stdout": (exc.stdout or "")[:max_output_chars] if isinstance(exc.stdout, str) else "",
                "stderr": f"Sandbox execution exceeded {clamped_timeout}s timeout.",
                "violations": [],
                "duration_ms": duration_ms,
                "external_models_used": False,
            }


def run_workspace_unittest(
    workspace_dir: Path,
    *,
    pattern: str = "test_*.py",
    timeout_s: float = 6.0,
    max_memory_mb: int = 256,
    max_output_chars: int = 12_000,
) -> dict[str, Any]:
    """
    Execute real Python `unittest discover` inside an isolated temporary copy of `workspace_dir`:
      - Pre-scans every .py file with `inspect_sandbox_code_policy`
      - Runs `python -I -m unittest discover` in a clean temp directory (stripped env, rlimits)
      - Returns real returncode, stdout, stderr, test count, and duration_ms.
    """
    ws = Path(workspace_dir).resolve()
    if not ws.exists() or not ws.is_dir():
        return {
            "ok": False,
            "status": "FAILED",
            "returncode": None,
            "stdout": "",
            "stderr": f"Workspace directory does not exist: {ws}",
            "tests_run": 0,
            "sandbox_isolated": True,
            "external_models_used": False,
        }

    def _is_ignored(path: Path) -> bool:
        try:
            parts = path.relative_to(ws).parts
        except ValueError:
            return True
        return any(part in {".zyrquen_history", "__pycache__", ".git", ".pytest_cache"} for part in parts)

    py_files = [p for p in sorted(ws.rglob("*.py")) if not _is_ignored(p)]
    json_files = [p for p in sorted(ws.rglob("*.json")) if not _is_ignored(p)]
    if not py_files:
        return {
            "ok": False,
            "status": "FAILED",
            "returncode": None,
            "stdout": "",
            "stderr": "No Python files found in workspace.",
            "tests_run": 0,
            "sandbox_isolated": True,
            "external_models_used": False,
        }

    # Static AST + Native-Only + Sandbox safety check across all Python files before running
    for pyf in py_files:
        rel = pyf.relative_to(ws)
        # Allow standard test imports (`unittest`, `pathlib`, `json`) in test_*.py, disallow network/LLM/subprocess
        src = pyf.read_text(encoding="utf-8", errors="replace")
        if pyf.name == "__init__.py" and not src.strip():
            continue
        pol = inspect_sandbox_code_policy(src)
        if not pol["ok"]:
            # Permit benign `unittest` import only inside test_*.py while still blocking all LLM/network/shell
            real_violations = [
                v for v in pol["violations"]
                if not (pyf.name.startswith("test_") and "'unittest'" in v)
            ]
            if real_violations:
                return {
                    "ok": False,
                    "status": "BLOCKED",
                    "returncode": None,
                    "stdout": "",
                    "stderr": f"{rel}: " + "; ".join(real_violations),
                    "violations": real_violations,
                    "tests_run": 0,
                    "sandbox_isolated": True,
                    "external_models_used": False,
                }

    clamped_timeout = max(0.5, min(15.0, float(timeout_s)))
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="zyrquen_ws_test_") as tmp_dir:
        tmp_ws = Path(tmp_dir)
        for pyf in py_files:
            rel = pyf.relative_to(ws)
            dest = tmp_ws / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(pyf.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            # Ensure nested test folders (e.g., tests/test_app.py) are discoverable by unittest discover
            if pyf.name.startswith("test_") and dest.parent != tmp_ws:
                init_p = dest.parent / "__init__.py"
                if not init_p.exists():
                    init_p.write_text('"""Test package marker."""\n', encoding="utf-8")
        for jf in json_files:
            rel = jf.relative_to(ws)
            dest = tmp_ws / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(jf.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

        clean_env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        preexec = _build_preexec_limiter(
            cpu_seconds=max(1, int(clamped_timeout) + 1),
            max_mem_mb=max(64, int(max_memory_mb)),
            max_fsize_bytes=512 * 1024,
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-m", "unittest", "discover", "-s", ".", "-p", pattern, "-v"],
                cwd=str(tmp_ws),
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=clamped_timeout,
                preexec_fn=preexec if os.name == "posix" else None,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            stdout = (proc.stdout or "")[:max_output_chars]
            stderr = (proc.stderr or "")[:max_output_chars]
            combined = stdout + "\n" + stderr
            import re as _re

            m_run = _re.search(r"Ran\s+(\d+)\s+tests?", combined)
            tests_run = int(m_run.group(1)) if m_run else 0
            ok = proc.returncode == 0 and tests_run > 0
            return {
                "ok": ok,
                "status": "COMPLETED" if ok else "FAILED",
                "sandbox_isolated": True,
                "timed_out": False,
                "returncode": int(proc.returncode),
                "tests_run": tests_run,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "duration_ms": duration_ms,
                "external_models_used": False,
            }
        except subprocess.TimeoutExpired as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "ok": False,
                "status": "FAILED",
                "error_code": "TIMEOUT",
                "sandbox_isolated": True,
                "timed_out": True,
                "returncode": None,
                "tests_run": 0,
                "stdout": "",
                "stderr": f"Workspace unittest exceeded {clamped_timeout}s timeout.",
                "duration_ms": duration_ms,
                "external_models_used": False,
            }

