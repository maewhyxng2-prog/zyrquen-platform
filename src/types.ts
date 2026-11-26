export type AppScreen =
  | 'overview'
  | 'projects'
  | 'tasks'
  | 'create'
  | 'analysis'
  | 'artifacts'
  | 'workspace'
  | 'memory'
  | 'settings';
export type SettingsTab = 'account' | 'developer' | 'admin';
export type ReasoningMode = 'auto' | 'math' | 'knowledge' | 'model' | 'plan';
export type ModelVariantId =
  | 'zyrquen-omega-v1'
  | 'zyrquen-ast-pro'
  | 'zyrquen-kg-v2'
  | 'zyrquen-ngram-ckpt'
  | 'zyrquen-neural-v1';

export const MODEL_VARIANTS: ReadonlyArray<{
  id: ModelVariantId;
  label: string;
  shortLabel: string;
  description: string;
}> = [
  {
    id: 'zyrquen-omega-v1',
    label: 'ZYRQUEN Ω∞ Core v1',
    shortLabel: 'Ω∞ Core v1',
    description: 'แกนสมองผสมผสานมาตรฐาน (AST + Graph + Neural/N-Gram)',
  },
  {
    id: 'zyrquen-ast-pro',
    label: 'ZYRQUEN AST Pro v1.2',
    shortLabel: 'AST Pro v1.2',
    description: 'เน้นการคำนวณเชิงสัญลักษณ์และสมการเชิงเส้น (งดเดาข้อความ)',
  },
  {
    id: 'zyrquen-kg-v2',
    label: 'ZYRQUEN Graph v2.0',
    shortLabel: 'Graph v2.0',
    description: 'เน้นกราฟความรู้หลายช่วงและตรวจความขัดแย้ง',
  },
  {
    id: 'zyrquen-ngram-ckpt',
    label: 'ZYRQUEN Checkpoint N-Gram',
    shortLabel: 'N-Gram Ckpt',
    description: 'เน้นการต่อข้อความจากสถิติ N-Gram Checkpoint ล่าสุด',
  },
  {
    id: 'zyrquen-neural-v1',
    label: 'ZYRQUEN Neural Transformer v1',
    shortLabel: 'Neural v1',
    description: 'โมเดล Native Transformer (Random-Init) + Subword BPE',
  },
];

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: 'admin' | 'user';
  created_at: string;
}

export interface AuthStatus {
  initialized: boolean;
  userCount: number;
  envPasscodeConfigured: boolean;
}

export type ProjectStatusCode =
  | 'ACTIVE'
  | 'COMPLETED'
  | 'AWAITING_APPROVAL'
  | 'BLOCKED'
  | 'NEEDS_INPUT';

export interface ProjectPendingAction {
  id: string;
  title: string;
  status: string;
  category: 'approval' | 'blocked' | 'task' | 'clarification' | 'setup' | string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  mode: ReasoningMode;
  created_at?: string;
  updated_at: string;
  message_count: number;
  project_status?: ProjectStatusCode;
  completion_pct?: number;
  completed_units?: number;
  total_units?: number;
  pending_actions?: ProjectPendingAction[];
  last_activity_summary?: string | null;
}

export interface ConversationSmartSummary {
  bullets: string[];
  metrics: {
    total_messages: number;
    verified_count: number;
    not_learned_count: number;
  };
}

export interface ReasoningTaskTiming {
  order?: number;
  task: string;
  duration_ms: number;
  matched: boolean;
  status: string;
  detail?: string;
}

export interface BottleneckTaskSummary {
  task: string;
  duration_ms: number;
  share_pct: number;
}

export interface NativeTrace {
  mode?: string;
  model_version?: string;
  metadata?: {
    modelVersion?: string;
    [key: string]: unknown;
  };
  engine_path?: string[];
  latency_ms?: number;
  python_version?: string;
  external_models_used?: boolean;
  task_timings?: ReasoningTaskTiming[];
  bottleneck_task?: BottleneckTaskSummary | null;
  math?: {
    expression: string;
    result: number;
    steps: string[];
  };
  word_math?: {
    engine: string;
    operation: string;
    operands: Array<number | string>;
    expression: string;
    result: number;
    steps: string[];
  };
  causal_logic?: {
    engine: string;
    sub_type: string;
    determined: boolean;
    contradiction: boolean;
    derived_conclusion: string | null;
    conclusions?: string[];
    verdict?: string;
    root_causes?: string[];
    steps: string[];
  };
  matched_triples?: Array<{
    id: string;
    subject: string;
    relation: string;
    object: string;
    source: string;
    hop?: number;
    provenance?: string;
    inferred_chain?: string;
    semantic_score?: number;
  }>;
  teach?: {
    triple: { subject: string; relation: string; object: string };
    duplicate: boolean;
    contradictions: string[];
  };
  checkpoint?: {
    engine?: string;
    checkpoint_version: number;
    perplexity: number;
    matched_vocab?: number;
    param_count?: number;
    generated: string | null;
    reason?: string;
  };
  statistics?: {
    count: number;
    mean: number;
    median: number;
    sum: number;
    min: number;
    max: number;
    range: number;
    stdev: number;
    pstdev: number;
  };
  algebra?: {
    engine: string;
    equation: string;
    variable?: string;
    solution_type: string;
    result?: number | string | null;
    roots?: Array<number | string>;
    solutions?: Record<string, number | string>;
    summary_tag?: string;
    steps: string[];
  };
  logic?: {
    contradiction?: boolean;
    determined?: boolean;
    derived_relation?: string | null;
    target?: string[];
    steps: string[];
  };
  graph_path?: {
    found: boolean;
    start: string;
    end: string;
    max_depth?: number;
    path?: {
      hops: number;
      bidirectional?: boolean;
      edges: Array<{ from: string; relation: string; to: string; source: string }>;
    } | null;
  };
  execution_phase?: string;
  goal_validation?: {
    clarity_status?: string;
    is_actionable_goal?: boolean;
    issues?: string[];
    status_transitions?: Array<{
      step_id?: string;
      from_status: string;
      to_status: string;
      reason?: string;
    }>;
  };
  plan?: {
    goal: string;
    plan_status?: string;
    status?: string;
    is_actionable_goal?: boolean;
    plan_valid?: boolean;
    status_transitions?: Array<{
      step_id?: string;
      from_status: string;
      to_status: string;
      reason?: string;
    }>;
    steps: Array<{
      step_id: string;
      title: string;
      status: string;
      depends_on?: string[];
      requires_approval?: boolean;
      detail: string;
    }>;
  };
  autonomous_mission?: {
    mission_id?: string;
    status?: string;
    stages?: Array<{ stage: string; label?: string; status: string; detail?: string }>;
    knowledge_developed?: unknown[];
  };
  external_tool?: {
    tool_id: string;
    status: string;
    invocation_id: string | null;
    trust_grade?: string | null;
    distinct_providers?: string[];
    kg_matches_count?: number;
    limitations?: string[];
    analysis_summary?: string | null;
  };
  deliverable?: {
    kind: 'document' | 'code' | 'plan' | 'analysis' | string;
    title: string;
    filename?: string;
    language?: string;
    sha256?: string;
    verified?: boolean;
    content?: string;
  };
}

export interface MessageItem {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  mode: ReasoningMode;
  trace_json: string | null;
  status: string;
  created_at: string;
}

export interface SystemMetrics {
  python_version: string;
  platform: string;
  cpu_count: number;
  load_1m: number;
  mem_total_mb: number;
  mem_available_mb: number;
  disk_free_gb: number;
  disk_total_gb: number;
  sqlite_db_kb: number;
}

export interface AutonomousMissionStage {
  stage: 'think' | 'discover' | 'learn' | 'plan' | 'act' | 'verify' | 'improve' | string;
  label: string;
  status: string;
  detail: string;
}

export interface AutonomousMissionItem {
  id: string;
  goal: string;
  status: string;
  capabilities_json: string;
  stages_json: string;
  knowledge_developed_json: string;
  research_summary_json: string;
  report_markdown: string;
  external_models_used: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface MissionNodeItem {
  id: string;
  mission_id: string;
  task_id: string;
  node_json: string;
  execution_status: string;
  attempt_count: number;
  idempotency_key: string;
  last_error: string | null;
  updated_at: string;
}

export interface MissionEvidenceItem {
  id: string;
  mission_id: string;
  node_id: string | null;
  source_url: string;
  provider: string;
  retrieved_at: string;
  trust_grade: string;
  content_sha256: string;
  extracted_claims_json: string;
}

export interface ExperimentItem {
  id: string;
  hypothesis: string;
  dataset_id: string | null;
  baseline_ckpt_id: string | null;
  candidate_ckpt_id: string | null;
  baseline_metrics_json: string;
  candidate_metrics_json: string;
  improved: number;
  approval_status: string;
  approved_by: string | null;
  created_by: string;
  created_at: string;
}

export interface HomeSummary {
  recent_conversations: ConversationSummary[];
  recent_missions?: AutonomousMissionItem[];
  counts: {
    triples: number;
    checkpoints: number;
    datasets: number;
    pending_approvals: number;
    evaluations?: number;
    missions?: number;
  };
  system: SystemMetrics;
}

export interface KnowledgeTriple {
  id: string;
  subject: string;
  relation: string;
  object: string;
  source: string;
  confidence: number;
  created_by: string;
  created_at: string;
}

export interface WorkflowGroup {
  id: string;
  name: string;
  description: string;
  requires_approval: boolean;
  stages: string[];
}

export interface WorkflowStageResult {
  stage: string;
  status: string;
  detail?: string;
}

export interface WorkflowRun {
  id: string;
  group_id: string;
  status: string;
  requires_approval: number;
  triggered_by: string;
  approved_by: string | null;
  summary: string;
  stages_json: string;
  created_at: string;
  updated_at: string;
}

export interface ReasoningTraceRecord {
  id: string;
  user_id: string;
  conversation_id: string | null;
  message_id: string | null;
  prompt: string;
  response_preview: string;
  mode: string;
  model_version: string;
  status: string;
  engine_path_json: string;
  trace_json: string;
  latency_ms: number;
  external_models_used: number;
  created_at: string;
}

export interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  scopes_json: string;
  quota_daily: number;
  requests_today: number;
  last_used_at: string | null;
  revoked: number;
  created_at: string;
}

export interface DatasetItem {
  id: string;
  name: string;
  manifest_hash: string;
  total_records: number;
  train_count: number;
  val_count: number;
  test_count: number;
  leakage_detected: number;
  status: string;
  created_at: string;
  source_name?: string;
  license?: string;
  provenance?: string;
  source_format?: string;
  content_sha256?: string;
}

export interface KgIngestionProposalItem {
  id: string;
  dataset_id: string;
  dataset_name: string;
  provenance: string;
  source_name: string;
  license: string;
  manifest_hash: string;
  proposal_checksum: string;
  triples_json?: string;
  contradictions_json?: string;
  triple_count: number;
  status: 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'BLOCKED' | string;
  submitted_by: string;
  approved_by: string | null;
  decision_reason: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface DatasetVerifyResult {
  ok: boolean;
  dataset_id?: string;
  name?: string;
  verified: boolean;
  disk_verified?: boolean;
  content_sha256?: string;
  manifest_sha256?: string;
  leakage_detected?: number;
  errors?: string[];
  error?: string;
}

export interface CheckpointItem {
  id: string;
  version: number;
  dataset_id: string;
  vocab_size: number;
  ngram_order: number;
  train_loss: number;
  val_loss: number;
  perplexity: number;
  eval_accuracy: number | null;
  eval_status: string;
  created_at: string;
}

export interface EvaluationItem {
  id: string;
  checkpoint_version: number | null;
  suite_name: string;
  overall_status: string;
  math_score: number;
  knowledge_score: number;
  planning_score: number;
  test_accuracy: number | null;
  perplexity: number | null;
  baseline_delta_json: string | null;
  created_at: string;
}

export interface DeveloperOverview {
  keys: ApiKeyItem[];
  datasets: DatasetItem[];
  kg_proposals?: KgIngestionProposalItem[];
  checkpoints: CheckpointItem[];
  evaluations?: EvaluationItem[];
  experiments?: ExperimentItem[];
  usage: {
    total_requests: number;
    avg_latency_ms: number;
    daily_quota: number;
    recent: Array<{
      endpoint: string;
      method: string;
      status_code: number;
      latency_ms: number;
      created_at: string;
    }>;
  };
}

export interface AuditLogItem {
  id: string;
  actor_id: string;
  actor_email: string;
  action: string;
  target: string;
  outcome: string;
  details_json?: string | null;
  created_at: string;
}

export interface ExternalToolItem {
  id: string;
  name: string;
  category: 'web' | 'document' | 'compute' | 'file';
  description: string;
  endpoint_allowlist_json: string;
  permission_mode: 'auto' | 'approval_required' | 'disabled';
  enabled: number;
  quota_daily: number;
  calls_today: number;
  last_reset_date: string;
  updated_at: string;
}

export interface ToolInvocationItem {
  id: string;
  tool_id: string;
  conversation_id: string | null;
  user_id: string;
  status: 'PENDING_APPROVAL' | 'COMPLETED' | 'REJECTED' | 'FAILED' | 'BLOCKED';
  input_json: string;
  output_json: string | null;
  analysis_summary: string | null;
  approved_by: string | null;
  latency_ms: number;
  created_at: string;
}

export interface WorkspaceFileItem {
  name: string;
  size_bytes: number;
  modified_at: string;
}

export interface ToolsOverview {
  tools: ExternalToolItem[];
  invocations: ToolInvocationItem[];
  workspace_files: WorkspaceFileItem[];
}

export interface TrainingReadinessSummary {
  gate_status:
    | 'BLOCKED'
    | 'BLOCKED_NO_BASELINE'
    | 'AWAITING_APPROVAL'
    | 'READY_FOR_TRAINING_GATE'
    | 'VERIFIED'
    | string;
  datasets_total: number;
  clean_datasets: number;
  baseline_evaluations?: number;
  approved_training_runs?: number;
  triples_total: number;
  verified_triples: number;
  experiments_total: number;
  approved_experiments: number;
  pending_experiments: number;
  pending_training_runs: number;
  pending_kg_proposals?: number;
  checkpoints_total: number;
  neural_checkpoints: number;
  datasets: DatasetItem[];
  checkpoints: CheckpointItem[];
  experiments: ExperimentItem[];
}

export interface MemorySnapshot {
  timestamp: number;
  heapSupported: boolean;
  usedJSHeapMB: number | null;
  totalJSHeapMB: number | null;
  jsHeapLimitMB: number | null;
  streamBufferBytes: number;
  messageCount: number;
  activeStreamCount: number;
  pendingThreadLoads: number;
  heapDeltaMB: number | null;
  leakWarning: boolean;
}

export interface ThreadCleanupVerification {
  clean: boolean;
  activeCount: number;
  abortedCount: number;
  leakedRequestIds: number[];
  checkedAt: number;
}

export interface ClientLatencySample {
  timestamp: number;
  label: string;
  endpoint: string;
  latencyMs: number;
  status: number | string;
}

export interface AdminOverview {
  users: User[];
  pending_runs: WorkflowRun[];
  pending_tool_invocations?: ToolInvocationItem[];
  pending_experiments?: ExperimentItem[];
  pending_kg_proposals?: KgIngestionProposalItem[];
  tools?: ExternalToolItem[];
  audit_logs: AuditLogItem[];
  system: SystemMetrics;
  reasoning_traces?: ReasoningTraceRecord[];
  recent_api_usage?: DeveloperOverview['usage']['recent'];
  training_readiness?: TrainingReadinessSummary;
}

export type BenchmarkPolarity = 'positive' | 'negative' | 'invariant';

export interface BenchmarkCaseItem {
  id: string;
  category: string;
  polarity: BenchmarkPolarity;
  input: string;
  passed: boolean;
  expected: string;
  actual: string;
  failure_type: string | null;
  engine_path: string[];
  detail: string;
}

export interface BenchmarkCategoryStats {
  total: number;
  passed: number;
  failed: number;
  score: number;
}

export type CapabilityStatus =
  | 'NOT_IMPLEMENTED'
  | 'IMPLEMENTED'
  | 'TESTED'
  | 'PARTIAL'
  | 'VERIFIED'
  | 'BLOCKED'
  | 'REGRESSION_FAILED';

export interface CapabilityDomainEntry {
  domain: string;
  label: string;
  status: CapabilityStatus;
  implemented: boolean;
  measured: boolean;
  passed: number;
  total: number;
  failed: number;
  false_positives: number;
  score: number;
  criteria: {
    has_benchmark: boolean;
    has_unseen_dataset: boolean;
    has_e2e_probe: boolean;
    has_postcondition_check: boolean;
    zero_blocked_dependencies: boolean;
    zero_regression: boolean;
    threshold_met: boolean;
  };
  self_assessment_blocked: boolean;
  blocked_dependencies: string[];
  disclosed_gaps: string[];
  case_ids: string[];
  evidence_hash: string;
  evaluated_at: string;
}

export interface CapabilityLedger {
  policy: string;
  self_assessment_blocked: boolean;
  allowed_statuses: CapabilityStatus[];
  domains: Record<string, CapabilityDomainEntry>;
  summary: {
    total_domains: number;
    verified: number;
    tested: number;
    partial: number;
    implemented: number;
    blocked: number;
    regression_failed: number;
    not_implemented: number;
    counts_by_status: Record<string, number>;
  };
}

export interface NativeBenchmarkReport {
  benchmark_version: string;
  environment: {
    python_version: string;
    platform: string;
    model_version: string;
    checkpoint_version: number;
    checkpoint_vocab_size: number;
    external_models_used: boolean;
  };
  summary: {
    total_cases: number;
    passed: number;
    failed: number;
    overall_score: number;
    false_positives: number;
    negative_cases_total: number;
    false_positive_rate: number;
    false_negatives: number;
    positive_cases_total: number;
    false_negative_rate: number;
  };
  capability_ledger?: CapabilityLedger;
  category_scores: Record<string, BenchmarkCategoryStats>;
  leakage_detection: {
    fixture_isolation: {
      isolated: boolean;
      overlaps: unknown[];
      corpus_lines?: number;
      seed_triples?: number;
      negative_prompts?: number;
    };
    clean_split_leakage_detected: number;
    exact_dedup_passed: boolean;
    near_dup_leakage_caught: boolean;
  };
  builtin_core_eval: {
    overall_status: string;
    math_score: number;
    knowledge_score: number;
    planning_score: number;
    test_accuracy: number | null;
    perplexity: number | null;
  };
  failure_types: Record<string, number>;
  failures: BenchmarkCaseItem[];
  unmeasurable_limitations: string[];
  cases: BenchmarkCaseItem[];
}

export interface SourceVerificationMetrics {
  status: 'VERIFIED' | 'FAILED';
  score: number;
  passed: number;
  total: number;
  externalModelsUsed: boolean;
  checks: {
    fabricatedSourceRejected: boolean;
    invalidUrlRejected: boolean;
    unsupportedClaimRejected: boolean;
    staleEvidenceFlagged: boolean;
    missingEvidenceAbstained: boolean;
    mockIsolationVerified: boolean;
    falseSuccessPrevented: boolean;
  };
  failedCases: BenchmarkCaseItem[];
}

export interface AbstentionAccuracyMetrics {
  status: 'VERIFIED' | 'FAILED';
  overallAbstentionAccuracy: number;
  negativeCasesPassed: number;
  negativeCasesTotal: number;
  falsePositives: number;
  falsePositiveRate: number;
  negativeAbstentionCategory: BenchmarkCategoryStats;
  breaches: BenchmarkCaseItem[];
}

export interface NativeBenchmarkEvaluation {
  executedAt: string;
  report: NativeBenchmarkReport;
  sourceVerification: SourceVerificationMetrics;
  abstentionAccuracy: AbstentionAccuracyMetrics;
  integrityVerified: boolean;
}

export interface CodeCorpusCurateResult {
  ok: boolean;
  dataset?: {
    id: string;
    name: string;
    total_records: number;
    train_count?: number;
    val_count?: number;
    test_count?: number;
    manifest_hash?: string;
  };
  code_verification?: {
    total_tasks: number;
    verified_tasks: number;
    failed_tasks: number;
    ast_records_added: number;
    splits_counts: Record<string, number>;
  };
}

export interface CodeTrainingExperimentResult {
  ok: boolean;
  improved: boolean;
  external_models_used: boolean;
  experiment: {
    id: string;
    hypothesis: string;
    approval_status: string;
    dataset_id: string;
  };
  metrics: {
    training_focus: string;
    param_count: number;
    initial_train_loss: number;
    final_train_loss: number;
    initial_val_loss: number;
    final_val_loss: number;
    val_perplexity: number;
    test_loss: number;
    test_perplexity: number;
    test_accuracy: number;
    pre_contrastive_accuracy: number;
    post_contrastive_accuracy: number;
    unseen_execution_verified: boolean;
    regression_detected: boolean;
    honest_limitations?: string[];
  };
}

export interface CodeModelEvaluationResult {
  ok: boolean;
  status: string;
  reason?: string;
  checkpoint_version?: number;
  unseen_test_loss?: number;
  unseen_test_perplexity?: number;
  unseen_token_accuracy?: number;
  contrastive_probe?: {
    total: number;
    passed: number;
    accuracy: number;
  };
  external_models_used: boolean;
}

