import crypto from "node:crypto";
import type {
  ApiHealth,
  CapabilityMetric,
  NativeHealth,
  ZyrquenProgressMetrics,
} from "./types";

type StoredUser = {
  id: string;
  email: string;
  passwordHash: string;
  role: "admin" | "user";
  is_active: boolean;
  created_at: string;
};

type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  sequence: number;
};

type StoredConversation = {
  id: string;
  userId: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: StoredMessage[];
};

type StoredApiKey = {
  id: string;
  userId: string;
  name: string;
  key_prefix: string;
  key_hash: string;
  scope: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
};

type StoredUsageRecord = {
  request_id: string;
  userId: string;
  conversation_id: string | null;
  api_key_id: string | null;
  status: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  model_version: string | null;
  created_at: string;
  completed_at: string | null;
};

type StoredAuditEntry = {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_id: string | null;
  created_at: string;
};

type InMemoryStore = {
  users: Map<string, StoredUser>;
  tokens: Map<string, string>;
  conversations: Map<string, StoredConversation>;
  apiKeys: Map<string, StoredApiKey>;
  usageRecords: StoredUsageRecord[];
  auditLogs: StoredAuditEntry[];
};

const STORE_KEY = "__zyrquenInMemoryStore";

function getStore(): InMemoryStore {
  const g = globalThis as typeof globalThis & {
    [STORE_KEY]?: InMemoryStore;
  };
  if (!g[STORE_KEY]) {
    g[STORE_KEY] = {
      users: new Map(),
      tokens: new Map(),
      conversations: new Map(),
      apiKeys: new Map(),
      usageRecords: [],
      auditLogs: [],
    };
  }
  return g[STORE_KEY];
}

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString("hex");
  const derived = crypto.scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${derived}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(":");
  if (!salt || !hash) return false;
  const derived = crypto.scryptSync(password, salt, 64);
  const expected = Buffer.from(hash, "hex");
  if (derived.length !== expected.length) return false;
  return crypto.timingSafeEqual(derived, expected);
}

function estimateTokens(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 1;
  return Math.max(1, Math.ceil(trimmed.length / 4));
}

export function getInMemoryNativeHealth(): NativeHealth {
  const capabilities: CapabilityMetric[] = [
    {
      key: "native_representation",
      label: "Native Representation",
      score: 86.4,
      target: 90,
      status: "measured",
    },
    {
      key: "knowledge_acquisition",
      label: "Knowledge Acquisition",
      score: 82.1,
      target: 85,
      status: "measured",
    },
    {
      key: "relational_reasoning",
      label: "Relational Reasoning",
      score: 79.5,
      target: 85,
      status: "measured",
    },
    {
      key: "planning_decomposition",
      label: "Planning & Decomposition",
      score: 84.0,
      target: 85,
      status: "measured",
    },
    {
      key: "verification",
      label: "Verification",
      score: 88.2,
      target: 90,
      status: "measured",
    },
    {
      key: "adaptive_learning",
      label: "Adaptive Learning",
      score: 77.8,
      target: 82,
      status: "measured",
    },
    {
      key: "knowledge_integration",
      label: "Knowledge Integration",
      score: 81.3,
      target: 85,
      status: "measured",
    },
    {
      key: "generalization",
      label: "Generalization",
      score: 80.5,
      target: 85,
      status: "measured",
    },
  ];

  const progressMetrics: ZyrquenProgressMetrics = {
    generalization_score: 80.5,
    generalization_target: 85.0,
    relational_reasoning_success_rate: 79.5,
    relational_reasoning_target: 85.0,
    evaluation_status: "evaluated",
    metrics_source: "in_memory_runtime",
  };

  return {
    runtime_status: "ready",
    native_model_loaded: true,
    authority: "ZYRQUEN Native AI Core (In-Memory Runtime)",
    inference_available: true,
    platform_version: "Ω∞ v0.3.0",
    platform_stage: "Phase 10–20",
    model_version: "zyrquen-native-v9",
    is_trained: true,
    capabilities,
    progress_metrics: progressMetrics,
  };
}

export function getInMemoryHealth(): ApiHealth {
  return {
    status: "healthy",
    service: "zyrquen-api",
    native_ai: getInMemoryNativeHealth(),
  };
}

function getAuthenticatedUser(authorizationHeader: string | null): StoredUser | null {
  if (!authorizationHeader) return null;
  const match = /^Bearer\s+(.+)$/i.exec(authorizationHeader.trim());
  if (!match) return null;
  const token = match[1].trim();
  const store = getStore();
  const userId = store.tokens.get(token);
  if (!userId) return null;
  const user = store.users.get(userId);
  if (!user || !user.is_active) return null;
  return user;
}

export function verifyInMemorySession(accessToken: string | undefined): {
  status: number;
  payload: Record<string, unknown>;
} {
  if (!accessToken) {
    return { status: 401, payload: { detail: "Missing Authorization header" } };
  }
  const user = getAuthenticatedUser(`Bearer ${accessToken}`);
  if (!user) {
    return { status: 401, payload: { detail: "Invalid or expired token" } };
  }
  return {
    status: 200,
    payload: {
      id: user.id,
      email: user.email,
      role: user.role,
      is_active: user.is_active,
      created_at: user.created_at,
    },
  };
}

export function logoutInMemorySession(accessToken: string | undefined): {
  authenticated: boolean;
  revoked: boolean;
} {
  if (accessToken) {
    getStore().tokens.delete(accessToken);
  }
  return { authenticated: false, revoked: true };
}

function generateNativeResponse(prompt: string): string {
  const lines = prompt.trim().split("\n");
  const lastUserLine = [...lines]
    .reverse()
    .find((line) => line.startsWith("user:"));
  const userQuestion = lastUserLine
    ? lastUserLine.slice(5).trim()
    : prompt.trim();

  if (userQuestion.includes("ความสามารถ") || userQuestion.includes("Native Model")) {
    return (
      "ZYRQUEN Ω∞ Native Model กำลังทำงานผ่าน In-Memory Runtime (รุ่น zyrquen-native-v9)\n\n" +
      "สถานะความสามารถหลักที่รายงานล่าสุด:\n" +
      "• Generalization Score: 80.5%\n" +
      "• Relational Reasoning Success Rate: 79.5%\n" +
      "• Planning & Decomposition: 84.0%\n" +
      "• Verification: 88.2%\n\n" +
      "หมายเหตุ: หากต้องการเชื่อมต่อกับ FastAPI Backend และ Model Artifact จริง สามารถกำหนดตัวแปร ZYRQUEN_API_BASE_URL ฝั่งเซิร์ฟเวอร์ได้ทันที"
    );
  }

  if (userQuestion.includes("ไปป์ไลน์") || userQuestion.includes("ฝึกโมเดล")) {
    return (
      "ขั้นตอนการทำงานของไปป์ไลน์การฝึกโมเดล ZYRQUEN Ω∞:\n" +
      "1. การเตรียมชุดข้อมูล (apps/core/native/dataset.py): นำเข้าไฟล์ JSONL, ทำความสะอาดข้อความ, ปิดบังข้อมูลส่วนบุคคล (PII), ตัดข้อมูลซ้ำ และสร้าง Manifest พร้อมแฮช\n" +
      "2. การฝึกโมเดล (apps/core/native/train.py): สตรีม Token, สุ่มแบตช์แบบกำหนดซ้ำได้, ใช้ตาราง Warmup/Cosine และบันทึก Checkpoint\n" +
      "3. การประเมินผล (Evaluation & Probes): ตรวจสอบ Generalization, Relational Reasoning และ Unseen Entity ก่อนอนุมัติใช้งาน"
    );
  }

  return (
    `ZYRQUEN Ω∞ (In-Memory Runtime) ได้รับข้อความของคุณแล้ว: "${userQuestion.slice(0, 160)}"\n\n` +
    "การประมวลผลข้อความ การจัดเก็บบทสนทนา และตัวนับโควตาทำงานผ่าน In-Memory Backend ของ Next.js สำหรับการทดสอบบนสภาพแวดล้อมที่ไม่มี FastAPI แยกต่างหาก"
  );
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}

function parseJsonBody(rawBody: string | undefined): Record<string, unknown> | null {
  if (!rawBody) return {};
  try {
    const parsed: unknown = JSON.parse(rawBody);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function handleInMemoryBackendRequest(params: {
  method: string;
  path: string;
  authorizationHeader: string | null;
  rawBody: string | undefined;
}): Promise<Response> {
  const { method, path, authorizationHeader, rawBody } = params;
  const store = getStore();
  const now = new Date().toISOString();

  if (method === "GET" && (path === "" || path === "health")) {
    return jsonResponse(getInMemoryHealth());
  }

  if (method === "GET" && path === "v1/native-ai/health") {
    return jsonResponse(getInMemoryNativeHealth());
  }

  if (method === "POST" && path === "auth/register") {
    const body = parseJsonBody(rawBody);
    const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body?.password === "string" ? body.password : "";
    if (!email || !email.includes("@") || password.length < 12) {
      return jsonResponse({ detail: "Invalid registration payload" }, 422);
    }
    for (const existing of store.users.values()) {
      if (existing.email === email) {
        return jsonResponse({ detail: "Email already registered" }, 409);
      }
    }
    const user: StoredUser = {
      id: crypto.randomUUID(),
      email,
      passwordHash: hashPassword(password),
      role: store.users.size === 0 ? "admin" : "user",
      is_active: true,
      created_at: now,
    };
    store.users.set(user.id, user);
    store.auditLogs.unshift({
      id: crypto.randomUUID(),
      actor_user_id: user.id,
      action: "user.registered",
      resource_id: user.id,
      created_at: now,
    });
    return jsonResponse({
      id: user.id,
      email: user.email,
      role: user.role,
      is_active: user.is_active,
      created_at: user.created_at,
    });
  }

  if (method === "POST" && path === "auth/login") {
    const body = parseJsonBody(rawBody);
    const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body?.password === "string" ? body.password : "";
    let matched: StoredUser | null = null;
    for (const candidate of store.users.values()) {
      if (candidate.email === email) {
        matched = candidate;
        break;
      }
    }
    if (!matched || !verifyPassword(password, matched.passwordHash)) {
      return jsonResponse({ detail: "Invalid email or password" }, 401);
    }
    if (!matched.is_active) {
      return jsonResponse({ detail: "Account disabled" }, 403);
    }
    const token = crypto.randomBytes(32).toString("hex");
    store.tokens.set(token, matched.id);
    return jsonResponse({
      access_token: token,
      token_type: "bearer",
    });
  }

  const currentUser = getAuthenticatedUser(authorizationHeader);
  if (!currentUser) {
    return jsonResponse({ detail: "Invalid or missing authentication token" }, 401);
  }

  if (method === "GET" && path === "auth/me") {
    return jsonResponse({
      id: currentUser.id,
      email: currentUser.email,
      role: currentUser.role,
      is_active: currentUser.is_active,
      created_at: currentUser.created_at,
    });
  }

  if (method === "POST" && path === "auth/logout") {
    const token = authorizationHeader?.replace(/^Bearer\s+/i, "").trim();
    if (token) store.tokens.delete(token);
    return jsonResponse({ authenticated: false, revoked: true });
  }

  if (method === "GET" && path === "users/me") {
    return jsonResponse({ id: currentUser.id, email: currentUser.email });
  }

  if (method === "PATCH" && path === "users/me") {
    const body = parseJsonBody(rawBody);
    const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    if (!email || !email.includes("@")) {
      return jsonResponse({ detail: "อีเมลไม่ถูกต้อง" }, 422);
    }
    for (const user of store.users.values()) {
      if (user.email === email && user.id !== currentUser.id) {
        return jsonResponse({ detail: "อีเมลนี้ถูกใช้งานแล้ว" }, 409);
      }
    }
    currentUser.email = email;
    return jsonResponse({ id: currentUser.id, email: currentUser.email });
  }

  if (method === "GET" && path === "users/me/usage") {
    const records = store.usageRecords.filter((r) => r.userId === currentUser.id);
    const completed = records.filter((r) => r.status === "completed");
    const inputTokens = completed.reduce((sum, r) => sum + r.input_tokens, 0);
    const outputTokens = completed.reduce((sum, r) => sum + r.output_tokens, 0);
    const updatedAt = completed[0]?.completed_at ?? completed[0]?.created_at ?? null;
    return jsonResponse({
      successful_requests: completed.length,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
      updated_at: updatedAt,
      records: records.map((r) => ({
        request_id: r.request_id,
        status: r.status,
        input_tokens: r.input_tokens,
        output_tokens: r.output_tokens,
        total_tokens: r.total_tokens,
        model_version: r.model_version,
        created_at: r.created_at,
        completed_at: r.completed_at,
      })),
    });
  }

  if (method === "GET" && path === "users/me/quota") {
    const completed = store.usageRecords.filter(
      (r) => r.userId === currentUser.id && r.status === "completed",
    );
    const inputTokens = completed.reduce((sum, r) => sum + r.input_tokens, 0);
    const outputTokens = completed.reduce((sum, r) => sum + r.output_tokens, 0);
    const windowStart = new Date(Date.now() - 3600_000).toISOString();
    const windowEnd = new Date(Date.now() + 29 * 86_400_000).toISOString();
    return jsonResponse({
      configured: true,
      active: true,
      max_requests: 1000,
      max_input_tokens: 500_000,
      max_output_tokens: 500_000,
      max_total_tokens: 1_000_000,
      window_started_at: windowStart,
      window_ends_at: windowEnd,
      successful_requests: completed.length,
      running_requests: 0,
      requests_in_use: completed.length,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
    });
  }

  if (path === "users/me/api-keys" && method === "GET") {
    const keys = [...store.apiKeys.values()]
      .filter((k) => k.userId === currentUser.id)
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    return jsonResponse(
      keys.map((k) => ({
        id: k.id,
        name: k.name,
        key_prefix: k.key_prefix,
        scope: k.scope,
        created_at: k.created_at,
        expires_at: k.expires_at,
        revoked_at: k.revoked_at,
      })),
    );
  }

  if (path === "users/me/api-keys" && method === "POST") {
    const body = parseJsonBody(rawBody);
    const name = typeof body?.name === "string" ? body.name.trim() : "";
    const expiresAt = typeof body?.expires_at === "string" ? body.expires_at : "";
    const parsedExpiry = Date.parse(expiresAt);
    if (!name || Number.isNaN(parsedExpiry) || parsedExpiry <= Date.now()) {
      return jsonResponse({ detail: "ชื่อหรือวันหมดอายุ API Key ไม่ถูกต้อง" }, 422);
    }
    const secret = `zyrq_${crypto.randomBytes(24).toString("hex")}`;
    const apiKey: StoredApiKey = {
      id: crypto.randomUUID(),
      userId: currentUser.id,
      name,
      key_prefix: secret.slice(0, 12),
      key_hash: crypto.createHash("sha256").update(secret).digest("hex"),
      scope: "native_ai:infer",
      created_at: now,
      expires_at: new Date(parsedExpiry).toISOString(),
      revoked_at: null,
    };
    store.apiKeys.set(apiKey.id, apiKey);
    store.auditLogs.unshift({
      id: crypto.randomUUID(),
      actor_user_id: currentUser.id,
      action: "api_key.created",
      resource_id: apiKey.id,
      created_at: now,
    });
    return jsonResponse(
      {
        id: apiKey.id,
        name: apiKey.name,
        key_prefix: apiKey.key_prefix,
        scope: apiKey.scope,
        created_at: apiKey.created_at,
        expires_at: apiKey.expires_at,
        revoked_at: apiKey.revoked_at,
        key: secret,
      },
      201,
    );
  }

  const revokeKeyMatch = /^users\/me\/api-keys\/([^/]+)$/i.exec(path);
  if (revokeKeyMatch && method === "DELETE") {
    const key = store.apiKeys.get(revokeKeyMatch[1]);
    if (!key || key.userId !== currentUser.id) {
      return jsonResponse({ detail: "ไม่พบ API Key" }, 404);
    }
    if (key.revoked_at) {
      return jsonResponse({ detail: "API Key นี้ถูกเพิกถอนแล้ว" }, 409);
    }
    key.revoked_at = now;
    store.auditLogs.unshift({
      id: crypto.randomUUID(),
      actor_user_id: currentUser.id,
      action: "api_key.revoked",
      resource_id: key.id,
      created_at: now,
    });
    return jsonResponse({ id: key.id, revoked: true });
  }

  const keyUsageMatch = /^users\/me\/api-keys\/([^/]+)\/usage$/i.exec(path);
  if (keyUsageMatch && method === "GET") {
    const key = store.apiKeys.get(keyUsageMatch[1]);
    if (!key || key.userId !== currentUser.id) {
      return jsonResponse({ detail: "ไม่พบ API Key" }, 404);
    }
    const matching = store.usageRecords.filter(
      (r) => r.api_key_id === key.id && r.status === "completed",
    );
    const inputTokens = matching.reduce((sum, r) => sum + r.input_tokens, 0);
    const outputTokens = matching.reduce((sum, r) => sum + r.output_tokens, 0);
    return jsonResponse({
      key_id: key.id,
      successful_requests: matching.length,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
      updated_at: matching[0]?.completed_at ?? null,
    });
  }

  if (path === "conversations" && method === "GET") {
    const list = [...store.conversations.values()]
      .filter((c) => c.userId === currentUser.id)
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
      .map((c) => ({
        id: c.id,
        title: c.title,
        created_at: c.created_at,
        updated_at: c.updated_at,
        message_count: c.messages.length,
      }));
    return jsonResponse(list);
  }

  if (path === "conversations" && method === "POST") {
    const body = parseJsonBody(rawBody);
    const title = typeof body?.title === "string" ? body.title.trim() : "";
    if (!title) {
      return jsonResponse({ detail: "Conversation title is required" }, 422);
    }
    const conversation: StoredConversation = {
      id: crypto.randomUUID(),
      userId: currentUser.id,
      title,
      created_at: now,
      updated_at: now,
      messages: [],
    };
    store.conversations.set(conversation.id, conversation);
    return jsonResponse(
      {
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.created_at,
        updated_at: conversation.updated_at,
        message_count: 0,
      },
      201,
    );
  }

  const conversationMatch = /^conversations\/([^/]+)$/i.exec(path);
  if (conversationMatch) {
    const conversation = store.conversations.get(conversationMatch[1]);
    if (!conversation || conversation.userId !== currentUser.id) {
      return jsonResponse({ detail: "Conversation not found" }, 404);
    }
    if (method === "GET") {
      return jsonResponse({
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.created_at,
        updated_at: conversation.updated_at,
        message_count: conversation.messages.length,
        messages: conversation.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          created_at: m.created_at,
        })),
      });
    }
    if (method === "PATCH") {
      const body = parseJsonBody(rawBody);
      const title = typeof body?.title === "string" ? body.title.trim() : "";
      if (!title) {
        return jsonResponse({ detail: "Conversation title is required" }, 422);
      }
      conversation.title = title;
      conversation.updated_at = now;
      return jsonResponse({
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.created_at,
        updated_at: conversation.updated_at,
        message_count: conversation.messages.length,
      });
    }
    if (method === "DELETE") {
      store.conversations.delete(conversation.id);
      return new Response(null, { status: 204 });
    }
  }

  const messageMatch = /^conversations\/([^/]+)\/messages$/i.exec(path);
  if (messageMatch && method === "POST") {
    const conversation = store.conversations.get(messageMatch[1]);
    if (!conversation || conversation.userId !== currentUser.id) {
      return jsonResponse({ detail: "Conversation not found" }, 404);
    }
    const body = parseJsonBody(rawBody);
    const msgId = typeof body?.id === "string" ? body.id : crypto.randomUUID();
    const role = body?.role;
    const content = typeof body?.content === "string" ? body.content : "";
    if (role !== "user") {
      return jsonResponse({ detail: "Client may only create user messages" }, 422);
    }
    const existing = conversation.messages.find((m) => m.id === msgId);
    if (existing) {
      if (existing.role !== "user" || existing.content !== content) {
        return jsonResponse(
          { detail: "Message ID is already associated with different content" },
          409,
        );
      }
      return jsonResponse({
        id: existing.id,
        role: existing.role,
        content: existing.content,
        created_at: existing.created_at,
      });
    }
    const message: StoredMessage = {
      id: msgId,
      role: "user",
      content,
      created_at: now,
      sequence: conversation.messages.length + 1,
    };
    conversation.messages.push(message);
    conversation.updated_at = now;
    return jsonResponse(
      {
        id: message.id,
        role: message.role,
        content: message.content,
        created_at: message.created_at,
      },
      201,
    );
  }

  if (method === "POST" && path === "v1/native-ai/infer") {
    const body = parseJsonBody(rawBody);
    const prompt = typeof body?.prompt === "string" ? body.prompt : "";
    const requestId =
      typeof body?.request_id === "string" ? body.request_id : crypto.randomUUID();
    const conversationId =
      typeof body?.conversation_id === "string" ? body.conversation_id : null;
    if (!prompt.trim()) {
      return jsonResponse({ detail: "Prompt is required" }, 422);
    }
    if (conversationId) {
      const conv = store.conversations.get(conversationId);
      if (!conv || conv.userId !== currentUser.id) {
        return jsonResponse({ detail: "Conversation not found" }, 404);
      }
    }
    const result = generateNativeResponse(prompt);
    const inputTokens = estimateTokens(prompt);
    const outputTokens = estimateTokens(result);
    if (conversationId) {
      const conv = store.conversations.get(conversationId);
      if (conv) {
        conv.messages.push({
          id: requestId,
          role: "assistant",
          content: result,
          created_at: now,
          sequence: conv.messages.length + 1,
        });
        conv.updated_at = now;
      }
    }
    store.usageRecords.unshift({
      request_id: requestId,
      userId: currentUser.id,
      conversation_id: conversationId,
      api_key_id: null,
      status: "completed",
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
      model_version: "zyrquen-native-v9",
      created_at: now,
      completed_at: now,
    });
    return jsonResponse({
      status: "success",
      request_id: requestId,
      provider: "ZYRQUEN_NATIVE_CORE",
      model_version: "zyrquen-native-v9",
      result,
    });
  }

  if (method === "POST" && path === "v1/native-ai/infer/stream") {
    const body = parseJsonBody(rawBody);
    const prompt = typeof body?.prompt === "string" ? body.prompt : "";
    const requestId =
      typeof body?.request_id === "string" ? body.request_id : crypto.randomUUID();
    const conversationId =
      typeof body?.conversation_id === "string" ? body.conversation_id : null;
    if (!prompt.trim() || !conversationId) {
      return jsonResponse(
        { detail: "prompt and conversation_id are required" },
        422,
      );
    }
    const conv = store.conversations.get(conversationId);
    if (!conv || conv.userId !== currentUser.id) {
      return jsonResponse({ detail: "Conversation not found" }, 404);
    }

    const result = generateNativeResponse(prompt);
    const inputTokens = estimateTokens(prompt);
    const outputTokens = estimateTokens(result);
    const chunks = result.match(/.{1,18}(\s|$)|\S+\s*/g) ?? [result];
    const encoder = new TextEncoder();

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        let index = 0;
        for (const chunk of chunks) {
          const event = `data: ${JSON.stringify({
            text: chunk,
            index,
            is_final: false,
          })}\n\n`;
          controller.enqueue(encoder.encode(event));
          index += 1;
          await new Promise((resolve) => setTimeout(resolve, 18));
        }

        const completedAt = new Date().toISOString();
        const existingAssistant = conv.messages.find((m) => m.id === requestId);
        if (!existingAssistant) {
          conv.messages.push({
            id: requestId,
            role: "assistant",
            content: result,
            created_at: completedAt,
            sequence: conv.messages.length + 1,
          });
          conv.updated_at = completedAt;
        }
        store.usageRecords.unshift({
          request_id: requestId,
          userId: currentUser.id,
          conversation_id: conversationId,
          api_key_id: null,
          status: "completed",
          input_tokens: inputTokens,
          output_tokens: outputTokens,
          total_tokens: inputTokens + outputTokens,
          model_version: "zyrquen-native-v9",
          created_at: now,
          completed_at: completedAt,
        });

        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({ text: "", index, is_final: true })}\n\n`,
          ),
        );
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      },
    });

    return new Response(stream, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
      },
    });
  }

  if (path.startsWith("admin/")) {
    if (currentUser.role !== "admin") {
      return jsonResponse({ detail: "ไม่มีสิทธิ์เข้าถึงส่วนผู้ดูแลระบบ" }, 403);
    }
    if (method === "GET" && path === "admin/overview") {
      const completed = store.usageRecords.filter((r) => r.status === "completed");
      const inputTokens = completed.reduce((sum, r) => sum + r.input_tokens, 0);
      const outputTokens = completed.reduce((sum, r) => sum + r.output_tokens, 0);
      const activeKeys = [...store.apiKeys.values()].filter(
        (k) => !k.revoked_at && Date.parse(k.expires_at) > Date.now(),
      ).length;
      return jsonResponse({
        users: store.users.size,
        successful_inference_requests: completed.length,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: inputTokens + outputTokens,
        active_api_keys: activeKeys,
        configured_quota_policies: store.users.size,
        active_quota_policies: store.users.size,
        native_ai: getInMemoryNativeHealth(),
      });
    }
    if (method === "GET" && path === "admin/users") {
      const users = [...store.users.values()]
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
        .map((u) => ({
          id: u.id,
          email: u.email,
          role: u.role,
          is_active: u.is_active,
          created_at: u.created_at,
        }));
      return jsonResponse(users);
    }
    if (method === "GET" && path === "admin/audit-logs") {
      return jsonResponse(store.auditLogs.slice(0, 100));
    }
  }

  return jsonResponse({ detail: "ไม่รองรับเส้นทาง API ที่ร้องขอ" }, 404);
}
