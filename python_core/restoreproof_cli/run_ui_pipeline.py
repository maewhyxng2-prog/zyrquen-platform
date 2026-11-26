from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import webbrowser

ROOT = Path(__file__).resolve().parent
UI_HTML = ROOT.parent / "restoreproof_ui" / "index.html"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import RestoreProofReport, file_sha256, run_restore_proof  # noqa: E402
from ui_adapter import write_ui_payload_from_reports  # noqa: E402


def run_pipeline_demo(
    open_browser: bool = True,
    out_dir: Path | None = None,
) -> Path:
    work_dir = Path(tempfile.mkdtemp(prefix="rp_ui_pipe_"))
    try:
        # 1) Create healthy backup bundle + manifest
        src_ok = work_dir / "src_ok"
        src_ok.mkdir()
        (src_ok / "orders.csv").write_text("id,total\n1,120.0\n2,80.0\n", encoding="utf-8")
        (src_ok / "meta.json").write_text('{"version": 1}\n', encoding="utf-8")

        manifest_ok = {
            "orders.csv": file_sha256(src_ok / "orders.csv"),
            "meta.json": file_sha256(src_ok / "meta.json"),
        }
        zip_ok = Path(
            shutil.make_archive(str(work_dir / "backup_ok"), "zip", root_dir=str(src_ok))
        )

        report_ok: RestoreProofReport = run_restore_proof(
            backup_path=zip_ok,
            min_files=2,
            expected_manifest_hashes=manifest_ok,
            health_cmd=[
                sys.executable,
                "-c",
                "import pathlib; assert (pathlib.Path('.') / 'orders.csv').exists()",
            ],
        )

        # 2) Create incomplete/tampered backup bundle (missing meta.json in manifest)
        src_bad = work_dir / "src_bad"
        src_bad.mkdir()
        (src_bad / "orders.csv").write_text("id,total\n1,120.0\n", encoding="utf-8")
        zip_bad = Path(
            shutil.make_archive(str(work_dir / "backup_incomplete"), "zip", root_dir=str(src_bad))
        )

        report_bad: RestoreProofReport = run_restore_proof(
            backup_path=zip_bad,
            min_files=2,
            expected_manifest_hashes=manifest_ok,
            health_cmd=[
                sys.executable,
                "-c",
                "import pathlib; assert (pathlib.Path('.') / 'meta.json').exists()",
            ],
        )

        target_out_dir = out_dir or (ROOT / "artifacts")
        target_out_dir.mkdir(parents=True, exist_ok=True)
        raw_reports_path = target_out_dir / "pipeline_reports.json"
        raw_reports_path.write_text(
            json.dumps([report_ok.to_dict(), report_bad.to_dict()], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        ui_payload_path = target_out_dir / "restoreproof_ui_payload.json"
        write_ui_payload_from_reports(
            reports=[report_ok, report_bad],
            out_path=ui_payload_path,
            source_name="Isolated Backup Test Fixture",
            backup_type="ZIP Archive",
            is_demo=True,  # Fixture created for local pipeline check; values come from real runs
        )

        print(f"Saved raw reports: {raw_reports_path}")
        print(f"Saved UI payload : {ui_payload_path}")
        print(f"UI HTML path     : {UI_HTML}")

        if open_browser and UI_HTML.exists():
            webbrowser.open(UI_HTML.as_uri())

        return ui_payload_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    run_pipeline_demo(open_browser=False)
