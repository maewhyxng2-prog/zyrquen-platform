import { describe, expect, it } from "vitest";
import {
  buildWorkflowLogsQuery,
  deriveLogsFromRuns,
  filterWorkflowLogs,
  isActiveOrchestrationStatus,
  logLevelForStatus,
} from "./workflow-logs";
import type { WorkflowExecutionLogItem } from "./types";
import type { WorkflowRunItem } from "./workflow-metrics";

describe("workflow-logs helpers", () => {
  it("detects active orchestration statuses accurately", () => {
    expect(isActiveOrchestrationStatus("PENDING")).toBe(true);
    expect(isActiveOrchestrationStatus("RUNNING")).toBe(true);
    expect(isActiveOrchestrationStatus("VERIFYING")).toBe(true);
    expect(isActiveOrchestrationStatus("WAITING_APPROVAL")).toBe(true);
    expect(isActiveOrchestrationStatus("WAITING_RESOURCE")).toBe(true);
    expect(isActiveOrchestrationStatus("COMPLETED")).toBe(false);
    expect(isActiveOrchestrationStatus("FAILED")).toBe(false);
    expect(isActiveOrchestrationStatus("CANCELLED")).toBe(false);
  });

  it("maps statuses and verdicts to log levels", () => {
    expect(logLevelForStatus("COMPLETED", "PASS")).toBe("INFO");
    expect(logLevelForStatus("WAITING_APPROVAL")).toBe("WARN");
    expect(logLevelForStatus("BLOCKED")).toBe("WARN");
    expect(logLevelForStatus("FAILED", "FAIL")).toBe("ERROR");
    expect(logLevelForStatus("COMPLETED", "DENY")).toBe("ERROR");
  });

  it("builds bounded query strings", () => {
    expect(buildWorkflowLogsQuery({ activeOnly: true, limit: 120 })).toBe(
      "active_only=true&limit=120",
    );
    expect(
      buildWorkflowLogsQuery({ activeOnly: false, runId: "run-42", limit: 999 }),
    ).toBe("active_only=false&run_id=run-42&limit=500");
  });

  it("filters log entries by level and search text", () => {
    const items: WorkflowExecutionLogItem[] = [
      {
        id: "1",
        run_id: "run-abc",
        workflow_key: "training.native_controlled_run",
        step_key: "preflight",
        level: "INFO",
        event_type: "step.completed",
        status: "COMPLETED",
        message: "Preflight budget check passed",
        timestamp: "2026-11-27T01:00:00Z",
      },
      {
        id: "2",
        run_id: "run-abc",
        workflow_key: "training.native_controlled_run",
        step_key: "execute_training",
        level: "WARN",
        event_type: "step.waiting_approval",
        status: "WAITING_APPROVAL",
        message: "Awaiting Tier-2 human approval",
        timestamp: "2026-11-27T01:00:05Z",
      },
      {
        id: "3",
        run_id: "run-xyz",
        workflow_key: "evaluation.model_verification",
        step_key: "verify",
        level: "ERROR",
        event_type: "step.failed",
        status: "FAILED",
        message: "Checkpoint SHA mismatch",
        timestamp: "2026-11-27T01:00:10Z",
      },
    ];

    expect(filterWorkflowLogs(items, { level: "WARN" })).toHaveLength(1);
    expect(filterWorkflowLogs(items, { search: "tier-2" })).toHaveLength(1);
    expect(filterWorkflowLogs(items, { level: "ERROR", search: "sha" })).toHaveLength(1);
    expect(filterWorkflowLogs(items, { level: "INFO", search: "sha" })).toHaveLength(0);
  });

  it("derives honest logs from active runs without fabricating entries", () => {
    const runs: WorkflowRunItem[] = [
      {
        id: "run-active-1",
        workflow_key: "training.native_controlled_run",
        workflow_version: "1.0.0",
        trigger_type: "manual",
        status: "WAITING_APPROVAL",
        created_at: "2026-11-27T01:00:00Z",
        started_at: "2026-11-27T01:00:01Z",
        steps: [
          {
            step_key: "preflight",
            status: "COMPLETED",
            lane: "cpu",
            attempt: 1,
            started_at: "2026-11-27T01:00:01Z",
            finished_at: "2026-11-27T01:00:02Z",
            evidence: { verdict: "PASS", summary: "Preflight budget check passed" },
          },
          {
            step_key: "execute_training",
            status: "WAITING_APPROVAL",
            lane: "gpu",
            attempt: 0,
          },
        ],
      },
      {
        id: "run-done-2",
        workflow_key: "system_ops.health_check",
        workflow_version: "1.0.0",
        trigger_type: "scheduled",
        status: "COMPLETED",
        created_at: "2026-11-27T00:50:00Z",
        finished_at: "2026-11-27T00:50:05Z",
        steps: [],
      },
    ];

    const activePayload = deriveLogsFromRuns(runs, { activeOnly: true });
    expect(activePayload.active_runs).toHaveLength(1);
    expect(activePayload.active_runs[0].id).toBe("run-active-1");
    expect(activePayload.items.every((item) => item.run_id === "run-active-1")).toBe(true);
    expect(activePayload.items.some((item) => item.level === "WARN")).toBe(true);

    const emptyActive = deriveLogsFromRuns([runs[1]], { activeOnly: true });
    expect(emptyActive.active_runs).toHaveLength(0);
    expect(emptyActive.items).toHaveLength(0);
  });
});
