#!/usr/bin/env python3
"""
Persistent NDJSON IPC worker for ZYRQUEN Python Core & SQLite Bridge.
Eliminates per-request Python process startup and repeated schema initialization
while preserving exact semantics and isolating stdout framing from internal logs.
"""

import contextlib
import json
import sys

from db_bridge import handle_action
from zyrquen_core import dispatch_command, init_db


def main() -> None:
    protocol_out = sys.stdout
    init_db()
    protocol_out.write(json.dumps({"ready": True}) + "\n")
    protocol_out.flush()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            script = req.get("script")
            payload_obj = req.get("input") or {}
            with contextlib.redirect_stdout(sys.stderr):
                if script == "db_bridge.py":
                    result = handle_action(
                        str(payload_obj.get("action", "")),
                        payload_obj.get("payload", {}) or {},
                    )
                elif script == "zyrquen_core.py":
                    result = dispatch_command(
                        str(payload_obj.get("cmd", "")),
                        payload_obj.get("payload", {}) or {},
                    )
                else:
                    raise ValueError(f"Unsupported worker target: {script}")
            resp = {"id": req_id, "ok": True, "result": result}
        except Exception as exc:
            resp = {"id": req_id, "ok": False, "error": str(exc)}

        protocol_out.write(json.dumps(resp) + "\n")
        protocol_out.flush()


if __name__ == "__main__":
    main()
