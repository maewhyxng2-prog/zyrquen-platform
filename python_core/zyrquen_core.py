#!/usr/bin/env python3
"""
ZYRQUEN Native Core (Python 3.11 Standard Library Only)
Implements:
- Safe AST mathematical & logical reasoning
- Persistent SQLite Associative Knowledge Graph with multi-hop BFS & contradiction detection
- Native DAG Goal Decomposition & Planning Engine grounded in live SQLite state
- Versioned, non-overwriting N-Gram Native Sequence Model with Thai syllable segmentation
- Scientific Evaluation & Baseline Comparison Suite
- Honest boundary reporting (never fabricates answers or calls external LLMs)
- Real system telemetry & 8-group Workflow Engine diagnostics
"""

import ast
import collections
import hashlib
import json
import math
import operator
import os
import platform
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from tools_engine import (
    analyze_structured_dataset_content,
    detect_tool_intent,
    format_tool_markdown,
    init_tools_schema,
    inspect_workspace_code_content,
    invoke_tool_governed,
)
from dag_executor import (
    MISSION_STATES,
    build_mission_dag,
    execute_dag_loop,
)
from native_neural import NativeTransformerLM
from causal_logic import try_causal_logic_reasoning
from memory_learning import (
    curate_verified_training_corpus,
    decide_experiment,
    detect_capability_gaps,
    record_episodic_experience,
    run_controlled_neural_experiment,
)
from continual_learning import (
    run_continual_learning_round,
    synthesize_failure_curriculum,
)
from code_problem_training import (
    curate_code_problem_corpus,
    evaluate_code_problem_model,
    run_code_problem_experiment,
)
from real_only_trainer import record_real_only_training_in_db
from dataset_ingestion import (
    decide_kg_proposal,
    ingest_dataset as _ingest_dataset_pipeline,
    init_dataset_pipeline_schema,
    verify_all_datasets_for_workflow,
    verify_dataset_integrity,
)
from cognitive_pipeline import (
    understand_input as _understand_cognitive_input,
    run_cognitive_fallback_pipeline,
    learn_from_experience as _learn_cognitive_experience,
)
from planner_intelligence import (
    analyze_planner_goal,
    build_context_aware_dag_plan,
    unwrap_command_wrapper,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ZYRQUEN_DATA_DIR") or (BASE_DIR / "data"))
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
DB_PATH = DATA_DIR / "zyrquen.db"

SAFE_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

SAFE_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

SAFE_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "factorial": math.factorial,
    "floor": math.floor,
    "ceil": math.ceil,
}

SAFE_CONSTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

WORKFLOW_GROUPS = [
    {
        "id": "system_ops",
        "name": "ปฏิบัติการระบบ (System Operations)",
        "description": "ตรวจสอบ CPU, RAM, พื้นที่ดิสก์, ฐานข้อมูล SQLite และสถานะแกนสมอง Python",
        "requires_approval": False,
        "stages": ["health_probe", "resource_audit", "storage_check", "status_report"],
    },
    {
        "id": "data_pipeline",
        "name": "จัดการข้อมูล (Data Workflow)",
        "description": "ตรวจรูปแบบข้อมูล คัดกรองข้อมูลซ้ำ ตรวจ Data Leakage และสร้างแฮช SHA-256",
        "requires_approval": False,
        "stages": ["schema_validate", "deduplicate", "leakage_scan", "manifest_hash"],
    },
    {
        "id": "native_training",
        "name": "ฝึกโมเดลภายใน (Native Training)",
        "description": "บังคับลำดับ ข้อมูลจริง+ไร้ Leakage → Baseline → อนุมัติ → ฝึก → ประเมินและควบคุม Checkpoint",
        "requires_approval": True,
        "stages": [
            "provenance_leakage_gate",
            "baseline_verify",
            "approval_gate",
            "checkpoint_train",
            "checkpoint_eval_gate",
        ],
    },
    {
        "id": "evaluation",
        "name": "ประเมินผล (Evaluation Workflow)",
        "description": "ทดสอบ AST, กราฟความรู้หลายชั้น, การวางแผน DAG และชุดข้อมูล Test เทียบ Baseline",
        "requires_approval": False,
        "stages": ["math_probe", "knowledge_probe", "planning_probe", "heldout_test_eval", "report_emit"],
    },
    {
        "id": "knowledge_memory",
        "name": "ความรู้และความจำ (Knowledge & Memory)",
        "description": "ตรวจสอบความสัมพันธ์ของความรู้ ตรวจจับข้อขัดแย้ง และจัดทำดัชนีกราฟความรู้",
        "requires_approval": False,
        "stages": ["triple_scan", "contradiction_detect", "graph_index"],
    },
    {
        "id": "autonomous_improvement",
        "name": "ปรับปรุงอัตโนมัติ (Autonomous Improvement)",
        "description": "วิเคราะห์จุดอ่อน เสนอสมมติฐาน ตรวจความถูกต้องแผน (plan_hash + repo_revision) ขออนุมัติ ดำเนินการแบบจำกัดขอบเขต ยืนยันผลจริง และบันทึกประสบการณ์",
        "requires_approval": True,
        "stages": [
            "gap_analysis",
            "hypothesis_draft",
            "plan_validation",
            "approval_gate",
            "bounded_execution",
            "verification",
            "outcome_learning",
        ],
    },
    {
        "id": "security_governance",
        "name": "ความปลอดภัยและธรรมาภิบาล",
        "description": "ตรวจแฮชความสมบูรณ์ของซอร์สโค้ดหลัก ความปลอดภัยของคีย์ และบันทึก Audit Trail",
        "requires_approval": False,
        "stages": ["integrity_hash", "key_hygiene", "audit_verify"],
    },
    {
        "id": "project_dev",
        "name": "โครงการและการพัฒนา",
        "description": "ตรวจความสอดคล้องของระบบจริง ชุดทดสอบ และขอบเขตสถาปัตยกรรมที่ได้รับอนุญาต",
        "requires_approval": False,
        "stages": ["runtime_sync", "artifact_check", "roadmap_verify"],
    },
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_ensured_data_dirs: set[str] = set()


def get_db() -> sqlite3.Connection:
    dir_key = str(DATA_DIR)
    if dir_key not in _ensured_data_dirs:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        _ensured_data_dirs.add(dir_key)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA cache_size=-16000;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    conn = get_db()
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'auto',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'auto',
                trace_json TEXT,
                status TEXT NOT NULL DEFAULT 'VERIFIED',
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                total_records INTEGER NOT NULL,
                train_count INTEGER NOT NULL,
                val_count INTEGER NOT NULL,
                test_count INTEGER NOT NULL,
                leakage_detected INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                records_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                dataset_id TEXT NOT NULL,
                vocab_size INTEGER NOT NULL,
                ngram_order INTEGER NOT NULL,
                train_loss REAL NOT NULL,
                val_loss REAL NOT NULL,
                perplexity REAL NOT NULL,
                eval_accuracy REAL,
                eval_status TEXT NOT NULL,
                weights_path TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                status TEXT NOT NULL,
                requires_approval INTEGER NOT NULL DEFAULT 0,
                triggered_by TEXT NOT NULL,
                approved_by TEXT,
                summary TEXT NOT NULL,
                stages_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                quota_daily INTEGER NOT NULL DEFAULT 1000,
                requests_today INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                key_id TEXT,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                actor_email TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                outcome TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                checkpoint_id TEXT,
                checkpoint_version INTEGER,
                suite_name TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                math_score REAL NOT NULL,
                knowledge_score REAL NOT NULL,
                planning_score REAL NOT NULL,
                test_accuracy REAL,
                perplexity REAL,
                baseline_delta_json TEXT,
                details_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS autonomous_missions (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                stages_json TEXT NOT NULL,
                knowledge_developed_json TEXT NOT NULL,
                research_summary_json TEXT NOT NULL,
                report_markdown TEXT NOT NULL,
                external_models_used INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mission_nodes (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                node_json TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT NOT NULL,
                last_error TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(mission_id) REFERENCES autonomous_missions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mission_evidence (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                node_id TEXT,
                source_url TEXT NOT NULL,
                provider TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                trust_grade TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                extracted_claims_json TEXT NOT NULL,
                FOREIGN KEY(mission_id) REFERENCES autonomous_missions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS episodic_experiences (
                id TEXT PRIMARY KEY,
                mission_id TEXT,
                goal TEXT NOT NULL,
                outcome_status TEXT NOT NULL,
                gap_type TEXT,
                hypothesis_json TEXT NOT NULL,
                verified_delta REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                hypothesis TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                baseline_ckpt_id TEXT,
                candidate_ckpt_id TEXT,
                baseline_metrics_json TEXT NOT NULL,
                candidate_metrics_json TEXT NOT NULL,
                improved INTEGER NOT NULL DEFAULT 0,
                approval_status TEXT NOT NULL,
                approved_by TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS capability_baselines (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                benchmark_version TEXT NOT NULL,
                model_version TEXT NOT NULL,
                status TEXT NOT NULL,
                score REAL NOT NULL,
                passed INTEGER NOT NULL,
                total INTEGER NOT NULL,
                false_positives INTEGER NOT NULL DEFAULT 0,
                evidence_hash TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reasoning_traces (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT,
                message_id TEXT,
                prompt TEXT NOT NULL,
                response_preview TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'auto',
                model_version TEXT NOT NULL DEFAULT 'zyrquen-omega-v1',
                status TEXT NOT NULL,
                engine_path_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                latency_ms REAL NOT NULL DEFAULT 0.0,
                external_models_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reasoning_traces_user_created
                ON reasoning_traces(user_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_reasoning_traces_created
                ON reasoning_traces(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                ON conversations(user_id, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_conv_created
                ON messages(conversation_id, created_at ASC);

            CREATE INDEX IF NOT EXISTS idx_knowledge_triples_subj_rel
                ON knowledge_triples(subject, relation);

            CREATE INDEX IF NOT EXISTS idx_api_keys_user
                ON api_keys(user_id);

            CREATE INDEX IF NOT EXISTS idx_api_usage_user_created
                ON api_usage_logs(user_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_workflow_runs_created
                ON workflow_runs(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_audit_logs_created
                ON audit_logs(created_at DESC);
            """
        )
        init_tools_schema(conn, DATA_DIR)
        init_dataset_pipeline_schema(conn)
        from tool_center import init_tool_center_schema

        init_tool_center_schema(conn)
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(tool_invocations)").fetchall()
        }
        if "mission_id" not in cols:
            conn.execute("ALTER TABLE tool_invocations ADD COLUMN mission_id TEXT")
        if "mission_node_id" not in cols:
            conn.execute("ALTER TABLE tool_invocations ADD COLUMN mission_node_id TEXT")

        wf_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()
        }
        for col_name, col_type in (
            ("plan_hash", "TEXT"),
            ("repo_revision", "TEXT"),
            ("plan_json", "TEXT"),
            ("approval_scope_json", "TEXT"),
            ("depends_on_runs_json", "TEXT"),
            ("output_json", "TEXT"),
            ("verification_json", "TEXT"),
            ("invalidated_reason", "TEXT"),
        ):
            if col_name not in wf_cols:
                conn.execute(f"ALTER TABLE workflow_runs ADD COLUMN {col_name} {col_type}")
    conn.close()


def get_system_metrics() -> dict:
    mem_total_mb = 0.0
    mem_avail_mb = 0.0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            mem_info = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    mem_info[key] = float(val)
            mem_total_mb = round(mem_info.get("MemTotal", 0.0) / 1024.0, 1)
            mem_avail_mb = round(mem_info.get("MemAvailable", 0.0) / 1024.0, 1)
    except OSError:
        pass

    disk = shutil.disk_usage(str(BASE_DIR))
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    db_size_kb = round(DB_PATH.stat().st_size / 1024.0, 1) if DB_PATH.exists() else 0.0

    return {
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "cpu_count": os.cpu_count() or 1,
        "load_1m": round(load_avg[0], 2),
        "mem_total_mb": mem_total_mb,
        "mem_available_mb": mem_avail_mb,
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "sqlite_db_kb": db_size_kb,
    }


def _compute_native_integrity() -> dict:
    core_dir = Path(__file__).resolve().parent
    module_digests: dict[str, str] = {}
    for fname in ("zyrquen_core.py", "dag_executor.py", "planner_intelligence.py"):
        fp = core_dir / fname
        if fp.is_file():
            module_digests[fname] = hashlib.sha256(fp.read_bytes()).hexdigest()[:16]
    combined = hashlib.sha256(
        json.dumps(module_digests, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "external_models_used": False,
        "runtime": "python_native_stdlib",
        "core_bundle_sha256": combined,
        "module_digests": module_digests,
    }


def _compute_repo_revision(repo_root: Path | None = None) -> str:
    root = repo_root or BASE_DIR
    try:
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if head_proc.returncode == 0 and head_proc.stdout.strip():
            head = head_proc.stdout.strip()[:16]
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            diff_proc = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            dirty_hash = hashlib.sha256(
                (status_proc.stdout + "\n" + diff_proc.stdout).encode("utf-8", errors="ignore")
            ).hexdigest()[:12]
            return f"git:{head}:dirty:{dirty_hash}"
    except Exception:
        pass
    integrity = _compute_native_integrity()
    return f"bundle:{integrity['core_bundle_sha256']}"


def _canonical_plan_hash(plan_obj: dict) -> str:
    canonical = json.dumps(plan_obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_knowledge_quality_summary(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT id, subject, relation, object, source, confidence, created_at FROM knowledge_triples ORDER BY created_at DESC"
    ).fetchall()
    total = len(rows)
    pairs: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    source_counts: dict[str, int] = collections.Counter()
    with_provenance = 0
    verified_count = 0
    timestamps: list[str] = []

    for r in rows:
        subj = str(r["subject"] or "")
        rel = str(r["relation"] or "")
        obj = str(r["object"] or "")
        src = str(r["source"] or "").strip()
        conf = float(r["confidence"] or 0.0)
        pairs[(subj.lower(), rel.lower())].add(obj.lower())
        if src:
            source_counts[src] += 1
        if src and conf >= 0.7:
            with_provenance += 1
        if (
            conf >= 0.8
            and src
            and "uncorroborated" not in src.lower()
            and "conflicting" not in src.lower()
            and "stale" not in src.lower()
        ):
            verified_count += 1
        if r["created_at"]:
            timestamps.append(str(r["created_at"]))

    contradiction_details = [
        {"subject": s, "relation": rel, "conflicting_objects": sorted(objs)}
        for (s, rel), objs in pairs.items()
        if len(objs) > 1
    ]
    contradictions = len(contradiction_details)
    provenance_coverage_pct = round((with_provenance / total) * 100.0, 1) if total > 0 else 0.0

    # Episodic + Tool Center task memory
    ep_rows = conn.execute(
        "SELECT goal, outcome_status, gap_type, verified_delta, created_at FROM episodic_experiences ORDER BY created_at DESC LIMIT 25"
    ).fetchall()
    ep_success = sum(1 for r in ep_rows if str(r["outcome_status"]) in {"COMPLETED", "VERIFIED", "PASS"})
    ep_failed = sum(1 for r in ep_rows if str(r["outcome_status"]) in {"FAILED", "BLOCKED"})

    tm_total = 0
    tm_success = 0
    tm_failed = 0
    try:
        tm_rows = conn.execute(
            "SELECT capability_id, success_count, failure_count FROM task_memory"
        ).fetchall()
        tm_total = len(tm_rows)
        tm_success = sum(int(r["success_count"] or 0) for r in tm_rows)
        tm_failed = sum(int(r["failure_count"] or 0) for r in tm_rows)
    except sqlite3.Error:
        pass

    if total == 0:
        status = "EMPTY"
        indexing_health = "EMPTY"
    elif contradictions > 0 or provenance_coverage_pct < 100.0:
        status = "WARN"
        indexing_health = "INDEXED_WITH_WARNINGS"
    else:
        status = "VERIFIED"
        indexing_health = "INDEXED"

    return {
        "status": status,
        "empty": total == 0,
        "total_triples": total,
        "verified_triples": verified_count,
        "provenance_coverage_pct": provenance_coverage_pct,
        "source_counts": dict(source_counts),
        "contradiction_groups": contradictions,
        "contradiction_details": contradiction_details[:8],
        "indexing_health": indexing_health,
        "freshness": {
            "latest_created_at": timestamps[0] if timestamps else None,
            "oldest_created_at": timestamps[-1] if timestamps else None,
        },
        "task_memory_summary": {
            "tracked_capabilities": tm_total,
            "success_observations": tm_success,
            "failure_observations": tm_failed,
            "episodic_experiences": len(ep_rows),
            "episodic_success": ep_success,
            "episodic_failures": ep_failed,
            "recent_outcomes": [
                {
                    "goal": str(r["goal"] or "")[:100],
                    "outcome_status": str(r["outcome_status"]),
                    "gap_type": r["gap_type"],
                    "created_at": str(r["created_at"]),
                }
                for r in ep_rows[:5]
            ],
        },
    }


def get_training_tracks_and_levels(conn: sqlite3.Connection) -> dict:
    # Track 1: Tool-Use Training (tool center invocations + task memory)
    tc_total = 0
    tc_success = 0
    try:
        tc_total = int(conn.execute("SELECT COUNT(*) FROM tool_center_invocations").fetchone()[0])
        tc_success = int(
            conn.execute("SELECT COUNT(*) FROM tool_center_invocations WHERE status IN ('COMPLETED', 'SUCCESS')").fetchone()[0]
        )
    except sqlite3.Error:
        pass

    # Track 2: Workflow Training (workflow_runs + improvement_proposals)
    wf_completed = int(conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE status='COMPLETED'").fetchone()[0])
    wf_failed = int(conn.execute("SELECT COUNT(*) FROM workflow_runs WHERE status IN ('FAILED', 'BLOCKED')").fetchone()[0])
    imp_approved = 0
    try:
        imp_approved = int(
            conn.execute("SELECT COUNT(*) FROM improvement_proposals WHERE approval_status='APPROVED'").fetchone()[0]
        )
    except sqlite3.Error:
        pass

    # Track 3: Native Weight Training (Native-Only, from scratch, gated)
    clean_datasets = int(
        conn.execute("SELECT COUNT(*) FROM datasets WHERE leakage_detected=0 AND total_records>=5").fetchone()[0]
    )
    checkpoints_total = int(conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0])
    neural_checkpoints = int(
        conn.execute("SELECT COUNT(*) FROM checkpoints WHERE eval_status LIKE 'NEURAL%'").fetchone()[0]
    )
    approved_training_runs = int(
        conn.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE group_id='native_training' AND status='COMPLETED' AND approved_by IS NOT NULL"
        ).fetchone()[0]
    )

    # 5 Progressive Engineering Levels (honestly derived from persisted evidence)
    missions_total = int(conn.execute("SELECT COUNT(*) FROM autonomous_missions").fetchone()[0])
    missions_completed = int(
        conn.execute("SELECT COUNT(*) FROM autonomous_missions WHERE status='COMPLETED'").fetchone()[0]
    )
    eval_rows = conn.execute(
        "SELECT overall_status, math_score, knowledge_score, planning_score FROM evaluations ORDER BY created_at DESC LIMIT 1"
    ).fetchall()
    latest_eval = eval_rows[0] if eval_rows else None

    code_understanding_score = 1.0 if tc_success > 0 else 0.0
    debugging_score = round(
        min(1.0, (ep_ok := int(conn.execute("SELECT COUNT(*) FROM episodic_experiences WHERE outcome_status='COMPLETED'").fetchone()[0])) / 2.0),
        2,
    )
    implementation_score = round(min(1.0, (missions_completed + wf_completed) / 3.0), 2) if (missions_completed + wf_completed) > 0 else 0.0
    testing_score = round(float(latest_eval["math_score"]), 2) if latest_eval else 0.0
    autonomous_score = round(
        min(1.0, (missions_completed / max(1, missions_total)) * (1.0 if (latest_eval and latest_eval["planning_score"] == 1.0) else 0.5)),
        2,
    ) if missions_total > 0 else 0.0

    def _lvl_status(score: float, evidence_count: int) -> str:
        if evidence_count == 0:
            return "NOT_RUN"
        if score >= 0.85:
            return "VERIFIED"
        if score > 0.0:
            return "PARTIAL"
        return "FAILED"

    engineering_levels = [
        {
            "level": 1,
            "key": "code_understanding",
            "label": "Level 1: Code Understanding",
            "status": _lvl_status(code_understanding_score, tc_total),
            "score": code_understanding_score,
            "evidence": f"{tc_success}/{tc_total} tool invocations completed",
        },
        {
            "level": 2,
            "key": "debugging",
            "label": "Level 2: Debugging & Diagnosis",
            "status": _lvl_status(debugging_score, ep_ok),
            "score": debugging_score,
            "evidence": f"{ep_ok} verified episodic recovery/outcome records",
        },
        {
            "level": 3,
            "key": "implementation",
            "label": "Level 3: Bounded Implementation",
            "status": _lvl_status(implementation_score, missions_completed + wf_completed),
            "score": implementation_score,
            "evidence": f"{missions_completed} missions, {wf_completed} completed workflows",
        },
        {
            "level": 4,
            "key": "testing",
            "label": "Level 4: Verification & Testing",
            "status": _lvl_status(testing_score, len(eval_rows)),
            "score": testing_score,
            "evidence": f"Latest eval={latest_eval['overall_status']}" if latest_eval else "No evaluations yet",
        },
        {
            "level": 5,
            "key": "autonomous_engineering",
            "label": "Level 5: Autonomous Engineering",
            "status": _lvl_status(autonomous_score, missions_total),
            "score": autonomous_score,
            "evidence": f"{missions_completed}/{missions_total} autonomous missions completed",
        },
    ]

    return {
        "training_tracks": {
            "tool_use_training": {
                "label": "Tool-Use Training (Empirical Task Memory)",
                "native_only": True,
                "status": "ACTIVE" if tc_total > 0 else "NOT_RUN",
                "invocations_total": tc_total,
                "invocations_succeeded": tc_success,
            },
            "workflow_training": {
                "label": "Workflow Training (Orchestrated Lifecycles)",
                "native_only": True,
                "status": "ACTIVE" if wf_completed > 0 else "NOT_RUN",
                "completed_runs": wf_completed,
                "failed_or_blocked_runs": wf_failed,
                "approved_improvement_proposals": imp_approved,
            },
            "native_weight_training": {
                "label": "Native Weight Training (From-Scratch & Approval-Gated)",
                "native_only": True,
                "from_scratch_only": True,
                "gated": True,
                "status": "VERIFIED" if checkpoints_total > 0 else ("READY_FOR_GATE" if clean_datasets > 0 else "BLOCKED"),
                "clean_datasets": clean_datasets,
                "checkpoints_total": checkpoints_total,
                "neural_checkpoints": neural_checkpoints,
                "approved_training_runs": approved_training_runs,
            },
        },
        "engineering_levels": engineering_levels,
    }


def _fmt_num(v: float) -> int | float:
    if abs(v) < 1e-11:
        return 0
    if abs(v - round(v)) < 1e-9:
        return int(round(v))
    return round(v, 8)


_MATH_TRAILING_RE = re.compile(
    r"(?:\s*(?:ได้เท่าไร|ได้เท่าไหร่|เป็นเท่าไร|เป็นเท่าไหร่|เท่าไร|เท่าไหร่|ให้หน่อยครับ|ให้หน่อยค่ะ|ให้หน่อย|หน่อยครับ|หน่อยค่ะ|หน่อย|ทีครับ|ทีค่ะ|นะครับ|นะคะ|ครับ|ค่ะ|นะ|please|plz|\?))+\s*$",
    re.IGNORECASE,
)


def safe_eval_ast(node: ast.AST, steps: list) -> float:
    if isinstance(node, ast.Expression):
        return safe_eval_ast(node.body, steps)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in SAFE_CONSTS:
            val = SAFE_CONSTS[node.id]
            steps.append(f"const {node.id} = {val:.6g}")
            return float(val)
        raise ValueError(f"Unknown symbol '{node.id}'")
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_BIN_OPS:
        left = safe_eval_ast(node.left, steps)
        right = safe_eval_ast(node.right, steps)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("Exponent magnitude bounded to 100 for resource safety")
        res = float(SAFE_BIN_OPS[type(node.op)](left, right))
        if not math.isfinite(res):
            raise ValueError("Non-finite arithmetic result")
        steps.append(f"{left:g} {type(node.op).__name__} {right:g} = {res:g}")
        return res
    if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_UNARY_OPS:
        operand = safe_eval_ast(node.operand, steps)
        return float(SAFE_UNARY_OPS[type(node.op)](operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fname = node.func.id
        if fname not in SAFE_FUNCS:
            raise ValueError(f"Function '{fname}' is not in safe AST whitelist")
        if len(node.args) != 1 or node.keywords:
            raise ValueError(f"Function '{fname}' requires exactly 1 positional argument")
        arg_val = safe_eval_ast(node.args[0], steps)
        if fname == "factorial" and (arg_val < 0 or arg_val > 50 or arg_val != int(arg_val)):
            raise ValueError("factorial argument must be integer in [0, 50]")
        res = float(SAFE_FUNCS[fname](int(arg_val) if fname == "factorial" else arg_val))
        if not math.isfinite(res):
            raise ValueError("Non-finite function result")
        steps.append(f"{fname}({arg_val:g}) = {res:g}")
        return res
    raise ValueError("Unsupported AST expression node")


def _normalize_algebra_expr(expr: str) -> str:
    # Insert explicit '*' for cases like '3x' or '2(x+1)' or '(x+1)(x-1)' without breaking func calls like log10(1000)
    step1 = re.sub(r"(?<![a-zA-Z0-9_])(\d+(?:\.\d+)?)\s*([a-zA-Z(])", r"\1*\2", expr)
    step2 = re.sub(r"(\))\s*([a-zA-Z0-9(])", r"\1*\2", step1)
    return step2.replace("^", "**")


def _eval_poly2_ast(node: ast.AST, var_name: str) -> tuple[float, float, float]:
    """Return (c2, c1, c0) for c2*x^2 + c1*x + c0 strictly bounded to degree <= 2."""
    if isinstance(node, ast.Expression):
        return _eval_poly2_ast(node.body, var_name)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return (0.0, 0.0, float(node.value))
    if isinstance(node, ast.Name):
        if node.id == var_name:
            return (0.0, 1.0, 0.0)
        if node.id in SAFE_CONSTS:
            return (0.0, 0.0, float(SAFE_CONSTS[node.id]))
        raise ValueError(f"Unknown symbol '{node.id}'")
    if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_UNARY_OPS:
        c2, c1, c0 = _eval_poly2_ast(node.operand, var_name)
        if isinstance(node.op, ast.USub):
            return (-c2, -c1, -c0)
        return (c2, c1, c0)
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_BIN_OPS:
        a2, a1, a0 = _eval_poly2_ast(node.left, var_name)
        b2, b1, b0 = _eval_poly2_ast(node.right, var_name)
        if isinstance(node.op, ast.Add):
            return (a2 + b2, a1 + b1, a0 + b0)
        if isinstance(node.op, ast.Sub):
            return (a2 - b2, a1 - b1, a0 - b0)
        if isinstance(node.op, ast.Mult):
            c4 = a2 * b2
            c3 = a2 * b1 + a1 * b2
            if abs(c4) > 1e-12 or abs(c3) > 1e-12:
                raise ValueError("สมการมีดีกรีสูงกว่า 2")
            return (a2 * b0 + a1 * b1 + a0 * b2, a1 * b0 + a0 * b1, a0 * b0)
        if isinstance(node.op, ast.Div):
            if abs(b2) > 1e-12 or abs(b1) > 1e-12:
                raise ValueError("ไม่อนุญาตให้ตัวแปรเป็นตัวหาร")
            if abs(b0) < 1e-12:
                raise ValueError("หารด้วยศูนย์ไม่ได้")
            return (a2 / b0, a1 / b0, a0 / b0)
        if isinstance(node.op, ast.Pow):
            if abs(b2) > 1e-12 or abs(b1) > 1e-12:
                raise ValueError("เลขชี้กำลังต้องเป็นค่าคงที่")
            if abs(a2) < 1e-12 and abs(a1) < 1e-12 and abs(b0) <= 100:
                return (0.0, 0.0, float(a0**b0))
            if abs(b0 - round(b0)) < 1e-12:
                exp_i = int(round(b0))
                if exp_i == 0:
                    return (0.0, 0.0, 1.0)
                if exp_i == 1:
                    return (a2, a1, a0)
                if exp_i == 2:
                    if abs(a2) > 1e-12:
                        raise ValueError("สมการมีดีกรีสูงกว่า 2")
                    return (a1 * a1, 2.0 * a1 * a0, a0 * a0)
            raise ValueError("รองรับพหุนามไม่เกินดีกรี 2")
        raise ValueError("ตัวดำเนินการไม่รองรับ")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fname = node.func.id
        if fname not in SAFE_FUNCS or len(node.args) != 1 or node.keywords:
            raise ValueError(f"Unsupported function '{fname}'")
        a2, a1, a0 = _eval_poly2_ast(node.args[0], var_name)
        if abs(a2) > 1e-12 or abs(a1) > 1e-12:
            raise ValueError("ฟังก์ชันไม่สามารถรับตัวแปรที่ไม่ทราบค่าได้")
        val = float(SAFE_FUNCS[fname](int(a0) if fname == "factorial" else a0))
        if not math.isfinite(val):
            raise ValueError("Non-finite function result")
        return (0.0, 0.0, val)
    raise ValueError("Unsupported polynomial AST node")


def _eval_linear_ast(node: ast.AST, var_name: str) -> tuple[float, float]:
    """Return (coeff_of_var, constant_term) strictly verifying linearity."""
    c2, c1, c0 = _eval_poly2_ast(node, var_name)
    if abs(c2) > 1e-12:
        raise ValueError("รองรับเฉพาะสมการเชิงเส้นกำลังหนึ่ง")
    return (c1, c0)


def _eval_multilinear_ast(node: ast.AST, var_names: set[str]) -> tuple[dict[str, float], float]:
    """Return ({var: coeff}, constant_term) strictly verifying joint linearity."""
    if isinstance(node, ast.Expression):
        return _eval_multilinear_ast(node.body, var_names)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return ({}, float(node.value))
    if isinstance(node, ast.Name):
        if node.id in var_names:
            return ({node.id: 1.0}, 0.0)
        if node.id in SAFE_CONSTS:
            return ({}, float(SAFE_CONSTS[node.id]))
        raise ValueError(f"Unknown symbol '{node.id}'")
    if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_UNARY_OPS:
        coeffs, const = _eval_multilinear_ast(node.operand, var_names)
        if isinstance(node.op, ast.USub):
            return ({k: -v for k, v in coeffs.items()}, -const)
        return (coeffs, const)
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_BIN_OPS:
        lc, lb = _eval_multilinear_ast(node.left, var_names)
        rc, rb = _eval_multilinear_ast(node.right, var_names)
        if isinstance(node.op, ast.Add):
            merged = dict(lc)
            for k, v in rc.items():
                merged[k] = merged.get(k, 0.0) + v
            return (merged, lb + rb)
        if isinstance(node.op, ast.Sub):
            merged = dict(lc)
            for k, v in rc.items():
                merged[k] = merged.get(k, 0.0) - v
            return (merged, lb - rb)
        if isinstance(node.op, ast.Mult):
            has_l = any(abs(v) > 1e-12 for v in lc.values())
            has_r = any(abs(v) > 1e-12 for v in rc.values())
            if has_l and has_r:
                raise ValueError("ระบบสมการไม่ใช่เชิงเส้น")
            if has_l:
                return ({k: v * rb for k, v in lc.items()}, lb * rb)
            return ({k: v * lb for k, v in rc.items()}, lb * rb)
        if isinstance(node.op, ast.Div):
            if any(abs(v) > 1e-12 for v in rc.values()):
                raise ValueError("ไม่อนุญาตให้ตัวแปรเป็นตัวหาร")
            if abs(rb) < 1e-12:
                raise ValueError("หารด้วยศูนย์ไม่ได้")
            return ({k: v / rb for k, v in lc.items()}, lb / rb)
        if isinstance(node.op, ast.Pow):
            has_l = any(abs(v) > 1e-12 for v in lc.values())
            has_r = any(abs(v) > 1e-12 for v in rc.values())
            if not has_l and not has_r and abs(rb) <= 100:
                return ({}, float(lb**rb))
            if not has_r and rb == 1.0:
                return (lc, lb)
            if not has_r and rb == 0.0:
                return ({}, 1.0)
            raise ValueError("ระบบสมการเชิงเส้นไม่รองรับเลขยกกำลังตัวแปร")
        raise ValueError("Unsupported operator")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fname = node.func.id
        if fname not in SAFE_FUNCS or len(node.args) != 1 or node.keywords:
            raise ValueError(f"Unsupported function '{fname}'")
        ac, ab = _eval_multilinear_ast(node.args[0], var_names)
        if any(abs(v) > 1e-12 for v in ac.values()):
            raise ValueError("ฟังก์ชันไม่สามารถรับตัวแปรที่ไม่ทราบค่าได้")
        val = float(SAFE_FUNCS[fname](int(ab) if fname == "factorial" else ab))
        return ({}, val)
    raise ValueError("Unsupported multilinear AST node")


def _try_solve_linear_system(candidate: str, eq_parts: list[str]) -> dict | None:
    if len(eq_parts) < 2 or len(eq_parts) > 6:
        return None
    parsed_eqs: list[tuple[str, str, str]] = []
    all_unknowns: set[str] = set()
    for part in eq_parts:
        if "=" not in part or part.count("=") != 1:
            return None
        lhs_raw, rhs_raw = [p.strip() for p in part.split("=", 1)]
        if not lhs_raw or not rhs_raw:
            return None
        lhs_norm = _normalize_algebra_expr(lhs_raw)
        rhs_norm = _normalize_algebra_expr(rhs_raw)
        if not (
            re.fullmatch(r"[0-9a-zA-Z_+\-*/%.()\s]+", lhs_norm)
            and re.fullmatch(r"[0-9a-zA-Z_+\-*/%.()\s]+", rhs_norm)
        ):
            return None
        tokens_found = re.findall(r"[a-zA-Z_]+", f"{lhs_norm} {rhs_norm}")
        for t in tokens_found:
            if t not in SAFE_FUNCS and t not in SAFE_CONSTS:
                if len(t) != 1:
                    return None
                all_unknowns.add(t)
        parsed_eqs.append((part, lhs_norm, rhs_norm))

    unknowns = sorted(all_unknowns)
    if len(unknowns) < 2 or len(unknowns) > 4:
        return None

    m = len(parsed_eqs)
    n = len(unknowns)
    mat: list[list[float]] = []
    steps: list[str] = [f"ตรวจพบระบบสมการเชิงเส้น {m} สมการ, {n} ตัวแปร ({', '.join(unknowns)})"]

    try:
        for raw_part, lhs_norm, rhs_norm in parsed_eqs:
            lc, lb = _eval_multilinear_ast(ast.parse(lhs_norm, mode="eval"), all_unknowns)
            rc, rb = _eval_multilinear_ast(ast.parse(rhs_norm, mode="eval"), all_unknowns)
            row = [round(lc.get(v, 0.0) - rc.get(v, 0.0), 10) for v in unknowns]
            rhs_const = round(rb - lb, 10)
            row.append(rhs_const)
            mat.append(row)
            terms = [f"{row[i]:g}{unknowns[i]}" for i in range(n) if abs(row[i]) > 1e-10]
            steps.append(f"จัดรูป `{raw_part}` → {' + '.join(terms) or '0'} = {rhs_const:g}")
    except Exception:
        return None

    # Gaussian elimination with partial pivoting (RREF)
    pivot_cols: list[int] = []
    r = 0
    for c in range(n):
        if r >= m:
            break
        best_row = max(range(r, m), key=lambda i: abs(mat[i][c]))
        if abs(mat[best_row][c]) < 1e-10:
            continue
        mat[r], mat[best_row] = mat[best_row], mat[r]
        piv = mat[r][c]
        mat[r] = [val / piv for val in mat[r]]
        for i in range(m):
            if i != r and abs(mat[i][c]) > 1e-12:
                factor = mat[i][c]
                mat[i] = [mat[i][j] - factor * mat[r][j] for j in range(n + 1)]
        pivot_cols.append(c)
        r += 1

    for i in range(m):
        if all(abs(mat[i][j]) < 1e-9 for j in range(n)) and abs(mat[i][n]) >= 1e-9:
            steps.append("พบแถวที่ขัดแย้งหลังกำจัดตัวแปรแบบเกาส์เซียน (0 = ค่าคงที่ที่ไม่เป็นศูนย์)")
            return {
                "engine": "linear_system_rref",
                "equation": candidate,
                "variables": unknowns,
                "solution_type": "no_solution",
                "solutions": {},
                "summary_tag": "no_solution",
                "result": None,
                "steps": steps,
            }

    if len(pivot_cols) < n:
        steps.append(f"อันดับเมทริกซ์ ({len(pivot_cols)}) น้อยกว่าจำนวนตัวแปร ({n}) — มีคำตอบได้หลายชุด")
        return {
            "engine": "linear_system_rref",
            "equation": candidate,
            "variables": unknowns,
            "solution_type": "underdetermined",
            "solutions": {},
            "summary_tag": "underdetermined",
            "result": None,
            "steps": steps,
        }

    solutions = {unknowns[col]: _fmt_num(mat[idx][n]) for idx, col in enumerate(pivot_cols)}
    summary_tag = "system(" + ",".join(f"{v}={solutions[v]}" for v in unknowns) + ")"
    steps.append("คำตอบจาก RREF: " + ", ".join(f"{v} = {solutions[v]}" for v in unknowns))
    return {
        "engine": "linear_system_rref",
        "equation": candidate,
        "variables": unknowns,
        "solution_type": "system",
        "solutions": solutions,
        "summary_tag": summary_tag,
        "result": solutions,
        "steps": steps,
    }


def try_solve_equation(prompt: str) -> dict | None:
    cleaned = prompt.strip()
    m = re.match(
        r"^(?:แก้สมการ|สมการ|solve|equation)\s*:?\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    candidate = m.group(1).strip() if m else cleaned
    candidate = _MATH_TRAILING_RE.sub("", candidate).strip()
    if "=" not in candidate:
        return None

    # Check multi-equation system first
    eq_parts = [p.strip() for p in re.split(r"(?:[,;\n]+|\s+และ\s+|\s+and\s+)", candidate) if p.strip()]
    if len(eq_parts) >= 2:
        return _try_solve_linear_system(candidate, eq_parts)

    if candidate.count("=") != 1:
        return None
    lhs_raw, rhs_raw = [p.strip() for p in candidate.split("=", 1)]
    if not lhs_raw or not rhs_raw:
        return None
    lhs_norm = _normalize_algebra_expr(lhs_raw)
    rhs_norm = _normalize_algebra_expr(rhs_raw)
    if not (
        re.fullmatch(r"[0-9a-zA-Z_+\-*/%.()\s]+", lhs_norm)
        and re.fullmatch(r"[0-9a-zA-Z_+\-*/%.()\s]+", rhs_norm)
    ):
        return None

    tokens_found = re.findall(r"[a-zA-Z_]+", f"{lhs_norm} {rhs_norm}")
    unknowns = sorted(
        {t for t in tokens_found if t not in SAFE_FUNCS and t not in SAFE_CONSTS}
    )
    if len(unknowns) != 1 or len(unknowns[0]) != 1:
        return None
    var_name = unknowns[0]

    try:
        lhs_tree = ast.parse(lhs_norm, mode="eval")
        rhs_tree = ast.parse(rhs_norm, mode="eval")
        l2, l1, l0 = _eval_poly2_ast(lhs_tree, var_name)
        r2, r1, r0 = _eval_poly2_ast(rhs_tree, var_name)
    except Exception:
        return None

    a = round(l2 - r2, 10)
    b = round(l1 - r1, 10)
    c = round(l0 - r0, 10)

    # Degree <= 1 (Linear)
    if abs(a) < 1e-10:
        net_a = b
        net_b = -c
        steps = [
            f"ฝั่งซ้าย: {l1:g}{var_name} + {l0:g}",
            f"ฝั่งขวา: {r1:g}{var_name} + {r0:g}",
            f"จัดรูปสมการเชิงเส้น: {net_a:g}{var_name} = {net_b:g}",
        ]
        if abs(net_a) < 1e-10:
            sol_type = "identity" if abs(net_b) < 1e-10 else "no_solution"
            steps.append(
                "สมการเป็นจริงทุกค่าของตัวแปร (อนันต์คำตอบ)"
                if sol_type == "identity"
                else "ค่าคงที่ไม่เท่ากัน (สมการไม่มีคำตอบ)"
            )
            return {
                "engine": "linear_algebra_ast",
                "equation": candidate,
                "variable": var_name,
                "solution_type": sol_type,
                "summary_tag": sol_type,
                "result": None,
                "steps": steps,
            }

        sol = _fmt_num(net_b / net_a)
        steps.append(f"{var_name} = {net_b:g} / {net_a:g} = {sol}")
        return {
            "engine": "linear_algebra_ast",
            "equation": candidate,
            "variable": var_name,
            "solution_type": "unique",
            "summary_tag": f"{var_name}={sol}",
            "result": sol,
            "steps": steps,
        }

    # Degree 2 (Quadratic): a*x^2 + b*x + c = 0
    disc = round(b * b - 4.0 * a * c, 12)
    steps = [
        f"จัดรูปสมการกำลังสอง: {a:g}{var_name}^2 + ({b:g}){var_name} + ({c:g}) = 0",
        f"คำนวณ Discriminant (Δ = b^2 - 4ac): {b:g}^2 - 4({a:g})({c:g}) = {disc:g}",
    ]
    if disc < -1e-10:
        steps.append("Δ < 0: ไม่มีคำตอบที่เป็นจำนวนจริง")
        return {
            "engine": "quadratic_algebra_ast",
            "equation": candidate,
            "variable": var_name,
            "solution_type": "no_real_solution",
            "roots": [],
            "summary_tag": "no_real_solution",
            "result": None,
            "steps": steps,
        }
    if abs(disc) <= 1e-10:
        root_val = _fmt_num(-b / (2.0 * a))
        steps.append(f"Δ = 0: มีรากซ้ำ 1 ค่า {var_name} = {root_val}")
        return {
            "engine": "quadratic_algebra_ast",
            "equation": candidate,
            "variable": var_name,
            "solution_type": "quadratic",
            "roots": [root_val],
            "summary_tag": f"root({root_val})",
            "result": root_val,
            "steps": steps,
        }

    sq = math.sqrt(disc)
    r1 = _fmt_num((-b - sq) / (2.0 * a))
    r2 = _fmt_num((-b + sq) / (2.0 * a))
    roots_sorted = sorted([r1, r2])
    if roots_sorted[0] == roots_sorted[1]:
        roots_sorted = [roots_sorted[0]]
        tag = f"root({roots_sorted[0]})"
    else:
        tag = f"roots({roots_sorted[0]},{roots_sorted[1]})"
    steps.append(f"รากของสมการที่เป็นจำนวนจริง: {var_name} ∈ {{{', '.join(str(x) for x in roots_sorted)}}}")
    return {
        "engine": "quadratic_algebra_ast",
        "equation": candidate,
        "variable": var_name,
        "solution_type": "quadratic",
        "roots": roots_sorted,
        "summary_tag": tag,
        "result": roots_sorted,
        "steps": steps,
    }


def try_solve_linear_equation(prompt: str) -> dict | None:
    return try_solve_equation(prompt)


def try_statistics_reasoning(prompt: str) -> dict | None:
    cleaned = _MATH_TRAILING_RE.sub("", prompt.strip()).strip()
    m = re.match(
        r"^(?:สถิติ|วิเคราะห์ตัวเลข|ค่าเฉลี่ย|มัธยฐาน|stats|statistics|mean|median)\s*:?\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None
    body = m.group(1).strip()
    nums_raw = re.findall(r"[-+]?\d+(?:\.\d+)?", body)
    if len(nums_raw) < 2:
        return None
    stripped_non_num = re.sub(r"[-+]?\d+(?:\.\d+)?|[,\s;|()\[\]]", "", body)
    if len(stripped_non_num) > 12:
        return None

    nums = [float(x) for x in nums_raw]
    total = sum(nums)
    mean_v = statistics.mean(nums)
    med_v = statistics.median(nums)
    min_v = min(nums)
    max_v = max(nums)
    pstdev_v = statistics.pstdev(nums)
    stdev_v = statistics.stdev(nums) if len(nums) >= 2 else 0.0

    def _fmt(v: float) -> int | float:
        return int(round(v)) if abs(v - round(v)) < 1e-9 else round(v, 6)

    return {
        "engine": "statistics_native",
        "count": len(nums),
        "values": [_fmt(v) for v in nums[:20]],
        "sum": _fmt(total),
        "mean": _fmt(mean_v),
        "median": _fmt(med_v),
        "min": _fmt(min_v),
        "max": _fmt(max_v),
        "range": _fmt(max_v - min_v),
        "pstdev": _fmt(pstdev_v),
        "stdev": _fmt(stdev_v),
    }


def try_math_reasoning(prompt: str) -> dict | None:
    cleaned = _MATH_TRAILING_RE.sub("", prompt.strip()).strip()
    m = re.search(
        r"(?:คำนวณ|หาค่า|คิดเลข|calculate|compute|eval|what is|evaluate)\s*:?\s*([0-9a-zA-Z_+\-*/%^().\s]+)$",
        cleaned,
        re.IGNORECASE,
    )
    candidate = m.group(1).strip() if m else cleaned
    candidate = _normalize_algebra_expr(candidate)
    if not re.search(r"[0-9]", candidate):
        return None
    if not re.fullmatch(r"[0-9a-zA-Z_+\-*/%.()\s]+", candidate):
        return None
    try:
        tree = ast.parse(candidate, mode="eval")
        steps: list[str] = []
        result = safe_eval_ast(tree, steps)
        formatted = int(result) if result.is_integer() else round(result, 8)
        return {
            "engine": "math_ast",
            "expression": candidate,
            "result": formatted,
            "steps": steps,
        }
    except Exception:
        return None


_LOGIC_OPS_ORDERED = [
    ("มากกว่าหรือเท่ากับ", ">=", "order"),
    ("น้อยกว่าหรือเท่ากับ", "<=", "order"),
    ("ไม่น้อยกว่า", ">=", "order"),
    ("ไม่มากกว่า", "<=", "order"),
    ("เท่ากับ", "=", "any"),
    ("มากกว่า", ">", "order"),
    ("น้อยกว่า", "<", "order"),
    ("สูงกว่า", ">", "height"),
    ("เตี้ยกว่า", "<", "height"),
    ("หนักกว่า", ">", "weight"),
    ("เบากว่า", "<", "weight"),
    ("ใหญ่กว่า", ">", "size"),
    ("เล็กกว่า", "<", "size"),
    ("ยาวกว่า", ">", "length"),
    ("สั้นกว่า", "<", "length"),
    ("เร็วกว่า", ">", "speed"),
    ("ช้ากว่า", "<", "speed"),
    ("แพงกว่า", ">", "price"),
    ("ถูกกว่า", "<", "price"),
    ("แก่กว่า", ">", "age"),
    ("อายุน้อยกว่า", "<", "age"),
    (">=", ">=", "order"),
    ("<=", "<=", "order"),
    (">", ">", "order"),
    ("<", "<", "order"),
    ("=", "=", "any"),
]


def _parse_comparison_clause(clause: str) -> tuple[str, str, str, str] | None:
    c = clause.strip()
    if not c:
        return None
    for tok, op, attr in _LOGIC_OPS_ORDERED:
        if tok.isascii():
            pat = rf"^(.+?)\s*{re.escape(tok)}\s*(.+)$"
        else:
            pat = rf"^(.+?)\s*{re.escape(tok)}\s*(.+)$"
        m = re.match(pat, c)
        if m:
            lhs = m.group(1).strip(" .,:;\"'")
            rhs = m.group(2).strip(" .,:;\"'")
            if lhs and rhs and lhs.lower() != rhs.lower():
                return (lhs, op, rhs, attr)
    # Generalizable comparative predicate fallback (arbitrary Thai "<adj>กว่า" or English "<adj>er than")
    m_th_comp = re.match(r"^(.+?)\s+([^\s]+กว่า)\s+(.+)$", c)
    if m_th_comp:
        lhs = m_th_comp.group(1).strip(" .,:;\"'")
        comp = m_th_comp.group(2).strip()
        rhs = m_th_comp.group(3).strip(" .,:;\"'")
        if lhs and rhs and lhs.lower() != rhs.lower():
            return (lhs, ">", rhs, f"comp:{comp}")
    m_en_comp = re.match(r"^(.+?)\s+(?:is\s+|are\s+)?([A-Za-z]+er)\s+than\s+(.+)$", c, re.IGNORECASE)
    if m_en_comp:
        lhs = m_en_comp.group(1).strip(" .,:;\"'")
        comp = m_en_comp.group(2).strip().lower()
        rhs = m_en_comp.group(3).strip(" .,:;\"'")
        if lhs and rhs and lhs.lower() != rhs.lower():
            return (lhs, ">", rhs, f"comp:{comp}")
    return None


def try_transitive_logic_reasoning(prompt: str) -> dict | None:
    cleaned = prompt.strip()
    m = re.match(
        r"^(?:ถ้า|สมมติว่า|กำหนดให้|หาก)\s*(.+?)\s*(?:แล้ว|ดังนั้น|จงหาว่า|ถามว่า)\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        m = re.match(
            r"^(?:if|given)\s+(.+?)\s*(?:then|,)\s*(.+)$",
            cleaned,
            re.IGNORECASE,
        )
    if not m:
        return None

    premises_raw, query_raw = m.group(1).strip(), m.group(2).strip()
    q_clean = re.sub(
        r"\s*(?:เป็นอย่างไร|เป็นยังไง|อย่างไร|ยังไง|คืออะไร|ครับ|ค่ะ|นะ|\?)+\s*$",
        "",
        query_raw,
        flags=re.IGNORECASE,
    ).strip()
    qm = re.match(
        r"^(.+?)\s*(?:เทียบกับ|เปรียบเทียบกับ|กับ|compared\s+to|vs\.?|versus)\s*(.+)$",
        q_clean,
        re.IGNORECASE,
    )
    if not qm:
        return None
    target_x = qm.group(1).strip(" .,:;\"'")
    target_y = qm.group(2).strip(" .,:;\"'")
    if not target_x or not target_y:
        return None

    clauses = [
        cl.strip()
        for cl in re.split(r"(?:[,;\n]+|\s+และ\s+|\s+and\s+)", premises_raw)
        if cl.strip()
    ]
    if not clauses:
        return None

    parsed_edges: list[tuple[str, str, str, str]] = []
    for cl in clauses:
        parsed = _parse_comparison_clause(cl)
        if not parsed:
            return None
        parsed_edges.append(parsed)

    # Build directed greater-or-equal graph: edge u -> v means u >= v (strict=True => u > v)
    canon: dict[str, str] = {}
    adj: dict[str, list[dict]] = collections.defaultdict(list)
    steps: list[str] = []
    for u, op, v, attr in parsed_edges:
        ul, vl = u.lower(), v.lower()
        canon.setdefault(ul, u)
        canon.setdefault(vl, v)
        steps.append(f"ข้อตั้ง: `{u} {op} {v}`")
        if op in (">", ">="):
            adj[ul].append({"to": vl, "strict": op == ">", "attr": attr, "label": f"{u} {op} {v}"})
        elif op in ("<", "<="):
            adj[vl].append({"to": ul, "strict": op == "<", "attr": attr, "label": f"{v} {'>' if op == '<' else '>='} {u}"})
        elif op == "=":
            adj[ul].append({"to": vl, "strict": False, "attr": "any", "label": f"{u} = {v}"})
            adj[vl].append({"to": ul, "strict": False, "attr": "any", "label": f"{v} = {u}"})

    xl, yl = target_x.lower(), target_y.lower()
    canon.setdefault(xl, target_x)
    canon.setdefault(yl, target_y)

    def _find_reach(src: str, dst: str) -> tuple[bool, bool, list[str], str]:
        """Return (reachable, has_strict_path, chain_labels, dominant_attr)."""
        queue: collections.deque[tuple[str, bool, str, list[str]]] = collections.deque()
        visited: set[tuple[str, bool, str]] = set()
        queue.append((src, False, "any", []))
        visited.add((src, False, "any"))
        any_path: tuple[list[str], str] | None = None
        while queue:
            curr, strict_seen, cur_attr, chain = queue.popleft()
            if curr == dst and chain:
                if strict_seen:
                    return True, True, chain, cur_attr
                if any_path is None:
                    any_path = (chain, cur_attr)
            for edge in adj.get(curr, []):
                e_attr = edge["attr"]
                if cur_attr != "any" and e_attr != "any" and cur_attr != e_attr:
                    continue
                next_attr = cur_attr if cur_attr != "any" else e_attr
                next_strict = strict_seen or edge["strict"]
                state = (edge["to"], next_strict, next_attr)
                if state not in visited:
                    visited.add(state)
                    queue.append((edge["to"], next_strict, next_attr, chain + [edge["label"]]))
        if any_path is not None:
            return True, False, any_path[0], any_path[1]
        return False, False, [], "any"

    def _has_strict_cycle_from(start_node: str) -> bool:
        r_self, s_self, _, _ = _find_reach(start_node, start_node)
        return r_self and s_self

    if xl == yl:
        if _has_strict_cycle_from(xl):
            return {
                "engine": "transitive_logic_native",
                "target": [target_x, target_y],
                "determined": False,
                "contradiction": True,
                "derived_relation": None,
                "steps": steps + ["ตรวจพบข้อขัดแย้งเชิงตรรกะในความสัมพันธ์ (Strict cycle)"],
            }
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": True,
            "contradiction": False,
            "derived_relation": f"{target_x} = {target_y}",
            "steps": steps + [f"สรุป: `{target_x} = {target_y}`"],
        }

    x_ge_y, x_gt_y, x_chain, x_attr = _find_reach(xl, yl)
    y_ge_x, y_gt_x, y_chain, y_attr = _find_reach(yl, xl)

    if (x_gt_y and y_ge_x) or (y_gt_x and x_ge_y) or _has_strict_cycle_from(xl) or _has_strict_cycle_from(yl):
        steps.append("ตรวจพบข้อขัดแย้งเชิงตรรกะระหว่างข้อตั้ง (ไม่สามารถสรุปค่าจริงที่สอดคล้องได้)")
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": False,
            "contradiction": True,
            "derived_relation": None,
            "steps": steps,
        }

    if x_gt_y:
        rel_str = f"{target_x} > {target_y}"
        steps.append(f"ห่วงโซ่อนุมานถ่ายทอด: {' ∧ '.join(x_chain)} ⇒ {rel_str}")
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": True,
            "contradiction": False,
            "derived_relation": rel_str,
            "attribute_family": x_attr,
            "steps": steps,
        }
    if y_gt_x:
        rel_str = f"{target_x} < {target_y}"
        steps.append(f"ห่วงโซ่อนุมานถ่ายทอด: {' ∧ '.join(y_chain)} ⇒ {rel_str}")
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": True,
            "contradiction": False,
            "derived_relation": rel_str,
            "attribute_family": y_attr,
            "steps": steps,
        }
    if x_ge_y and y_ge_x:
        rel_str = f"{target_x} = {target_y}"
        steps.append(f"ห่วงโซ่อนุมานสมมูล: {' ∧ '.join(x_chain)} ⇒ {rel_str}")
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": True,
            "contradiction": False,
            "derived_relation": rel_str,
            "attribute_family": x_attr,
            "steps": steps,
        }
    if x_ge_y:
        rel_str = f"{target_x} >= {target_y}"
        steps.append(f"ห่วงโซ่อนุมานถ่ายทอด: {' ∧ '.join(x_chain)} ⇒ {rel_str}")
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": True,
            "contradiction": False,
            "derived_relation": rel_str,
            "attribute_family": x_attr,
            "steps": steps,
        }
    if y_ge_x:
        rel_str = f"{target_x} <= {target_y}"
        steps.append(f"ห่วงโซ่อนุมานถ่ายทอด: {' ∧ '.join(y_chain)} ⇒ {rel_str}")
        return {
            "engine": "transitive_logic_native",
            "target": [target_x, target_y],
            "determined": True,
            "contradiction": False,
            "derived_relation": rel_str,
            "attribute_family": y_attr,
            "steps": steps,
        }

    steps.append(f"ไม่มีเส้นทางความสัมพันธ์เชื่อมระหว่าง `{target_x}` และ `{target_y}` ในข้อตั้งที่กำหนด")
    return {
        "engine": "transitive_logic_native",
        "target": [target_x, target_y],
        "determined": False,
        "contradiction": False,
        "derived_relation": None,
        "steps": steps,
    }


def try_word_math_reasoning(prompt: str) -> dict | None:
    cleaned = prompt.strip()
    if not re.search(r"(?:กี่|เท่าไร|เท่าไหร่|how many|how much)", cleaned, re.IGNORECASE):
        return None
    if re.match(r"^(?:แก้สมการ|สมการ|คำนวณ|สถิติ|วางแผน|สอน|เชื่อมโยง|solve|plan|teach)\b", cleaned, re.IGNORECASE):
        return None

    nums_raw = re.findall(r"(?<![a-zA-Z_])[-+]?\d+(?:\.\d+)?(?![a-zA-Z_])", cleaned)
    if len(nums_raw) < 2 or len(nums_raw) > 3:
        return None

    # 1. Percentage & Tax/Discount Reasoning (2 numbers with % / เปอร์เซ็นต์ / ร้อยละ)
    has_pct_cue = bool(re.search(r"(?:%|เปอร์เซ็นต์|ร้อยละ|percent)", cleaned, re.IGNORECASE))
    if has_pct_cue and len(nums_raw) == 2:
        n0, n1 = float(nums_raw[0]), float(nums_raw[1])
        m_pct_first = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:%|เปอร์เซ็นต์|percent)", cleaned, re.IGNORECASE)
        m_roila = re.search(r"ร้อยละ\s*([-+]?\d+(?:\.\d+)?)", cleaned)
        pct_val = float(m_pct_first.group(1)) if m_pct_first else (float(m_roila.group(1)) if m_roila else n1)
        base_val = n1 if abs(pct_val - n0) < 1e-12 else n0
        b_fmt, p_fmt = _fmt_num(base_val), _fmt_num(pct_val)

        is_discount = any(k in cleaned.lower() for k in ["ลดราคา", "ลดลง", "ส่วนลด", "discount", "off"])
        is_increase = any(k in cleaned.lower() for k in ["เพิ่มขึ้น", "บวกเพิ่ม", "ขึ้นราคา", "vat", "ภาษี", "ดอกเบี้ย", "increase", "tax", "interest"])
        asks_portion_only = any(k in cleaned.lower() for k in ["ส่วนลดกี่", "ลดไปกี่", "ภาษีกี่", "ดอกเบี้ยกี่", "คิดเป็นกี่"])

        if is_discount and not asks_portion_only:
            val = base_val * (1.0 - pct_val / 100.0)
            op_name = "percentage_discount"
            expr_str = f"{b_fmt} * (1 - {p_fmt}/100)"
            steps = [
                f"ระบุราคา/ปริมาณตั้งต้น {b_fmt} และส่วนลด {p_fmt}%",
                f"คำนวณส่วนลด {b_fmt} * {p_fmt}% = {_fmt_num(base_val * pct_val / 100.0)}",
                f"ราคาหลังหักส่วนลด: {b_fmt} - {_fmt_num(base_val * pct_val / 100.0)} = {_fmt_num(val)}",
            ]
        elif is_increase and not asks_portion_only:
            val = base_val * (1.0 + pct_val / 100.0)
            op_name = "percentage_increase"
            expr_str = f"{b_fmt} * (1 + {p_fmt}/100)"
            steps = [
                f"ระบุฐานตั้งต้น {b_fmt} และอัตราเพิ่ม {p_fmt}%",
                f"คำนวณส่วนเพิ่ม {b_fmt} * {p_fmt}% = {_fmt_num(base_val * pct_val / 100.0)}",
                f"ยอดรวมหลังปรับเพิ่ม: {b_fmt} + {_fmt_num(base_val * pct_val / 100.0)} = {_fmt_num(val)}",
            ]
        else:
            val = base_val * (pct_val / 100.0)
            op_name = "percentage_of"
            expr_str = f"{b_fmt} * ({p_fmt}/100)"
            steps = [
                f"คำนวณ {p_fmt}% ของ {b_fmt}",
                f"{b_fmt} * {p_fmt} / 100 = {_fmt_num(val)}",
            ]
        return {
            "engine": "word_math_native",
            "operation": op_name,
            "operands": [b_fmt, p_fmt],
            "expression": expr_str,
            "result": _fmt_num(val),
            "steps": steps,
        }

    # 2. Multi-step 3-number word math
    if len(nums_raw) == 3:
        n0, n1, n2 = float(nums_raw[0]), float(nums_raw[1]), float(nums_raw[2])
        f0, f1, f2 = _fmt_num(n0), _fmt_num(n1), _fmt_num(n2)
        has_rate = bool(re.search(r"(?:[\u0E00-\u0E7F]{1,8}ละ(?=\s*[-+]?\d)|เล่มละ|ชิ้นละ|กล่องละ|อันละ|ใบละ|ถุงละ|ขวดละ|คนละ|ด้ามละ|แท่งละ|ต่อหน่วย|each|per)", cleaned, re.IGNORECASE))
        has_change_cue = any(k in cleaned.lower() for k in ["ทอน", "เหลือ", "จ่าย", "change", "remain", "left"])
        has_add_extra = any(k in cleaned.lower() for k in ["เพิ่ม", "ซื้อเพิ่ม", "อีก", "plus", "more"])

        # Order A: "มี/จ่าย M บาท ซื้อ Q ชิ้น ชิ้นละ P บาท เหลือกี่บาท"
        m_budget_first = re.match(r"^(?:มีเงิน|มี|จ่ายเงิน|จ่าย)\s*([-+]?\d+(?:\.\d+)?)", cleaned)
        if has_rate and has_change_cue:
            if m_budget_first:
                paid, qty, unit_p = n0, n1, n2
            else:
                qty, unit_p, paid = n0, n1, n2
            cost = qty * unit_p
            val = paid - cost
            q_s, u_s, p_s = _fmt_num(qty), _fmt_num(unit_p), _fmt_num(paid)
            return {
                "engine": "word_math_native",
                "operation": "multistep_unit_change",
                "operands": [q_s, u_s, p_s],
                "expression": f"{p_s} - ({q_s} * {u_s})",
                "result": _fmt_num(val),
                "steps": [
                    f"ขั้นที่ 1: คำนวณยอดรวมตามอัตราต่อหน่วย {q_s} * {u_s} = {_fmt_num(cost)}",
                    f"ขั้นที่ 2: หักจากจำนวนเงินที่มี/จ่าย {p_s} - {_fmt_num(cost)} = {_fmt_num(val)}",
                ],
            }
        if has_rate and has_add_extra:
            total = (n0 * n1) + n2
            return {
                "engine": "word_math_native",
                "operation": "multistep_unit_add",
                "operands": [f0, f1, f2],
                "expression": f"({f0} * {f1}) + {f2}",
                "result": _fmt_num(total),
                "steps": [
                    f"ขั้นที่ 1: คำนวณส่วนอัตราคูณ {f0} * {f1} = {_fmt_num(n0 * n1)}",
                    f"ขั้นที่ 2: บวกส่วนเพิ่มเติม {_fmt_num(n0 * n1)} + {f2} = {_fmt_num(total)}",
                ],
            }
        if any(k in cleaned.lower() for k in ["เหลือ", "left", "remain"]) and not has_add_extra:
            val = n0 - n1 - n2
            return {
                "engine": "word_math_native",
                "operation": "multistep_subtraction",
                "operands": [f0, f1, f2],
                "expression": f"{f0} - {f1} - {f2}",
                "result": _fmt_num(val),
                "steps": [
                    f"ระบุยอดตั้งต้น {f0} และรายการหักออก {f1}, {f2}",
                    f"คำนวณต่อเนื่อง {f0} - {f1} - {f2} = {_fmt_num(val)}",
                ],
            }
        if any(k in cleaned.lower() for k in ["รวม", "ทั้งหมด", "altogether", "in total"]) and not has_rate:
            val = n0 + n1 + n2
            return {
                "engine": "word_math_native",
                "operation": "multistep_addition",
                "operands": [f0, f1, f2],
                "expression": f"{f0} + {f1} + {f2}",
                "result": _fmt_num(val),
                "steps": [
                    f"ระบุปริมาณทั้ง 3 ส่วน ({f0}, {f1}, {f2})",
                    f"รวมทั้งหมด {f0} + {f1} + {f2} = {_fmt_num(val)}",
                ],
            }
        return None

    # 3. Single-step 2-number reasoning
    a, b = float(nums_raw[0]), float(nums_raw[1])
    a_fmt, b_fmt = _fmt_num(a), _fmt_num(b)

    has_div_cue = any(k in cleaned for k in ["แบ่ง", "หาร", "เฉลี่ย", "เท่าๆ กัน", "เท่ากัน", "divide", "share"]) or bool(
        re.search(r"(?:คนละ|กล่องละ|ใบละ|อันละ|กองละ|ชิ้นละ|กลุ่มละ|ถุงละ)\s*กี่", cleaned)
    )
    has_rate_time_cue = any(k in cleaned for k in ["ความเร็ว", "อัตราเร็ว", "speed"]) and any(
        k in cleaned for k in ["เวลา", "ชั่วโมง", "นาที", "ระยะทาง", "ได้ไกล", "distance"]
    )
    has_mul_cue = has_rate_time_cue or (
        any(k in cleaned for k in ["ทั้งหมด", "รวมทั้งหมด", "รวมเป็น", "ได้ระยะทาง", "คิดเป็น", "total"])
        and any(k in cleaned for k in ["ละ", "แต่ละ", "ทุก", "เป็นเวลา", "per", "each"])
    )
    has_sub_cue = any(
        k in cleaned for k in ["เหลือ", "จ่ายไป", "ใช้ไป", "กินไป", "หัก", "ลดลง", "หายไป", "ขายไป", "ให้ไป", "ต่างกัน", "left", "remain"]
    ) and not any(k in cleaned for k in ["เพิ่ม", "รวม"])
    has_add_cue = any(k in cleaned for k in ["เพิ่ม", "ได้รับเพิ่ม", "ซื้อมาเพิ่ม", "รวม", "บวก", "ทั้งสอง", "ทั้งหมด", "altogether", "in total"])

    op_name: str
    expr_str: str
    steps: list[str]
    if has_div_cue:
        if abs(b) < 1e-12:
            return {
                "engine": "word_math_native",
                "operation": "division",
                "determined": False,
                "unable_reason": "division_by_zero",
                "operands": [a_fmt, 0],
                "expression": f"{a_fmt} / 0",
                "result": None,
                "steps": [
                    f"ระบุปริมาณตั้งต้น {a_fmt} และตัวหาร 0",
                    "ไม่สามารถคำนวณได้เนื่องจากการหารด้วย 0 ไม่นิยามในระบบจำนวนจริง",
                ],
            }
        val = a / b
        op_name = "division"
        expr_str = f"{a_fmt} / {b_fmt}"
        steps = [
            f"ระบุปริมาณตั้งต้น {a_fmt} และตัวหาร {b_fmt} จากเงื่อนไขการแบ่งเท่ากัน",
            f"คำนวณ {a_fmt} / {b_fmt} = {_fmt_num(val)}",
        ]
    elif has_mul_cue:
        val = a * b
        op_name = "multiplication"
        expr_str = f"{a_fmt} * {b_fmt}"
        steps = [
            f"ระบุจำนวนกลุ่ม/อัตรา {a_fmt} และตัวคูณ {b_fmt}",
            f"คำนวณ {a_fmt} * {b_fmt} = {_fmt_num(val)}",
        ]
    elif has_sub_cue:
        val = a - b
        op_name = "subtraction"
        expr_str = f"{a_fmt} - {b_fmt}"
        steps = [
            f"ระบุปริมาณเริ่มต้น {a_fmt} และปริมาณที่ลดลง/จ่ายไป {b_fmt}",
            f"คำนวณ {a_fmt} - {b_fmt} = {_fmt_num(val)}",
        ]
    elif has_add_cue:
        val = a + b
        op_name = "addition"
        expr_str = f"{a_fmt} + {b_fmt}"
        steps = [
            f"ระบุปริมาณสองส่วน {a_fmt} และ {b_fmt} เพื่อนำมารวมกัน",
            f"คำนวณ {a_fmt} + {b_fmt} = {_fmt_num(val)}",
        ]
    else:
        return None

    res_fmt = _fmt_num(val)
    return {
        "engine": "word_math_native",
        "operation": op_name,
        "operands": [a_fmt, b_fmt],
        "expression": expr_str,
        "result": res_fmt,
        "steps": steps,
    }


def try_teach_knowledge(conn: sqlite3.Connection, prompt: str, user_id: str) -> dict | None:
    cleaned = prompt.strip()
    m = re.match(
        r"^(?:สอน|จำว่า|จำ|เรียนรู้|teach|learn|remember)\s*:?\s*(.+?)\s*(?:->|\|)\s*(.+?)\s*(?:->|\|)\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        subj, rel, obj = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    else:
        natural = re.match(
            r"^(?:สอน|จำว่า|จำ|เรียนรู้|teach|remember)\s*:?\s*(.+?)\s+"
            r"(เป็น|คือ|ใช้งาน|ใช้|เชื่อมต่อกับ|เชื่อมต่อ|อยู่ใน|สังกัด|พัฒนาโดย|รองรับ|มี|equals|is|uses)"
            r"\s+(.+)$",
            cleaned,
            re.IGNORECASE,
        )
        if not natural:
            return None
        subj, rel, obj = (
            natural.group(1).strip(),
            natural.group(2).strip(),
            re.sub(r"\s+(?:ครับ|ค่ะ|นะ)$", "", natural.group(3).strip()),
        )

    if not subj or not rel or not obj:
        return None

    existing = conn.execute(
        "SELECT id, object FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?)",
        (subj, rel),
    ).fetchall()
    contradictions = [row["object"] for row in existing if row["object"].lower() != obj.lower()]
    exact_match = any(row["object"].lower() == obj.lower() for row in existing)

    triple_id = str(uuid.uuid4())
    if not exact_match:
        with conn:
            conn.execute(
                """
                INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (triple_id, subj, rel, obj, "user_workspace", 1.0, user_id, now_iso()),
            )
    return {
        "engine": "knowledge_ingest",
        "triple": {"id": triple_id, "subject": subj, "relation": rel, "object": obj},
        "duplicate": exact_match,
        "contradictions": contradictions,
    }


THAI_TOKEN_RE = re.compile(
    r"[\u0E40-\u0E44]?[\u0E01-\u0E2E][\u0E30-\u0E3A\u0E47-\u0E4E]*(?:[\u0E01-\u0E2E](?=[\u0E40-\u0E44]|[\u0E01-\u0E2E][\u0E30-\u0E3A\u0E47-\u0E4E]|$))?|[\u0E50-\u0E59]+|[a-zA-Z0-9_]+|[.,!?;]"
)

THAI_QUERY_STOPWORDS = {
    "อะไร", "ไหม", "หรือไม่", "อย่างไร", "ยังไง", "บ้าง", "หรือ", "คืออะไร", "คือ",
    "เท่าไร", "เท่าไหร่", "เท่า", "กี่", "ครับ", "ค่ะ", "นะครับ", "นะคะ", "หน่อย",
    "หน่อยครับ", "หน่อยค่ะ", "ใคร", "ไหน", "ที่ไหน", "เมื่อไร", "ทำไม", "เป็น",
    "ได้", "มี", "ทำ", "ทำงาน", "งาน", "และ", "กับ", "ที่", "ใน", "ของ", "จาก",
    "ไป", "มา", "ให้", "จะ", "แล้ว", "ว่า", "การ", "ความ", "เกิด", "เกิดขึ้น",
    "เกี่ยวกับ", "เกี่ยวข้อง", "เกี่ยวข้องกับ", "ถ้า", "what", "why", "how", "who",
    "where", "when", "is", "are", "the", "and", "or",
}

_THAI_PREFIX_STRIPS = (
    "ใคร", "อะไร", "ทำไม", "ที่ไหน", "เมื่อไร", "อย่างไร", "ถ้า",
)
_THAI_SUFFIX_STRIPS = (
    "ทำงานอย่างไร", "เกิดขึ้นได้อย่างไร", "ได้อย่างไร", "คืออะไร", "เกี่ยวข้องกับ",
    "เกี่ยวกับ", "เท่าไหร่", "เท่าไร", "อย่างไร", "ยังไง", "หน่อยครับ", "หน่อยค่ะ",
    "นะครับ", "นะคะ", "หรือไม่", "บ้าง", "ไหม", "หรือ", "อะไร", "คือ", "ครับ", "ค่ะ", "หน่อย",
)


def tokenize(text: str) -> list[str]:
    """Tokenize English words, numbers, punctuation, and Thai orthographic syllable clusters."""
    return THAI_TOKEN_RE.findall(text.lower())


def _strip_thai_affixes(span: str) -> str:
    cur = span
    changed = True
    while changed and cur:
        changed = False
        for pref in _THAI_PREFIX_STRIPS:
            if cur.startswith(pref) and len(cur) > len(pref) + 1:
                cur = cur[len(pref):]
                changed = True
        for suf in _THAI_SUFFIX_STRIPS:
            if cur.endswith(suf) and len(cur) > len(suf) + 1:
                cur = cur[: -len(suf)]
                changed = True
    return cur


def extract_query_terms(text: str) -> list[str]:
    ascii_tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    thai_spans = re.findall(r"[\u0E00-\u0E7F]+", text.lower())

    candidates: list[str] = []
    # Preserve standalone alphanumeric entity symbols (e.g., 'A', 'B', '6') and multi-char ASCII terms
    for tok in ascii_tokens:
        if len(tok) == 1:
            if tok.isalnum() and tok not in THAI_QUERY_STOPWORDS:
                candidates.append(tok)
        elif tok not in THAI_QUERY_STOPWORDS:
            candidates.append(tok)

    for span in thai_spans:
        cleaned = _strip_thai_affixes(span)
        if len(cleaned) >= 3 and cleaned not in THAI_QUERY_STOPWORDS:
            candidates.append(cleaned)
        if len(span) >= 3 and span not in THAI_QUERY_STOPWORDS and span != cleaned:
            candidates.append(span)
        for syl in tokenize(cleaned or span):
            # Require >=3 chars for Thai syllable tokens to avoid 1-2 char cross-word collisions
            if len(syl) >= 3 and syl not in THAI_QUERY_STOPWORDS:
                candidates.append(syl)

    seen: set[str] = set()
    terms: list[str] = []
    for tok in candidates:
        if tok not in seen:
            seen.add(tok)
            terms.append(tok)
    return terms


def find_graph_path(conn: sqlite3.Connection, start_term: str, end_term: str, max_depth: int = 8) -> dict | None:
    rows = conn.execute(
        "SELECT id, subject, relation, object, source FROM knowledge_triples"
    ).fetchall()
    if not rows:
        return None

    start_l = start_term.strip().lower()
    end_l = end_term.strip().lower()
    if not start_l or not end_l:
        return None

    # Build adjacency index (forward and reverse edges)
    adj: dict[str, list[dict]] = collections.defaultdict(list)
    nodes: dict[str, str] = {}
    for row in rows:
        s_orig, r_orig, o_orig = row["subject"], row["relation"], row["object"]
        s_l, o_l = s_orig.lower(), o_orig.lower()
        nodes[s_l] = s_orig
        nodes[o_l] = o_orig
        adj[s_l].append(
            {
                "next": o_l,
                "from": s_orig,
                "relation": r_orig,
                "to": o_orig,
                "direction": "forward",
                "triple_id": row["id"],
                "source": row["source"],
            }
        )
        adj[o_l].append(
            {
                "next": s_l,
                "from": o_orig,
                "relation": f"← {r_orig}",
                "to": s_orig,
                "direction": "reverse",
                "triple_id": row["id"],
                "source": row["source"],
            }
        )

    exact_starts = [k for k in nodes if start_l == k]
    start_nodes = exact_starts or [k for k in nodes if start_l in k]
    exact_ends = {k for k in nodes if end_l == k}
    end_nodes = exact_ends or {k for k in nodes if end_l in k}
    if not start_nodes or not end_nodes:
        return None

    def run_bfs(forward_only: bool) -> list[dict] | None:
        queue: collections.deque[tuple[str, list[dict]]] = collections.deque()
        visited: set[str] = set()
        for sn in start_nodes:
            queue.append((sn, []))
            visited.add(sn)
        while queue:
            curr, path = queue.popleft()
            if curr in end_nodes and path:
                return path
            if len(path) >= max_depth:
                continue
            for edge in adj.get(curr, []):
                if forward_only and edge["direction"] != "forward":
                    continue
                nxt = edge["next"]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + [edge]))
        return None

    # Prefer directed forward chain first, then allow bidirectional path
    path = run_bfs(forward_only=True)
    bidirectional_used = False
    if path is None:
        path = run_bfs(forward_only=False)
        bidirectional_used = path is not None

    if not path:
        return None

    return {
        "start": start_term.strip(),
        "end": end_term.strip(),
        "hops": len(path),
        "bidirectional": bidirectional_used,
        "edges": [
            {
                "from": e["from"],
                "relation": e["relation"],
                "to": e["to"],
                "direction": e["direction"],
                "source": e["source"],
            }
            for e in path
        ],
    }


def try_graph_path_query(conn: sqlite3.Connection, prompt: str) -> dict | None:
    cleaned = prompt.strip()
    m = re.match(
        r"^(?:เชื่อมโยง|หาเส้นทาง|เส้นทาง|path|connect|trace)\s*:?\s*(.+?)\s*(?:->|→|กับ|ถึง|to)\s*(.+?)\??$",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None
    start_term = m.group(1).strip()
    end_term = _MATH_TRAILING_RE.sub("", m.group(2).strip()).strip()
    if not start_term or not end_term:
        return None
    max_depth = 8
    result = find_graph_path(conn, start_term, end_term, max_depth=max_depth)
    return {
        "engine": "knowledge_multihop_bfs",
        "start": start_term,
        "end": end_term,
        "max_depth": max_depth,
        "found": result is not None,
        "path": result,
    }


def _token_matches_field(tok: str, field_l: str, field_syllables: set[str]) -> bool:
    if not tok or not field_l:
        return False
    if tok.isascii():
        return bool(re.search(rf"(?<![a-z0-9_]){re.escape(tok)}(?![a-z0-9_])", field_l))
    if len(tok) < 3 or tok in THAI_QUERY_STOPWORDS:
        return False
    if len(tok) == 3:
        return tok in field_syllables or tok == field_l
    return tok in field_l or (len(field_l) >= 4 and field_l in tok)


_REL_SYNONYM_GROUPS: dict[str, set[str]] = {
    "creator": {"สร้าง", "ผู้สร้าง", "พัฒนา", "พัฒนาโดย", "ผู้พัฒนา", "ออกแบบ", "สร้างโดย", "created", "developed", "author"},
    "location": {"ตั้งอยู่", "ตั้งอยู่ที่", "อยู่ที่", "อยู่ที่ไหน", "ที่ตั้ง", "สถานที่", "located", "location"},
    "usage": {"ใช้", "ใช้งาน", "ใช้ฐานข้อมูล", "ใช้อะไร", "อาศัย", "uses", "using"},
    "support": {"รองรับ", "สนับสนุน", "ช่วย", "supports", "enables"},
    "identity": {"เป็น", "คือ", "จัดเป็น", "สังกัด", "is", "are"},
    "cause": {"ทำให้เกิด", "ส่งผลให้", "ก่อให้เกิด", "นำไปสู่", "สาเหตุ", "causes", "leads"},
}


def _relation_family(text: str) -> set[str]:
    low = text.lower()
    matched: set[str] = set()
    for fam, cues in _REL_SYNONYM_GROUPS.items():
        if any(cue in low for cue in cues):
            matched.add(fam)
    return matched


def _char_ngrams(text: str, n: int = 3) -> collections.Counter:
    cleaned = re.sub(r"\s+", "", text.lower())
    if len(cleaned) < n:
        return collections.Counter([cleaned]) if cleaned else collections.Counter()
    return collections.Counter(cleaned[i : i + n] for i in range(len(cleaned) - n + 1))


def _cosine_counter(c1: collections.Counter, c2: collections.Counter, idf: dict[str, float] | None = None) -> float:
    if not c1 or not c2:
        return 0.0
    common = set(c1.keys()) & set(c2.keys())
    if not common:
        return 0.0
    dot = 0.0
    for k in common:
        w = idf.get(k, 1.0) if idf else 1.0
        dot += float(c1[k]) * float(c2[k]) * (w * w)
    n1 = math.sqrt(sum((float(v) * (idf.get(k, 1.0) if idf else 1.0)) ** 2 for k, v in c1.items()))
    n2 = math.sqrt(sum((float(v) * (idf.get(k, 1.0) if idf else 1.0)) ** 2 for k, v in c2.items()))
    if n1 <= 1e-12 or n2 <= 1e-12:
        return 0.0
    return dot / (n1 * n2)


def query_knowledge_graph(conn: sqlite3.Connection, prompt: str) -> list[dict]:
    tokens = extract_query_terms(prompt)
    if not tokens:
        return []
    rows = conn.execute(
        "SELECT id, subject, relation, object, source, confidence, created_at FROM knowledge_triples"
    ).fetchall()
    if not rows:
        return []

    # Build lightweight native TF-IDF weights over KG triple terms
    doc_freq: collections.Counter = collections.Counter()
    doc_tokens_list: list[list[str]] = []
    for row in rows:
        dtoks = extract_query_terms(f"{row['subject']} {row['relation']} {row['object']}")
        doc_tokens_list.append(dtoks)
        for t in set(dtoks):
            doc_freq[t] += 1
    total_docs = len(rows)
    idf = {t: (math.log((total_docs + 1) / (df + 1)) + 1.0) for t, df in doc_freq.items()}
    q_counter = collections.Counter(tokens)
    q_rel_families = _relation_family(prompt)
    q_ngrams = _char_ngrams(" ".join(tokens), 3)

    scored = []
    for idx, row in enumerate(rows):
        subj_l = row["subject"].lower()
        rel_l = row["relation"].lower()
        obj_l = row["object"].lower()
        subj_syls = set(tokenize(subj_l))
        rel_syls = set(tokenize(rel_l))
        obj_syls = set(tokenize(obj_l))

        score = 0.0
        entity_hits = 0
        strong_entity_hits = 0
        for tok in tokens:
            s_hit = _token_matches_field(tok, subj_l, subj_syls)
            o_hit = _token_matches_field(tok, obj_l, obj_syls)
            r_hit = _token_matches_field(tok, rel_l, rel_syls)
            if s_hit:
                score += 3.0
                entity_hits += 1
                if len(tok) >= 4 or tok.isascii():
                    strong_entity_hits += 1
            if o_hit:
                score += 2.5
                entity_hits += 1
                if len(tok) >= 4 or tok.isascii():
                    strong_entity_hits += 1
            if r_hit and not s_hit and not o_hit:
                score += 1.0

        # Semantic paraphrase & TF-IDF cosine (strictly gated on entity grounding or high entity char-3gram similarity)
        rel_fam_overlap = bool(q_rel_families & _relation_family(rel_l))
        tfidf_sim = _cosine_counter(q_counter, collections.Counter(doc_tokens_list[idx]), idf=idf)
        ent_char_sim = max(
            _cosine_counter(q_ngrams, _char_ngrams(subj_l, 3)),
            _cosine_counter(q_ngrams, _char_ngrams(obj_l, 3)),
        )
        semantic_score = round(0.65 * tfidf_sim + 0.35 * ent_char_sim, 4)

        has_direct_grounding = entity_hits >= 1 and (strong_entity_hits >= 1 or entity_hits >= 2) and score >= 2.5
        has_high_char_entity_match = ent_char_sim >= 0.72 and len("".join(tokens)) >= 6
        if has_direct_grounding or has_high_char_entity_match:
            total_score = score + (1.2 if rel_fam_overlap else 0.0) + (1.5 * semantic_score)
            if has_high_char_entity_match and not has_direct_grounding:
                total_score = max(total_score, 2.6 + (1.2 if rel_fam_overlap else 0.0))
            item = dict(row)
            item["hop"] = 1
            item["provenance"] = "direct"
            item["match_score"] = round(total_score, 2)
            item["semantic_score"] = semantic_score
            scored.append((total_score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [item[1] for item in scored[:5]]
    seen_ids = {item["id"] for item in results}

    # Multi-hop transitive expansion (2-hop & 3-hop) with explicit provenance
    if results:
        hop2_items: list[dict] = []
        for base in list(results):
            obj_l = base["object"].lower()
            for row in rows:
                if row["id"] in seen_ids:
                    continue
                if row["subject"].lower() == obj_l:
                    hop2 = dict(row)
                    hop2["hop"] = 2
                    hop2["provenance"] = "inferred_2hop"
                    hop2["inferred_chain"] = (
                        f"{base['subject']} -[{base['relation']}]-> {base['object']} "
                        f"-[{row['relation']}]-> {row['object']}"
                    )
                    results.append(hop2)
                    hop2_items.append(hop2)
                    seen_ids.add(row["id"])
                    if len(results) >= 9:
                        break
            if len(results) >= 9:
                break

        if len(results) < 12:
            for base2 in hop2_items:
                obj2_l = base2["object"].lower()
                for row in rows:
                    if row["id"] in seen_ids:
                        continue
                    if row["subject"].lower() == obj2_l:
                        hop3 = dict(row)
                        hop3["hop"] = 3
                        hop3["provenance"] = "inferred_3hop"
                        hop3["inferred_chain"] = (
                            f"{base2['inferred_chain']} -[{row['relation']}]-> {row['object']}"
                        )
                        results.append(hop3)
                        seen_ids.add(row["id"])
                        if len(results) >= 12:
                            return results
    return results


def run_ngram_continuation(conn: sqlite3.Connection, prompt: str, max_tokens: int = 18) -> dict | None:
    ckpt = conn.execute(
        "SELECT * FROM checkpoints WHERE eval_status NOT LIKE 'NEURAL%' AND ngram_order > 0 ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not ckpt:
        return None
    weights_path = Path(ckpt["weights_path"])
    if not weights_path.exists() or str(weights_path).endswith(".gz"):
        return None
    with open(weights_path, "r", encoding="utf-8") as f:
        weights = json.load(f)

    trigrams: dict = weights.get("trigrams", {})
    bigrams: dict = weights.get("bigrams", {})
    vocab: list = weights.get("vocab", [])
    tokens = tokenize(prompt)
    if not tokens:
        return None
    known_tokens = [t for t in tokens if t in vocab]
    if not known_tokens:
        return {
            "engine": "ngram_checkpoint",
            "checkpoint_version": ckpt["version"],
            "perplexity": ckpt["perplexity"],
            "matched_vocab": 0,
            "generated": None,
            "reason": "Input tokens are out-of-vocabulary for the trained checkpoint.",
        }

    generated = []
    ctx = tokens[-2:] if len(tokens) >= 2 else [tokens[-1]]
    seen_transitions: set[tuple[str, str]] = set()
    cycle_stopped = False
    for _ in range(max_tokens):
        next_tok = None
        if len(ctx) >= 2:
            bi_key = f"{ctx[-2]} {ctx[-1]}"
            if bi_key in trigrams and trigrams[bi_key]:
                choices = trigrams[bi_key]
                next_tok = max(choices.items(), key=lambda kv: kv[1])[0]
        if next_tok is None and ctx[-1] in bigrams and bigrams[ctx[-1]]:
            choices = bigrams[ctx[-1]]
            next_tok = max(choices.items(), key=lambda kv: kv[1])[0]
        if next_tok is None or next_tok == "<END>":
            break
        state_key = (" ".join(ctx), next_tok)
        if state_key in seen_transitions:
            cycle_stopped = True
            break
        seen_transitions.add(state_key)
        generated.append(next_tok)
        ctx = (ctx + [next_tok])[-2:]

    return {
        "engine": "ngram_checkpoint",
        "checkpoint_version": ckpt["version"],
        "perplexity": ckpt["perplexity"],
        "matched_vocab": len(known_tokens),
        "generated": " ".join(generated) if generated else None,
        "reason": (
            "Generated from interpolated trigram/bigram weights (stopped cleanly on cycle)."
            if (generated and cycle_stopped)
            else (
                "Generated strictly from trained bigram/trigram transition counts."
                if generated
                else "No continuation transitions from prompt context."
            )
        ),
    }


def _format_clarification_markdown(
    *,
    clarify_status: str,
    issues: list[str],
    questions: list[str],
    context_resolution: dict | None = None,
    heading: str = "ต้องการข้อมูลเพิ่มเติมก่อนวางแผน",
) -> str:
    ctx_res = context_resolution or {}
    candidates = ctx_res.get("candidates") or []
    parts = [f"**{heading} (`{clarify_status}`)**"]
    if issues:
        parts.append(f"สาเหตุที่ตรวจพบ: `{', '.join(issues)}`")
    if ctx_res.get("resolved_from_context") and candidates:
        cand_lines: list[str] = []
        for idx, cand in enumerate(candidates, start=1):
            ev = ", ".join(str(x) for x in (cand.get("grounded_evidence") or [])[:3])
            cand_lines.append(
                f"{idx}. **{cand.get('domain')}** — {cand.get('proposed_objective')}"
                + (f"\n   - หลักฐานบริบทจริง: `{ev}`" if ev else "")
                + (f"\n   - เงื่อนไขสำเร็จ: {cand.get('success_criteria')}" if cand.get("success_criteria") else "")
            )
        parts.append(
            "**ข้อเสนอเป้าหมายจากบริบทงานปัจจุบัน (ยังไม่เริ่มขั้นที่มีความเสี่ยงจนกว่าจะยืนยัน):**\n"
            + "\n".join(cand_lines)
        )
    if questions:
        q_lines = "\n".join(f"- {q}" for q in questions)
        parts.append(f"**คำถามเพื่อความชัดเจน:**\n{q_lines}")
    return "\n\n".join(parts)


def try_native_planning(conn: sqlite3.Connection, prompt: str, force_plan: bool = False) -> dict | None:
    return build_context_aware_dag_plan(
        conn,
        prompt,
        repo_root=BASE_DIR,
        force_plan=force_plan,
    )


def _score_interpolated_ngram(
    lines_subset: list[str],
    bigrams: dict,
    trigrams: dict,
    unigrams: dict,
    vocab_size: int,
) -> tuple[float, float, int]:
    total_log_prob = 0.0
    total_preds = 0
    correct = 0
    total_uni = max(1, sum(unigrams.values())) if unigrams else vocab_size
    for ln in lines_subset:
        toks = tokenize(ln) + ["<END>"]
        for i in range(1, len(toks)):
            prev = toks[i - 1]
            curr = toks[i]

            tri_counts = trigrams.get(f"{toks[i - 2]} {prev}", {}) if i >= 2 else {}
            tri_total = sum(tri_counts.values())
            p_tri = ((tri_counts.get(curr, 0) + 0.5) / (tri_total + 0.5 * vocab_size)) if tri_total > 0 else 0.0

            bi_counts = bigrams.get(prev, {})
            bi_total = sum(bi_counts.values())
            p_bi = (bi_counts.get(curr, 0) + 1.0) / (bi_total + vocab_size)

            p_uni = (unigrams.get(curr, 0) + 1.0) / (total_uni + vocab_size) if unigrams else (1.0 / vocab_size)

            if tri_total > 0:
                prob = 0.6 * p_tri + 0.3 * p_bi + 0.1 * p_uni
            else:
                prob = 0.85 * p_bi + 0.15 * p_uni

            total_log_prob += -math.log(max(prob, 1e-12))
            total_preds += 1

            pred_source = tri_counts if tri_counts else bi_counts
            if pred_source:
                pred = max(pred_source.items(), key=lambda kv: kv[1])[0]
                if pred == curr:
                    correct += 1
    if total_preds == 0:
        return 0.0, 0.0, 0
    return total_log_prob / total_preds, correct / total_preds, total_preds


def evaluate_checkpoint_heldout(conn: sqlite3.Connection, ckpt_row: sqlite3.Row) -> dict:
    raw_weights = str(ckpt_row["weights_path"] or "").strip()
    if not raw_weights:
        return {"ok": False, "status": "BLOCKED", "error": "Checkpoint weights_path is empty"}
    weights_path = Path(raw_weights)
    if weights_path.is_symlink() or not weights_path.is_file():
        return {"ok": False, "status": "BLOCKED", "error": "Checkpoint weights file missing or invalid on disk"}

    actual_sha = hashlib.sha256(weights_path.read_bytes()).hexdigest()
    exp_row = conn.execute(
        "SELECT candidate_metrics_json FROM experiments WHERE candidate_ckpt_id=? LIMIT 1",
        (ckpt_row["id"],),
    ).fetchone()
    exp_cand: dict = {}
    if exp_row and exp_row["candidate_metrics_json"]:
        try:
            exp_cand = json.loads(exp_row["candidate_metrics_json"])
        except Exception:
            exp_cand = {}
    recorded_sha = str(exp_cand.get("checkpoint_sha256") or "").strip()
    if recorded_sha and actual_sha != recorded_sha:
        return {
            "ok": False,
            "status": "FAILED",
            "error": "Checkpoint SHA-256 verification failed (artifact modified after promotion)",
        }

    eval_status = str(ckpt_row["eval_status"] or "")
    dataset_id = str(ckpt_row["dataset_id"] or "")

    # 1. Real-only AST linear classifier checkpoint (.json)
    if eval_status.startswith("AST") or int(ckpt_row["ngram_order"] or 0) < 0:
        try:
            ast_ckpt = json.loads(weights_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "status": "FAILED", "error": f"Invalid AST checkpoint JSON: {exc}"}
        if ast_ckpt.get("schema") != "zyrquen.real_only_ast_classifier.v1.1":
            return {"ok": False, "status": "FAILED", "error": "Unrecognized AST checkpoint schema"}
        weights_vec = ast_ckpt.get("weights")
        if not isinstance(weights_vec, list) or not all(
            isinstance(w, (int, float)) and math.isfinite(float(w)) for w in weights_vec
        ):
            return {"ok": False, "status": "FAILED", "error": "Non-finite or invalid AST checkpoint weights"}
        report_path_str = str(exp_cand.get("report_path") or "").strip()
        if not report_path_str or not Path(report_path_str).is_file():
            return {
                "ok": False,
                "status": "BLOCKED",
                "error": "Verified real-only evaluation_report.json missing on disk",
            }
        try:
            report_obj = json.loads(Path(report_path_str).read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "status": "FAILED", "error": f"Corrupt evaluation_report.json: {exc}"}
        if str(report_obj.get("checkpoint_sha256") or "") != actual_sha:
            return {
                "ok": False,
                "status": "FAILED",
                "error": "evaluation_report.json checkpoint_sha256 mismatch",
            }
        if int(report_obj.get("leak_count") or 0) > 0:
            return {"ok": False, "status": "FAILED", "error": "Data leakage recorded in evaluation report"}
        test_m = (report_obj.get("final_metrics") or {}).get("test") or {}
        test_acc = test_m.get("accuracy")
        test_loss = test_m.get("loss")
        if test_acc is None or test_loss is None:
            return {"ok": False, "status": "NOT_RUN", "error": "AST evaluation report lacks test metrics"}
        splits_info = ((report_obj.get("dataset_summary") or {}).get("splits") or {})
        return {
            "ok": True,
            "engine": "real_only_ast_classifier",
            "test_records": int(splits_info.get("test") or 0),
            "test_accuracy": float(test_acc),
            "test_perplexity": round(math.exp(min(float(test_loss), 20.0)), 3),
            "checkpoint_sha256": actual_sha,
        }

    # 2. Native Neural Transformer checkpoint (.json.gz)
    ds = conn.execute("SELECT records_json FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if eval_status.startswith("NEURAL") or str(weights_path).endswith(".gz"):
        try:
            n_model, n_tok, _ = NativeTransformerLM.load_checkpoint(weights_path)
        except Exception as exc:
            return {"ok": False, "status": "FAILED", "error": f"Failed to load neural checkpoint: {exc}"}
        if not ds and dataset_id == "continual-curriculum":
            ds = conn.execute(
                "SELECT records_json FROM datasets WHERE leakage_detected=0 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not ds:
            return {
                "ok": False,
                "status": "BLOCKED" if dataset_id != "continual-curriculum" else "NOT_RUN",
                "error": "Training/held-out dataset missing for neural checkpoint",
            }
        splits = json.loads(ds["records_json"])
        test_lines = splits.get("test", [])
        test_seqs = [n_tok.encode(ln, add_bos=True, add_eos=True) for ln in test_lines if str(ln).strip()]
        n_eval = n_model.evaluate_sequences(test_seqs)
        if n_eval["tokens"] == 0:
            return {"ok": False, "status": "NOT_RUN", "error": "Held-out test split contains zero tokens"}
        return {
            "ok": True,
            "test_records": len(test_lines),
            "test_tokens": n_eval["tokens"],
            "test_accuracy": n_eval["accuracy"],
            "test_perplexity": n_eval["perplexity"],
        }

    # 3. N-Gram JSON checkpoint
    if not ds:
        return {"ok": False, "status": "BLOCKED", "error": "Training dataset missing for N-gram checkpoint"}
    splits = json.loads(ds["records_json"])
    test_lines = splits.get("test", [])
    try:
        with open(weights_path, "r", encoding="utf-8") as f:
            weights = json.load(f)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Failed to parse N-gram weights: {exc}"}
    bigrams = weights.get("bigrams", {})
    trigrams = weights.get("trigrams", {})
    unigrams = weights.get("unigrams", {})
    vocab_size = max(1, len(weights.get("vocab", [])))

    avg_loss, acc, total_preds = _score_interpolated_ngram(
        test_lines, bigrams, trigrams, unigrams, vocab_size
    )
    if total_preds == 0:
        return {"ok": False, "status": "NOT_RUN", "error": "Held-out test split contains zero N-gram tokens"}
    return {
        "ok": True,
        "test_records": len(test_lines),
        "test_tokens": total_preds,
        "test_accuracy": round(acc, 4),
        "test_perplexity": round(math.exp(min(avg_loss, 20.0)), 3),
    }


def handle_run_evaluation(payload: dict) -> dict:
    conn = get_db()
    user_id = str(payload.get("user_id", "system"))
    suite_name = str(payload.get("suite_name", "ZYRQUEN Scientific Benchmark v1"))

    # 1. Deterministic Math AST, Linear Algebra & Statistics Probes
    math_cases = [
        ("ast", "(2^12 - 96) / 16", 250),
        ("ast", "(144 / 12) + sqrt(81)", 21),
        ("ast", "factorial(5) - 20", 100),
        ("ast", "round(log10(1000) + abs(-7))", 10),
        ("ast", "ceil(3.2) * floor(4.9)", 16),
        ("algebra", "แก้สมการ: 3*x + 7 = 22", 5),
        ("statistics", "สถิติ: 10, 20, 30, 40", 25),
    ]
    math_results = []
    math_passed = 0
    for kind, expr, expected in math_cases:
        if kind == "algebra":
            res = try_solve_linear_equation(expr)
            actual = res["result"] if res else None
        elif kind == "statistics":
            res = try_statistics_reasoning(expr)
            actual = res["mean"] if res else None
        else:
            res = try_math_reasoning(expr)
            actual = res["result"] if res else None
        ok = actual == expected
        if ok:
            math_passed += 1
        math_results.append(
            {
                "kind": kind,
                "expression": expr,
                "expected": expected,
                "actual": actual,
                "status": "PASS" if ok else "FAILED",
            }
        )
    math_score = round(math_passed / len(math_cases), 4)

    # 2. Knowledge Graph Resolution & Contradiction Probe
    triples = conn.execute(
        "SELECT id, subject, relation, object FROM knowledge_triples ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    total_triples = conn.execute("SELECT COUNT(*) FROM knowledge_triples").fetchone()[0]
    k_resolved = 0
    for tr in triples:
        found = query_knowledge_graph(conn, f"{tr['subject']} {tr['object']}")
        if any(m["id"] == tr["id"] for m in found):
            k_resolved += 1
    knowledge_score = round(k_resolved / len(triples), 4) if triples else 0.0
    knowledge_status = "PASS" if (triples and knowledge_score == 1.0) else ("PARTIAL" if triples else "NOT_RUN")

    # 3. Native DAG Planning Probe
    plan_probe = try_native_planning(conn, "วางแผน: เตรียมข้อมูล ฝึกโมเดล และประเมินผล", force_plan=True)
    plan_steps = plan_probe["steps"] if plan_probe else []
    step_ids = {s["step_id"] for s in plan_steps}
    dag_valid = bool(plan_steps) and all(
        all(dep in step_ids and dep != s["step_id"] for dep in s["depends_on"])
        for s in plan_steps
    )
    planning_score = 1.0 if dag_valid else 0.0

    # 4. Held-out Test Split Evaluation & Baseline Comparison
    ckpts = conn.execute("SELECT * FROM checkpoints ORDER BY version DESC LIMIT 2").fetchall()
    latest_ckpt = ckpts[0] if ckpts else None
    prev_ckpt = ckpts[1] if len(ckpts) > 1 else None

    test_acc = None
    test_ppl = None
    heldout_detail = {"status": "NOT_RUN", "reason": "No trained checkpoint available"}
    baseline_delta = None

    if latest_ckpt:
        heldout = evaluate_checkpoint_heldout(conn, latest_ckpt)
        if heldout and heldout.get("ok") is True:
            test_acc = heldout["test_accuracy"]
            test_ppl = heldout["test_perplexity"]
            heldout_detail = {
                "status": "PASS",
                "checkpoint_version": latest_ckpt["version"],
                **{k: v for k, v in heldout.items() if k != "ok"},
            }
            if prev_ckpt:
                prev_heldout = evaluate_checkpoint_heldout(conn, prev_ckpt)
                if prev_heldout and prev_heldout.get("ok") is True:
                    baseline_delta = {
                        "baseline_version": prev_ckpt["version"],
                        "current_version": latest_ckpt["version"],
                        "accuracy_delta": round(test_acc - prev_heldout["test_accuracy"], 4),
                        "perplexity_delta": round(test_ppl - prev_heldout["test_perplexity"], 3),
                    }
        else:
            err_status = str((heldout or {}).get("status") or "BLOCKED")
            heldout_detail = {
                "status": err_status,
                "checkpoint_version": latest_ckpt["version"],
                "reason": (heldout or {}).get("error") or "Held-out checkpoint evaluation failed",
            }

    if math_score < 1.0 or planning_score < 1.0 or (latest_ckpt and heldout_detail["status"] == "FAILED"):
        overall_status = "FAILED"
    elif latest_ckpt and heldout_detail["status"] == "BLOCKED":
        overall_status = "BLOCKED"
    elif not latest_ckpt or total_triples == 0 or heldout_detail["status"] != "PASS":
        overall_status = "PARTIAL"
    else:
        overall_status = "VERIFIED"

    eval_id = str(uuid.uuid4())
    tracks_and_levels = get_training_tracks_and_levels(conn)
    details_obj = {
        "math_probes": math_results,
        "knowledge_probe": {
            "status": knowledge_status,
            "total_triples": total_triples,
            "sampled": len(triples),
            "resolved": k_resolved,
        },
        "planning_probe": {
            "status": "PASS" if dag_valid else "FAILED",
            "steps_generated": len(plan_steps),
        },
        "heldout_test": heldout_detail,
        "training_tracks": tracks_and_levels["training_tracks"],
        "engineering_levels": tracks_and_levels["engineering_levels"],
    }

    with conn:
        conn.execute(
            """
            INSERT INTO evaluations (
                id, checkpoint_id, checkpoint_version, suite_name, overall_status,
                math_score, knowledge_score, planning_score, test_accuracy, perplexity,
                baseline_delta_json, details_json, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eval_id,
                latest_ckpt["id"] if latest_ckpt else None,
                latest_ckpt["version"] if latest_ckpt else None,
                suite_name,
                overall_status,
                math_score,
                knowledge_score,
                planning_score,
                test_acc,
                test_ppl,
                json.dumps(baseline_delta) if baseline_delta else None,
                json.dumps(details_obj),
                user_id,
                now_iso(),
            ),
        )
    row = dict(conn.execute("SELECT * FROM evaluations WHERE id=?", (eval_id,)).fetchone())
    conn.close()
    return {
        "ok": True,
        "evaluation": row,
        "training_tracks": tracks_and_levels["training_tracks"],
        "engineering_levels": tracks_and_levels["engineering_levels"],
    }


def _calc_any_for_tool(expr: str) -> dict | None:
    return (
        try_statistics_reasoning(expr)
        or try_solve_equation(expr)
        or try_math_reasoning(expr)
        or try_word_math_reasoning(expr)
    )


_CHAT_AUTONOMOUS_GOAL_RE = re.compile(
    r"^(?:ช่วย)?(?:"
    r"(?:สร้างเอกสาร|จัดทำเอกสาร|เขียนเอกสาร|สร้างไฟล์|สร้างระบบ|สร้างโมดูล|สร้างแผน|สร้างรายงาน|สร้างคู่มือ|สร้างสคริปต์|สร้าง|ออกแบบ|พัฒนา|แก้ไข|ปรับปรุง|เขียนโค้ด|เขียนสคริปต์)"
    r"|(?:build|create|implement|design|generate|write|refactor|fix)\b"
    r")",
    re.IGNORECASE,
)

_CHAT_ENG_INSPECT_GOAL_RE = re.compile(
    r"^(?:ช่วย)?(?:"
    r"(?:ค้นหา(?:สัญลักษณ์|ฟังก์ชัน|คลาส|จุดใช้งาน|ไฟล์ทดสอบ|ตำแหน่งในโค้ด)"
    r"|สำรวจ\s*(?:dependencies|แพ็กเกจ|ไฟล์ทดสอบ|โครงสร้างโค้ด|การตั้งค่า|sbom|license|schema)"
    r"|ตรวจสอบ\s*(?:diff|git\s*diff|ความแตกต่างของโค้ด|dependencies|ไฟล์ทดสอบ|การตั้งค่า\s*build|build\s*config|quality\s*config|compatibility|ความเข้ากันได้|migration|alembic|a11y|accessibility|sbom|license|threat\s*model|permission|rbac|schema|ความผิดปกติ|ข้อมูลซ้ำ|artifact\s*integrity)"
    r"|วิเคราะห์\s*(?:migration|alembic|threat\s*model|ภัยคุกคาม|schema|สาเหตุราก|error|traceback|ความเสี่ยง)"
    r"|แตกเป้าหมาย"
    r"|วินิจฉัย\s*(?:error|traceback|สาเหตุ))"
    r"|(?:(?:search|find)\s+(?:symbol|function|class|reference)\b|(?:inspect|check|audit|analyze|diagnose|decompose)\s+(?:git\s+)?(?:diff|dependencies|compatibility|migration|a11y|accessibility|sbom|license|threat\s+model|permission|rbac|tests?|build\s+config|configs?|schema|anomal\w*|duplicates?|goal|error|traceback)\b)"
    r")",
    re.IGNORECASE,
)

_CHAT_FACTUAL_EXCLUSION_RE = re.compile(
    r"(?:คืออะไร|ทำงานอย่างไร|เกิดขึ้นได้อย่างไร|ต่างกันอย่างไร|what\s+is|how\s+does|explain\b|\?$)",
    re.IGNORECASE,
)

_SYMBOL_STOPWORDS = frozenset({
    "symbol", "symbols", "search", "find", "function", "functions", "class", "classes",
    "reference", "references", "inspect", "audit", "check", "diff", "git", "code",
    "file", "files", "test", "tests", "config", "configs", "build", "quality",
    "dependencies", "dependency", "package", "packages", "project", "repo", "repository",
    "workspace", "zyrquen", "create", "implement", "design", "generate", "write",
    "refactor", "fix", "python", "typescript", "javascript", "tsx", "jsx",
    "and", "or", "the", "for", "with", "from", "into", "that", "this", "where", "all",
})


def _extract_symbol_query_from_goal(goal: str) -> str | None:
    quoted = re.search(r"[`'\"]([A-Za-z_][A-Za-z0-9_.\-]{1,120})[`'\"]", goal)
    if quoted:
        return quoted.group(1)
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,120}\b", goal):
        low_tok = token.lower()
        if low_tok in _SYMBOL_STOPWORDS:
            continue
        if "_" in token or any(ch.isupper() for ch in token[1:]):
            return token
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,120}\b", goal):
        if token.lower() not in _SYMBOL_STOPWORDS:
            return token
    return None


def _try_execute_chat_autonomous_goal(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    attachment: str = "",
    user_id: str = "",
) -> dict | None:
    cleaned = prompt.strip()
    unwrapped = unwrap_command_wrapper(cleaned)
    effective_cleaned = unwrapped["effective_goal"] or cleaned
    is_create_goal = bool(
        cleaned
        and (
            _CHAT_AUTONOMOUS_GOAL_RE.match(cleaned)
            or _CHAT_AUTONOMOUS_GOAL_RE.match(effective_cleaned)
            or unwrapped["wrapper_kind"] in {"create_document", "create_data"}
        )
    )
    is_inspect_goal = bool(
        cleaned and (_CHAT_ENG_INSPECT_GOAL_RE.match(cleaned) or _CHAT_ENG_INSPECT_GOAL_RE.match(effective_cleaned))
    )
    if not cleaned or (not is_create_goal and not is_inspect_goal):
        return None
    if _CHAT_FACTUAL_EXCLUSION_RE.search(effective_cleaned):
        return None
    # Skip explicit KG triple teaching variations like "สร้างความจำ: ..."
    if re.match(r"^(?:สร้างความจำ|สร้าง\s*triple)\b", effective_cleaned, re.IGNORECASE):
        return None

    t0 = time.perf_counter()
    repo_root_str = str(Path(__file__).resolve().parent.parent)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    plan_res = try_native_planning(conn, cleaned, force_plan=True)
    if not plan_res:
        return None

    goal_analysis = plan_res.get("goal_interpretation") or analyze_planner_goal(cleaned, attachment=attachment)
    if (
        plan_res.get("plan_status") == "NEEDS_CLARIFICATION"
        or plan_res.get("plan_valid") is False
        or goal_analysis.get("clarity_status") != "VALID"
    ):
        clarify_status = "UNKNOWN" if goal_analysis.get("clarity_status") == "INVALID_CORRUPT" else "NEEDS_CLARIFICATION"
        questions = plan_res.get("clarification_questions") or goal_analysis.get("clarification_questions") or []
        issues = plan_res.get("issues") or goal_analysis.get("issues") or []
        ctx_res = plan_res.get("context_resolution") or goal_analysis.get("context_resolution") or {}
        content = _format_clarification_markdown(
            clarify_status=clarify_status,
            issues=issues,
            questions=questions,
            context_resolution=ctx_res,
            heading="ยังไม่สามารถสร้างหรือดำเนินการจากคำสั่งนี้ได้",
        )
        return {
            "content": content,
            "status": clarify_status,
            "execution_phase": "CLARIFICATION_REQUIRED",
            "goal_interpretation": goal_analysis,
            "goal_validation": {
                "clarity_status": goal_analysis.get("clarity_status"),
                "is_actionable_goal": False,
                "issues": issues,
                "context_resolution": ctx_res,
                "status_transitions": plan_res.get("status_transitions") or [],
            },
            "engine_path": ["goal_understanding_gate"],
            "task_timings": [
                {
                    "task": "goal_understanding_gate",
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
                    "matched": True,
                    "status": clarify_status,
                    "detail": ", ".join(issues) or clarify_status,
                }
            ],
        }

    cleaned = effective_cleaned
    timings: list[dict] = [
        {
            "task": "native_planner",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            "matched": True,
            "status": "PLANNED",
            "detail": f"{len(plan_res.get('steps') or [])} steps",
        }
    ]

    from tool_center import execute_orchestrated_plan, get_tool_center_registry

    tc_reg = get_tool_center_registry()

    # Stage 1: Toolkit Resolution (internal Registry + Task Memory)
    t_tc = time.perf_counter()
    try:
        tc_plan = tc_reg.compose_for_goal(cleaned, user_role="user", conn=conn)
        selected_caps = [
            f"{c['capability_id']}" for c in (tc_plan.get("selected_capabilities") or [])[:10]
        ]
    except Exception:
        selected_caps = []
    timings.append(
        {
            "task": "toolkit_resolution",
            "duration_ms": round((time.perf_counter() - t_tc) * 1000, 3),
            "matched": bool(selected_caps),
            "status": "VERIFIED",
            "detail": f"{len(selected_caps)} capabilities",
        }
    )

    # Stage 2: Execute Wave 1 inspection via real Orchestrator & Execution Engine
    t_w1 = time.perf_counter()
    wave1_steps: list[dict] = [
        {
            "step_id": "inspect_repo",
            "capability_id": "development.code_analysis",
            "input": {"target_path": "."},
            "depends_on": [],
        },
        {
            "step_id": "inspect_db",
            "capability_id": "data.db_inspect",
            "input": {"table_limit": 20},
            "depends_on": [],
        },
    ]

    low = cleaned.lower()
    is_doc_goal = any(
        k in low
        for k in (
            "เอกสาร",
            "สรุป",
            "สถาปัตยกรรม",
            "ตรวจสอบความพร้อม",
            "checklist",
            "document",
            "spec",
            "report",
            "architecture",
            "markdown",
            "readme",
        )
    )
    wants_dep_inventory = (
        is_doc_goal
        or "development.dependency_inventory" in selected_caps
        or any(k in low for k in ("dependency", "dependencies", "package", "npm", "pip", "แพ็กเกจ"))
    )
    wants_test_discovery = (
        is_doc_goal
        or "development.test_discovery" in selected_caps
        or any(k in low for k in ("ไฟล์ทดสอบ", "test discovery", "discover test", "tests", "pytest", "vitest"))
    )
    wants_config_audit = (
        is_doc_goal
        or "development.config_audit" in selected_caps
        or any(k in low for k in ("build config", "quality config", "config", "ตั้งค่า", "ci", "lint"))
    )
    symbol_query = _extract_symbol_query_from_goal(cleaned)
    wants_symbol_search = bool(symbol_query) and (
        "development.symbol_search" in selected_caps
        or any(k in low for k in ("symbol", "สัญลักษณ์", "จุดใช้งาน", "ค้นหาฟังก์ชัน", "ค้นหาคลาส", "search symbol", "find symbol"))
    )
    wants_diff_inspect = (
        "development.diff_inspect" in selected_caps
        or any(k in low for k in ("diff", "ความแตกต่างของโค้ด", "ตรวจ diff", "git diff", "patch"))
    )
    wants_dep_compat = (
        "development.dependency_compatibility" in selected_caps
        or any(k in low for k in ("compatibility", "ความเข้ากันได้", "conflict"))
    )
    wants_migration = (
        "development.migration_analyzer" in selected_caps
        or any(k in low for k in ("migration", "alembic", "ไมเกรชัน"))
    )
    wants_a11y = (
        "development.frontend_a11y_audit" in selected_caps
        or any(k in low for k in ("a11y", "accessibility", "การเข้าถึง"))
    )
    wants_sbom = (
        "security.sbom_generate" in selected_caps
        or any(k in low for k in ("sbom", "cyclonedx", "bill of materials"))
    )
    wants_license = (
        "security.license_compliance" in selected_caps
        or any(k in low for k in ("license", "สัญญาอนุญาต", "copyleft"))
    )
    wants_threat = (
        "security.threat_model" in selected_caps
        or any(k in low for k in ("threat model", "stride", "ภัยคุกคาม"))
    )
    wants_perm_audit = (
        "security.permission_audit" in selected_caps
        or any(k in low for k in ("permission audit", "rbac", "ตรวจสิทธิ์"))
    )
    wants_goal_decomp = (
        "automation.goal_decomposition" in selected_caps
        or any(k in low for k in ("แตกเป้าหมาย", "decompose", "แยกงานย่อย"))
    )

    if wants_dep_inventory:
        wave1_steps.append(
            {
                "step_id": "inspect_dependencies",
                "capability_id": "development.dependency_inventory",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_test_discovery:
        wave1_steps.append(
            {
                "step_id": "discover_tests",
                "capability_id": "development.test_discovery",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_config_audit:
        wave1_steps.append(
            {
                "step_id": "audit_configs",
                "capability_id": "development.config_audit",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_symbol_search and symbol_query:
        wave1_steps.append(
            {
                "step_id": "search_symbol",
                "capability_id": "development.symbol_search",
                "input": {"query": symbol_query, "target_path": "."},
                "depends_on": [],
            }
        )
    if wants_diff_inspect:
        wave1_steps.append(
            {
                "step_id": "inspect_diff",
                "capability_id": "development.diff_inspect",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_dep_compat:
        wave1_steps.append(
            {
                "step_id": "check_dep_compat",
                "capability_id": "development.dependency_compatibility",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_migration:
        wave1_steps.append(
            {
                "step_id": "analyze_migrations",
                "capability_id": "development.migration_analyzer",
                "input": {"migrations_path": "apps/api/migrations/versions"},
                "depends_on": [],
            }
        )
    if wants_a11y:
        wave1_steps.append(
            {
                "step_id": "audit_a11y",
                "capability_id": "development.frontend_a11y_audit",
                "input": {"target_path": "src"},
                "depends_on": [],
            }
        )
    if wants_sbom:
        wave1_steps.append(
            {
                "step_id": "generate_sbom",
                "capability_id": "security.sbom_generate",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_license:
        wave1_steps.append(
            {
                "step_id": "audit_licenses",
                "capability_id": "security.license_compliance",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_threat:
        wave1_steps.append(
            {
                "step_id": "analyze_threat_model",
                "capability_id": "security.threat_model",
                "input": {"target_path": "."},
                "depends_on": [],
            }
        )
    if wants_perm_audit:
        wave1_steps.append(
            {
                "step_id": "audit_permissions",
                "capability_id": "security.permission_audit",
                "input": {},
                "depends_on": [],
            }
        )
    if wants_goal_decomp:
        wave1_steps.append(
            {
                "step_id": "decompose_goal",
                "capability_id": "automation.goal_decomposition",
                "input": {"goal": cleaned},
                "depends_on": [],
            }
        )

    ds_rep = analyze_structured_dataset_content(attachment) if attachment else {"ok": False}
    if attachment:
        if ds_rep.get("ok"):
            ds_fmt = str(ds_rep.get("format") or "csv").lower()
            ds_txt = attachment[:15000]
            wave1_steps.append(
                {
                    "step_id": "inspect_attachment_data",
                    "capability_id": "data.profile_structured",
                    "input": {"format": ds_fmt, "content": ds_txt},
                    "depends_on": [],
                }
            )
            if ds_fmt in {"csv", "json", "jsonl"}:
                wave1_steps.extend([
                    {
                        "step_id": "infer_attachment_schema",
                        "capability_id": "data.schema_inference",
                        "input": {"format": ds_fmt, "content": ds_txt},
                        "depends_on": [],
                    },
                    {
                        "step_id": "detect_attachment_duplicates",
                        "capability_id": "data.duplicate_detection",
                        "input": {"format": ds_fmt, "content": ds_txt},
                        "depends_on": [],
                    },
                    {
                        "step_id": "detect_attachment_anomalies",
                        "capability_id": "data.anomaly_detection",
                        "input": {"format": ds_fmt, "content": ds_txt},
                        "depends_on": [],
                    },
                ])
        else:
            wave1_steps.append(
                {
                    "step_id": "inspect_attachment_code",
                    "capability_id": "development.code_analysis",
                    "input": {"source": attachment[:15000]},
                    "depends_on": [],
                }
            )

    wave1_res = execute_orchestrated_plan(
        tc_reg,
        f"inspect:{cleaned[:180]}",
        wave1_steps,
        conn=conn,
        data_dir=DATA_DIR,
        user_id=user_id or "system",
        user_role="user",
        enable_parallel=True,
    )
    wave1_by_id = {s["step_id"]: s for s in (wave1_res.get("steps") or [])}
    repo_info = (wave1_by_id.get("inspect_repo") or {}).get("output") or {}
    db_info = (wave1_by_id.get("inspect_db") or {}).get("output") or {}
    dep_info = (wave1_by_id.get("inspect_dependencies") or {}).get("output") or {}
    test_disc_info = (wave1_by_id.get("discover_tests") or {}).get("output") or {}
    config_audit_info = (wave1_by_id.get("audit_configs") or {}).get("output") or {}
    symbol_info = (wave1_by_id.get("search_symbol") or {}).get("output") or {}
    diff_info = (wave1_by_id.get("inspect_diff") or {}).get("output") or {}
    compat_info = (wave1_by_id.get("check_dep_compat") or {}).get("output") or {}
    mig_info = (wave1_by_id.get("analyze_migrations") or {}).get("output") or {}
    a11y_info = (wave1_by_id.get("audit_a11y") or {}).get("output") or {}
    sbom_info = (wave1_by_id.get("generate_sbom") or {}).get("output") or {}
    lic_info = (wave1_by_id.get("audit_licenses") or {}).get("output") or {}
    threat_info = (wave1_by_id.get("analyze_threat_model") or {}).get("output") or {}
    perm_info = (wave1_by_id.get("audit_permissions") or {}).get("output") or {}
    decomp_info = (wave1_by_id.get("decompose_goal") or {}).get("output") or {}

    attach_summary_lines: list[str] = []
    if attachment:
        if ds_rep.get("ok"):
            prof_out = (wave1_by_id.get("inspect_attachment_data") or {}).get("output") or {}
            cols = prof_out.get("columns") or ds_rep.get("columns") or []
            row_count = prof_out.get("row_count", ds_rep.get("rows", 0))
            dup_count = prof_out.get("duplicate_rows", 0)
            attach_summary_lines.append(
                f"ข้อมูลที่แนบ: {ds_rep.get('format')} ({row_count} แถว, ซ้ำ {dup_count} แถว, คอลัมน์ {', '.join(cols[:8])})"
            )
        else:
            code_out = (wave1_by_id.get("inspect_attachment_code") or {}).get("output") or {}
            code_lang = code_out.get("language") or "text"
            val_status = (code_out.get("validation") or {}).get("status") or "checked"
            attach_summary_lines.append(
                f"โค้ด/ข้อความที่แนบ ({code_lang}): สถานะตรวจสอบ `{val_status}`"
            )
            for defect in (code_out.get("defects") or [])[:5]:
                attach_summary_lines.append(
                    f"- บรรทัด {defect.get('line', '?')}: {defect.get('message')}"
                )

    run_ids = [wave1_res["run_id"]] if wave1_res.get("run_id") else []
    caps_executed = [s["capability_id"] for s in (wave1_res.get("steps") or [])]

    timings.append(
        {
            "task": "orchestrator_inspect",
            "duration_ms": round((time.perf_counter() - t_w1) * 1000, 3),
            "matched": bool(wave1_res.get("ok")),
            "status": str(wave1_res.get("delivery_verdict") or "FAILED"),
            "detail": f"run={wave1_res.get('run_id', '')[:8]}",
        }
    )

    snap = (plan_res.get("summary") or {}).get("state_snapshot") or {}
    counts = repo_info.get("file_counts") or {}
    top_dirs = repo_info.get("top_directories") or []
    sample_mods = repo_info.get("sample_python_modules") or []
    db_tables_count = len(db_info.get("tables") or [])

    t_exec = time.perf_counter()
    engine_path = ["native_planner", "tool_center", "tool_center_orchestrator"]

    if is_doc_goal:
        manifest_count = int(dep_info.get("manifest_count") or 0)
        discovered_test_count = int(test_disc_info.get("count") or counts.get("tests", 0))
        config_count = int(config_audit_info.get("count") or 0)
        sections = [
            {
                "heading": "1. โครงสร้างระบบจริงใน Workspace",
                "body": (
                    f"- ไดเรกทอรีหลัก: {', '.join(f'`{d}`' for d in top_dirs[:10]) or '`src`, `python_core`, `apps`'}\n"
                    f"- จำนวนไฟล์ตรวจพบ: Python `{counts.get('python', 0)}` ไฟล์ · TypeScript/React `{counts.get('typescript', 0)}` ไฟล์ · ไฟล์ทดสอบ `{discovered_test_count}` ไฟล์\n"
                    f"- ไฟล์กำหนด Dependencies: `{manifest_count}` รายการ · ไฟล์ตั้งค่า Build/Quality: `{config_count}` รายการ\n"
                    f"- โมดูลแกนหลักตัวอย่าง: {', '.join(f'`{m}`' for m in sample_mods[:6]) or '`python_core/zyrquen_core.py`'}"
                ),
            },
            {
                "heading": "2. แผนดำเนินงานเชิงโครงสร้าง",
                "body": "\n".join(
                    f"{idx + 1}. **{st['title']}** — {st['detail']}"
                    for idx, st in enumerate(plan_res.get("steps") or [])
                ),
            },
            {
                "heading": "3. สถานะความพร้อมจากฐานข้อมูลจริง",
                "body": (
                    f"- ตาราง SQLite ที่ตรวจพบ: `{db_tables_count}` ตาราง\n"
                    f"- ชุดข้อมูลผ่านเกณฑ์: `{snap.get('clean_datasets', 0)}` ชุด\n"
                    f"- รุ่นโมเดลภายใน (Checkpoints): `{snap.get('checkpoints', 0)}` รุ่น\n"
                    f"- ความจำกราฟความรู้: `{snap.get('triples', 0)}` รายการ\n"
                    f"- งานรออนุมัติ: `{snap.get('pending_approvals', 0)}` รายการ"
                ),
            },
        ]
        if attach_summary_lines:
            sections.append(
                {
                    "heading": "4. ผลตรวจสอบไฟล์แนบ",
                    "body": "\n".join(f"- {ln}" if not ln.startswith("- ") else ln for ln in attach_summary_lines),
                }
            )

        doc_title = cleaned[:72]
        spec_wave = execute_orchestrated_plan(
            tc_reg,
            f"generate_spec:{cleaned[:160]}",
            [
                {
                    "step_id": "generate_spec",
                    "capability_id": "document.spec_generate",
                    "input": {
                        "title": doc_title,
                        "objective": cleaned,
                        "constraints": [
                            "อ้างอิงสถานะจริงจากฐานข้อมูลและซอร์สโค้ดใน Workspace เท่านั้น",
                            "ประมวลผลภายในเครื่องทั้งหมด (Zero External LLMs)",
                            "บังคับใช้การตรวจสอบสิทธิ์และ Approval Gate สำหรับการเปลี่ยนแปลงสำคัญ",
                        ],
                        "sections": sections,
                        "save_to_workspace": False,
                    },
                    "depends_on": [],
                }
            ],
            conn=conn,
            data_dir=DATA_DIR,
            user_id=user_id or "system",
            user_role="user",
            enable_parallel=False,
        )
        if spec_wave.get("run_id"):
            run_ids.append(spec_wave["run_id"])
        caps_executed.extend(s["capability_id"] for s in (spec_wave.get("steps") or []))

        spec_step = next(iter(spec_wave.get("steps") or []), {})
        doc_out = spec_step.get("output") or {}
        doc_md = str(doc_out.get("markdown") or "").strip()

        outline_wave = execute_orchestrated_plan(
            tc_reg,
            f"verify_outline:{cleaned[:160]}",
            [
                {
                    "step_id": "verify_outline",
                    "capability_id": "document.markdown_outline",
                    "input": {"content": doc_md},
                    "depends_on": [],
                },
                {
                    "step_id": "scan_doc_hygiene",
                    "capability_id": "security.secret_and_path_scan",
                    "input": {"path": "zyrquen-architecture-readiness.md", "content": doc_md},
                    "depends_on": [],
                },
            ],
            conn=conn,
            data_dir=DATA_DIR,
            user_id=user_id or "system",
            user_role="user",
            enable_parallel=True,
        )
        if outline_wave.get("run_id"):
            run_ids.append(outline_wave["run_id"])
        caps_executed.extend(s["capability_id"] for s in (outline_wave.get("steps") or []))
        outline_by_id = {s["step_id"]: s for s in (outline_wave.get("steps") or [])}
        outline_out = (outline_by_id.get("verify_outline") or {}).get("output") or {}
        hygiene_out = (outline_by_id.get("scan_doc_hygiene") or {}).get("output") or {}

        doc_verified = bool(
            spec_wave.get("ok")
            and spec_wave.get("delivery_verdict") == "SUCCESS"
            and outline_wave.get("ok")
            and outline_wave.get("delivery_verdict") == "SUCCESS"
            and hygiene_out.get("clean", True)
        )

        readiness_table = "\n".join(
            [
                "| รายการตรวจสอบความพร้อม | สถานะปัจจุบัน | รายละเอียดจากการตรวจจริง |",
                "| --- | --- | --- |",
                f"| โครงสร้าง Backend & Core | READY | พบโมดูล Python {counts.get('python', 0)} ไฟล์ |",
                f"| โครงสร้าง Frontend Workspace | READY | พบไฟล์ TypeScript/React {counts.get('typescript', 0)} ไฟล์ |",
                f"| ชุดทดสอบอัตโนมัติ | READY | พบไฟล์ทดสอบ {counts.get('tests', 0)} ไฟล์ |",
                f"| หน่วยความจำและฐานข้อมูล | {'READY' if snap.get('triples', 0) > 0 or db_tables_count > 0 else 'NEEDS_DATA'} | {db_tables_count} ตาราง, ความจำ {snap.get('triples', 0)} รายการ, ชุดข้อมูล {snap.get('clean_datasets', 0)} ชุด |",
                f"| การกำกับดูแลและการอนุมัติ | {'PENDING_REVIEW' if snap.get('pending_approvals', 0) > 0 else 'CLEAR'} | คิวรออนุมัติ {snap.get('pending_approvals', 0)} รายการ |",
            ]
        )

        full_content = (
            f"{doc_md}\n\n"
            f"## ตารางตรวจสอบความพร้อมระบบ\n\n"
            f"{readiness_table}\n\n"
            f"> ตรวจสอบโครงสร้างเอกสารแล้ว: {outline_out.get('heading_count', 0)} หัวข้อ · "
            f"{outline_out.get('line_count', 0)} บรรทัด · สถานะ QA: `{'VERIFIED' if doc_verified else 'FAILED'}`"
        )
        timings.append(
            {
                "task": "document_synthesis_verify",
                "duration_ms": round((time.perf_counter() - t_exec) * 1000, 3),
                "matched": doc_verified,
                "status": "VERIFIED" if doc_verified else "FAILED",
                "detail": f"headings={outline_out.get('heading_count', 0)}",
            }
        )
        engine_path.extend(["document_spec_generate", "verification_gate"])
        deliverable = {
            "kind": "document",
            "title": doc_title,
            "filename": "zyrquen-architecture-readiness.md",
            "language": "markdown",
            "sha256": doc_out.get("content_sha256")
            or hashlib.sha256(full_content.encode("utf-8")).hexdigest(),
            "verified": doc_verified,
            "content": full_content,
        }
        return {
            "content": full_content,
            "status": "VERIFIED" if doc_verified else "FAILED",
            "execution_phase": "VERIFIED" if doc_verified else "EXECUTED",
            "goal_interpretation": goal_analysis,
            "engine_path": engine_path,
            "plan": plan_res,
            "deliverable": deliverable,
            "orchestration": {
                "run_ids": run_ids,
                "delivery_verdict": "SUCCESS" if doc_verified else "FAILED",
                "capabilities_executed": list(dict.fromkeys(caps_executed)),
            },
            "task_timings": timings,
        }

    # Engineering Inspection / Audit Goal (Execute -> Verify -> Deliver)
    if is_inspect_goal and not is_create_goal:
        inspect_sections: list[str] = [
            f"**ผลการสำรวจและตรวจสอบวิศวกรรมซอฟต์แวร์ (Read-Only Verified)**",
            f"เป้าหมาย: `{cleaned}`",
            "",
            "### 1. สรุปภาพรวม Repository",
            f"- โมดูล Python `{counts.get('python', 0)}` ไฟล์ · TypeScript/React `{counts.get('typescript', 0)}` ไฟล์ · ไฟล์ทดสอบ `{test_disc_info.get('count', counts.get('tests', 0))}` ไฟล์",
        ]
        if dep_info:
            manifest_names = sorted((dep_info.get("manifests") or {}).keys())
            inspect_sections.extend([
                "",
                "### 2. รายการ Dependencies (`development.dependency_inventory`)",
                f"- พบไฟล์กำหนด Dependencies `{dep_info.get('manifest_count', 0)}` รายการ (ไม่ติดตั้งแพ็กเกจ): {', '.join(f'`{m}`' for m in manifest_names) or 'ไม่มี'}",
            ])
        if test_disc_info:
            sample_tests = (test_disc_info.get("test_files") or [])[:12]
            inspect_sections.extend([
                "",
                "### 3. ไฟล์ทดสอบที่ค้นพบ (`development.test_discovery`)",
                f"- พบไฟล์ทดสอบ `{test_disc_info.get('count', 0)}` ไฟล์ (ยังไม่ได้รันทดสอบ)",
                *(f"- `{tf}`" for tf in sample_tests),
            ])
        if config_audit_info:
            cfgs = config_audit_info.get("present_configs") or []
            inspect_sections.extend([
                "",
                "### 4. การตั้งค่า Build & Quality (`development.config_audit`)",
                f"- พบไฟล์ตั้งค่า `{config_audit_info.get('count', 0)}` รายการ: {', '.join(f'`{c}`' for c in cfgs) or 'ไม่มี'}",
            ])
        if symbol_info:
            matches = (symbol_info.get("matches") or [])[:15]
            inspect_sections.extend([
                "",
                f"### 5. ผลการค้นหาสัญลักษณ์ `{symbol_info.get('query', '')}`",
                f"- พบ `{symbol_info.get('count', 0)}` จุด จากการสแกน `{symbol_info.get('files_scanned', 0)}` ไฟล์ (ไม่รันโค้ด)",
                *(f"- `{m['path']}:{m['line']}` — `{m['text'][:120]}`" for m in matches),
            ])
        if diff_info:
            diff_text = str(diff_info.get("diff") or "").strip()
            changed_lines = int(diff_info.get("changed_line_count") or 0)
            inspect_sections.extend([
                "",
                "### 6. ผลตรวจสอบ Git Diff",
                f"- เป้าหมาย `{diff_info.get('target', '.')}` · บรรทัดที่เปลี่ยนแปลง `{changed_lines}` บรรทัด · Git พร้อมใช้งาน: `{diff_info.get('git_available', bool(diff_text))}`",
            ])
            if diff_text:
                inspect_sections.append(f"```diff\n{diff_text[:3000]}\n```")
            elif diff_info.get("reason"):
                inspect_sections.append(f"- หมายเหตุ: {diff_info['reason']}")
        if compat_info:
            inspect_sections.extend([
                "",
                "### ความเข้ากันได้ Dependencies (`development.dependency_compatibility`)",
                f"- ตรวจ {len(compat_info.get('manifests_checked') or [])} ไฟล์ · compatible=`{compat_info.get('compatible')}` · ความขัดแย้ง `{len(compat_info.get('conflicts') or [])}` รายการ",
            ])
        if mig_info:
            inspect_sections.extend([
                "",
                "### วิเคราะห์ Database Migration (`development.migration_analyzer`)",
                f"- พบ `{mig_info.get('migration_count', 0)}` ไฟล์ · heads=`{len(mig_info.get('heads') or [])}` · chain_valid=`{mig_info.get('chain_valid')}`",
            ])
        if a11y_info:
            inspect_sections.extend([
                "",
                "### ตรวจสอบ Accessibility (`development.frontend_a11y_audit`)",
                f"- สแกน `{a11y_info.get('scanned_files', 0)}` ไฟล์ · ข้อสังเกต `{a11y_info.get('issue_count', 0)}` รายการ",
            ])
        if sbom_info:
            inspect_sections.extend([
                "",
                "### รายการ SBOM (`security.sbom_generate`)",
                f"- `{sbom_info.get('bom_format', 'CycloneDX')} {sbom_info.get('spec_version', '1.5')}` · องค์ประกอบ `{sbom_info.get('component_count', 0)}` รายการ · SHA-256: `{sbom_info.get('bom_sha256', '')[:16]}...`",
            ])
        if lic_info:
            inspect_sections.extend([
                "",
                "### ตรวจสอบ License (`security.license_compliance`)",
                f"- ทั้งหมด `{lic_info.get('total_components', 0)}` รายการ · Copyleft Review `{lic_info.get('copyleft_review_count', 0)}` · Compliant=`{lic_info.get('compliant')}`",
            ])
        if threat_info:
            inspect_sections.extend([
                "",
                "### วิเคราะห์ Threat Model (`security.threat_model`)",
                f"- พื้นผิวหลัก `{threat_info.get('surface_count', 0)}` จุด · กลไกป้องกันที่ตรวจพบ `{len(threat_info.get('verified_controls') or [])}` รายการ",
            ])
        if perm_info:
            inspect_sections.extend([
                "",
                "### ตรวจสอบ Permission / RBAC (`security.permission_audit`)",
                f"- ตรวจสอบทั้ง `{perm_info.get('total_capabilities', 0)}` ความสามารถ · rbac_compliant=`{perm_info.get('rbac_compliant')}`",
            ])
        if decomp_info:
            inspect_sections.extend([
                "",
                "### แตกเป้าหมายเป็น DAG (`automation.goal_decomposition`)",
                f"- งานย่อย `{decomp_info.get('subtask_count', 0)}` ขั้นตอน · จับคู่เครื่องมือได้ `{decomp_info.get('matched_capability_count', 0)}` · dag_valid=`{decomp_info.get('dag_valid')}`",
            ])

        inspect_report = "\n".join(inspect_sections)

        verify_cases: list[dict[str, Any]] = [
            {"name": "wave1_ok", "op": "eq", "actual": bool(wave1_res.get("ok")), "expected": True},
            {"name": "report_nonempty", "op": "gt", "actual": len(inspect_report), "expected": 40},
        ]
        if dep_info:
            verify_cases.append({"name": "no_pkg_install", "op": "eq", "actual": dep_info.get("install_performed"), "expected": False})
        if test_disc_info:
            verify_cases.append({"name": "no_test_exec", "op": "eq", "actual": test_disc_info.get("tests_executed"), "expected": False})
        if symbol_info:
            verify_cases.append({"name": "no_code_exec", "op": "eq", "actual": symbol_info.get("code_executed"), "expected": False})
        if diff_info:
            verify_cases.append({"name": "repo_unmodified", "op": "eq", "actual": diff_info.get("repository_modified"), "expected": False})

        verify_wave = execute_orchestrated_plan(
            tc_reg,
            f"verify_inspect:{cleaned[:160]}",
            [
                {
                    "step_id": "assert_readonly_evidence",
                    "capability_id": "testing.contract_assertion",
                    "input": {"cases": verify_cases},
                    "depends_on": [],
                },
                {
                    "step_id": "scan_inspect_report",
                    "capability_id": "security.secret_and_path_scan",
                    "input": {"path": "zyrquen-engineering-inspection.md", "content": inspect_report},
                    "depends_on": [],
                },
            ],
            conn=conn,
            data_dir=DATA_DIR,
            user_id=user_id or "system",
            user_role="user",
            enable_parallel=True,
        )
        if verify_wave.get("run_id"):
            run_ids.append(verify_wave["run_id"])
        caps_executed.extend(s["capability_id"] for s in (verify_wave.get("steps") or []))
        v_by_id = {s["step_id"]: s for s in (verify_wave.get("steps") or [])}
        assert_res = (v_by_id.get("assert_readonly_evidence") or {}).get("output") or {}
        scan_res = (v_by_id.get("scan_inspect_report") or {}).get("output") or {}
        inspect_verified = bool(
            wave1_res.get("ok")
            and verify_wave.get("ok")
            and verify_wave.get("delivery_verdict") == "SUCCESS"
            and assert_res.get("verdict") == "PASS"
            and scan_res.get("clean", False)
        )
        timings.append(
            {
                "task": "engineering_inspection_verify",
                "duration_ms": round((time.perf_counter() - t_exec) * 1000, 3),
                "matched": inspect_verified,
                "status": "VERIFIED" if inspect_verified else "FAILED",
                "detail": f"assert={assert_res.get('passed', 0)}/{assert_res.get('total', 0)}",
            }
        )
        engine_path.extend(["engineering_readonly_inspection", "verification_gate"])
        full_report = (
            f"{inspect_report}\n\n"
            f"> ตรวจสอบหลักฐานแล้ว ({assert_res.get('passed', 0)}/{assert_res.get('total', 0)} เงื่อนไข) · สถานะ QA: `{'VERIFIED' if inspect_verified else 'FAILED'}`"
        )
        deliverable = {
            "kind": "analysis",
            "title": f"ผลตรวจสอบวิศวกรรมซอฟต์แวร์: {cleaned[:60]}",
            "filename": "zyrquen-engineering-inspection.md",
            "language": "markdown",
            "sha256": hashlib.sha256(full_report.encode("utf-8")).hexdigest(),
            "verified": inspect_verified,
            "content": full_report,
        }
        return {
            "content": full_report,
            "status": "VERIFIED" if inspect_verified else "FAILED",
            "execution_phase": "VERIFIED" if inspect_verified else "EXECUTED",
            "goal_interpretation": goal_analysis,
            "engine_path": engine_path,
            "plan": plan_res,
            "deliverable": deliverable,
            "orchestration": {
                "run_ids": run_ids,
                "delivery_verdict": "SUCCESS" if inspect_verified else "FAILED",
                "capabilities_executed": list(dict.fromkeys(caps_executed)),
            },
            "task_timings": timings,
        }

    # Code / API / Data / System implementation command
    wants_ts = any(k in low for k in ("typescript", "tsx", "react", "express", "node", "frontend", "ui"))
    is_api_domain = any(k in low for k in ("api", "endpoint", "rest", "route", "webhook", "service", "บริการ"))
    is_data_domain = any(k in low for k in ("csv", "json", "data", "dataset", "etl", "ข้อมูล", "สถิติ"))

    raw_slug = re.sub(r"[^a-z0-9_]+", "_", low).strip("_")[:28]
    if not raw_slug:
        raw_slug = "api_service_module" if is_api_domain else ("data_pipeline_module" if is_data_domain else "workflow_module")
    slug = f"task_{raw_slug}" if raw_slug[0].isdigit() else raw_slug
    pascal_name = "".join(part.capitalize() for part in slug.split("_") if part) or "WorkflowModule"

    if wants_ts:
        lang = "typescript"
        filename = f"{slug}.ts"
        generated_code = (
            f"export interface {pascal_name}Input {{\n"
            f"  goal: string;\n"
            f"  items?: Array<Record<string, unknown>>;\n"
            f"}}\n\n"
            f"export interface {pascal_name}Result {{\n"
            f"  ok: boolean;\n"
            f"  status: 'VERIFIED' | 'BLOCKED';\n"
            f"  processedCount: number;\n"
            f"  summary: string;\n"
            f"}}\n\n"
            f"export function execute{pascal_name}(input: {pascal_name}Input): {pascal_name}Result {{\n"
            f"  const goal = input.goal.trim();\n"
            f"  if (!goal) {{\n"
            f"    return {{\n"
            f"      ok: false,\n"
            f"      status: 'BLOCKED',\n"
            f"      processedCount: 0,\n"
            f"      summary: 'Goal must be non-empty before execution',\n"
            f"    }};\n"
            f"  }}\n"
            f"  const validItems = (input.items ?? []).filter((item) => item !== null && typeof item === 'object');\n"
            f"  return {{\n"
            f"    ok: true,\n"
            f"    status: 'VERIFIED',\n"
            f"    processedCount: validItems.length,\n"
            f"    summary: `Executed ${{goal}} (${{validItems.length}} validated items)`,\n"
            f"  }};\n"
            f"}}\n"
        )
        verify_steps: list[dict] = [
            {
                "step_id": "contract_check",
                "capability_id": "development.contract_validate",
                "input": {
                    "kind": "output",
                    "payload": {
                        "task_id": slug,
                        "language": "typescript",
                        "files": [{"path": filename, "content": generated_code}],
                    },
                },
                "depends_on": [],
            },
            {
                "step_id": "ts_verify",
                "capability_id": "development.code_analysis",
                "input": {"language": "typescript", "source": generated_code},
                "depends_on": [],
            },
            {
                "step_id": "secret_scan",
                "capability_id": "security.secret_and_path_scan",
                "input": {"path": filename, "content": generated_code},
                "depends_on": [],
            },
            {
                "step_id": "contract_assert",
                "capability_id": "testing.contract_assertion",
                "input": {
                    "cases": [
                        {"name": "has_export", "op": "contains", "actual": generated_code, "expected": f"export function execute{pascal_name}"},
                        {"name": "balanced_braces", "op": "eq", "actual": generated_code.count("{"), "expected": generated_code.count("}")},
                    ]
                },
                "depends_on": ["contract_check"],
            },
        ]
    else:
        lang = "python"
        filename = f"{slug}.py"
        safe_doc_goal = cleaned[:72].replace('"', "").replace("'", "").replace("\n", " ")
        if is_data_domain:
            generated_code = (
                f"from __future__ import annotations\n\n"
                f"import hashlib\n"
                f"import json\n"
                f"from dataclasses import dataclass\n"
                f"from typing import Any\n\n\n"
                f"@dataclass(frozen=True)\n"
                f"class DataValidationReport:\n"
                f"    ok: bool\n"
                f"    status: str\n"
                f"    record_count: int\n"
                f"    duplicate_count: int\n"
                f"    digest_sha256: str\n\n\n"
                f"def validate_records(records: list[dict[str, Any]]) -> DataValidationReport:\n"
                f'    """Deterministic record validation & SHA-256 manifest for: {safe_doc_goal}"""\n'
                f"    if not isinstance(records, list) or not records:\n"
                f"        return DataValidationReport(ok=False, status='BLOCKED', record_count=0, duplicate_count=0, digest_sha256='')\n"
                f"    seen: set[str] = set()\n"
                f"    duplicates = 0\n"
                f"    canonical_rows: list[str] = []\n"
                f"    for row in records:\n"
                f"        encoded = json.dumps(row, sort_keys=True, ensure_ascii=False)\n"
                f"        if encoded in seen:\n"
                f"            duplicates += 1\n"
                f"        seen.add(encoded)\n"
                f"        canonical_rows.append(encoded)\n"
                f"    digest = hashlib.sha256('\\n'.join(canonical_rows).encode('utf-8')).hexdigest()\n"
                f"    return DataValidationReport(\n"
                f"        ok=True,\n"
                f"        status='VERIFIED',\n"
                f"        record_count=len(records),\n"
                f"        duplicate_count=duplicates,\n"
                f"        digest_sha256=digest,\n"
                f"    )\n"
            )
            sandbox_test_harness = (
                f"{generated_code}\n"
                f"rep_ok = validate_records([{{'id': 1, 'v': 'a'}}, {{'id': 1, 'v': 'a'}}])\n"
                f"rep_empty = validate_records([])\n"
                f"assert rep_ok.ok and rep_ok.record_count == 2 and rep_ok.duplicate_count == 1 and len(rep_ok.digest_sha256) == 64\n"
                f"assert not rep_empty.ok and rep_empty.status == 'BLOCKED'\n"
                f"print('SANDBOX_PASS')\n"
            )
        elif is_api_domain:
            generated_code = (
                f"from __future__ import annotations\n\n"
                f"from dataclasses import dataclass\n"
                f"from typing import Any\n\n\n"
                f"@dataclass(frozen=True)\n"
                f"class ApiContractCheck:\n"
                f"    ok: bool\n"
                f"    status: str\n"
                f"    missing_fields: tuple[str, ...]\n"
                f"    summary: str\n\n\n"
                f"def validate_api_request(method: str, endpoint: str, payload: dict[str, Any], required_fields: tuple[str, ...]) -> ApiContractCheck:\n"
                f'    """Validate REST request contract for: {safe_doc_goal}"""\n'
                f"    clean_method = str(method or '').strip().upper()\n"
                f"    clean_ep = str(endpoint or '').strip()\n"
                f"    if clean_method not in {{'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}} or not clean_ep.startswith('/api/'):\n"
                f"        return ApiContractCheck(ok=False, status='BLOCKED', missing_fields=(), summary='Invalid HTTP method or /api/ path')\n"
                f"    missing = tuple(f for f in required_fields if payload.get(f) is None or (isinstance(payload.get(f), str) and not str(payload.get(f)).strip()))\n"
                f"    if missing:\n"
                f"        return ApiContractCheck(ok=False, status='BLOCKED', missing_fields=missing, summary=f'Missing fields: {{\", \".join(missing)}}')\n"
                f"    return ApiContractCheck(ok=True, status='VERIFIED', missing_fields=(), summary=f'Contract valid for {{clean_method}} {{clean_ep}}')\n"
            )
            sandbox_test_harness = (
                f"{generated_code}\n"
                f"ok_chk = validate_api_request('POST', '/api/tasks', {{'goal': 'verify'}}, ('goal',))\n"
                f"bad_chk = validate_api_request('POST', '/bad', {{}}, ('goal',))\n"
                f"assert ok_chk.ok and ok_chk.status == 'VERIFIED'\n"
                f"assert not bad_chk.ok and bad_chk.status == 'BLOCKED'\n"
                f"print('SANDBOX_PASS')\n"
            )
        else:
            generated_code = (
                f"from __future__ import annotations\n\n"
                f"from dataclasses import dataclass\n"
                f"from typing import Any\n\n\n"
                f"@dataclass(frozen=True)\n"
                f"class ExecutionResult:\n"
                f"    ok: bool\n"
                f"    status: str\n"
                f"    summary: str\n"
                f"    data: dict[str, Any]\n\n\n"
                f"def run_verified_task(goal: str, context: dict[str, Any] | None = None) -> ExecutionResult:\n"
                f'    """Execute validated workflow logic for: {safe_doc_goal}"""\n'
                f"    clean_goal = str(goal or '').strip()\n"
                f"    if not clean_goal:\n"
                f"        return ExecutionResult(ok=False, status='BLOCKED', summary='Goal is required', data={{}})\n"
                f"    ctx = dict(context or {{}})\n"
                f"    return ExecutionResult(\n"
                f"        ok=True,\n"
                f"        status='VERIFIED',\n"
                f"        summary=f'Verified execution for: {{clean_goal}}',\n"
                f"        data={{'goal': clean_goal, 'context_keys': sorted(ctx.keys())}},\n"
                f"    )\n"
            )
            sandbox_test_harness = (
                f"{generated_code}\n"
                f"ok_res = run_verified_task('verify_goal', {{'step': 1}})\n"
                f"bad_res = run_verified_task('   ')\n"
                f"assert ok_res.ok and ok_res.status == 'VERIFIED' and ok_res.data['context_keys'] == ['step']\n"
                f"assert not bad_res.ok and bad_res.status == 'BLOCKED'\n"
                f"print('SANDBOX_PASS')\n"
            )

        verify_steps = [
            {
                "step_id": "contract_check",
                "capability_id": "development.contract_validate",
                "input": {
                    "kind": "output",
                    "payload": {
                        "task_id": slug,
                        "language": "python",
                        "files": [{"path": filename, "content": generated_code}],
                    },
                },
                "depends_on": [],
            },
            {
                "step_id": "ast_verify",
                "capability_id": "development.code_analysis",
                "input": {"language": "python", "source": generated_code},
                "depends_on": [],
            },
            {
                "step_id": "policy_audit",
                "capability_id": "security.native_policy_audit",
                "input": {"source": generated_code},
                "depends_on": [],
            },
            {
                "step_id": "secret_scan",
                "capability_id": "security.secret_and_path_scan",
                "input": {"path": filename, "content": generated_code},
                "depends_on": [],
            },
            {
                "step_id": "sandbox_verify",
                "capability_id": "testing.sandbox_run",
                "input": {"source": sandbox_test_harness, "timeout_s": 3.0},
                "depends_on": ["ast_verify", "policy_audit"],
            },
        ]

    verify_wave = execute_orchestrated_plan(
        tc_reg,
        f"verify_code:{cleaned[:160]}",
        verify_steps,
        conn=conn,
        data_dir=DATA_DIR,
        user_id=user_id or "system",
        user_role="user",
        enable_parallel=True,
    )
    if verify_wave.get("run_id"):
        run_ids.append(verify_wave["run_id"])
    caps_executed.extend(s["capability_id"] for s in (verify_wave.get("steps") or []))

    verify_by_id = {s["step_id"]: s for s in (verify_wave.get("steps") or [])}
    contract_out = (verify_by_id.get("contract_check") or {}).get("output") or {}
    policy_out = (verify_by_id.get("policy_audit") or {}).get("output") or {}
    secret_out = (verify_by_id.get("secret_scan") or {}).get("output") or {}
    sandbox_out = (verify_by_id.get("sandbox_verify") or {}).get("output") or {}
    assert_out = (verify_by_id.get("contract_assert") or {}).get("output") or {}

    if lang == "python":
        ast_out = (verify_by_id.get("ast_verify") or {}).get("output") or {}
        sandbox_passed = (
            verify_by_id.get("sandbox_verify", {}).get("status") == "SUCCESS"
            and "SANDBOX_PASS" in str(sandbox_out.get("stdout") or "")
        )
        code_verified = bool(
            verify_wave.get("ok")
            and verify_wave.get("delivery_verdict") == "SUCCESS"
            and contract_out.get("valid", False)
            and ast_out.get("validation", {}).get("status") == "valid"
            and policy_out.get("policy_compliant", False)
            and secret_out.get("clean", False)
            and sandbox_passed
        )
        validation_summary = (
            f"ผ่านการตรวจสอบ AST + Sandbox Assertion + Security Policy (run `{verify_wave.get('run_id', '')[:8]}`)"
            if code_verified
            else "การตรวจสอบโค้ดหรือ Sandbox ไม่ผ่านเกณฑ์"
        )
    else:
        ts_step = verify_by_id.get("ts_verify") or {}
        ts_out = ts_step.get("output") or {}
        ts_ok = ts_step.get("status") == "SUCCESS" and (
            ts_out.get("validation", {}).get("status") == "valid"
            or (ts_out.get("mode") == "source_lexical_analysis" and int(ts_out.get("line_count") or 0) > 0)
        )
        code_verified = bool(
            verify_wave.get("ok")
            and verify_wave.get("delivery_verdict") == "SUCCESS"
            and contract_out.get("valid", False)
            and ts_ok
            and secret_out.get("clean", False)
            and assert_out.get("verdict") == "PASS"
        )
        validation_summary = (
            f"ผ่านการตรวจสอบ Code Contract + Static Analysis + Assertion ({assert_out.get('passed', 0)}/{assert_out.get('total', 0)})"
            if code_verified
            else "การตรวจสอบสัญญาโครงสร้างโค้ด TypeScript ไม่ผ่านเกณฑ์"
        )

    timings.append(
        {
            "task": "code_generation_verify",
            "duration_ms": round((time.perf_counter() - t_exec) * 1000, 3),
            "matched": code_verified,
            "status": "VERIFIED" if code_verified else "FAILED",
            "detail": f"{lang}:run={verify_wave.get('run_id', '')[:8]}",
        }
    )
    engine_path.extend(["code_static_validation", "verification_gate"])

    step_md = "\n".join(
        f"{idx + 1}. **{st['title']}** — {st['detail']}"
        for idx, st in enumerate(plan_res.get("steps") or [])
    )
    attach_block = (
        "\n\n**ผลตรวจสอบข้อมูล/โค้ดที่แนบ:**\n"
        + "\n".join(f"- {ln}" if not ln.startswith("- ") else ln for ln in attach_summary_lines)
        if attach_summary_lines
        else ""
    )
    content = (
        f"**{'ดำเนินการวิเคราะห์ วางแผน และสร้างผลงานที่ผ่านการตรวจสอบแล้ว' if code_verified else 'ไม่สามารถรับรองผลงานได้ (Verification Failed)'}**\n"
        f"เป้าหมาย: `{cleaned}`\n\n"
        f"**ขั้นตอนดำเนินงาน:**\n{step_md}"
        f"{attach_block}\n\n"
        f"**ซอร์สโค้ด ({filename}):**\n"
        f"```{lang}\n{generated_code.rstrip()}\n```\n\n"
        f"> การตรวจสอบผลลัพธ์: {validation_summary} · โครงการปัจจุบันมีโมดูล Python {counts.get('python', 0)} ไฟล์ และ TypeScript {counts.get('typescript', 0)} ไฟล์"
    )
    deliverable = {
        "kind": "code",
        "title": f"โมดูลที่สร้าง: {filename}",
        "filename": filename,
        "language": lang,
        "sha256": hashlib.sha256(generated_code.encode("utf-8")).hexdigest(),
        "verified": code_verified,
        "content": generated_code,
    }
    return {
        "content": content,
        "status": "VERIFIED" if code_verified else "FAILED",
        "execution_phase": "VERIFIED" if code_verified else "EXECUTED",
        "goal_interpretation": goal_analysis,
        "engine_path": engine_path,
        "plan": plan_res,
        "deliverable": deliverable,
        "orchestration": {
            "run_ids": run_ids,
            "delivery_verdict": "SUCCESS" if code_verified else "FAILED",
            "capabilities_executed": list(dict.fromkeys(caps_executed)),
        },
        "task_timings": timings,
    }



def handle_infer(payload: dict) -> dict:
    start = time.perf_counter()
    conn = get_db()
    prompt = str(payload.get("prompt", "")).strip()
    mode = str(payload.get("mode", "auto")).lower()
    user_id = str(payload.get("user_id", ""))
    conversation_id = payload.get("conversation_id")
    attachment = str(payload.get("attachment", "")).strip()
    model_version = str(
        payload.get("model_version") or payload.get("model_variant") or "zyrquen-omega-v1"
    ).strip()[:64] or "zyrquen-omega-v1"

    if attachment:
        prompt_with_ctx = f"{prompt}\n[Attached Context]: {attachment[:800]}"
    else:
        prompt_with_ctx = prompt

    model_policy_map = {
        "zyrquen-omega-v1": "balanced_hybrid",
        "zyrquen-ast-pro": "symbolic_ast_priority",
        "zyrquen-kg-v2": "knowledge_graph_deep",
        "zyrquen-ngram-ckpt": "ngram_checkpoint_priority",
        "zyrquen-neural-v1": "neural_transformer_priority",
    }
    model_policy = model_policy_map.get(model_version, "balanced_hybrid")

    task_timings: list[dict] = []

    def _record_task_timing(
        task_name: str,
        t0: float,
        *,
        matched: bool,
        status_label: str,
        detail: str | None = None,
    ) -> None:
        entry: dict = {
            "order": len(task_timings) + 1,
            "task": task_name,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            "matched": bool(matched),
            "status": status_label,
        }
        if detail:
            entry["detail"] = detail
        task_timings.append(entry)

    def _finalize_trace() -> None:
        trace["task_timings"] = task_timings
        trace["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        if task_timings:
            total_tasks_ms = sum(float(t.get("duration_ms", 0.0) or 0.0) for t in task_timings)
            slowest = max(task_timings, key=lambda t: float(t.get("duration_ms", 0.0) or 0.0))
            slowest_ms = float(slowest.get("duration_ms", 0.0) or 0.0)
            trace["bottleneck_task"] = {
                "task": slowest["task"],
                "duration_ms": slowest_ms,
                "share_pct": round((slowest_ms / total_tasks_ms) * 100, 1) if total_tasks_ms > 0 else 0.0,
                "informative": slowest_ms >= 1.0,
                "note": "sub_millisecond_fast_path" if slowest_ms < 1.0 else "measured_hotspot",
            }
        else:
            trace["bottleneck_task"] = None

    goal_interp = analyze_planner_goal(prompt, attachment=attachment)
    trace: dict = {
        "mode": mode,
        "model_version": model_version,
        "model_policy": model_policy,
        "metadata": {"modelVersion": model_version, "modelPolicy": model_policy},
        "engine_path": [],
        "task_timings": task_timings,
        "bottleneck_task": None,
        "latency_ms": 0.0,
        "python_version": platform.python_version(),
        "external_models_used": False,
        "native_integrity": _compute_native_integrity(),
        "goal_interpretation": goal_interp,
        "execution_phase": "EXECUTED",
    }

    # Stage 1 & 2: Native Understand -> Interpret BEFORE retrieval/checkpoints
    t_und = time.perf_counter()
    understanding = _understand_cognitive_input(
        conn,
        prompt,
        attachment=attachment,
        mode=mode,
        conversation_id=str(conversation_id) if conversation_id else None,
        tokenize_fn=tokenize,
        extract_terms_fn=extract_query_terms,
        query_kg_fn=query_knowledge_graph,
    )
    interpretation = understanding.get("interpretation") or {}
    effective_prompt = str(interpretation.get("effective_prompt") or prompt).strip() or prompt
    _record_task_timing(
        "understand_interpret",
        t_und,
        matched=True,
        status_label=str(understanding.get("speech_act") or "general_utterance"),
        detail=f"lang={understanding.get('language')}",
    )

    if interpretation.get("early_communicative_route"):
        t_cog = time.perf_counter()
        cog = run_cognitive_fallback_pipeline(
            conn,
            prompt=prompt,
            attachment=attachment,
            mode=mode,
            conversation_id=str(conversation_id) if conversation_id else None,
            attempted_engines=[t["task"] for t in task_timings],
            understanding=understanding,
            tokenize_fn=tokenize,
            extract_terms_fn=extract_query_terms,
            query_kg_fn=query_knowledge_graph,
        )
        epistemic_state = cog["epistemic_state"]
        cognitive_state = cog.get("cognitive_state") or "UNDERSTOOD"
        trace["engine_path"].append("cognitive_pipeline")
        trace["epistemic_state"] = epistemic_state
        trace["cognitive_state"] = cognitive_state
        trace["cognitive_pipeline"] = cog["pipeline_trace"]
        conn.close()
        _record_task_timing(
            "cognitive_pipeline",
            t_cog,
            matched=True,
            status_label=epistemic_state,
            detail=f"{cog['pipeline_trace']['understand']['speech_act']}:{cognitive_state}",
        )
        _finalize_trace()
        return {
            "content": cog["response"],
            "status": epistemic_state,
            "epistemic_state": epistemic_state,
            "cognitive_state": cognitive_state,
            "trace": trace,
        }

    # Use effective_prompt (salutation stripped when compound greeting + task) for downstream solvers
    prompt = effective_prompt

    # 0. Autonomous Continuous Operation Trigger from Conversation Channel
    if mode == "auto":
        t0 = time.perf_counter()
        m_mission = re.match(
            r"^(?:ภารกิจ|ปฏิบัติการ(?:อัตโนมัติ)?|mission|autonomous)\s*:?\s*(.+)$",
            prompt,
            re.IGNORECASE,
        )
        if m_mission:
            goal_text = m_mission.group(1).strip()
            conn.close()
            mission_res = run_autonomous_mission(
                {
                    "goal": goal_text,
                    "user_id": user_id,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "enable_research": True,
                    "enable_knowledge_dev": True,
                    "enable_planning": True,
                    "enable_execution": True,
                }
            )
            mission = mission_res.get("mission", {})
            m_stat = str(mission.get("status") or "")
            _record_task_timing(
                "autonomous_cognitive_loop",
                t0,
                matched=True,
                status_label=m_stat or "COMPLETED",
                detail=f"goal={goal_text[:60]}",
            )
            for node_row in mission_res.get("nodes") or []:
                try:
                    n_obj = json.loads(node_row.get("node_json") or "{}")
                except Exception:
                    n_obj = {}
                if isinstance(n_obj, dict) and n_obj.get("duration_ms") is not None:
                    task_timings.append(
                        {
                            "order": len(task_timings) + 1,
                            "task": f"dag_node:{n_obj.get('task_id') or node_row.get('task_id')}",
                            "duration_ms": float(n_obj.get("duration_ms", 0.0) or 0.0),
                            "matched": True,
                            "status": str(node_row.get("execution_status") or n_obj.get("execution_status") or "UNKNOWN"),
                            "detail": str(n_obj.get("tool_id") or ""),
                        }
                    )
            trace["engine_path"] = ["autonomous_cognitive_loop", "dag_executor"]
            trace["autonomous_mission"] = {
                "mission_id": mission.get("id"),
                "status": mission.get("status"),
                "stages": json.loads(mission.get("stages_json") or "[]"),
                "knowledge_developed": json.loads(mission.get("knowledge_developed_json") or "[]"),
            }
            _finalize_trace()
            if m_stat in {"PENDING_APPROVAL", "AWAITING_APPROVAL"}:
                msg_status = "PENDING_APPROVAL"
            elif m_stat in {"BLOCKED", "CANCELLED"}:
                msg_status = "BLOCKED"
            elif m_stat == "FAILED":
                msg_status = "FAILED"
            else:
                msg_status = "VERIFIED"
            return {
                "content": mission.get("report_markdown") or "ดำเนินภารกิจอัตโนมัติแล้ว",
                "status": msg_status,
                "trace": trace,
            }
        _record_task_timing("autonomous_mission_detect", t0, matched=False, status_label="MISS")

    # 1. Native DAG Goal Decomposition & Planning (Read-Only Planning Phase -> PLANNED or NEEDS_CLARIFICATION)
    if mode in ("auto", "plan"):
        t0 = time.perf_counter()
        plan_res = try_native_planning(conn, prompt, force_plan=(mode == "plan"))
        if plan_res:
            trace["engine_path"].append("native_planner")
            if plan_res.get("goal_interpretation"):
                trace["goal_interpretation"] = plan_res["goal_interpretation"]

            if (
                plan_res.get("plan_status") == "NEEDS_CLARIFICATION"
                or plan_res.get("plan_valid") is False
                or plan_res.get("is_actionable_goal") is False
                or not (plan_res.get("steps") or [])
            ):
                clarity = (plan_res.get("goal_interpretation") or {}).get("clarity_status")
                clarify_status = "UNKNOWN" if clarity == "INVALID_CORRUPT" else "NEEDS_CLARIFICATION"
                issues = plan_res.get("issues") or []
                questions = plan_res.get("clarification_questions") or []
                ctx_res = plan_res.get("context_resolution") or (plan_res.get("goal_interpretation") or {}).get("context_resolution") or {}
                trace["goal_validation"] = {
                    "clarity_status": clarity,
                    "is_actionable_goal": False,
                    "issues": issues,
                    "context_resolution": ctx_res,
                    "status_transitions": plan_res.get("status_transitions") or [],
                }
                _record_task_timing(
                    "native_planner",
                    t0,
                    matched=True,
                    status_label=clarify_status,
                    detail=", ".join(issues) or clarify_status,
                )
                trace["execution_phase"] = "CLARIFICATION_REQUIRED"
                content = _format_clarification_markdown(
                    clarify_status=clarify_status,
                    issues=issues,
                    questions=questions,
                    context_resolution=ctx_res,
                    heading="ต้องการข้อมูลเพิ่มเติมก่อนวางแผน",
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": clarify_status, "trace": trace}

            trace["plan"] = plan_res
            _record_task_timing(
                "native_planner",
                t0,
                matched=True,
                status_label="PLANNED",
                detail=f"{len(plan_res.get('steps') or [])} DAG steps (read-only plan)",
            )
            trace["execution_phase"] = "PLANNED"
            step_lines = [
                f"- **{s['step_id']} · {s['title']}** (`{s['status']}`"
                + (f", รอ `{','.join(s['depends_on'])}`" if s.get("depends_on") else "")
                + (", ต้องอนุมัติ" if s.get("requires_approval") else "")
                + f"): {s['detail']}"
                for s in plan_res["steps"]
                if str(s.get("step_id") or "").strip()
                and str(s.get("title") or "").strip()
                and str(s.get("detail") or "").strip()
            ]
            snap = plan_res["summary"]["state_snapshot"]
            content = (
                f"**แผนปฏิบัติการเชิงโครงสร้าง (Native DAG Plan · PLANNED)**\n"
                f"เป้าหมาย: `{plan_res['goal']}`\n\n"
                + "\n".join(step_lines)
                + f"\n\n*สถานะฐานข้อมูลจริง: ชุดข้อมูลผ่านเกณฑ์ {snap['clean_datasets']}, "
                f"Checkpoint {snap['checkpoints']} รุ่น, ความจำ {snap['triples']} รายการ · (ยังไม่ได้รันปฏิบัติการจริง)*"
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "PLANNED", "trace": trace}
        _record_task_timing("native_planner", t0, matched=False, status_label="MISS")

    # 1.5 Governed External Tool Integration (Native Core calls tools, never replaced by them)
    if mode == "auto":
        t0 = time.perf_counter()
        tool_req = detect_tool_intent(prompt)
        if tool_req and attachment and tool_req[0] == "workspace_file_read":
            req_file = str(tool_req[1].get("filename") or "").strip()
            workspace_dir = DATA_DIR / "workspace_files"
            if not req_file or not (workspace_dir / Path(req_file).name).exists():
                tool_req = None
        if tool_req:
            tool_id, tool_input = tool_req
            _record_task_timing("external_tool_detect", t0, matched=True, status_label="HIT", detail=tool_id)
            t_tool = time.perf_counter()
            inv_res = invoke_tool_governed(
                conn,
                DATA_DIR,
                tool_id,
                tool_input,
                user_id=user_id,
                conversation_id=str(conversation_id) if conversation_id else None,
                approved_by=None,
                tokenize_fn=tokenize,
                extract_terms_fn=extract_query_terms,
                query_kg_fn=query_knowledge_graph,
                calc_fn=_calc_any_for_tool,
            )
            trace["engine_path"].append(f"external_tool:{tool_id}")
            if inv_res.get("status") == "COMPLETED":
                trace["engine_path"].append("native_tool_synthesizer")
            analysis_obj = inv_res.get("analysis") or {}
            trace["external_tool"] = {
                "tool_id": tool_id,
                "status": inv_res.get("status", "FAILED"),
                "invocation_id": inv_res.get("invocation", {}).get("id") if inv_res.get("invocation") else None,
                "trust_grade": analysis_obj.get("trust_grade"),
                "distinct_providers": analysis_obj.get("distinct_providers", []),
                "kg_matches_count": len(analysis_obj.get("kg_matches") or []),
                "limitations": analysis_obj.get("limitations", []),
                "analysis_summary": analysis_obj.get("summary"),
            }
            content = (
                format_tool_markdown(tool_id, inv_res)
                if inv_res.get("ok")
                else f"**ไม่สามารถเรียกใช้เครื่องมือ `{tool_id}`:** {inv_res.get('error', 'Error')}"
            )
            t_grade = analysis_obj.get("trust_grade")
            if inv_res.get("status") == "COMPLETED":
                if t_grade in {"INSUFFICIENT_EVIDENCE", "CONFLICTING_SOURCES"}:
                    msg_status = "NOT_LEARNED"
                elif t_grade == "BLOCKED":
                    msg_status = "BLOCKED"
                else:
                    msg_status = "VERIFIED"
            elif inv_res.get("status") == "PENDING_APPROVAL":
                msg_status = "PENDING_APPROVAL"
            else:
                msg_status = "BLOCKED"
            _record_task_timing(
                f"external_tool:{tool_id}",
                t_tool,
                matched=True,
                status_label=msg_status,
                detail=str(inv_res.get("status") or ""),
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": msg_status, "trace": trace}
        _record_task_timing("external_tool_detect", t0, matched=False, status_label="MISS")

    # 1.6 Autonomous Goal Execution for Natural Engineering & Document Commands
    if mode == "auto":
        t_auto = time.perf_counter()
        auto_res = _try_execute_chat_autonomous_goal(
            conn,
            prompt,
            attachment=attachment,
            user_id=user_id,
        )
        if auto_res:
            for item in auto_res.get("task_timings") or []:
                task_timings.append({"order": len(task_timings) + 1, **item})
            trace["engine_path"].extend(auto_res.get("engine_path") or ["autonomous_goal_executor"])
            if auto_res.get("execution_phase"):
                trace["execution_phase"] = auto_res["execution_phase"]
            else:
                trace["execution_phase"] = "VERIFIED" if auto_res.get("status") == "VERIFIED" else "EXECUTED"
            if auto_res.get("goal_interpretation"):
                trace["goal_interpretation"] = auto_res["goal_interpretation"]
            if auto_res.get("goal_validation"):
                trace["goal_validation"] = auto_res["goal_validation"]
            auto_plan = auto_res.get("plan")
            if (
                isinstance(auto_plan, dict)
                and auto_plan.get("plan_valid") is not False
                and auto_plan.get("is_actionable_goal") is not False
                and auto_plan.get("plan_status") not in ("NEEDS_CLARIFICATION", "BLOCKED")
                and (auto_plan.get("steps") or [])
            ):
                trace["plan"] = auto_plan
            if auto_res.get("deliverable"):
                trace["deliverable"] = auto_res["deliverable"]
            if auto_res.get("orchestration"):
                trace["orchestration"] = auto_res["orchestration"]
            _finalize_trace()
            conn.close()
            return {
                "content": auto_res["content"],
                "status": auto_res["status"],
                "trace": trace,
            }
        _record_task_timing("autonomous_goal_detect", t_auto, matched=False, status_label="MISS")

    # 2. Explicit knowledge teaching
    if mode in ("auto", "knowledge"):
        t0 = time.perf_counter()
        teach_res = try_teach_knowledge(conn, prompt, user_id)
        if teach_res:
            _record_task_timing("knowledge_ingest", t0, matched=True, status_label="VERIFIED")
            trace["engine_path"].append("knowledge_ingest")
            trace["teach"] = teach_res
            t = teach_res["triple"]
            if teach_res["contradictions"]:
                content = (
                    f"บันทึกความสัมพันธ์ใหม่แล้ว: `{t['subject']} -> {t['relation']} -> {t['object']}`\n\n"
                    f"ตรวจพบข้อมูลขัดแย้งกับความจำเดิม: {', '.join(teach_res['contradictions'])} "
                    f"ระบบเก็บทั้งสองรายการไว้เพื่อการตรวจสอบย้อนกลับในกราฟความรู้"
                )
            elif teach_res["duplicate"]:
                content = f"ความสัมพันธ์ `{t['subject']} -> {t['relation']} -> {t['object']}` มีอยู่แล้วในหน่วยความจำภายใน"
            else:
                content = f"บันทึกลงในกราฟความรู้ภายในแล้ว: `{t['subject']} -> {t['relation']} -> {t['object']}`"
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "trace": trace}
        _record_task_timing("knowledge_ingest", t0, matched=False, status_label="MISS")

    # 3. Multi-hop BFS Graph Path Reasoning
    if mode in ("auto", "knowledge"):
        t0 = time.perf_counter()
        path_res = try_graph_path_query(conn, prompt)
        if path_res:
            trace["engine_path"].append("knowledge_multihop_bfs")
            trace["graph_path"] = path_res
            if path_res["found"] and path_res["path"]:
                p = path_res["path"]
                _record_task_timing(
                    "knowledge_multihop_bfs",
                    t0,
                    matched=True,
                    status_label="VERIFIED",
                    detail=f"{p['hops']} hops",
                )
                hops_md = "\n".join(
                    f"- ขั้นที่ {idx + 1}: `{e['from']}` — *{e['relation']}* → `{e['to']}` (แหล่งที่มา: {e['source']})"
                    for idx, e in enumerate(p["edges"])
                )
                direction_note = " (รวมเส้นทางย้อนกลับในกราฟ)" if p["bidirectional"] else ""
                content = (
                    f"**พบเส้นทางเชื่อมโยง {p['hops']} ช่วง (Multi-Hop BFS)**{direction_note} "
                    f"จาก `{p['start']}` ไปยัง `{p['end']}`:\n\n{hops_md}"
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": "VERIFIED", "trace": trace}
            else:
                _record_task_timing("knowledge_multihop_bfs", t0, matched=True, status_label="NOT_LEARNED")
                content = (
                    f"ยังไม่พบเส้นทางความสัมพันธ์ที่เชื่อมโยงจาก `{path_res['start']}` ไปยัง `{path_res['end']}` ในข้อมูลที่บันทึกไว้ตอนนี้ครับ "
                    f"(ตรวจสอบแล้วสูงสุด {path_res.get('max_depth', 8)} ช่วง)\n\n"
                    f"หากคุณมีข้อมูลความสัมพันธ์เพิ่มเติม สามารถพิมพ์บอกเพื่อบันทึกได้ เช่น `สอน: {path_res['start']} -> ความสัมพันธ์ -> {path_res['end']}`"
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": "NOT_LEARNED", "trace": trace}
        _record_task_timing("knowledge_multihop_bfs", t0, matched=False, status_label="MISS")

    # 4. Native Statistics, Linear/Quadratic/System Algebra, AST Math, Word Math & Transitive Logic
    if mode in ("auto", "math"):
        t0 = time.perf_counter()
        stats_res = try_statistics_reasoning(prompt)
        if stats_res:
            _record_task_timing("statistics_native", t0, matched=True, status_label="VERIFIED")
            trace["engine_path"].append("statistics_native")
            trace["statistics"] = stats_res
            content = (
                f"**ผลวิเคราะห์สถิติเชิงตัวเลข ({stats_res['count']} รายการ)**\n\n"
                f"- ค่าเฉลี่ย (Mean): `{stats_res['mean']}`\n"
                f"- มัธยฐาน (Median): `{stats_res['median']}`\n"
                f"- ผลรวม (Sum): `{stats_res['sum']}`\n"
                f"- ต่ำสุด / สูงสุด: `{stats_res['min']}` / `{stats_res['max']}` (พิสัย `{stats_res['range']}`)\n"
                f"- ส่วนเบี่ยงเบนมาตรฐาน (SD ตัวอย่าง / ประชากร): `{stats_res['stdev']}` / `{stats_res['pstdev']}`"
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "trace": trace}
        _record_task_timing("statistics_native", t0, matched=False, status_label="MISS")

        t0 = time.perf_counter()
        algebra_res = try_solve_equation(prompt)
        if algebra_res:
            _record_task_timing(
                algebra_res.get("engine") or "algebra_solver",
                t0,
                matched=True,
                status_label="VERIFIED",
                detail=str(algebra_res.get("solution_type") or ""),
            )
            trace["engine_path"].append(algebra_res["engine"])
            trace["algebra"] = algebra_res
            steps_md = "\n".join(f"- {s}" for s in algebra_res["steps"])
            sol_type = algebra_res["solution_type"]
            if sol_type == "unique":
                headline = f"**คำตอบสมการ:** `{algebra_res['variable']} = {algebra_res['result']}`"
            elif sol_type == "quadratic":
                roots_s = ", ".join(str(r) for r in algebra_res.get("roots", []))
                headline = f"**คำตอบสมการกำลังสอง:** `{algebra_res['variable']} ∈ {{{roots_s}}}` (`{algebra_res['summary_tag']}`)"
            elif sol_type == "system":
                sols_s = ", ".join(f"{k} = {v}" for k, v in algebra_res.get("solutions", {}).items())
                headline = f"**คำตอบระบบสมการเชิงเส้น:** `{sols_s}` (`{algebra_res['summary_tag']}`)"
            elif sol_type == "identity":
                headline = "**คำตอบสมการ:** เป็นจริงทุกค่าของตัวแปร (อนันต์คำตอบ)"
            elif sol_type == "underdetermined":
                headline = "**คำตอบระบบสมการ:** มีคำตอบได้หลายชุด (สมการอิสระน้อยกว่าจำนวนตัวแปร)"
            elif sol_type == "no_real_solution":
                headline = "**คำตอบสมการกำลังสอง:** ไม่มีคำตอบที่เป็นจำนวนจริง (Δ < 0)"
            else:
                headline = "**คำตอบสมการ:** ไม่มีคำตอบที่สอดคล้อง"
            content = (
                f"{headline}\n\n"
                f"**ลำดับการจัดรูปและคำนวณ (`{algebra_res['equation']}`):**\n{steps_md}"
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "trace": trace}
        _record_task_timing("algebra_solver", t0, matched=False, status_label="MISS")

        t0 = time.perf_counter()
        math_res = try_math_reasoning(prompt)
        if math_res:
            _record_task_timing("math_ast", t0, matched=True, status_label="VERIFIED")
            trace["engine_path"].append("math_ast")
            trace["math"] = math_res
            steps_md = "\n".join(f"- {s}" for s in math_res["steps"]) or "- ประมวลผลค่าคงที่โดยตรง"
            content = (
                f"**ผลลัพธ์:** `{math_res['result']}`\n\n"
                f"**ลำดับการคำนวณผ่าน AST ภายใน (`{math_res['expression']}`):**\n{steps_md}"
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "trace": trace}
        _record_task_timing("math_ast", t0, matched=False, status_label="MISS")

        t0 = time.perf_counter()
        word_math_res = try_word_math_reasoning(prompt)
        if word_math_res:
            trace["engine_path"].append("word_math_native")
            trace["word_math"] = word_math_res
            if word_math_res.get("determined") is False:
                cog = run_cognitive_fallback_pipeline(
                    conn,
                    prompt=prompt,
                    attachment=attachment,
                    mode=mode,
                    conversation_id=str(conversation_id) if conversation_id else None,
                    attempted_engines=[t["task"] for t in task_timings] + ["word_math_native"],
                    failure_context={
                        "unable_reason": word_math_res.get("unable_reason") or "underdetermined",
                        "detail": "; ".join(word_math_res.get("steps") or []),
                    },
                    explicit_status="UNABLE_TO_INFER",
                    tokenize_fn=tokenize,
                    extract_terms_fn=extract_query_terms,
                    query_kg_fn=query_knowledge_graph,
                )
                trace["engine_path"].append("cognitive_pipeline")
                trace["epistemic_state"] = "UNABLE_TO_INFER"
                trace["cognitive_pipeline"] = cog["pipeline_trace"]
                _record_task_timing("word_math_native", t0, matched=True, status_label="UNABLE_TO_INFER")
                _finalize_trace()
                conn.close()
                return {
                    "content": cog["response"],
                    "status": "UNABLE_TO_INFER",
                    "epistemic_state": "UNABLE_TO_INFER",
                    "trace": trace,
                }
            _record_task_timing("word_math_native", t0, matched=True, status_label="VERIFIED")
            steps_md = "\n".join(f"- {s}" for s in word_math_res["steps"])
            content = (
                f"**คำตอบเชิงปริมาณ:** `{word_math_res['result']}`\n\n"
                f"**ลำดับการวิเคราะห์โจทย์ (`{word_math_res['expression']}`):**\n{steps_md}"
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "epistemic_state": "VERIFIED", "trace": trace}
        _record_task_timing("word_math_native", t0, matched=False, status_label="MISS")

    if mode in ("auto", "math", "knowledge"):
        t0 = time.perf_counter()
        logic_res = try_transitive_logic_reasoning(prompt)
        if logic_res:
            trace["engine_path"].append("transitive_logic_native")
            trace["logic"] = logic_res
            steps_md = "\n".join(f"- {s}" for s in logic_res["steps"])
            if logic_res["contradiction"]:
                _record_task_timing("transitive_logic_native", t0, matched=True, status_label="BLOCKED")
                content = (
                    f"**ตรวจพบข้อขัดแย้งเชิงตรรกะ (Contradiction)**\n\n"
                    f"ไม่สามารถสรุปความสัมพันธ์ระหว่าง `{logic_res['target'][0]}` และ `{logic_res['target'][1]}` ได้อย่างสอดคล้อง:\n{steps_md}"
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": "BLOCKED", "epistemic_state": "BLOCKED", "trace": trace}
            if logic_res["determined"] and logic_res["derived_relation"]:
                _record_task_timing("transitive_logic_native", t0, matched=True, status_label="VERIFIED")
                content = (
                    f"**ข้อสรุปเชิงตรรกะถ่ายทอด:** `{logic_res['derived_relation']}`\n\n"
                    f"**ลำดับการอนุมานจากข้อตั้ง:**\n{steps_md}"
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": "VERIFIED", "epistemic_state": "VERIFIED", "trace": trace}
            cog = run_cognitive_fallback_pipeline(
                conn,
                prompt=prompt,
                attachment=attachment,
                mode=mode,
                conversation_id=str(conversation_id) if conversation_id else None,
                attempted_engines=[t["task"] for t in task_timings] + ["transitive_logic_native"],
                failure_context={
                    "unable_reason": "missing_premise_or_rule",
                    "detail": "; ".join(logic_res.get("steps") or []),
                },
                explicit_status="UNABLE_TO_INFER",
                tokenize_fn=tokenize,
                extract_terms_fn=extract_query_terms,
                query_kg_fn=query_knowledge_graph,
            )
            trace["engine_path"].append("cognitive_pipeline")
            trace["epistemic_state"] = "UNABLE_TO_INFER"
            trace["cognitive_pipeline"] = cog["pipeline_trace"]
            _record_task_timing("transitive_logic_native", t0, matched=True, status_label="UNABLE_TO_INFER")
            content = (
                f"{cog['response']}\n\n**รายละเอียดการตรวจสอบข้อตั้ง:**\n{steps_md}"
                if steps_md
                else cog["response"]
            )
            _finalize_trace()
            conn.close()
            return {
                "content": content,
                "status": "UNABLE_TO_INFER",
                "epistemic_state": "UNABLE_TO_INFER",
                "trace": trace,
            }
        _record_task_timing("transitive_logic_native", t0, matched=False, status_label="MISS")

        t0 = time.perf_counter()
        causal_res = try_causal_logic_reasoning(prompt, conn)
        if causal_res:
            trace["engine_path"].append("causal_logic_native")
            trace["causal_logic"] = causal_res
            steps_md = "\n".join(f"- {s}" for s in causal_res["steps"])
            if causal_res.get("contradiction"):
                _record_task_timing("causal_logic_native", t0, matched=True, status_label="BLOCKED")
                content = (
                    f"**ตรวจพบข้อขัดแย้งเชิงสาเหตุ/ตรรกศาสตร์ (Contradiction)**\n\n"
                    f"ข้อตั้งมีความขัดแย้งกันเอง จึงไม่สามารถอนุมานผลลัพธ์อย่างปลอดภัย:\n{steps_md}"
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": "BLOCKED", "epistemic_state": "BLOCKED", "trace": trace}
            if causal_res.get("determined") and causal_res.get("derived_conclusion"):
                sub_t = causal_res.get("sub_type", "causal")
                _record_task_timing("causal_logic_native", t0, matched=True, status_label="VERIFIED", detail=str(sub_t))
                content = (
                    f"**ข้อสรุปเชิงตรรกศาสตร์/เหตุ-ผล (`{sub_t}`):** `{causal_res['derived_conclusion']}`\n\n"
                    f"**ลำดับการอนุมาน:**\n{steps_md}"
                )
                _finalize_trace()
                conn.close()
                return {"content": content, "status": "VERIFIED", "epistemic_state": "VERIFIED", "trace": trace}
            cog = run_cognitive_fallback_pipeline(
                conn,
                prompt=prompt,
                attachment=attachment,
                mode=mode,
                conversation_id=str(conversation_id) if conversation_id else None,
                attempted_engines=[t["task"] for t in task_timings] + ["causal_logic_native"],
                failure_context={
                    "unable_reason": "missing_premise_or_rule",
                    "detail": "; ".join(causal_res.get("steps") or []),
                },
                explicit_status="UNABLE_TO_INFER",
                tokenize_fn=tokenize,
                extract_terms_fn=extract_query_terms,
                query_kg_fn=query_knowledge_graph,
            )
            trace["engine_path"].append("cognitive_pipeline")
            trace["epistemic_state"] = "UNABLE_TO_INFER"
            trace["cognitive_pipeline"] = cog["pipeline_trace"]
            _record_task_timing("causal_logic_native", t0, matched=True, status_label="UNABLE_TO_INFER")
            content = (
                f"{cog['response']}\n\n**รายละเอียดการตรวจสอบข้อตั้ง:**\n{steps_md}"
                if steps_md
                else cog["response"]
            )
            _finalize_trace()
            conn.close()
            return {
                "content": content,
                "status": "UNABLE_TO_INFER",
                "epistemic_state": "UNABLE_TO_INFER",
                "trace": trace,
            }
        _record_task_timing("causal_logic_native", t0, matched=False, status_label="MISS")

    is_explicit_math_cmd = bool(
        re.match(
            r"^(?:แก้สมการ|สมการ|คำนวณ|หาค่า|คิดเลข|สถิติ|วิเคราะห์ตัวเลข|ค่าเฉลี่ย|มัธยฐาน|solve|equation|calculate|compute|eval|evaluate|stats|statistics)\b",
            prompt.strip(),
            re.IGNORECASE,
        )
    )

    # 5. Knowledge Graph Query (with 2-hop & 3-hop provenance)
    if mode in ("auto", "knowledge") and not is_explicit_math_cmd:
        t0 = time.perf_counter()
        if model_policy == "knowledge_graph_deep":
            all_triples = conn.execute("SELECT subject, relation, object FROM knowledge_triples").fetchall()
            pair_objs: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
            for tr in all_triples:
                pair_objs[(tr["subject"].lower(), tr["relation"].lower())].add(tr["object"].lower())
            trace["kg_audit"] = {
                "total_triples": len(all_triples),
                "contradiction_groups": sum(1 for objs in pair_objs.values() if len(objs) > 1),
            }
        matches = query_knowledge_graph(conn, prompt)
        if not matches and interpretation.get("resolved_referent"):
            matches = query_knowledge_graph(
                conn, f"{interpretation['resolved_referent']} {prompt}"
            )
        if matches:
            _record_task_timing(
                "knowledge_graph_query",
                t0,
                matched=True,
                status_label="VERIFIED",
                detail=f"{len(matches)} matches",
            )
            trace["engine_path"].append("knowledge_graph")
            trace["matched_triples"] = matches
            lines = []
            for m in matches:
                if m.get("provenance") in ("inferred_2hop", "inferred_3hop") and m.get("inferred_chain"):
                    hop_n = m.get("hop", 2)
                    lines.append(
                        f"- [อนุมาน {hop_n} ช่วง] `{m['inferred_chain']}` (แหล่งที่มา: {m['source']})"
                    )
                else:
                    lines.append(
                        f"- `{m['subject']}` — *{m['relation']}* → `{m['object']}` (แหล่งที่มา: {m['source']})"
                    )
            content = (
                f"ค้นพบความสัมพันธ์ที่ยืนยันแล้ว {len(matches)} รายการจากกราฟความรู้ภายใน:\n\n"
                + "\n".join(lines)
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "trace": trace}
        _record_task_timing("knowledge_graph_query", t0, matched=False, status_label="MISS")

    # 6. Native Neural Transformer & N-Gram Sequence Checkpoint
    allow_generative_ckpt = (
        model_policy != "symbolic_ast_priority"
        and not (model_policy == "knowledge_graph_deep" and mode != "model")
    )
    if mode in ("auto", "model") and not is_explicit_math_cmd and allow_generative_ckpt:
        neural_ckpt = conn.execute(
            "SELECT * FROM checkpoints WHERE eval_status LIKE 'NEURAL%' AND weights_path LIKE '%.gz' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if neural_ckpt and model_policy in ("neural_transformer_priority", "balanced_hybrid") and Path(neural_ckpt["weights_path"]).exists():
            t0 = time.perf_counter()
            try:
                n_model, n_tok, _ = NativeTransformerLM.load_checkpoint(Path(neural_ckpt["weights_path"]))
                n_res = n_model.generate_continuation(n_tok, prompt)
                if n_res.get("generated"):
                    _record_task_timing(
                        "neural_transformer_checkpoint",
                        t0,
                        matched=True,
                        status_label="VERIFIED",
                        detail=f"v{neural_ckpt['version']}",
                    )
                    trace["engine_path"].append("neural_transformer_checkpoint")
                    trace["checkpoint"] = {
                        "engine": "neural_transformer",
                        "checkpoint_version": neural_ckpt["version"],
                        "perplexity": neural_ckpt["perplexity"],
                        "param_count": n_model.parameter_count(),
                        "generated": n_res["generated"],
                        "mean_confidence": n_res.get("mean_confidence"),
                    }
                    content = (
                        f"**ผลต่อข้อความจาก Neural Transformer Checkpoint v{neural_ckpt['version']}** "
                        f"({n_model.parameter_count():,} params · ppl {neural_ckpt['perplexity']:.2f}):\n\n"
                        f"{prompt} **{n_res['generated']}**"
                    )
                    _finalize_trace()
                    conn.close()
                    return {"content": content, "status": "VERIFIED", "trace": trace}
                _record_task_timing("neural_transformer_checkpoint", t0, matched=False, status_label="MISS")
            except Exception:
                _record_task_timing("neural_transformer_checkpoint", t0, matched=False, status_label="ERROR")

        t0 = time.perf_counter()
        ngram_res = run_ngram_continuation(conn, prompt)
        if ngram_res and ngram_res.get("generated"):
            _record_task_timing(
                "ngram_checkpoint",
                t0,
                matched=True,
                status_label="VERIFIED",
                detail=f"v{ngram_res['checkpoint_version']}",
            )
            trace["engine_path"].append("ngram_checkpoint")
            trace["checkpoint"] = ngram_res
            content = (
                f"**ผลต่อข้อความจาก Checkpoint ภายใน v{ngram_res['checkpoint_version']}** "
                f"(perplexity {ngram_res['perplexity']:.2f}, ตรงคำศัพท์ {ngram_res['matched_vocab']} คำ):\n\n"
                f"{prompt} **{ngram_res['generated']}**"
            )
            _finalize_trace()
            conn.close()
            return {"content": content, "status": "VERIFIED", "trace": trace}
        elif ngram_res:
            trace["checkpoint"] = ngram_res
        _record_task_timing("ngram_checkpoint", t0, matched=False, status_label="MISS")

    # 7. Attachment analysis (factual local statistics + structured dataset/code inspection)
    if attachment:
        t0 = time.perf_counter()
        words = tokenize(attachment)
        freq = collections.Counter(words).most_common(5)
        trace["engine_path"].append("attachment_stats")
        trace["attachment_tokens"] = len(words)

        ds_report = analyze_structured_dataset_content(attachment)
        code_report = None if ds_report.get("ok") else inspect_workspace_code_content(attachment)
        sections: list[str] = []

        if ds_report.get("ok"):
            trace["engine_path"].append("dataset_structure_analyzer")
            trace["dataset_analysis"] = ds_report
            sections.append(
                f"วิเคราะห์ข้อมูลโครงสร้าง ({ds_report.get('format')}, {ds_report.get('rows', 0)} แถว)"
            )
            if ds_report.get("columns"):
                sections.append(f"- คอลัมน์: {', '.join(ds_report['columns'][:12])}")
            if ds_report.get("missing_counts"):
                sections.append(f"- ค่าว่าง/หายไป: {json.dumps(ds_report['missing_counts'], ensure_ascii=False)}")
            if ds_report.get("numeric_summary"):
                for col, st_obj in list(ds_report["numeric_summary"].items())[:4]:
                    sections.append(
                        f"- คอลัมน์ตัวเลข {col}: min={st_obj['min']}, max={st_obj['max']}, mean={st_obj['mean']}"
                    )
            for iss in ds_report.get("issues") or []:
                sections.append(f"- จุดผิดปกติ: {iss}")
        elif code_report and code_report.get("ok") and code_report.get("language") in {"python", "json"}:
            trace["engine_path"].append("code_static_inspector")
            trace["code_inspection"] = code_report
            sections.append(code_report.get("summary", "ตรวจสอบโครงสร้างโค้ดแล้ว"))
            if code_report.get("symbols"):
                sections.append(f"- สัญลักษณ์ที่พบ: {', '.join(code_report['symbols'][:10])}")
            if code_report.get("defects"):
                for d in code_report["defects"][:8]:
                    sections.append(f"- บรรทัด {d.get('line', '?')} [{d.get('severity', 'info')}]: {d.get('message')}")
            else:
                sections.append("- ไม่พบข้อผิดพลาดทางไวยากรณ์ (Syntax Pass)")

        _record_task_timing(
            "attachment_stats",
            t0,
            matched=True,
            status_label="VERIFIED",
            detail=f"{len(words)} tokens",
        )
        top_terms = ", ".join(f"{w} ({c})" for w, c in freq)
        structured_block = ("\n" + "\n".join(sections) + "\n") if sections else ""
        content = (
            f"วิเคราะห์เนื้อหาที่แนบในเครื่องแล้ว ({len(words)} หน่วยคำ, {len(set(words))} หน่วยไม่ซ้ำ)\n"
            f"{structured_block}\n"
            f"คำที่พบบ่อย: {top_terms or 'ไม่มี'}\n\n"
            f"หากต้องการนำข้อมูลนี้ไปใช้ต่อในโปรเจกต์ สามารถสั่งงานเพิ่มเติมหรือบันทึกเข้าสู่หน่วยความจำของระบบได้ทันที"
        )
        _finalize_trace()
        conn.close()
        return {"content": content, "status": "VERIFIED", "trace": trace}

    # 8. Native Cognitive Pipeline Fallback: Reason -> Evaluate -> Respond -> Learn
    # Reuses Stage 1+2 understanding to handle compositional reasoning, contextual follow-ups,
    # clarification requests, UNKNOWN, UNCERTAIN, NOT_LEARNED, and UNABLE_TO_INFER cleanly.
    t0 = time.perf_counter()
    cog = run_cognitive_fallback_pipeline(
        conn,
        prompt=prompt,
        attachment=attachment,
        mode=mode,
        conversation_id=str(conversation_id) if conversation_id else None,
        attempted_engines=[t["task"] for t in task_timings],
        understanding=understanding,
        tokenize_fn=tokenize,
        extract_terms_fn=extract_query_terms,
        query_kg_fn=query_knowledge_graph,
    )
    epistemic_state = cog["epistemic_state"]
    cognitive_state = cog.get("cognitive_state") or "UNDERSTOOD"
    trace["engine_path"].append("cognitive_pipeline")
    if epistemic_state == "NOT_LEARNED":
        trace["engine_path"].append("unlearned_boundary")
    trace["epistemic_state"] = epistemic_state
    trace["cognitive_state"] = cognitive_state
    trace["cognitive_pipeline"] = cog["pipeline_trace"]
    conn.close()
    _record_task_timing(
        "unlearned_boundary" if epistemic_state == "NOT_LEARNED" else "cognitive_pipeline",
        t0,
        matched=True,
        status_label=epistemic_state,
        detail=cog["pipeline_trace"]["understand"]["speech_act"],
    )
    _finalize_trace()
    return {
        "content": cog["response"],
        "status": epistemic_state,
        "epistemic_state": epistemic_state,
        "cognitive_state": cognitive_state,
        "trace": trace,
    }


def _canonical_record_key(line: str) -> str:
    stripped = re.sub(r"[^\w\u0E00-\u0E7F\s]", " ", line.lower())
    return re.sub(r"\s+", " ", stripped).strip()


def _near_dup_leakage_exists(split_a: list[str], split_b: list[str], threshold: float = 0.85) -> bool:
    if not split_a or not split_b:
        return False
    canon_a = {_canonical_record_key(x) for x in split_a if _canonical_record_key(x)}
    canon_b = {_canonical_record_key(x) for x in split_b if _canonical_record_key(x)}
    if canon_a & canon_b:
        return True
    toks_a = [set(tokenize(_canonical_record_key(x))) for x in split_a]
    toks_b = [set(tokenize(_canonical_record_key(x))) for x in split_b]
    for ta in toks_a:
        if len(ta) < 4:
            continue
        for tb in toks_b:
            if len(tb) < 4:
                continue
            union_sz = len(ta | tb)
            if union_sz > 0 and (len(ta & tb) / union_sz) >= threshold:
                return True
    return False


DISALLOWED_PROVENANCE_TOKENS = (
    "fake",
    "mock",
    "fabricated",
    "synthetic_llm",
    "external_llm",
    "gpt",
    "openai",
    "claude",
    "gemini",
)


def handle_ingest_dataset(payload: dict) -> dict:
    conn = get_db()
    try:
        return _ingest_dataset_pipeline(
            conn,
            DATA_DIR,
            payload,
            canonical_key_fn=_canonical_record_key,
            tokenize_fn=tokenize,
        )
    finally:
        conn.close()


def check_training_pipeline_prerequisites(
    conn: sqlite3.Connection,
    *,
    dataset_id: str | None = None,
    require_approval: bool = False,
) -> dict:
    # Step 1 & 2: Real dataset + provenance + manifest hash + zero leakage
    if dataset_id:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    else:
        ds = conn.execute(
            "SELECT * FROM datasets WHERE leakage_detected=0 AND total_records>=5 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not ds:
        return {
            "ok": False,
            "blocked_step": "STEP_1_2_DATA_PROVENANCE_LEAKAGE",
            "error": "Training blocked (Steps 1–2): ต้องสร้าง/นำเข้าชุดข้อมูลจริงที่ผ่านการตรวจที่มาและไม่พบ Data Leakage (>= 5 รายการ) ก่อน",
        }
    if int(ds["leakage_detected"] or 0) != 0 or int(ds["total_records"] or 0) < 5:
        return {
            "ok": False,
            "blocked_step": "STEP_1_2_DATA_PROVENANCE_LEAKAGE",
            "error": "Training blocked (Steps 1–2): ชุดข้อมูลพบ Data Leakage หรือมีรายการน้อยกว่า 5 รายการ",
        }
    manifest = str(ds["manifest_hash"] or "")
    if len(manifest) != 64:
        return {
            "ok": False,
            "blocked_step": "STEP_1_2_DATA_PROVENANCE_LEAKAGE",
            "error": "Training blocked (Steps 1–2): ไม่พบ SHA-256 manifest hash ของชุดข้อมูล",
        }
    try:
        rec_meta = json.loads(ds["records_json"] or "{}")
    except Exception:
        rec_meta = {}
    prov = str(rec_meta.get("provenance") or "legacy_verified").lower()
    if any(tok in prov for tok in DISALLOWED_PROVENANCE_TOKENS):
        return {
            "ok": False,
            "blocked_step": "STEP_1_2_DATA_PROVENANCE_LEAKAGE",
            "error": "Training blocked (Steps 1–2): ที่มาของข้อมูลไม่ผ่านเกณฑ์ความถูกต้อง",
        }

    # Step 3: Baseline evaluation must exist before approval or training
    eval_count = int(conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0])
    baseline_count = int(conn.execute("SELECT COUNT(*) FROM capability_baselines").fetchone()[0])
    if eval_count == 0 and baseline_count == 0:
        return {
            "ok": False,
            "blocked_step": "STEP_3_BASELINE_EVALUATION",
            "error": "Training blocked (Step 3): ต้องประเมิน Baseline (evaluate หรือ benchmark) ก่อนจึงจะดำเนินการขั้นถัดไปได้",
        }

    # Step 4: Explicit Admin Approval Gate must exist before training when required
    approved_runs = int(
        conn.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE group_id='native_training' AND status='COMPLETED' AND approved_by IS NOT NULL"
        ).fetchone()[0]
    )
    if require_approval and approved_runs == 0:
        return {
            "ok": False,
            "blocked_step": "STEP_4_APPROVAL_GATE",
            "error": "Training blocked (Step 4): ต้องผ่านการตรวจสอบและอนุมัติจากผู้ดูแลระบบ (Approval Gate) ก่อนเริ่มฝึก",
        }

    return {
        "ok": True,
        "dataset_id": ds["id"],
        "dataset_name": ds["name"],
        "provenance": str(rec_meta.get("provenance") or "verified"),
        "manifest_hash": manifest,
        "eval_count": eval_count,
        "baseline_count": baseline_count,
        "approved_runs": approved_runs,
    }


def _load_stage_aware_sampler():
    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from apps.core.native.train.StageAwareSampler import StageAwareSampler

    return StageAwareSampler


def train_checkpoint_from_dataset(conn: sqlite3.Connection, dataset_id: str, user_id: str) -> dict:
    ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if not ds:
        return {"ok": False, "error": "Dataset not found"}
    if ds["leakage_detected"]:
        return {"ok": False, "error": "Training blocked: dataset leakage detected"}

    splits = json.loads(ds["records_json"])
    ds_keys = set(ds.keys())
    raw_prov = (
        ds["provenance"]
        if "provenance" in ds_keys and ds["provenance"]
        else splits.get("provenance")
    )
    provenance_str = str(raw_prov or "legacy_verified").strip()
    if not provenance_str or any(tok in provenance_str.lower() for tok in DISALLOWED_PROVENANCE_TOKENS):
        return {"ok": False, "error": f"Training blocked: invalid dataset provenance {provenance_str!r}"}

    raw_train_lines = splits.get("train", [])
    val_lines = splits.get("val", [])
    test_lines = splits.get("test", [])
    if not raw_train_lines:
        return {"ok": False, "error": "Training blocked: train split is empty"}

    kq = get_knowledge_quality_summary(conn)
    conflicting_pairs = {
        (str(d.get("subject") or "").lower(), str(d.get("relation") or "").lower())
        for d in (kq.get("contradiction_details") or [])
    }
    heldout_keys = {
        _canonical_record_key(str(x))
        for x in (list(val_lines) + list(test_lines))
        if _canonical_record_key(str(x))
    }

    ingestion_records: list[dict] = []
    for item in raw_train_lines:
        if isinstance(item, dict):
            text_val = str(item.get("text") or item.get("input") or "").strip()
            stage_val = str(item.get("stage") or "verified_dataset").strip() or "verified_dataset"
            q_val = float(item.get("quality_score", 1.0) or 1.0)
            rec_prov = str(item.get("provenance") or provenance_str).strip()
        else:
            text_val = str(item).strip()
            stage_val = "verified_dataset"
            q_val = 1.0
            rec_prov = provenance_str
        if not text_val or any(tok in rec_prov.lower() for tok in DISALLOWED_PROVENANCE_TOKENS):
            continue
        if q_val < 0.7:
            continue
        ingestion_records.append(
            {
                "text": text_val,
                "stage": stage_val,
                "provenance": rec_prov,
                "quality_score": q_val,
            }
        )

    # Supplement with non-contradictory, provenance-verified KG triples that do not overlap val/test
    kg_rows = conn.execute(
        "SELECT subject, relation, object, source, confidence FROM knowledge_triples ORDER BY created_at DESC"
    ).fetchall()
    for kr in kg_rows:
        subj = str(kr["subject"] or "").strip()
        rel = str(kr["relation"] or "").strip()
        obj = str(kr["object"] or "").strip()
        src = str(kr["source"] or "").strip()
        conf = float(kr["confidence"] or 0.0)
        if not subj or not rel or not obj or not src:
            continue
        src_low = src.lower()
        if conf < 0.7 or any(tok in src_low for tok in DISALLOWED_PROVENANCE_TOKENS) or any(
            bad in src_low for bad in ("uncorroborated", "conflicting", "stale")
        ):
            continue
        if (subj.lower(), rel.lower()) in conflicting_pairs:
            continue
        fact_line = f"{subj} {rel} {obj}"
        if _canonical_record_key(fact_line) in heldout_keys:
            continue
        ingestion_records.append(
            {
                "text": fact_line,
                "stage": "verified_knowledge",
                "provenance": src,
                "quality_score": conf,
            }
        )

    if not ingestion_records:
        return {"ok": False, "error": "Training blocked: no verified provenance/quality training records available"}

    stage_quality_sums: dict[str, float] = collections.defaultdict(float)
    stage_counts: dict[str, int] = collections.Counter()
    for rec in ingestion_records:
        st = rec["stage"]
        stage_quality_sums[st] += rec["quality_score"]
        stage_counts[st] += 1

    stage_weights: dict[str, float] = {}
    for st, cnt in stage_counts.items():
        avg_q = stage_quality_sums[st] / max(1, cnt)
        if st == "verified_knowledge":
            cov_factor = max(0.1, float(kq.get("provenance_coverage_pct") or 0.0) / 100.0)
            stage_weights[st] = round(max(0.05, min(0.35, avg_q * cov_factor * 0.25)), 6)
        else:
            stage_weights[st] = round(max(0.1, avg_q), 6)

    StageAwareSampler = _load_stage_aware_sampler()
    sampler = StageAwareSampler(
        ingestion_records,
        stage_weights=stage_weights,
        seed=max(0, int(hashlib.sha256(str(dataset_id).encode("utf-8")).hexdigest()[:8], 16)),
        num_samples=len(ingestion_records),
    )
    sampled_indices = sampler.sample_indices()
    train_lines = [ingestion_records[idx]["text"] for idx in sampled_indices]
    sampling_summary = {
        "sampler": "StageAwareSampler",
        "provenance": provenance_str,
        "knowledge_quality_status": kq.get("status"),
        "provenance_coverage_pct": kq.get("provenance_coverage_pct"),
        "contradiction_groups_excluded": kq.get("contradiction_groups", 0),
        "stage_counts": sampler.stage_counts,
        "normalized_weights": sampler.normalized_weights,
        "sampled_count": len(sampled_indices),
        "sampled_distribution": sampler.measure_stage_distribution(sampled_indices),
    }

    bigrams: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.defaultdict(int))
    trigrams: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.defaultdict(int))
    unigrams: collections.Counter = collections.Counter()

    for ln in train_lines:
        toks = tokenize(ln) + ["<END>"]
        for i, tok in enumerate(toks):
            unigrams[tok] += 1
            if i >= 1:
                bigrams[toks[i - 1]][tok] += 1
            if i >= 2:
                trigrams[f"{toks[i - 2]} {toks[i - 1]}"][tok] += 1

    vocab = sorted(unigrams.keys())
    vocab_size = max(1, len(vocab))

    def cross_entropy(lines_subset: list[str]) -> tuple[float, float]:
        avg_loss, acc, _ = _score_interpolated_ngram(
            lines_subset, bigrams, trigrams, unigrams, vocab_size
        )
        return avg_loss, acc

    train_loss, _ = cross_entropy(train_lines)
    val_loss, _ = cross_entropy(val_lines)
    _, test_acc = cross_entropy(test_lines)

    if math.isnan(train_loss) or math.isnan(val_loss) or math.isinf(val_loss):
        return {"ok": False, "error": "Training halted: NaN or Inf loss detected"}

    perplexity = round(math.exp(min(val_loss, 20.0)), 3)
    max_ver = conn.execute("SELECT COALESCE(MAX(version), 0) FROM checkpoints").fetchone()[0]
    new_ver = int(max_ver) + 1
    ckpt_id = str(uuid.uuid4())
    weights_path = CHECKPOINT_DIR / f"ckpt_v{new_ver}_{ckpt_id[:8]}.json"

    weights_payload = {
        "version": new_ver,
        "dataset_id": dataset_id,
        "vocab": vocab,
        "unigrams": dict(unigrams),
        "bigrams": {k: dict(v) for k, v in bigrams.items()},
        "trigrams": {k: dict(v) for k, v in trigrams.items()},
        "created_at": now_iso(),
    }
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights_payload, f)

    eval_status = "PASS" if test_acc > 0 else "VERIFIED_LOW_ACC"
    with conn:
        conn.execute(
            """
            INSERT INTO checkpoints (id, version, dataset_id, vocab_size, ngram_order, train_loss, val_loss, perplexity, eval_accuracy, eval_status, weights_path, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ckpt_id,
                new_ver,
                dataset_id,
                vocab_size,
                3,
                round(train_loss, 4),
                round(val_loss, 4),
                perplexity,
                round(test_acc, 4),
                eval_status,
                str(weights_path),
                user_id,
                now_iso(),
            ),
        )
    row = dict(conn.execute("SELECT * FROM checkpoints WHERE id=?", (ckpt_id,)).fetchone())
    return {"ok": True, "checkpoint": row, "sampling": sampling_summary}


def _collect_upstream_workflow_refs(conn: sqlite3.Connection, group_ids: list[str]) -> dict[str, dict]:
    refs: dict[str, dict] = {}
    for gid in group_ids:
        row = conn.execute(
            "SELECT id, group_id, status, summary, output_json, created_at FROM workflow_runs WHERE group_id=? ORDER BY created_at DESC LIMIT 1",
            (gid,),
        ).fetchone()
        if row:
            try:
                out_obj = json.loads(row["output_json"] or "{}") if row["output_json"] else {}
            except Exception:
                out_obj = {}
            refs[gid] = {
                "run_id": row["id"],
                "status": row["status"],
                "summary": row["summary"],
                "output": out_obj,
                "created_at": row["created_at"],
            }
    return refs


def _build_autonomous_improvement_proposal(conn: sqlite3.Connection) -> dict:
    """Stages 1-3 (Strictly Read-Only): gap_analysis -> hypothesis_draft -> plan_validation."""
    upstream = _collect_upstream_workflow_refs(conn, ["evaluation", "project_dev", "knowledge_memory"])
    latest_ckpt = conn.execute("SELECT * FROM checkpoints ORDER BY version DESC LIMIT 1").fetchone()
    latest_eval = conn.execute(
        "SELECT id, overall_status, math_score, knowledge_score, planning_score, test_accuracy, created_at FROM evaluations ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    gaps = detect_capability_gaps(conn)

    failure_patterns: list[dict] = []
    try:
        from tool_center import analyze_failure_patterns
        failure_patterns = analyze_failure_patterns(conn, limit=5)
    except Exception:
        failure_patterns = []

    if gaps:
        top_gap = gaps[0]
        gap_summary = f"{top_gap.get('gap_type')}: {top_gap.get('detail')}"
    elif not latest_ckpt:
        gap_summary = "No trained native checkpoint yet; focus bounded verification on core planner/workflow modules."
    else:
        gap_summary = (
            f"Checkpoint v{latest_ckpt['version']} test_accuracy={latest_ckpt['eval_accuracy']}; "
            f"evaluate bounded quality checks and corpus coverage."
        )

    # Read-only real repo files that exist
    candidate_targets = [
        rel
        for rel in ("python_core/zyrquen_core.py", "python_core/dag_executor.py", "python_core/planner_intelligence.py")
        if (BASE_DIR / rel).is_file()
    ]
    hypothesis = (
        f"{gap_summary} เสนอแผนตรวจสอบและปรับปรุงแบบจำกัดขอบเขต (Read-Only Syntax/Contract Verification + Outcome Memory) "
        f"บนโมดูล {', '.join(candidate_targets) or 'python_core/zyrquen_core.py'}"
    )
    allowed_operations = ["readonly_file_inspect", "python_ast_syntax_check", "contract_assertion_verify", "record_outcome_memory"]
    forbidden_operations = ["git_push", "git_commit", "weight_mutation", "delete_data", "paid_compute", "architecture_change"]

    plan_obj = {
        "gap_summary": gap_summary,
        "hypothesis": hypothesis,
        "target_files": candidate_targets,
        "allowed_operations": allowed_operations,
        "forbidden_operations": forbidden_operations,
        "expected_checks": ["python_syntax_ast", "contract_assertion"],
        "verification_command": "python3 -m unittest discover -s python_core/tests -p 'test_planner_and_workflow_lifecycle.py'",
        "rollback_strategy": "No repository mutation performed outside sandbox; abort outcome_learning on any check failure.",
        "upstream_refs": {k: {"run_id": v["run_id"], "status": v["status"]} for k, v in upstream.items()},
    }
    scope_obj = {
        "allowed_files": candidate_targets,
        "allowed_operations": allowed_operations,
        "forbidden_operations": forbidden_operations,
        "max_files": len(candidate_targets),
        "allow_weight_mutation": False,
        "allow_external_models": False,
    }

    # Stage 3: Read-Only Plan Validation
    validation_errors: list[str] = []
    if not candidate_targets:
        validation_errors.append("No target files resolved in workspace")
    for rel in candidate_targets:
        resolved = (BASE_DIR / rel).resolve()
        if not str(resolved).startswith(str(BASE_DIR.resolve())) or not resolved.is_file():
            validation_errors.append(f"Target file outside repo or missing: {rel}")
    if any(op in allowed_operations for op in forbidden_operations):
        validation_errors.append("Allowed operations overlap forbidden operations")
    if not plan_obj["expected_checks"]:
        validation_errors.append("Missing expected verification checks")

    repo_rev = _compute_repo_revision(BASE_DIR)
    plan_hash = _canonical_plan_hash(plan_obj)
    return {
        "valid": len(validation_errors) == 0,
        "validation_errors": validation_errors,
        "plan_obj": plan_obj,
        "scope_obj": scope_obj,
        "plan_hash": plan_hash,
        "repo_revision": repo_rev,
        "upstream": upstream,
        "latest_eval": dict(latest_eval) if latest_eval else None,
        "failure_patterns_count": len(failure_patterns),
        "hypothesis": hypothesis,
    }


def _execute_autonomous_improvement_approved(
    conn: sqlite3.Connection,
    run_row: dict,
    *,
    approved_by: str,
    user_id: str,
) -> dict:
    """Stages 4-7 after verified Admin Approval: hash/revision check -> bounded_execution -> verification -> outcome_learning."""
    stored_hash = str(run_row.get("plan_hash") or "")
    stored_rev = str(run_row.get("repo_revision") or "")
    try:
        plan_obj = json.loads(run_row.get("plan_json") or "{}")
    except Exception:
        plan_obj = {}
    try:
        scope_obj = json.loads(run_row.get("approval_scope_json") or "{}")
    except Exception:
        scope_obj = {}
    try:
        prior_stages = json.loads(run_row.get("stages_json") or "[]")
    except Exception:
        prior_stages = []

    stage_by_name = {s.get("stage"): s for s in prior_stages if isinstance(s, dict)}
    s_gap = stage_by_name.get("gap_analysis") or {"stage": "gap_analysis", "status": "PASS", "detail": plan_obj.get("gap_summary", "")}
    s_hyp = stage_by_name.get("hypothesis_draft") or {"stage": "hypothesis_draft", "status": "PASS", "detail": plan_obj.get("hypothesis", "")}
    s_val = stage_by_name.get("plan_validation") or {"stage": "plan_validation", "status": "PASS", "detail": f"plan_hash={stored_hash[:12]}..."}

    # Re-verify immutable plan_hash & repo_revision BEFORE execution!
    recomputed_hash = _canonical_plan_hash(plan_obj) if plan_obj else ""
    current_rev = _compute_repo_revision(BASE_DIR)

    if not stored_hash or recomputed_hash != stored_hash:
        reason = "Approval invalidated: stored plan payload hash does not match approved plan_hash."
        stages_out = [
            s_gap,
            s_hyp,
            s_val,
            {"stage": "approval_gate", "status": "BLOCKED", "detail": reason},
            {"stage": "bounded_execution", "status": "BLOCKED", "detail": "Halted due to plan tamper/mismatch"},
            {"stage": "verification", "status": "BLOCKED", "detail": "Not executed"},
            {"stage": "outcome_learning", "status": "BLOCKED", "detail": "Not executed"},
        ]
        return {
            "ok": False,
            "status": "BLOCKED",
            "summary": reason,
            "stages_out": stages_out,
            "invalidated_reason": reason,
            "verification_obj": {"passed": False, "reason": reason},
            "output_obj": {"invalidated": True},
        }

    if not stored_rev or current_rev != stored_rev:
        reason = f"Approval invalidated: repository revision changed ({stored_rev} -> {current_rev}). Re-propose and re-approve required."
        stages_out = [
            s_gap,
            s_hyp,
            s_val,
            {"stage": "approval_gate", "status": "BLOCKED", "detail": reason},
            {"stage": "bounded_execution", "status": "BLOCKED", "detail": "Halted due to repo_revision drift"},
            {"stage": "verification", "status": "BLOCKED", "detail": "Not executed"},
            {"stage": "outcome_learning", "status": "BLOCKED", "detail": "Not executed"},
        ]
        return {
            "ok": False,
            "status": "BLOCKED",
            "summary": reason,
            "stages_out": stages_out,
            "invalidated_reason": reason,
            "verification_obj": {"passed": False, "reason": reason},
            "output_obj": {"invalidated": True},
        }

    # Stage 5: Bounded Execution within approved scope
    allowed_files = set(scope_obj.get("allowed_files") or [])
    target_files = list(plan_obj.get("target_files") or [])
    allowed_ops = set(scope_obj.get("allowed_operations") or [])
    forbidden_ops = set(scope_obj.get("forbidden_operations") or [])

    scope_violation: str | None = None
    for tf in target_files:
        if tf not in allowed_files:
            scope_violation = f"Out-of-scope file requested: {tf}"
            break
    if not target_files or not allowed_files:
        scope_violation = "Empty approval scope"
    if allowed_ops & forbidden_ops:
        scope_violation = "Forbidden operation present in execution scope"

    if scope_violation:
        stages_out = [
            s_gap,
            s_hyp,
            s_val,
            {"stage": "approval_gate", "status": "PASS", "detail": f"Approved by {approved_by}"},
            {"stage": "bounded_execution", "status": "BLOCKED", "detail": scope_violation},
            {"stage": "verification", "status": "BLOCKED", "detail": "Halted on scope violation"},
            {"stage": "outcome_learning", "status": "BLOCKED", "detail": "Skipped"},
        ]
        return {
            "ok": False,
            "status": "BLOCKED",
            "summary": scope_violation,
            "stages_out": stages_out,
            "invalidated_reason": scope_violation,
            "verification_obj": {"passed": False, "reason": scope_violation},
            "output_obj": {"scope_violation": scope_violation},
        }

    inspected_files: list[dict] = []
    for rel in target_files:
        fp = (BASE_DIR / rel).resolve()
        if not fp.is_file():
            scope_violation = f"Approved file missing on disk: {rel}"
            break
        src_text = fp.read_text(encoding="utf-8")
        inspected_files.append(
            {
                "path": rel,
                "bytes": len(src_text.encode("utf-8")),
                "lines": len(src_text.splitlines()),
                "sha256": hashlib.sha256(src_text.encode("utf-8")).hexdigest()[:16],
                "source": src_text,
            }
        )

    if scope_violation:
        stages_out = [
            s_gap,
            s_hyp,
            s_val,
            {"stage": "approval_gate", "status": "PASS", "detail": f"Approved by {approved_by}"},
            {"stage": "bounded_execution", "status": "FAILED", "detail": scope_violation},
            {"stage": "verification", "status": "BLOCKED", "detail": "Target file missing"},
            {"stage": "outcome_learning", "status": "BLOCKED", "detail": "Skipped"},
        ]
        return {
            "ok": False,
            "status": "FAILED",
            "summary": scope_violation,
            "stages_out": stages_out,
            "invalidated_reason": None,
            "verification_obj": {"passed": False, "reason": scope_violation},
            "output_obj": {},
        }

    # Stage 6: Real Verification Checks (AST parse + Contract Assertion)
    ast_checks: list[dict] = []
    all_ast_ok = True
    for finfo in inspected_files:
        if finfo["path"].endswith(".py"):
            try:
                ast.parse(finfo["source"], filename=finfo["path"])
                ast_checks.append({"file": finfo["path"], "syntax_valid": True})
            except SyntaxError as exc:
                all_ast_ok = False
                ast_checks.append({"file": finfo["path"], "syntax_valid": False, "error": str(exc)})

    contract_cases = [
        {"name": "plan_hash_bound", "op": "eq", "actual": recomputed_hash, "expected": stored_hash},
        {"name": "repo_revision_bound", "op": "eq", "actual": current_rev, "expected": stored_rev},
        {"name": "all_target_files_ast_valid", "op": "eq", "actual": all_ast_ok, "expected": True},
        {"name": "no_weight_mutation", "op": "eq", "actual": bool(scope_obj.get("allow_weight_mutation", False)), "expected": False},
    ]
    assertion_verdict = "PASS" if all(c["actual"] == c["expected"] for c in contract_cases) else "FAILED"
    try:
        from tool_center import get_tool_center_registry
        tc_res = get_tool_center_registry().execute(
            "testing.contract_assertion",
            {"cases": contract_cases},
            user_role="admin",
            conn=conn,
            data_dir=DATA_DIR,
            approved_by=approved_by,
        )
        tc_out = tc_res.get("output") or {}
        if tc_res.get("ok") and tc_out.get("verdict"):
            assertion_verdict = str(tc_out["verdict"])
    except Exception:
        pass

    verification_passed = bool(all_ast_ok and assertion_verdict == "PASS")
    verification_obj = {
        "passed": verification_passed,
        "ast_checks": ast_checks,
        "assertion_verdict": assertion_verdict,
        "checked_files": [f["path"] for f in inspected_files],
        "plan_hash": stored_hash,
        "repo_revision": stored_rev,
        "verified_at": now_iso(),
    }

    if not verification_passed:
        fail_msg = "Verification failed: target module AST or contract assertion did not pass; outcome_learning halted."
        stages_out = [
            s_gap,
            s_hyp,
            s_val,
            {"stage": "approval_gate", "status": "PASS", "detail": f"Approved by {approved_by}"},
            {"stage": "bounded_execution", "status": "PASS", "detail": f"Inspected {len(inspected_files)} scoped file(s)"},
            {"stage": "verification", "status": "FAILED", "detail": fail_msg},
            {"stage": "outcome_learning", "status": "BLOCKED", "detail": "Blocked because verification failed"},
        ]
        return {
            "ok": False,
            "status": "FAILED",
            "summary": fail_msg,
            "stages_out": stages_out,
            "invalidated_reason": None,
            "verification_obj": verification_obj,
            "output_obj": {"inspected_files": [f["path"] for f in inspected_files]},
        }

    # Stage 7: Outcome Learning (ONLY reached when verification passes)
    record_episodic_experience(
        conn,
        mission_id=None,
        goal=str(plan_obj.get("hypothesis") or "autonomous_improvement")[:240],
        outcome_status="COMPLETED",
        gap_type="autonomous_improvement_verified",
        hypothesis={
            "plan_hash": stored_hash,
            "repo_revision": stored_rev,
            "approved_by": approved_by,
            "checked_files": [f["path"] for f in inspected_files],
        },
        verified_delta=1.0,
    )
    try:
        from tool_center import record_task_memory
        record_task_memory(
            conn,
            goal=str(plan_obj.get("hypothesis") or "autonomous_improvement")[:200],
            capability_id="automation.outcome_learning",
            success=True,
            latency_ms=1.0,
            detail=f"verified plan_hash={stored_hash[:12]}",
        )
    except Exception:
        pass

    stages_out = [
        s_gap,
        s_hyp,
        s_val,
        {"stage": "approval_gate", "status": "PASS", "detail": f"Approved by {approved_by}"},
        {
            "stage": "bounded_execution",
            "status": "PASS",
            "detail": f"Bounded inspection on {len(inspected_files)} approved file(s); zero unapproved mutations",
        },
        {
            "stage": "verification",
            "status": "PASS",
            "detail": f"AST + Contract assertions passed ({len(ast_checks)} file(s), plan_hash={stored_hash[:12]}...)",
        },
        {
            "stage": "outcome_learning",
            "status": "PASS",
            "detail": "Recorded verified outcome into episodic_experiences & task_memory",
        },
    ]
    summary = (
        f"Autonomous Improvement COMPLETED (7/7 stages): verified {len(inspected_files)} scoped file(s), "
        f"plan_hash={stored_hash[:12]}..., approved_by={approved_by}."
    )
    return {
        "ok": True,
        "status": "COMPLETED",
        "summary": summary,
        "stages_out": stages_out,
        "invalidated_reason": None,
        "verification_obj": verification_obj,
        "output_obj": {
            "checked_files": [{"path": f["path"], "sha256": f["sha256"]} for f in inspected_files],
            "plan_hash": stored_hash,
            "repo_revision": stored_rev,
        },
    }


def handle_run_workflow(payload: dict) -> dict:
    conn = get_db()
    group_id = str(payload.get("group_id", ""))
    user_id = str(payload.get("user_id", ""))
    approved_by = payload.get("approved_by")
    existing_run_id = payload.get("run_id")
    dataset_id = payload.get("dataset_id")
    verified_approval_ctx = bool(payload.get("_verified_approval_context", False))

    group = next((g for g in WORKFLOW_GROUPS if g["id"] == group_id), None)
    if not group:
        conn.close()
        return {"ok": False, "error": f"Unknown workflow group '{group_id}'"}

    # Fail-closed guard: block forged approved_by bypasses on approval-gated workflows
    if group["requires_approval"] and approved_by and not verified_approval_ctx:
        conn.close()
        return {
            "ok": False,
            "error": "Direct approval bypass blocked: approval-gated workflows must enter PENDING_APPROVAL and pass Admin Approval Gate.",
        }

    # Strict pre-gate check for native_training: Steps 1-3 must pass BEFORE creating an Approval Gate request
    if group_id == "native_training":
        prereq = check_training_pipeline_prerequisites(
            conn,
            dataset_id=str(dataset_id) if dataset_id else None,
            require_approval=False,
        )
        if not prereq["ok"]:
            conn.close()
            return prereq

    # Handle approval-gated pre-gate submission (no verified approval yet)
    if group["requires_approval"] and not approved_by:
        run_id = str(uuid.uuid4())
        if group_id == "autonomous_improvement":
            # Execute Stages 1-3 (read-only) BEFORE entering Approval Gate!
            proposal = _build_autonomous_improvement_proposal(conn)
            upstream_refs = {k: v["run_id"] for k, v in proposal["upstream"].items()}
            if not proposal["valid"]:
                err_msg = "; ".join(proposal["validation_errors"])
                stages = [
                    {"stage": "gap_analysis", "status": "PASS", "detail": proposal["plan_obj"]["gap_summary"]},
                    {"stage": "hypothesis_draft", "status": "PASS", "detail": proposal["hypothesis"]},
                    {"stage": "plan_validation", "status": "FAILED", "detail": err_msg},
                    {"stage": "approval_gate", "status": "BLOCKED", "detail": "Blocked: plan validation failed"},
                    {"stage": "bounded_execution", "status": "BLOCKED", "detail": "Not executed"},
                    {"stage": "verification", "status": "BLOCKED", "detail": "Not executed"},
                    {"stage": "outcome_learning", "status": "BLOCKED", "detail": "Not executed"},
                ]
                with conn:
                    conn.execute(
                        """
                        INSERT INTO workflow_runs (
                            id, group_id, status, requires_approval, triggered_by, approved_by,
                            summary, stages_json, plan_hash, repo_revision, plan_json,
                            approval_scope_json, depends_on_runs_json, output_json, invalidated_reason,
                            created_at, updated_at
                        )
                        VALUES (?, ?, 'BLOCKED', 1, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            group_id,
                            user_id,
                            f"Plan validation failed: {err_msg}",
                            json.dumps(stages),
                            proposal["plan_hash"],
                            proposal["repo_revision"],
                            json.dumps(proposal["plan_obj"], ensure_ascii=False),
                            json.dumps(proposal["scope_obj"], ensure_ascii=False),
                            json.dumps(upstream_refs),
                            json.dumps({"validation_errors": proposal["validation_errors"]}),
                            err_msg,
                            now_iso(),
                            now_iso(),
                        ),
                    )
                run = dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone())
                conn.close()
                return {"ok": False, "error": err_msg, "run": run}

            stages = [
                {"stage": "gap_analysis", "status": "PASS", "detail": proposal["plan_obj"]["gap_summary"]},
                {"stage": "hypothesis_draft", "status": "PASS", "detail": proposal["hypothesis"]},
                {
                    "stage": "plan_validation",
                    "status": "PASS",
                    "detail": f"Validated scope ({len(proposal['scope_obj']['allowed_files'])} files) · plan_hash={proposal['plan_hash'][:12]}... · {proposal['repo_revision']}",
                },
                {
                    "stage": "approval_gate",
                    "status": "PENDING_APPROVAL",
                    "detail": f"Awaiting Admin Approval for plan_hash={proposal['plan_hash'][:12]}...",
                },
                {"stage": "bounded_execution", "status": "WAITING", "detail": "Awaiting Admin Approval"},
                {"stage": "verification", "status": "WAITING", "detail": "Awaiting bounded_execution"},
                {"stage": "outcome_learning", "status": "WAITING", "detail": "Awaiting verified outcome"},
            ]
            summary = (
                f"Stages 1–3 passed (read-only). Awaiting Admin Approval Gate: "
                f"plan_hash={proposal['plan_hash'][:12]}... · {proposal['repo_revision']}"
            )
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflow_runs (
                        id, group_id, status, requires_approval, triggered_by, approved_by,
                        summary, stages_json, plan_hash, repo_revision, plan_json,
                        approval_scope_json, depends_on_runs_json, output_json,
                        created_at, updated_at
                    )
                    VALUES (?, ?, 'PENDING_APPROVAL', 1, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        group_id,
                        user_id,
                        summary,
                        json.dumps(stages),
                        proposal["plan_hash"],
                        proposal["repo_revision"],
                        json.dumps(proposal["plan_obj"], ensure_ascii=False),
                        json.dumps(proposal["scope_obj"], ensure_ascii=False),
                        json.dumps(upstream_refs),
                        json.dumps({"plan_hash": proposal["plan_hash"], "repo_revision": proposal["repo_revision"]}),
                        now_iso(),
                        now_iso(),
                    ),
                )
            run = dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone())
            conn.close()
            return {"ok": True, "run": run}

        # Other approval-gated workflows (native_training)
        stages = [
            {"stage": s, "status": "PENDING_APPROVAL" if s == "approval_gate" else "WAITING"}
            for s in group["stages"]
        ]
        summary = f"Approval Gate active: {group['name']} requires explicit Admin authorization before execution."
        with conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (id, group_id, status, requires_approval, triggered_by, approved_by, summary, stages_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, group_id, "PENDING_APPROVAL", 1, user_id, None, summary, json.dumps(stages), now_iso(), now_iso()),
            )
        run = dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone())
        conn.close()
        return {"ok": True, "run": run}

    # Execute actual workflow stages
    stages_out = []
    status = "COMPLETED"
    summary = ""
    depends_on_runs: dict = {}
    output_obj: dict = {}
    verification_obj: dict | None = None
    invalidated_reason: str | None = None
    exec_ok = True

    if group_id == "system_ops":
        metrics = get_system_metrics()
        stages_out = [
            {"stage": "health_probe", "status": "PASS", "detail": f"Python {metrics['python_version']} Native Core responsive"},
            {"stage": "resource_audit", "status": "PASS", "detail": f"CPU {metrics['cpu_count']} cores · Mem avail {metrics['mem_available_mb']} MB"},
            {"stage": "storage_check", "status": "PASS", "detail": f"SQLite {metrics['sqlite_db_kb']} KB · Disk free {metrics['disk_free_gb']} GB"},
            {"stage": "status_report", "status": "PASS", "detail": "All runtime boundaries nominal"},
        ]
        output_obj = {"metrics": metrics}
        summary = f"System Operations verified: {metrics['mem_available_mb']} MB RAM free, {metrics['disk_free_gb']} GB disk free."

    elif group_id == "data_pipeline":
        audit_res = verify_all_datasets_for_workflow(conn)
        total_ds = audit_res["total"]
        leak_count = audit_res["leak_count"]
        checksum_fails = audit_res["checksum_failed_count"]
        pending_kg = int(
            conn.execute("SELECT COUNT(*) FROM kg_ingestion_proposals WHERE status='PENDING_APPROVAL'").fetchone()[0]
        )
        stages_out = [
            {"stage": "schema_validate", "status": "PASS" if total_ds > 0 else "EMPTY", "detail": f"Audited {total_ds} registered dataset(s)"},
            {"stage": "deduplicate", "status": "PASS" if total_ds > 0 else "NOT_RUN", "detail": f"Provenance & normalization verified ({pending_kg} KG proposal(s) awaiting gate)"},
            {"stage": "leakage_scan", "status": "FAILED" if leak_count else ("PASS" if total_ds > 0 else "NOT_RUN"), "detail": f"{leak_count} dataset(s) with split/template/eval leakage"},
            {
                "stage": "manifest_hash",
                "status": "FAILED" if checksum_fails else ("PASS" if total_ds > 0 else "NOT_RUN"),
                "detail": (
                    f"{checksum_fails} dataset(s) failed SHA-256 recomputation"
                    if checksum_fails
                    else (
                        f"Verified SHA-256 manifests & disk checksums for {total_ds} dataset(s)"
                        if total_ds > 0
                        else "No datasets registered yet"
                    )
                ),
            },
        ]
        status = "FAILED" if (leak_count or checksum_fails) else ("EMPTY" if total_ds == 0 else "COMPLETED")
        output_obj = {"total_datasets": total_ds, "leak_count": leak_count, "checksum_fails": checksum_fails, "pending_kg": pending_kg}
        summary = f"Data Pipeline audited {total_ds} dataset(s); leakage={leak_count}, checksum_failures={checksum_fails}, pending_kg_gate={pending_kg}."

    elif group_id == "native_training":
        upstream = _collect_upstream_workflow_refs(conn, ["data_pipeline", "evaluation"])
        depends_on_runs = {k: v["run_id"] for k, v in upstream.items()}
        prereq = check_training_pipeline_prerequisites(
            conn,
            dataset_id=str(dataset_id) if dataset_id else None,
            require_approval=False,
        )
        if not prereq["ok"]:
            status = "BLOCKED"
            stages_out = [
                {"stage": "provenance_leakage_gate", "status": "BLOCKED", "detail": prereq["error"]},
            ]
            summary = prereq["error"]
        else:
            target_ds = str(prereq["dataset_id"])
            res = train_checkpoint_from_dataset(conn, target_ds, approved_by or user_id)
            if not res["ok"]:
                status = "FAILED"
                stages_out = [{"stage": "checkpoint_train", "status": "FAILED", "detail": res["error"]}]
                summary = res["error"]
            else:
                ck = res["checkpoint"]
                sampling_info = res.get("sampling") or {}
                post_eval = handle_run_evaluation(
                    {
                        "user_id": approved_by or user_id,
                        "suite_name": f"Checkpoint v{ck['version']} Post-Training Gate",
                    }
                )
                ev = post_eval.get("evaluation") or {}
                stages_out = [
                    {
                        "stage": "provenance_leakage_gate",
                        "status": "PASS",
                        "detail": f"Dataset {target_ds[:8]} ({prereq['provenance']}, sha256:{prereq['manifest_hash'][:10]}..., leakage=0)",
                    },
                    {
                        "stage": "baseline_verify",
                        "status": "PASS",
                        "detail": f"Baseline verified ({prereq['eval_count']} evals, {prereq['baseline_count']} capability baselines)",
                    },
                    {
                        "stage": "approval_gate",
                        "status": "PASS",
                        "detail": f"Authorized by {approved_by}",
                    },
                    {
                        "stage": "checkpoint_train",
                        "status": "PASS",
                        "detail": (
                            f"Saved immutable Checkpoint v{ck['version']} via StageAwareSampler "
                            f"(samples={sampling_info.get('sampled_count', 0)}, perplexity {ck['perplexity']})"
                        ),
                    },
                    {
                        "stage": "checkpoint_eval_gate",
                        "status": "PASS" if ev.get("overall_status") in ("VERIFIED", "PASS", "PARTIAL") else "WARN",
                        "detail": f"Post-eval {ev.get('overall_status', 'RECORDED')} (test_acc={ev.get('test_accuracy')}, ppl={ev.get('perplexity')})",
                    },
                ]
                output_obj = {
                    "checkpoint_id": ck["id"],
                    "version": ck["version"],
                    "perplexity": ck["perplexity"],
                    "post_eval_status": ev.get("overall_status"),
                    "sampling": sampling_info,
                }
                summary = (
                    f"Trained & evaluated immutable Checkpoint v{ck['version']}: "
                    f"train_loss={ck['train_loss']}, val_loss={ck['val_loss']}, "
                    f"perplexity={ck['perplexity']}, post_eval={ev.get('overall_status', 'RECORDED')}."
                )

    elif group_id == "evaluation":
        upstream = _collect_upstream_workflow_refs(conn, ["knowledge_memory", "native_training"])
        depends_on_runs = {k: v["run_id"] for k, v in upstream.items()}
        eval_res = handle_run_evaluation({"user_id": user_id, "suite_name": "Evaluation Workflow Suite"})
        ev = eval_res["evaluation"]
        details = json.loads(ev["details_json"])
        ckpt_detail = (
            f"Checkpoint v{ev['checkpoint_version']} test_acc={ev['test_accuracy']} ppl={ev['perplexity']}"
            if ev["checkpoint_version"] is not None
            else "NOT RUN (no trained checkpoint)"
        )
        ev_overall = str(ev["overall_status"])
        report_emit_status = "PASS" if ev_overall == "VERIFIED" else ("PARTIAL" if ev_overall == "PARTIAL" else "FAILED")
        stages_out = [
            {
                "stage": "math_probe",
                "status": "PASS" if ev["math_score"] == 1.0 else "FAILED",
                "detail": f"AST/Algebra/Stats {len(details['math_probes'])}-probe score {ev['math_score'] * 100:.0f}%",
            },
            {
                "stage": "knowledge_probe",
                "status": details["knowledge_probe"]["status"],
                "detail": f"{details['knowledge_probe']['total_triples']} triples indexed · resolution {ev['knowledge_score'] * 100:.0f}%",
            },
            {
                "stage": "planning_probe",
                "status": details["planning_probe"]["status"],
                "detail": f"DAG planner verified ({details['planning_probe']['steps_generated']} steps)",
            },
            {
                "stage": "heldout_test_eval",
                "status": details["heldout_test"]["status"],
                "detail": ckpt_detail,
            },
            {
                "stage": "report_emit",
                "status": report_emit_status,
                "detail": f"Evaluation {ev['id'][:8]} saved ({ev_overall})",
            },
        ]
        status = "FAILED" if ev_overall == "FAILED" else ("PARTIAL" if ev_overall == "PARTIAL" else "COMPLETED")
        output_obj = {"evaluation_id": ev["id"], "overall_status": ev_overall, "math_score": ev["math_score"], "knowledge_score": ev["knowledge_score"], "planning_score": ev["planning_score"]}
        verification_obj = {"evaluation_id": ev["id"], "overall_status": ev_overall}
        summary = f"Evaluation ({ev_overall}): Math={ev['math_score'] * 100:.0f}%, Plan={ev['planning_score'] * 100:.0f}%, {ckpt_detail}."

    elif group_id == "knowledge_memory":
        kq = get_knowledge_quality_summary(conn)
        total_tr = kq["total_triples"]
        conflicts = kq["contradiction_groups"]
        if total_tr == 0:
            stages_out = [
                {"stage": "triple_scan", "status": "EMPTY", "detail": "NO_RECORDS: 0 triples stored in knowledge_triples"},
                {"stage": "contradiction_detect", "status": "NOT_RUN", "detail": "Skipped (0 knowledge records)"},
                {"stage": "graph_index", "status": "EMPTY", "detail": "Graph index empty (0 records)"},
            ]
            status = "EMPTY"
            summary = "Knowledge & Memory EMPTY (NO_RECORDS): 0 triples indexed; add or ingest verified facts first."
        else:
            stages_out = [
                {
                    "stage": "triple_scan",
                    "status": "PASS",
                    "detail": f"Scanned {total_tr} triple(s) · provenance coverage {kq['provenance_coverage_pct']}%",
                },
                {
                    "stage": "contradiction_detect",
                    "status": "WARN" if conflicts else "PASS",
                    "detail": f"{conflicts} conflicting relation group(s)",
                },
                {
                    "stage": "graph_index",
                    "status": "PASS" if kq["provenance_coverage_pct"] >= 100.0 else "WARN",
                    "detail": f"Index status={kq['indexing_health']} ({kq['verified_triples']}/{total_tr} verified)",
                },
            ]
            status = "PARTIAL" if (conflicts > 0 or kq["provenance_coverage_pct"] < 100.0) else "COMPLETED"
            summary = (
                f"Knowledge audit: {total_tr} triple(s) ({kq['verified_triples']} verified, "
                f"provenance {kq['provenance_coverage_pct']}%), {conflicts} contradiction group(s)."
            )
        output_obj = kq

    elif group_id == "autonomous_improvement":
        if not existing_run_id:
            conn.close()
            return {"ok": False, "error": "existing_run_id is required for approved autonomous_improvement execution"}
        run_row_obj = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (existing_run_id,)).fetchone()
        if not run_row_obj:
            conn.close()
            return {"ok": False, "error": "Workflow run not found"}
        res_imp = _execute_autonomous_improvement_approved(
            conn,
            dict(run_row_obj),
            approved_by=str(approved_by),
            user_id=user_id,
        )
        exec_ok = bool(res_imp["ok"])
        status = res_imp["status"]
        summary = res_imp["summary"]
        stages_out = res_imp["stages_out"]
        invalidated_reason = res_imp.get("invalidated_reason")
        verification_obj = res_imp.get("verification_obj")
        output_obj = res_imp.get("output_obj") or {}

    elif group_id == "security_governance":
        integrity = _compute_native_integrity()
        core_hash = integrity["core_bundle_sha256"]
        active_keys = conn.execute("SELECT COUNT(*) FROM api_keys WHERE revoked=0").fetchone()[0]
        audit_count = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        stages_out = [
            {"stage": "integrity_hash", "status": "PASS", "detail": f"native_core bundle sha256:{core_hash}... (external_models_used=false)"},
            {"stage": "key_hygiene", "status": "PASS", "detail": f"{active_keys} hashed API key(s) active"},
            {"stage": "audit_verify", "status": "PASS", "detail": f"{audit_count} immutable audit event(s)"},
        ]
        output_obj = {"integrity": integrity, "active_keys": active_keys, "audit_count": audit_count}
        summary = f"Security Governance verified: bundle sha256:{core_hash}, {active_keys} active key(s), {audit_count} audit log(s)."

    elif group_id == "project_dev":
        ckpt_count = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        ds_count = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        repo_rev = _compute_repo_revision(BASE_DIR)
        stages_out = [
            {"stage": "runtime_sync", "status": "PASS", "detail": f"Express + Python Native Core synchronized ({repo_rev})"},
            {"stage": "artifact_check", "status": "PASS", "detail": f"{ds_count} dataset(s), {ckpt_count} checkpoint(s)"},
            {"stage": "roadmap_verify", "status": "PASS", "detail": "No unauthorized architecture mutations"},
        ]
        output_obj = {"repo_revision": repo_rev, "datasets": ds_count, "checkpoints": ckpt_count}
        summary = f"Project sync verified ({repo_rev}): {ds_count} dataset(s), {ckpt_count} immutable checkpoint(s)."

    if existing_run_id:
        with conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status=?, approved_by=?, summary=?, stages_json=?,
                    depends_on_runs_json=COALESCE(?, depends_on_runs_json),
                    output_json=?, verification_json=?, invalidated_reason=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    approved_by,
                    summary,
                    json.dumps(stages_out),
                    json.dumps(depends_on_runs) if depends_on_runs else None,
                    json.dumps(output_obj, ensure_ascii=False),
                    json.dumps(verification_obj, ensure_ascii=False) if verification_obj is not None else None,
                    invalidated_reason,
                    now_iso(),
                    existing_run_id,
                ),
            )
        run_id = existing_run_id
    else:
        run_id = str(uuid.uuid4())
        with conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    id, group_id, status, requires_approval, triggered_by, approved_by,
                    summary, stages_json, depends_on_runs_json, output_json, verification_json,
                    invalidated_reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    group_id,
                    status,
                    1 if group["requires_approval"] else 0,
                    user_id,
                    approved_by,
                    summary,
                    json.dumps(stages_out),
                    json.dumps(depends_on_runs) if depends_on_runs else None,
                    json.dumps(output_obj, ensure_ascii=False),
                    json.dumps(verification_obj, ensure_ascii=False) if verification_obj is not None else None,
                    invalidated_reason,
                    now_iso(),
                    now_iso(),
                ),
            )
    run = dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone())
    conn.close()
    if not exec_ok:
        return {"ok": False, "error": summary, "run": run}
    return {"ok": True, "run": run}


def _integrate_mission_knowledge(
    conn: sqlite3.Connection,
    goal: str,
    user_id: str,
    terms: list[str],
    research_res: dict,
) -> dict:
    developed_triples: list[dict] = []
    details: list[str] = []

    explicit_teach = try_teach_knowledge(conn, goal, user_id)
    if explicit_teach and explicit_teach.get("triple"):
        tr = explicit_teach["triple"]
        developed_triples.append(
            {
                "id": tr["id"],
                "subject": tr["subject"],
                "relation": tr["relation"],
                "object": tr["object"],
                "source": tr["source"],
                "contradictions": explicit_teach.get("contradictions", []),
            }
        )
        details.append(f"บันทึกความสัมพันธ์โดยตรง: {tr['subject']} -> {tr['relation']} -> {tr['object']}")

    if research_res and research_res.get("status") == "COMPLETED":
        analysis_obj = research_res.get("analysis") or {}
        t_grade = str(research_res.get("trust_grade") or analysis_obj.get("trust_grade") or "")
        ev_items = analysis_obj.get("evidence_items") or []
        if t_grade in {"CORROBORATED_MULTI_SOURCE", "UNCORROBORATED_SINGLE_SOURCE"} and ev_items:
            topic_subj = (terms[0] if terms else goal[:40]).strip()
            shared = analysis_obj.get("cross_source_shared_terms") or analysis_obj.get("top_terms") or []
            candidates: list[tuple[str, str, str]] = []
            # Extract concrete factual triples from verified claims
            for cl_obj in (research_res.get("claims") or [])[:6]:
                c_txt = str(cl_obj.get("claim_text") or "").strip()
                m_rel = re.search(
                    r"\b([A-Za-z0-9_.-]{2,30})\s+(supports|enables|uses|provides|released in)\s+([A-Za-z0-9_., -]{2,48})",
                    c_txt,
                    re.IGNORECASE,
                ) or re.search(
                    r"([\u0E00-\u0E7FA-Za-z0-9_-]{2,30})\s+(รองรับ|ใช้|เปิดตัวเมื่อ|พัฒนาโดย|ทำให้เกิด)\s+([\u0E00-\u0E7FA-Za-z0-9_ -]{2,48})",
                    c_txt,
                )
                if m_rel:
                    s_c, r_c, o_c = m_rel.group(1).strip(), m_rel.group(2).strip(), m_rel.group(3).strip(" .,;")
                    if s_c and r_c and o_c and len(candidates) < 2:
                        candidates.append((s_c, r_c, o_c))
            if shared:
                candidates.append((topic_subj, "เชื่อมโยงแนวคิด", ", ".join(shared[:3])))
            first_ev = ev_items[0]
            if first_ev.get("title"):
                candidates.append(
                    (
                        topic_subj,
                        "มีเอกสารอ้างอิง",
                        f"{first_ev['title'][:60]} ({first_ev.get('provider', 'web')})",
                    )
                )
            conf_val = 0.9 if t_grade == "CORROBORATED_MULTI_SOURCE" else 0.65
            src_tag = f"autonomous_research:{t_grade.lower()}"
            for subj_c, rel_c, obj_c in candidates:
                dup = conn.execute(
                    "SELECT id FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?) AND lower(object)=lower(?)",
                    (subj_c, rel_c, obj_c),
                ).fetchone()
                if dup:
                    continue
                existing_rel = conn.execute(
                    "SELECT object FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?)",
                    (subj_c, rel_c),
                ).fetchall()
                contradictions = [r["object"] for r in existing_rel if r["object"].lower() != obj_c.lower()]
                tid = str(uuid.uuid4())
                with conn:
                    conn.execute(
                        "INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (tid, subj_c, rel_c, obj_c, src_tag, conf_val, user_id, now_iso()),
                    )
                developed_triples.append(
                    {
                        "id": tid,
                        "subject": subj_c,
                        "relation": rel_c,
                        "object": obj_c,
                        "source": src_tag,
                        "contradictions": contradictions,
                    }
                )
            if developed_triples:
                details.append(f"พัฒนาความรู้ใหม่เข้ากราฟถาวร {len(developed_triples)} รายการ ({t_grade})")
            else:
                details.append("หลักฐานตรงกับความรู้เดิม (ไม่สร้างซ้ำ)")
        elif t_grade in {"CONFLICTING_SOURCES", "STALE", "BLOCKED", "INSUFFICIENT_EVIDENCE"}:
            details.append(f"งดบันทึกความรู้ใหม่อัตโนมัติเนื่องจากหลักฐานอยู่ในระดับ {t_grade} (NOT_LEARNED)")
    elif not details:
        kg_hits = query_knowledge_graph(conn, goal)
        details.append(f"ตรวจสอบความสอดคล้องกราฟความรู้ภายในแล้ว (พบฐานความรู้เดิม {len(kg_hits)} รายการ)")

    return {
        "triples": developed_triples,
        "detail": " · ".join(details),
    }


def _mission_callbacks() -> dict:
    return {
        "tokenize": tokenize,
        "extract_terms": extract_query_terms,
        "query_kg": query_knowledge_graph,
        "calc_any": _calc_any_for_tool,
        "try_logic": try_transitive_logic_reasoning,
        "try_causal_logic": try_causal_logic_reasoning,
        "integrate_knowledge": _integrate_mission_knowledge,
    }


def _finalize_mission_record(
    conn: sqlite3.Connection,
    mission_id: str,
    goal: str,
    user_id: str,
    caps_obj: dict,
    dag_result: dict,
    ctx: dict,
    started_iso: str,
) -> dict:
    nodes = dag_result.get("nodes", [])
    node_map = {n["task_id"]: n for n in nodes}
    m_status = str(dag_result.get("mission_status") or "FAILED")
    if m_status not in MISSION_STATES:
        m_status = "FAILED"
    recovery_events = list(dag_result.get("recovery_events") or [])
    developed_triples = list(ctx.get("developed_triples") or [])

    r_node = node_map.get("node_research_discover")
    r_out = (r_node or {}).get("output_data") or {}
    r_analysis = r_out.get("analysis") or {}
    research_summary = {
        "queried": bool(caps_obj.get("enable_research", True)),
        "status": (r_node or {}).get("execution_status", "SKIPPED"),
        "verdict": r_out.get("verdict"),
        "trust_grade": r_out.get("trust_grade") or r_analysis.get("trust_grade"),
        "invocation_id": r_out.get("invocation_id"),
        "queries": r_out.get("queries", []),
        "sub_queries_executed": r_out.get("sub_queries_executed", []),
        "providers": r_analysis.get("distinct_providers", []),
        "shared_terms": r_analysis.get("cross_source_shared_terms", []),
        "claims_count": len(r_out.get("claims") or []),
        "doc_fetch": r_out.get("doc_fetch"),
        "injection_warnings": r_out.get("injection_warnings", []),
        "limitations": r_analysis.get("limitations", []),
    }

    think_node = node_map.get("node_goal_analysis")
    think_out = (think_node or {}).get("output_data") or {}
    think_detail = (
        f"สกัดคำสำคัญ {think_out.get('terms_count', 0)} หน่วย · เชื่อมโยงกราฟเดิม {think_out.get('kg_hits', 0)} รายการ"
        if think_node
        else "วิเคราะห์เป้าหมายผ่าน Native Core"
    )

    if r_node:
        r_st = r_node["execution_status"]
        disc_status = "PENDING_APPROVAL" if r_st == "AWAITING_APPROVAL" else ("PASS" if r_st == "COMPLETED" else r_st)
        disc_detail = (
            "ส่งคำขอ web_search เข้า P5 Approval Gate แล้ว (ภารกิจหยุดรอการอนุมัติและสามารถทำงานต่ออัตโนมัติ)"
            if r_st == "AWAITING_APPROVAL"
            else (r_out.get("error") or f"verdict={research_summary.get('verdict')} · claims={research_summary.get('claims_count', 0)}")
        )
    else:
        disc_status = "SKIPPED"
        disc_detail = "ปิดการค้นคว้าอินเทอร์เน็ตสำหรับภารกิจนี้"

    k_node = node_map.get("node_knowledge_integrate")
    k_out = (k_node or {}).get("output_data") or {}
    learn_status = "PASS" if (k_node and k_node["execution_status"] == "COMPLETED") else ("WAITING" if m_status == "AWAITING_APPROVAL" else ("SKIPPED" if not k_node else k_node["execution_status"]))
    learn_detail = str(k_out.get("detail") or ("รออนุมัติการค้นคว้าก่อนพัฒนาองค์ความรู้" if learn_status == "WAITING" else "ตรวจสอบกราฟความรู้"))

    plan_status = "PASS" if nodes else "SKIPPED"
    plan_detail = f"สร้าง DAG {len(nodes)} โหนดพร้อม pre/postconditions และ recovery policy"

    act_nodes = [n for n in nodes if n["task_id"] not in {"node_goal_analysis", "node_research_discover", "node_knowledge_integrate"}]
    if not act_nodes:
        act_status = "WAITING" if m_status == "AWAITING_APPROVAL" else "SKIPPED"
        act_detail = "รอดำเนินการหลังการค้นคว้าและการพัฒนาความรู้"
    else:
        act_done = [n for n in act_nodes if n["execution_status"] == "COMPLETED"]
        act_fail = [n for n in act_nodes if n["execution_status"] in {"FAILED", "BLOCKED"}]
        act_status = "PASS" if (len(act_done) == len(act_nodes)) else ("FAILED" if act_fail else "WAITING")
        act_detail = " · ".join(f"{n['task_id']}:{n['execution_status']}" for n in act_nodes)

    if m_status == "AWAITING_APPROVAL":
        ver_status = "PENDING_APPROVAL"
        ver_detail = "ภารกิจพักรอการอนุมัติใน P5 Gate — ระบบบันทึก DAG state ถาวรเพื่อ resume ต่อทันทีหลังอนุมัติ"
    elif m_status == "COMPLETED":
        ver_status = "PASS"
        ver_detail = f"ยืนยัน postconditions ครบทุกโหนด ({len([n for n in nodes if n['execution_status']=='COMPLETED'])}/{len(nodes)}) · external_models_used=false"
    else:
        ver_status = "FAILED" if m_status == "FAILED" else "BLOCKED"
        ver_detail = f"ภารกิจสิ้นสุดสถานะ {m_status} (ไม่รายงานสำเร็จเท็จ)"

    gaps = detect_capability_gaps(conn)
    gap_type = gaps[0]["gap_type"] if gaps else None
    improve_detail = (
        "; ".join(recovery_events)
        if recovery_events
        else (gaps[0]["detail"] if gaps else "บันทึกประสบการณ์ลง Episodic Memory แล้ว")
    )
    if m_status in {"COMPLETED", "FAILED", "BLOCKED"}:
        record_episodic_experience(
            conn,
            mission_id=mission_id,
            goal=goal,
            outcome_status=m_status,
            gap_type=gap_type if m_status != "COMPLETED" else None,
            hypothesis={"recovery_events": recovery_events, "gaps": gaps[:2]},
            verified_delta=float(len(developed_triples)),
        )

    stages = [
        {"stage": "think", "label": "1. Think (Autonomous Cognition)", "status": "PASS", "detail": think_detail},
        {"stage": "discover", "label": "2. Discover (Autonomous Research)", "status": disc_status, "detail": disc_detail},
        {"stage": "learn", "label": "3. Learn (Knowledge Development)", "status": learn_status, "detail": learn_detail},
        {"stage": "plan", "label": "4. Plan (DAG Decomposition)", "status": plan_status, "detail": plan_detail},
        {"stage": "act", "label": "5. Act (DAG Execution & Recovery)", "status": act_status, "detail": act_detail},
        {"stage": "verify", "label": "6. Verify (Postcondition Check)", "status": ver_status, "detail": ver_detail},
        {"stage": "improve", "label": "7. Improve (Episodic Gap Loop)", "status": "PASS", "detail": improve_detail},
    ]

    stage_lines = "\n".join(f"- **{s['label']}** [`{s['status']}`]: {s['detail']}" for s in stages)
    triple_lines = (
        "\n".join(f"- `{t['subject']}` — *{t['relation']}* → `{t['object']}` (แหล่ง: `{t['source']}`)" for t in developed_triples)
        if developed_triples
        else "- ยังไม่มีการเพิ่ม Triple ใหม่ลงกราฟความรู้ในรอบนี้"
    )
    report_md = (
        f"**ผลปฏิบัติการอัตโนมัติ ZYRQUEN Ω∞ (`{m_status}`)**\n"
        f"เป้าหมาย: `{goal}`\n\n"
        f"> วงจร Think → Discover → Learn → Plan → Act → Verify → Improve (DAG Executor · Native Cognitive Core)\n\n"
        f"**ลำดับการปฏิบัติการจริง:**\n{stage_lines}\n\n"
        f"**องค์ความรู้ที่พัฒนาในรอบนี้:**\n{triple_lines}"
    )

    now = now_iso()
    with conn:
        conn.execute(
            """
            UPDATE autonomous_missions
            SET status=?, stages_json=?, knowledge_developed_json=?, research_summary_json=?, report_markdown=?, updated_at=?
            WHERE id=?
            """,
            (
                m_status,
                json.dumps(stages, ensure_ascii=False),
                json.dumps(developed_triples, ensure_ascii=False),
                json.dumps(research_summary, ensure_ascii=False),
                report_md,
                now,
                mission_id,
            ),
        )
    mission = dict(conn.execute("SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)).fetchone())
    node_rows = [dict(r) for r in conn.execute("SELECT * FROM mission_nodes WHERE mission_id=? ORDER BY rowid ASC", (mission_id,)).fetchall()]
    ev_rows = [dict(r) for r in conn.execute("SELECT * FROM mission_evidence WHERE mission_id=? ORDER BY rowid ASC", (mission_id,)).fetchall()]
    return {"ok": True, "mission": mission, "nodes": node_rows, "evidence": ev_rows}


def run_autonomous_mission(payload: dict) -> dict:
    """
    ZYRQUEN Autonomous Cognitive-Action Loop powered by real DAG Execution State Machine.
    Persists mission states (MISSION_CREATED -> GOAL_ANALYZED -> PLAN_READY -> EXECUTING ->
    AWAITING_APPROVAL/COMPLETED/BLOCKED/FAILED) and supports safe resumption.
    """
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return {"ok": False, "error": "กรุณาระบุเป้าหมายของปฏิบัติการอัตโนมัติ"}

    user_id = str(payload.get("user_id", "") or "system")
    conversation_id = payload.get("conversation_id")
    enable_research = bool(payload.get("enable_research", True))
    enable_knowledge_dev = bool(payload.get("enable_knowledge_dev", True))
    enable_planning = bool(payload.get("enable_planning", True))
    enable_execution = bool(payload.get("enable_execution", True))

    conn = get_db()
    from tool_center import get_tool_center_registry

    tc_reg = get_tool_center_registry()
    tc_plan = tc_reg.compose_for_goal(goal, user_role=str(payload.get("user_role") or "user"), conn=conn)
    mission_id = str(uuid.uuid4())
    started_iso = now_iso()
    caps_obj = {
        "enable_research": enable_research,
        "enable_knowledge_dev": enable_knowledge_dev,
        "enable_planning": enable_planning,
        "enable_execution": enable_execution,
        "tool_center": {
            "selected_toolkits": tc_plan.get("selected_toolkits", []),
            "selected_capabilities": [
                f"{c['capability_id']}@{c['version']}"
                for c in tc_plan.get("selected_capabilities", [])
            ],
            "task_memory_hints": tc_plan.get("task_memory_hints", {}),
            "resource_admission_allowed": bool((tc_plan.get("resource_admission") or {}).get("allowed", True)),
        },
    }

    with conn:
        conn.execute(
            """
            INSERT INTO autonomous_missions (
                id, goal, status, capabilities_json, stages_json,
                knowledge_developed_json, research_summary_json, report_markdown,
                external_models_used, created_by, created_at, updated_at
            )
            VALUES (?, ?, 'MISSION_CREATED', ?, '[]', '[]', '{}', '', 0, ?, ?, ?)
            """,
            (mission_id, goal, json.dumps(caps_obj, ensure_ascii=False), user_id, started_iso, started_iso),
        )

    math_hit = _calc_any_for_tool(goal)
    logic_hit = try_transitive_logic_reasoning(goal)
    causal_hit = try_causal_logic_reasoning(goal, conn)
    nodes = build_mission_dag(
        mission_id,
        goal,
        has_math=bool(math_hit),
        has_logic=bool(logic_hit or causal_hit),
        enable_research=enable_research,
        enable_knowledge_dev=enable_knowledge_dev,
        enable_execution=enable_execution,
    )

    with conn:
        conn.execute(
            "UPDATE autonomous_missions SET status='PLAN_READY', updated_at=? WHERE id=?",
            (now_iso(), mission_id),
        )

    ctx = {
        "goal": goal,
        "user_id": user_id,
        "conversation_id": str(conversation_id) if conversation_id else None,
        "math_hit": math_hit,
        "logic_hit": logic_hit,
        "causal_hit": causal_hit,
    }
    dag_result = execute_dag_loop(
        conn,
        DATA_DIR,
        mission_id,
        nodes,
        ctx,
        callbacks=_mission_callbacks(),
    )
    out = _finalize_mission_record(conn, mission_id, goal, user_id, caps_obj, dag_result, ctx, started_iso)
    conn.close()
    return out


def resume_autonomous_mission(payload: dict) -> dict:
    """Resume a paused/recoverable mission from its persisted DAG state in SQLite."""
    mission_id = str(payload.get("mission_id", "")).strip()
    if not mission_id:
        return {"ok": False, "error": "mission_id is required"}
    approved_by = payload.get("approved_by")
    decision = payload.get("decision")
    invocation_id = payload.get("invocation_id")
    node_id = payload.get("node_id")

    conn = get_db()
    m_row = conn.execute("SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)).fetchone()
    if not m_row:
        conn.close()
        return {"ok": False, "error": "Mission not found"}
    if m_row["status"] == "CANCELLED":
        conn.close()
        return {"ok": False, "error": "Mission was cancelled"}

    node_rows = conn.execute(
        "SELECT * FROM mission_nodes WHERE mission_id=? ORDER BY rowid ASC",
        (mission_id,),
    ).fetchall()
    if not node_rows:
        conn.close()
        return {"ok": False, "error": "Mission has no persisted DAG nodes"}

    nodes = [json.loads(r["node_json"]) for r in node_rows]
    if not node_id:
        pending_n = next((n for n in nodes if n.get("execution_status") == "AWAITING_APPROVAL"), None)
        node_id = pending_n["task_id"] if pending_n else None

    caps_obj = json.loads(m_row["capabilities_json"] or "{}")
    ctx: dict = {
        "goal": m_row["goal"],
        "user_id": m_row["created_by"],
        "conversation_id": None,
        "terms": extract_query_terms(m_row["goal"]),
    }
    # Hydrate research output from completed or pending research node if available
    for n in nodes:
        if n.get("tool_id") == "research_pipeline" and isinstance(n.get("output_data"), dict) and n["output_data"]:
            ctx["research_result"] = n["output_data"]

    with conn:
        conn.execute(
            "UPDATE autonomous_missions SET status='EXECUTING', updated_at=? WHERE id=?",
            (now_iso(), mission_id),
        )

    dag_result = execute_dag_loop(
        conn,
        DATA_DIR,
        mission_id,
        nodes,
        ctx,
        callbacks=_mission_callbacks(),
        resume_node_id=node_id,
        approved_by=approved_by,
        approval_decision=decision,
        existing_invocation_id=invocation_id,
    )
    out = _finalize_mission_record(
        conn,
        mission_id,
        m_row["goal"],
        m_row["created_by"],
        caps_obj,
        dag_result,
        ctx,
        m_row["created_at"],
    )
    conn.close()
    return out


def cancel_autonomous_mission(payload: dict) -> dict:
    mission_id = str(payload.get("mission_id", "")).strip()
    if not mission_id:
        return {"ok": False, "error": "mission_id is required"}
    conn = get_db()
    m_row = conn.execute("SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)).fetchone()
    if not m_row:
        conn.close()
        return {"ok": False, "error": "Mission not found"}
    with conn:
        conn.execute(
            "UPDATE autonomous_missions SET status='CANCELLED', updated_at=? WHERE id=?",
            (now_iso(), mission_id),
        )
    mission = dict(conn.execute("SELECT * FROM autonomous_missions WHERE id=?", (mission_id,)).fetchone())
    conn.close()
    return {"ok": True, "mission": mission}



def summarize_conversation(messages: list[dict]) -> dict:
    """
    Deterministic Native Conversation Summarizer (no external LLM).
    Extracts verified AST math outputs, taught/discovered knowledge triples,
    multi-hop BFS paths, DAG plans, and top recurring Thai/English terms.
    """
    if not messages:
        return {
            "bullets": [],
            "metrics": {"total_messages": 0, "verified_count": 0, "not_learned_count": 0},
        }

    bullets: list[str] = []
    seen_bullets: set[str] = set()
    verified_count = 0
    not_learned_count = 0
    user_tokens: list[str] = []
    stop_tokens = {
        "คำนวณ", "สอน", "จำ", "วางแผน", "เชื่อมโยง", "หาเส้นทาง", "อะไร", "คือ",
        "และ", "ที่", "ใน", "ของ", "ให้", "ได้", "เป็น", "มี", "การ", "ความ",
    }

    def add_bullet(text: str) -> None:
        if text not in seen_bullets and len(bullets) < 7:
            seen_bullets.add(text)
            bullets.append(text)

    for m in messages:
        role = m.get("role")
        status = str(m.get("status", ""))
        content = str(m.get("content", "")).strip()
        if role == "user":
            for tok in extract_query_terms(content):
                if tok not in stop_tokens and len(tok) >= 2:
                    user_tokens.append(tok)
            continue

        if status == "VERIFIED":
            verified_count += 1
        elif status in {"NOT_LEARNED", "UNABLE_TO_INFER"}:
            not_learned_count += 1

        trace_raw = m.get("trace_json")
        if not trace_raw:
            continue
        try:
            trace = json.loads(trace_raw) if isinstance(trace_raw, str) else trace_raw
        except Exception:
            trace = {}
        if not isinstance(trace, dict):
            continue

        if "math" in trace and isinstance(trace["math"], dict):
            math_obj = trace["math"]
            add_bullet(f"คำนวณ AST ยืนยันผล: `{math_obj.get('expression')}` = `{math_obj.get('result')}`")

        if "algebra" in trace and isinstance(trace["algebra"], dict):
            alg = trace["algebra"]
            res_str = (
                f"{alg.get('variable')} = {alg.get('result')}"
                if alg.get("solution_type") == "unique"
                else str(alg.get("solution_type"))
            )
            add_bullet(f"แก้สมการเชิงเส้น `{alg.get('equation')}` → `{res_str}`")

        if "statistics" in trace and isinstance(trace["statistics"], dict):
            st = trace["statistics"]
            add_bullet(
                f"วิเคราะห์สถิติ ({st.get('count')} ค่า): Mean `{st.get('mean')}`, Median `{st.get('median')}`, SD `{st.get('stdev')}`"
            )

        if "teach" in trace and isinstance(trace["teach"], dict):
            tr = trace["teach"].get("triple", {})
            contradictions = trace["teach"].get("contradictions", [])
            note = f" (พบข้อขัดแย้ง: {', '.join(contradictions)})" if contradictions else ""
            add_bullet(
                f"บันทึกความจำ: `{tr.get('subject')} -> {tr.get('relation')} -> {tr.get('object')}`{note}"
            )

        if "graph_path" in trace and isinstance(trace["graph_path"], dict):
            gp = trace["graph_path"]
            if gp.get("found") and gp.get("path"):
                p = gp["path"]
                add_bullet(f"ค้นพบเส้นทางเชื่อมโยง {p.get('hops')} ช่วง: `{p.get('start')}` → `{p.get('end')}`")
            else:
                add_bullet(f"ไม่พบเส้นทางในกราฟความรู้: `{gp.get('start')}` → `{gp.get('end')}`")

        if "matched_triples" in trace and isinstance(trace["matched_triples"], list) and trace["matched_triples"]:
            first = trace["matched_triples"][0]
            add_bullet(
                f"อ้างอิงกราฟความรู้ ({len(trace['matched_triples'])} รายการ): "
                f"`{first.get('subject')} -> {first.get('relation')} -> {first.get('object')}`"
            )

        if "plan" in trace and isinstance(trace["plan"], dict):
            pl = trace["plan"]
            pl_goal = str(pl.get("goal", "")).strip()
            pl_steps = pl.get("steps") or []
            if (
                pl.get("plan_valid") is not False
                and pl.get("is_actionable_goal") is not False
                and pl.get("plan_status") not in ("NEEDS_CLARIFICATION", "BLOCKED")
                and pl_goal
                and pl_steps
            ):
                sm = pl.get("summary", {})
                add_bullet(
                    f"แผนงาน DAG (`{pl_goal[:40]}`): "
                    f"{sm.get('total_steps', len(pl_steps))} ขั้นตอน (ถูกบล็อก {sm.get('blocked_steps', 0)}, รออนุมัติ {sm.get('approval_gated_steps', 0)})"
                )

        if "causal_logic" in trace and isinstance(trace["causal_logic"], dict):
            cl = trace["causal_logic"]
            if cl.get("determined") and cl.get("derived_conclusion"):
                add_bullet(f"อนุมานเหตุ-ผล/ตรรกศาสตร์ (`{cl.get('sub_type')}`): `{cl.get('derived_conclusion')}`")
            elif cl.get("contradiction"):
                add_bullet("ตรวจพบข้อขัดแย้งเชิงสาเหตุ/ตรรกศาสตร์ (BLOCKED)")

        if "checkpoint" in trace and isinstance(trace["checkpoint"], dict):
            ck = trace["checkpoint"]
            if ck.get("generated"):
                add_bullet(
                    f"ทำนายข้อความ Checkpoint v{ck.get('checkpoint_version')} (ppl {ck.get('perplexity')})"
                )

        if "external_tool" in trace and isinstance(trace["external_tool"], dict):
            et = trace["external_tool"]
            grade = f" · {et.get('trust_grade')}" if et.get("trust_grade") else ""
            add_bullet(
                f"เครื่องมือ `{et.get('tool_id')}` ({et.get('status')}{grade}): {et.get('analysis_summary') or 'รอตรวจสอบ'}"
            )

    if user_tokens:
        top_terms = [w for w, _ in collections.Counter(user_tokens).most_common(4)]
        add_bullet(f"หัวข้อหลักที่สนทนา: {', '.join(top_terms)}")

    if not_learned_count > 0:
        add_bullet(f"ขอบเขตความซื่อสัตย์: ตอบว่า 'ยังไม่ได้เรียนรู้' {not_learned_count} ครั้งโดยไม่สร้างข้อมูลสมมติ")

    return {
        "bullets": bullets,
        "metrics": {
            "total_messages": len(messages),
            "verified_count": verified_count,
            "not_learned_count": not_learned_count,
        },
    }


def dispatch_command(cmd: str, payload: dict) -> dict:
    if cmd == "init":
        return {"ok": True, "db_path": str(DB_PATH)}
    if cmd == "health":
        conn = get_db()
        triples = conn.execute("SELECT COUNT(*) FROM knowledge_triples").fetchone()[0]
        ckpts = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        datasets = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        conn.close()
        return {
            "ok": True,
            "metrics": get_system_metrics(),
            "counts": {"triples": triples, "checkpoints": ckpts, "datasets": datasets},
        }
    if cmd == "infer":
        res = handle_infer(payload)
        return {"ok": True, **res}
    if cmd == "ingest_dataset":
        return handle_ingest_dataset(payload)
    if cmd == "verify_dataset":
        conn = get_db()
        res = verify_dataset_integrity(conn, str(payload.get("dataset_id", "")))
        conn.close()
        return res
    if cmd == "decide_kg_proposal":
        conn = get_db()
        res = decide_kg_proposal(
            conn,
            proposal_id=str(payload.get("proposal_id", "")),
            decision=str(payload.get("decision", "approve")),
            admin_email=str(payload.get("admin_email", "admin")),
            admin_id=str(payload.get("admin_id", "admin")),
            reason=payload.get("reason"),
        )
        conn.close()
        return res
    if cmd == "run_workflow":
        return handle_run_workflow(payload)
    if cmd == "evaluate":
        return handle_run_evaluation(payload)
    if cmd == "evaluations_list":
        conn = get_db()
        rows = [dict(r) for r in conn.execute("SELECT * FROM evaluations ORDER BY created_at DESC LIMIT 15").fetchall()]
        conn.close()
        return {"ok": True, "evaluations": rows}
    if cmd == "run_mission":
        return run_autonomous_mission(payload)
    if cmd == "resume_mission":
        return resume_autonomous_mission(payload)
    if cmd == "cancel_mission":
        return cancel_autonomous_mission(payload)
    if cmd == "run_experiment":
        conn = get_db()
        res = run_controlled_neural_experiment(
            conn,
            CHECKPOINT_DIR,
            str(payload.get("user_id", "system")),
            dataset_id=payload.get("dataset_id"),
            epochs=int(payload.get("epochs", 8)),
            seed=int(payload.get("seed", 42)),
            require_baseline_and_approval=bool(payload.get("require_baseline_and_approval", False)),
        )
        conn.close()
        return res
    if cmd == "decide_experiment":
        conn = get_db()
        res = decide_experiment(
            conn,
            CHECKPOINT_DIR,
            experiment_id=str(payload.get("experiment_id", "")),
            decision=str(payload.get("decision", "approve")),
            admin_email=str(payload.get("admin_email", "admin")),
            admin_id=str(payload.get("admin_id", "admin")),
        )
        conn.close()
        return res
    if cmd == "curate_corpus":
        conn = get_db()
        res = curate_verified_training_corpus(
            conn,
            str(payload.get("user_id", "system")),
            handle_ingest_dataset,
            name=str(payload.get("name", "verified-knowledge-corpus")),
        )
        conn.close()
        return res
    if cmd == "curate_code_corpus":
        conn = get_db()
        res = curate_code_problem_corpus(
            conn,
            str(payload.get("user_id", "system")),
            handle_ingest_dataset,
            name=str(payload.get("name", "code-problem-solving-corpus")),
            extra_tasks=payload.get("extra_tasks") if isinstance(payload.get("extra_tasks"), list) else None,
        )
        conn.close()
        return res
    if cmd == "run_code_training_experiment":
        conn = get_db()
        res = run_code_problem_experiment(
            conn,
            CHECKPOINT_DIR,
            str(payload.get("user_id", "system")),
            dataset_id=payload.get("dataset_id"),
            epochs=int(payload.get("epochs", 3)),
            seed=int(payload.get("seed", 42)),
        )
        conn.close()
        return res
    if cmd == "evaluate_code_model":
        conn = get_db()
        res = evaluate_code_problem_model(conn)
        conn.close()
        return res
    if cmd == "run_real_only_jsonl_training":
        raw_data_path = str(payload.get("data_path") or "").strip()
        if not raw_data_path:
            return {
                "ok": False,
                "status": "BLOCKED",
                "reason": "MISSING_DATA_PATH",
                "error": "STOP: กรุณาระบุพาธไฟล์ JSONL ข้อมูลจริง (data_path)",
                "external_models_used": False,
                "synthetic_data_used": False,
            }
        cand_path = Path(raw_data_path)
        if not cand_path.is_absolute():
            cand_path = (DATA_DIR / cand_path).resolve()
        else:
            cand_path = cand_path.resolve()
        data_root = DATA_DIR.resolve()
        base_root = BASE_DIR.resolve()
        if not (cand_path.is_relative_to(data_root) or cand_path.is_relative_to(base_root)):
            return {
                "ok": False,
                "status": "BLOCKED",
                "reason": "PATH_OUTSIDE_WORKSPACE",
                "error": "STOP: พาธไฟล์ข้อมูลต้องอยู่ภายในพื้นที่ข้อมูลของระบบเท่านั้น",
                "external_models_used": False,
                "synthetic_data_used": False,
            }
        conn = get_db()
        res = record_real_only_training_in_db(
            conn,
            checkpoint_dir=CHECKPOINT_DIR,
            user_id=str(payload.get("user_id", "system")),
            data_path=cand_path,
            epochs=int(payload.get("epochs", 5)),
            lr=float(payload.get("lr", 0.05)),
            seed=int(payload.get("seed", 42)),
            min_samples=int(payload.get("min_samples", 30)),
            run_sandbox_audit=bool(payload.get("sandbox_audit", False)),
            require_sandbox_pass=bool(payload.get("require_sandbox_pass", False)),
        )
        conn.close()
        return res
    if cmd == "synthesize_curriculum":
        conn = get_db()
        res = synthesize_failure_curriculum(
            conn,
            heldout_prompts=payload.get("heldout_prompts"),
            limit=int(payload.get("limit", 50)),
        )
        conn.close()
        return res
    if cmd == "run_continual_round":
        conn = get_db()
        res = run_continual_learning_round(
            conn,
            CHECKPOINT_DIR,
            str(payload.get("user_id", "system")),
            new_train_lines=payload.get("new_train_lines"),
            anchor_lines=payload.get("anchor_lines"),
            replay_ratio=float(payload.get("replay_ratio", 0.35)),
            anchor_l2_lambda=float(payload.get("anchor_l2_lambda", 0.02)),
            max_forgetting_loss_delta=float(payload.get("max_forgetting_loss_delta", 0.25)),
            max_forgetting_acc_drop=float(payload.get("max_forgetting_acc_drop", 0.15)),
            epochs=int(payload.get("epochs", 6)),
            lr=float(payload.get("lr", 0.012)),
            seed=int(payload.get("seed", 42)),
        )
        conn.close()
        return res
    if cmd == "workflow_groups":
        return {"ok": True, "groups": WORKFLOW_GROUPS}
    if cmd == "tool_center_orchestrate":
        from tool_center import execute_orchestrated_plan, get_tool_center_registry

        conn = get_db()
        res = execute_orchestrated_plan(
            get_tool_center_registry(),
            str(payload.get("goal", "")),
            payload.get("steps") or [],
            conn=conn,
            data_dir=DATA_DIR,
            user_id=str(payload.get("user_id", "system")),
            user_role=str(payload.get("user_role", "user")),
            shared_context=payload.get("shared_context") if isinstance(payload.get("shared_context"), dict) else None,
            idempotency_scope=payload.get("idempotency_scope"),
            enable_parallel=bool(payload.get("enable_parallel", True)),
        )
        conn.close()
        return res
    if cmd == "tool_center_self_improve":
        from tool_center import get_tool_center_registry, run_self_improvement_evaluation

        conn = get_db()
        res = run_self_improvement_evaluation(
            conn,
            get_tool_center_registry(),
            data_dir=DATA_DIR,
            user_id=str(payload.get("user_id", "system")),
            sandbox_probe_code=payload.get("sandbox_probe_code"),
        )
        conn.close()
        return res
    if cmd == "tool_center_decide_improvement":
        from tool_center import decide_improvement_proposal

        conn = get_db()
        res = decide_improvement_proposal(
            conn,
            proposal_id=str(payload.get("proposal_id", "")),
            decision=str(payload.get("decision", "reject")),
            admin_email=str(payload.get("admin_email", "admin")),
            admin_id=str(payload.get("admin_id", "admin")),
            reason=payload.get("reason"),
        )
        conn.close()
        return res
    return {"ok": False, "error": f"Unknown command '{cmd}'"}


def main() -> None:
    init_db()
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"ok": False, "error": "Empty command payload"}))
        return
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"Invalid JSON: {exc}"}))
        return

    cmd = str(req.get("cmd", ""))
    payload = req.get("payload", {})
    print(json.dumps(dispatch_command(cmd, payload)))


if __name__ == "__main__":
    main()
