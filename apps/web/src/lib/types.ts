export type ApiHealth = {
  status: string;
  service?: string;
  native_ai?: NativeHealth;
};

export type NativeHealth = {
  runtime_status: string;
  native_model_loaded: boolean;
  authority: string;
  inference_available: boolean;
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
