import type { ClosureAuditStatus, StatusTone, V10ClosureAudit } from "./types";

export function toneForAuditStatus(status: string | null | undefined): StatusTone {
  const normalized = (status ?? "").trim().toUpperCase();
  if (normalized === "PASS" || normalized === "READY") {
    return "good";
  }
  if (normalized === "STATIC PASS" || normalized === "IMPLEMENTED") {
    return "info";
  }
  if (normalized === "BLOCKED" || normalized === "NOT RUN" || normalized === "LOCKED") {
    return "warn";
  }
  if (normalized === "FAILED" || normalized === "FAIL") {
    return "bad";
  }
  return "neutral";
}

export function labelForAuditStatus(status: ClosureAuditStatus | string): string {
  switch (status) {
    case "PASS":
      return "PASS · ผ่านเกณฑ์จริง";
    case "STATIC PASS":
      return "STATIC PASS";
    case "IMPLEMENTED":
      return "IMPLEMENTED";
    case "BLOCKED":
      return "BLOCKED";
    case "NOT RUN":
      return "NOT RUN";
    case "FAILED":
      return "FAILED";
    default:
      return status;
  }
}

const BLOCKER_DESCRIPTIONS: Record<string, string> = {
  TORCH_NOT_INSTALLED: "ไม่พบ PyTorch (torch) ในสภาพแวดล้อมรันไทม์ปัจจุบัน",
  DATASET_DIR_NOT_CONFIGURED: "ยังไม่ได้กำหนด ZYRQUEN_DATASET_DIR",
  TOKENIZER_NOT_CONFIGURED: "ยังไม่ได้กำหนด ZYRQUEN_TOKENIZER_PATH",
  EVAL_REPORT_NOT_CONFIGURED: "ยังไม่ได้กำหนด ZYRQUEN_EVAL_REPORT_PATH ของ V10",
  EVAL_REPORT_INVALID_PATH: "พาธรายงานประเมินผลไม่ถูกต้องหรือเป็น symlink",
  EVAL_REPORT_UNREADABLE: "ไม่สามารถอ่านไฟล์รายงานประเมินผล V10 ได้",
  EVAL_REPORT_INVALID_SCHEMA: "รูปแบบไฟล์รายงานประเมินผลไม่ถูกต้อง",
  EVAL_REPORT_SCHEMA_MISMATCH: "Schema ของรายงานไม่ตรงกับ zyrquen.v10.evaluation_report.v1",
  EVAL_INFERENCE_BLOCKED: "ขั้นตอน Inference ในรายงานประเมินผลถูกบล็อก (BLOCKED)",
  EVAL_REGRESSION_FAILED: "ตรวจพบการถดถอย (Regression) เทียบกับ Baseline",
  EVAL_FAILED: "ผลการประเมิน V10 ไม่ผ่านเกณฑ์ (FAILED)",
  EVAL_NOT_PASSED: "รายงานประเมินผลยังไม่ผ่านสถานะ PASS",
  MODEL_REGISTRY_NOT_CONFIGURED: "ยังไม่ได้กำหนด ZYRQUEN_MODEL_REGISTRY_ROOT",
  MODEL_REGISTRY_UNAVAILABLE: "ไม่พบไดเรกทอรี Model Registry",
  MODEL_REGISTRY_UNREADABLE: "ไม่สามารถอ่านข้อมูล Model Registry ได้",
  TRAINED_V10_MODEL_UNAVAILABLE: "ยังไม่มีโมเดล V10 ที่ผ่านการฝึกและการตรวจสอบ Registry จริง",
};

export function describeBlocker(code: string): string {
  return BLOCKER_DESCRIPTIONS[code] ?? code;
}

export function computeV11ProgressMetrics(audit: V10ClosureAudit): {
  contractsRatioPct: number;
  stagesReadyCount: number;
  stagesTotal: number;
  isValidAuditPayload: boolean;
} {
  const total = audit.contracts_total > 0 ? audit.contracts_total : audit.contracts.length;
  const passed = Math.min(total, Math.max(0, audit.contracts_passed_count));
  const contractsRatioPct = total > 0 ? Math.round((passed / total) * 100) : 0;

  const stagesTotal = audit.stages.length;
  const stagesReadyCount = audit.stages.filter(
    (stage) =>
      stage.status === "PASS" ||
      stage.status === "STATIC PASS" ||
      stage.status === "IMPLEMENTED",
  ).length;

  const isValidAuditPayload =
    audit.schema === "zyrquen.v10.closure_audit.v1" &&
    Array.isArray(audit.contracts) &&
    Array.isArray(audit.stages);

  return {
    contractsRatioPct,
    stagesReadyCount,
    stagesTotal,
    isValidAuditPayload,
  };
}
