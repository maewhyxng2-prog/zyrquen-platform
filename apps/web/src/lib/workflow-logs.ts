import type {
  WorkflowActiveJobSummary,
  WorkflowExecutionLogItem,
  WorkflowExecutionLogLevel,
  WorkflowLogsResponse,
} from "./types";
import type { WorkflowRunItem } from "./workflow-metrics";

const ACTIVE_ORCHESTRATION_STATUSES = new Set([
  "PENDING",
  "RUNNING",
  "VERIFYING",
  "WAITING_APPROVAL",
  "WAITING_RESOURCE",
]);

export function isActiveOrchestrationStatus(status: string | null | undefined): boolean {
  return Boolean(status && ACTIVE_ORCHESTRATION_STATUSES.has(status.toUpperCase()));
}

export function logLevelForStatus(
  statusValue: string | null | undefined,
  decisionValue?: string | null,
): WorkflowExecutionLogLevel {
  const combined = `${statusValue ?? ""} ${decisionValue ?? ""}`.toUpperCase();
  if (
    combined.includes("FAILED") ||
    combined.includes("ERROR") ||
    combined.includes("DENY") ||
    combined.includes("REJECTED") ||
    combined.includes("VIOLATION")
  ) {
    return "ERROR";
  }
  if (
    combined.includes("BLOCKED") ||
    combined.includes("WAITING") ||
    combined.includes("WARN") ||
    combined.includes("RETRY") ||
    combined.includes("CANCEL")
  ) {
    return "WARN";
  }
  return "INFO";
}

export function normalizeWorkflowLogLevel(
  level: string | null | undefined,
): "ALL" | WorkflowExecutionLogLevel | null {
  if (level == null) return null;
  const upper = level.trim().toUpperCase();
  if (!upper) return null;
  if (upper === "ALL" || upper === "INFO" || upper === "WARN" || upper === "ERROR") {
    return upper;
  }
  return null;
}

export function buildWorkflowLogsQuery(options: {
  activeOnly?: boolean;
  runId?: string;
  limit?: number;
  level?: "ALL" | WorkflowExecutionLogLevel;
  search?: string;
}): string {
  const params = new URLSearchParams();
  params.set("active_only", options.activeOnly === false ? "false" : "true");
  if (options.runId && options.runId.trim()) {
    params.set("run_id", options.runId.trim());
  }
  if (typeof options.limit === "number" && Number.isFinite(options.limit)) {
    const clamped = Math.max(1, Math.min(500, Math.round(options.limit)));
    params.set("limit", String(clamped));
  }
  if (options.level && options.level !== "ALL") {
    params.set("level", options.level);
  }
  if (options.search && options.search.trim()) {
    params.set("search", options.search.trim().slice(0, 160));
  }
  return params.toString();
}

export function filterWorkflowLogs(
  items: WorkflowExecutionLogItem[],
  options: {
    level?: "ALL" | WorkflowExecutionLogLevel;
    search?: string;
  },
): WorkflowExecutionLogItem[] {
  const levelFilter = options.level ?? "ALL";
  const query = (options.search ?? "").trim().toLowerCase();

  return items.filter((item) => {
    if (levelFilter !== "ALL" && item.level !== levelFilter) {
      return false;
    }
    if (!query) return true;
    const haystack = [
      item.workflow_key ?? "",
      item.run_id ?? "",
      item.step_key ?? "",
      item.event_type ?? "",
      item.status ?? "",
      item.message ?? "",
      item.actor_id ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}

export function formatWorkflowLogTime(timestamp: string | null | undefined): string {
  if (!timestamp) return "—";
  const parsed = Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return timestamp;
  return new Date(parsed).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export const SAFE_WORKFLOW_RUN_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export function isValidWorkflowRunId(runId: string | null | undefined): boolean {
  if (typeof runId !== "string") return false;
  const trimmed = runId.trim();
  return trimmed.length > 0 && SAFE_WORKFLOW_RUN_ID_RE.test(trimmed);
}

export function filterWorkflowRunsByOwnership<
  T extends { requested_by_user_id?: string | null },
>(runs: T[], caller: { id: string; role: string }): T[] {
  if (caller.role === "admin") {
    return runs;
  }
  return runs.filter((r) => r.requested_by_user_id === caller.id);
}

export function deriveLogsFromRuns(
  runs: WorkflowRunItem[],
  options: {
    activeOnly?: boolean;
    runId?: string | null;
    limit?: number;
    level?: "ALL" | WorkflowExecutionLogLevel;
    search?: string;
  } = {},
): WorkflowLogsResponse {
  const activeOnly = options.activeOnly !== false;
  const runIdFilter = options.runId?.trim() || null;
  const limit = Math.max(1, Math.min(500, Math.round(options.limit ?? 100)));

  const activeRuns = runs.filter((run) => isActiveOrchestrationStatus(run.status));
  const targetRuns = runIdFilter
    ? runs.filter((run) => run.id === runIdFilter)
    : activeOnly
      ? activeRuns
      : runs.slice(0, 25);

  const items: WorkflowExecutionLogItem[] = [];

  for (const run of targetRuns) {
    const runTimestamp = run.finished_at || run.started_at || run.created_at;
    items.push({
      id: `run:${run.id}:${run.status}`,
      run_id: run.id,
      workflow_key: run.workflow_key,
      step_key: null,
      level: logLevelForStatus(run.status),
      event_type: `workflow.${run.status.toLowerCase()}`,
      status: run.status,
      actor_id: "orchestrator",
      message:
        run.error_message?.trim() ||
        `Workflow ${run.workflow_key} (${run.trigger_type || "manual"}) is ${run.status}`,
      details: {
        workflow_version: run.workflow_version,
        trigger_type: run.trigger_type,
      },
      timestamp: runTimestamp,
    });

    for (const step of run.steps ?? []) {
      const stepTimestamp =
        step.finished_at || step.started_at || run.started_at || run.created_at;
      const verdict = step.evidence?.verdict ?? null;
      const summary =
        typeof step.evidence?.summary === "string" && step.evidence.summary.trim()
          ? step.evidence.summary.trim()
          : `Step ${step.step_key} is ${step.status} (attempt ${step.attempt ?? 0})`;
      items.push({
        id: `step:${run.id}:${step.step_key}:${step.status}:${step.attempt ?? 0}`,
        run_id: run.id,
        workflow_key: run.workflow_key,
        step_key: step.step_key,
        level: logLevelForStatus(step.status, verdict),
        event_type: `step.${step.status.toLowerCase()}`,
        status: step.status,
        actor_id: "orchestrator",
        message: summary,
        details: {
          lane: step.lane ?? null,
          attempt: step.attempt ?? 0,
          verdict,
          output: step.output ?? null,
        },
        timestamp: stepTimestamp,
      });
    }
  }

  items.sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? ""));

  const filtered = filterWorkflowLogs(items, {
    level: options.level,
    search: options.search,
  });

  const activeSummaries: WorkflowActiveJobSummary[] = activeRuns.map((run) => ({
    id: run.id,
    workflow_key: run.workflow_key,
    workflow_version: run.workflow_version,
    status: run.status,
    started_at: run.started_at ?? run.created_at,
  }));

  return {
    items: filtered.slice(0, limit),
    active_runs: activeSummaries,
    active_only: activeOnly,
    polled_at: new Date().toISOString(),
  };
}

export function collectSelectableWorkflowRuns(
  activeRuns: WorkflowActiveJobSummary[],
  logs: WorkflowExecutionLogItem[],
  previousKnown: WorkflowActiveJobSummary[] = [],
): WorkflowActiveJobSummary[] {
  const byId = new Map<string, WorkflowActiveJobSummary>();

  for (const run of activeRuns) {
    if (run.id) {
      byId.set(run.id, run);
    }
  }

  for (const prev of previousKnown) {
    if (prev.id && !byId.has(prev.id)) {
      byId.set(prev.id, prev);
    }
  }

  for (const entry of logs) {
    const rid = entry.run_id?.trim();
    if (!rid || byId.has(rid)) continue;
    byId.set(rid, {
      id: rid,
      workflow_key: entry.workflow_key || entry.event_type || "workflow",
      status: entry.status || "RECORDED",
      started_at: entry.timestamp ?? null,
    });
  }

  return Array.from(byId.values());
}

