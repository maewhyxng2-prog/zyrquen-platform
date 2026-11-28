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

export type NativeModelVariant = {
  version: string;
  parent?: string | null;
  lifecycle_status?: string;
  created_at?: string;
  frozen?: boolean;
  checkpoint?: {
    path?: string;
    sha256_path?: string;
    step?: number;
    sha256?: string;
    size_bytes?: number;
  } | null;
  compatibility?: {
    version?: string;
    compatible?: boolean;
    checks?: {
      artifacts_sha256?: boolean;
      tokenizer_sha256?: boolean;
      architecture_config?: boolean;
    };
    reasons?: string[];
  } | null;
};

export type NativeModelRegistryResponse = {
  configured: boolean;
  detail?: string;
  root?: string;
  active_version: string | null;
  registered_count?: number;
  versions: NativeModelVariant[];
};

export type CheckpointIntegrityStatus = "Verified" | "Corrupted";

export type CheckpointIntegrityResult = {
  version: string;
  status: CheckpointIntegrityStatus;
  verified: boolean;
  checkpoint_path: string | null;
  sidecar_path: string | null;
  sidecar_present: boolean;
  expected_sha256: string | null;
  recorded_sha256?: string | null;
  actual_sha256: string | null;
  checked_at: string;
  detail: string;
  compatibility?: {
    version: string;
    compatible: boolean;
    checks: {
      artifacts_sha256: boolean;
      tokenizer_sha256: boolean;
      architecture_config: boolean;
    };
    reasons: string[];
  } | null;
};

export type Session = {
  authenticated: boolean;
  email: string | null;
  userId: string | null;
  role: string | null;
  verified: boolean;
  emailVerified: boolean;
  expired?: boolean;
  error?: string | null;
};

export type AuditEntry = {
  id: string;
  actor_user_id: string | null;
  actor_email?: string | null;
  action: string;
  resource_id: string | null;
  outcome?: string | null;
  created_at: string;
};

export type AuthProviderConfigStatus = {
  configured: boolean;
  name?: string;
};

export type AuthProvidersResponse = {
  providers: {
    github: AuthProviderConfigStatus;
    google: AuthProviderConfigStatus;
  };
};

export type OAuthIdentity = {
  id: string;
  provider: "github" | "google";
  provider_user_id: string;
  provider_email: string | null;
  email_verified: boolean;
  display_name: string | null;
  avatar_url: string | null;
  linked_at: string;
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
  total_documents?: number;
  split_counts?: Record<string, { documents?: number | null; sha256?: string | null }>;
  required_four_splits?: string[];
  four_split_compliant?: boolean;
  missing_four_splits?: string[];
  split_distribution?: Record<string, { present: boolean; documents: number; ratio: number }>;
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
  four_split_compliant?: boolean;
  detail: string;
  active_dataset: DatasetRecordStatus | null;
  datasets: DatasetRecordStatus[];
};

export type TrainingReadinessStatus = {
  configured: boolean;
  status: "ready" | "not_ready" | "not_configured";
  dataset_configured: boolean;
  dataset_verified?: boolean;
  four_split_present?: boolean;
  tokenizer_configured: boolean;
  runtime_ready?: boolean;
  torch_available?: boolean;
  training_root_ready?: boolean;
  worker_ready?: boolean;
  worker_busy?: boolean;
  admin_allowlist_configured: boolean;
  is_training_admin: boolean;
  tier2_approval_required: boolean;
  approval_secret_configured?: boolean;
  approved_training_approvals?: number;
  pending_training_approvals?: number;
  active_run_id: string | null;
  dataset?: {
    configured: boolean;
    verified: boolean;
    format?: string | null;
    four_split_enforced: boolean;
    required_splits: string[];
    splits: string[];
    four_split_present: boolean;
    split_counts: Record<string, number>;
    leakage_check: {
      status: string;
      passed: boolean;
      violations: string[];
    };
  };
  tokenizer?: {
    configured: boolean;
    valid: boolean;
    detail: string;
  };
  preflight?: {
    passed: boolean;
    detail: string;
    storage_writable: boolean;
    resource_limits_checked: boolean;
    max_cpu_parameters: number;
  };
  runtime?: {
    ready: boolean;
    torch_available: boolean;
    training_root_ready: boolean;
    worker_ready: boolean;
    worker_busy: boolean;
    active_run_id: string | null;
  };
  reasons?: string[];
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

export type WorkflowExecutionLogLevel = "INFO" | "WARN" | "ERROR";

export type WorkflowExecutionLogItem = {
  id: string;
  run_id: string | null;
  workflow_key: string | null;
  step_key: string | null;
  level: WorkflowExecutionLogLevel;
  event_type: string;
  status: string;
  actor_id?: string | null;
  message: string;
  details?: Record<string, unknown> | null;
  timestamp: string | null;
};

export type WorkflowActiveJobSummary = {
  id: string;
  workflow_key: string;
  workflow_version?: string;
  status: string;
  started_at?: string | null;
};

export type WorkflowLogsResponse = {
  items: WorkflowExecutionLogItem[];
  active_runs: WorkflowActiveJobSummary[];
  active_only: boolean;
  polled_at: string;
};
