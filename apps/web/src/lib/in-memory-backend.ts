import { createHash, randomBytes, randomUUID, scryptSync, timingSafeEqual } from "node:crypto";
import type {
  NativeHealth,
  V10ClosureAudit,
  WorkflowActiveJobSummary,
  WorkflowExecutionLogItem,
} from "./types";
import {
  filterWorkflowRunsByOwnership,
  isActiveOrchestrationStatus,
  isValidWorkflowRunId,
  logLevelForStatus,
} from "./workflow-logs";

type StoredUser = {
  id: string;
  email: string;
  passwordHash: string | null;
  role: "admin" | "user";
  isActive: boolean;
  emailVerified: boolean;
  createdAt: string;
};

type StoredToken = {
  userId: string;
  expiresAt: number;
};

type StoredEmailVerificationToken = {
  tokenHash: string;
  userId: string;
  email: string;
  expiresAt: number;
};

type StoredOAuthState = {
  state: string;
  provider: "github" | "google";
  intent: "login" | "link";
  userId: string | null;
  redirectUri: string;
  codeVerifier: string;
  origin: string;
  expiresAt: number;
};

type StoredOAuthIdentity = {
  id: string;
  userId: string;
  provider: "github" | "google";
  providerUserId: string;
  providerEmail: string | null;
  emailVerified: boolean;
  displayName: string | null;
  avatarUrl: string | null;
  linkedAt: string;
};

type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
};

type StoredConversation = {
  id: string;
  userId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: StoredMessage[];
};

type StoredUsageRecord = {
  requestId: string;
  userId: string;
  apiKeyId?: string | null;
  status: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  modelVersion: string | null;
  createdAt: string;
  completedAt: string | null;
};

type StoredApiKey = {
  id: string;
  userId: string;
  name: string;
  keyPrefix: string;
  keyHash?: string;
  scope: string;
  createdAt: string;
  expiresAt: string;
  revokedAt: string | null;
  autoRotateEnabled: boolean;
  autoRotateIntervalDays: number | null;
  lastRotatedAt: string | null;
  nextRotationAt: string | null;
  rotationCount: number;
  validityDurationMs: number;
};

type StoredAuditEntry = {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_id: string | null;
  created_at: string;
};

type WorkflowStepRecord = {
  step_key: string;
  status: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  evidence: { verdict?: string; summary?: string } | null;
  output: Record<string, unknown> | null;
};

type WorkflowRunRecord = {
  id: string;
  workflow_key: string;
  workflow_version: string;
  trigger_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  requested_by_user_id: string | null;
  steps: WorkflowStepRecord[];
};

type WorkflowApprovalRecord = {
  id: string;
  run_id: string;
  step_key: string;
  action_type: string;
  scope: string;
  status: "pending" | "approved" | "rejected";
  reason: string;
  expires_at: string;
};

type ModelVersionRecord = {
  version: string;
  parent: string | null;
  lifecycle_status: string;
  created_at: string;
  frozen: boolean;
  checkpoint: { step: number; sha256: string };
  dataset: { version: string; content_sha256: string };
  evaluation_evidence: {
    passed: boolean;
    zero_regression: boolean;
    report_sha256: string;
    metrics: Record<string, number>;
    capabilities: Record<string, number>;
  } | null;
  compatibility: {
    version: string;
    compatible: boolean;
    checks: {
      artifacts_sha256: boolean;
      tokenizer_sha256: boolean;
      architecture_config: boolean;
    };
    reasons: string[];
  };
};

type InMemoryStore = {
  usersById: Map<string, StoredUser>;
  userIdByEmail: Map<string, string>;
  tokens: Map<string, StoredToken>;
  emailVerificationTokens: Map<string, StoredEmailVerificationToken>;
  oauthStates: Map<string, StoredOAuthState>;
  oauthIdentities: StoredOAuthIdentity[];
  conversations: Map<string, StoredConversation>;
  usageRecords: StoredUsageRecord[];
  apiKeys: Map<string, StoredApiKey>;
  auditLogs: StoredAuditEntry[];
  workflowRuns: WorkflowRunRecord[];
  workflowApprovals: WorkflowApprovalRecord[];
  modelVersions: ModelVersionRecord[];
  activeModelVersion: string;
};

export type InMemoryResponse = {
  status: number;
  headers?: Record<string, string>;
  body: unknown;
  stream?: ReadableStream<Uint8Array>;
};

const WORKFLOW_DEFINITIONS = [
  {
    workflow_key: "system_ops.health_check",
    version: "1.0.0",
    group_name: "system_ops",
    title: "System Operations Health & Resource Check",
    description:
      "Check API/NativeRuntime readiness, CPU/RAM/Disk snapshots, and compile daily status report.",
    default_tier: "tier1_auto",
    schedule_interval_sec: 3600,
    event_triggers: ["api.startup", "health.degraded"],
  },
  {
    workflow_key: "data.ingestion_and_leakage_gate",
    version: "1.0.0",
    group_name: "data",
    title: "Data Validation & Leakage Audit Gate",
    description:
      "Verify dataset manifest SHA-256 and execute 4-layer zero-tolerance leakage audit.",
    default_tier: "tier1_auto",
    schedule_interval_sec: null,
    event_triggers: ["dataset.ingested"],
  },
  {
    workflow_key: "training.native_controlled_run",
    version: "1.0.0",
    group_name: "training",
    title: "Controlled Native Training Pipeline",
    description:
      "Pre-flight dataset/resource caps check followed by mandatory Tier-2 human approval before training.",
    default_tier: "tier2_approval",
    schedule_interval_sec: null,
    event_triggers: [],
  },
  {
    workflow_key: "evaluation.model_verification",
    version: "1.0.0",
    group_name: "evaluation",
    title: "Native Model Evaluation & Regression Gate",
    description:
      "Verify registered artifact SHA-256, audit evaluation report evidence, and update registry verified/quarantined state.",
    default_tier: "tier1_auto",
    schedule_interval_sec: null,
    event_triggers: ["training.completed"],
  },
  {
    workflow_key: "knowledge.memory_ingestion",
    version: "1.0.0",
    group_name: "knowledge_memory",
    title: "Knowledge & Memory Isolation Check",
    description:
      "Validate tenant isolation, scrub PII patterns, and index grounded knowledge hashes.",
    default_tier: "tier1_auto",
    schedule_interval_sec: null,
    event_triggers: [],
  },
  {
    workflow_key: "improvement.offline_proposal",
    version: "1.0.0",
    group_name: "improvement_proposal",
    title: "Autonomous Improvement Hypothesis Draft",
    description:
      "Analyze evaluation reports for weak capabilities and draft offline proposals (never auto-mutates weights).",
    default_tier: "tier1_auto",
    schedule_interval_sec: null,
    event_triggers: ["evaluation.completed"],
  },
  {
    workflow_key: "security.integrity_audit",
    version: "1.0.0",
    group_name: "security_governance",
    title: "Security Configuration & Critical File Integrity Audit",
    description:
      "Check production secret requirements and verify SHA-256 digests of core API/Registry modules.",
    default_tier: "tier1_auto",
    schedule_interval_sec: 3600,
    event_triggers: ["auth.anomaly", "file.modified"],
  },
  {
    workflow_key: "project_dev.roadmap_sync",
    version: "1.0.0",
    group_name: "project_dev",
    title: "Roadmap 11–20 & Repository Readiness Audit",
    description:
      "Verify Roadmap 11–20 phase modules, v9 scripts, and block unapproved push/deploy actions.",
    default_tier: "tier1_auto",
    schedule_interval_sec: null,
    event_triggers: [],
  },
  {
    workflow_key: "project_dev.autonomous_maintainer",
    version: "1.0.0",
    group_name: "project_dev",
    title: "Autonomous Repository Maintainer (Audit -> PR Proposal -> Tier-2 Merge Gate)",
    description:
      "Tier-1 auto-audits code/security/dependencies and prepares verified PR drafts on isolated branches; merging into main strictly requires Tier-2 human approval.",
    default_tier: "tier2_approval",
    schedule_interval_sec: null,
    event_triggers: ["ci.failure", "security.alert"],
  },
];

function hashPassword(password: string): string {
  const salt = randomBytes(16).toString("hex");
  const derived = scryptSync(password, salt, 32).toString("hex");
  return `${salt}:${derived}`;
}

function verifyPassword(password: string, storedHash: string | null): boolean {
  if (!storedHash) return false;
  const [salt, expectedHex] = storedHash.split(":");
  if (!salt || !expectedHex) return false;
  const derived = scryptSync(password, salt, 32);
  const expected = Buffer.from(expectedHex, "hex");
  if (derived.length !== expected.length) return false;
  return timingSafeEqual(derived, expected);
}

function allowTestOAuthEndpoints(): boolean {
  return (
    (process.env.NODE_ENV === "test" || Boolean(process.env.VITEST)) &&
    process.env.ZYRQUEN_OAUTH_ALLOW_TEST_ENDPOINTS === "1"
  );
}

type OAuthProvider = "github" | "google";

function getOAuthProviderConfig(provider: OAuthProvider, origin: string) {
  const cleanOrigin = (origin || "http://localhost:3000").replace(/\/+$/, "");
  const callbackUrl = `${cleanOrigin}/api/backend/auth/oauth/${provider}/callback`;
  const useTest = allowTestOAuthEndpoints();

  if (provider === "github") {
    const clientId = (process.env.GITHUB_OAUTH_CLIENT_ID || "").trim();
    const clientSecret = (process.env.GITHUB_OAUTH_CLIENT_SECRET || "").trim();
    return {
      provider,
      name: "GitHub",
      configured: Boolean(clientId && clientSecret),
      clientId,
      clientSecret,
      scopes: ["read:user", "user:email"],
      callbackUrl,
      authorizeUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_AUTH_URL) ||
        "https://github.com/login/oauth/authorize",
      tokenUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_TOKEN_URL) ||
        "https://github.com/login/oauth/access_token",
      userUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_USER_URL) ||
        "https://api.github.com/user",
      emailsUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_EMAILS_URL) ||
        "https://api.github.com/user/emails",
    };
  }

  const clientId = (process.env.GOOGLE_OAUTH_CLIENT_ID || "").trim();
  const clientSecret = (process.env.GOOGLE_OAUTH_CLIENT_SECRET || "").trim();
  return {
    provider,
    name: "Google",
    configured: Boolean(clientId && clientSecret),
    clientId,
    clientSecret,
    scopes: ["openid", "email", "profile"],
    callbackUrl,
    authorizeUrl:
      (useTest && process.env.ZYRQUEN_GOOGLE_AUTH_URL) ||
      "https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl:
      (useTest && process.env.ZYRQUEN_GOOGLE_TOKEN_URL) ||
      "https://oauth2.googleapis.com/token",
    userInfoUrl:
      (useTest && process.env.ZYRQUEN_GOOGLE_USERINFO_URL) ||
      "https://openidconnect.googleapis.com/v1/userinfo",
  };
}

function issueEmailVerificationToken(
  store: InMemoryStore,
  user: StoredUser,
): string {
  const now = Date.now();
  for (const [hash, entry] of store.emailVerificationTokens.entries()) {
    if (entry.userId === user.id || entry.expiresAt <= now) {
      store.emailVerificationTokens.delete(hash);
    }
  }
  const rawToken = randomBytes(32).toString("base64url");
  const tokenHash = createHash("sha256").update(rawToken, "utf8").digest("hex");
  store.emailVerificationTokens.set(tokenHash, {
    tokenHash,
    userId: user.id,
    email: user.email,
    expiresAt: now + 24 * 60 * 60 * 1000,
  });
  return rawToken;
}

async function sendVerificationEmailIfConfigured(params: {
  to: string;
  rawToken: string;
  origin?: string;
}): Promise<{
  required: boolean;
  emailSent: boolean;
  deliveryReason: string | null;
}> {
  const apiKey = (process.env.RESEND_API_KEY || "").trim();
  const from = (process.env.EMAIL_FROM || "").trim();
  if (!apiKey || !from) {
    return {
      required: true,
      emailSent: false,
      deliveryReason: "EMAIL_PROVIDER_NOT_CONFIGURED",
    };
  }
  const cleanOrigin = (params.origin || "http://localhost:3000").replace(/\/+$/, "");
  const verifyUrl = `${cleanOrigin}/login?verify_token=${encodeURIComponent(params.rawToken)}`;
  try {
    const resp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from,
        to: [params.to],
        subject: "ยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ",
        text: `กรุณาคลิกลิงก์ด้านล่างเพื่อยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ (ลิงก์มีอายุ 24 ชั่วโมง):\n${verifyUrl}\n`,
        html: `<p>กรุณาคลิกลิงก์ด้านล่างเพื่อยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ (ลิงก์มีอายุ 24 ชั่วโมง):</p><p><a href="${verifyUrl}">Verify Email</a></p>`,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) {
      return {
        required: true,
        emailSent: false,
        deliveryReason: `EMAIL_PROVIDER_HTTP_${resp.status}`,
      };
    }
    return {
      required: true,
      emailSent: true,
      deliveryReason: null,
    };
  } catch {
    return {
      required: true,
      emailSent: false,
      deliveryReason: "EMAIL_SEND_FAILED",
    };
  }
}

export function getInMemoryVerificationTokenForTesting(
  email: string,
): string | null {
  if (process.env.NODE_ENV !== "test" && !process.env.VITEST) {
    return null;
  }
  const store = getStore();
  const userId = store.userIdByEmail.get(email.trim().toLowerCase());
  if (!userId) return null;
  const user = store.usersById.get(userId);
  if (!user) return null;
  return issueEmailVerificationToken(store, user);
}

function createInitialStore(): InMemoryStore {
  const now = new Date();
  const earlier = new Date(now.getTime() - 120_000).toISOString();
  const finished = new Date(now.getTime() - 95_000).toISOString();

  const demoUserId = randomUUID();
  const demoUser: StoredUser = {
    id: demoUserId,
    email: "demo@zyrquen.local",
    passwordHash: hashPassword("zyrquen-demo-pass"),
    role: "admin",
    isActive: true,
    emailVerified: true,
    createdAt: earlier,
  };

  const modelVersions: ModelVersionRecord[] = [
    {
      version: "ZYRQUEN-Native-v7",
      parent: null,
      lifecycle_status: "registered",
      created_at: "2026-10-10T08:00:00.000Z",
      frozen: false,
      checkpoint: { step: 0, sha256: "unverified-preview" },
      dataset: { version: "nagi-v7", content_sha256: "unverified-preview" },
      evaluation_evidence: null,
      compatibility: {
        version: "ZYRQUEN-Native-v7",
        compatible: true,
        checks: {
          artifacts_sha256: false,
          tokenizer_sha256: false,
          architecture_config: true,
        },
        reasons: ["Node.js preview sandbox: native Python evaluation not executed"],
      },
    },
    {
      version: "ZYRQUEN-Native-v8",
      parent: "ZYRQUEN-Native-v7",
      lifecycle_status: "registered",
      created_at: "2026-10-24T08:00:00.000Z",
      frozen: true,
      checkpoint: { step: 0, sha256: "unverified-preview" },
      dataset: { version: "nagi-v8", content_sha256: "unverified-preview" },
      evaluation_evidence: null,
      compatibility: {
        version: "ZYRQUEN-Native-v8",
        compatible: true,
        checks: {
          artifacts_sha256: false,
          tokenizer_sha256: false,
          architecture_config: true,
        },
        reasons: ["Node.js preview sandbox: native Python evaluation not executed"],
      },
    },
    {
      version: "ZYRQUEN-Native-v9",
      parent: "ZYRQUEN-Native-v8",
      lifecycle_status: "staging",
      created_at: "2026-11-05T08:00:00.000Z",
      frozen: false,
      checkpoint: { step: 0, sha256: "unverified-preview" },
      dataset: { version: "nagi-v9", content_sha256: "unverified-preview" },
      evaluation_evidence: null,
      compatibility: {
        version: "ZYRQUEN-Native-v9",
        compatible: true,
        checks: {
          artifacts_sha256: false,
          tokenizer_sha256: false,
          architecture_config: true,
        },
        reasons: ["Node.js preview sandbox: native Python evaluation not executed"],
      },
    },
    {
      version: "ZYRQUEN-Native-V10",
      parent: "ZYRQUEN-Native-v9",
      lifecycle_status: "registered",
      created_at: "2026-11-18T08:00:00.000Z",
      frozen: false,
      checkpoint: { step: 0, sha256: "unverified-preview" },
      dataset: { version: "nagi-v10", content_sha256: "unverified-preview" },
      evaluation_evidence: null,
      compatibility: {
        version: "ZYRQUEN-Native-V10",
        compatible: true,
        checks: {
          artifacts_sha256: false,
          tokenizer_sha256: false,
          architecture_config: true,
        },
        reasons: ["Node.js preview sandbox: native Python evaluation not executed"],
      },
    },
  ];

  const seedRun: WorkflowRunRecord = {
    id: randomUUID(),
    workflow_key: "evaluation.model_verification",
    workflow_version: "1.0.0",
    trigger_type: "manual",
    status: "BLOCKED",
    started_at: earlier,
    finished_at: finished,
    error_message: "PyTorch/Python Native EvaluationEngine is not attached in Node.js preview mode.",
    requested_by_user_id: demoUserId,
    steps: [
      {
        step_key: "verify_artifact",
        status: "BLOCKED",
        attempt: 1,
        started_at: earlier,
        finished_at: earlier,
        evidence: {
          verdict: "NOT RUN",
          summary: "No verified native checkpoint artifacts attached in Node.js preview",
        },
        output: { verified: false, torch_installed: false },
      },
      {
        step_key: "evaluate_gate",
        status: "BLOCKED",
        attempt: 1,
        started_at: earlier,
        finished_at: finished,
        evidence: {
          verdict: "NOT RUN",
          summary: "Evaluation skipped honestly (zero-mock policy: no fabricated metrics)",
        },
        output: null,
      },
    ],
  };

  return {
    usersById: new Map([[demoUserId, demoUser]]),
    userIdByEmail: new Map([[demoUser.email, demoUserId]]),
    tokens: new Map(),
    emailVerificationTokens: new Map(),
    oauthStates: new Map(),
    oauthIdentities: [],
    conversations: new Map(),
    usageRecords: [],
    apiKeys: new Map(),
    auditLogs: [
      {
        id: randomUUID(),
        actor_user_id: demoUserId,
        action: "runtime.initialized_in_memory",
        resource_id: "ZYRQUEN-Native-V10",
        created_at: earlier,
      },
    ],
    workflowRuns: [seedRun],
    workflowApprovals: [],
    modelVersions,
    activeModelVersion: "ZYRQUEN-Native-V10",
  };
}

const globalForStore = globalThis as typeof globalThis & {
  __zyrquenInMemoryStore?: InMemoryStore;
};

function getStore(): InMemoryStore {
  if (!globalForStore.__zyrquenInMemoryStore) {
    globalForStore.__zyrquenInMemoryStore = createInitialStore();
  }
  return globalForStore.__zyrquenInMemoryStore;
}

const globalForProbe = globalThis as typeof globalThis & {
  __zyrquenLocalApiProbe?: { baseUrl: string; available: boolean; checkedAt: number };
};

export async function shouldUseInMemoryBackend(
  baseUrl: string | null,
  hasExplicitExternalUrl: boolean,
  nodeEnvironment: string | undefined = process.env.NODE_ENV,
): Promise<boolean> {
  if (nodeEnvironment === "production") return false;
  if (!baseUrl) return !hasExplicitExternalUrl;
  if (hasExplicitExternalUrl) return false;

  const cached = globalForProbe.__zyrquenLocalApiProbe;
  if (
    cached &&
    cached.baseUrl === baseUrl &&
    Date.now() - cached.checkedAt < 10_000
  ) {
    return !cached.available;
  }

  let available = false;
  try {
    const res = await fetch(`${baseUrl}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(250),
    });
    if (res.ok) {
      const data = (await res.json().catch(() => null)) as {
        service?: unknown;
      } | null;
      available = data?.service === "zyrquen-api";
    }
  } catch {
    available = false;
  }

  globalForProbe.__zyrquenLocalApiProbe = {
    baseUrl,
    available,
    checkedAt: Date.now(),
  };
  return !available;
}

export function getInMemoryNativeHealth(): NativeHealth {
  const store = getStore();
  return {
    runtime_status: "blocked",
    native_model_loaded: false,
    authority: "ZYRQUEN Preview Sandbox (BLOCKED: Native Model Weights Not Loaded)",
    inference_available: false,
    platform_version: "V10 / Ω∞",
    platform_stage: "AI Studio Node.js Sandbox (BLOCKED · No Native Weights)",
    model_version: store.activeModelVersion,
    is_trained: false,
    progress_metrics: null,
    capabilities: [],
  };
}

function getClosureAudit(): V10ClosureAudit {
  const store = getStore();
  return {
    schema: "zyrquen.v10.closure_audit.v1",
    checked_at: new Date().toISOString(),
    overall_status: "BLOCKED",
    static_status: "STATIC PASS",
    runtime_status: "BLOCKED",
    contracts_passed_count: 5,
    contracts_total: 5,
    v11_gate: {
      target_version: "V11",
      unlocked: false,
      status: "LOCKED",
      prerequisite_summary:
        "Contracts 1–5 ผ่านเชิงโครงสร้าง แต่ยังไม่มีรันไทม์ PyTorch/Checkpoint จริงในโหมด Node.js Preview",
    },
    runtime_environment: {
      torch_installed: false,
      native_runtime_status: "not_configured",
      native_model_loaded: false,
      is_trained: false,
      active_model_version: store.activeModelVersion,
      eval_report_configured: false,
      eval_report_status: "NOT RUN",
      registry_configured: false,
      verified_v10_models: 0,
      dataset_configured: false,
      tokenizer_configured: false,
    },
    blockers: ["TORCH_NOT_INSTALLED", "TRAINED_V10_MODEL_UNAVAILABLE"],
    contracts: [
      {
        id: "C1",
        code: "CONTRACT-1",
        title: "Model Architecture & 5M CPU Budget",
        stage: "V10-A",
        status: "STATIC PASS",
        anchor: "apps/core/native/config.py::ZyrquenConfig",
        summary: "zyrquen-decoder budget verified (<= 5,000,000 parameters)",
        checks: [],
      },
      {
        id: "C2",
        code: "CONTRACT-2",
        title: "Slot-Safe Native Tokenizer",
        stage: "V10-A",
        status: "STATIC PASS",
        anchor: "apps/core/native/tokenizer.py::ZyrquenTokenizer",
        summary: "zyrquen.tokenizer.v2 atomic slots (IDs 4..35) verified",
        checks: [],
      },
      {
        id: "C3",
        code: "CONTRACT-3",
        title: "SFT Alignment & Ephemeral Slots",
        stage: "V10-A",
        status: "STATIC PASS",
        anchor: "apps/core/native/sft.py::encode_sft_pair",
        summary: "zyrquen.sft.v1 boundary and causal masking verified",
        checks: [],
      },
      {
        id: "C4",
        code: "CONTRACT-4",
        title: "Unified Dataset, Leakage Gate & Prepare Budget",
        stage: "V10-A",
        status: "STATIC PASS",
        anchor: "apps/core/training/orchestrator.py::TrainingOrchestrator",
        summary: "zyrquen.dataset-manifest.v1 and leakage audit verified",
        checks: [],
      },
      {
        id: "C5",
        code: "CONTRACT-5",
        title: "Streaming SFT Parity & Registry Gate",
        stage: "V10-A",
        status: "STATIC PASS",
        anchor: "apps/core/streaming.py::StreamingInferenceEngine",
        summary: "Streaming SFT prompt encoding & incremental decoder verified",
        checks: [],
      },
    ],
    stages: [
      {
        id: "V10-A",
        title: "Architecture & Data Contracts (C1–C5)",
        status: "STATIC PASS",
        summary: "Contracts 1–5 verified cleanly.",
        blockers: [],
      },
      {
        id: "V10-B",
        title: "Central Workflow & Registry Controls",
        status: "IMPLEMENTED",
        summary: "8 workflow groups and Model Registry lifecycle active in preview.",
        blockers: [],
      },
      {
        id: "V10-C",
        title: "Web & API Integration",
        status: "IMPLEMENTED",
        summary: "Next.js App Router & preview API adapter operational (no real PyTorch inference).",
        blockers: ["TORCH_NOT_INSTALLED"],
      },
      {
        id: "V10-D",
        title: "PyTorch CPU Training & Live Artifact Gate",
        status: "BLOCKED",
        summary: "Python/PyTorch runtime is not present in the Node.js preview.",
        blockers: ["TORCH_NOT_INSTALLED"],
      },
    ],
  };
}

function hashApiKeySecret(secret: string): string {
  return createHash("sha256").update(secret, "utf8").digest("hex");
}

function authenticateInferenceCaller(
  authorizationHeader: string | null,
): { user: StoredUser; apiKeyId: string | null } | null {
  if (!authorizationHeader) return null;
  const match = authorizationHeader.match(/^Bearer\s+(.+)$/i);
  if (!match) return null;
  const token = match[1].trim();
  const store = getStore();

  if (token.startsWith("zq_live_") || token.startsWith("zyr_")) {
    const digest = hashApiKeySecret(token);
    const nowMs = Date.now();
    for (const key of store.apiKeys.values()) {
      if (
        key.keyHash === digest &&
        key.revokedAt === null &&
        Date.parse(key.expiresAt) > nowMs
      ) {
        const user = store.usersById.get(key.userId);
        if (!user || !user.isActive) return null;
        return { user, apiKeyId: key.id };
      }
    }
    return null;
  }

  const entry = store.tokens.get(token);
  if (!entry) return null;
  if (entry.expiresAt < Date.now()) {
    store.tokens.delete(token);
    return null;
  }
  const user = store.usersById.get(entry.userId);
  if (!user || !user.isActive) return null;
  return { user, apiKeyId: null };
}

function parseJsonBody(rawBody?: string): Record<string, unknown> {
  if (!rawBody) return {};
  try {
    const parsed: unknown = JSON.parse(rawBody);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // fallback to empty object
  }
  return {};
}

// Strict Native-Only Policy: template or simulated neural responses are strictly prohibited.

function summarizeConversation(conv: StoredConversation) {
  return {
    id: conv.id,
    title: conv.title,
    created_at: conv.createdAt,
    updated_at: conv.updatedAt,
    message_count: conv.messages.length,
  };
}

const DAY_MS = 24 * 60 * 60 * 1000;

function parseAutoRotateSchedule(body: Record<string, unknown>):
  | { ok: true; enabled: boolean; intervalDays: number | null }
  | { ok: false; detail: string } {
  const enabled = Boolean(body.auto_rotate_enabled);
  if (!enabled) {
    return { ok: true, enabled: false, intervalDays: null };
  }
  const rawDays = body.auto_rotate_interval_days;
  if (
    typeof rawDays !== "number" ||
    !Number.isInteger(rawDays) ||
    rawDays < 1 ||
    rawDays > 365
  ) {
    return {
      ok: false,
      detail: "รอบเวลา Auto-rotate ต้องเป็นจำนวนเต็มระหว่าง 1 ถึง 365 วัน",
    };
  }
  return { ok: true, enabled: true, intervalDays: rawDays };
}

function serializeApiKey(k: StoredApiKey) {
  return {
    id: k.id,
    name: k.name,
    key_prefix: k.keyPrefix,
    scope: k.scope,
    created_at: k.createdAt,
    expires_at: k.expiresAt,
    revoked_at: k.revokedAt,
    auto_rotate_enabled: Boolean(k.autoRotateEnabled),
    auto_rotate_interval_days: k.autoRotateIntervalDays ?? null,
    last_rotated_at: k.lastRotatedAt ?? null,
    next_rotation_at: k.nextRotationAt ?? null,
    rotation_count: k.rotationCount ?? 0,
  };
}

function rotateStoredApiKey(
  store: InMemoryStore,
  entry: StoredApiKey,
  actorUserId: string,
  action: "api_key.rotated" | "api_key.auto_rotated",
): string {
  const nowMs = Date.now();
  const nowIso = new Date(nowMs).toISOString();
  const secret = `zq_live_${randomBytes(18).toString("hex")}`;
  entry.keyPrefix = secret.slice(0, 12);
  entry.keyHash = hashApiKeySecret(secret);
  entry.lastRotatedAt = nowIso;
  entry.rotationCount = (entry.rotationCount ?? 0) + 1;

  const intervalMs =
    entry.autoRotateEnabled && entry.autoRotateIntervalDays
      ? entry.autoRotateIntervalDays * DAY_MS
      : 0;
  entry.nextRotationAt = intervalMs
    ? new Date(nowMs + intervalMs).toISOString()
    : null;

  const fallbackValidity = Math.max(
    entry.validityDurationMs || 30 * DAY_MS,
    intervalMs,
  );
  const currentExpiryMs = Date.parse(entry.expiresAt);
  if (Number.isNaN(currentExpiryMs) || currentExpiryMs < nowMs + fallbackValidity) {
    entry.expiresAt = new Date(nowMs + fallbackValidity).toISOString();
  }

  store.auditLogs.unshift({
    id: randomUUID(),
    actor_user_id: actorUserId,
    action,
    resource_id: entry.id,
    created_at: nowIso,
  });
  return secret;
}

function applyDueAutoRotations(store: InMemoryStore, userId: string): void {
  const nowMs = Date.now();
  for (const entry of store.apiKeys.values()) {
    if (
      entry.userId !== userId ||
      entry.revokedAt !== null ||
      !entry.autoRotateEnabled ||
      !entry.autoRotateIntervalDays ||
      !entry.nextRotationAt
    ) {
      continue;
    }
    const dueMs = Date.parse(entry.nextRotationAt);
    if (!Number.isNaN(dueMs) && dueMs <= nowMs) {
      rotateStoredApiKey(store, entry, userId, "api_key.auto_rotated");
    }
  }
}

function buildUserUsageStats(userId: string) {
  const store = getStore();
  const records = store.usageRecords.filter((r) => r.userId === userId);
  const completed = records.filter((r) => r.status === "completed");
  const inputTokens = completed.reduce((acc, r) => acc + r.inputTokens, 0);
  const outputTokens = completed.reduce((acc, r) => acc + r.outputTokens, 0);
  const updatedAt = completed[0]?.completedAt ?? null;
  return {
    records,
    successfulRequests: completed.length,
    inputTokens,
    outputTokens,
    totalTokens: inputTokens + outputTokens,
    updatedAt,
  };
}

export async function handleInMemoryBackendRequest(options: {
  method: string;
  path: string;
  searchParams?: URLSearchParams;
  authorizationHeader: string | null;
  rawBody?: string;
  origin?: string;
}): Promise<InMemoryResponse> {
  const method = options.method.toUpperCase();
  const path = options.path.replace(/^\/+/, "");
  const store = getStore();
  const nativeHealth = getInMemoryNativeHealth();
  const requestOrigin = (
    options.origin ||
    options.searchParams?.get("origin") ||
    "http://localhost:3000"
  ).replace(/\/+$/, "");

  if (method === "GET" && path === "") {
    return {
      status: 200,
      body: {
        platform: "ZYRQUEN Ω∞",
        status: "running",
        mode: "in-memory-sandbox",
        native_ai: nativeHealth,
      },
    };
  }

  if (method === "GET" && path === "health") {
    return {
      status: 200,
      body: {
        status: "healthy",
        service: "zyrquen-api",
        database: { status: "in_memory" },
        native_ai: nativeHealth,
      },
    };
  }

  if (method === "GET" && path === "v1/native-ai/health") {
    return { status: 200, body: nativeHealth };
  }

  if (method === "GET" && path === "v1/v10/closure-audit") {
    return { status: 200, body: getClosureAudit() };
  }

  if (method === "POST" && path === "auth/register") {
    const body = parseJsonBody(options.rawBody);
    const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body.password === "string" ? body.password : "";
    if (!email || !email.includes("@")) {
      return { status: 422, body: { detail: "Invalid email" } };
    }
    if (password.length < 12 || password.length > 128) {
      return {
        status: 422,
        body: { detail: "Password must be 12–128 characters" },
      };
    }
    if (store.userIdByEmail.has(email)) {
      return { status: 409, body: { detail: "Email already registered" } };
    }
    const id = randomUUID();
    const createdAt = new Date().toISOString();
    const user: StoredUser = {
      id,
      email,
      passwordHash: hashPassword(password),
      role: "user",
      isActive: true,
      emailVerified: false,
      createdAt,
    };
    store.usersById.set(id, user);
    store.userIdByEmail.set(email, id);
    const rawVerifyToken = issueEmailVerificationToken(store, user);
    const verification = await sendVerificationEmailIfConfigured({
      to: user.email,
      rawToken: rawVerifyToken,
      origin: requestOrigin,
    });
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: id,
      action: "user.registered",
      resource_id: id,
      created_at: createdAt,
    });
    return {
      status: 200,
      body: {
        id: user.id,
        email: user.email,
        role: user.role,
        is_active: user.isActive,
        email_verified: user.emailVerified,
        created_at: user.createdAt,
        verification,
      },
    };
  }

  if (method === "POST" && path === "auth/verify-email") {
    const body = parseJsonBody(options.rawBody);
    const rawToken = typeof body.token === "string" ? body.token.trim() : "";
    if (!rawToken || rawToken.length < 16 || rawToken.length > 512) {
      return { status: 400, body: { detail: "โทเคนยืนยันอีเมลไม่ถูกต้อง" } };
    }
    const tokenHash = createHash("sha256").update(rawToken, "utf8").digest("hex");
    const entry = store.emailVerificationTokens.get(tokenHash);
    if (!entry || entry.expiresAt <= Date.now()) {
      if (entry) store.emailVerificationTokens.delete(tokenHash);
      return {
        status: 400,
        body: { detail: "ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว" },
      };
    }
    store.emailVerificationTokens.delete(tokenHash);
    const user = store.usersById.get(entry.userId);
    if (!user || !user.isActive) {
      return { status: 404, body: { detail: "ไม่พบบัญชีผู้ใช้" } };
    }
    user.emailVerified = true;
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: user.id,
      action: "auth.email_verified",
      resource_id: user.id,
      created_at: new Date().toISOString(),
    });
    return {
      status: 200,
      body: {
        ok: true,
        email_verified: true,
        user: {
          id: user.id,
          email: user.email,
          role: user.role,
          is_active: user.isActive,
          email_verified: user.emailVerified,
          created_at: user.createdAt,
        },
      },
    };
  }

  if (method === "GET" && path === "auth/providers") {
    const googleCfg = getOAuthProviderConfig("google", requestOrigin);
    const githubCfg = getOAuthProviderConfig("github", requestOrigin);
    return {
      status: 200,
      body: {
        providers: {
          google: { configured: googleCfg.configured, name: googleCfg.name },
          github: { configured: githubCfg.configured, name: githubCfg.name },
        },
      },
    };
  }

  const oauthUrlMatch = path.match(/^auth\/oauth\/(google|github)\/url$/i);
  if (method === "GET" && oauthUrlMatch) {
    const provider = oauthUrlMatch[1].toLowerCase() as OAuthProvider;
    const intent =
      options.searchParams?.get("intent") === "link" ? "link" : "login";
    let linkUserId: string | null = null;
    if (intent === "link") {
      const caller = authenticateInferenceCaller(options.authorizationHeader);
      if (!caller || caller.apiKeyId !== null) {
        return {
          status: 401,
          body: { detail: "กรุณาเข้าสู่ระบบก่อนเชื่อมต่อบัญชีภายนอก" },
        };
      }
      linkUserId = caller.user.id;
    }

    const cfg = getOAuthProviderConfig(provider, requestOrigin);
    if (!cfg.configured) {
      return {
        status: 503,
        body: {
          code: "OAUTH_NOT_CONFIGURED",
          provider,
          callbackUrl: cfg.callbackUrl,
          detail: `ยังไม่ได้ตั้งค่าการเข้าสู่ระบบผ่าน ${cfg.name} OAuth 2.0 ใน Backend นี้`,
        },
      };
    }

    const now = Date.now();
    for (const [k, v] of store.oauthStates.entries()) {
      if (v.expiresAt <= now) store.oauthStates.delete(k);
    }

    const state = randomBytes(24).toString("base64url");
    const codeVerifier = randomBytes(32).toString("base64url");
    const codeChallenge = createHash("sha256")
      .update(codeVerifier, "ascii")
      .digest("base64url");

    store.oauthStates.set(state, {
      state,
      provider,
      intent,
      userId: linkUserId,
      redirectUri: cfg.callbackUrl,
      codeVerifier,
      origin: requestOrigin,
      expiresAt: now + 10 * 60 * 1000,
    });

    const params = new URLSearchParams({
      client_id: cfg.clientId,
      redirect_uri: cfg.callbackUrl,
      response_type: "code",
      scope: cfg.scopes.join(" "),
      state,
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
    });
    if (provider === "google") {
      params.set("prompt", "select_account");
    }

    return {
      status: 200,
      body: {
        url: `${cfg.authorizeUrl}?${params.toString()}`,
        provider,
        callbackUrl: cfg.callbackUrl,
      },
    };
  }

  const oauthCallbackMatch = path.match(
    /^auth\/oauth\/(google|github)\/callback$/i,
  );
  if (method === "GET" && oauthCallbackMatch) {
    const provider = oauthCallbackMatch[1].toLowerCase() as OAuthProvider;
    const providerErr =
      options.searchParams?.get("error_description") ||
      options.searchParams?.get("error");
    if (providerErr) {
      return {
        status: 400,
        body: {
          ok: false,
          provider,
          error: providerErr,
          detail: providerErr,
        },
      };
    }

    const rawState = options.searchParams?.get("state")?.trim() || "";
    const stateEntry = rawState ? store.oauthStates.get(rawState) : undefined;
    if (rawState) store.oauthStates.delete(rawState);

    if (
      !stateEntry ||
      stateEntry.provider !== provider ||
      stateEntry.expiresAt <= Date.now()
    ) {
      return {
        status: 400,
        body: {
          ok: false,
          provider,
          detail: "OAuth state ไม่ถูกต้องหรือหมดอายุ กรุณาลองใหม่อีกครั้ง",
        },
      };
    }

    const code = options.searchParams?.get("code")?.trim() || "";
    if (!code) {
      return {
        status: 400,
        body: {
          ok: false,
          provider,
          detail: "ไม่ได้รับ Authorization Code จากผู้ให้บริการ",
        },
      };
    }

    const cfg = getOAuthProviderConfig(provider, stateEntry.origin);
    if (!cfg.configured) {
      return {
        status: 503,
        body: {
          ok: false,
          provider,
          code: "OAUTH_NOT_CONFIGURED",
          detail: `ยังไม่ได้ตั้งค่า ${cfg.name} OAuth 2.0 ใน Backend นี้`,
        },
      };
    }

    try {
      let providerUserId = "";
      let providerEmail = "";
      let providerEmailVerified = false;
      let providerDisplayName: string | null = null;
      let providerAvatarUrl: string | null = null;

      if (provider === "github") {
        const tokenResp = await fetch(cfg.tokenUrl, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams({
            client_id: cfg.clientId,
            client_secret: cfg.clientSecret,
            code,
            redirect_uri: stateEntry.redirectUri,
            code_verifier: stateEntry.codeVerifier,
          }).toString(),
          signal: AbortSignal.timeout(12_000),
        });
        const tokenJson = (await tokenResp.json().catch(() => ({}))) as {
          access_token?: string;
          error_description?: string;
          error?: string;
        };
        if (!tokenResp.ok || !tokenJson.access_token) {
          return {
            status: 400,
            body: {
              ok: false,
              provider,
              detail:
                tokenJson.error_description ||
                tokenJson.error ||
                "GitHub token exchange failed",
            },
          };
        }
        const ghHeaders = {
          Authorization: `Bearer ${tokenJson.access_token}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "ZYRQUEN-Platform",
        };
        const [userResp, emailsResp] = await Promise.all([
          fetch(cfg.userUrl!, { headers: ghHeaders, signal: AbortSignal.timeout(10_000) }),
          fetch(cfg.emailsUrl!, { headers: ghHeaders, signal: AbortSignal.timeout(10_000) }),
        ]);
        if (!userResp.ok) {
          return {
            status: 502,
            body: {
              ok: false,
              provider,
              detail: `GitHub user lookup failed (${userResp.status})`,
            },
          };
        }
        const ghUser = (await userResp.json()) as {
          id?: number | string;
          login?: string;
          name?: string;
          email?: string;
          avatar_url?: string;
        };
        providerUserId = ghUser.id !== undefined ? String(ghUser.id) : "";
        providerDisplayName =
          String(ghUser.name || ghUser.login || "").trim() || null;
        providerAvatarUrl = String(ghUser.avatar_url || "").trim() || null;

        if (emailsResp.ok) {
          const emails = (await emailsResp.json().catch(() => [])) as Array<{
            email?: string;
            primary?: boolean;
            verified?: boolean;
          }>;
          const preferred =
            emails.find((e) => e.primary && e.verified) ||
            emails.find((e) => e.verified) ||
            emails.find((e) => e.primary) ||
            emails[0];
          if (preferred?.email) {
            providerEmail = String(preferred.email).trim().toLowerCase();
            providerEmailVerified = Boolean(preferred.verified);
          }
        }
        if (!providerEmail && ghUser.email) {
          providerEmail = String(ghUser.email).trim().toLowerCase();
          providerEmailVerified = false;
        }
      } else {
        const tokenResp = await fetch(cfg.tokenUrl, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams({
            client_id: cfg.clientId,
            client_secret: cfg.clientSecret,
            code,
            redirect_uri: stateEntry.redirectUri,
            code_verifier: stateEntry.codeVerifier,
            grant_type: "authorization_code",
          }).toString(),
          signal: AbortSignal.timeout(12_000),
        });
        const tokenJson = (await tokenResp.json().catch(() => ({}))) as {
          access_token?: string;
          error_description?: string;
          error?: string;
        };
        if (!tokenResp.ok || !tokenJson.access_token) {
          return {
            status: 400,
            body: {
              ok: false,
              provider,
              detail:
                tokenJson.error_description ||
                tokenJson.error ||
                "Google token exchange failed",
            },
          };
        }
        const infoResp = await fetch(cfg.userInfoUrl!, {
          headers: {
            Authorization: `Bearer ${tokenJson.access_token}`,
            Accept: "application/json",
          },
          signal: AbortSignal.timeout(10_000),
        });
        if (!infoResp.ok) {
          return {
            status: 502,
            body: {
              ok: false,
              provider,
              detail: `Google userinfo lookup failed (${infoResp.status})`,
            },
          };
        }
        const gUser = (await infoResp.json()) as {
          sub?: string;
          email?: string;
          email_verified?: boolean;
          name?: string;
          picture?: string;
        };
        providerUserId = String(gUser.sub || "").trim();
        providerEmail = String(gUser.email || "").trim().toLowerCase();
        providerEmailVerified = Boolean(gUser.email_verified);
        providerDisplayName = String(gUser.name || "").trim() || null;
        providerAvatarUrl = String(gUser.picture || "").trim() || null;
      }

      if (!providerUserId) {
        return {
          status: 502,
          body: {
            ok: false,
            provider,
            detail: "ผู้ให้บริการ OAuth ไม่ได้ส่งรหัสบัญชีผู้ใช้กลับมา",
          },
        };
      }

      const nowIso = new Date().toISOString();

      if (stateEntry.intent === "link" && stateEntry.userId) {
        const targetUser = store.usersById.get(stateEntry.userId);
        if (!targetUser || !targetUser.isActive) {
          return {
            status: 403,
            body: { ok: false, provider, detail: "ไม่พบบัญชีผู้ใช้หรือบัญชีถูกปิดใช้งาน" },
          };
        }
        const existingConflict = store.oauthIdentities.find(
          (i) =>
            i.provider === provider &&
            i.providerUserId === providerUserId &&
            i.userId !== targetUser.id,
        );
        if (existingConflict) {
          return {
            status: 409,
            body: {
              ok: false,
              provider,
              code: "IDENTITY_ALREADY_LINKED",
              detail: `บัญชี ${cfg.name} นี้ถูกเชื่อมต่อกับบัญชี ZYRQUEN อื่นแล้ว`,
            },
          };
        }
        let identity = store.oauthIdentities.find(
          (i) => i.provider === provider && i.userId === targetUser.id,
        );
        if (identity) {
          identity.providerUserId = providerUserId;
          identity.providerEmail = providerEmail || null;
          identity.emailVerified = providerEmailVerified;
          identity.displayName = providerDisplayName;
          identity.avatarUrl = providerAvatarUrl;
          identity.linkedAt = nowIso;
        } else {
          identity = {
            id: randomUUID(),
            userId: targetUser.id,
            provider,
            providerUserId,
            providerEmail: providerEmail || null,
            emailVerified: providerEmailVerified,
            displayName: providerDisplayName,
            avatarUrl: providerAvatarUrl,
            linkedAt: nowIso,
          };
          store.oauthIdentities.push(identity);
        }
        if (
          providerEmailVerified &&
          providerEmail &&
          providerEmail === targetUser.email
        ) {
          targetUser.emailVerified = true;
        }
        store.auditLogs.unshift({
          id: randomUUID(),
          actor_user_id: targetUser.id,
          action: "auth.identity_linked",
          resource_id: `${provider}:${providerUserId}`,
          created_at: nowIso,
        });
        return {
          status: 200,
          body: {
            ok: true,
            intent: "link",
            provider,
            identity: {
              id: identity.id,
              provider: identity.provider,
              provider_user_id: identity.providerUserId,
              provider_email: identity.providerEmail,
              email_verified: identity.emailVerified,
              display_name: identity.displayName,
              avatar_url: identity.avatarUrl,
              linked_at: identity.linkedAt,
            },
          },
        };
      }

      let identity = store.oauthIdentities.find(
        (i) => i.provider === provider && i.providerUserId === providerUserId,
      );
      let user: StoredUser | undefined = identity
        ? store.usersById.get(identity.userId)
        : undefined;

      if (!user) {
        if (!providerEmail) {
          return {
            status: 403,
            body: {
              ok: false,
              provider,
              detail: `บัญชี ${cfg.name} นี้ไม่ได้เปิดเผยอีเมล กรุณาอนุญาตสิทธิ์การเข้าถึงอีเมล`,
            },
          };
        }
        const existingUserId = store.userIdByEmail.get(providerEmail);
        if (existingUserId) {
          if (!providerEmailVerified) {
            return {
              status: 403,
              body: {
                ok: false,
                provider,
                detail: `อีเมล ${providerEmail} จาก ${cfg.name} ยังไม่ได้รับการยืนยัน จึงไม่สามารถเชื่อมกับบัญชีที่มีอยู่โดยอัตโนมัติได้`,
              },
            };
          }
          user = store.usersById.get(existingUserId);
          if (user) {
            user.emailVerified = true;
          }
        } else {
          const newUserId = randomUUID();
          user = {
            id: newUserId,
            email: providerEmail,
            passwordHash: null,
            role: "user",
            isActive: true,
            emailVerified: providerEmailVerified,
            createdAt: nowIso,
          };
          store.usersById.set(newUserId, user);
          store.userIdByEmail.set(providerEmail, newUserId);
          store.auditLogs.unshift({
            id: randomUUID(),
            actor_user_id: newUserId,
            action: "user.registered_oauth",
            resource_id: `${provider}:${providerUserId}`,
            created_at: nowIso,
          });
        }

        if (user && !identity) {
          identity = {
            id: randomUUID(),
            userId: user.id,
            provider,
            providerUserId,
            providerEmail,
            emailVerified: providerEmailVerified,
            displayName: providerDisplayName,
            avatarUrl: providerAvatarUrl,
            linkedAt: nowIso,
          };
          store.oauthIdentities.push(identity);
        }
      }

      if (!user || !user.isActive) {
        return {
          status: 403,
          body: { ok: false, provider, detail: "Account disabled" },
        };
      }

      const token = randomBytes(32).toString("hex");
      store.tokens.set(token, {
        userId: user.id,
        expiresAt: Date.now() + 30 * 60 * 1000,
      });
      store.auditLogs.unshift({
        id: randomUUID(),
        actor_user_id: user.id,
        action: "auth.oauth_login",
        resource_id: `${provider}:${providerUserId}`,
        created_at: nowIso,
      });

      return {
        status: 200,
        body: {
          ok: true,
          intent: "login",
          provider,
          access_token: token,
          token_type: "bearer",
          email: user.email,
          user: {
            id: user.id,
            email: user.email,
            role: user.role,
            is_active: user.isActive,
            email_verified: user.emailVerified,
            created_at: user.createdAt,
          },
        },
      };
    } catch (reason) {
      return {
        status: 500,
        body: {
          ok: false,
          provider,
          detail:
            reason instanceof Error
              ? reason.message
              : "OAuth authentication failed",
        },
      };
    }
  }

  if (method === "POST" && path === "auth/login") {
    const body = parseJsonBody(options.rawBody);
    const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body.password === "string" ? body.password : "";
    const userId = store.userIdByEmail.get(email);
    const user = userId ? store.usersById.get(userId) : undefined;
    if (!user || !verifyPassword(password, user.passwordHash)) {
      return { status: 401, body: { detail: "Invalid email or password" } };
    }
    if (!user.isActive) {
      return { status: 403, body: { detail: "Account disabled" } };
    }
    const token = randomBytes(32).toString("hex");
    store.tokens.set(token, {
      userId: user.id,
      expiresAt: Date.now() + 30 * 60 * 1000,
    });
    return {
      status: 200,
      body: {
        access_token: token,
        token_type: "bearer",
      },
    };
  }

  const caller = authenticateInferenceCaller(options.authorizationHeader);
  const isInferRoute =
    method === "POST" &&
    (path === "v1/native-ai/infer" || path === "v1/native-ai/infer/stream");
  const currentUser = caller && (isInferRoute || caller.apiKeyId === null)
    ? caller.user
    : null;
  const callerApiKeyId = caller?.apiKeyId ?? null;
  if (!currentUser) {
    return { status: 401, body: { detail: "Not authenticated" } };
  }

  if (method === "GET" && path === "auth/me") {
    return {
      status: 200,
      body: {
        id: currentUser.id,
        email: currentUser.email,
        role: currentUser.role,
        is_active: currentUser.isActive,
        email_verified: currentUser.emailVerified,
        created_at: currentUser.createdAt,
      },
    };
  }

  if (method === "GET" && path === "auth/identities") {
    const identities = store.oauthIdentities
      .filter((i) => i.userId === currentUser.id)
      .map((i) => ({
        id: i.id,
        provider: i.provider,
        provider_user_id: i.providerUserId,
        provider_email: i.providerEmail,
        email_verified: i.emailVerified,
        display_name: i.displayName,
        avatar_url: i.avatarUrl,
        linked_at: i.linkedAt,
      }));
    return { status: 200, body: { identities } };
  }

  const unlinkMatch = path.match(/^auth\/identities\/(google|github)$/i);
  if (method === "DELETE" && unlinkMatch) {
    const provider = unlinkMatch[1].toLowerCase() as OAuthProvider;
    const userIdentities = store.oauthIdentities.filter(
      (i) => i.userId === currentUser.id,
    );
    const targetIdx = store.oauthIdentities.findIndex(
      (i) => i.userId === currentUser.id && i.provider === provider,
    );
    if (targetIdx === -1) {
      return { status: 404, body: { detail: "ไม่พบการเชื่อมต่อบัญชีภายนอกนี้" } };
    }
    if (!currentUser.passwordHash && userIdentities.length <= 1) {
      return {
        status: 409,
        body: {
          detail:
            "ไม่สามารถยกเลิกการเชื่อมต่อวิธีเข้าสู่ระบบสุดท้ายได้ กรุณาเชื่อมบัญชีอื่นก่อน",
        },
      };
    }
    const [removed] = store.oauthIdentities.splice(targetIdx, 1);
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: currentUser.id,
      action: "auth.identity_unlinked",
      resource_id: `${provider}:${removed.providerUserId}`,
      created_at: new Date().toISOString(),
    });
    return { status: 200, body: { ok: true, provider } };
  }

  if (method === "POST" && path === "auth/verification/resend") {
    if (currentUser.emailVerified) {
      return {
        status: 200,
        body: {
          ok: true,
          alreadyVerified: true,
          email_verified: true,
          emailSent: false,
          deliveryReason: null,
          detail: "อีเมลนี้ได้รับการยืนยันแล้ว",
        },
      };
    }
    const rawVerifyToken = issueEmailVerificationToken(store, currentUser);
    const verification = await sendVerificationEmailIfConfigured({
      to: currentUser.email,
      rawToken: rawVerifyToken,
      origin: requestOrigin,
    });
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: currentUser.id,
      action: "auth.verification_resend",
      resource_id: currentUser.id,
      created_at: new Date().toISOString(),
    });
    return {
      status: 200,
      body: {
        ok: true,
        alreadyVerified: false,
        email_verified: currentUser.emailVerified,
        emailSent: verification.emailSent,
        deliveryReason: verification.deliveryReason,
        detail: verification.emailSent
          ? "ส่งลิงก์ยืนยันอีเมลแล้ว กรุณาตรวจสอบกล่องจดหมายของคุณ"
          : "ไม่สามารถส่งอีเมลยืนยันอัตโนมัติได้ในโหมด Sandbox (ยังไม่ได้ตั้งค่า RESEND_API_KEY)",
      },
    };
  }

  if (method === "POST" && path === "auth/logout") {
    const token = options.authorizationHeader?.replace(/^Bearer\s+/i, "").trim();
    if (token) {
      store.tokens.delete(token);
    }
    return { status: 200, body: { authenticated: false, revoked: true } };
  }

  if (method === "GET" && path === "users/me") {
    return {
      status: 200,
      body: { id: currentUser.id, email: currentUser.email },
    };
  }

  if (method === "PATCH" && path === "users/me") {
    const body = parseJsonBody(options.rawBody);
    const nextEmail = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
    if (!nextEmail || !nextEmail.includes("@")) {
      return { status: 422, body: { detail: "กรุณากรอกอีเมลให้ถูกต้อง" } };
    }
    const existingOwner = store.userIdByEmail.get(nextEmail);
    if (existingOwner && existingOwner !== currentUser.id) {
      return { status: 409, body: { detail: "อีเมลนี้ถูกใช้งานแล้ว" } };
    }
    store.userIdByEmail.delete(currentUser.email);
    currentUser.email = nextEmail;
    store.userIdByEmail.set(nextEmail, currentUser.id);
    return {
      status: 200,
      body: { id: currentUser.id, email: currentUser.email },
    };
  }

  if (method === "GET" && path === "users/me/usage") {
    const stats = buildUserUsageStats(currentUser.id);
    return {
      status: 200,
      body: {
        successful_requests: stats.successfulRequests,
        input_tokens: stats.inputTokens,
        output_tokens: stats.outputTokens,
        total_tokens: stats.totalTokens,
        updated_at: stats.updatedAt,
        records: stats.records.slice(0, 25).map((r) => ({
          request_id: r.requestId,
          status: r.status,
          input_tokens: r.inputTokens,
          output_tokens: r.outputTokens,
          total_tokens: r.totalTokens,
          model_version: r.modelVersion,
          created_at: r.createdAt,
          completed_at: r.completedAt,
        })),
      },
    };
  }

  if (method === "GET" && path === "users/me/quota") {
    const stats = buildUserUsageStats(currentUser.id);
    return {
      status: 200,
      body: {
        configured: true,
        active: true,
        max_requests: 1000,
        max_input_tokens: 250000,
        max_output_tokens: 100000,
        max_total_tokens: 350000,
        window_started_at: currentUser.createdAt,
        window_ends_at: null,
        successful_requests: stats.successfulRequests,
        running_requests: 0,
        requests_in_use: 0,
        input_tokens: stats.inputTokens,
        output_tokens: stats.outputTokens,
        total_tokens: stats.totalTokens,
      },
    };
  }

  if (path === "users/me/api-keys") {
    if (method === "GET") {
      applyDueAutoRotations(store, currentUser.id);
      const keys = [...store.apiKeys.values()]
        .filter((k) => k.userId === currentUser.id)
        .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
        .map(serializeApiKey);
      return { status: 200, body: keys };
    }
    if (method === "POST") {
      const body = parseJsonBody(options.rawBody);
      const name = typeof body.name === "string" ? body.name.trim() : "";
      const expiresAt = typeof body.expires_at === "string" ? body.expires_at : "";
      const expiryMs = Date.parse(expiresAt);
      if (!name || !expiresAt || Number.isNaN(expiryMs) || expiryMs <= Date.now()) {
        return {
          status: 422,
          body: { detail: "กรุณาระบุชื่อและวันหมดอายุในอนาคตของ API Key" },
        };
      }
      const schedule = parseAutoRotateSchedule(body);
      if (!schedule.ok) {
        return { status: 422, body: { detail: schedule.detail } };
      }
      const id = randomUUID();
      const secret = `zq_live_${randomBytes(18).toString("hex")}`;
      const nowMs = Date.now();
      const createdAt = new Date(nowMs).toISOString();
      const nextRotationAt =
        schedule.enabled && schedule.intervalDays
          ? new Date(nowMs + schedule.intervalDays * DAY_MS).toISOString()
          : null;
      const entry: StoredApiKey = {
        id,
        userId: currentUser.id,
        name,
        keyPrefix: secret.slice(0, 12),
        keyHash: hashApiKeySecret(secret),
        scope: "inference:read_write",
        createdAt,
        expiresAt: new Date(expiryMs).toISOString(),
        revokedAt: null,
        autoRotateEnabled: schedule.enabled,
        autoRotateIntervalDays: schedule.intervalDays,
        lastRotatedAt: null,
        nextRotationAt,
        rotationCount: 0,
        validityDurationMs: Math.max(DAY_MS, expiryMs - nowMs),
      };
      store.apiKeys.set(id, entry);
      store.auditLogs.unshift({
        id: randomUUID(),
        actor_user_id: currentUser.id,
        action: "api_key.created",
        resource_id: id,
        created_at: createdAt,
      });
      return {
        status: 201,
        body: {
          ...serializeApiKey(entry),
          key: secret,
        },
      };
    }
  }

  if (method === "POST" && path === "users/me/api-keys/bulk-revoke") {
    const body = parseJsonBody(options.rawBody);
    const rawIds = Array.isArray(body.ids) ? body.ids : [];
    const ids = [...new Set(rawIds.filter((v): v is string => typeof v === "string" && v.trim().length > 0))];
    if (ids.length === 0 || ids.length > 100) {
      return {
        status: 422,
        body: { detail: "กรุณาระบุรายการ API Key ที่ต้องการเพิกถอน (1–100 รายการ)" },
      };
    }
    const nowIso = new Date().toISOString();
    const revokedIds: string[] = [];
    for (const keyId of ids) {
      const key = store.apiKeys.get(keyId);
      if (key && key.userId === currentUser.id && key.revokedAt === null) {
        key.revokedAt = nowIso;
        key.autoRotateEnabled = false;
        key.nextRotationAt = null;
        revokedIds.push(key.id);
        store.auditLogs.unshift({
          id: randomUUID(),
          actor_user_id: currentUser.id,
          action: "api_key.bulk_revoked",
          resource_id: key.id,
          created_at: nowIso,
        });
      }
    }
    return {
      status: 200,
      body: {
        revoked_ids: revokedIds,
        revoked_count: revokedIds.length,
      },
    };
  }

  const apiKeyAutoRotateMatch = path.match(
    /^users\/me\/api-keys\/([^/]+)\/auto-rotate$/i,
  );
  if (method === "PATCH" && apiKeyAutoRotateMatch) {
    const key = store.apiKeys.get(apiKeyAutoRotateMatch[1]);
    if (!key || key.userId !== currentUser.id) {
      return { status: 404, body: { detail: "ไม่พบ API Key" } };
    }
    if (key.revokedAt) {
      return {
        status: 409,
        body: { detail: "ไม่สามารถตั้งค่า Auto-rotate ให้ API Key ที่ถูกเพิกถอนแล้ว" },
      };
    }
    const body = parseJsonBody(options.rawBody);
    const schedule = parseAutoRotateSchedule(body);
    if (!schedule.ok) {
      return { status: 422, body: { detail: schedule.detail } };
    }
    const nowMs = Date.now();
    const nowIso = new Date(nowMs).toISOString();
    key.autoRotateEnabled = schedule.enabled;
    key.autoRotateIntervalDays = schedule.intervalDays;
    key.nextRotationAt =
      schedule.enabled && schedule.intervalDays
        ? new Date(nowMs + schedule.intervalDays * DAY_MS).toISOString()
        : null;
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: currentUser.id,
      action: "api_key.auto_rotate_updated",
      resource_id: key.id,
      created_at: nowIso,
    });
    return { status: 200, body: serializeApiKey(key) };
  }

  const apiKeyRotateMatch = path.match(/^users\/me\/api-keys\/([^/]+)\/rotate$/i);
  if (method === "POST" && apiKeyRotateMatch) {
    const key = store.apiKeys.get(apiKeyRotateMatch[1]);
    if (!key || key.userId !== currentUser.id) {
      return { status: 404, body: { detail: "ไม่พบ API Key" } };
    }
    if (key.revokedAt) {
      return {
        status: 409,
        body: { detail: "ไม่สามารถหมุนเวียน API Key ที่ถูกเพิกถอนแล้ว" },
      };
    }
    const secret = rotateStoredApiKey(
      store,
      key,
      currentUser.id,
      "api_key.rotated",
    );
    return {
      status: 200,
      body: {
        ...serializeApiKey(key),
        key: secret,
      },
    };
  }

  const apiKeyUsageMatch = path.match(/^users\/me\/api-keys\/([^/]+)\/usage$/i);
  if (method === "GET" && apiKeyUsageMatch) {
    const key = store.apiKeys.get(apiKeyUsageMatch[1]);
    if (!key || key.userId !== currentUser.id) {
      return { status: 404, body: { detail: "ไม่พบ API Key" } };
    }
    const matchingRecords = store.usageRecords.filter(
      (r) =>
        r.userId === currentUser.id &&
        r.apiKeyId === key.id &&
        r.status === "completed",
    );
    const inputTokens = matchingRecords.reduce((acc, r) => acc + r.inputTokens, 0);
    const outputTokens = matchingRecords.reduce((acc, r) => acc + r.outputTokens, 0);
    const updatedAt = matchingRecords[0]?.completedAt ?? matchingRecords[0]?.createdAt ?? null;

    const nowDate = new Date();
    const endUtc = Date.UTC(
      nowDate.getUTCFullYear(),
      nowDate.getUTCMonth(),
      nowDate.getUTCDate(),
    );
    const dayBuckets = new Map<
      string,
      {
        date: string;
        successful_requests: number;
        input_tokens: number;
        output_tokens: number;
        total_tokens: number;
      }
    >();
    for (let offset = 6; offset >= 0; offset -= 1) {
      const dateStr = new Date(endUtc - offset * DAY_MS).toISOString().slice(0, 10);
      dayBuckets.set(dateStr, {
        date: dateStr,
        successful_requests: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
      });
    }
    for (const record of matchingRecords) {
      const dayStr = (record.completedAt ?? record.createdAt).slice(0, 10);
      const bucket = dayBuckets.get(dayStr);
      if (!bucket) continue;
      bucket.successful_requests += 1;
      bucket.input_tokens += record.inputTokens;
      bucket.output_tokens += record.outputTokens;
      bucket.total_tokens += record.totalTokens;
    }

    return {
      status: 200,
      body: {
        key_id: key.id,
        successful_requests: matchingRecords.length,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: inputTokens + outputTokens,
        updated_at: updatedAt,
        daily_usage: [...dayBuckets.values()],
      },
    };
  }

  const apiKeyItemMatch = path.match(/^users\/me\/api-keys\/([^/]+)$/i);
  if (method === "DELETE" && apiKeyItemMatch) {
    const key = store.apiKeys.get(apiKeyItemMatch[1]);
    if (!key || key.userId !== currentUser.id) {
      return { status: 404, body: { detail: "ไม่พบ API Key" } };
    }
    if (key.revokedAt) {
      return { status: 409, body: { detail: "API Key นี้ถูกเพิกถอนแล้ว" } };
    }
    const now = new Date().toISOString();
    key.revokedAt = now;
    key.autoRotateEnabled = false;
    key.nextRotationAt = null;
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: currentUser.id,
      action: "api_key.revoked",
      resource_id: key.id,
      created_at: now,
    });
    return { status: 200, body: { id: key.id, revoked: true } };
  }

  if (path === "conversations") {
    if (method === "GET") {
      const items = [...store.conversations.values()]
        .filter((c) => c.userId === currentUser.id)
        .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
        .map(summarizeConversation);
      return { status: 200, body: items };
    }
    if (method === "POST") {
      const body = parseJsonBody(options.rawBody);
      const title =
        typeof body.title === "string" && body.title.trim()
          ? body.title.trim().slice(0, 80)
          : "บทสนทนาใหม่";
      const now = new Date().toISOString();
      const conv: StoredConversation = {
        id: randomUUID(),
        userId: currentUser.id,
        title,
        createdAt: now,
        updatedAt: now,
        messages: [],
      };
      store.conversations.set(conv.id, conv);
      return { status: 201, body: summarizeConversation(conv) };
    }
  }

  const conversationMessageMatch = path.match(/^conversations\/([^/]+)\/messages$/i);
  if (method === "POST" && conversationMessageMatch) {
    const conv = store.conversations.get(conversationMessageMatch[1]);
    if (!conv || conv.userId !== currentUser.id) {
      return { status: 404, body: { detail: "Conversation not found" } };
    }
    const body = parseJsonBody(options.rawBody);
    const content = typeof body.content === "string" ? body.content : "";
    if (!content.trim()) {
      return { status: 422, body: { detail: "Message content is required" } };
    }
    const msgId = typeof body.id === "string" && body.id ? body.id : randomUUID();
    const existing = conv.messages.find((m) => m.id === msgId);
    if (existing) {
      return {
        status: 200,
        body: {
          id: existing.id,
          role: existing.role,
          content: existing.content,
          created_at: existing.createdAt,
        },
      };
    }
    const createdAt = new Date().toISOString();
    const message: StoredMessage = {
      id: msgId,
      role: "user",
      content,
      createdAt,
    };
    conv.messages.push(message);
    conv.updatedAt = createdAt;
    return {
      status: 201,
      body: {
        id: message.id,
        role: message.role,
        content: message.content,
        created_at: message.createdAt,
      },
    };
  }

  const conversationItemMatch = path.match(/^conversations\/([^/]+)$/i);
  if (conversationItemMatch) {
    const conv = store.conversations.get(conversationItemMatch[1]);
    if (!conv || conv.userId !== currentUser.id) {
      return { status: 404, body: { detail: "Conversation not found" } };
    }
    if (method === "GET") {
      return {
        status: 200,
        body: {
          ...summarizeConversation(conv),
          messages: conv.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            created_at: m.createdAt,
          })),
        },
      };
    }
    if (method === "PATCH") {
      const body = parseJsonBody(options.rawBody);
      const title = typeof body.title === "string" ? body.title.trim() : "";
      if (!title) {
        return { status: 422, body: { detail: "Conversation title is required" } };
      }
      conv.title = title.slice(0, 80);
      conv.updatedAt = new Date().toISOString();
      return { status: 200, body: summarizeConversation(conv) };
    }
    if (method === "DELETE") {
      store.conversations.delete(conv.id);
      return { status: 200, body: { deleted: true } };
    }
  }

  if (method === "POST" && (path === "v1/native-ai/infer" || path === "v1/native-ai/infer/stream")) {
    const body = parseJsonBody(options.rawBody);
    const prompt = typeof body.prompt === "string" ? body.prompt : "";
    const requestId =
      typeof body.request_id === "string" && body.request_id
        ? body.request_id
        : randomUUID();
    const conversationId =
      typeof body.conversation_id === "string" ? body.conversation_id : null;

    if (!prompt.trim()) {
      return { status: 422, body: { detail: "Prompt is required" } };
    }
    if (conversationId) {
      const conv = store.conversations.get(conversationId);
      if (!conv || conv.userId !== currentUser.id) {
        return { status: 404, body: { detail: "Conversation not found" } };
      }
    }

    const requestedModelVersion =
      typeof body.model_version === "string" ? body.model_version.trim() : "";
    let targetModelVersion = store.activeModelVersion;
    if (requestedModelVersion) {
      const matchedModel = store.modelVersions.find(
        (m) =>
          m.version === requestedModelVersion &&
          m.compatibility?.compatible !== false &&
          m.lifecycle_status !== "quarantined",
      );
      if (!matchedModel) {
        return {
          status: 422,
          body: {
            detail: "Selected native model version is not registered or compatible",
          },
        };
      }
      targetModelVersion = matchedModel.version;
    }

    const nativeStatus = getInMemoryNativeHealth();
    if (!nativeStatus.inference_available || !nativeStatus.native_model_loaded) {
      store.usageRecords.unshift({
        requestId,
        userId: currentUser.id,
        apiKeyId: callerApiKeyId,
        status: "blocked",
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
        modelVersion: targetModelVersion,
        createdAt: new Date().toISOString(),
        completedAt: null,
      });
      return {
        status: 503,
        body: {
          status: "blocked",
          code: "NATIVE_INFERENCE_BLOCKED",
          request_id: requestId,
          provider: "ZYRQUEN_NATIVE_CORE",
          model_version: targetModelVersion,
          detail:
            "BLOCKED: รันไทม์ ZYRQUEN Native Model ยังไม่พร้อมใช้งาน (ไม่มีน้ำหนักโมเดล PyTorch ที่โหลดจริง ห้ามสร้างคำตอบจำลอง)",
        },
      };
    }

    return {
      status: 503,
      body: {
        status: "blocked",
        code: "NATIVE_INFERENCE_BLOCKED",
        detail: "BLOCKED: Native inference runtime is unavailable",
      },
    };
  }

  if (method === "GET" && path === "v1/workflows/definitions") {
    const schedulerEnabled =
      (process.env.ZYRQUEN_WORKFLOW_SCHEDULER ?? "1").trim() !== "0";
    return {
      status: 200,
      body: {
        items: WORKFLOW_DEFINITIONS,
        scheduler_active: schedulerEnabled,
      },
    };
  }

  if (method === "GET" && path === "v1/workflows/services/status") {
    const schedulerEnvEnabled =
      (process.env.ZYRQUEN_WORKFLOW_SCHEDULER ?? "1").trim() !== "0";
    const recoveryEnvEnabled =
      (process.env.ZYRQUEN_WORKFLOW_RECOVERY ?? "1").trim() !== "0";
    return {
      status: 200,
      body: {
        service: "zyrquen-workflow-engine",
        started: true,
        started_at: new Date().toISOString(),
        diagnostics_safe_mode: !schedulerEnvEnabled && !recoveryEnvEnabled,
        scheduler: {
          enabled: schedulerEnvEnabled,
          running: schedulerEnvEnabled,
          safely_disabled: !schedulerEnvEnabled,
          status: schedulerEnvEnabled ? "running" : "disabled",
          env_flag: "ZYRQUEN_WORKFLOW_SCHEDULER",
          env_enabled: schedulerEnvEnabled,
          poll_interval_sec: 60,
        },
        recovery: {
          enabled: recoveryEnvEnabled,
          safely_disabled: !recoveryEnvEnabled,
          status: recoveryEnvEnabled ? "enabled" : "disabled",
          env_flag: "ZYRQUEN_WORKFLOW_RECOVERY",
          env_enabled: recoveryEnvEnabled,
          startup_reconciliation_ran: recoveryEnvEnabled,
          reconciled_runs_count: 0,
        },
      },
    };
  }

  if (path === "v1/workflows/runs") {
    if (method === "GET") {
      const limit = Number(options.searchParams?.get("limit") ?? 50);
      const accessibleRuns = filterWorkflowRunsByOwnership(store.workflowRuns, currentUser);
      return {
        status: 200,
        body: {
          items: accessibleRuns.slice(0, Number.isFinite(limit) ? limit : 50),
        },
      };
    }
    if (method === "POST") {
      const body = parseJsonBody(options.rawBody);
      const workflowKey =
        typeof body.workflow_key === "string" ? body.workflow_key : "";
      const defn = WORKFLOW_DEFINITIONS.find((d) => d.workflow_key === workflowKey);
      if (!defn) {
        return { status: 422, body: { detail: `Unknown workflow_key: ${workflowKey}` } };
      }

      const runId = randomUUID();
      const startedAt = new Date().toISOString();

      if (workflowKey === "training.native_controlled_run") {
        const approvalId = randomUUID();
        const approval: WorkflowApprovalRecord = {
          id: approvalId,
          run_id: runId,
          step_key: "execute_training",
          action_type: "training.execute",
          scope: "native_training_cpu",
          status: "pending",
          reason: "Controlled training requires Tier-2 human approval",
          expires_at: new Date(Date.now() + 3600_000).toISOString(),
        };
        store.workflowApprovals.unshift(approval);

        const run: WorkflowRunRecord = {
          id: runId,
          workflow_key: defn.workflow_key,
          workflow_version: defn.version,
          trigger_type: "manual",
          status: "WAITING_APPROVAL",
          started_at: startedAt,
          finished_at: null,
          error_message: null,
          requested_by_user_id: currentUser.id,
          steps: [
            {
              step_key: "preflight",
              status: "COMPLETED",
              attempt: 1,
              started_at: startedAt,
              finished_at: startedAt,
              evidence: { verdict: "PASS", summary: "Preflight budget check passed" },
              output: { cpu_budget_ok: true },
            },
            {
              step_key: "execute_training",
              status: "WAITING_APPROVAL",
              attempt: 0,
              started_at: null,
              finished_at: null,
              evidence: null,
              output: null,
            },
          ],
        };
        store.workflowRuns.unshift(run);
        store.auditLogs.unshift({
          id: randomUUID(),
          actor_user_id: currentUser.id,
          action: `workflow.waiting_approval:${workflowKey}`,
          resource_id: runId,
          created_at: startedAt,
        });
        return { status: 202, body: run };
      }

      if (workflowKey === "project_dev.autonomous_maintainer") {
        const approvalId = randomUUID();
        const approval: WorkflowApprovalRecord = {
          id: approvalId,
          run_id: runId,
          step_key: "merge_to_main",
          action_type: "git.merge_main",
          scope: "project_dev.autonomous_maintainer:merge_to_main",
          status: "pending",
          reason: "Merging maintainer branch into main requires Tier-2 human approval",
          expires_at: new Date(Date.now() + 7200_000).toISOString(),
        };
        store.workflowApprovals.unshift(approval);

        const run: WorkflowRunRecord = {
          id: runId,
          workflow_key: defn.workflow_key,
          workflow_version: defn.version,
          trigger_type: "manual",
          status: "WAITING_APPROVAL",
          started_at: startedAt,
          finished_at: null,
          error_message: null,
          requested_by_user_id: currentUser.id,
          steps: [
            {
              step_key: "audit_repo",
              status: "COMPLETED",
              attempt: 1,
              started_at: startedAt,
              finished_at: startedAt,
              evidence: { verdict: "PASS", summary: "Read-only AST, security, and Native-Only audit completed" },
              output: { native_only_compliance: "PASS", audit_mode: "read_only" },
            },
            {
              step_key: "propose_remediation",
              status: "COMPLETED",
              attempt: 1,
              started_at: startedAt,
              finished_at: startedAt,
              evidence: { verdict: "PASS", summary: "PR branch & anti-tamper policy validation completed" },
              output: { target_base_branch: "main", tier2_required_before_merge: true },
            },
            {
              step_key: "merge_to_main",
              status: "WAITING_APPROVAL",
              attempt: 0,
              started_at: null,
              finished_at: null,
              evidence: null,
              output: null,
            },
          ],
        };
        store.workflowRuns.unshift(run);
        store.auditLogs.unshift({
          id: randomUUID(),
          actor_user_id: currentUser.id,
          action: `workflow.waiting_approval:${workflowKey}`,
          resource_id: runId,
          created_at: startedAt,
        });
        return { status: 202, body: run };
      }

      const finishedAt = new Date(Date.now() + 50).toISOString();
      const isModelEval = workflowKey === "evaluation.model_verification";
      const run: WorkflowRunRecord = {
        id: runId,
        workflow_key: defn.workflow_key,
        workflow_version: defn.version,
        trigger_type: "manual",
        status: isModelEval ? "BLOCKED" : "COMPLETED",
        started_at: startedAt,
        finished_at: finishedAt,
        error_message: isModelEval
          ? "PyTorch/Python Native EvaluationEngine is not attached in Node.js preview mode."
          : null,
        requested_by_user_id: currentUser.id,
        steps: [
          {
            step_key: defn.workflow_key.split(".")[1] || "execute",
            status: isModelEval ? "BLOCKED" : "COMPLETED",
            attempt: 1,
            started_at: startedAt,
            finished_at: finishedAt,
            evidence: isModelEval
              ? {
                  verdict: "NOT RUN",
                  summary: "Zero-Mock policy: evaluation metrics require real PyTorch execution",
                }
              : { verdict: "PASS", summary: `${defn.title} verified` },
            output: isModelEval
              ? { torch_installed: false, evaluation_executed: false }
              : { checked: true },
          },
        ],
      };
      store.workflowRuns.unshift(run);
      store.auditLogs.unshift({
        id: randomUUID(),
        actor_user_id: currentUser.id,
        action: `workflow.completed:${workflowKey}`,
        resource_id: runId,
        created_at: finishedAt,
      });
      return { status: 202, body: run };
    }
  }

  const workflowRunMatch = path.match(/^v1\/workflows\/runs\/([^/]+)$/i);
  if (method === "GET" && workflowRunMatch) {
    const run = store.workflowRuns.find((r) => r.id === workflowRunMatch[1]);
    if (!run) return { status: 404, body: { detail: "Workflow run not found" } };
    if (currentUser.role !== "admin" && run.requested_by_user_id !== currentUser.id) {
      return { status: 403, body: { detail: "Forbidden" } };
    }
    return { status: 200, body: run };
  }

  const workflowCancelMatch = path.match(/^v1\/workflows\/runs\/([^/]+)\/cancel$/i);
  if (method === "POST" && workflowCancelMatch) {
    const run = store.workflowRuns.find((r) => r.id === workflowCancelMatch[1]);
    if (!run) return { status: 404, body: { detail: "Workflow run not found" } };
    if (currentUser.role !== "admin" && run.requested_by_user_id !== currentUser.id) {
      return { status: 403, body: { detail: "Forbidden" } };
    }
    run.status = "CANCELLED";
    run.finished_at = new Date().toISOString();
    return { status: 200, body: run };
  }

  if (method === "GET" && path === "v1/workflows/approvals") {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Admin privileges required" } };
    }
    return { status: 200, body: { items: store.workflowApprovals } };
  }

  const approvalDecisionMatch = path.match(
    /^v1\/workflows\/approvals\/([^/]+)\/decision$/i,
  );
  if (method === "POST" && approvalDecisionMatch) {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Admin privileges required" } };
    }
    const approval = store.workflowApprovals.find(
      (a) => a.id === approvalDecisionMatch[1],
    );
    if (!approval) {
      return { status: 404, body: { detail: "Approval request not found" } };
    }
    const body = parseJsonBody(options.rawBody);
    const approve = body.approve === true;
    const now = new Date().toISOString();
    approval.status = approve ? "approved" : "rejected";
    if (typeof body.reason === "string" && body.reason.trim()) {
      approval.reason = body.reason.trim();
    }

    const run = store.workflowRuns.find((r) => r.id === approval.run_id);
    if (run) {
      const step = run.steps.find((s) => s.step_key === approval.step_key);
      if (approve) {
        const isMerge = approval.action_type === "git.merge_main";
        run.status = isMerge ? "COMPLETED" : "BLOCKED";
        run.finished_at = now;
        run.error_message = isMerge
          ? null
          : "PyTorch training worker is not attached in Node.js preview mode.";
        if (step) {
          step.status = isMerge ? "COMPLETED" : "BLOCKED";
          step.attempt = 1;
          step.started_at = now;
          step.finished_at = now;
          step.evidence = isMerge
            ? { verdict: "PASS", summary: "Approved & authorized in preview" }
            : {
                verdict: "BLOCKED",
                summary: "Zero-Mock policy: training execution requires Python/PyTorch worker",
              };
          step.output = isMerge
            ? {
                authorized: true,
                action: "git.merge_main",
                target_base_branch: "main",
              }
            : { torch_installed: false, training_executed: false };
        }
      } else {
        run.status = "BLOCKED";
        run.finished_at = now;
        run.error_message = `Approval rejected for step ${approval.step_key}`;
        if (step) {
          step.status = "BLOCKED";
          step.finished_at = now;
        }
      }
    }
    store.auditLogs.unshift({
      id: randomUUID(),
      actor_user_id: currentUser.id,
      action: `workflow.approval.${approval.status}`,
      resource_id: approval.id,
      created_at: now,
    });
    return { status: 200, body: run ?? approval };
  }

  if (method === "GET" && path === "v1/workflows/audit-logs") {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Admin privileges required" } };
    }
    return { status: 200, body: { items: store.auditLogs } };
  }

  if (method === "GET" && path === "v1/workflows/logs") {
    const runIdFilter = options.searchParams?.get("run_id")?.trim() || null;
    if (runIdFilter && !isValidWorkflowRunId(runIdFilter)) {
      return { status: 400, body: { detail: "Invalid workflow run_id identifier." } };
    }
    const activeOnlyParam = options.searchParams?.get("active_only");
    const activeOnly = activeOnlyParam !== "false";
    const rawLimit = Number(options.searchParams?.get("limit") ?? 100);
    const limit = Number.isFinite(rawLimit)
      ? Math.max(1, Math.min(500, Math.round(rawLimit)))
      : 100;

    const accessibleRuns = filterWorkflowRunsByOwnership(store.workflowRuns, currentUser);
    const activeRuns = accessibleRuns.filter((r) =>
      isActiveOrchestrationStatus(r.status),
    );

    let targetRuns: WorkflowRunRecord[];
    if (runIdFilter) {
      const requestedRun = store.workflowRuns.find((r) => r.id === runIdFilter);
      if (!requestedRun) {
        return { status: 404, body: { detail: "Workflow run not found" } };
      }
      if (
        currentUser.role !== "admin" &&
        requestedRun.requested_by_user_id !== currentUser.id
      ) {
        return { status: 403, body: { detail: "Forbidden" } };
      }
      targetRuns = [requestedRun];
    } else if (activeOnly) {
      targetRuns = activeRuns;
    } else {
      targetRuns = accessibleRuns.slice(0, 25);
    }

    const runById = new Map(targetRuns.map((r) => [r.id, r]));
    const targetRunIds = new Set(targetRuns.map((r) => r.id));
    const entries: WorkflowExecutionLogItem[] = [];

    if (targetRunIds.size > 0) {
      for (const audit of store.auditLogs) {
        if (!audit.resource_id || !targetRunIds.has(audit.resource_id)) {
          continue;
        }
      const runObj = runById.get(audit.resource_id);
      entries.push({
        id: `audit:${audit.id}`,
        run_id: audit.resource_id,
        workflow_key: runObj?.workflow_key ?? null,
        step_key: null,
        level: logLevelForStatus(runObj?.status ?? null, audit.action),
        event_type: audit.action,
        status: runObj?.status ?? "RECORDED",
        actor_id: audit.actor_user_id,
        message: `${audit.action} on run ${audit.resource_id}`,
        details: null,
        timestamp: audit.created_at,
        });
      }
    }

    for (const runObj of targetRuns) {
      const runTimestamp = runObj.finished_at || runObj.started_at;
      entries.push({
        id: `run:${runObj.id}:${runObj.status}`,
        run_id: runObj.id,
        workflow_key: runObj.workflow_key,
        step_key: null,
        level: logLevelForStatus(runObj.status),
        event_type: `workflow.${runObj.status.toLowerCase()}`,
        status: runObj.status,
        actor_id: runObj.requested_by_user_id ?? "orchestrator",
        message:
          runObj.error_message ||
          `Workflow ${runObj.workflow_key} (${runObj.trigger_type}) is ${runObj.status}`,
        details: {
          workflow_version: runObj.workflow_version,
          trigger_type: runObj.trigger_type,
        },
        timestamp: runTimestamp,
      });

      for (const step of runObj.steps) {
        const stepTimestamp = step.finished_at || step.started_at || runObj.started_at;
        const verdict = step.evidence?.verdict ?? null;
        const summary =
          step.evidence?.summary?.trim() ||
          `Step ${step.step_key} is ${step.status} (attempt ${step.attempt})`;
        entries.push({
          id: `step:${runObj.id}:${step.step_key}:${step.status}:${step.attempt}`,
          run_id: runObj.id,
          workflow_key: runObj.workflow_key,
          step_key: step.step_key,
          level: logLevelForStatus(step.status, verdict),
          event_type: `step.${step.status.toLowerCase()}`,
          status: step.status,
          actor_id: runObj.requested_by_user_id ?? "orchestrator",
          message: summary,
          details: {
            attempt: step.attempt,
            verdict,
            output: step.output,
          },
          timestamp: stepTimestamp,
        });
      }
    }

    entries.sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? ""));

    const activeSummaries: WorkflowActiveJobSummary[] = activeRuns.map((r) => ({
      id: r.id,
      workflow_key: r.workflow_key,
      workflow_version: r.workflow_version,
      status: r.status,
      started_at: r.started_at,
    }));

    return {
      status: 200,
      body: {
        items: entries.slice(0, limit),
        active_runs: activeSummaries,
        active_only: activeOnly,
        polled_at: new Date().toISOString(),
      },
    };
  }

  if (method === "GET" && path === "v1/models/registry") {
    return {
      status: 200,
      body: {
        configured: true,
        root: "in-memory://model-registry",
        active_version: store.activeModelVersion,
        registered_count: store.modelVersions.length,
        baseline_policy: {
          v7: { status: "Baseline", note: "Preserved legacy baseline" },
          v8: { status: "CLOSED / FROZEN", note: "Immutable frozen reference" },
          v9: { status: "Development", note: "Experimental candidate track" },
        },
        versions: store.modelVersions,
      },
    };
  }

  if (method === "GET" && path === "v1/models/registry/compare") {
    const baseName = options.searchParams?.get("base") ?? "";
    const candidateName = options.searchParams?.get("candidate") ?? "";
    const base = store.modelVersions.find((m) => m.version === baseName);
    const candidate = store.modelVersions.find((m) => m.version === candidateName);
    if (!base || !candidate) {
      return { status: 404, body: { detail: "Model version not found" } };
    }
    const metricDeltas: Record<string, { base: number; candidate: number; delta: number }> = {};
    const baseMetrics = base.evaluation_evidence?.metrics ?? {};
    const candMetrics = candidate.evaluation_evidence?.metrics ?? {};
    for (const key of Object.keys(baseMetrics)) {
      if (typeof candMetrics[key] === "number") {
        metricDeltas[key] = {
          base: baseMetrics[key],
          candidate: candMetrics[key],
          delta: Number((candMetrics[key] - baseMetrics[key]).toFixed(4)),
        };
      }
    }
    const capabilityDeltas: Record<string, { base: number; candidate: number; delta: number }> = {};
    const baseCaps = base.evaluation_evidence?.capabilities ?? {};
    const candCaps = candidate.evaluation_evidence?.capabilities ?? {};
    const regressedCapabilities: string[] = [];
    for (const key of Object.keys(baseCaps)) {
      if (typeof candCaps[key] === "number") {
        const delta = Number((candCaps[key] - baseCaps[key]).toFixed(2));
        capabilityDeltas[key] = {
          base: baseCaps[key],
          candidate: candCaps[key],
          delta,
        };
        if (delta < 0) regressedCapabilities.push(key);
      }
    }
    return {
      status: 200,
      body: {
        base_version: base.version,
        candidate_version: candidate.version,
        base_lifecycle: base.lifecycle_status,
        candidate_lifecycle: candidate.lifecycle_status,
        metric_deltas: metricDeltas,
        capability_deltas: capabilityDeltas,
        regressed_metrics: [],
        regressed_capabilities: regressedCapabilities,
        zero_regression: regressedCapabilities.length === 0,
      },
    };
  }

  const lineageMatch = path.match(/^v1\/models\/registry\/([^/]+)\/lineage$/i);
  if (method === "GET" && lineageMatch) {
    const versionName = decodeURIComponent(lineageMatch[1]);
    const record = store.modelVersions.find((m) => m.version === versionName);
    if (!record) return { status: 404, body: { detail: "Model version not found" } };
    const ancestors: Array<{
      version: string;
      parent: string | null;
      lifecycle_status: string;
      dataset_version: string;
      checkpoint_sha256: string;
      eval_report_sha256: string | null;
      eval_passed: boolean | null;
    }> = [];
    let cursor: ModelVersionRecord | undefined = record;
    while (cursor) {
      ancestors.push({
        version: cursor.version,
        parent: cursor.parent,
        lifecycle_status: cursor.lifecycle_status,
        dataset_version: cursor.dataset.version,
        checkpoint_sha256: cursor.checkpoint.sha256,
        eval_report_sha256: cursor.evaluation_evidence?.report_sha256 ?? null,
        eval_passed: cursor.evaluation_evidence?.passed ?? null,
      });
      const parentName: string | null = cursor.parent;
      cursor = parentName
        ? store.modelVersions.find((m) => m.version === parentName)
        : undefined;
    }
    return {
      status: 200,
      body: {
        record,
        lineage: {
          version: record.version,
          depth: ancestors.length,
          ancestors,
        },
        compatibility: record.compatibility,
      },
    };
  }

  const artifactDownloadMatch = path.match(
    /^v1\/models\/registry\/([^/]+)\/artifacts\/(manifest|logs)$/i,
  );
  if (method === "GET" && artifactDownloadMatch) {
    const versionName = decodeURIComponent(artifactDownloadMatch[1]);
    const kind = artifactDownloadMatch[2].toLowerCase();
    const record = store.modelVersions.find((m) => m.version === versionName);
    if (!record) return { status: 404, body: { detail: "Model version not found" } };

    const safeName = record.version.replace(/[^A-Za-z0-9._-]/g, "_");
    if (kind === "manifest") {
      const manifestDoc = {
        schema: "zyrquen.model-artifact-manifest.v1",
        version: record.version,
        registry_record: record,
        dataset_manifest: {
          version: record.dataset.version,
          content_sha256: record.dataset.content_sha256,
        },
      };
      return {
        status: 200,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "content-disposition": `attachment; filename="${safeName}-manifest.json"`,
          "x-content-type-options": "nosniff",
        },
        body: JSON.stringify(manifestDoc, null, 2),
      };
    }

    return {
      status: 404,
      body: {
        detail: `No raw training logs recorded for model version ${record.version} in Node.js preview mode.`,
      },
    };
  }

  const stageOrPromoteMatch = path.match(
    /^v1\/models\/registry\/([^/]+)\/(stage|promote)$/i,
  );
  if (method === "POST" && stageOrPromoteMatch) {
    const versionName = decodeURIComponent(stageOrPromoteMatch[1]);
    const action = stageOrPromoteMatch[2].toLowerCase();
    const record = store.modelVersions.find((m) => m.version === versionName);
    if (!record) return { status: 404, body: { detail: "Model version not found" } };
    if (record.frozen) {
      return { status: 422, body: { detail: `${record.version} is frozen` } };
    }
    if (action === "stage") {
      record.lifecycle_status = "staging";
    } else {
      for (const item of store.modelVersions) {
        if (item.lifecycle_status === "production") {
          item.lifecycle_status = "verified";
        }
      }
      record.lifecycle_status = "production";
      store.activeModelVersion = record.version;
    }
    return { status: 200, body: record };
  }

  if (method === "POST" && path === "v1/models/registry/rollback") {
    const body = parseJsonBody(options.rawBody);
    const requested = typeof body.to_version === "string" ? body.to_version.trim() : "";
    const target = requested
      ? store.modelVersions.find((m) => m.version === requested)
      : store.modelVersions.find(
          (m) =>
            m.version !== store.activeModelVersion &&
            !m.frozen &&
            m.evaluation_evidence?.passed,
        );
    if (!target) {
      return { status: 422, body: { detail: "No eligible rollback version found" } };
    }
    for (const item of store.modelVersions) {
      if (item.lifecycle_status === "production") {
        item.lifecycle_status = "verified";
      }
    }
    target.lifecycle_status = "production";
    store.activeModelVersion = target.version;
    return { status: 200, body: target };
  }

  if (method === "GET" && path === "admin/overview") {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Admin access is required." } };
    }
    const completedUsage = store.usageRecords.filter((r) => r.status === "completed");
    const inputTokens = completedUsage.reduce((acc, r) => acc + r.inputTokens, 0);
    const outputTokens = completedUsage.reduce((acc, r) => acc + r.outputTokens, 0);
    const activeKeys = [...store.apiKeys.values()].filter(
      (k) => !k.revokedAt && Date.parse(k.expiresAt) > Date.now(),
    ).length;
    return {
      status: 200,
      body: {
        users: store.usersById.size,
        successful_inference_requests: completedUsage.length,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: inputTokens + outputTokens,
        active_api_keys: activeKeys,
        configured_quota_policies: store.usersById.size,
        active_quota_policies: store.usersById.size,
        native_ai: nativeHealth,
      },
    };
  }

  if (method === "GET" && path === "admin/users") {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Admin access is required." } };
    }
    const users = [...store.usersById.values()]
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .map((u) => ({
        id: u.id,
        email: u.email,
        role: u.role,
        is_active: u.isActive,
        created_at: u.createdAt,
      }));
    return { status: 200, body: users };
  }

  if (method === "GET" && path === "admin/audit-logs") {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Admin access is required." } };
    }
    return { status: 200, body: store.auditLogs.slice(0, 100) };
  }

  if (method === "GET" && path === "v1/datasets/status") {
    return {
      status: 200,
      body: {
        configured: false,
        status: "not_configured",
        four_split_compliant: false,
        detail: "ZYRQUEN_DATASET_DIR and ZYRQUEN_DATASET_ROOT are not configured in preview backend.",
        active_dataset: null,
        datasets: [],
      },
    };
  }

  const datasetVersionMatch = path.match(/^v1\/datasets\/([^/]+)\/status$/i);
  if (method === "GET" && datasetVersionMatch) {
    return {
      status: 503,
      body: { detail: "Dataset pipeline paths are not configured." },
    };
  }

  if (method === "GET" && path === "training/readiness") {
    return {
      status: 200,
      body: {
        configured: false,
        status: "not_configured",
        dataset_configured: false,
        dataset_verified: false,
        four_split_present: false,
        tokenizer_configured: false,
        runtime_ready: false,
        torch_available: false,
        training_root_ready: false,
        worker_ready: false,
        worker_busy: false,
        admin_allowlist_configured: false,
        is_training_admin: currentUser.role === "admin",
        tier2_approval_required: true,
        approval_secret_configured: false,
        approved_training_approvals: 0,
        pending_training_approvals: 0,
        active_run_id: null,
        dataset: {
          configured: false,
          verified: false,
          format: null,
          four_split_enforced: true,
          required_splits: ["train", "validation", "unseen", "ood"],
          splits: [],
          four_split_present: false,
          split_counts: {},
          leakage_check: { status: "NOT RUN", passed: false, violations: [] },
        },
        tokenizer: {
          configured: false,
          valid: false,
          detail: "ZYRQUEN_TOKENIZER_PATH is not configured in preview mode.",
        },
        preflight: {
          passed: false,
          detail: "Training preflight unavailable in preview mode.",
          storage_writable: false,
          resource_limits_checked: false,
          max_cpu_parameters: 5000000,
        },
        runtime: {
          ready: false,
          torch_available: false,
          training_root_ready: false,
          worker_ready: false,
          worker_busy: false,
          active_run_id: null,
        },
        reasons: [
          "ZYRQUEN_DATASET_DIR is not configured in preview mode.",
          "ZYRQUEN_TOKENIZER_PATH is not configured in preview mode.",
          "Python Native Training Worker is not attached to in-memory preview.",
        ],
      },
    };
  }

  if (path === "training/runs") {
    if (method === "GET") {
      if (currentUser.role !== "admin") {
        return { status: 403, body: { detail: "Training administrator access is required." } };
      }
      return { status: 200, body: { items: [] } };
    }
    if (method === "POST") {
      if (currentUser.role !== "admin") {
        return { status: 403, body: { detail: "Training administrator access is required." } };
      }
      return {
        status: 503,
        body: { detail: "Training dataset and tokenizer paths are not configured." },
      };
    }
  }

  const trainingRunItemMatch = path.match(/^training\/runs\/([^/]+)(?:\/(telemetry))?$/i);
  if (method === "GET" && trainingRunItemMatch) {
    if (currentUser.role !== "admin") {
      return { status: 403, body: { detail: "Training administrator access is required." } };
    }
    return { status: 404, body: { detail: "Training run not found." } };
  }

  return { status: 404, body: { detail: "ไม่รองรับเส้นทาง API ที่ร้องขอ" } };
}
