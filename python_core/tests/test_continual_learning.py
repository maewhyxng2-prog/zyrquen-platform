"""
Unit tests for Continual Learning, Catastrophic Forgetting Protection,
and Failure-Driven Curriculum Synthesis (python_core/continual_learning.py).
"""

import sys
import unittest
import uuid
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

import continual_learning as cl  # noqa: E402
import memory_learning as ml  # noqa: E402
import zyrquen_core as zc  # noqa: E402
from tests.benchmark_suite import isolated_core_env  # noqa: E402


class ContinualLearningAndCurriculumTests(unittest.TestCase):
    def test_failure_driven_curriculum_synthesis_grounds_triples_and_blocks_leakage(self) -> None:
        with isolated_core_env():
            conn = zc.get_db()
            now = zc.now_iso()
            with conn:
                # Verified knowledge triple
                conn.execute(
                    """
                    INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), "QuasarCore", "รองรับ", "ContinualReplay", "verified-doc", 0.95, "u1", now),
                )
                # Leaked triple matching heldout prompt
                conn.execute(
                    """
                    INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), "HeldoutTopic", "คือ", "SecretEvalAnswer", "verified-doc", 0.95, "u1", now),
                )
                # Uncorroborated triple must NOT be curated
                conn.execute(
                    """
                    INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), "RumorNode", "เป็น", "FakeClaim", "uncorroborated_web", 0.4, "u1", now),
                )
                # Trace failures
                conn.execute(
                    """
                    INSERT INTO reasoning_traces (
                        id, user_id, prompt, response_preview, mode, model_version,
                        status, engine_path_json, trace_json, latency_ms, external_models_used, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), "u1", "QuasarCore ทำงานอย่างไร", "ยังไม่ได้เรียนรู้",
                        "auto", "zyrquen-omega-v1", "NOT_LEARNED", "[]", "{}", 2.5, 0, now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO reasoning_traces (
                        id, user_id, prompt, response_preview, mode, model_version,
                        status, engine_path_json, trace_json, latency_ms, external_models_used, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), "u1", "HeldoutTopic คืออะไร", "ยังไม่ได้เรียนรู้",
                        "auto", "zyrquen-omega-v1", "NOT_LEARNED", "[]", "{}", 2.1, 0, now,
                    ),
                )
                # Episodic failure with no verified triple grounding
                ml.record_episodic_experience(
                    conn,
                    mission_id="m-fail-1",
                    goal="RumorNode status check",
                    outcome_status="FAILED",
                    gap_type="execution_or_evidence_gap",
                    hypothesis={"detail": "missing verified source"},
                )

            res = cl.synthesize_failure_curriculum(
                conn,
                heldout_prompts=["HeldoutTopic คือ SecretEvalAnswer"],
                limit=20,
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["leakage_checked"])
            self.assertGreaterEqual(res["leaked_items_filtered"], 1)

            statements = [item["training_statement"] for item in res["curriculum_items"]]
            self.assertIn("QuasarCore รองรับ ContinualReplay", statements)
            self.assertNotIn("HeldoutTopic คือ SecretEvalAnswer", statements)
            self.assertFalse(any("RumorNode" in s for s in statements))
            self.assertGreaterEqual(res["unresolved_gaps_count"], 1)
            conn.close()

    def test_continual_learning_replay_consolidation_and_forgetting_gate(self) -> None:
        with isolated_core_env():
            conn = zc.get_db()
            anchor_lines = [
                "zyrquen ast ตรวจสอบสมการคณิตศาสตร์อย่างปลอดภัย",
                "zyrquen sqlite จัดเก็บกราฟความรู้แบบมีแหล่งอ้างอิง",
                "zyrquen ไม่เรียกใช้โมเดลภายนอกโดยเด็ดขาด",
                "zyrquen approval gate ป้องกันการเขียนทับ checkpoint",
            ]
            new_lines = [
                "curriculum replay ช่วยลด catastrophic forgetting ระหว่างรอบฝึก",
                "consolidation penalty ช่วยรักษาความจำเดิมของโมเดลเนทีฟ",
                "episodic trace failure ถูกสังเคราะห์เป็นข้อมูลฝึกที่ผ่านการตรวจแล้ว",
            ]

            res = cl.run_continual_learning_round(
                conn,
                zc.CHECKPOINT_DIR,
                "u-test",
                new_train_lines=new_lines,
                anchor_lines=anchor_lines,
                replay_ratio=0.5,
                anchor_l2_lambda=0.05,
                max_forgetting_loss_delta=0.6,
                max_forgetting_acc_drop=0.35,
                epochs=4,
                seed=7,
            )
            self.assertTrue(res["ok"])
            cm = res["continual_metrics"]
            self.assertEqual(cm["mode"], "continual_replay_consolidation")
            self.assertGreaterEqual(cm["replay_samples"], 2)
            self.assertGreaterEqual(cm["retention_rate"], 0.0)
            self.assertLessEqual(cm["retention_rate"], 1.0)
            self.assertIn("forgetting_loss_delta", cm)
            self.assertIn("param_drift_rms", cm)

            exp = res["experiment"]
            self.assertIn(exp["approval_status"], ("PENDING_APPROVAL", "REJECTED_NO_GAIN", "FORGETTING_FAILED"))

            # Verify overly strict threshold catches forgetting honestly
            strict_res = cl.run_continual_learning_round(
                conn,
                zc.CHECKPOINT_DIR,
                "u-test",
                new_train_lines=new_lines,
                anchor_lines=anchor_lines,
                replay_ratio=0.0,
                anchor_l2_lambda=0.0,
                max_forgetting_loss_delta=-10.0,
                max_forgetting_acc_drop=-1.0,
                epochs=2,
                seed=7,
            )
            self.assertTrue(strict_res["ok"])
            self.assertTrue(strict_res["catastrophic_forgetting_detected"])
            self.assertEqual(strict_res["experiment"]["approval_status"], "FORGETTING_FAILED")
            conn.close()


if __name__ == "__main__":
    unittest.main()
