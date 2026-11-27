import { describe, expect, it } from "vitest";
import { handleInMemoryBackendRequest } from "./in-memory-backend";
import {
  buildWorkflowLogsQuery,
  collectSelectableWorkflowRuns,
  deriveLogsFromRuns,
  filterWorkflowLogs,
  filterWorkflowRunsByOwnership,
  isActiveOrchestrationStatus,
  isValidWorkflowRunId,
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

  it("validates safe workflow run identifiers", () => {
    expect(isValidWorkflowRunId("run-abc_123:01")).toBe(true);
    expect(isValidWorkflowRunId("123e4567-e89b-42d3-a456-426614174000")).toBe(true);
    expect(isValidWorkflowRunId("../secret")).toBe(false);
    expect(isValidWorkflowRunId("run/nested")).toBe(false);
    expect(isValidWorkflowRunId("bad run id")).toBe(false);
    expect(isValidWorkflowRunId("")).toBe(false);
    expect(isValidWorkflowRunId(null)).toBe(false);
  });

  it("enforces workflow run ownership filtering for non-admins", () => {
    const runs = [
      { id: "r1", requested_by_user_id: "u-alice" },
      { id: "r2", requested_by_user_id: "u-bob" },
    ];
    expect(
      filterWorkflowRunsByOwnership(runs, { id: "u-alice", role: "user" }).map((r) => r.id),
    ).toEqual(["r1"]);
    expect(
      filterWorkflowRunsByOwnership(runs, { id: "u-admin", role: "admin" }).map((r) => r.id),
    ).toEqual(["r1", "r2"]);
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

    const allLogs = deriveLogsFromRuns(runs, { activeOnly: false });
    const selectable = collectSelectableWorkflowRuns(allLogs.active_runs, allLogs.items);
    expect(selectable.map((r) => r.id)).toContain("run-active-1");
    expect(selectable.map((r) => r.id)).toContain("run-done-2");
  });

  it("enforces authentication, ownership isolation, and run_id scoping on /v1/workflows/logs", async () => {
    // 1. Unauthenticated request returns 401
    const unauth = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/logs",
      authorizationHeader: null,
    });
    expect(unauth.status).toBe(401);

    // 2. Login as seeded admin and trigger an active run
    const adminLogin = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/login",
      authorizationHeader: null,
      rawBody: JSON.stringify({
        email: "demo@zyrquen.local",
        password: "zyrquen-demo-pass",
      }),
    });
    expect(adminLogin.status).toBe(200);
    const adminToken = (adminLogin.body as { access_token: string }).access_token;
    const adminHeaders = `Bearer ${adminToken}`;

    const adminRunRes = await handleInMemoryBackendRequest({
      method: "POST",
      path: "v1/workflows/runs",
      authorizationHeader: adminHeaders,
      rawBody: JSON.stringify({ workflow_key: "training.native_controlled_run" }),
    });
    expect(adminRunRes.status).toBe(202);
    const adminRunId = (adminRunRes.body as { id: string }).id;

    // 3. Register a separate non-admin user, login, and trigger their own active run
    const aliceEmail = `alice-${Date.now()}@zyrquen.local`;
    const alicePassword = "StrongPassword123!";
    const aliceReg = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/register",
      authorizationHeader: null,
      rawBody: JSON.stringify({
        email: aliceEmail,
        password: alicePassword,
      }),
    });
    expect(aliceReg.status).toBe(200);
    const aliceLogin = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/login",
      authorizationHeader: null,
      rawBody: JSON.stringify({
        email: aliceEmail,
        password: alicePassword,
      }),
    });
    expect(aliceLogin.status).toBe(200);
    const aliceToken = (aliceLogin.body as { access_token: string }).access_token;
    const aliceHeaders = `Bearer ${aliceToken}`;

    const aliceRunRes = await handleInMemoryBackendRequest({
      method: "POST",
      path: "v1/workflows/runs",
      authorizationHeader: aliceHeaders,
      rawBody: JSON.stringify({ workflow_key: "training.native_controlled_run" }),
    });
    expect(aliceRunRes.status).toBe(202);
    const aliceRunId = (aliceRunRes.body as { id: string }).id;

    // 4. Invalid run_id -> 400; Missing run_id -> 404; Cross-user run_id -> 403
    const badRunId = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/logs",
      authorizationHeader: aliceHeaders,
      searchParams: new URLSearchParams({ run_id: "../escape" }),
    });
    expect(badRunId.status).toBe(400);

    const missingRunId = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/logs",
      authorizationHeader: aliceHeaders,
      searchParams: new URLSearchParams({ run_id: "nonexistent-run-999" }),
    });
    expect(missingRunId.status).toBe(404);

    const crossUserRun = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/logs",
      authorizationHeader: aliceHeaders,
      searchParams: new URLSearchParams({ run_id: adminRunId }),
    });
    expect(crossUserRun.status).toBe(403);

    // 5. Alice sees ONLY Alice's runs and logs (zero cross-workflow leak from admin)
    const aliceLogs = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/logs",
      authorizationHeader: aliceHeaders,
      searchParams: new URLSearchParams({ active_only: "true" }),
    });
    expect(aliceLogs.status).toBe(200);
    const aliceBody = aliceLogs.body as {
      items: Array<{ run_id: string }>;
      active_runs: Array<{ id: string }>;
    };
    expect(aliceBody.active_runs.some((r) => r.id === aliceRunId)).toBe(true);
    expect(aliceBody.active_runs.some((r) => r.id === adminRunId)).toBe(false);
    expect(aliceBody.items.length).toBeGreaterThan(0);
    expect(aliceBody.items.every((item) => item.run_id === aliceRunId)).toBe(true);

    // 6. Non-admin cannot access approvals or audit-logs (403)
    const nonAdminApprovals = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/approvals",
      authorizationHeader: aliceHeaders,
    });
    expect(nonAdminApprovals.status).toBe(403);

    // 7. Admin requesting specific run_id receives ONLY entries for that run
    const adminScoped = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/workflows/logs",
      authorizationHeader: adminHeaders,
      searchParams: new URLSearchParams({ run_id: aliceRunId }),
    });
    expect(adminScoped.status).toBe(200);
    const adminScopedBody = adminScoped.body as {
      items: Array<{ run_id: string }>;
    };
    expect(adminScopedBody.items.length).toBeGreaterThan(0);
    expect(adminScopedBody.items.every((item) => item.run_id === aliceRunId)).toBe(true);
  });
});
