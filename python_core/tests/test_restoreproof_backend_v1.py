from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from restoreproof_backend.models import RunRecord, StepRecord, utc_now_iso  # noqa: E402
from restoreproof_backend.pg_verifier import compute_sha256  # noqa: E402
from restoreproof_backend.server import create_server  # noqa: E402
from restoreproof_backend.store import EvidenceStore  # noqa: E402


def _http_json(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw), dict(resp.headers.items())
    except HTTPError as err:
        raw = err.read().decode("utf-8")
        return err.code, json.loads(raw), dict(err.headers.items())


def _write_executable(path: Path, script: str) -> None:
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class TestRestoreProofBackendV1(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="rp_backend_test_"))
        self.data_dir = self.tmp_root / "data"
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            data_dir=self.data_dir,
            pg_host="127.0.0.1",
            pg_port=15432,
            pg_user="restoreproof_user",
        )
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.orig_path = os.environ.get("PATH", "")

    def tearDown(self) -> None:
        os.environ["PATH"] = self.orig_path
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _wait_terminal(self, run_id: str, timeout_sec: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            code, data, _ = _http_json(f"{self.base_url}/v1/runs/{run_id}")
            if code == 200 and data["status"] != "RUNNING":
                return data
            time.sleep(0.05)
        self.fail(f"Run {run_id} did not finish within {timeout_sec}s")
        return {}

    def test_health_and_validation_and_blocked_when_missing_file_or_reserved_db(self) -> None:
        code, health, _ = _http_json(f"{self.base_url}/v1/health")
        self.assertEqual(code, 200)
        self.assertEqual(health["service"], "realitycheck-restoreproof-backend")
        self.assertEqual(health["version"], "1.0.0")
        self.assertIn("isolated_worker_ready", health)

        # 422 on missing backup_uri
        code_422, err_422, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={"source_name": "Orders"},
        )
        self.assertEqual(code_422, 422)
        self.assertEqual(err_422["error"], "validation_error")

        # BLOCKED when dump file does not exist
        code_202, job, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "source_name": "Missing Dump",
                "backup_format": "postgresql_custom",
                "backup_uri": str(self.tmp_root / "missing.dump"),
                "min_total_rows": 10,
                "target_isolation": {"mode": "isolated_db", "target_dbname": "rp_verify_missing"},
            },
        )
        self.assertEqual(code_202, 202)
        run_data = self._wait_terminal(job["run_id"])
        self.assertEqual(run_data["status"], "BLOCKED")

        # BLOCKED when reserved production DB name is supplied
        dump_file = self.tmp_root / "orders.dump"
        dump_file.write_bytes(b"PGDMP_TEST")
        code_202_res, job_res, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "source_name": "Reserved DB Guard",
                "backup_format": "postgresql_custom",
                "backup_uri": str(dump_file),
                "target_isolation": {"mode": "isolated_db", "target_dbname": "postgres"},
            },
        )
        self.assertEqual(code_202_res, 202)
        res_run = self._wait_terminal(job_res["run_id"])
        self.assertEqual(res_run["status"], "BLOCKED")
        self.assertTrue(any("reserved" in d.lower() for d in res_run["discrepancies"]))

    def test_sha256_mismatch_returns_fail_and_incomplete_report_returns_409_while_running(self) -> None:
        # Assert explicit 409 Conflict when report is queried while run is RUNNING
        active_store = EvidenceStore(self.data_dir)
        active_run = RunRecord(
            run_id="run_active_409_check",
            source_name="Active PG Job",
            backup_format="postgresql_custom",
            backup_uri="/tmp/nonexistent_active.dump",
            target_dbname="rp_verify_active",
            min_total_rows=1,
            required_tables=[],
            expected_sha256=None,
            status="RUNNING",
            started_at=utc_now_iso(),
            steps=[StepRecord("isolated_pg_restore", "RUNNING", None, "Restoring...")],
        )
        active_store.save(active_run)
        # Re-open or hit running endpoint via a fresh server bound to same data_dir
        srv2 = create_server("127.0.0.1", 0, self.data_dir)
        t2 = threading.Thread(target=srv2.serve_forever, daemon=True)
        t2.start()
        try:
            p2 = srv2.server_address[1]
            c_409, b_409, _ = _http_json(f"http://127.0.0.1:{p2}/v1/reports/run_active_409_check")
            self.assertEqual(c_409, 409)
            self.assertEqual(b_409["error"], "evidence_not_ready")
            ce_409, _, _ = _http_json(f"http://127.0.0.1:{p2}/v1/reports/run_active_409_check/export")
            self.assertEqual(ce_409, 409)
        finally:
            srv2.shutdown()
            srv2.server_close()

        dump_file = self.tmp_root / "orders_bad_sha.dump"
        dump_file.write_bytes(b"PGDMP_CORRUPT")

        code_202, job, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "source_name": "Orders SHA Mismatch",
                "backup_format": "postgresql_custom",
                "backup_uri": str(dump_file),
                "expected_sha256": "0" * 64,
                "target_isolation": {"mode": "isolated_db", "target_dbname": "rp_verify_sha_fail"},
            },
        )
        self.assertEqual(code_202, 202)
        run_data = self._wait_terminal(job["run_id"])
        self.assertEqual(run_data["status"], "FAIL")

        rep_code, rep, _ = _http_json(f"{self.base_url}/v1/reports/{job['run_id']}")
        self.assertEqual(rep_code, 200)
        self.assertEqual(rep["verdict"], "FAIL")
        self.assertFalse(rep["backup_artifact"]["sha256_matched"])
        self.assertTrue(rep["evidence_complete"])

    def test_isolated_pg_restore_pass_fail_export_and_persistence(self) -> None:
        # Install temporary pg_restore and psql CLI executables in isolated PATH dir
        # solely to verify subprocess invocation, isolated DB create/drop, and HTTP evidence output.
        bin_dir = self.tmp_root / "bin"
        bin_dir.mkdir()
        pg_log = self.tmp_root / "pg_invocations.log"

        _write_executable(
            bin_dir / "pg_restore",
            f"""#!{sys.executable}
import sys
with open({str(pg_log)!r}, "a", encoding="utf-8") as f:
    f.write("pg_restore " + " ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
""",
        )
        _write_executable(
            bin_dir / "psql",
            f"""#!{sys.executable}
import sys
args = sys.argv[1:]
with open({str(pg_log)!r}, "a", encoding="utf-8") as f:
    f.write("psql " + " ".join(args) + "\\n")
q = args[args.index("-c") + 1] if "-c" in args else ""
if "information_schema.tables" in q:
    print("public.orders")
    print("public.order_items")
elif 'COUNT(*)' in q and '"orders"' in q:
    print("35")
elif 'COUNT(*)' in q and '"order_items"' in q:
    print("7")
sys.exit(0)
""",
        )
        os.environ["PATH"] = f"{bin_dir}:{self.orig_path}"

        code_h, health, _ = _http_json(f"{self.base_url}/v1/health")
        self.assertEqual(code_h, 200)
        self.assertTrue(health["isolated_worker_ready"])

        dump_file = self.tmp_root / "orders_20261126.dump"
        dump_file.write_bytes(b"PGDMP_CUSTOM_PAYLOAD_V1")
        sha = compute_sha256(dump_file)

        # Case A: 35 + 7 = 42 rows, min_total_rows=100 -> FAIL
        _, job_fail, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "source_name": "Orders Low Rows",
                "backup_format": "postgresql_custom",
                "backup_uri": str(dump_file),
                "expected_sha256": sha,
                "min_total_rows": 100,
                "required_tables": ["public.orders", "public.order_items"],
                "target_isolation": {"mode": "isolated_db", "target_dbname": "rp_verify_orders_low"},
            },
        )
        res_fail = self._wait_terminal(job_fail["run_id"])
        self.assertEqual(res_fail["status"], "FAIL")

        rep_code, rep_fail, _ = _http_json(f"{self.base_url}/v1/reports/{job_fail['run_id']}")
        self.assertEqual(rep_code, 200)
        self.assertEqual(rep_fail["verdict"], "FAIL")
        self.assertEqual(rep_fail["restore_evidence"]["total_rows_observed"], 42)
        self.assertEqual(rep_fail["restore_evidence"]["pg_restore_exit_code"], 0)
        self.assertTrue(any("42" in d for d in rep_fail["discrepancies"]))

        # Case B: min_total_rows=40 -> PASS + export
        _, job_pass, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "source_name": "Orders Healthy",
                "backup_format": "postgresql_custom",
                "backup_uri": str(dump_file),
                "expected_sha256": sha,
                "min_total_rows": 40,
                "required_tables": ["public.orders", "public.order_items"],
                "target_isolation": {"mode": "isolated_db", "target_dbname": "rp_verify_orders_ok"},
            },
        )
        res_pass = self._wait_terminal(job_pass["run_id"])
        self.assertEqual(res_pass["status"], "PASS")

        exp_code, exp_body, exp_headers = _http_json(
            f"{self.base_url}/v1/reports/{job_pass['run_id']}/export"
        )
        self.assertEqual(exp_code, 200)
        self.assertEqual(exp_body["verdict"], "PASS")
        self.assertIn("attachment; filename=", exp_headers.get("Content-Disposition", ""))

        # Verify isolated DB lifecycle executed CREATE DATABASE and DROP DATABASE
        log_text = pg_log.read_text(encoding="utf-8")
        self.assertIn('CREATE DATABASE "rp_verify_orders_ok"', log_text)
        self.assertIn('DROP DATABASE IF EXISTS "rp_verify_orders_ok"', log_text)

        # Verify GET /v1/runs?status=PASS filter and EvidenceStore persistence
        list_code, list_data, _ = _http_json(f"{self.base_url}/v1/runs?status=PASS&limit=10")
        self.assertEqual(list_code, 200)
        self.assertEqual(list_data["total"], 1)
        self.assertEqual(list_data["items"][0]["run_id"], job_pass["run_id"])

        reloaded = EvidenceStore(self.data_dir)
        self.assertIsNotNone(reloaded.get(job_pass["run_id"]))
        self.assertEqual(reloaded.get(job_pass["run_id"]).status, "PASS")

    def test_backup_manager_sqlite_restore_compare_audit_and_native_assistant(self) -> None:
        # 1. System monitor reports real host & binary capabilities
        m_code, mon, _ = _http_json(f"{self.base_url}/v1/system/monitor")
        self.assertEqual(m_code, 200)
        self.assertTrue(mon["isolated_sqlite_ready"])
        self.assertIn("cpu_count", mon["host"])

        # 2. Create managed valid SQLite backup + tampered archive backup
        c1, b1, _ = _http_json(
            f"{self.base_url}/v1/backups",
            method="POST",
            body={"name": "SQLite Prod Dump", "preset": "valid_sqlite", "actor": "ops1"},
        )
        self.assertEqual(c1, 201)
        b1_id = b1["backup"]["id"]

        c2, b2, _ = _http_json(
            f"{self.base_url}/v1/backups",
            method="POST",
            body={"name": "Tampered Archive", "preset": "tampered_manifest_archive", "actor": "ops1"},
        )
        self.assertEqual(c2, 201)
        b2_id = b2["backup"]["id"]

        # 3. Check integrity on both backups
        chk1_c, chk1, _ = _http_json(f"{self.base_url}/v1/backups/{b1_id}/check", method="POST", body={})
        self.assertEqual(chk1_c, 200)
        self.assertEqual(chk1["status"], "PASS")

        chk2_c, chk2, _ = _http_json(f"{self.base_url}/v1/backups/{b2_id}/check", method="POST", body={})
        self.assertEqual(chk2_c, 200)
        self.assertEqual(chk2["status"], "FAIL")

        # 4. Run real SQLite isolated restore verification (PASS) and low-rows FAIL
        _, j_ok, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "backup_source_id": b1_id,
                "min_total_rows": 3,
                "required_tables": ["accounts"],
                "priority": "high",
            },
        )
        r_ok = self._wait_terminal(j_ok["run_id"])
        self.assertEqual(r_ok["status"], "PASS")

        _, j_fail, _ = _http_json(
            f"{self.base_url}/v1/verifications",
            method="POST",
            body={
                "backup_source_id": b1_id,
                "min_total_rows": 50,
                "required_tables": ["accounts"],
            },
        )
        r_fail = self._wait_terminal(j_fail["run_id"])
        self.assertEqual(r_fail["status"], "FAIL")

        # 5. Compare PASS vs FAIL run
        cmp_c, cmp_data, _ = _http_json(
            f"{self.base_url}/v1/compare?a={j_ok['run_id']}&b={j_fail['run_id']}"
        )
        self.assertEqual(cmp_c, 200)
        self.assertTrue(cmp_data["diff"]["verdict_changed"])
        self.assertEqual(cmp_data["diff"]["verdict_transition"], "PASS -> FAIL")

        # 6. Native AI Operations Assistant: Approval Gate + Root Cause Diagnosis
        a_plan_c, a_plan, _ = _http_json(
            f"{self.base_url}/v1/assistant/command",
            method="POST",
            body={"message": "ทดสอบ restore backup ล่าสุด", "context_backup_id": b1_id},
        )
        self.assertEqual(a_plan_c, 200)
        self.assertFalse(a_plan["external_ai_used"])
        self.assertTrue(a_plan["requires_approval"])
        self.assertFalse(a_plan["executed"])

        a_diag_c, a_diag, _ = _http_json(
            f"{self.base_url}/v1/assistant/command",
            method="POST",
            body={"message": f"วิเคราะห์สาเหตุที่ {j_fail['run_id']} ล้มเหลว"},
        )
        self.assertEqual(a_diag_c, 200)
        self.assertIn(j_fail["run_id"], a_diag["referenced_run_ids"])
        self.assertEqual(
            a_diag["tool_outputs"]["diagnosis"]["root_cause_code"],
            "DATA_COMPLETENESS_OR_INVARIANT_FAIL",
        )

        # 7. Audit trail recorded operations
        aud_c, aud_data, _ = _http_json(f"{self.base_url}/v1/audit?limit=20")
        self.assertEqual(aud_c, 200)
        self.assertGreaterEqual(aud_data["total"], 4)


if __name__ == "__main__":
    unittest.main()
