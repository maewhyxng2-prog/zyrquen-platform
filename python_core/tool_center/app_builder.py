"""
Multi-File Persistent App Builder & Real Build Runner for ZYRQUEN Tool Center.
-----------------------------------------------------------------------------
Provides real end-to-end software creation & maintenance in confined persistent
workspaces under `DATA_DIR/sandbox_workspaces/<workspace>`:
  1. Multi-File Pipeline:
       Plans and synthesizes multi-file Python apps (`manifest.json`, `README.md`,
       package modules `models.py`, `engine.py`, `cli.py`, `main.py`, and
       `tests/__init__.py` + `tests/test_app.py`) OR applies arbitrary multi-file
       specifications (`files` dict) with create / update / patch semantics.
  2. Real Build, Lint & Test Runner (`run_real_project_build`):
       - Build: isolated `python -I -m compileall -q .` + JSON manifest check
       - Lint & Security: `ast.parse`, `inspect_sandbox_code_policy` (external LLM &
         dangerous module/call ban), secret leak scan, and structural sanity checks
       - Test: isolated `python -I -m unittest discover -s . -p "test_*.py" -v`
       Never claims `VERIFIED` if Build, Lint, or Unit Tests fail (`tests_run == 0` fails!).
  3. Persistent Workspace Snapshot History, Diff & Rollback (`.zyrquen_history/`):
       Stores versioned snapshots across sessions, computes unified diffs between
       any two revisions or against current disk state, and atomically rolls back
       failed or unwanted changes without losing verified work.

100% Pure Python 3.11 Standard Library. Zero external AI models.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from apps.core.intelligence.static_validation import PythonSyntaxValidator

from .resource_manager import get_resource_manager
from .sandbox import _build_preexec_limiter, inspect_sandbox_code_policy, run_workspace_unittest
from .software_engineering import (
    WorkspaceTransaction,
    _diagnose_failure,
    _safe_confined_path,
    compute_unified_diff,
)

HISTORY_DIRNAME = ".zyrquen_history"
IGNORED_WORKSPACE_PARTS = frozenset({HISTORY_DIRNAME, "__pycache__", ".git", ".pytest_cache"})

_SECRET_PATTERN_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{16,}\b|\bAIza[0-9A-Za-z_-]{20,}\b|\bghp_[0-9A-Za-z]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sanitize_slug(raw: str, default: str = "zyrquen_app") -> str:
    clean = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower()).strip("_")[:40]
    if not clean:
        clean = default
    if clean[0].isdigit():
        clean = f"app_{clean}"
    return clean


def _list_project_files(ws_root: Path) -> list[str]:
    if not ws_root.exists() or not ws_root.is_dir():
        return []
    files: list[str] = []
    for p in sorted(ws_root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel_parts = p.relative_to(ws_root).parts
        if any(part in IGNORED_WORKSPACE_PARTS for part in rel_parts):
            continue
        files.append("/".join(rel_parts))
    return files


def _read_workspace_text_map(ws_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in _list_project_files(ws_root):
        fp = ws_root / rel
        out[rel] = fp.read_text(encoding="utf-8", errors="replace")
    return out


def _history_paths(ws_root: Path) -> tuple[Path, Path, Path]:
    hist_dir = ws_root / HISTORY_DIRNAME
    snaps_dir = hist_dir / "snapshots"
    ledger = hist_dir / "history.json"
    return hist_dir, snaps_dir, ledger


def _load_history_ledger(ws_root: Path) -> dict[str, Any]:
    _, _, ledger = _history_paths(ws_root)
    if ledger.is_file():
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
                return data
        except Exception:
            pass
    return {"workspace": ws_root.name, "snapshots": []}


def _save_history_ledger(ws_root: Path, ledger_data: dict[str, Any]) -> None:
    hist_dir, snaps_dir, ledger = _history_paths(ws_root)
    hist_dir.mkdir(parents=True, exist_ok=True)
    snaps_dir.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(ledger_data, indent=2, ensure_ascii=False), encoding="utf-8")


def _record_snapshot(
    ws_root: Path,
    *,
    action: str,
    label: str,
    verified: bool,
    build_passed: bool | None = None,
    lint_passed: bool | None = None,
    tests_passed: bool | None = None,
    tests_run: int = 0,
    changed_files: list[str] | None = None,
    diffs: dict[str, str] | None = None,
) -> dict[str, Any]:
    ledger = _load_history_ledger(ws_root)
    _, snaps_dir, _ = _history_paths(ws_root)
    snaps_dir.mkdir(parents=True, exist_ok=True)

    snap_num = len(ledger["snapshots"]) + 1
    snap_id = f"snap_{snap_num:04d}_{uuid.uuid4().hex[:8]}"
    snap_folder = snaps_dir / snap_id
    snap_folder.mkdir(parents=True, exist_ok=True)

    text_map = _read_workspace_text_map(ws_root)
    files_sha: dict[str, str] = {}
    for rel, content in text_map.items():
        dest = snap_folder / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        files_sha[rel] = _sha256_text(content)

    entry = {
        "snapshot_id": snap_id,
        "index": snap_num,
        "created_at": _now_iso(),
        "action": action,
        "label": str(label or "")[:160],
        "verified": bool(verified),
        "build_passed": build_passed,
        "lint_passed": lint_passed,
        "tests_passed": tests_passed,
        "tests_run": int(tests_run),
        "file_count": len(text_map),
        "files_sha256": files_sha,
        "changed_files": list(changed_files or sorted(text_map.keys())),
        "diffs": dict(diffs or {}),
    }
    ledger["snapshots"].append(entry)
    # Cap stored snapshot payloads cleanly to latest 40 revisions
    if len(ledger["snapshots"]) > 40:
        removed = ledger["snapshots"].pop(0)
        old_dir = snaps_dir / str(removed.get("snapshot_id") or "")
        if old_dir.is_dir():
            shutil.rmtree(old_dir, ignore_errors=True)
    _save_history_ledger(ws_root, ledger)
    return entry


def _load_snapshot_files(ws_root: Path, snapshot_id: str) -> dict[str, str] | None:
    _, snaps_dir, _ = _history_paths(ws_root)
    snap_dir = (snaps_dir / snapshot_id).resolve()
    if not snap_dir.is_relative_to(snaps_dir.resolve()) or not snap_dir.is_dir():
        return None
    out: dict[str, str] = {}
    for p in sorted(snap_dir.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = "/".join(p.relative_to(snap_dir).parts)
        out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def manage_workspace_history(
    workspace_root: Path,
    *,
    action: str = "list",
    snapshot_id: str | None = None,
    base_snapshot_id: str | None = None,
    file_path: str | None = None,
    label: str = "",
) -> dict[str, Any]:
    """
    Manage persistent snapshots, unified diffs, file inspection, and rollback for a sandbox workspace.
    Actions: snapshot | list | diff | rollback | read_file
    """
    ws = Path(workspace_root).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    act = str(action or "list").strip().lower()
    ledger = _load_history_ledger(ws)
    snapshots = list(ledger.get("snapshots") or [])

    if act == "list":
        verified_snaps = [s for s in snapshots if s.get("verified")]
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "action": "list",
                "workspace": ws.name,
                "current_files": _list_project_files(ws),
                "snapshot_count": len(snapshots),
                "last_verified_snapshot_id": verified_snaps[-1]["snapshot_id"] if verified_snaps else None,
                "snapshots": [
                    {
                        "snapshot_id": s["snapshot_id"],
                        "index": s["index"],
                        "created_at": s["created_at"],
                        "action": s["action"],
                        "label": s["label"],
                        "verified": s["verified"],
                        "file_count": s["file_count"],
                        "tests_run": s.get("tests_run", 0),
                    }
                    for s in snapshots
                ],
            },
            "summary": f"Workspace '{ws.name}' มี snapshot {len(snapshots)} รายการ",
            "external_models_used": False,
        }

    if act == "snapshot":
        current_files = _list_project_files(ws)
        if not current_files:
            return {
                "ok": False,
                "status": "FAILED",
                "error": f"Workspace '{ws.name}' has no project files to snapshot.",
                "output": {},
                "external_models_used": False,
            }
        entry = _record_snapshot(
            ws,
            action="manual_snapshot",
            label=label or "Manual checkpoint",
            verified=False,
        )
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "action": "snapshot",
                "workspace": ws.name,
                "snapshot_id": entry["snapshot_id"],
                "file_count": entry["file_count"],
                "files": sorted(entry["files_sha256"].keys()),
                "files_sha256": entry["files_sha256"],
            },
            "summary": f"บันทึก snapshot '{entry['snapshot_id']}' ({entry['file_count']} ไฟล์) สำเร็จ",
            "external_models_used": False,
        }

    if act == "diff":
        target_snap_id = snapshot_id or (snapshots[-1]["snapshot_id"] if snapshots else None)
        if not target_snap_id:
            return {
                "ok": False,
                "status": "FAILED",
                "error": "No snapshot exists in workspace history to diff against.",
                "output": {},
                "external_models_used": False,
            }
        target_map = _load_snapshot_files(ws, target_snap_id)
        if target_map is None:
            return {
                "ok": False,
                "status": "FAILED",
                "error": f"Snapshot '{target_snap_id}' not found.",
                "output": {},
                "external_models_used": False,
            }
        if base_snapshot_id:
            base_map = _load_snapshot_files(ws, base_snapshot_id)
            if base_map is None:
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": f"Base snapshot '{base_snapshot_id}' not found.",
                    "output": {},
                    "external_models_used": False,
                }
            # Compare base_snapshot_id -> target_snap_id
            before_map, after_map = base_map, target_map
            compared = f"{base_snapshot_id} -> {target_snap_id}"
        else:
            # Compare snapshot -> current working disk state
            before_map, after_map = target_map, _read_workspace_text_map(ws)
            compared = f"{target_snap_id} -> working_tree"

        all_paths = sorted(set(before_map.keys()) | set(after_map.keys()))
        diffs: dict[str, str] = {}
        changed_files: list[str] = []
        for rel in all_paths:
            b_txt = before_map.get(rel, "")
            a_txt = after_map.get(rel, "")
            if b_txt != a_txt:
                changed_files.append(rel)
                diffs[rel] = compute_unified_diff(rel, b_txt, a_txt)
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "action": "diff",
                "workspace": ws.name,
                "compared": compared,
                "changed_files": changed_files,
                "changed_count": len(changed_files),
                "diffs": diffs,
            },
            "summary": f"เปรียบเทียบ Diff ({compared}): พบไฟล์ต่างกัน {len(changed_files)} ไฟล์",
            "external_models_used": False,
        }

    if act == "rollback":
        target_snap_id = snapshot_id
        if not target_snap_id:
            verified_snaps = [s for s in snapshots if s.get("verified")]
            if verified_snaps:
                target_snap_id = verified_snaps[-1]["snapshot_id"]
            elif snapshots:
                target_snap_id = snapshots[-1]["snapshot_id"]
        if not target_snap_id:
            return {
                "ok": False,
                "status": "FAILED",
                "error": "No snapshot available to roll back to.",
                "output": {},
                "external_models_used": False,
            }
        snap_files = _load_snapshot_files(ws, target_snap_id)
        if snap_files is None:
            return {
                "ok": False,
                "status": "FAILED",
                "error": f"Snapshot '{target_snap_id}' not found on disk.",
                "output": {},
                "external_models_used": False,
            }

        current_map = _read_workspace_text_map(ws)
        removed_files: list[str] = []
        restored_files: list[str] = []
        diffs: dict[str, str] = {}

        for rel in sorted(current_map.keys()):
            if rel not in snap_files:
                target_p = _safe_confined_path(ws, rel)
                if target_p and target_p.is_file():
                    diffs[rel] = compute_unified_diff(rel, current_map[rel], "")
                    target_p.unlink()
                    removed_files.append(rel)

        for rel, content in sorted(snap_files.items()):
            target_p = _safe_confined_path(ws, rel)
            if target_p is None:
                continue
            target_p.parent.mkdir(parents=True, exist_ok=True)
            before_txt = current_map.get(rel, "")
            if before_txt != content or not target_p.exists():
                diffs[rel] = compute_unified_diff(rel, before_txt, content)
                restored_files.append(rel)
            target_p.write_text(content, encoding="utf-8")

        # Clean empty directories outside .zyrquen_history
        for d in sorted([p for p in ws.rglob("*") if p.is_dir()], reverse=True):
            if any(part in IGNORED_WORKSPACE_PARTS for part in d.relative_to(ws).parts):
                continue
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass

        rb_snap = _record_snapshot(
            ws,
            action="rollback",
            label=label or f"Rollback to {target_snap_id}",
            verified=any(s["snapshot_id"] == target_snap_id and s.get("verified") for s in snapshots),
            changed_files=sorted(set(restored_files) | set(removed_files)),
            diffs=diffs,
        )
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "action": "rollback",
                "workspace": ws.name,
                "rolled_back_to": target_snap_id,
                "new_snapshot_id": rb_snap["snapshot_id"],
                "restored_files": restored_files,
                "removed_files": removed_files,
                "files": _list_project_files(ws),
                "diffs": diffs,
            },
            "summary": f"ย้อนกลับ workspace '{ws.name}' ไปยัง '{target_snap_id}' (คืนค่า {len(restored_files)} ไฟล์, ลบ {len(removed_files)} ไฟล์)",
            "external_models_used": False,
        }

    if act == "read_file":
        clean_rel = str(file_path or "").strip().lstrip("/")
        if (
            not clean_rel
            or ".." in Path(clean_rel).parts
            or any(part in IGNORED_WORKSPACE_PARTS for part in Path(clean_rel).parts)
        ):
            return {
                "ok": False,
                "status": "BLOCKED",
                "error": f"Forbidden or invalid workspace file_path '{file_path}'.",
                "output": {},
                "external_models_used": False,
            }
        if snapshot_id:
            snap_files = _load_snapshot_files(ws, snapshot_id)
            if snap_files is None:
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": f"Snapshot '{snapshot_id}' not found on disk.",
                    "output": {},
                    "external_models_used": False,
                }
            if clean_rel not in snap_files:
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": f"File '{clean_rel}' not found in snapshot '{snapshot_id}'.",
                    "output": {},
                    "external_models_used": False,
                }
            content = snap_files[clean_rel]
            source_ref = snapshot_id
        else:
            target_p = _safe_confined_path(ws, clean_rel)
            if target_p is None:
                return {
                    "ok": False,
                    "status": "BLOCKED",
                    "error": f"Path '{file_path}' escapes workspace root.",
                    "output": {},
                    "external_models_used": False,
                }
            if not target_p.is_file():
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": f"File '{clean_rel}' does not exist in workspace '{ws.name}'.",
                    "output": {},
                    "external_models_used": False,
                }
            content = target_p.read_text(encoding="utf-8", errors="replace")
            source_ref = "working_tree"
        return {
            "ok": True,
            "status": "COMPLETED",
            "output": {
                "action": "read_file",
                "workspace": ws.name,
                "file_path": clean_rel,
                "source": source_ref,
                "content": content,
                "sha256": _sha256_text(content),
                "bytes": len(content.encode("utf-8")),
            },
            "summary": f"อ่านไฟล์ '{clean_rel}' ({source_ref}) ใน workspace '{ws.name}' สำเร็จ",
            "external_models_used": False,
        }

    return {
        "ok": False,
        "status": "FAILED",
        "error": f"Unsupported workspace history action '{action}'.",
        "output": {},
        "external_models_used": False,
    }


def _lint_workspace_files(ws_root: Path, files: list[str]) -> dict[str, Any]:
    """Run static Python AST, native-only policy, JSON validity, and secret scan across workspace."""
    validator = PythonSyntaxValidator()
    issues: list[dict[str, Any]] = []
    files_checked = 0
    ts_files_present: list[str] = []

    for rel in files:
        fp = _safe_confined_path(ws_root, rel)
        if fp is None or not fp.is_file():
            issues.append({"file": rel, "rule": "invalid_path", "detail": "File escapes workspace or missing."})
            continue
        files_checked += 1
        src = fp.read_text(encoding="utf-8", errors="replace")

        if _SECRET_PATTERN_RE.search(src):
            issues.append({"file": rel, "rule": "secret_leak", "detail": "Potential secret token detected in source."})

        suffix = fp.suffix.lower()
        if suffix == ".py":
            if fp.name == "__init__.py" and not src.strip():
                continue
            sv = validator.validate(src)
            if sv.get("status") != "valid":
                issues.append({"file": rel, "rule": "python_syntax", "detail": str(sv.get("problems"))})
                continue
            pol = inspect_sandbox_code_policy(src)
            if not pol["ok"]:
                is_test = fp.name.startswith("test_") or "/tests/" in f"/{rel}" or rel.startswith("tests/")
                real_violations = [
                    v for v in pol["violations"]
                    if not (is_test and "'unittest'" in v)
                ]
                for v in real_violations:
                    issues.append({"file": rel, "rule": "sandbox_policy", "detail": v})
        elif suffix == ".json":
            try:
                json.loads(src)
            except Exception as exc:
                issues.append({"file": rel, "rule": "json_syntax", "detail": str(exc)})
        elif suffix in {".ts", ".tsx"}:
            ts_files_present.append(rel)

    return {
        "passed": len(issues) == 0,
        "files_checked": files_checked,
        "issue_count": len(issues),
        "issues": issues[:50],
        "ts_files_present": ts_files_present,
    }


def run_real_project_build(
    workspace_root: Path,
    *,
    run_lint: bool = True,
    run_tests: bool = True,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
    """
    Real Sandbox Build, Lint, and Unit Test Runner for a multi-file workspace:
      1. Build: copies workspace into isolated tmpdir and runs `python -I -m compileall -q .`
      2. Lint: AST + sandbox native-only policy + JSON validation + secret hygiene
      3. Test: isolated `python -I -m unittest discover -s . -p "test_*.py" -v`
    Never reports `verified=True` or `ok=True` unless Build, Lint, AND Tests (>=1 test) pass!
    """
    started = time.perf_counter()
    res_mgr = get_resource_manager()
    admission = res_mgr.evaluate_admission(requested_workers=1)
    if not admission["allowed"]:
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": admission["reason"],
            "external_models_used": False,
        }

    ws = Path(workspace_root).resolve()
    files = _list_project_files(ws)
    if not files:
        return {
            "ok": False,
            "status": "FAILED",
            "error": f"Workspace '{ws.name}' contains no project files.",
            "output": {
                "workspace": ws.name,
                "files": [],
                "build_passed": False,
                "lint_passed": False,
                "tests_passed": False,
                "tests_run": 0,
                "verified": False,
            },
            "external_models_used": False,
        }

    # 1. Lint & Security Policy Check
    if run_lint:
        lint_res = _lint_workspace_files(ws, files)
    else:
        lint_res = {"passed": False, "skipped": True, "files_checked": 0, "issue_count": 0, "issues": [], "ts_files_present": []}

    # 2. Real Build Step (`python -I -m compileall -q .` in isolated clean env mirror)
    py_files = [f for f in files if f.endswith(".py")]
    build_res: dict[str, Any] = {
        "command": "python -I -m compileall -q .",
        "executed": False,
        "passed": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "python_file_count": len(py_files),
        "duration_ms": 0.0,
    }
    if not py_files:
        build_res["stderr"] = "No Python source files to compile."
    else:
        b_t0 = time.perf_counter()
        clamped = max(1.0, min(15.0, float(timeout_s)))
        with tempfile.TemporaryDirectory(prefix="zyrquen_real_build_") as tmp_dir:
            tmp_ws = Path(tmp_dir)
            for rel in files:
                src_p = _safe_confined_path(ws, rel)
                if src_p and src_p.is_file():
                    dest_p = tmp_ws / rel
                    dest_p.parent.mkdir(parents=True, exist_ok=True)
                    dest_p.write_text(src_p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            clean_env = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            }
            preexec = _build_preexec_limiter(
                cpu_seconds=max(2, int(clamped) + 1),
                max_mem_mb=256,
                max_fsize_bytes=512 * 1024,
            )
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-m", "compileall", "-q", "."],
                    cwd=str(tmp_ws),
                    env=clean_env,
                    capture_output=True,
                    text=True,
                    timeout=clamped,
                    preexec_fn=preexec if os.name == "posix" else None,
                )
                build_res.update({
                    "executed": True,
                    "passed": proc.returncode == 0,
                    "returncode": int(proc.returncode),
                    "stdout": (proc.stdout or "").strip()[:4000],
                    "stderr": (proc.stderr or "").strip()[:4000],
                    "duration_ms": round((time.perf_counter() - b_t0) * 1000, 2),
                })
            except subprocess.TimeoutExpired:
                build_res.update({
                    "executed": True,
                    "passed": False,
                    "returncode": None,
                    "stderr": f"compileall exceeded {clamped}s timeout.",
                    "duration_ms": round((time.perf_counter() - b_t0) * 1000, 2),
                })

    # 3. Real Unit Test Execution in Isolated Sandbox
    if run_tests and lint_res["passed"] and build_res["passed"]:
        test_res = run_workspace_unittest(ws, pattern="test_*.py", timeout_s=timeout_s)
    elif not run_tests:
        test_res = {"ok": False, "status": "NOT_RUN", "tests_run": 0, "returncode": None, "stdout": "", "stderr": "Tests skipped."}
    else:
        test_res = {
            "ok": False,
            "status": "NOT_RUN",
            "tests_run": 0,
            "returncode": None,
            "stdout": "",
            "stderr": "Skipped unit tests because Build or Lint stage failed.",
        }

    # Check TS compilation honestly (never fake TS compilation when workspace has .ts files without configured runner)
    ts_note = "NOT_APPLICABLE"
    if lint_res.get("ts_files_present"):
        ts_note = "NOT_RUN_NO_SANDBOX_TSC"

    tests_run = int(test_res.get("tests_run") or 0)
    tests_passed = bool(test_res.get("ok") and tests_run > 0)
    build_passed = bool(build_res.get("passed"))
    lint_passed = bool(lint_res.get("passed"))
    verified = bool(build_passed and lint_passed and tests_passed and ts_note == "NOT_APPLICABLE")

    total_ms = round((time.perf_counter() - started) * 1000, 2)
    output_payload = {
        "workspace": ws.name,
        "files": files,
        "file_count": len(files),
        "build_passed": build_passed,
        "lint_passed": lint_passed,
        "tests_passed": tests_passed,
        "tests_run": tests_run,
        "verified": verified,
        "typescript_compile_status": ts_note,
        "build_evidence": build_res,
        "lint_evidence": lint_res,
        "test_evidence": test_res,
        "duration_ms": total_ms,
    }
    return {
        "ok": verified,
        "status": "COMPLETED" if verified else "FAILED",
        "error": (
            None
            if verified
            else (
                build_res.get("stderr")
                or (lint_res["issues"][0]["detail"] if lint_res.get("issues") else "")
                or test_res.get("stderr")
                or "Real build/lint/test verification did not pass."
            )
        ),
        "output": output_payload,
        "summary": (
            f"Build+Lint+Test ผ่านจริง ({tests_run} tests, {len(files)} ไฟล์)"
            if verified
            else f"Build/Lint/Test ไม่ผ่าน (build={build_passed}, lint={lint_passed}, tests={tests_passed}, run={tests_run})"
        ),
        "external_models_used": False,
    }


def synthesize_multifile_app_files(
    *,
    app_name: str,
    goal: str,
    blueprint: str = "auto",
) -> tuple[str, dict[str, str]]:
    """
    Deterministically synthesize a clean, cohesive multi-file Python application
    for the requested blueprint:
      - `python_cli_app`: Task & Workflow CLI app with validation, execution & JSON reporting
      - `python_service_app`: Service request router, schema contract validator & state engine
      - `python_data_app`: Structured record pipeline with deduplication, stats & SHA-256 manifest
    """
    pkg = _sanitize_slug(app_name, default="zyrquen_app")
    low = f"{blueprint} {goal}".lower()
    if blueprint == "auto":
        if any(k in low for k in ("data", "csv", "json", "etl", "pipeline", "stats", "ข้อมูล", "สถิติ")):
            chosen_bp = "python_data_app"
        elif any(k in low for k in ("api", "service", "route", "endpoint", "rest", "บริการ")):
            chosen_bp = "python_service_app"
        else:
            chosen_bp = "python_cli_app"
    elif blueprint in {"python_cli_app", "python_service_app", "python_data_app"}:
        chosen_bp = blueprint
    else:
        chosen_bp = "python_cli_app"

    safe_goal = re.sub(r"[\r\n\"']+", " ", str(goal or f"Native {pkg} application")).strip()[:120]

    manifest_obj = {
        "name": pkg,
        "version": "1.0.0",
        "blueprint": chosen_bp,
        "goal": safe_goal,
        "entrypoint": "main.py",
        "package": pkg,
        "test_command": "python -I -m unittest discover -s . -p \"test_*.py\" -v",
        "external_models_used": False,
    }

    readme_md = (
        f"# {pkg}\n\n"
        f"- **Goal**: {safe_goal}\n"
        f"- **Blueprint**: `{chosen_bp}`\n"
        f"- **Entrypoint**: `main.py`\n\n"
        f"## Structure\n"
        f"- `{pkg}/models.py` — Typed domain dataclasses & input contracts\n"
        f"- `{pkg}/engine.py` — Core deterministic logic\n"
        f"- `{pkg}/cli.py` & `main.py` — Argument parsing & JSON/text output\n"
        f"- `tests/test_app.py` — Real unit test suite\n"
    )

    if chosen_bp == "python_data_app":
        models_py = (
            f'"""Data pipeline models for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"from dataclasses import dataclass\n\n\n"
            f"@dataclass(frozen=True)\n"
            f"class PipelineReport:\n"
            f"    ok: bool\n"
            f"    status: str\n"
            f"    total_rows: int\n"
            f"    unique_rows: int\n"
            f"    duplicate_rows: int\n"
            f"    mean_score: float\n"
            f"    digest_sha256: str\n"
        )
        engine_py = (
            f'"""Deterministic data cleaning, statistics & manifest hashing for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"import hashlib\n"
            f"import json\n"
            f"from typing import Any\n\n"
            f"from .models import PipelineReport\n\n\n"
            f"def run_pipeline(records: list[dict[str, Any]]) -> PipelineReport:\n"
            f'    """Validate, deduplicate, summarize numeric scores, and hash records."""\n'
            f"    if not isinstance(records, list) or not records:\n"
            f"        return PipelineReport(ok=False, status='BLOCKED', total_rows=0, unique_rows=0, duplicate_rows=0, mean_score=0.0, digest_sha256='')\n"
            f"    seen: set[str] = set()\n"
            f"    canonical: list[str] = []\n"
            f"    scores: list[float] = []\n"
            f"    duplicates = 0\n"
            f"    for row in records:\n"
            f"        if not isinstance(row, dict):\n"
            f"            raise TypeError('Each record must be a dict')\n"
            f"        enc = json.dumps(row, sort_keys=True, ensure_ascii=False)\n"
            f"        if enc in seen:\n"
            f"            duplicates += 1\n"
            f"        else:\n"
            f"            seen.add(enc)\n"
            f"            canonical.append(enc)\n"
            f"        if 'score' in row and isinstance(row['score'], (int, float)):\n"
            f"            scores.append(float(row['score']))\n"
            f"    mean_score = round(sum(scores) / len(scores), 4) if scores else 0.0\n"
            f"    digest = hashlib.sha256('\\n'.join(canonical).encode('utf-8')).hexdigest()\n"
            f"    return PipelineReport(\n"
            f"        ok=True,\n"
            f"        status='VERIFIED',\n"
            f"        total_rows=len(records),\n"
            f"        unique_rows=len(canonical),\n"
            f"        duplicate_rows=duplicates,\n"
            f"        mean_score=mean_score,\n"
            f"        digest_sha256=digest,\n"
            f"    )\n"
        )
        cli_py = (
            f'"""CLI interface for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"import argparse\n"
            f"import json\n"
            f"from dataclasses import asdict\n\n"
            f"from .engine import run_pipeline\n\n\n"
            f"def main(argv: list[str] | None = None) -> int:\n"
            f"    parser = argparse.ArgumentParser(prog={pkg!r})\n"
            f"    parser.add_argument('--records-json', default='[]')\n"
            f"    args = parser.parse_args(argv)\n"
            f"    try:\n"
            f"        records = json.loads(args.records_json)\n"
            f"    except json.JSONDecodeError as exc:\n"
            f"        print(json.dumps({{'ok': False, 'error': str(exc)}}))\n"
            f"        return 2\n"
            f"    report = run_pipeline(records)\n"
            f"    print(json.dumps(asdict(report), ensure_ascii=False))\n"
            f"    return 0 if report.ok else 1\n"
        )
        test_py = (
            f"import json\n"
            f"import unittest\n"
            f"from {pkg}.cli import main\n"
            f"from {pkg}.engine import run_pipeline\n\n\n"
            f"class TestDataApp(unittest.TestCase):\n"
            f"    def test_dedup_and_stats(self) -> None:\n"
            f"        rep = run_pipeline([{{'id': 1, 'score': 10}}, {{'id': 1, 'score': 10}}, {{'id': 2, 'score': 20}}])\n"
            f"        self.assertTrue(rep.ok)\n"
            f"        self.assertEqual(rep.total_rows, 3)\n"
            f"        self.assertEqual(rep.unique_rows, 2)\n"
            f"        self.assertEqual(rep.duplicate_rows, 1)\n"
            f"        self.assertEqual(len(rep.digest_sha256), 64)\n\n"
            f"    def test_empty_blocked(self) -> None:\n"
            f"        rep = run_pipeline([])\n"
            f"        self.assertFalse(rep.ok)\n"
            f"        self.assertEqual(rep.status, 'BLOCKED')\n\n"
            f"    def test_cli_exit_codes(self) -> None:\n"
            f"        rc_ok = main(['--records-json', json.dumps([{{'id': 1, 'score': 5}}])])\n"
            f"        rc_empty = main(['--records-json', '[]'])\n"
            f"        self.assertEqual(rc_ok, 0)\n"
            f"        self.assertEqual(rc_empty, 1)\n"
        )
    elif chosen_bp == "python_service_app":
        models_py = (
            f'"""Service request/response models for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"from dataclasses import dataclass, field\n"
            f"from typing import Any\n\n\n"
            f"@dataclass(frozen=True)\n"
            f"class ServiceResponse:\n"
            f"    ok: bool\n"
            f"    status_code: int\n"
            f"    route: str\n"
            f"    data: dict[str, Any] = field(default_factory=dict)\n"
            f"    error: str = ''\n"
        )
        engine_py = (
            f'"""In-memory service router and contract validator for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"from typing import Any\n\n"
            f"from .models import ServiceResponse\n\n\n"
            f"class ServiceApp:\n"
            f"    def __init__(self) -> None:\n"
            f"        self._items: dict[str, dict[str, Any]] = {{}}\n\n"
            f"    def handle(self, method: str, path: str, body: dict[str, Any] | None = None) -> ServiceResponse:\n"
            f"        m = str(method or '').strip().upper()\n"
            f"        p = str(path or '').strip()\n"
            f"        payload = dict(body or {{}})\n"
            f"        if m == 'GET' and p == '/api/health':\n"
            f"            return ServiceResponse(ok=True, status_code=200, route=p, data={{'healthy': True, 'count': len(self._items)}})\n"
            f"        if m == 'GET' and p == '/api/items':\n"
            f"            return ServiceResponse(ok=True, status_code=200, route=p, data={{'items': list(self._items.values())}})\n"
            f"        if m == 'POST' and p == '/api/items':\n"
            f"            item_id = str(payload.get('id') or '').strip()\n"
            f"            title = str(payload.get('title') or '').strip()\n"
            f"            if not item_id or not title:\n"
            f"                return ServiceResponse(ok=False, status_code=400, route=p, error='id and title are required')\n"
            f"            record = {{'id': item_id, 'title': title, 'done': bool(payload.get('done', False))}}\n"
            f"            self._items[item_id] = record\n"
            f"            return ServiceResponse(ok=True, status_code=201, route=p, data={{'item': record}})\n"
            f"        return ServiceResponse(ok=False, status_code=404, route=p, error='Route not found')\n"
        )
        cli_py = (
            f'"""CLI runner for {pkg} service app."""\n\n'
            f"from __future__ import annotations\n\n"
            f"import argparse\n"
            f"import json\n"
            f"from dataclasses import asdict\n\n"
            f"from .engine import ServiceApp\n\n\n"
            f"def main(argv: list[str] | None = None) -> int:\n"
            f"    parser = argparse.ArgumentParser(prog={pkg!r})\n"
            f"    parser.add_argument('--method', default='GET')\n"
            f"    parser.add_argument('--path', default='/api/health')\n"
            f"    parser.add_argument('--body-json', default='{{}}')\n"
            f"    args = parser.parse_args(argv)\n"
            f"    app = ServiceApp()\n"
            f"    resp = app.handle(args.method, args.path, json.loads(args.body_json))\n"
            f"    print(json.dumps(asdict(resp), ensure_ascii=False))\n"
            f"    return 0 if resp.ok else 1\n"
        )
        test_py = (
            f"import unittest\n"
            f"from {pkg}.cli import main\n"
            f"from {pkg}.engine import ServiceApp\n\n\n"
            f"class TestServiceApp(unittest.TestCase):\n"
            f"    def test_create_and_list_items(self) -> None:\n"
            f"        app = ServiceApp()\n"
            f"        created = app.handle('POST', '/api/items', {{'id': 't1', 'title': 'Verify build'}})\n"
            f"        self.assertTrue(created.ok)\n"
            f"        self.assertEqual(created.status_code, 201)\n"
            f"        listed = app.handle('GET', '/api/items')\n"
            f"        self.assertEqual(len(listed.data['items']), 1)\n\n"
            f"    def test_validation_and_not_found(self) -> None:\n"
            f"        app = ServiceApp()\n"
            f"        bad = app.handle('POST', '/api/items', {{'id': 't1'}})\n"
            f"        self.assertFalse(bad.ok)\n"
            f"        self.assertEqual(bad.status_code, 400)\n"
            f"        missing = app.handle('GET', '/api/unknown')\n"
            f"        self.assertEqual(missing.status_code, 404)\n\n"
            f"    def test_cli_health(self) -> None:\n"
            f"        self.assertEqual(main(['--method', 'GET', '--path', '/api/health']), 0)\n"
        )
    else:
        models_py = (
            f'"""Task & workflow domain models for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"from dataclasses import dataclass, field\n"
            f"from typing import Any\n\n\n"
            f"@dataclass\n"
            f"class TaskItem:\n"
            f"    task_id: str\n"
            f"    title: str\n"
            f"    priority: int = 1\n"
            f"    completed: bool = False\n"
            f"    metadata: dict[str, Any] = field(default_factory=dict)\n"
        )
        engine_py = (
            f'"""Task manager state engine for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"from .models import TaskItem\n\n\n"
            f"class TaskRegistry:\n"
            f"    def __init__(self) -> None:\n"
            f"        self._tasks: dict[str, TaskItem] = {{}}\n\n"
            f"    def add_task(self, task_id: str, title: str, priority: int = 1) -> TaskItem:\n"
            f"        tid = str(task_id or '').strip()\n"
            f"        ttl = str(title or '').strip()\n"
            f"        if not tid or not ttl:\n"
            f"            raise ValueError('task_id and title must be non-empty')\n"
            f"        if tid in self._tasks:\n"
            f"            raise ValueError(f'Task {{tid!r}} already exists')\n"
            f"        item = TaskItem(task_id=tid, title=ttl, priority=max(1, min(5, int(priority))))\n"
            f"        self._tasks[tid] = item\n"
            f"        return item\n\n"
            f"    def complete_task(self, task_id: str) -> TaskItem:\n"
            f"        tid = str(task_id or '').strip()\n"
            f"        if tid not in self._tasks:\n"
            f"            raise KeyError(f'Unknown task {{tid!r}}')\n"
            f"        self._tasks[tid].completed = True\n"
            f"        return self._tasks[tid]\n\n"
            f"    def summary(self) -> dict[str, int]:\n"
            f"        total = len(self._tasks)\n"
            f"        done = sum(1 for t in self._tasks.values() if t.completed)\n"
            f"        return {{'total': total, 'completed': done, 'pending': total - done}}\n"
        )
        cli_py = (
            f'"""CLI interface for {pkg}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"import argparse\n"
            f"import json\n\n"
            f"from .engine import TaskRegistry\n\n\n"
            f"def main(argv: list[str] | None = None) -> int:\n"
            f"    parser = argparse.ArgumentParser(prog={pkg!r})\n"
            f"    parser.add_argument('--title', default='Verify workflow')\n"
            f"    parser.add_argument('--complete', action='store_true')\n"
            f"    args = parser.parse_args(argv)\n"
            f"    reg = TaskRegistry()\n"
            f"    reg.add_task('t1', args.title)\n"
            f"    if args.complete:\n"
            f"        reg.complete_task('t1')\n"
            f"    print(json.dumps({{'ok': True, 'summary': reg.summary()}}, ensure_ascii=False))\n"
            f"    return 0\n"
        )
        test_py = (
            f"import unittest\n"
            f"from {pkg}.cli import main\n"
            f"from {pkg}.engine import TaskRegistry\n\n\n"
            f"class TestCliApp(unittest.TestCase):\n"
            f"    def test_add_and_complete(self) -> None:\n"
            f"        reg = TaskRegistry()\n"
            f"        reg.add_task('a1', 'Build runner', priority=2)\n"
            f"        self.assertEqual(reg.summary()['pending'], 1)\n"
            f"        reg.complete_task('a1')\n"
            f"        self.assertEqual(reg.summary(), {{'total': 1, 'completed': 1, 'pending': 0}})\n\n"
            f"    def test_validation_guards(self) -> None:\n"
            f"        reg = TaskRegistry()\n"
            f"        with self.assertRaises(ValueError):\n"
            f"            reg.add_task('', 'Missing ID')\n"
            f"        with self.assertRaises(KeyError):\n"
            f"            reg.complete_task('missing')\n\n"
            f"    def test_cli_run(self) -> None:\n"
            f"        self.assertEqual(main(['--title', 'Ship v1', '--complete']), 0)\n"
        )

    init_py = (
        f'"""Package {pkg} generated by ZYRQUEN Multi-file App Builder."""\n\n'
        f"__version__ = '1.0.0'\n"
    )
    main_py = (
        f'"""Executable entrypoint for {pkg}."""\n\n'
        f"from {pkg}.cli import main\n\n"
        f"if __name__ == '__main__':\n"
        f"    raise SystemExit(main())\n"
    )

    files = {
        "manifest.json": json.dumps(manifest_obj, indent=2, ensure_ascii=False) + "\n",
        "README.md": readme_md,
        "main.py": main_py,
        f"{pkg}/__init__.py": init_py,
        f"{pkg}/models.py": models_py,
        f"{pkg}/engine.py": engine_py,
        f"{pkg}/cli.py": cli_py,
        "tests/__init__.py": f'"""Test suite package for {pkg}."""\n',
        "tests/test_app.py": test_py,
    }
    return chosen_bp, files


def build_and_verify_app(
    workspace_root: Path,
    *,
    goal: str,
    app_name: str = "zyrquen_app",
    blueprint: str = "auto",
    files: dict[str, str] | None = None,
    patches: dict[str, list[dict[str, Any]]] | None = None,
    delete_files: list[str] | None = None,
    mode: str = "upsert",
    auto_repair: bool = True,
    max_repair_rounds: int = 2,
    rollback_on_failure: bool = True,
) -> dict[str, Any]:
    """
    End-to-end Multi-File Persistent App Builder & Verifier:
      1. Inspects existing workspace files & saves pre-edit baseline snapshot if non-empty
      2. Prepares multi-file changes (`files` full specs, partial `patches`, `delete_files`, or blueprint synthesis)
      3. Applies changes atomically via `WorkspaceTransaction` with unified diffs
      4. Runs `run_real_project_build` (compileall + AST/policy lint + unittest)
      5. If tests fail and `auto_repair=True`, executes bounded Diagnose -> Patch -> Rebuild/Retest loop
      6. Saves verified snapshot in `.zyrquen_history/` ONLY if Build + Lint + Unit Tests pass;
         otherwise rolls back transaction cleanly when `rollback_on_failure=True` and reports FAILED!
    """
    started = time.perf_counter()
    res_mgr = get_resource_manager()
    admission = res_mgr.evaluate_admission(requested_workers=1)
    if not admission["allowed"]:
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": admission["reason"],
            "external_models_used": False,
        }

    ws = Path(workspace_root).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    stages: list[dict[str, Any]] = []

    existing_files = _list_project_files(ws)
    pre_snapshot_id: str | None = None
    if existing_files:
        ledger = _load_history_ledger(ws)
        if not ledger.get("snapshots"):
            pre_snap = _record_snapshot(
                ws,
                action="pre_edit_baseline",
                label="Baseline before multi-file edit",
                verified=False,
            )
            pre_snapshot_id = pre_snap["snapshot_id"]
        else:
            pre_snapshot_id = ledger["snapshots"][-1]["snapshot_id"]

    # 1. Plan & Resolve Multi-file Edits (files / patches / delete_files / blueprint)
    chosen_blueprint = blueprint
    planned_edits: dict[str, str] = {}
    planned_deletes: list[str] = []

    def _validate_rel(rel_raw: Any) -> str | None:
        clean = str(rel_raw or "").strip().lstrip("/")
        if (
            not clean
            or ".." in Path(clean).parts
            or any(part in IGNORED_WORKSPACE_PARTS for part in Path(clean).parts)
        ):
            return None
        return clean

    has_explicit_changes = bool(
        (isinstance(files, dict) and files)
        or (isinstance(patches, dict) and patches)
        or (isinstance(delete_files, list) and delete_files)
    )

    if isinstance(files, dict) and files:
        for rel_raw, content in files.items():
            clean_rel = _validate_rel(rel_raw)
            if clean_rel is None:
                return {
                    "ok": False,
                    "status": "BLOCKED",
                    "error": f"Forbidden workspace path '{rel_raw}'.",
                    "output": {},
                    "external_models_used": False,
                }
            planned_edits[clean_rel] = str(content)
        chosen_blueprint = "custom_multifile"

    if isinstance(patches, dict) and patches:
        for rel_raw, rep_list in patches.items():
            clean_rel = _validate_rel(rel_raw)
            if clean_rel is None:
                return {
                    "ok": False,
                    "status": "BLOCKED",
                    "error": f"Forbidden workspace path '{rel_raw}'.",
                    "output": {},
                    "external_models_used": False,
                }
            if not isinstance(rep_list, list) or not rep_list:
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": f"Patch entries for '{clean_rel}' must be a non-empty list.",
                    "output": {},
                    "external_models_used": False,
                }
            if clean_rel in planned_edits:
                current_text = planned_edits[clean_rel]
            else:
                target_p = _safe_confined_path(ws, clean_rel)
                if target_p is None or not target_p.is_file():
                    return {
                        "ok": False,
                        "status": "FAILED",
                        "error": f"Cannot apply patch to missing file '{clean_rel}'.",
                        "output": {},
                        "external_models_used": False,
                    }
                current_text = target_p.read_text(encoding="utf-8", errors="replace")
            for rep in rep_list:
                if not isinstance(rep, dict) or not isinstance(rep.get("old"), str) or not isinstance(rep.get("new"), str):
                    return {
                        "ok": False,
                        "status": "FAILED",
                        "error": f"Invalid patch replacement item for '{clean_rel}'.",
                        "output": {},
                        "external_models_used": False,
                    }
                old_snippet = rep["old"]
                if not old_snippet or old_snippet not in current_text:
                    return {
                        "ok": False,
                        "status": "FAILED",
                        "error": f"Patch target snippet not found in '{clean_rel}'.",
                        "output": {},
                        "external_models_used": False,
                    }
                current_text = current_text.replace(old_snippet, rep["new"], 1)
            planned_edits[clean_rel] = current_text
        if chosen_blueprint == blueprint:
            chosen_blueprint = "incremental_patch"

    if isinstance(delete_files, list) and delete_files:
        for rel_raw in delete_files:
            clean_rel = _validate_rel(rel_raw)
            if clean_rel is None:
                return {
                    "ok": False,
                    "status": "BLOCKED",
                    "error": f"Forbidden workspace path '{rel_raw}'.",
                    "output": {},
                    "external_models_used": False,
                }
            if clean_rel in planned_edits:
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": f"File '{clean_rel}' cannot be both edited and deleted in one operation.",
                    "output": {},
                    "external_models_used": False,
                }
            target_del = _safe_confined_path(ws, clean_rel)
            if target_del is not None and target_del.is_file() and clean_rel not in planned_deletes:
                planned_deletes.append(clean_rel)
        if chosen_blueprint == blueprint:
            chosen_blueprint = "incremental_patch"

    if not has_explicit_changes:
        chosen_blueprint, planned_edits = synthesize_multifile_app_files(
            app_name=app_name,
            goal=goal,
            blueprint=blueprint,
        )

    stages.append({
        "stage": "plan_multifile",
        "status": "COMPLETED",
        "blueprint": chosen_blueprint,
        "planned_files": sorted(planned_edits.keys()),
        "planned_deletes": sorted(planned_deletes),
        "existing_files": existing_files,
    })

    # If mode == "replace" or delete_files specified, remove target files inside atomic transaction
    tx = WorkspaceTransaction(ws)
    to_remove: list[str] = list(planned_deletes)
    if str(mode or "upsert").strip().lower() == "replace" and existing_files:
        for old_rel in existing_files:
            if old_rel not in planned_edits and old_rel not in to_remove:
                to_remove.append(old_rel)

    for old_rel in to_remove:
        target_old = _safe_confined_path(ws, old_rel)
        if target_old and target_old.is_file():
            tx._snapshots[old_rel] = target_old.read_bytes()
            tx.diffs[old_rel] = compute_unified_diff(old_rel, target_old.read_text(encoding="utf-8", errors="replace"), "")
            target_old.unlink()
            if old_rel not in tx.changed_files:
                tx.changed_files.append(old_rel)

    # 2. Apply Multi-file Transaction
    if planned_edits:
        apply_res = tx.apply_edits(planned_edits)
        if not apply_res.get("ok"):
            return {
                "ok": False,
                "status": apply_res.get("status", "FAILED"),
                "error": apply_res.get("error"),
                "output": {
                    "workspace": ws.name,
                    "verified": False,
                    "build_passed": False,
                    "lint_passed": False,
                    "tests_passed": False,
                    "tests_run": 0,
                    "files": _list_project_files(ws),
                    "snapshot_id": pre_snapshot_id,
                },
                "external_models_used": False,
            }
    elif not tx.changed_files:
        return {
            "ok": False,
            "status": "FAILED",
            "error": "No file edits, patches, or deletions took effect.",
            "output": {
                "workspace": ws.name,
                "verified": False,
                "build_passed": False,
                "lint_passed": False,
                "tests_passed": False,
                "tests_run": 0,
                "files": _list_project_files(ws),
                "snapshot_id": pre_snapshot_id,
            },
            "external_models_used": False,
        }
    stages.append({
        "stage": "apply_multifile_edits",
        "status": "COMPLETED",
        "transaction_id": tx.transaction_id,
        "changed_files": list(tx.changed_files),
    })

    # 3. Initial Real Build, Lint & Unit Test Run
    build_run = run_real_project_build(ws, run_lint=True, run_tests=True)
    build_out = build_run["output"]
    stages.append({
        "stage": "initial_real_build_and_test",
        "status": "PASS" if build_out["verified"] else "FAILED",
        "build_passed": build_out["build_passed"],
        "lint_passed": build_out["lint_passed"],
        "tests_passed": build_out["tests_passed"],
        "tests_run": build_out["tests_run"],
    })

    # 4. Bounded Autonomous Repair Loop (for SyntaxError / ZeroDivision / Arithmetic defects)
    repair_rounds_used = 0
    bounded_rounds = max(0, min(3, int(max_repair_rounds))) if auto_repair else 0
    if not build_out["verified"] and bounded_rounds > 0:
        for round_idx in range(1, bounded_rounds + 1):
            repair_rounds_used = round_idx
            err_parts = [
                str((build_out.get("build_evidence") or {}).get("stderr") or ""),
                str((build_out.get("test_evidence") or {}).get("stderr") or ""),
            ]
            for iss in (build_out.get("lint_evidence") or {}).get("issues") or []:
                err_parts.append(str(iss.get("detail") or ""))
            combined_err = "\n".join(p for p in err_parts if p.strip())
            diag = _diagnose_failure(combined_err, ws)
            stages.append({
                "stage": f"diagnose_round_{round_idx}",
                "status": "COMPLETED",
                "root_cause": diag.get("root_cause"),
                "repairable": diag.get("repairable"),
                "detail": diag.get("detail"),
            })
            if not diag.get("repairable") or not diag.get("patch"):
                break
            patch_res = tx.apply_edits(diag["patch"])
            if not patch_res.get("ok"):
                stages.append({
                    "stage": f"repair_round_{round_idx}",
                    "status": "BLOCKED",
                    "detail": patch_res.get("error"),
                })
                break
            stages.append({
                "stage": f"repair_round_{round_idx}",
                "status": "COMPLETED",
                "changed_files": patch_res["changed_files"],
            })
            build_run = run_real_project_build(ws, run_lint=True, run_tests=True)
            build_out = build_run["output"]
            stages.append({
                "stage": f"rebuild_retest_round_{round_idx}",
                "status": "PASS" if build_out["verified"] else "FAILED",
                "build_passed": build_out["build_passed"],
                "lint_passed": build_out["lint_passed"],
                "tests_passed": build_out["tests_passed"],
                "tests_run": build_out["tests_run"],
            })
            if build_out["verified"]:
                break

    verified = bool(build_out.get("verified"))
    rolled_back = False
    rollback_summary: dict[str, Any] | None = None
    snapshot_id = pre_snapshot_id

    if verified:
        snap_entry = _record_snapshot(
            ws,
            action="verified_build",
            label=goal[:140] or chosen_blueprint,
            verified=True,
            build_passed=build_out["build_passed"],
            lint_passed=build_out["lint_passed"],
            tests_passed=build_out["tests_passed"],
            tests_run=build_out["tests_run"],
            changed_files=list(tx.changed_files),
            diffs=dict(tx.diffs),
        )
        snapshot_id = snap_entry["snapshot_id"]
        stages.append({
            "stage": "persist_verified_snapshot",
            "status": "COMPLETED",
            "snapshot_id": snapshot_id,
        })
    elif rollback_on_failure:
        rollback_summary = tx.rollback()
        rolled_back = True
        stages.append({
            "stage": "rollback_on_failure",
            "status": "COMPLETED",
            "detail": (
                f"Rolled back failed edits ({len(rollback_summary['restored_files'])} restored, "
                f"{len(rollback_summary['removed_files'])} removed)."
            ),
        })

    total_ms = round((time.perf_counter() - started) * 1000, 2)
    final_files = _list_project_files(ws)
    return {
        "ok": verified,
        "status": "COMPLETED" if verified else "FAILED",
        "error": None if verified else (build_run.get("error") or "Real build/lint/test verification failed."),
        "output": {
            "workspace": ws.name,
            "blueprint": chosen_blueprint,
            "verified": verified,
            "build_passed": bool(build_out["build_passed"]),
            "lint_passed": bool(build_out["lint_passed"]),
            "tests_passed": bool(build_out["tests_passed"]),
            "tests_run": int(build_out["tests_run"]),
            "files": final_files,
            "file_count": len(final_files),
            "changed_files": [] if rolled_back else list(tx.changed_files),
            "diffs": {} if rolled_back else dict(tx.diffs),
            "repair_rounds_used": repair_rounds_used,
            "rolled_back": rolled_back,
            "rollback_summary": rollback_summary,
            "snapshot_id": snapshot_id,
            "build_evidence": build_out["build_evidence"],
            "lint_evidence": build_out["lint_evidence"],
            "test_evidence": build_out["test_evidence"],
            "stages": stages,
            "duration_ms": total_ms,
        },
        "summary": (
            f"สร้างและตรวจสอบแอปหลายไฟล์ '{ws.name}' สำเร็จ (build=PASS, lint=PASS, tests={build_out['tests_run']} PASS, snapshot={snapshot_id})"
            if verified
            else f"ไม่สามารถรับรองแอป '{ws.name}' ได้ (build={build_out['build_passed']}, lint={build_out['lint_passed']}, tests={build_out['tests_passed']}, rolled_back={rolled_back})"
        ),
        "external_models_used": False,
    }
