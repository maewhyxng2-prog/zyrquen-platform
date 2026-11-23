export type ApiHealth = {
  status: string;
  service?: string;
  native_ai?: NativeHealth;
};

export type CapabilityMetric = {
  key: string;
  label: string;
  score: number | null;
  target?: number | null;
  status: "measured" | "not_evaluated";
};

export type ZyrquenProgressMetrics = {
  generalization_score: number | null;
  generalization_target?: number | null;
  relational_reasoning_success_rate: number | null;
  relational_reasoning_target?: number | null;
  evaluation_status: "evaluated" | "not_evaluated";
  metrics_source: string | null;
};

export type NativeHealth = {
  runtime_status: string;
  native_model_loaded: boolean;
  authority: string;
  inference_available: boolean;
  platform_version?: string | null;
  platform_stage?: string | null;
  model_version?: string | null;
  is_trained?: boolean;
  capabilities?: CapabilityMetric[];
  progress_metrics?: ZyrquenProgressMetrics | null;
};

export type Session = {
  authenticated: boolean;
  email: string | null;
  userId?: string | null;
  verified?: boolean;
  expired?: boolean;
  error?: string | null;
};

export type InferenceResponse = {
  status: string;
  request_id: string;
  provider: string;
  result: string;
};

export type UserProfile = {
  id: string;
  email: string;
};

export type UsageRecord = {
  requestId: string;
  status: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  modelVersion: string | null;
  createdAt: string;
  completedAt: string | null;
};

export type UsageSummary = {
  successfulRequests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  updatedAt: string | null;
  records: UsageRecord[];
};

export type QuotaSummary = {
  configured: boolean;
  active: boolean;
  maxRequests: number | null;
  maxInputTokens: number | null;
  maxOutputTokens: number | null;
  maxTotalTokens: number | null;
  windowStartedAt: string | null;
  windowEndsAt: string | null;
  successfulRequests: number;
  runningRequests: number;
  requestsInUse: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
};

export type ApiKeyMetadata = {
  id: string;
  name: string;
  keyPrefix: string;
  scope: string;
  createdAt: string;
  expiresAt: string;
  revokedAt: string | null;
  autoRotateEnabled: boolean;
  autoRotateIntervalDays: number | null;
  lastRotatedAt: string | null;
  nextRotationAt: string | null;
  rotationCount: number;
};

export type CreatedApiKey = ApiKeyMetadata & { key: string };

export type ApiKeyDailyUsagePoint = {
  date: string;
  successfulRequests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
};

export type ApiKeyUsage = {
  keyId: string;
  successfulRequests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  updatedAt: string | null;
  dailyUsage: ApiKeyDailyUsagePoint[];
};

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  incomplete?: boolean;
};

export type Conversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  messages: ConversationMessage[];
};

export type StatusTone = "good" | "warn" | "bad" | "neutral" | "info";

export type ClosureAuditStatus =
  | "PASS"
  | "STATIC PASS"
  | "IMPLEMENTED"
  | "BLOCKED"
  | "NOT RUN"
  | "FAILED";

export type V10ContractCheckItem = {
  label: string;
  passed: boolean;
  detail: string;
};

export type V10ContractAudit = {
  id: string;
  code: string;
  title: string;
  stage: string;
  status: ClosureAuditStatus;
  anchor: string;
  summary: string;
  checks: V10ContractCheckItem[];
};

export type V10ClosureStage = {
  id: string;
  title: string;
  status: ClosureAuditStatus;
  summary: string;
  blockers: string[];
};

export type V10ClosureAudit = {
  schema: string;
  checked_at: string;
  overall_status: ClosureAuditStatus;
  static_status: ClosureAuditStatus;
  runtime_status: ClosureAuditStatus;
  contracts_passed_count: number;
  contracts_total: number;
  v11_gate: {
    target_version: string;
    unlocked: boolean;
    status: "READY" | "LOCKED";
    prerequisite_summary: string;
  };
  runtime_environment: {
    torch_installed: boolean;
    native_runtime_status: string;
    native_model_loaded: boolean;
    is_trained: boolean;
    active_model_version: string | null;
    eval_report_configured: boolean;
    eval_report_status: string | null;
    registry_configured: boolean;
    verified_v10_models: number;
    dataset_configured: boolean;
    tokenizer_configured: boolean;
  };
  blockers: string[];
  contracts: V10ContractAudit[];
  stages: V10ClosureStage[];
};

export type WorkflowServicesStatus = {
  service: string;
  started: boolean;
  started_at: string | null;
  diagnostics_safe_mode: boolean;
  scheduler: {
    enabled: boolean;
    running: boolean;
    safely_disabled: boolean;
    status: "running" | "disabled" | "idle";
    env_flag: string;
    env_enabled: boolean;
    poll_interval_sec: number;
  };
  recovery: {
    enabled: boolean;
    safely_disabled: boolean;
    status: "enabled" | "disabled";
    env_flag: string;
    env_enabled: boolean;
    startup_reconciliation_ran: boolean;
    reconciled_runs_count: number;
  };
};

export type DatasetRecordStatus = {
  exists: boolean;
  verified: boolean;
  status: string;
  version?: string | null;
  schema?: string | null;
  format?: string | null;
  content_sha256?: string | null;
  splits?: string[];
  split_counts?: Record<string, { documents?: number | null; sha256?: string | null }>;
  licensed_sources_count?: number;
  v11_leakage_check?: {
    status: string;
    passed?: boolean;
    violations?: string[];
  };
  error?: string;
};

export type DatasetPipelineStatus = {
  configured: boolean;
  status: "ready" | "invalid" | "not_configured";
  detail: string;
  active_dataset: DatasetRecordStatus | null;
  datasets: DatasetRecordStatus[];
};

export type TrainingReadinessStatus = {
  configured: boolean;
  status: "ready" | "not_configured";
  dataset_configured: boolean;
  tokenizer_configured: boolean;
  admin_allowlist_configured: boolean;
  is_training_admin: boolean;
  tier2_approval_required: boolean;
  active_run_id: string | null;
};

export type TrainingRunSummary = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  dataset_version: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
};

export type TrainingTelemetryPayload = {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  metrics: Array<Record<string, unknown>>;
  checkpoints: Array<{
    step: number;
    file: string;
    size_bytes: number;
    sha256: string;
  }>;
  epochs_completed: number | null;
  epochs_note?: string;
};
