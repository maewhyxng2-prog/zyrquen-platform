"""Unit tests for parameterized OAuth provider config persistence in db_bridge.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))


class TestDbOAuthConfig(unittest.TestCase):
    def test_oauth_config_upsert_get_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prev = os.environ.get("ZYRQUEN_DATA_DIR")
            os.environ["ZYRQUEN_DATA_DIR"] = tmpdir
            try:
                import zyrquen_core
                import db_bridge

                zyrquen_core.DATA_DIR = Path(tmpdir)
                zyrquen_core.DB_PATH = Path(tmpdir) / "zyrquen.db"
                db_bridge.DATA_DIR = Path(tmpdir)
                zyrquen_core.init_db()

                up = db_bridge.handle_action(
                    "oauth_config_upsert",
                    {
                        "provider": "google",
                        "client_id": "test-google-client-id-1234",
                        "client_secret_enc": "v1.iv.tag.ciphertext",
                        "secret_masked": "••••••••9999",
                        "actor_id": "admin-1",
                        "actor_email": "admin@example.com",
                    },
                )
                self.assertTrue(up["ok"])

                fetched = db_bridge.handle_action("oauth_config_get", {})
                self.assertTrue(fetched["ok"])
                self.assertEqual(len(fetched["configs"]), 1)
                self.assertEqual(fetched["configs"][0]["provider"], "google")
                self.assertEqual(fetched["configs"][0]["client_id"], "test-google-client-id-1234")
                self.assertEqual(fetched["configs"][0]["secret_masked"], "••••••••9999")

                # Verify audit log redacts secret
                conn = zyrquen_core.get_db()
                logs = conn.execute(
                    "SELECT action, details_json FROM audit_logs ORDER BY created_at DESC LIMIT 1"
                ).fetchall()
                conn.close()
                self.assertEqual(logs[0]["action"], "admin_oauth_config_updated")
                self.assertEqual(json.loads(logs[0]["details_json"])["client_secret"], "[REDACTED]")

                deleted = db_bridge.handle_action(
                    "oauth_config_delete",
                    {
                        "provider": "google",
                        "actor_id": "admin-1",
                        "actor_email": "admin@example.com",
                    },
                )
                self.assertTrue(deleted["ok"])
                after = db_bridge.handle_action("oauth_config_get", {})
                self.assertEqual(after["configs"], [])
            finally:
                if prev is None:
                    os.environ.pop("ZYRQUEN_DATA_DIR", None)
                else:
                    os.environ["ZYRQUEN_DATA_DIR"] = prev


if __name__ == "__main__":
    unittest.main()
