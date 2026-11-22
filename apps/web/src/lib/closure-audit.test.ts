import { describe, expect, it } from "vitest";
import {
  computeV11ProgressMetrics,
  describeBlocker,
  labelForAuditStatus,
  toneForAuditStatus,
} from "./closure-audit";
import type { V10ClosureAudit } from "./types";

function makeAudit(overrides: Partial<V10ClosureAudit> = {}): V10ClosureAudit {
  return {
    schema: "zyrquen.v10.closure_audit.v1",
    checked_at: "2026-11-22T08:00:00Z",
    overall_status: "BLOCKED",
    static_status: "STATIC PASS",
    runtime_status: "BLOCKED",
    contracts_passed_count: 5,
    contracts_total: 5,
    v11_gate: {
      target_version: "V11",
      unlocked: false,
      status: "LOCKED",
      prerequisite_summary: "V11 remains LOCKED until V10-D runtime closure passes.",
    },
    runtime_environment: {
      torch_installed: false,
      native_runtime_status: "not_configured",
      native_model_loaded: false,
      is_trained: false,
      active_model_version: null,
      eval_report_configured: false,
      eval_report_status: null,
      registry_configured: false,
      verified_v10_models: 0,
      dataset_configured: false,
      tokenizer_configured: false,
    },
    blockers: ["TORCH_NOT_INSTALLED", "TRAINED_V10_MODEL_UNAVAILABLE"],
    contracts: [
      {
        id: "C1",
        code: "CONTRACT-1",
        title: "Model Architecture & 5M CPU Budget",
        stage: "V10-A",
        status: "STATIC PASS",
        anchor: "apps/core/native/config.py::ZyrquenConfig",
        summary: "zyrquen-decoder verified",
        checks: [],
      },
    ],
    stages: [
      {
        id: "V10-A",
        title: "Contracts 1-5",
        status: "STATIC PASS",
        summary: "5/5 static contracts verified",
        blockers: [],
      },
      {
        id: "V10-B",
        title: "Workflow & Governance",
        status: "IMPLEMENTED",
        summary: "Implemented",
        blockers: [],
      },
      {
        id: "V10-C",
        title: "Training Hook & CLI",
        status: "IMPLEMENTED",
        summary: "Implemented",
        blockers: ["TORCH_NOT_INSTALLED"],
      },
      {
        id: "V10-D",
        title: "Runtime Closure Gate",
        status: "BLOCKED",
        summary: "Blocked on torch",
        blockers: ["TORCH_NOT_INSTALLED"],
      },
    ],
    ...overrides,
  };
}

describe("closure-audit helpers", () => {
  it("maps statuses to accurate tones without conflating STATIC PASS with runtime PASS", () => {
    expect(toneForAuditStatus("PASS")).toBe("good");
    expect(toneForAuditStatus("READY")).toBe("good");
    expect(toneForAuditStatus("STATIC PASS")).toBe("info");
    expect(toneForAuditStatus("IMPLEMENTED")).toBe("info");
    expect(toneForAuditStatus("BLOCKED")).toBe("warn");
    expect(toneForAuditStatus("NOT RUN")).toBe("warn");
    expect(toneForAuditStatus("LOCKED")).toBe("warn");
    expect(toneForAuditStatus("FAILED")).toBe("bad");
    expect(labelForAuditStatus("STATIC PASS")).toBe("STATIC PASS");
    expect(labelForAuditStatus("PASS")).toContain("PASS");
  });

  it("computes honest V11 progress metrics and translates known blocker codes", () => {
    const blockedAudit = makeAudit();
    expect(computeV11ProgressMetrics(blockedAudit)).toEqual({
      contractsRatioPct: 100,
      stagesReadyCount: 3,
      stagesTotal: 4,
      isValidAuditPayload: true,
    });
    expect(describeBlocker("TORCH_NOT_INSTALLED")).toContain("PyTorch");
    expect(describeBlocker("UNKNOWN_CODE")).toBe("UNKNOWN_CODE");

    const partialAudit = makeAudit({ contracts_passed_count: 3, contracts_total: 5 });
    expect(computeV11ProgressMetrics(partialAudit).contractsRatioPct).toBe(60);
  });
});
