"""Integrity tests for ZYRQUEN checkpoint promotion, held-out evaluation, and inference guards."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

import continual_learning as cl  # noqa: E402
import memory_learning as ml  # noqa: E402
import real_only_trainer as rot  # noqa: E402
import zyrquen_core as zc  # noqa: E402
from tests.benchmark_suite import isolated_core_env  # noqa: E402


def _write_real_ast_jsonl(path: Path, count_per_class: int = 24) -> None:
    lines: list[str] = []
    for idx in range(count_per_class):
        code = (
            f"def guarded_op_{idx}(x, y):\n"
            f"    if y == 0:\n"
            f"        return 0\n"
            f"    try:\n"
            f"        return x / (y + {idx})\n"
            f"    except ZeroDivisionError:\n"
            f"        return 0\n"
        )
        lines.append(json.dumps({"code": code, "label": 1, "source": "internal_ast_verified"}))
    for idx in range(count_per_class):
        code = f"raw_val_{idx} = {idx + 1} * 2 + {idx % 5}\n"
        lines.append(json.dumps({"code": code, "label": 0, "source": "internal_ast_verified"}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class LearningAndEvalIntegrityTests(unittest.TestCase):
    def test_decide_experiment_rejects_empty_and_tampered_paths(self) -> None:
        with isolated_core_env():
            conn = zc.get_db()
            exp_id = "exp-empty-path-1"
            with conn:
                conn.execute(
                    """
                    INSERT INTO experiments (
                        id, hypothesis, dataset_id, baseline_ckpt_id, candidate_ckpt_id,
                        baseline_metrics_json, candidate_metrics_json, improved,
                        approval_status, approved_by, created_by, created_at
                    )
                    VALUES (?, ?, ?, NULL, NULL, '{}', '{}', 1, 'PENDING_APPROVAL', NULL, 'u1', '2026-11-27T00:00:00Z')
                    """,
                    (exp_id, "Empty path test", "real-only:empty"),
                )
            res = ml.decide_experiment(
                conn,
                zc.CHECKPOINT_DIR,
                experiment_id=exp_id,
                decision="approve",
                admin_email="admin@zyrquen.local",
                admin_id="admin-1",
            )
            self.assertFalse(res["ok"])
            self.assertIn("missing", res["error"].lower())

            with tempfile.TemporaryDirectory() as tmp:
                jsonl_path = Path(tmp) / "real.jsonl"
                _write_real_ast_jsonl(jsonl_path, count_per_class=22)
                rec = rot.record_real_only_training_in_db(
                    conn,
                    checkpoint_dir=zc.CHECKPOINT_DIR,
                    user_id="u1",
                    data_path=jsonl_path,
                    epochs=12,
                    lr=0.1,
                    seed=7,
                    min_samples=30,
                )
                self.assertTrue(rec["ok"], rec)
                if rec["approval"] == "PENDING_APPROVAL":
                    ckpt_file = Path(rec["checkpoint_path"])
                    ckpt_obj = json.loads(ckpt_file.read_text(encoding="utf-8"))
                    ckpt_obj["bias"] = float(ckpt_obj["bias"]) + 9.5
                    ckpt_file.write_text(json.dumps(ckpt_obj), encoding="utf-8")

                    tamper_res = ml.decide_experiment(
                        conn,
                        zc.CHECKPOINT_DIR,
                        experiment_id=rec["experiment_id"],
                        decision="approve",
                        admin_email="admin@zyrquen.local",
                        admin_id="admin-1",
                    )
                    self.assertFalse(tamper_res["ok"])
                    self.assertIn("SHA-256", tamper_res["error"])
            conn.close()

    def test_ast_promotion_evaluation_and_missing_weights_fail_closed(self) -> None:
        with isolated_core_env():
            conn = zc.get_db()
            with tempfile.TemporaryDirectory() as tmp:
                jsonl_path = Path(tmp) / "real.jsonl"
                _write_real_ast_jsonl(jsonl_path, count_per_class=24)
                rec = rot.record_real_only_training_in_db(
                    conn,
                    checkpoint_dir=zc.CHECKPOINT_DIR,
                    user_id="u1",
                    data_path=jsonl_path,
                    epochs=15,
                    lr=0.1,
                    seed=11,
                    min_samples=30,
                )
                self.assertTrue(rec["ok"], rec)
                self.assertEqual(rec["approval"], "PENDING_APPROVAL", rec)

                promo = ml.decide_experiment(
                    conn,
                    zc.CHECKPOINT_DIR,
                    experiment_id=rec["experiment_id"],
                    decision="approve",
                    admin_email="admin@zyrquen.local",
                    admin_id="admin-1",
                )
                self.assertTrue(promo["ok"], promo)
                ckpt = promo["checkpoint"]
                self.assertEqual(ckpt["eval_status"], "AST_VERIFIED")
                self.assertEqual(ckpt["ngram_order"], -1)
                self.assertTrue(Path(ckpt["weights_path"]).is_file())

            # Evaluation verifies AST checkpoint via SHA-256 + report
            ev_ok = zc.handle_run_evaluation({"user_id": "u1", "suite_name": "AST Eval"})
            self.assertTrue(ev_ok["ok"])
            ev_row = ev_ok["evaluation"]
            details = json.loads(ev_row["details_json"])
            self.assertEqual(details["heldout_test"]["status"], "PASS")
            self.assertIsNotNone(ev_row["test_accuracy"])

            # Inference cleanly ignores AST .json checkpoint rather than crashing in NativeTransformerLM
            infer_res = zc.handle_infer({"prompt": "ทดสอบโครงสร้างระบบ", "mode": "model", "user_id": "u1"})
            self.assertNotEqual(infer_res.get("status"), "ERROR")

            # Tampering checkpoint post-promotion MUST fail evaluation cleanly (never cached WARN)
            promoted_path = Path(ckpt["weights_path"])
            promoted_path.write_text('{"schema":"corrupted"}', encoding="utf-8")
            ev_tamper = zc.handle_run_evaluation({"user_id": "u1", "suite_name": "Tampered AST Eval"})["evaluation"]
            tamper_details = json.loads(ev_tamper["details_json"])
            self.assertEqual(tamper_details["heldout_test"]["status"], "FAILED")
            self.assertEqual(ev_tamper["overall_status"], "FAILED")
            self.assertIsNone(ev_tamper["test_accuracy"])
            self.assertIsNone(ev_tamper["perplexity"])

            # Removing checkpoint file on disk MUST block evaluation honestly (never cached WARN)
            promoted_path.unlink()
            ev_missing = zc.handle_run_evaluation({"user_id": "u1", "suite_name": "Missing AST Eval"})["evaluation"]
            missing_details = json.loads(ev_missing["details_json"])
            self.assertEqual(missing_details["heldout_test"]["status"], "BLOCKED")
            self.assertEqual(ev_missing["overall_status"], "BLOCKED")
            self.assertIsNone(ev_missing["test_accuracy"])
            self.assertIsNone(ev_missing["perplexity"])
            conn.close()

    def test_continual_promotion_sets_neural_continual_verified(self) -> None:
        distinct_corpus = [
            "ตัวแปลงข้อความระดับไบต์สร้างโทเคนย่อยอย่างมีประสิทธิภาพโดยไม่พึ่งพาพจนานุกรมภายนอก",
            "เครื่องมือแยกวิเคราะห์โครงสร้างไวยากรณ์ตรวจสอบลำดับนิพจน์ทางคณิตศาสตร์ได้อย่างถูกต้อง",
            "ฐานข้อมูลเชิงสัมพันธ์จัดเก็บตารางเหตุการณ์และดัชนีสืบค้นแบบธุรกรรมปลอดภัย",
            "กลไกควบคุมเวอร์ชันบันทึกประวัติการแก้ไขไฟล์และคำนวณความแตกต่างเชิงบรรทัด",
            "ระบบกักกันการประมวลผลจำกัดหน่วยความจำและปิดกั้นการเชื่อมต่อเครือข่ายภายนอก",
            "โมดูลตรวจสอบความถูกต้องของข้อมูลคัดกรองรายการซ้ำซ้อนก่อนส่งเข้าสู่ขั้นตอนถัดไป",
            "ส่วนประสานงานเวิร์กโฟลว์จัดเรียงลำดับงานตามกราฟความสัมพันธ์แบบไม่มีวงวน",
            "ชุดทดสอบอัตโนมัติจำลองสถานการณ์ผิดพลาดเพื่อตรวจจับข้อบกพร่องด้านการหารด้วยศูนย์",
            "คลังความรู้เชื่อมโยงความสัมพันธ์เชิงสาเหตุพร้อมบันทึกหลักฐานอ้างอิงที่ตรวจสอบได้",
            "ระบบจัดการทรัพยากรเฝ้าดูภาระซีพียูและพื้นที่จัดเก็บคงเหลือก่อนอนุมัติงานใหม่",
            "ขั้นตอนการปรับเทียบน้ำหนักใช้การสะสมเกรเดียนต์ร่วมกับการลดอัตราการเรียนรู้แบบโคไซน์",
            "เกตตรวจสอบคุณภาพปฏิเสธการส่งมอบงานเมื่อคำสั่งคอมไพล์หรือทดสอบยูนิตไม่ผ่าน",
            "อัลกอริทึมค้นหาเส้นทางกราฟเลือกโหนดเป้าหมายที่มีความคล้ายคลึงของสัญลักษณ์สูงสุด",
            "สถาปัตยกรรมความจำระยะสั้นจัดเก็บเหตุการณ์ล้มเหลวเพื่อสร้างแบบฝึกหัดซ่อมแซมจุดอ่อน",
            "เครื่องตรวจจับข้อมูลรั่วไหลเปรียบเทียบแฮชเชิงความหมายระหว่างชุดฝึกกับชุดประเมินผล",
            "ชั้นความสนใจแบบหลายหัวคำนวณน้ำหนักบริบทของลำดับโทเคนในหน้าต่างขนาดคงที่",
            "ระบบสำรองสถานะไฟล์สร้างจุดย้อนกลับอัตโนมัติก่อนเริ่มปรับปรุงโมดูลซอฟต์แวร์",
            "ตัวตรวจสอบสิทธิ์บังคับใช้บทบาทผู้ดูแลระบบก่อนเลื่อนขั้นน้ำหนักโมเดลรุ่นใหม่",
        ]
        distinct_new = [
            "แพ็กเกจตัวสร้างแอปพลิเคชันจัดโครงสร้างซอร์สโค้ดหลายไฟล์พร้อมชุดทดสอบมาตรฐาน",
            "โปรแกรมคอมไพล์ตรวจสอบความถูกต้องของไวยากรณ์ไพทอนและโครงร่างเจสันในห้องทดลอง",
            "กลไกซ่อมแซมอัตโนมัติวิเคราะห์ข้อความแสดงข้อผิดพลาดเพื่อสร้างแพตช์ที่ปลอดภัย",
            "ตัวจัดการประวัติบันทึกความแตกต่างระหว่างรุ่นและย้อนคืนสถานะเดิมเมื่อเกิดปัญหา",
            "ขั้นตอนตรวจประเมินผลวัดอัตราการผ่านจริงบนกรณีทดสอบที่ไม่เคยปรากฏระหว่างฝึก",
            "สายท่อประมวลผลตรวจสอบความครบถ้วนของข้อกำหนดส่วนติดต่อโปรแกรมประยุกต์ทุกเส้นทาง",
        ]
        distinct_anchor = [
            "ฟังก์ชันคำนวณค่าเฉลี่ยต้องป้องกันกรณีรายการข้อมูลว่างเปล่าก่อนดำเนินการหารเสมอ",
            "โครงสร้างข้อมูลบันทึกหลักฐานรหัสแฮชแบบถาวรเพื่อรองรับการตรวจย้อนหลังครบวงจร",
            "ระบบรักษาความปลอดภัยสแกนหาข้อมูลลับและป้องกันการเข้าถึงโฟลเดอร์นอกขอบเขต",
            "หน้าต่างบริบทเก็บเฉพาะข้อมูลอ้างอิงที่ยืนยันแหล่งที่มาและไม่มีความขัดแย้งกัน",
            "ตัวจัดตารางเวลาแยกงานอัตโนมัติที่ได้รับสิทธิ์ออกจากคำสั่งที่ต้องรออนุมัติพิเศษ",
        ]
        with isolated_core_env():
            conn = zc.get_db()
            ing = zc.handle_ingest_dataset(
                {
                    "name": "continual-base-corpus",
                    "user_id": "u1",
                    "source": "internal_test_corpus",
                    "content": "\n".join(distinct_corpus),
                }
            )
            self.assertTrue(ing["ok"], ing)
            self.assertEqual(ing["dataset"]["leakage_detected"], 0, ing)
            ds_id = ing["dataset"]["id"]

            exp = ml.run_controlled_neural_experiment(
                conn,
                zc.CHECKPOINT_DIR,
                "u1",
                dataset_id=ds_id,
                epochs=4,
                seed=42,
            )
            self.assertTrue(exp["ok"], exp)
            if exp["experiment"]["approval_status"] == "PENDING_APPROVAL":
                p1 = ml.decide_experiment(
                    conn,
                    zc.CHECKPOINT_DIR,
                    experiment_id=exp["experiment"]["id"],
                    decision="approve",
                    admin_email="admin@zyrquen.local",
                    admin_id="admin-1",
                )
                self.assertTrue(p1["ok"], p1)

            cl_res = cl.run_continual_learning_round(
                conn,
                zc.CHECKPOINT_DIR,
                "u1",
                new_train_lines=distinct_new,
                anchor_lines=distinct_anchor,
                epochs=4,
                seed=43,
            )
            self.assertTrue(cl_res["ok"], cl_res)
            if cl_res["experiment"]["approval_status"] == "PENDING_APPROVAL":
                p2 = ml.decide_experiment(
                    conn,
                    zc.CHECKPOINT_DIR,
                    experiment_id=cl_res["experiment"]["id"],
                    decision="approve",
                    admin_email="admin@zyrquen.local",
                    admin_id="admin-1",
                )
                self.assertTrue(p2["ok"], p2)
                self.assertEqual(p2["checkpoint"]["eval_status"], "NEURAL_CONTINUAL_VERIFIED")
                # Evaluates genuinely against clean dataset split
                ev = zc.handle_run_evaluation({"user_id": "u1", "suite_name": "Continual Eval"})["evaluation"]
                details = json.loads(ev["details_json"])
                self.assertEqual(details["heldout_test"]["status"], "PASS")
                self.assertIsNotNone(ev["test_accuracy"])
            conn.close()

    def test_template_leakage_and_overlap_strictly_blocked(self) -> None:
        with isolated_core_env():
            conn = zc.get_db()
            # 1. Templated lines must be flagged with leakage_detected == 1 and blocked from experiment training
            templated = [
                f"สถาปัตยกรรมโครงข่ายโมดูลหมายเลข {i} ใช้หน่วยความจำอ้างอิงคู่ที่ {i + 1} และทดสอบสมรรถนะ"
                for i in range(18)
            ]
            ing = zc.handle_ingest_dataset(
                {
                    "name": "templated-leaky-corpus",
                    "user_id": "u1",
                    "source": "internal_test_corpus",
                    "content": "\n".join(templated),
                }
            )
            self.assertTrue(ing["ok"], ing)
            self.assertEqual(ing["dataset"]["leakage_detected"], 1)
            blocked_exp = ml.run_controlled_neural_experiment(
                conn,
                zc.CHECKPOINT_DIR,
                "u1",
                dataset_id=ing["dataset"]["id"],
                epochs=2,
                seed=42,
            )
            self.assertFalse(blocked_exp["ok"])
            self.assertIn("Data Leakage", blocked_exp["error"])

            # 2. Continual learning MUST reject overlapping new_train_lines and anchor_lines
            overlap_res = cl.run_continual_learning_round(
                conn,
                zc.CHECKPOINT_DIR,
                "u1",
                new_train_lines=[
                    "ชุดข้อมูลใหม่สำหรับทดสอบการป้องกันการรั่วไหลข้ามชุดข้อมูลฝึก",
                    "ตัวประมวลผลแบบจำลองภาษาสร้างลำดับโทเคนจากการกระจายความน่าจะเป็น",
                ],
                anchor_lines=[
                    "ชุดข้อมูลใหม่สำหรับทดสอบการป้องกันการรั่วไหลข้ามชุดข้อมูลฝึก",
                    "ระบบจัดการฐานข้อมูลตรวจสอบความสอดคล้องของธุรกรรมก่อนบันทึก",
                ],
                epochs=2,
                seed=42,
            )
            self.assertFalse(overlap_res["ok"])
            self.assertIn("Leakage", overlap_res["error"])

            # 3. evaluate_checkpoint_heldout MUST fail-closed if linked dataset has leakage_detected=1
            fake_ckpt = {"id": "ckpt-leak", "weights_path": str(zc.CHECKPOINT_DIR / "missing.json.gz"), "eval_status": "NEURAL_VERIFIED", "dataset_id": ing["dataset"]["id"], "ngram_order": 0}
            fake_w = zc.CHECKPOINT_DIR / "ckpt_leak_check.json.gz"
            import native_neural as nn
            import native_tokenizer as nt
            tok = nt.NativeBPETokenizer()
            tok.train(["alpha beta gamma delta", "epsilon zeta eta theta"], target_vocab_size=64)
            mod = nn.NativeTransformerLM(vocab_size=tok.vocab_size, d_model=16, n_heads=2, n_layers=1, d_ff=32, max_seq_len=16, seed=1)
            mod.save_checkpoint(fake_w, tok, metrics={})
            fake_ckpt["weights_path"] = str(fake_w)
            ev_blocked = zc.evaluate_checkpoint_heldout(conn, fake_ckpt)  # type: ignore[arg-type]
            self.assertFalse(ev_blocked["ok"])
            self.assertEqual(ev_blocked["status"], "FAILED")
            conn.close()


if __name__ == "__main__":
    unittest.main()
