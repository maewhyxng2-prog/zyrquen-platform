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
};

export type CreatedApiKey = ApiKeyMetadata & { key: string };

export type ApiKeyUsage = {
  keyId: string;
  successfulRequests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  updatedAt: string | null;
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
