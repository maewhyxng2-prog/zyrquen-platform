"""Read-Only Repository Auditor for ZYRQUEN Autonomous Repository Maintainer."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.maintainer.policy import is_protected_path, normalize_repo_path

_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".next",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".pytest_cache",
    }
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_or_sk_key", re.compile(r"""["']sk-[A-Za-z0-9_-]{20,}["']""")),
    ("github_pat", re.compile(r"""["']gh[pousr]_[A-Za-z0-9]{20,}["']""")),
    ("google_api_key", re.compile(r"""["']AIza[0-9A-Za-z_-]{20,}["']""")),
    (
        "hardcoded_jwt_secret",
        re.compile(r"""(?:JWT_SECRET_KEY|ZYRQUEN_APPROVAL_SECRET)\s*=\s*["'][A-Za-z0-9+/=_-]{16,}["']"""),
    ),
)

_NATIVE_EXTERNAL_LLM_IMPORT = re.compile(
    r"""^\s*(?:import|from)\s+(?:openai|anthropic|google\.generativeai|google\.genai|groq|together|mistralai)\b""",
    re.MULTILINE,
)


@dataclass
class AuditFinding:
    finding_id: str
    category: str  # structure | syntax | security | native_only | dependency | ci_workflow | test_failure
    severity: str  # critical | high | medium | low | info
    file_path: str
    line: int | None
    message: str
    root_cause: str
    auto_fixable: bool = False
    protected_path: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    schema: str
    generated_at: str
    repo_root: str
    overall_verdict: str  # PASS | FAIL | BLOCKED
    files_scanned: int
    findings: list[AuditFinding] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        category_counts: dict[str, int] = {}
        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
            category_counts[f.category] = category_counts.get(f.category, 0) + 1
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "overall_verdict": self.overall_verdict,
            "files_scanned": self.files_scanned,
            "finding_count": len(self.findings),
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "checks": self.checks,
            "findings": [f.to_dict() for f in self.findings],
        }


class RepositoryAuditor:
    """Strictly read-only repository inspector covering structure, AST/bugs, security, CI, and dependencies."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def _iter_repo_files(self) -> list[Path]:
        collected: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.repo_root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fname in sorted(filenames):
                full = Path(dirpath) / fname
                if full.is_symlink():
                    continue
                if not full.resolve().is_relative_to(self.repo_root):
                    continue
                collected.append(full)
        return collected

    def run_audit(
        self,
        *,
        run_tests: bool = False,
        test_pattern: str = "test_*.py",
    ) -> AuditReport:
        files = self._iter_repo_files()
        findings: list[AuditFinding] = []
        idx = 0

        def add_finding(
            *,
            category: str,
            severity: str,
            rel_path: str,
            line: int | None,
            message: str,
            root_cause: str,
            auto_fixable: bool = False,
        ) -> None:
            nonlocal idx
            idx += 1
            norm = normalize_repo_path(rel_path)
            protected = is_protected_path(norm)
            findings.append(
                AuditFinding(
                    finding_id=f"ZMA-{idx:04d}",
                    category=category,
                    severity=severity,
                    file_path=norm,
                    line=line,
                    message=message,
                    root_cause=root_cause,
                    auto_fixable=(auto_fixable and not protected),
                    protected_path=protected,
                )
            )

        # 1. Structure & Baseline Contract Checks
        required_paths = (
            "apps/api/main.py",
            "apps/core/workflow/orchestrator.py",
            "apps/core/workflow/governance.py",
            "apps/core/native/closure_audit.py",
            "apps/core/native/train.py",
            "apps/core/native/dataset_v11.py",
            ".github/workflows/security.yml",
            ".github/workflows/api-tests.yml",
            ".github/workflows/capability-development.yml",
            ".github/workflows/data-quality.yml",
        )
        missing_required = [p for p in required_paths if not (self.repo_root / p).is_file()]
        for missing in missing_required:
            add_finding(
                category="structure",
                severity="high",
                rel_path=missing,
                line=None,
                message=f"Expected core architecture or workflow file is missing: {missing}",
                root_cause="missing_core_structure",
            )

        # Check Dependabot status honestly (note PR #15 may exist externally until merged into main)
        dependabot_path = self.repo_root / ".github" / "dependabot.yml"
        dependabot_status = "present" if dependabot_path.is_file() else "not_on_current_branch"

        # 2. Scan Python & Web files (AST, Security, Native-Only Policy)
        py_files = 0
        py_syntax_errors = 0
        native_policy_violations = 0
        security_hits = 0

        for path in files:
            rel = path.relative_to(self.repo_root).as_posix()
            suffix = path.suffix.lower()

            if suffix == ".py":
                py_files += 1
                try:
                    src = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    add_finding(
                        category="syntax",
                        severity="medium",
                        rel_path=rel,
                        line=None,
                        message=f"Could not read Python file: {exc}",
                        root_cause="unreadable_file",
                    )
                    continue

                try:
                    tree = ast.parse(src, filename=rel)
                except SyntaxError as exc:
                    py_syntax_errors += 1
                    add_finding(
                        category="syntax",
                        severity="critical",
                        rel_path=rel,
                        line=exc.lineno,
                        message=f"Python syntax error: {exc.msg}",
                        root_cause="python_syntax_error",
                    )
                    continue

                is_test_file = (
                    rel.startswith("tests/")
                    or "/test_" in f"/{rel}"
                    or path.name.startswith("test_")
                )
                is_maintainer_self = rel.startswith("apps/core/maintainer/")

                # Native-Only policy check: apps/core/native, engine, inference must never import external LLM SDKs
                if rel.startswith(("apps/core/native/", "apps/core/engine.py", "apps/core/inference.py")) and not is_test_file:
                    match = _NATIVE_EXTERNAL_LLM_IMPORT.search(src)
                    if match:
                        native_policy_violations += 1
                        line_no = src[: match.start()].count("\n") + 1
                        add_finding(
                            category="native_only",
                            severity="critical",
                            rel_path=rel,
                            line=line_no,
                            message="Forbidden external LLM SDK import detected inside ZYRQUEN Native Core.",
                            root_cause="native_only_policy_violation",
                        )

                # Hardcoded credential scan outside tests and auditor self-definitions
                if not is_test_file and not is_maintainer_self:
                    for secret_name, pat in _SECRET_PATTERNS:
                        m = pat.search(src)
                        if m:
                            security_hits += 1
                            line_no = src[: m.start()].count("\n") + 1
                            add_finding(
                                category="security",
                                severity="critical",
                                rel_path=rel,
                                line=line_no,
                                message=f"Potential hardcoded credential detected ({secret_name}).",
                                root_cause="hardcoded_secret",
                            )

                # AST checks for subprocess shell=True and unsafe torch.load without weights_only
                if not is_test_file and not is_maintainer_self:
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            fn_name = self._call_name(node.func)
                            if fn_name.startswith("subprocess."):
                                for kw in node.keywords:
                                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                        security_hits += 1
                                        add_finding(
                                            category="security",
                                            severity="high",
                                            rel_path=rel,
                                            line=getattr(node, "lineno", None),
                                            message=f"Unsafe {fn_name}(..., shell=True) call detected.",
                                            root_cause="unsafe_subprocess_shell",
                                        )
                            elif fn_name == "torch.load":
                                has_weights_only = any(kw.arg == "weights_only" for kw in node.keywords)
                                if not has_weights_only:
                                    security_hits += 1
                                    line_no = getattr(node, "lineno", None)
                                    add_finding(
                                        category="security",
                                        severity="medium",
                                        rel_path=rel,
                                        line=line_no,
                                        message="torch.load() called without explicit weights_only=True safety flag.",
                                        root_cause="unsafe_torch_load",
                                        auto_fixable=True,
                                    )

            elif suffix in {".ts", ".tsx", ".js", ".jsx"} and rel.startswith("apps/web/src/"):
                src = path.read_text(encoding="utf-8", errors="replace")
                if "test" not in path.name.lower():
                    for forbidden in ("window.alert(", "window.open("):
                        pos = src.find(forbidden)
                        if pos != -1:
                            line_no = src[:pos].count("\n") + 1
                            add_finding(
                                category="security",
                                severity="medium",
                                rel_path=rel,
                                line=line_no,
                                message=f"Iframe-incompatible call {forbidden[:-1]} detected in web UI.",
                                root_cause="unsafe_browser_dialog",
                            )

            elif rel.startswith(".github/workflows/") and suffix in {".yml", ".yaml"}:
                wf_text = path.read_text(encoding="utf-8", errors="replace")
                if "pull_request_target:" in wf_text:
                    add_finding(
                        category="ci_workflow",
                        severity="high",
                        rel_path=rel,
                        line=None,
                        message="pull_request_target trigger poses privilege escalation risk on fork PRs.",
                        root_cause="unsafe_workflow_trigger",
                    )
                if "permissions:" not in wf_text:
                    add_finding(
                        category="ci_workflow",
                        severity="low",
                        rel_path=rel,
                        line=None,
                        message="Workflow lacks explicit least-privilege permissions block.",
                        root_cause="missing_workflow_permissions",
                    )

        # 3. Dependency & Config Hygiene Check
        env_example = self.repo_root / ".env.example"
        req_file = self.repo_root / "apps" / "api" / "requirements.txt"
        web_pkg = self.repo_root / "apps" / "web" / "package.json"
        if not env_example.is_file():
            add_finding(
                category="dependency",
                severity="medium",
                rel_path=".env.example",
                line=None,
                message="Missing .env.example template.",
                root_cause="missing_env_example",
            )
        if not req_file.is_file():
            add_finding(
                category="dependency",
                severity="high",
                rel_path="apps/api/requirements.txt",
                line=None,
                message="Missing apps/api/requirements.txt dependency manifest.",
                root_cause="missing_requirements",
            )
        if web_pkg.is_file():
            try:
                pkg_data = json.loads(web_pkg.read_text(encoding="utf-8"))
                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                for banned in ("openai", "@anthropic-ai/sdk", "@google/genai", "@google/generative-ai"):
                    if banned in deps:
                        native_policy_violations += 1
                        add_finding(
                            category="native_only",
                            severity="high",
                            rel_path="apps/web/package.json",
                            line=None,
                            message=f"External LLM package {banned!r} found in web dependencies.",
                            root_cause="native_only_dependency_violation",
                        )
            except (json.JSONDecodeError, OSError) as exc:
                add_finding(
                    category="dependency",
                    severity="high",
                    rel_path="apps/web/package.json",
                    line=None,
                    message=f"Invalid package.json: {exc}",
                    root_cause="invalid_package_json",
                )

        # 4. Optional Live Unittest Execution (never fabricated!)
        test_check: dict[str, Any] = {"verdict": "NOT RUN", "executed": False}
        if run_tests:
            test_check = self._run_stdlib_tests(pattern=test_pattern)
            if test_check["verdict"] == "FAIL":
                add_finding(
                    category="test_failure",
                    severity="high",
                    rel_path="tests",
                    line=None,
                    message=f"Automated test suite failed (returncode={test_check.get('returncode')}).",
                    root_cause="unit_test_failure",
                )

        has_blocking = any(f.severity in ("critical", "high") for f in findings)
        overall_verdict = "FAIL" if has_blocking else "PASS"

        checks = {
            "python_files_parsed": py_files,
            "python_syntax_errors": py_syntax_errors,
            "native_only_compliance": "PASS" if native_policy_violations == 0 else "FAIL",
            "security_findings": security_hits,
            "dependabot_config": dependabot_status,
            "missing_required_files": missing_required,
            "tests": test_check,
        }
        return AuditReport(
            schema="zyrquen.maintainer.audit.v1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            repo_root=str(self.repo_root),
            overall_verdict=overall_verdict,
            files_scanned=len(files),
            findings=findings,
            checks=checks,
        )

    def _run_stdlib_tests(self, *, pattern: str = "test_*.py") -> dict[str, Any]:
        tests_dir = self.repo_root / "tests"
        if not tests_dir.is_dir():
            return {"verdict": "NOT RUN", "executed": False, "reason": "tests_directory_missing"}
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern]
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{self.repo_root}:{self.repo_root / 'apps' / 'api'}"
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return {"verdict": "FAIL", "executed": True, "returncode": -1, "error": "timeout"}
        except OSError as exc:
            return {"verdict": "NOT RUN", "executed": False, "reason": str(exc)}

        summary_line = ""
        combined = (proc.stderr or "") + "\n" + (proc.stdout or "")
        for line in reversed(combined.splitlines()):
            if line.strip():
                summary_line = line.strip()
                break
        return {
            "verdict": "PASS" if proc.returncode == 0 else "FAIL",
            "executed": True,
            "returncode": proc.returncode,
            "summary": summary_line,
            "tail": combined.splitlines()[-15:],
        }

    @staticmethod
    def _call_name(node: ast.AST) -> str:
        parts: list[str] = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
