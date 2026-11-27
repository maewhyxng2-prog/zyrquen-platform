import { describe, expect, it } from "vitest";
import {
  computeRunDurationMs,
  computeRunProgress,
  extractRunMetrics,
  filterWorkflowDefinitions,
  filterWorkflowRuns,
  formatDuration,
  formatLoss,
  isWorkflowRunActive,
  selectLatestCompletedKpi,
  type WorkflowRunItem,
} from "./workflow-metrics";

function makeRun(overrides: Partial<WorkflowRunItem> = {}): WorkflowRunItem {
  return {
    id: "run-1",
    workflow_key: "training.native_controlled_run",
    workflow_version: "1.0.0",
    trigger_type: "manual",
    status: "COMPLETED",
    created_at: "2026-11-22T10:00:00Z",
    started_at: "2026-11-22T10:00:00Z",
    finished_at: "2026-11-22T10:00:45Z",
    steps: [],
    ...overrides,
  };
}

describe("computeRunProgress", () => {
  it("computes real step-level progress for waiting and running workflows", () => {
    const waitingApproval = makeRun({
      status: "WAITING_APPROVAL",
      steps: [
        { step_key: "preflight", status: "COMPLETED", lane: "control_ops" },
        { step_key: "execute_training", status: "WAITING_APPROVAL", lane: "compute_heavy" },
      ],
    });
    expect(computeRunProgress(waitingApproval)).toEqual({
      percent: 50,
      completedSteps: 1,
      totalSteps: 2,
      activeStepKey: "execute_training",
      activeStepStatus: "WAITING_APPROVAL",
      tone: "warn",
    });

    const runningWithStepTelemetry = makeRun({
      status: "RUNNING",
      steps: [
        { step_key: "preflight", status: "COMPLETED", lane: "control_ops" },
        {
          step_key: "execute_training",
          status: "RUNNING",
          lane: "compute_heavy",
          output: { current_step: 40, max_steps: 100 },
        },
      ],
    });
    expect(computeRunProgress(runningWithStepTelemetry)).toEqual({
      percent: 70,
      completedSteps: 1,
      totalSteps: 2,
      activeStepKey: "execute_training",
      activeStepStatus: "RUNNING",
      tone: "info",
    });

    const verifyingRun = makeRun({
      status: "VERIFYING",
      steps: [
        { step_key: "check_health", status: "COMPLETED", lane: "control_ops" },
        { step_key: "daily_report", status: "COMPLETED", lane: "control_ops" },
      ],
    });
    expect(computeRunProgress(verifyingRun).percent).toBe(95);
    expect(isWorkflowRunActive("VERIFYING")).toBe(true);
    expect(isWorkflowRunActive("COMPLETED")).toBe(false);
  });
});

describe("extractRunMetrics & selectLatestCompletedKpi", () => {
  it("extracts metrics from structured output or legacy summary strings without inventing epochs", () => {
    const legacyRun = makeRun({
      id: "run-old",
      started_at: "2026-11-22T09:00:00Z",
      finished_at: "2026-11-22T09:01:00Z",
      steps: [
        { step_key: "preflight", status: "COMPLETED", lane: "control_ops" },
        {
          step_key: "execute_training",
          status: "COMPLETED",
          lane: "compute_heavy",
          evidence: {
            verdict: "PASS",
            summary: "Training completed: steps=100 val_loss=2.4500 perplexity=11.59 ram_peak_gb=0.42",
          },
        },
      ],
    });

    const newerRun = makeRun({
      id: "run-new",
      started_at: "2026-11-22T10:00:00Z",
      finished_at: "2026-11-22T10:00:40Z",
      steps: [
        { step_key: "preflight", status: "COMPLETED", lane: "control_ops" },
        {
          step_key: "execute_training",
          status: "COMPLETED",
          lane: "compute_heavy",
          output: {
            steps: 200,
            epochs: null,
            train_loss: 1.92,
            val_loss: 2.1,
            perplexity: 8.17,
            ram_peak_gb: 0.48,
          },
        },
      ],
    });

    const kpi = selectLatestCompletedKpi([legacyRun, newerRun]);
    expect(kpi).not.toBeNull();
    expect(kpi?.latestRun.id).toBe("run-new");
    expect(kpi?.latestMetrics.epochs).toBeNull();
    expect(kpi?.latestMetrics.steps).toBe(200);
    expect(kpi?.latestMetrics.latestLoss).toBe(2.1);
    expect(kpi?.latestMetrics.latestLossKind).toBe("val_loss");
    expect(kpi?.durationMs).toBe(40_000);
    expect(kpi?.lossDelta).toBeCloseTo(-0.35, 6);
    expect(kpi?.durationDeltaMs).toBe(-20_000);
    expect(formatDuration(kpi?.durationMs ?? null)).toBe("40.0s");
    expect(formatLoss(kpi?.latestMetrics.latestLoss ?? null)).toBe("2.1000");
  });

  it("prefers completed training runs over later system checks and returns null when none completed", () => {
    const failedRun = makeRun({ id: "failed", status: "FAILED" });
    expect(selectLatestCompletedKpi([failedRun])).toBeNull();

    const trainingRun = makeRun({
      id: "train-1",
      finished_at: "2026-11-22T09:30:00Z",
      steps: [
        {
          step_key: "execute_training",
          status: "COMPLETED",
          lane: "compute_heavy",
          output: { epochs: 3, steps: 300, val_loss: 1.75 },
        },
      ],
    });
    const sysCheck = makeRun({
      id: "sys-1",
      workflow_key: "system_ops.health_check",
      finished_at: "2026-11-22T10:30:00Z",
      steps: [{ step_key: "check_health", status: "COMPLETED", lane: "control_ops" }],
    });

    const summary = selectLatestCompletedKpi([sysCheck, trainingRun]);
    expect(summary?.latestRun.id).toBe("train-1");
    expect(summary?.latestMetrics.epochs).toBe(3);
    expect(extractRunMetrics(sysCheck).hasTrainingMetrics).toBe(false);
    expect(computeRunDurationMs(makeRun({ finished_at: null }))).toBeNull();
  });
});

describe("WorkflowConsole Tier-2 approval filtering", () => {
  it("switches cleanly between All Workflows and Only Pending Tier-2 Approvals", () => {
    const waitingRun = makeRun({
      id: "run-wait",
      workflow_key: "training.native_controlled_run",
      status: "WAITING_APPROVAL",
      steps: [{ step_key: "approve", status: "WAITING_APPROVAL", lane: "governance" }],
    });
    const completedRun = makeRun({
      id: "run-done",
      workflow_key: "system_ops.health_check",
      status: "COMPLETED",
    });
    const approvalLinkedRun = makeRun({
      id: "run-linked",
      workflow_key: "project_dev.maintainer_pr",
      status: "PENDING",
    });

    const pendingRunIds = new Set(["run-wait", "run-linked"]);
    const allRuns = [waitingRun, completedRun, approvalLinkedRun];

    expect(filterWorkflowRuns(allRuns, "all", pendingRunIds).map((r) => r.id)).toEqual([
      "run-wait",
      "run-done",
      "run-linked",
    ]);
    expect(
      filterWorkflowRuns(allRuns, "pending_tier2", pendingRunIds).map((r) => r.id),
    ).toEqual(["run-wait", "run-linked"]);

    const definitions = [
      { workflow_key: "training.native_controlled_run" },
      { workflow_key: "system_ops.health_check" },
      { workflow_key: "project_dev.maintainer_pr" },
    ];
    const pendingWorkflowKeys = new Set([
      "training.native_controlled_run",
      "project_dev.maintainer_pr",
    ]);

    expect(
      filterWorkflowDefinitions(definitions, "all", pendingWorkflowKeys).map(
        (d) => d.workflow_key,
      ),
    ).toEqual([
      "training.native_controlled_run",
      "system_ops.health_check",
      "project_dev.maintainer_pr",
    ]);
    expect(
      filterWorkflowDefinitions(
        definitions,
        "pending_tier2",
        pendingWorkflowKeys,
      ).map((d) => d.workflow_key),
    ).toEqual(["training.native_controlled_run", "project_dev.maintainer_pr"]);
  });
});
