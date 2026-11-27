"""
Software Development Toolkit for ZYRQUEN Tool Center.
Binds real static validation, code contracts, language registry, and sandboxed workspace files.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from apps.core.intelligence.build_validation import BuildValidationInterface, BuildValidationUnavailable
from apps.core.intelligence.code_contract import analyze_code_output, analyze_code_task
from apps.core.intelligence.language_registry import ProgrammingLanguageRegistry
from apps.core.intelligence.static_validation import PythonSyntaxValidator, StaticValidationInterface
import tools_engine as te

from ..app_builder import (
    build_and_verify_app,
    manage_workspace_history,
    run_real_project_build,
)
from ..contracts import CapabilitySpec, ToolkitManifest
from ..software_engineering import WorkspaceTransaction, _diagnose_failure, _safe_confined_path, compute_unified_diff

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _inspect_python_source(source: str) -> dict[str, Any]:
    validator = PythonSyntaxValidator()
    static_res = validator.validate(source)
    symbols: dict[str, list[str]] = {"functions": [], "classes": [], "imports": []}
    if static_res["status"] == "valid":
        tree = ast.parse(source, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols["functions"].append(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols["classes"].append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod:
                    symbols["imports"].append(mod)
    return {
        "static_validation": static_res,
        "symbols": {k: sorted(set(v))[:40] for k, v in symbols.items()},
        "line_count": len(source.splitlines()),
    }


def _inspect_repository_target(target_path: str) -> dict[str, Any]:
    clean = str(target_path or "").strip()
    if not clean or clean in {"current_project", ".", "./"}:
        target = REPO_ROOT
    else:
        target = (REPO_ROOT / clean).resolve()
        if target != REPO_ROOT and not target.is_relative_to(REPO_ROOT):
            return {
                "ok": False,
                "status": "BLOCKED",
                "error": "Path traversal outside repository root is forbidden.",
                "output": {},
            }
    if not target.exists():
        return {
            "ok": False,
            "status": "FAILED",
            "error": f"Target path '{clean}' does not exist in repository.",
            "output": {},
        }

    if target.is_file():
        text = target.read_text(encoding="utf-8", errors="replace")
        rel = str(target.relative_to(REPO_ROOT))
        info: dict[str, Any] = {
            "mode": "file_inspection",
            "path": rel,
            "size_bytes": target.stat().st_size,
            "line_count": len(text.splitlines()),
        }
        if target.suffix == ".py":
            info["python_analysis"] = _inspect_python_source(text)
        elif target.suffix == ".json":
            try:
                parsed = json.loads(text)
                info["json_valid"] = True
                info["top_keys"] = sorted(parsed.keys())[:20] if isinstance(parsed, dict) else []
            except Exception as exc:
                info["json_valid"] = False
                info["json_error"] = str(exc)
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": info,
            "summary": f"วิเคราะห์ไฟล์ {rel} ({info['line_count']} บรรทัด) เรียบร้อยแล้ว",
        }

    # Directory architecture inspection
    counts: dict[str, int] = {"python": 0, "typescript": 0, "tests": 0, "other": 0}
    top_dirs: list[str] = []
    for entry in sorted(target.iterdir()):
        if entry.name.startswith(".") or entry.name in {"node_modules", "dist", "__pycache__", ".venv"}:
            continue
        if entry.is_dir():
            top_dirs.append(entry.name)
    sample_modules: list[str] = []
    for p in sorted(target.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(REPO_ROOT).parts
        if any(part in {"node_modules", "dist", "__pycache__", ".git", ".venv"} for part in rel_parts):
            continue
        if p.suffix == ".py":
            counts["python"] += 1
            if "test" in p.name:
                counts["tests"] += 1
            if len(sample_modules) < 25:
                sample_modules.append("/".join(rel_parts))
        elif p.suffix in {".ts", ".tsx"}:
            counts["typescript"] += 1
            if ".test." in p.name:
                counts["tests"] += 1
        else:
            counts["other"] += 1

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "mode": "repository_architecture",
            "target": str(target.relative_to(REPO_ROOT)) if target != REPO_ROOT else ".",
            "top_directories": top_dirs,
            "file_counts": counts,
            "sample_python_modules": sample_modules,
        },
        "summary": (
            f"สำรวจสถาปัตยกรรมสำเร็จ: โมดูล Python {counts['python']} ไฟล์, "
            f"TypeScript/React {counts['typescript']} ไฟล์, ไฟล์ทดสอบ {counts['tests']} ไฟล์"
        ),
    }


def _handle_code_analysis(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source")
    language = str(payload.get("language") or "python").strip().lower()
    if isinstance(source, str) and source.strip():
        lang_reg = ProgrammingLanguageRegistry()
        lang_reg.register("json", (".json",))
        lang_reg.register("typescript", (".ts", ".tsx"))
        if language == "python":
            iface = StaticValidationInterface(lang_reg)
            sv = iface.validate("python", source)
            details = _inspect_python_source(source)
            return {
                "ok": True,
                "status": "COMPLETED",
                "output": {
                    "mode": "source_static_analysis",
                    "language": "python",
                    "validation": sv,
                    **details,
                },
                "summary": (
                    f"วิเคราะห์โค้ด Python ({details['line_count']} บรรทัด): "
                    f"สถานะ {sv['status']} (ฟังก์ชัน {len(details['symbols']['functions'])}, คลาส {len(details['symbols']['classes'])})"
                ),
            }
        if language == "json":
            try:
                parsed = json.loads(source)
                return {
                    "ok": True,
                    "status": "COMPLETED",
                    "output": {
                        "mode": "source_static_analysis",
                        "language": "json",
                        "validation": {"status": "valid", "problems": [], "code_executed": False},
                        "type": type(parsed).__name__,
                    },
                    "summary": "ตรวจสอบโครงสร้าง JSON ถูกต้อง",
                }
            except Exception as exc:
                return {
                    "ok": True,
                    "status": "COMPLETED",
                    "output": {
                        "mode": "source_static_analysis",
                        "language": "json",
                        "validation": {
                            "status": "invalid",
                            "problems": [{"message": str(exc), "line": None, "column": None}],
                            "code_executed": False,
                        },
                    },
                    "summary": f"JSON ไม่ถูกต้อง: {exc}",
                }
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "mode": "source_lexical_analysis",
                "language": language,
                "line_count": len(source.splitlines()),
                "char_count": len(source),
                "code_executed": False,
            },
            "summary": f"วิเคราะห์โครงสร้างข้อความ {language} ({len(source.splitlines())} บรรทัด)",
        }

    repo_target = str(payload.get("target_path") or payload.get("repository") or "current_project")
    return _inspect_repository_target(repo_target)


def _handle_contract_validate(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    lang_reg = ProgrammingLanguageRegistry()
    lang_reg.register("typescript", (".ts", ".tsx"))
    lang_reg.register("json", (".json",))
    lang_reg.register("markdown", (".md",))

    kind = str(payload.get("kind") or "task").strip().lower()
    target = payload.get("payload")
    if not isinstance(target, dict):
        return {
            "ok": False,
            "status": "FAILED",
            "error": "payload must be a JSON object representing a code task or code output.",
            "output": {},
        }
    if kind == "output":
        res = analyze_code_output(target, lang_reg, expected_task_id=payload.get("expected_task_id"))
        valid = res["status"] == "valid_output"
    else:
        res = analyze_code_task(target, lang_reg)
        valid = res["status"] == "valid_task"

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "kind": kind,
            "valid": valid,
            **res,
        },
        "summary": f"ตรวจสอบ Code Contract ({kind}): {res['status']} ({len(res['problems'])} ปัญหา)",
    }


def _handle_workspace_file(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "list").strip().lower()
    data_dir: Path = ctx["data_dir"]
    if action == "list":
        files = te.list_workspace_files(data_dir)
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {"action": "list", "files": files, "count": len(files)},
            "summary": f"พบไฟล์ใน workspace จำนวน {len(files)} ไฟล์",
        }
    filename = str(payload.get("filename") or "").strip()
    if action == "read":
        if not filename:
            return {"ok": False, "status": "FAILED", "error": "filename is required for read.", "output": {}}
        target = te.safe_workspace_path(data_dir, filename)
        if not target or not target.exists():
            return {"ok": False, "status": "FAILED", "error": f"Workspace file '{filename}' not found.", "output": {}}
        content = target.read_text(encoding="utf-8", errors="replace")[:20000]
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {"action": "read", "filename": target.name, "content": content, "size_bytes": target.stat().st_size},
            "summary": f"อ่านไฟล์ {target.name} ({target.stat().st_size} B) สำเร็จ",
        }
    if action == "write":
        content = str(payload.get("content") or "")
        saved = te.save_workspace_file(data_dir, filename, content)
        if not saved.get("ok"):
            return {"ok": False, "status": "FAILED", "error": saved.get("error"), "output": {}}
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {"action": "write", "file": saved.get("file")},
            "summary": f"บันทึกไฟล์ {filename} เข้าสู่ workspace เรียบร้อยแล้ว",
        }
    return {"ok": False, "status": "FAILED", "error": "Unsupported action (expected list, read, or write).", "output": {}}


def _handle_build_validate(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    iface = BuildValidationInterface()
    try:
        iface.validate(payload.get("specification") or {}, payload.get("manifest") or {})
        return {"ok": True, "status": "COMPLETED", "output": {}}
    except BuildValidationUnavailable as exc:
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": str(exc),
            "output": {"implemented": False, "fail_closed": True},
            "summary": "Build validation ยังเป็น fail-closed placeholder (IN_DEVELOPMENT)",
        }


def _handle_git_inspect(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    git_dir = REPO_ROOT / ".git"
    if not git_dir.exists():
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "git_available": False,
                "branch": None,
                "dirty_files": [],
                "recent_commits": [],
                "reason": "Repository metadata directory (.git) is not present in this runtime.",
            },
            "summary": "ไม่พบข้อมูล .git ใน runtime นี้ (git_available=false)",
        }

    max_commits = max(1, min(15, int(payload.get("limit") or 5)))
    try:
        branch_p = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        status_p = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        log_p = subprocess.run(
            ["git", "log", f"-n{max_commits}", "--oneline"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch_p.returncode != 0:
            return {
                "ok": True,
                "status": "COMPLETED",
                "output": {
                    "git_available": False,
                    "branch": None,
                    "dirty_files": [],
                    "recent_commits": [],
                    "reason": (branch_p.stderr or "git command returned non-zero").strip(),
                },
                "summary": "ไม่สามารถอ่านสถานะ Git ได้ในสภาพแวดล้อมนี้",
            }
        dirty = [ln for ln in (status_p.stdout or "").splitlines() if ln.strip()][:50]
        commits = [ln for ln in (log_p.stdout or "").splitlines() if ln.strip()][:max_commits]
        branch = (branch_p.stdout or "").strip()
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "git_available": True,
                "branch": branch,
                "dirty_files": dirty,
                "dirty_count": len(dirty),
                "recent_commits": commits,
            },
            "summary": f"ตรวจสอบ Git (branch '{branch}', ไฟล์เปลี่ยนแปลง {len(dirty)}, คอมมิตล่าสุด {len(commits)})",
        }
    except Exception as exc:
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "git_available": False,
                "branch": None,
                "dirty_files": [],
                "recent_commits": [],
                "reason": str(exc),
            },
            "summary": f"ไม่สามารถเรียก git read-only: {exc}",
        }


def _safe_repo_path(value: str | None) -> Path | None:
    raw = str(value or ".").strip() or "."
    target = (REPO_ROOT / raw).resolve()
    if target != REPO_ROOT and not target.is_relative_to(REPO_ROOT):
        return None
    return target


def _handle_dependency_inventory(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    """Read dependency declarations without installing or executing packages."""
    target = _safe_repo_path(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}
    manifests = ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "package.json", "Pipfile", "poetry.lock", "package-lock.json")
    found: dict[str, Any] = {}
    for name in manifests:
        path = target / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            if name == "package.json":
                doc = json.loads(path.read_text(encoding="utf-8"))
                found[name] = {
                    "dependencies": sorted((doc.get("dependencies") or {}).keys()),
                    "devDependencies": sorted((doc.get("devDependencies") or {}).keys()),
                }
            elif name.endswith(".txt"):
                entries = []
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "-")):
                        entries.append(line)
                found[name] = entries[:500]
            elif name == "pyproject.toml":
                try:
                    import tomllib
                    doc = tomllib.loads(path.read_text(encoding="utf-8"))
                    project = doc.get("project", {})
                    found[name] = {"dependencies": project.get("dependencies", []), "optional_dependencies": project.get("optional-dependencies", {})}
                except (ImportError, ValueError) as exc:
                    found[name] = {"parse_error": str(exc)}
            else:
                found[name] = {"present": True, "size_bytes": path.stat().st_size}
        except (OSError, json.JSONDecodeError) as exc:
            found[name] = {"parse_error": str(exc)}
    rel_target = str(target.relative_to(REPO_ROOT)) if target != REPO_ROOT else "."
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {"target": rel_target, "manifests": found, "manifest_count": len(found), "install_performed": False},
        "summary": f"ตรวจพบไฟล์กำหนด Dependencies {len(found)} รายการ โดยไม่ติดตั้งแพ็กเกจ",
    }


def _handle_test_discovery(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    target = _safe_repo_path(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}
    ignored = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".pytest_cache"}
    matches: list[str] = []
    for path in target.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.relative_to(target).parts):
            continue
        name = path.name.lower()
        if name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx")):
            matches.append(str(path.relative_to(REPO_ROOT)))
            if len(matches) >= 500:
                break
    matches.sort()
    rel_target = str(target.relative_to(REPO_ROOT)) if target != REPO_ROOT else "."
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {"target": rel_target, "test_files": matches, "count": len(matches), "tests_executed": False},
        "summary": f"ค้นพบไฟล์ทดสอบ {len(matches)} ไฟล์ (ยังไม่ได้รันทดสอบ)",
    }


def _handle_config_audit(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    target = _safe_repo_path(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}
    config_names = ("pyproject.toml", "pytest.ini", "tox.ini", "mypy.ini", "ruff.toml", ".ruff.toml", "tsconfig.json", "vite.config.ts", "vitest.config.ts", "eslint.config.js", ".eslintrc.json", "Dockerfile", "docker-compose.yml", "compose.yaml", ".github/workflows")
    present = [name for name in config_names if (target / name).exists()]
    rel_target = str(target.relative_to(REPO_ROOT)) if target != REPO_ROOT else "."
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {"target": rel_target, "present_configs": present, "count": len(present), "files_modified": False},
        "summary": f"ตรวจพบไฟล์ตั้งค่า Build/Test/Quality {len(present)} รายการ",
    }


def _handle_symbol_search(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    """Search source files without importing or executing them."""
    target = _safe_repo_path(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}
    query = str(payload.get("query") or "").strip()
    if not query or len(query) > 160:
        return {"ok": False, "status": "FAILED", "error": "A search query of 1–160 characters is required.", "output": {}}
    extensions = {".py", ".ts", ".tsx", ".js", ".jsx"}
    ignored = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".pytest_cache"}
    files = (
        [target]
        if target.is_file()
        else (
            path
            for path in sorted(target.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in extensions
            and not any(part in ignored for part in path.relative_to(target).parts)
        )
    )
    results: list[dict[str, Any]] = []
    needle = query.casefold()
    scanned = 0
    for path in files:
        resolved = path.resolve()
        if resolved != REPO_ROOT and not resolved.is_relative_to(REPO_ROOT):
            continue
        if path.suffix.lower() not in extensions or path.stat().st_size > 1_000_000:
            continue
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            if needle not in line.casefold():
                continue
            results.append({"path": str(path.relative_to(REPO_ROOT)), "line": line_no, "text": line.strip()[:300]})
            if len(results) >= 100:
                break
        if len(results) >= 100:
            break
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "query": query,
            "matches": results,
            "count": len(results),
            "files_scanned": scanned,
            "code_executed": False,
        },
        "summary": f"ค้นหา '{query}' พบ {len(results)} จุด จากการอ่าน {scanned} ไฟล์",
    }


def _handle_diff_inspect(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    """Inspect Git diff without modifying the repository."""
    raw_path = str(payload.get("target_path") or "").strip()
    if raw_path:
        target = _safe_repo_path(raw_path)
        if target is None:
            return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
        if not target.exists():
            return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}
        rel = "." if target == REPO_ROOT else str(target.relative_to(REPO_ROOT))
    else:
        rel = "."
    if not (REPO_ROOT / ".git").exists():
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "diff": "",
                "truncated": False,
                "changed_line_count": 0,
                "target": rel,
                "repository_modified": False,
                "git_available": False,
                "reason": "Repository metadata directory (.git) is not present in this runtime.",
            },
            "summary": "Runtime นี้ไม่มี Git metadata จึงไม่มี diff ให้ตรวจสอบ",
        }
    try:
        command = ["git", "--no-pager", "diff", "--no-color", "--no-ext-diff", "--unified=3", "--"]
        if rel != ".":
            command.append(rel)
        completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=8, check=False)
        if completed.returncode not in (0, 1):
            reason = completed.stderr.strip()[:500] or "git diff failed"
            if "not a git repository" in reason.lower():
                return {
                    "ok": True,
                    "status": "COMPLETED",
                    "output": {
                        "diff": "",
                        "truncated": False,
                        "changed_line_count": 0,
                        "target": rel,
                        "repository_modified": False,
                        "git_available": False,
                        "reason": reason,
                    },
                    "summary": "Runtime นี้ไม่มี Git metadata จึงไม่มี diff ให้ตรวจสอบ",
                }
            return {"ok": False, "status": "FAILED", "error": reason, "output": {}}
        full_diff = completed.stdout
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "diff": full_diff[:40000],
                "truncated": len(full_diff) > 40000,
                "changed_line_count": sum(
                    1 for line in full_diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
                ),
                "target": rel,
                "repository_modified": False,
                "git_available": True,
            },
            "summary": "อ่าน Git diff เรียบร้อยแล้ว" if full_diff else "ไม่พบความแตกต่างใน Git diff",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "status": "FAILED", "error": f"Unable to inspect Git diff: {exc}", "output": {}}


def _resolve_sandbox_workspace(ctx: dict[str, Any], workspace_name: str | None) -> tuple[Path | None, str | None]:
    data_dir: Path = ctx["data_dir"]
    base = (data_dir / "sandbox_workspaces").resolve()
    base.mkdir(parents=True, exist_ok=True)
    raw = str(workspace_name or "default").strip()
    if not raw or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", raw) or ".." in raw:
        return None, "Invalid workspace name; use 1-64 safe characters [A-Za-z0-9._-]."
    ws = (base / raw).resolve()
    if ws == base or not ws.is_relative_to(base):
        return None, "Workspace path escapes sandbox base directory."
    ws.mkdir(parents=True, exist_ok=True)
    return ws, None


def _validate_file_syntax(rel_path: str, content: str) -> tuple[bool, str | None]:
    suffix = Path(rel_path).suffix.lower()
    if suffix == ".py":
        res = PythonSyntaxValidator().validate(content)
        if res.get("status") != "valid":
            return False, f"Python syntax error in '{rel_path}': {res.get('problems')}"
    elif suffix == ".json":
        try:
            json.loads(content)
        except Exception as exc:
            return False, f"JSON syntax error in '{rel_path}': {exc}"
    return True, None


def _handle_code_patch_apply(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Apply structured search/replace or full-file edits inside a confined sandbox workspace with syntax check & rollback."""
    ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
    if ws_err or ws is None:
        return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}

    dry_run = bool(payload.get("dry_run", False))
    target_file = str(payload.get("target_file") or "").strip()
    edits_raw = payload.get("edits")
    replacements = payload.get("replacements")

    planned_edits: dict[str, str] = {}
    if isinstance(edits_raw, dict) and edits_raw:
        for rel, body in edits_raw.items():
            planned_edits[str(rel)] = str(body)
    elif target_file and isinstance(replacements, list) and replacements:
        if target_file.startswith("/") or "\\" in target_file or "\x00" in target_file:
            return {"ok": False, "status": "BLOCKED", "error": "Unsafe target_file path.", "output": {}}
        fpath = _safe_confined_path(ws, target_file)
        if fpath is None:
            return {"ok": False, "status": "BLOCKED", "error": "Path escapes workspace or targets reserved metadata.", "output": {}}
        if not fpath.is_file():
            return {"ok": False, "status": "FAILED", "error": f"Target file '{target_file}' not found in workspace.", "output": {}}
        updated_text = fpath.read_text(encoding="utf-8", errors="replace")
        for idx, rep in enumerate(replacements):
            if not isinstance(rep, dict) or "old" not in rep or "new" not in rep:
                return {"ok": False, "status": "FAILED", "error": f"Replacement #{idx + 1} requires 'old' and 'new'.", "output": {}}
            old_s = str(rep["old"])
            new_s = str(rep["new"])
            if old_s not in updated_text:
                return {"ok": False, "status": "FAILED", "error": f"Pattern #{idx + 1} not found in '{target_file}'.", "output": {}}
            updated_text = updated_text.replace(old_s, new_s, 1)
        planned_edits[target_file] = updated_text
    else:
        return {
            "ok": False,
            "status": "FAILED",
            "error": "Provide either 'edits' mapping or ('target_file' + 'replacements').",
            "output": {},
        }

    # Validate syntax and confinement of all candidate files before/with transaction
    for rel, content in planned_edits.items():
        if rel.startswith("/") or _safe_confined_path(ws, rel) is None:
            return {"ok": False, "status": "BLOCKED", "error": f"Unsafe relative path '{rel}'.", "output": {}}
        ok_syn, syn_err = _validate_file_syntax(rel, content)
        if not ok_syn:
            return {"ok": False, "status": "FAILED", "error": syn_err, "output": {"rolled_back": False, "dry_run": dry_run}}

    if dry_run:
        diffs: dict[str, str] = {}
        for rel, content in planned_edits.items():
            fpath = _safe_confined_path(ws, rel)
            if fpath is None:
                return {"ok": False, "status": "BLOCKED", "error": "Path escapes workspace.", "output": {}}
            before = fpath.read_text(encoding="utf-8", errors="replace") if fpath.is_file() else ""
            diffs[rel] = compute_unified_diff(rel, before, content)
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "applied": False,
                "dry_run": True,
                "workspace": ws.name,
                "changed_files": sorted(planned_edits.keys()),
                "diffs": diffs,
                "syntax_verified": True,
            },
            "summary": f"จำลองการแก้โค้ด (dry-run) {len(planned_edits)} ไฟล์ผ่านการตรวจไวยากรณ์",
        }

    tx = WorkspaceTransaction(ws)
    res = tx.apply_edits(planned_edits)
    if not res.get("ok"):
        return {"ok": False, "status": res.get("status", "FAILED"), "error": res.get("error"), "output": {}}
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "applied": True,
            "dry_run": False,
            "workspace": ws.name,
            "transaction_id": res["transaction_id"],
            "changed_files": res["changed_files"],
            "diffs": res["diffs"],
            "syntax_verified": True,
        },
        "summary": f"ปรับปรุงโค้ดใน workspace '{ws.name}' สำเร็จ ({len(res['changed_files'])} ไฟล์)",
    }


def _handle_project_scaffold(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Generate deterministic project/module/test files inside a confined sandbox workspace."""
    ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
    if ws_err or ws is None:
        return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}

    module_name = str(payload.get("module_name") or "service_mod").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,48}", module_name):
        return {"ok": False, "status": "FAILED", "error": "module_name must be a valid identifier.", "output": {}}

    template = str(payload.get("template") or "python_module").strip().lower()
    dry_run = bool(payload.get("dry_run", False))
    overwrite = bool(payload.get("overwrite", False))

    pascal = "".join(p.capitalize() for p in module_name.split("_") if p) or "ServiceMod"
    files: dict[str, str] = {}
    if template == "python_module":
        files[f"{module_name}.py"] = (
            f'"""Deterministic module {module_name}."""\n\n'
            f"from __future__ import annotations\n\n\n"
            f"def run_{module_name}(value: int) -> dict[str, int | bool]:\n"
            f"    if not isinstance(value, int):\n"
            f"        raise TypeError('value must be int')\n"
            f"    return {{'ok': True, 'input': value, 'doubled': value * 2}}\n"
        )
        files[f"test_{module_name}.py"] = (
            f"import unittest\n"
            f"from {module_name} import run_{module_name}\n\n\n"
            f"class Test{pascal}(unittest.TestCase):\n"
            f"    def test_run_valid(self) -> None:\n"
            f"        res = run_{module_name}(5)\n"
            f"        self.assertTrue(res['ok'])\n"
            f"        self.assertEqual(res['doubled'], 10)\n\n"
            f"    def test_run_invalid_type(self) -> None:\n"
            f"        with self.assertRaises(TypeError):\n"
            f"            run_{module_name}('bad')  # type: ignore[arg-type]\n"
        )
    elif template == "express_route":
        files[f"{module_name}Router.ts"] = (
            f"export interface {pascal}Request {{\n"
            f"  id: string;\n"
            f"}}\n\n"
            f"export function validate{pascal}Request(body: unknown): body is {pascal}Request {{\n"
            f"  if (!body || typeof body !== 'object') return false;\n"
            f"  const id = (body as Record<string, unknown>).id;\n"
            f"  return typeof id === 'string' && id.trim().length > 0;\n"
            f"}}\n"
        )
    elif template == "python_cli_package":
        files[f"{module_name}/__init__.py"] = f"from .core import process_{module_name}\n\n__all__ = ['process_{module_name}']\n"
        files[f"{module_name}/core.py"] = (
            f"def process_{module_name}(items: list[str]) -> list[str]:\n"
            f"    return [str(i).strip() for i in items if str(i).strip()]\n"
        )
        files[f"test_{module_name}.py"] = (
            f"import unittest\n"
            f"from {module_name} import process_{module_name}\n\n"
            f"class Test{pascal}Pkg(unittest.TestCase):\n"
            f"    def test_process(self) -> None:\n"
            f"        self.assertEqual(process_{module_name}([' a ', '', 'b']), ['a', 'b'])\n"
        )
    else:
        return {"ok": False, "status": "FAILED", "error": f"Unknown template '{template}'.", "output": {}}

    for rel in files:
        target = (ws / rel).resolve()
        if not target.is_relative_to(ws):
            return {"ok": False, "status": "BLOCKED", "error": "Escaped workspace.", "output": {}}
        if target.exists() and not overwrite and not dry_run:
            return {"ok": False, "status": "FAILED", "error": f"File '{rel}' already exists (set overwrite=True to replace).", "output": {}}
        ok_syn, syn_err = _validate_file_syntax(rel, files[rel])
        if not ok_syn:
            return {"ok": False, "status": "FAILED", "error": syn_err, "output": {}}

    if dry_run:
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "created": False,
                "dry_run": True,
                "workspace": ws.name,
                "template": template,
                "files": sorted(files.keys()),
                "preview": files,
            },
            "summary": f"จำลองโครงสร้างโปรเจกต์ '{module_name}' ({len(files)} ไฟล์)",
        }

    tx = WorkspaceTransaction(ws)
    res = tx.apply_edits(files)
    if not res.get("ok"):
        return {"ok": False, "status": res.get("status", "FAILED"), "error": res.get("error"), "output": {}}
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "created": True,
            "dry_run": False,
            "workspace": ws.name,
            "template": template,
            "transaction_id": res["transaction_id"],
            "files": res["changed_files"],
        },
        "summary": f"สร้างโครงสร้างโมดูล '{module_name}' ใน workspace '{ws.name}' ({len(res['changed_files'])} ไฟล์)",
    }


def _handle_refactor_engine(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """AST-based safe Python symbol rename & unused-import inspection (inline preview or confined workspace apply)."""
    old_name = str(payload.get("old_name") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,64}", old_name) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,64}", new_name):
        return {"ok": False, "status": "FAILED", "error": "old_name and new_name must be valid Python identifiers.", "output": {}}

    dry_run = bool(payload.get("dry_run", True))
    source = payload.get("source")
    target_file = str(payload.get("target_file") or "").strip()

    ws: Path | None = None
    if isinstance(source, str) and source.strip():
        original = source
        label = target_file or "<inline.py>"
    elif target_file:
        ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
        if ws_err or ws is None:
            return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}
        if target_file.startswith("/"):
            return {"ok": False, "status": "BLOCKED", "error": "Absolute path escapes workspace.", "output": {}}
        fpath = _safe_confined_path(ws, target_file)
        if fpath is None:
            return {"ok": False, "status": "BLOCKED", "error": "Path escapes workspace.", "output": {}}
        if not fpath.is_file():
            return {"ok": False, "status": "FAILED", "error": f"File '{target_file}' not found in workspace.", "output": {}}
        original = fpath.read_text(encoding="utf-8", errors="replace")
        label = target_file
    else:
        return {"ok": False, "status": "FAILED", "error": "Provide 'source' or ('workspace' + 'target_file').", "output": {}}

    try:
        tree = ast.parse(original, mode="exec")
    except SyntaxError as exc:
        return {"ok": False, "status": "FAILED", "error": f"Cannot refactor invalid Python syntax: {exc}", "output": {}}

    class _RenameVisitor(ast.NodeTransformer):
        def __init__(self) -> None:
            self.replacements = 0
            self.collision = False

        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id == new_name:
                self.collision = True
            elif node.id == old_name:
                node.id = new_name
                self.replacements += 1
            return node

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            if node.name == new_name:
                self.collision = True
            elif node.name == old_name:
                node.name = new_name
                self.replacements += 1
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if arg.arg == old_name:
                    arg.arg = new_name
                    self.replacements += 1
            self.generic_visit(node)
            return node

        def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
            if node.name == new_name:
                self.collision = True
            elif node.name == old_name:
                node.name = new_name
                self.replacements += 1
            self.generic_visit(node)
            return node

    visitor = _RenameVisitor()
    new_tree = visitor.visit(tree)
    ast.fix_missing_locations(new_tree)

    if visitor.collision and old_name != new_name:
        return {
            "ok": False,
            "status": "FAILED",
            "error": f"Identifier collision: '{new_name}' already exists in scope.",
            "output": {"replacements": 0, "collision_detected": True},
        }

    refactored = ast.unparse(new_tree) + "\n"
    diff_text = compute_unified_diff(label, original, refactored)
    applied = False
    if not dry_run and ws is not None and target_file:
        tx = WorkspaceTransaction(ws)
        tx_res = tx.apply_edits({label: refactored})
        if not tx_res.get("ok"):
            return {"ok": False, "status": "FAILED", "error": tx_res.get("error"), "output": {}}
        applied = True

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "old_name": old_name,
            "new_name": new_name,
            "replacements": visitor.replacements,
            "applied": applied,
            "dry_run": dry_run or ws is None,
            "refactored_source": refactored,
            "diff": diff_text,
            "syntax_valid": True,
        },
        "summary": f"Refactor '{old_name}' -> '{new_name}' จำนวน {visitor.replacements} จุด (applied={applied})",
    }


def _handle_error_diagnosis(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Diagnose Python traceback/error logs & optional source/workspace for root cause and bounded repair hints."""
    stderr = str(payload.get("stderr") or payload.get("traceback") or "").strip()
    source = payload.get("source")
    workspace_name = payload.get("workspace")
    if not stderr and not (isinstance(source, str) and source.strip()):
        return {"ok": False, "status": "FAILED", "error": "stderr/traceback or source is required.", "output": {}}

    exception_type = "UnknownError"
    exception_msg = ""
    line_refs: list[dict[str, Any]] = []
    for line in stderr.splitlines():
        m_file = re.search(r'File "([^"]+)", line (\d+)(?:, in (\S+))?', line)
        if m_file:
            line_refs.append({
                "file": Path(m_file.group(1)).name,
                "line": int(m_file.group(2)),
                "function": m_file.group(3) or "<module>",
            })
        m_exc = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning))(?::\s*(.*))?$", line.strip())
        if m_exc:
            exception_type = m_exc.group(1)
            exception_msg = (m_exc.group(2) or "").strip()

    ws_diag: dict[str, Any] | None = None
    if workspace_name:
        ws, ws_err = _resolve_sandbox_workspace(ctx, str(workspace_name))
        if ws_err or ws is None:
            return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}
        ws_diag = _diagnose_failure(stderr, ws)

    syntax_problem: dict[str, Any] | None = None
    if isinstance(source, str) and source.strip():
        sv = PythonSyntaxValidator().validate(source)
        if sv.get("status") != "valid":
            syntax_problem = sv
            exception_type = "SyntaxError"

    remediation_map = {
        "SyntaxError": "ตรวจสอบวงเล็บ เครื่องหมาย ':' ท้าย def/if/for/class และการย่อหน้า",
        "IndentationError": "จัดแนว whitespace/indentation ให้สม่ำเสมอ (4 spaces)",
        "ZeroDivisionError": "เพิ่มเงื่อนไขตรวจตัวหาร != 0 ก่อนคำนวณหาร",
        "KeyError": "ใช้ .get() หรือตรวจ key membership ก่อนเข้าถึง dict",
        "NameError": "ตรวจสอบการประกาศตัวแปรหรือการ import สัญลักษณ์",
        "ImportError": "ตรวจสอบชื่อโมดูลและ PYTHONPATH / dependencies",
        "ModuleNotFoundError": "ตรวจสอบว่าโมดูลอยู่ใน sys.path หรือ manifest",
        "TypeError": "ตรวจสอบชนิดข้อมูลและจำนวนอาร์กิวเมนต์ของฟังก์ชัน",
        "AssertionError": "เปรียบเทียบผลลัพธ์จริงกับเงื่อนไขคาดหวังในฟังก์ชันเป้าหมาย",
    }

    root_cause = (
        ws_diag.get("root_cause")
        if ws_diag and ws_diag.get("root_cause") != "unclassified_runtime_failure"
        else exception_type
    )
    suggestion = (
        ws_diag.get("detail")
        if ws_diag and ws_diag.get("repairable")
        else remediation_map.get(exception_type, "ตรวจสอบ stack trace บรรทัดสุดท้ายและ input ที่ส่งเข้าฟังก์ชัน")
    )

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "exception_type": exception_type,
            "exception_message": exception_msg,
            "root_cause": root_cause,
            "stack_frames": line_refs[-10:],
            "syntax_problem": syntax_problem,
            "repairable": bool(ws_diag and ws_diag.get("repairable")),
            "suggested_patch": (ws_diag or {}).get("patch"),
            "remediation_suggestion": suggestion,
        },
        "summary": f"วินิจฉัยสาเหตุราก ({root_cause}): {suggestion}",
    }


def _handle_dependency_compatibility(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    """Cross-check package.json, requirements.txt, and pyproject.toml for version/conflict/prohibited issues."""
    target = _safe_repo_path(payload.get("target_path"))
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}

    npm_deps: dict[str, str] = {}
    duplicate_conflicts: list[dict[str, str]] = []
    unpinned_packages: list[dict[str, str]] = []
    manifests_checked: list[str] = []

    pkg_file = target / "package.json"
    if pkg_file.is_file():
        manifests_checked.append("package.json")
        try:
            pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
            deps = pkg_data.get("dependencies") or {}
            dev_deps = pkg_data.get("devDependencies") or {}
            for name, ver in deps.items():
                npm_deps[name] = str(ver)
                if name in dev_deps:
                    duplicate_conflicts.append({
                        "package": name,
                        "issue": "declared_in_both_dependencies_and_devDependencies",
                        "detail": f"dependencies={ver}, devDependencies={dev_deps[name]}",
                    })
                if str(ver).strip() in {"*", "latest", ""}:
                    unpinned_packages.append({"file": "package.json", "package": name, "spec": str(ver)})
        except Exception as exc:
            duplicate_conflicts.append({"package": "package.json", "issue": "parse_error", "detail": str(exc)})

    py_specs: dict[str, list[tuple[str, str]]] = {}
    for req_rel in ("requirements.txt", "apps/api/requirements.txt"):
        rf = target / req_rel
        if rf.is_file():
            manifests_checked.append(req_rel)
            for line in rf.read_text(encoding="utf-8", errors="replace").splitlines():
                clean = line.strip()
                if not clean or clean.startswith(("#", "-")):
                    continue
                m = re.match(r"^([A-Za-z0-9_.\-]+)(.*)$", clean)
                if m:
                    pname = m.group(1).lower()
                    spec = m.group(2).strip()
                    py_specs.setdefault(pname, []).append((req_rel, spec))
                    if not spec:
                        unpinned_packages.append({"file": req_rel, "package": pname, "spec": "unpinned"})

    for pname, entries in py_specs.items():
        distinct_specs = {s for _, s in entries if s}
        if len(distinct_specs) > 1:
            duplicate_conflicts.append({
                "package": pname,
                "issue": "conflicting_python_constraints",
                "detail": "; ".join(f"{f}: {s}" for f, s in entries),
            })

    compatible = len(duplicate_conflicts) == 0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "compatible": compatible,
            "manifests_checked": manifests_checked,
            "npm_dependency_count": len(npm_deps),
            "python_dependency_count": len(py_specs),
            "conflicts": duplicate_conflicts,
            "unpinned_packages": unpinned_packages[:30],
        },
        "summary": (
            f"ตรวจสอบความเข้ากันได้ของ Dependencies ({len(manifests_checked)} ไฟล์): "
            f"{'ไม่พบความขัดแย้ง' if compatible else f'พบความขัดแย้ง {len(duplicate_conflicts)} รายการ'}"
        ),
    }


def _handle_migration_analyzer(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Read-only analyzer for Alembic migration versions and SQLite schema consistency."""
    mig_rel = str(payload.get("migrations_path") or "apps/api/migrations/versions").strip()
    mig_dir = _safe_repo_path(mig_rel)
    if mig_dir is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}

    revisions: list[dict[str, Any]] = []
    rev_ids: set[str] = set()
    down_refs: set[str] = set()
    tables_created: list[str] = []

    if mig_dir.exists() and mig_dir.is_dir():
        for pyf in sorted(mig_dir.glob("*.py")):
            if pyf.name.startswith("__"):
                continue
            text = pyf.read_text(encoding="utf-8", errors="replace")
            m_rev = re.search(r'revision(?:\s*:\s*[^=]+)?\s*=\s*[\'"]([^\'"]+)[\'"]', text)
            m_down = re.search(r'down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:[\'"]([^\'"]+)[\'"]|None)', text)
            rev_id = m_rev.group(1) if m_rev else pyf.stem
            down_id = m_down.group(1) if (m_down and m_down.group(1)) else None
            created = re.findall(r'op\.create_table\(\s*[\'"]([^\'"]+)[\'"]', text)
            altered = re.findall(r'op\.add_column\(\s*[\'"]([^\'"]+)[\'"]', text)
            dropped = re.findall(r'op\.drop_table\(\s*[\'"]([^\'"]+)[\'"]', text)
            rev_ids.add(rev_id)
            if down_id:
                down_refs.add(down_id)
            tables_created.extend(created)
            revisions.append({
                "file": pyf.name,
                "revision": rev_id,
                "down_revision": down_id,
                "tables_created": created,
                "tables_altered": altered,
                "tables_dropped": dropped,
            })

    heads = sorted(r["revision"] for r in revisions if r["revision"] not in down_refs)
    broken_links = [
        {"revision": r["revision"], "missing_down_revision": r["down_revision"]}
        for r in revisions
        if r["down_revision"] and r["down_revision"] not in rev_ids
    ]

    sqlite_tables: list[str] = []
    conn = ctx.get("conn")
    if conn is not None:
        try:
            sqlite_tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
        except Exception:
            sqlite_tables = []

    chain_valid = len(broken_links) == 0 and len(heads) <= 1
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "migrations_path": mig_rel,
            "migration_count": len(revisions),
            "revisions": revisions,
            "heads": heads,
            "broken_links": broken_links,
            "chain_valid": chain_valid,
            "tables_declared_in_migrations": sorted(set(tables_created)),
            "sqlite_table_count": len(sqlite_tables),
        },
        "summary": f"วิเคราะห์ Migration {len(revisions)} ไฟล์ (heads={len(heads)}, chain_valid={chain_valid})",
    }


def _handle_api_implementation(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Generate a validated REST API endpoint implementation + contract verification + optional sandbox write."""
    method = str(payload.get("method") or "POST").strip().upper()
    endpoint = str(payload.get("endpoint") or "").strip()
    framework = str(payload.get("framework") or "fastapi").strip().lower()
    handler_name = str(payload.get("handler_name") or "handle_resource").strip()
    required_fields = [str(f).strip() for f in (payload.get("required_fields") or []) if str(f).strip()]
    dry_run = bool(payload.get("dry_run", True))

    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return {"ok": False, "status": "FAILED", "error": f"Unsupported HTTP method '{method}'.", "output": {}}
    if not endpoint.startswith("/api/"):
        return {"ok": False, "status": "FAILED", "error": "endpoint must start with '/api/'.", "output": {}}
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,48}", handler_name):
        return {"ok": False, "status": "FAILED", "error": "handler_name must be a valid identifier.", "output": {}}

    if framework == "express":
        checks = "\n".join(
            f"  if (!body.{f}) return res.status(400).json({{ error: 'Missing required field: {f}' }});"
            for f in required_fields
        )
        code = (
            f"import type {{ Request, Response }} from 'express';\n\n"
            f"export async function {handler_name}(req: Request, res: Response): Promise<void> {{\n"
            f"  const body = (req.body ?? {{}}) as Record<string, unknown>;\n"
            f"{checks}\n"
            f"  res.status(200).json({{ ok: true, endpoint: '{endpoint}', method: '{method}' }});\n"
            f"}}\n"
        )
        filename = f"{handler_name}.ts"
        lang = "typescript"
    else:
        field_checks = "\n".join(
            f"    if not str(payload.get({f!r}) or '').strip():\n        return {{'ok': False, 'status': 400, 'error': 'Missing required field: {f}'}}"
            for f in required_fields
        )
        code = (
            f"from __future__ import annotations\nfrom typing import Any\n\n\n"
            f"def {handler_name}(payload: dict[str, Any] | None = None) -> dict[str, Any]:\n"
            f"    payload = payload or {{}}\n"
            f"{field_checks + chr(10) if field_checks else ''}"
            f"    return {{'ok': True, 'status': 200, 'method': {method!r}, 'endpoint': {endpoint!r}}}\n"
        )
        filename = f"{handler_name}.py"
        lang = "python"
        sv = PythonSyntaxValidator().validate(code)
        if sv.get("status") != "valid":
            return {"ok": False, "status": "FAILED", "error": f"Generated code failed AST check: {sv}", "output": {}}

    written = False
    if not dry_run:
        ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
        if ws_err or ws is None:
            return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}
        tx = WorkspaceTransaction(ws)
        res = tx.apply_edits({filename: code})
        if not res.get("ok"):
            return {"ok": False, "status": "FAILED", "error": res.get("error"), "output": {}}
        written = True

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "method": method,
            "endpoint": endpoint,
            "framework": framework,
            "language": lang,
            "filename": filename,
            "code": code,
            "syntax_valid": True,
            "written_to_workspace": written,
            "dry_run": dry_run,
        },
        "summary": f"สร้างโค้ด API {method} {endpoint} ({framework}) พร้อมตรวจไวยากรณ์สำเร็จ",
    }


def _iter_jsx_open_tags(text: str, tag_names: set[str]) -> list[tuple[str, str, int]]:
    results: list[tuple[str, str, int]] = []
    for m in re.finditer(r"<(" + "|".join(sorted(tag_names)) + r")\b", text, re.IGNORECASE):
        tag = m.group(1).lower()
        i = m.end()
        brace_depth = 0
        quote: str | None = None
        escaped = False
        n = len(text)
        while i < n:
            ch = text[i]
            if quote is not None:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
            else:
                if ch in ("'", '"', "`"):
                    quote = ch
                elif ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth = max(0, brace_depth - 1)
                elif ch == ">" and brace_depth == 0:
                    attrs = text[m.end():i]
                    line_no = text[:m.start()].count("\n") + 1
                    results.append((tag, attrs, line_no))
                    break
            i += 1
    return results


def _scan_a11y_text(text: str, rel_label: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for tag, attrs, line_no in _iter_jsx_open_tags(text, {"img", "div", "span", "button"}):
        if tag == "img":
            if not re.search(r"\balt\s*=", attrs, re.IGNORECASE):
                issues.append({"file": rel_label, "line": line_no, "rule": "img-missing-alt", "severity": "warning", "detail": "<img> missing alt attribute"})
        elif tag in {"div", "span"}:
            if re.search(r"\bonClick\s*=", attrs):
                if not re.search(r"\brole\s*=", attrs) or not re.search(r"\btabIndex\b", attrs):
                    issues.append({"file": rel_label, "line": line_no, "rule": "clickable-non-interactive-element", "severity": "warning", "detail": f"<{tag} onClick> missing role or tabIndex"})
        elif tag == "button":
            if not re.search(r"\btype\s*=", attrs):
                issues.append({"file": rel_label, "line": line_no, "rule": "button-missing-type", "severity": "info", "detail": "<button> should declare explicit type attribute"})
    return issues


def _handle_frontend_a11y_audit(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    """Static accessibility (a11y) audit over inline TSX/HTML or repository frontend files."""
    source = payload.get("source")
    if isinstance(source, str) and source.strip():
        issues = _scan_a11y_text(source, "<inline_tsx>")
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "scanned_files": 1,
                "issue_count": len(issues),
                "issues": issues[:100],
                "clean": len(issues) == 0,
            },
            "summary": f"ตรวจสอบ Frontend A11y (inline): พบข้อสังเกต {len(issues)} รายการ",
        }

    target = _safe_repo_path(payload.get("target_path") or "src")
    if target is None:
        return {"ok": False, "status": "BLOCKED", "error": "Path traversal outside repository root is forbidden.", "output": {}}
    if not target.exists():
        return {"ok": False, "status": "FAILED", "error": "Target path does not exist.", "output": {}}

    files = [target] if target.is_file() else [
        p for p in sorted(target.rglob("*"))
        if p.is_file() and p.suffix.lower() in {".tsx", ".jsx", ".html"} and "node_modules" not in p.parts and "dist" not in p.parts
    ]
    all_issues: list[dict[str, Any]] = []
    for fpath in files[:200]:
        txt = fpath.read_text(encoding="utf-8", errors="replace")
        rel = str(fpath.relative_to(REPO_ROOT))
        all_issues.extend(_scan_a11y_text(txt, rel))

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "scanned_files": len(files),
            "issue_count": len(all_issues),
            "issues": all_issues[:100],
            "clean": len(all_issues) == 0,
        },
        "summary": f"ตรวจสอบ Frontend A11y ({len(files)} ไฟล์): พบข้อสังเกต {len(all_issues)} รายการ",
    }


def _handle_real_build_runner(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Run real isolated compileall + AST/policy lint + unittest suite inside sandbox workspace."""
    ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
    if ws_err or ws is None:
        return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}
    return run_real_project_build(
        ws,
        run_lint=bool(payload.get("run_lint", True)),
        run_tests=bool(payload.get("run_tests", True)),
        timeout_s=float(payload.get("timeout_s") or 8.0),
    )


def _handle_app_builder(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Multi-file Persistent App Builder with transactional edits, build+lint+test, repair loop & snapshot."""
    ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
    if ws_err or ws is None:
        return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}
    goal = str(payload.get("goal") or "").strip()
    files = payload.get("files") if isinstance(payload.get("files"), dict) else None
    patches = payload.get("patches") if isinstance(payload.get("patches"), dict) else None
    delete_files = payload.get("delete_files") if isinstance(payload.get("delete_files"), list) else None
    if not goal and not files and not patches and not delete_files:
        return {"ok": False, "status": "FAILED", "error": "Provide 'goal', 'files', 'patches', or 'delete_files'.", "output": {}}
    return build_and_verify_app(
        ws,
        goal=goal or "Multi-file app update",
        app_name=str(payload.get("app_name") or ws.name or "zyrquen_app"),
        blueprint=str(payload.get("blueprint") or "auto"),
        files=files,
        patches=patches,
        delete_files=delete_files,
        mode=str(payload.get("mode") or "upsert"),
        auto_repair=bool(payload.get("auto_repair", True)),
        max_repair_rounds=int(payload.get("max_repair_rounds") or 2),
        rollback_on_failure=bool(payload.get("rollback_on_failure", True)),
    )


def _handle_workspace_history(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Manage persistent workspace snapshots, unified diffs, file inspection, and rollback across sessions."""
    ws, ws_err = _resolve_sandbox_workspace(ctx, payload.get("workspace"))
    if ws_err or ws is None:
        return {"ok": False, "status": "BLOCKED", "error": ws_err or "Invalid workspace.", "output": {}}
    return manage_workspace_history(
        ws,
        action=str(payload.get("action") or "list"),
        snapshot_id=str(payload.get("snapshot_id")) if payload.get("snapshot_id") else None,
        base_snapshot_id=str(payload.get("base_snapshot_id")) if payload.get("base_snapshot_id") else None,
        file_path=str(payload.get("file_path")) if payload.get("file_path") else None,
        label=str(payload.get("label") or ""),
    )


def register_development_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="development",
        name="Software Development Toolkit",
        thai_name="ชุดเครื่องมือพัฒนาซอฟต์แวร์",
        version="1.2.0",
        description="วิเคราะห์โค้ด, แก้ไข/สร้าง/Refactor ใน Sandbox, วินิจฉัย Error, ตรวจ Migration/Dependency/API/Frontend A11y",
        category="engineering",
        dependencies=("apps.core.intelligence.static_validation", "apps.core.intelligence.code_contract", "python_core.tools_engine"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=(
            "apps/core/intelligence/static_validation.py",
            "apps/core/intelligence/code_contract.py",
            "apps/core/intelligence/language_registry.py",
            "apps/core/intelligence/build_validation.py",
            "python_core/tools_engine.py",
            "python_core/tool_center/software_engineering.py",
        ),
        documentation="ใช้สำหรับวิเคราะห์โครงสร้างโค้ด, ปรับปรุงโค้ดในพื้นที่กักกันพร้อม Rollback, ตรวจ Migration/Dependencies, สร้าง API และตรวจ A11y",
    )

    specs = [
        (
            CapabilitySpec(
                id="development.code_analysis",
                toolkit_id="development",
                name="วิเคราะห์โค้ดและสถาปัตยกรรม (Static Code & Repo Analysis)",
                version="1.0.0",
                description="วิเคราะห์ไวยากรณ์ Python ด้วย AST (ไม่รันโค้ด) หรือสำรวจโครงสร้างโมดูลใน Repository จริง",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "repository": {"type": "string"},
                        "target_path": {"type": "string"},
                        "task": {"type": "string"},
                        "language": {"type": "string", "enum": ["python", "json", "typescript"]},
                        "source": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["mode"]},
                dependencies=("apps.core.intelligence.static_validation",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/intelligence/static_validation.py",),
                documentation="ส่ง source+language เพื่อตรวจโค้ดโดยตรง หรือส่ง repository='current_project' เพื่อตรวจโครงสร้างโปรเจกต์",
                example_input={"repository": "current_project", "task": "inspect_architecture"},
                keywords=("code", "architecture", "project", "ast", "python", "พัฒนา", "ระบบ", "โค้ด", "โครงสร้าง"),
            ),
            _handle_code_analysis,
        ),
        (
            CapabilitySpec(
                id="development.contract_validate",
                toolkit_id="development",
                name="ตรวจสอบ Code Task & Output Contract",
                version="1.0.0",
                description="ตรวจสอบความครบถ้วนและความปลอดภัยของโครงสร้างงานเขียนโค้ดและไฟล์ผลลัพธ์ (ป้องกัน Path Traversal)",
                input_schema={
                    "type": "object",
                    "required": ["payload"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["task", "output"]},
                        "payload": {"type": "object"},
                        "expected_task_id": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["valid", "status", "problems"]},
                dependencies=("apps.core.intelligence.code_contract", "apps.core.intelligence.language_registry"),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/intelligence/code_contract.py", "apps/core/intelligence/language_registry.py"),
                documentation="ตรวจสอบ task (task_id, objective, language, requirements) หรือ output (task_id, language, files)",
                example_input={
                    "kind": "task",
                    "payload": {
                        "task_id": "task-1",
                        "objective": "Create validator",
                        "language": "python",
                        "requirements": ["Validate input strictly"],
                    },
                },
                keywords=("contract", "validate", "schema", "พัฒนา", "สัญญา"),
            ),
            _handle_contract_validate,
        ),
        (
            CapabilitySpec(
                id="development.workspace_file",
                toolkit_id="development",
                name="จัดการไฟล์เวิร์กสเปซ Sandbox",
                version="1.0.0",
                description="แสดงรายการ อ่าน หรือเขียนไฟล์ข้อความ/โค้ดภายใน DATA_DIR/workspace_files อย่างปลอดภัย",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "read", "write"]},
                        "filename": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["action"]},
                dependencies=("python_core.tools_engine",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py",),
                documentation="ระบุ action='list', 'read' (พร้อม filename), หรือ 'write' (พร้อม filename และ content)",
                example_input={"action": "list"},
                keywords=("file", "workspace", "save", "ไฟล์", "คลัง"),
            ),
            _handle_workspace_file,
        ),
        (
            CapabilitySpec(
                id="development.build_validate",
                toolkit_id="development",
                name="Build Validation Interface (อยู่ระหว่างพัฒนา)",
                version="0.1.0",
                description="อินเทอร์เฟซ Build Validation แบบ Fail-Closed จาก apps/core (ยังไม่มี Build Runner จริงเชื่อมต่อ)",
                input_schema={"type": "object", "required": [], "properties": {"specification": {"type": "object"}, "manifest": {"type": "object"}}},
                output_schema={"type": "object", "required": ["implemented"]},
                dependencies=("apps.core.intelligence.build_validation",),
                permission_mode="admin_only",
                risk_tier="governance",
                lifecycle_status="IN_DEVELOPMENT",
                bound_modules=("apps/core/intelligence/build_validation.py",),
                documentation="โมดูลนี้ยังอยู่ในสถานะ IN_DEVELOPMENT และจะตอบ BLOCKED แบบซื่อสัตย์จนกว่าจะมี Build Runner จริง",
                example_input={"specification": {}, "manifest": {}},
                keywords=("build", "compile"),
            ),
            _handle_build_validate,
        ),
        (
            CapabilitySpec(
                id="development.git_inspect",
                toolkit_id="development",
                name="ตรวจสอบสถานะ Git แบบอ่านอย่างเดียว (Read-Only Git Inspect)",
                version="1.0.0",
                description="ตรวจ branch, ไฟล์ที่เปลี่ยนแปลง และประวัติ commit ล่าสุดแบบอ่านอย่างเดียว (ไม่แก้ไข repo)",
                input_schema={"type": "object", "required": [], "properties": {"limit": {"type": "integer"}}},
                output_schema={"type": "object", "required": ["git_available", "dirty_files", "recent_commits"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="เรียก git status/log แบบ read-only และแจ้งผลตามจริงหาก runtime ไม่มี .git",
                example_input={"limit": 5},
                keywords=("git", "commit", "branch", "diff", "repo", "สถานะโค้ด"),
            ),
            _handle_git_inspect,
        ),
        (
            CapabilitySpec(
                id="development.dependency_inventory",
                toolkit_id="development",
                name="สำรวจ Dependencies ของโปรเจกต์",
                version="1.0.0",
                description="อ่าน package.json, pyproject.toml และ requirements แบบ read-only โดยไม่ติดตั้งแพ็กเกจ",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["manifests", "manifest_count"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="สำรวจรายการ dependency และไฟล์ lock/config โดยไม่เรียก package manager.",
                example_input={"target_path": "."},
                keywords=("dependency", "package", "npm", "pip", "requirements", "แพ็กเกจ"),
            ),
            _handle_dependency_inventory,
        ),
        (
            CapabilitySpec(
                id="development.test_discovery",
                toolkit_id="development",
                name="ค้นหาไฟล์ทดสอบใน Repository",
                version="1.0.0",
                description="ค้นหาไฟล์ pytest, Vitest, Jest และ Playwright ตามรูปแบบชื่อไฟล์ โดยไม่รันการทดสอบ",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["test_files", "count", "tests_executed"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="คืนรายการไฟล์ทดสอบที่ค้นพบ แยกจากการรันทดสอบจริง.",
                example_input={"target_path": "."},
                keywords=("test", "pytest", "vitest", "jest", "playwright", "ค้นหาเทสต์"),
            ),
            _handle_test_discovery,
        ),
        (
            CapabilitySpec(
                id="development.config_audit",
                toolkit_id="development",
                name="ตรวจสอบ Build และ Quality Configuration",
                version="1.0.0",
                description="ตรวจหาไฟล์ตั้งค่าของ TypeScript, Vite, pytest, lint, Docker และ CI แบบ read-only",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["present_configs", "count"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="รายงานเฉพาะไฟล์ตั้งค่าที่มีอยู่ ไม่แก้ไขไฟล์และไม่อ้างว่าระบบผ่าน CI.",
                example_input={"target_path": "."},
                keywords=("config", "build", "lint", "ci", "quality", "ตั้งค่า"),
            ),
            _handle_config_audit,
        ),
        (
            CapabilitySpec(
                id="development.symbol_search",
                toolkit_id="development",
                name="ค้นหาสัญลักษณ์และจุดใช้งานในโค้ด",
                version="1.0.0",
                description="ค้นหาชื่อฟังก์ชัน คลาส หรือข้อความในไฟล์ Python/TypeScript/JavaScript แบบอ่านอย่างเดียว",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}, "target_path": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["matches", "count", "code_executed"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="ค้นหาตำแหน่งข้อความในซอร์สโค้ดโดยไม่ import หรือ execute ไฟล์",
                example_input={"query": "register_development_toolkit", "target_path": "."},
                keywords=(
                    "symbol",
                    "search",
                    "function",
                    "class",
                    "reference",
                    "สัญลักษณ์",
                    "จุดใช้งาน",
                    "ค้นหาฟังก์ชัน",
                    "ค้นหาคลาส",
                    "ค้นหาโค้ด",
                ),
            ),
            _handle_symbol_search,
        ),
        (
            CapabilitySpec(
                id="development.diff_inspect",
                toolkit_id="development",
                name="ตรวจสอบความแตกต่างของโค้ด (Git Diff)",
                version="1.0.0",
                description="อ่าน Git diff แบบ read-only พร้อมจำกัดเวลาและขนาดผลลัพธ์",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["diff", "truncated", "repository_modified"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="อ่าน diff ที่ Git ติดตามอยู่ ไม่แก้ไขไฟล์หรือ stage การเปลี่ยนแปลง",
                example_input={"target_path": "."},
                keywords=("git", "diff", "changes", "patch", "review", "ความแตกต่าง", "ตรวจ diff", "git diff"),
            ),
            _handle_diff_inspect,
        ),
        (
            CapabilitySpec(
                id="development.code_patch_apply",
                toolkit_id="development",
                name="ปรับปรุงและแก้ไขโค้ดแบบมีธุรกรรม (Transactional Patch Apply)",
                version="1.0.0",
                description="แก้ไขไฟล์ใน sandbox workspace หรือ dry-run พร้อมตรวจไวยากรณ์ AST/JSON และ Diff/Rollback อัตโนมัติ",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "workspace": {"type": "string"},
                        "edits": {"type": "object"},
                        "target_file": {"type": "string"},
                        "replacements": {"type": "array"},
                        "dry_run": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["applied", "changed_files", "diffs", "syntax_verified"]},
                dependencies=("python_core.tool_center.software_engineering",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/software_engineering.py",),
                documentation="แก้ไขไฟล์เฉพาะใน DATA_DIR/sandbox_workspaces พร้อมตรวจไวยากรณ์ก่อนบันทึก",
                example_input={"workspace": "demo", "edits": {"app.py": "def ok():\n    return 1\n"}, "dry_run": True},
                keywords=("patch", "edit", "modify", "apply", "diff", "แก้โค้ด", "แก้ไขไฟล์", "แพตช์"),
            ),
            _handle_code_patch_apply,
        ),
        (
            CapabilitySpec(
                id="development.project_scaffold",
                toolkit_id="development",
                name="สร้างโครงสร้างโมดูลและชุดทดสอบ (Project Scaffold)",
                version="1.0.0",
                description="สร้างไฟล์โมดูลและ unit test เชิงกำหนดใน sandbox workspace หรือ dry-run preview",
                input_schema={
                    "type": "object",
                    "required": ["module_name"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "module_name": {"type": "string"},
                        "template": {"type": "string", "enum": ["python_module", "express_route", "python_cli_package"]},
                        "dry_run": {"type": "boolean"},
                        "overwrite": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["created", "files", "template"]},
                dependencies=("python_core.tool_center.software_engineering",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="สร้างโครงสร้างโค้ดพร้อมไฟล์ทดสอบภายใต้ sandbox_workspaces",
                example_input={"workspace": "demo", "module_name": "calc_helper", "template": "python_module", "dry_run": True},
                keywords=("scaffold", "boilerplate", "generate", "project", "สร้างโมดูล", "โครงสร้างโปรเจกต์"),
            ),
            _handle_project_scaffold,
        ),
        (
            CapabilitySpec(
                id="development.refactor_engine",
                toolkit_id="development",
                name="เครื่องมือปรับโครงสร้างโค้ดด้วย AST (Safe Refactor Engine)",
                version="1.0.0",
                description="เปลี่ยนชื่อสัญลักษณ์ Python เชิงโครงสร้าง AST พร้อมตรวจการชนชื่อและสร้าง Unified Diff",
                input_schema={
                    "type": "object",
                    "required": ["old_name", "new_name"],
                    "properties": {
                        "source": {"type": "string"},
                        "workspace": {"type": "string"},
                        "target_file": {"type": "string"},
                        "old_name": {"type": "string"},
                        "new_name": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["old_name", "new_name", "replacements", "diff", "syntax_valid"]},
                dependencies=("python_core.tool_center.software_engineering",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="เปลี่ยนชื่อฟังก์ชัน คลาส หรือตัวแปรด้วย AST โดยป้องกันชื่อซ้ำซ้อน",
                example_input={"source": "def old_fn(x):\n    return x + 1\n", "old_name": "old_fn", "new_name": "new_fn", "dry_run": True},
                keywords=("refactor", "rename", "ast", "cleanup", "ปรับโค้ด"),
            ),
            _handle_refactor_engine,
        ),
        (
            CapabilitySpec(
                id="development.error_diagnosis",
                toolkit_id="development",
                name="วินิจฉัยสาเหตุรากของข้อผิดพลาด (Error Diagnosis)",
                version="1.0.0",
                description="วิเคราะห์ Traceback, SyntaxError, ZeroDivisionError และเสนอแนวทางแก้ไขแบบมีโครงสร้าง",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "stderr": {"type": "string"},
                        "traceback": {"type": "string"},
                        "source": {"type": "string"},
                        "workspace": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["exception_type", "root_cause", "remediation_suggestion"]},
                dependencies=("python_core.tool_center.software_engineering",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/software_engineering.py",),
                documentation="ส่ง stderr/traceback หรือ source เพื่อระบุประเภท error และจุดแก้ไข",
                example_input={"stderr": "ZeroDivisionError: division by zero"},
                keywords=("debug", "diagnose", "error", "traceback", "fix", "แก้บั๊ก", "วินิจฉัย"),
            ),
            _handle_error_diagnosis,
        ),
        (
            CapabilitySpec(
                id="development.dependency_compatibility",
                toolkit_id="development",
                name="ตรวจสอบความเข้ากันได้ของ Dependencies",
                version="1.0.0",
                description="ตรวจหาข้อขัดแย้งเวอร์ชัน แพ็กเกจซ้ำระหว่าง dependencies/devDependencies และข้อกำหนดที่ยังไม่ตรึงเวอร์ชัน",
                input_schema={"type": "object", "properties": {"target_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["compatible", "manifests_checked", "conflicts"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="วิเคราะห์ package.json และ requirements.txt แบบ read-only",
                example_input={"target_path": "."},
                keywords=("dependency", "compatibility", "semver", "conflict", "เวอร์ชัน"),
            ),
            _handle_dependency_compatibility,
        ),
        (
            CapabilitySpec(
                id="development.migration_analyzer",
                toolkit_id="development",
                name="วิเคราะห์ Database Migrations & Schema (Read-Only)",
                version="1.0.0",
                description="ตรวจสอบสาย Revision ของ Alembic migrations, ลิงก์ที่ขาดหาย และเปรียบเทียบกับตาราง SQLite ปัจจุบัน",
                input_schema={"type": "object", "properties": {"migrations_path": {"type": "string"}}},
                output_schema={"type": "object", "required": ["migration_count", "heads", "chain_valid"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="อ่านไฟล์ migration ใน apps/api/migrations/versions แบบ read-only",
                example_input={"migrations_path": "apps/api/migrations/versions"},
                keywords=("migration", "alembic", "schema", "database", "ฐานข้อมูล"),
            ),
            _handle_migration_analyzer,
        ),
        (
            CapabilitySpec(
                id="development.api_implementation",
                toolkit_id="development",
                name="สร้างและตรวจสอบโค้ด REST API Handler",
                version="1.0.0",
                description="สร้างโค้ด API Handler (FastAPI/Python หรือ Express/TypeScript) พร้อมตรวจ validation และไวยากรณ์",
                input_schema={
                    "type": "object",
                    "required": ["method", "endpoint"],
                    "properties": {
                        "method": {"type": "string"},
                        "endpoint": {"type": "string"},
                        "framework": {"type": "string", "enum": ["fastapi", "express"]},
                        "handler_name": {"type": "string"},
                        "required_fields": {"type": "array"},
                        "workspace": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["method", "endpoint", "code", "syntax_valid"]},
                dependencies=("python_core.tool_center.software_engineering",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="สร้างและตรวจโค้ด handler สำหรับ endpoint ภายใต้ /api/*",
                example_input={"method": "POST", "endpoint": "/api/items", "framework": "fastapi", "required_fields": ["name"], "dry_run": True},
                keywords=("api", "endpoint", "handler", "fastapi", "express", "สร้าง api"),
            ),
            _handle_api_implementation,
        ),
        (
            CapabilitySpec(
                id="development.frontend_a11y_audit",
                toolkit_id="development",
                name="ตรวจสอบการเข้าถึง Frontend (Accessibility Audit)",
                version="1.0.0",
                description="สแกนไฟล์ TSX/JSX/HTML เพื่อหา <img> ไม่มี alt, <div onClick> ขาด role/tabIndex และ <button> ขาด type",
                input_schema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target_path": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["scanned_files", "issue_count", "issues", "clean"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/development.py",),
                documentation="ตรวจโค้ด Frontend เชิงสถิตเพื่อยกระดับ Accessibility",
                example_input={"target_path": "src"},
                keywords=("frontend", "a11y", "accessibility", "tsx", "ui", "การเข้าถึง"),
            ),
            _handle_frontend_a11y_audit,
        ),
        (
            CapabilitySpec(
                id="development.app_builder",
                toolkit_id="development",
                name="สร้างและปรับปรุงแอปหลายไฟล์แบบถาวร (Persistent Multi-file App Builder)",
                version="1.0.0",
                description="วางโครงสร้างและแก้ไขแอปหลายไฟล์ เชื่อม Build/Lint/Test จริง Repair Loop อัตโนมัติ และ Snapshot/Rollback",
                input_schema={
                    "type": "object",
                    "required": ["workspace"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "goal": {"type": "string"},
                        "app_name": {"type": "string"},
                        "blueprint": {"type": "string", "enum": ["auto", "python_cli_app", "python_service_app", "python_data_app"]},
                        "files": {"type": "object"},
                        "patches": {"type": "object"},
                        "delete_files": {"type": "array"},
                        "mode": {"type": "string", "enum": ["upsert", "replace"]},
                        "auto_repair": {"type": "boolean"},
                        "max_repair_rounds": {"type": "integer"},
                        "rollback_on_failure": {"type": "boolean"},
                    },
                },
                output_schema={
                    "type": "object",
                    "required": [
                        "workspace",
                        "verified",
                        "build_passed",
                        "lint_passed",
                        "tests_passed",
                        "tests_run",
                        "files",
                        "snapshot_id",
                    ],
                },
                dependencies=("python_core.tool_center.app_builder", "python_core.tool_center.software_engineering"),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/app_builder.py", "python_core/tool_center/software_engineering.py"),
                documentation="สร้าง/แก้ไขโปรเจกต์หลายไฟล์ใน sandbox_workspaces พร้อมทดสอบและบันทึก snapshot ถาวรเมื่อผ่านจริง",
                example_input={"workspace": "demo_app", "goal": "Create task manager CLI app", "blueprint": "python_cli_app"},
                keywords=("app", "builder", "multifile", "project", "create app", "สร้างแอป", "หลายไฟล์", "สร้างโปรเจกต์"),
            ),
            _handle_app_builder,
        ),
        (
            CapabilitySpec(
                id="development.real_build_runner",
                toolkit_id="development",
                name="รัน Build, Lint และ Test จริงใน Sandbox (Real Build Runner)",
                version="1.0.0",
                description="คอมไพล์ (python -I -m compileall), ตรวจ AST/Policy/Secrets และรัน unittest ในพื้นที่กักกันจริง",
                input_schema={
                    "type": "object",
                    "required": ["workspace"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "run_lint": {"type": "boolean"},
                        "run_tests": {"type": "boolean"},
                        "timeout_s": {"type": "number"},
                    },
                },
                output_schema={
                    "type": "object",
                    "required": ["workspace", "build_passed", "lint_passed", "tests_passed", "tests_run", "verified"],
                },
                dependencies=("python_core.tool_center.app_builder",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/app_builder.py", "python_core/tool_center/sandbox.py"),
                documentation="รัน Build + Lint + Unit Test จริงใน Sandbox และไม่คืน VERIFIED หากขั้นตอนใดไม่ผ่าน",
                example_input={"workspace": "demo_app", "run_lint": True, "run_tests": True},
                keywords=("build", "runner", "compile", "lint", "test", "ci", "คอมไพล์", "รันเทสต์"),
            ),
            _handle_real_build_runner,
        ),
        (
            CapabilitySpec(
                id="development.workspace_history",
                toolkit_id="development",
                name="ประวัติ Snapshot, Diff และ Rollback ของ Workspace",
                version="1.0.0",
                description="จัดการ Snapshot ของโปรเจกต์ เปรียบเทียบ Unified Diff และย้อนกลับไปยังสถานะที่ผ่านการตรวจสอบ",
                input_schema={
                    "type": "object",
                    "required": ["workspace", "action"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "action": {"type": "string", "enum": ["snapshot", "list", "diff", "rollback", "read_file"]},
                        "snapshot_id": {"type": "string"},
                        "base_snapshot_id": {"type": "string"},
                        "file_path": {"type": "string"},
                        "label": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["action", "workspace"]},
                dependencies=("python_core.tool_center.app_builder",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/app_builder.py",),
                documentation="บันทึก snapshot ใน .zyrquen_history, ตรวจ diff ระหว่างรุ่น และ rollback แบบ atomic",
                example_input={"workspace": "demo_app", "action": "list"},
                keywords=("snapshot", "history", "diff", "rollback", "restore", "ย้อนกลับ", "ประวัติ"),
            ),
            _handle_workspace_history,
        ),
    ]

    registry.register_toolkit(manifest, specs)
