"""
End-to-End Tests for ZYRQUEN Multi-File Persistent App Builder & Real Build Runner.
-----------------------------------------------------------------------------------
Covers every stage of the required engineering pipeline:
  1. Multi-file project synthesis & creation + Real Build (compileall) + Lint + Unit Tests -> VERIFIED
  2. Iterative multi-file edit with automated Diagnose -> Patch -> Rebuild/Retest repair loop -> VERIFIED + unified diff
  3. Unrepairable broken regression patch -> Real Build Runner fails honestly, NEVER reports VERIFIED, rolls back cleanly
  4. Persistent workspace history, unified diffs across snapshots, manual rollback, and external-LLM policy blocking
  5. QA Guard enforcement (verify_capability_delivery rejects unverified/untested build outputs)
  6. Autonomous chat multi-file app command (`_try_execute_chat_autonomous_goal`) end-to-end
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PYTHON_CORE_DIR = TESTS_DIR.parent
REPO_ROOT = PYTHON_CORE_DIR.parent
for _p in (str(REPO_ROOT), str(PYTHON_CORE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import zyrquen_core as zc  # noqa: E402
from tool_center import (  # noqa: E402
    build_and_verify_app,
    get_tool_center_registry,
    init_tool_center_schema,
    manage_workspace_history,
    run_real_project_build,
    verify_capability_delivery,
)


class AppBuilderAndBuildRunnerE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="zyrquen_app_e2e_")
        self.data_dir = Path(self._tmp.name)
        self.db_path = self.data_dir / "test_app_builder.db"
        self._prev_data_dir = os.environ.get("ZYRQUEN_DATA_DIR")
        os.environ["ZYRQUEN_DATA_DIR"] = str(self.data_dir)
        zc.DATA_DIR = self.data_dir
        zc.CHECKPOINT_DIR = self.data_dir / "checkpoints"
        zc.DB_PATH = self.db_path
        zc.init_db()
        self.conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        self.conn.row_factory = sqlite3.Row
        init_tool_center_schema(self.conn)
        self.registry = get_tool_center_registry()

    def tearDown(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        if self._prev_data_dir is None:
            os.environ.pop("ZYRQUEN_DATA_DIR", None)
        else:
            os.environ["ZYRQUEN_DATA_DIR"] = self._prev_data_dir
        self._tmp.cleanup()

    def test_1_build_multifile_app_from_scratch_and_verify_build_lint_test(self) -> None:
        res = self.registry.execute(
            "development.app_builder",
            {
                "workspace": "inventory_cli",
                "goal": "Create CLI app for task inventory management",
                "app_name": "inv_cli",
                "blueprint": "python_cli_app",
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["qa"]["verdict"], "SUCCESS")
        out = res["output"]
        self.assertTrue(out["verified"])
        self.assertTrue(out["build_passed"])
        self.assertTrue(out["lint_passed"])
        self.assertTrue(out["tests_passed"])
        self.assertGreaterEqual(out["tests_run"], 3)
        self.assertIn("main.py", out["files"])
        self.assertIn("manifest.json", out["files"])
        self.assertIn("inv_cli/engine.py", out["files"])
        self.assertIn("tests/test_app.py", out["files"])
        self.assertTrue(out["snapshot_id"])

        # Independent Real Build Runner execution on persisted workspace
        runner = self.registry.execute(
            "development.real_build_runner",
            {"workspace": "inventory_cli", "run_lint": True, "run_tests": True},
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(runner["ok"], runner)
        self.assertEqual(runner["qa"]["verdict"], "SUCCESS")
        self.assertTrue(runner["output"]["verified"])
        self.assertEqual(runner["output"]["build_evidence"]["returncode"], 0)

    def test_2_multifile_buggy_patch_triggers_repair_loop_and_unified_diff(self) -> None:
        ws = self.data_dir / "sandbox_workspaces" / "finance_pkg"
        initial = build_and_verify_app(
            ws,
            goal="Create initial multi-file finance calculator package",
            files={
                "pkg/__init__.py": "from .math_ops import divide, mean_score\n__all__ = ['divide', 'mean_score']\n",
                "pkg/math_ops.py": (
                    "def divide(total, count):\n"
                    "    return total / count\n\n"
                    "def mean_score(values):\n"
                    "    if not values:\n"
                    "        return 0.0\n"
                    "    return sum(values) / len(values)\n"
                ),
                "tests/__init__.py": "",
                "tests/test_pkg.py": (
                    "import unittest\n"
                    "from pkg.math_ops import divide, mean_score\n\n"
                    "class TestFinance(unittest.TestCase):\n"
                    "    def test_divide(self):\n"
                    "        self.assertEqual(divide(10, 2), 5.0)\n"
                    "    def test_mean(self):\n"
                    "        self.assertEqual(mean_score([10, 20]), 15.0)\n"
                ),
            },
        )
        self.assertTrue(initial["ok"], initial)
        snap1 = initial["output"]["snapshot_id"]

        # Follow-up buggy multi-file edit (SyntaxError + ZeroDivisionError case added in test)
        repaired = build_and_verify_app(
            ws,
            goal="Add empty list test and fix divide zero-guard + syntax defect",
            files={
                "pkg/math_ops.py": (
                    "def divide(total, count)\n"
                    "    return total / count\n\n"
                    "def mean_score(values):\n"
                    "    return sum(values) / len(values)\n"
                ),
                "tests/test_pkg.py": (
                    "import unittest\n"
                    "from pkg.math_ops import divide, mean_score\n\n"
                    "class TestFinance(unittest.TestCase):\n"
                    "    def test_divide(self):\n"
                    "        self.assertEqual(divide(10, 2), 5.0)\n"
                    "    def test_empty_mean(self):\n"
                    "        self.assertEqual(mean_score([]), 0.0)\n"
                ),
            },
            auto_repair=True,
            max_repair_rounds=3,
        )
        self.assertTrue(repaired["ok"], repaired)
        self.assertTrue(repaired["output"]["verified"])
        self.assertGreaterEqual(repaired["output"]["repair_rounds_used"], 1)
        self.assertIn("pkg/math_ops.py", repaired["output"]["diffs"])
        snap2 = repaired["output"]["snapshot_id"]
        self.assertNotEqual(snap1, snap2)

        # Verify unified diff between snap1 and snap2
        diff_res = manage_workspace_history(
            ws,
            action="diff",
            base_snapshot_id=snap1,
            snapshot_id=snap2,
        )
        self.assertTrue(diff_res["ok"])
        self.assertIn("pkg/math_ops.py", diff_res["output"]["changed_files"])

    def test_3_unrepairable_regression_fails_honestly_and_rolls_back_cleanly(self) -> None:
        ws = self.data_dir / "sandbox_workspaces" / "rollback_app"
        v1 = build_and_verify_app(
            ws,
            goal="Build clean v1 service app",
            app_name="svc_v1",
            blueprint="python_service_app",
        )
        self.assertTrue(v1["ok"], v1)
        snap_v1 = v1["output"]["snapshot_id"]
        original_engine = (ws / "svc_v1" / "engine.py").read_text(encoding="utf-8")

        # Inject unrepairable breaking change + new stale file
        v2_broken = self.registry.execute(
            "development.app_builder",
            {
                "workspace": "rollback_app",
                "goal": "Break service router cleanly",
                "files": {
                    "svc_v1/engine.py": (
                        "class ServiceApp:\n"
                        "    def handle(self, method, path, body=None):\n"
                        "        raise RuntimeError('broken regression')\n"
                    ),
                    "stale_temp.py": "VALUE = 999\n",
                },
                "auto_repair": True,
                "max_repair_rounds": 1,
                "rollback_on_failure": True,
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertFalse(v2_broken["ok"])
        self.assertEqual(v2_broken["qa"]["verdict"], "FAILED")
        self.assertFalse(v2_broken["output"]["verified"])
        self.assertFalse(v2_broken["output"]["tests_passed"])
        self.assertTrue(v2_broken["output"]["rolled_back"])
        # Confirm working v1 code intact and stale_temp.py removed
        self.assertEqual((ws / "svc_v1" / "engine.py").read_text(encoding="utf-8"), original_engine)
        self.assertFalse((ws / "stale_temp.py").exists())

        # Now apply a valid v2 edit, snapshot it, then manually roll back to v1 snapshot
        v2_ok = build_and_verify_app(
            ws,
            goal="Add extra helper module",
            files={"svc_v1/helper.py": "def ping():\n    return 'pong'\n"},
        )
        self.assertTrue(v2_ok["ok"], v2_ok)
        self.assertTrue((ws / "svc_v1" / "helper.py").is_file())

        rb_res = self.registry.execute(
            "development.workspace_history",
            {"workspace": "rollback_app", "action": "rollback", "snapshot_id": snap_v1},
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(rb_res["ok"], rb_res)
        self.assertFalse((ws / "svc_v1" / "helper.py").exists())
        post_rb_build = run_real_project_build(ws)
        self.assertTrue(post_rb_build["ok"], post_rb_build)

    def test_4_policy_blocks_external_llm_and_qa_rejects_untested_build(self) -> None:
        ws = self.data_dir / "sandbox_workspaces" / "blocked_app"
        res_llm = build_and_verify_app(
            ws,
            goal="Attempt forbidden external LLM import",
            files={
                "app.py": "from openai import OpenAI\ndef run():\n    return OpenAI()\n",
                "test_app.py": "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
            },
            rollback_on_failure=True,
        )
        self.assertFalse(res_llm["ok"])
        self.assertFalse(res_llm["output"]["lint_passed"])
        self.assertFalse(res_llm["output"]["verified"])
        self.assertFalse((ws / "app.py").exists())

        # QA verify_capability_delivery MUST reject any fake VERIFIED claim if build/test flags fail
        app_spec = self.registry.get_capability("development.app_builder").spec
        fake_claim = {
            "ok": True,
            "status": "COMPLETED",
            "external_models_used": False,
            "output": {
                "workspace": "blocked_app",
                "verified": True,
                "build_passed": True,
                "lint_passed": True,
                "tests_passed": False,
                "tests_run": 0,
                "files": ["nonexistent.py"],
                "snapshot_id": None,
            },
        }
        qa = verify_capability_delivery(app_spec, fake_claim, data_dir=self.data_dir)
        self.assertFalse(qa["passed"])
        self.assertEqual(qa["verdict"], "FAILED")

    def test_5_chat_autonomous_multifile_app_builder_e2e(self) -> None:
        goal_res = zc._try_execute_chat_autonomous_goal(
            self.conn,
            "สร้างแอปพลิเคชัน CLI จัดการข้อมูลและคำนวณสถิติหลายไฟล์",
            user_id="u-builder",
        )
        self.assertIsNotNone(goal_res)
        assert goal_res is not None
        self.assertEqual(goal_res["status"], "VERIFIED", goal_res)
        deliv = goal_res["deliverable"]
        self.assertEqual(deliv["kind"], "multi_file_app")
        self.assertTrue(deliv["verified"])
        self.assertTrue(deliv["build_passed"])
        self.assertTrue(deliv["lint_passed"])
        self.assertTrue(deliv["tests_passed"])
        self.assertGreaterEqual(deliv["tests_run"], 3)
        self.assertGreaterEqual(len(deliv["files"]), 6)
        self.assertIn("development.app_builder", goal_res["orchestration"]["capabilities_executed"])
        self.assertIn("development.real_build_runner", goal_res["orchestration"]["capabilities_executed"])

    def test_6_incremental_patches_delete_files_and_regression_rollback(self) -> None:
        ws_name = "patch_delete_ws"
        init_res = self.registry.execute(
            "development.app_builder",
            {
                "workspace": ws_name,
                "goal": "Create initial multi-file package with extra obsolete file",
                "files": {
                    "calc/__init__.py": "",
                    "calc/ops.py": "def scale(x, factor=2):\n    return x * factor\n",
                    "obsolete.txt": "remove me safely",
                    "tests/__init__.py": "",
                    "tests/test_ops.py": (
                        "import unittest\n"
                        "from calc.ops import scale\n\n"
                        "class TestOps(unittest.TestCase):\n"
                        "    def test_scale(self):\n"
                        "        self.assertEqual(scale(4), 8)\n"
                    ),
                },
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(init_res["ok"], init_res)
        ws = self.data_dir / "sandbox_workspaces" / ws_name
        self.assertTrue((ws / "obsolete.txt").is_file())

        # Partial multi-file patches + safe delete_files
        patched = self.registry.execute(
            "development.app_builder",
            {
                "workspace": ws_name,
                "goal": "Update default factor to 3 via patches and remove obsolete.txt",
                "patches": {
                    "calc/ops.py": [{"old": "factor=2", "new": "factor=3"}],
                    "tests/test_ops.py": [{"old": "scale(4), 8", "new": "scale(4), 12"}],
                },
                "delete_files": ["obsolete.txt"],
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(patched["ok"], patched)
        self.assertTrue(patched["output"]["verified"])
        self.assertFalse((ws / "obsolete.txt").exists())
        self.assertIn("calc/ops.py", patched["output"]["diffs"])
        self.assertIn("obsolete.txt", patched["output"]["diffs"])

        # Deleting critical module file fails tests -> rollback MUST restore calc/ops.py
        bad_delete = self.registry.execute(
            "development.app_builder",
            {
                "workspace": ws_name,
                "goal": "Delete critical ops module",
                "delete_files": ["calc/ops.py"],
                "auto_repair": False,
                "rollback_on_failure": True,
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertFalse(bad_delete["ok"])
        self.assertTrue(bad_delete["output"]["rolled_back"])
        self.assertTrue((ws / "calc" / "ops.py").is_file())

    def test_7_repair_loop_recovers_syntax_and_stdlib_import(self) -> None:
        ws = self.data_dir / "sandbox_workspaces" / "auto_import_ws"
        repaired = build_and_verify_app(
            ws,
            goal="Recover missing colon syntax error and missing math import across repair rounds",
            files={
                "pkg/__init__.py": "",
                "pkg/geo.py": (
                    '"""Geometry helpers."""\n\n'
                    "def hypotenuse(a: float, b: float) -> float\n"
                    "    return round(math.sqrt(a * a + b * b), 4)\n"
                ),
                "tests/__init__.py": "",
                "tests/test_geo.py": (
                    "import unittest\n"
                    "from pkg.geo import hypotenuse\n\n"
                    "class TestGeo(unittest.TestCase):\n"
                    "    def test_hypotenuse(self):\n"
                    "        self.assertEqual(hypotenuse(3, 4), 5.0)\n"
                ),
            },
            auto_repair=True,
            max_repair_rounds=3,
        )
        self.assertTrue(repaired["ok"], repaired)
        self.assertTrue(repaired["output"]["verified"])
        self.assertEqual(repaired["output"]["repair_rounds_used"], 2)
        geo_src = (ws / "pkg" / "geo.py").read_text(encoding="utf-8")
        self.assertIn("def hypotenuse(a: float, b: float) -> float:", geo_src)
        self.assertIn("import math", geo_src)

    def test_8_workspace_history_read_file_and_confinement(self) -> None:
        ws_name = "history_read_ws"
        created = self.registry.execute(
            "development.app_builder",
            {
                "workspace": ws_name,
                "goal": "Create app to inspect persisted files",
                "app_name": "hist_app",
                "blueprint": "python_cli_app",
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(created["ok"], created)
        snap_id = created["output"]["snapshot_id"]

        read_wt = self.registry.execute(
            "development.workspace_history",
            {"workspace": ws_name, "action": "read_file", "file_path": "manifest.json"},
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(read_wt["ok"], read_wt)
        self.assertEqual(read_wt["output"]["source"], "working_tree")
        self.assertIn("hist_app", read_wt["output"]["content"])

        read_snap = self.registry.execute(
            "development.workspace_history",
            {
                "workspace": ws_name,
                "action": "read_file",
                "snapshot_id": snap_id,
                "file_path": "hist_app/engine.py",
            },
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertTrue(read_snap["ok"], read_snap)
        self.assertEqual(read_snap["output"]["source"], snap_id)
        self.assertIn("TaskRegistry", read_snap["output"]["content"])

        blocked_history = self.registry.execute(
            "development.workspace_history",
            {"workspace": ws_name, "action": "read_file", "file_path": ".zyrquen_history/history.json"},
            user_role="user",
            conn=self.conn,
            data_dir=self.data_dir,
        )
        self.assertFalse(blocked_history["ok"])
        self.assertEqual(blocked_history["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
