export type WorkflowStepItem = {
  step_key: string;
  status: string;
  lane: string;
  attempt?: number;
  max_attempts?: number;
  started_at?: string | null;
  finished_at?: string | null;
  evidence?: {
    verdict?: string;
    summary?: string;
    [key: string]: unknown;
  } | null;
  output?: Record<string, unknown> | null;
  error_code?: string | null;
};

export type WorkflowRunItem = {
  id: string;
  workflow_key: string;
  workflow_version: string;
  trigger_type: string;
  status: string;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  steps: WorkflowStepItem[];
};

export type RunProgressInfo = {
  percent: number;
  completedSteps: number;
  totalSteps: number;
  activeStepKey: string | null;
  activeStepStatus: string | null;
  tone: "info" | "warn" | "neutral";
};

export type ExtractedRunMetrics = {
  epochs: number | null;
  steps: number | null;
  trainLoss: number | null;
  valLoss: number | null;
  latestLoss: number | null;
  latestLossKind: "val_loss" | "train_loss" | "loss" | null;
  perplexity: number | null;
  ramPeakGb: number | null;
  hasTrainingMetrics: boolean;
};

export type CompletedKpiSummary = {
  latestRun: WorkflowRunItem;
  latestMetrics: ExtractedRunMetrics;
  durationMs: number | null;
  previousRun: WorkflowRunItem | null;
  previousMetrics: ExtractedRunMetrics | null;
  previousDurationMs: number | null;
  lossDelta: number | null;
  durationDeltaMs: number | null;
  completedSteps: number;
  totalSteps: number;
};

const ACTIVE_STATUSES = new Set([
  "PENDING",
  "RUNNING",
  "VERIFYING",
  "WAITING_APPROVAL",
  "WAITING_RESOURCE",
]);

export function isWorkflowRunActive(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

function readNumberFromRecord(
  record: Record<string, unknown> | null | undefined,
  keys: readonly string[],
): number | null {
  if (!record) return null;
  for (const key of keys) {
    const candidate = finiteNumber(record[key]);
    if (candidate !== null) return candidate;
  }
  return null;
}

function parseSummaryMetric(summary: unknown, pattern: RegExp): number | null {
  if (typeof summary !== "string" || !summary) return null;
  const match = summary.match(pattern);
  if (!match || !match[1]) return null;
  return finiteNumber(match[1]);
}

export function computeRunProgress(run: WorkflowRunItem): RunProgressInfo {
  const steps = Array.isArray(run.steps) ? run.steps : [];
  const totalSteps = steps.length;
  const completedSteps = steps.filter(
    (s) => s.status === "COMPLETED" || s.status === "SKIPPED",
  ).length;

  const activeStep =
    steps.find((s) => s.status === "RUNNING") ??
    steps.find((s) => s.status === "WAITING_APPROVAL") ??
    steps.find((s) => s.status === "WAITING_RESOURCE") ??
    steps.find((s) => s.status === "PENDING") ??
    null;

  const tone: "info" | "warn" | "neutral" =
    run.status === "WAITING_APPROVAL" || run.status === "WAITING_RESOURCE"
      ? "warn"
      : run.status === "RUNNING" || run.status === "VERIFYING"
        ? "info"
        : "neutral";

  if (run.status === "COMPLETED") {
    return {
      percent: 100,
      completedSteps,
      totalSteps,
      activeStepKey: null,
      activeStepStatus: null,
      tone: "info",
    };
  }

  if (totalSteps === 0) {
    return {
      percent: 0,
      completedSteps: 0,
      totalSteps: 0,
      activeStepKey: null,
      activeStepStatus: null,
      tone,
    };
  }

  let activeFraction = 0;
  if (activeStep?.status === "RUNNING") {
    const explicitPct =
      readNumberFromRecord(activeStep.output, ["progress_pct", "progress_percent"]) ??
      readNumberFromRecord(activeStep.evidence, ["progress_pct", "progress_percent"]);
    if (explicitPct !== null) {
      activeFraction = clamp01(explicitPct / 100);
    } else {
      const currentStep =
        readNumberFromRecord(activeStep.output, ["current_step", "step"]) ??
        readNumberFromRecord(activeStep.evidence, ["current_step", "step"]);
      const maxSteps =
        readNumberFromRecord(activeStep.output, ["max_steps", "total_steps"]) ??
        readNumberFromRecord(activeStep.evidence, ["max_steps", "total_steps"]);
      if (currentStep !== null && maxSteps !== null && maxSteps > 0) {
        activeFraction = clamp01(currentStep / maxSteps);
      } else {
        activeFraction = 0.5;
      }
    }
  }

  let percent = Math.round(((completedSteps + activeFraction) / totalSteps) * 100);
  if (run.status === "VERIFYING") {
    percent = Math.min(95, Math.max(percent, Math.round((completedSteps / totalSteps) * 95)));
  } else {
    percent = Math.min(99, Math.max(0, percent));
  }

  return {
    percent,
    completedSteps,
    totalSteps,
    activeStepKey: activeStep?.step_key ?? null,
    activeStepStatus: activeStep?.status ?? null,
    tone,
  };
}

function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

export function computeRunDurationMs(run: WorkflowRunItem): number | null {
  const finishedMs = parseTimestamp(run.finished_at);
  if (finishedMs === null) return null;

  let startedMs = parseTimestamp(run.started_at);
  if (startedMs === null) {
    const stepStarts = (run.steps ?? [])
      .map((s) => parseTimestamp(s.started_at))
      .filter((t): t is number => t !== null);
    if (stepStarts.length > 0) {
      startedMs = Math.min(...stepStarts);
    }
  }
  if (startedMs === null) {
    startedMs = parseTimestamp(run.created_at);
  }
  if (startedMs === null || finishedMs < startedMs) {
    return null;
  }
  return finishedMs - startedMs;
}

export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const totalWholeSeconds = Math.round(totalSeconds);
  const hours = Math.floor(totalWholeSeconds / 3600);
  const minutes = Math.floor((totalWholeSeconds % 3600) / 60);
  const seconds = totalWholeSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

export function formatLoss(loss: number | null): string {
  if (loss === null || !Number.isFinite(loss)) return "—";
  return loss.toFixed(4);
}

export function extractRunMetrics(run: WorkflowRunItem): ExtractedRunMetrics {
  let epochs: number | null = null;
  let steps: number | null = null;
  let trainLoss: number | null = null;
  let valLoss: number | null = null;
  let genericLoss: number | null = null;
  let perplexity: number | null = null;
  let ramPeakGb: number | null = null;

  for (const step of run.steps ?? []) {
    const out = step.output ?? undefined;
    const ev = step.evidence ?? undefined;
    const summary = ev?.summary;

    epochs ??=
      readNumberFromRecord(out, ["epochs", "epoch", "epochs_completed"]) ??
      readNumberFromRecord(ev, ["epochs", "epoch", "epochs_completed"]) ??
      parseSummaryMetric(summary, /\bepochs?\s*=\s*(-?\d+(?:\.\d+)?)\b/i);

    steps ??=
      readNumberFromRecord(out, ["steps", "global_step", "step"]) ??
      readNumberFromRecord(ev, ["steps", "global_step", "step"]) ??
      parseSummaryMetric(summary, /\bsteps?\s*=\s*(-?\d+(?:\.\d+)?)\b/i);

    valLoss ??=
      readNumberFromRecord(out, ["val_loss"]) ??
      readNumberFromRecord(ev, ["val_loss"]) ??
      parseSummaryMetric(summary, /\bval_loss\s*=\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/i);

    trainLoss ??=
      readNumberFromRecord(out, ["train_loss"]) ??
      readNumberFromRecord(ev, ["train_loss"]) ??
      parseSummaryMetric(summary, /\btrain_loss\s*=\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/i);

    genericLoss ??=
      readNumberFromRecord(out, ["loss"]) ??
      readNumberFromRecord(ev, ["loss"]) ??
      parseSummaryMetric(summary, /\bloss\s*=\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/i);

    perplexity ??=
      readNumberFromRecord(out, ["perplexity"]) ??
      readNumberFromRecord(ev, ["perplexity"]) ??
      parseSummaryMetric(summary, /\bperplexity\s*=\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/i);

    ramPeakGb ??=
      readNumberFromRecord(out, ["ram_peak_gb"]) ??
      readNumberFromRecord(ev, ["ram_peak_gb"]) ??
      parseSummaryMetric(summary, /\bram_peak_gb\s*=\s*(-?\d+(?:\.\d+)?)\b/i);
  }

  const latestLoss = valLoss ?? trainLoss ?? genericLoss;
  const latestLossKind: ExtractedRunMetrics["latestLossKind"] =
    valLoss !== null
      ? "val_loss"
      : trainLoss !== null
        ? "train_loss"
        : genericLoss !== null
          ? "loss"
          : null;

  const hasTrainingMetrics =
    epochs !== null ||
    steps !== null ||
    latestLoss !== null ||
    perplexity !== null;

  return {
    epochs,
    steps,
    trainLoss,
    valLoss,
    latestLoss,
    latestLossKind,
    perplexity,
    ramPeakGb,
    hasTrainingMetrics,
  };
}

function runOrderTimestamp(run: WorkflowRunItem): number {
  return (
    parseTimestamp(run.finished_at) ??
    parseTimestamp(run.started_at) ??
    parseTimestamp(run.created_at) ??
    0
  );
}

export function selectLatestCompletedKpi(runs: WorkflowRunItem[]): CompletedKpiSummary | null {
  const completedRuns = runs
    .filter((r) => r.status === "COMPLETED")
    .sort((a, b) => runOrderTimestamp(b) - runOrderTimestamp(a));

  if (completedRuns.length === 0) return null;

  const withMetrics = completedRuns.map((run) => ({
    run,
    metrics: extractRunMetrics(run),
  }));

  const preferred =
    withMetrics.find(
      (item) => item.metrics.hasTrainingMetrics || item.run.workflow_key.startsWith("training."),
    ) ?? withMetrics[0];

  const previous =
    withMetrics.find(
      (item) =>
        item.run.id !== preferred.run.id &&
        (item.run.workflow_key === preferred.run.workflow_key ||
          (preferred.metrics.hasTrainingMetrics && item.metrics.hasTrainingMetrics)),
    ) ?? null;

  const durationMs = computeRunDurationMs(preferred.run);
  const previousDurationMs = previous ? computeRunDurationMs(previous.run) : null;

  const lossDelta =
    preferred.metrics.latestLoss !== null &&
    previous?.metrics.latestLoss !== null &&
    previous?.metrics.latestLoss !== undefined
      ? preferred.metrics.latestLoss - previous.metrics.latestLoss
      : null;

  const durationDeltaMs =
    durationMs !== null && previousDurationMs !== null
      ? durationMs - previousDurationMs
      : null;

  const totalSteps = preferred.run.steps.length;
  const completedSteps = preferred.run.steps.filter(
    (s) => s.status === "COMPLETED" || s.status === "SKIPPED",
  ).length;

  return {
    latestRun: preferred.run,
    latestMetrics: preferred.metrics,
    durationMs,
    previousRun: previous?.run ?? null,
    previousMetrics: previous?.metrics ?? null,
    previousDurationMs,
    lossDelta,
    durationDeltaMs,
    completedSteps,
    totalSteps,
  };
}
