import { randomBytes, randomUUID, scryptSync, timingSafeEqual } from "node:crypto";

type MockUser = {
  id: string;
  email: string;
  passwordHash: string;
  role: "admin" | "user";
  isActive: boolean;
  createdAt: string;
};

type MockToken = {
  token: string;
  userId: string;
  expiresAt: number;
  revoked: boolean;
};

type MockMessage = {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  sequence: number;
};

type MockConversation = {
  id: string;
  userId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: MockMessage[];
};

type MockApiKey = {
  id: string;
  userId: string;
  name: string;
  keyPrefix: string;
  scope: string;
  createdAt: string;
  expiresAt: string;
  revokedAt: string | null;
};

type MockUsageRecord = {
  requestId: string;
  userId: string;
  conversationId: string | null;
  apiKeyId: string | null;
  status: "completed" | "failed" | "cancelled";
  inputTokens: number;
  outputTokens: number;
  modelVersion: string;
  createdAt: string;
  completedAt: string | null;
};

type MockAuditLog = {
  id: string;
  actorUserId: string | null;
  action: string;
  resourceId: string | null;
  createdAt: string;
};

type MockStore = {
  users: Map<string, MockUser>;
  usersByEmail: Map<string, string>;
  tokens: Map<string, MockToken>;
  conversations: Map<string, MockConversation>;
  apiKeys: Map<string, MockApiKey>;
  usageRecords: MockUsageRecord[];
  auditLogs: MockAuditLog[];
  upstreamProbeCache?: {
    url: string;
    isZyrquenApi: boolean;
    checkedAt: number;
  };
};

const globalStore = globalThis as typeof globalThis & {
  __zyrquenMockStore?: MockStore;
};

function getStore(): MockStore {
  if (!globalStore.__zyrquenMockStore) {
    globalStore.__zyrquenMockStore = {
      users: new Map(),
      usersByEmail: new Map(),
      tokens: new Map(),
      conversations: new Map(),
      apiKeys: new Map(),
      usageRecords: [],
      auditLogs: [],
    };
  }
  return globalStore.__zyrquenMockStore;
}

function isLoopbackUrl(baseUrl: string): boolean {
  try {
    const { hostname } = new URL(baseUrl);
    const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
    return (
      host === "localhost" ||
      host.endsWith(".localhost") ||
      host === "::1" ||
      host === "0.0.0.0" ||
      host.startsWith("127.")
    );
  } catch {
    return false;
  }
}

export async function shouldUseMockBackend(
  baseUrl: string | null,
  hasExplicitUrl: boolean,
): Promise<boolean> {
  if (!baseUrl) {
    return !hasExplicitUrl || !process.env.ZYRQUEN_API_BASE_URL?.trim()
      ? true
      : isLoopbackUrl(process.env.ZYRQUEN_API_BASE_URL.trim());
  }
  if (!isLoopbackUrl(baseUrl)) {
    return false;
  }
  const store = getStore();
  const now = Date.now();
  if (
    store.upstreamProbeCache &&
    store.upstreamProbeCache.url === baseUrl &&
    now - store.upstreamProbeCache.checkedAt < 10_000
  ) {
    return !store.upstreamProbeCache.isZyrquenApi;
  }
  let isZyrquenApi = false;
  try {
    const response = await fetch(`${baseUrl}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(400),
    });
    if (response.ok) {
      const data = (await response.json().catch(() => null)) as
        | { service?: unknown }
        | null;
      isZyrquenApi = data?.service === "zyrquen-api";
    }
  } catch {
    isZyrquenApi = false;
  }
  store.upstreamProbeCache = {
    url: baseUrl,
    isZyrquenApi,
    checkedAt: now,
  };
  return !isZyrquenApi;
}

function hashPassword(password: string): string {
  const salt = randomBytes(16).toString("hex");
  const derived = scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${derived}`;
}

function verifyPassword(password: string, storedHash: string): boolean {
  const [salt, keyHex] = storedHash.split(":");
  if (!salt || !keyHex) return false;
  const expected = Buffer.from(keyHex, "hex");
  const actual = scryptSync(password, salt, 64);
  if (expected.length !== actual.length) return false;
  return timingSafeEqual(expected, actual);
}

function extractBearerToken(authorizationHeader: string | null): string | null {
  if (!authorizationHeader) return null;
  const match = /^Bearer\s+(.+)$/i.exec(authorizationHeader.trim());
  return match ? match[1].trim() : null;
}

function resolveTokenUser(authorizationHeader: string | null): {
  user: MockUser | null;
  status: number;
  detail: string;
} {
  const token = extractBearerToken(authorizationHeader);
  if (!token) {
    return {
      user: null,
      status: 401,
      detail: "Not authenticated",
    };
  }
  const store = getStore();
  const entry = store.tokens.get(token);
  if (!entry || entry.revoked || entry.expiresAt <= Date.now()) {
    return {
      user: null,
      status: 401,
      detail: "Invalid or expired token",
    };
  }
  const user = store.users.get(entry.userId) ?? null;
  if (!user) {
    return {
      user: null,
      status: 401,
      detail: "Invalid or expired token",
    };
  }
  if (!user.isActive) {
    return {
      user: null,
      status: 403,
      detail: "Account disabled",
    };
  }
  return { user, status: 200, detail: "" };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
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

function estimateTokens(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 1;
  return Math.max(1, Math.ceil(trimmed.length / 4));
}

function extractLatestUserPrompt(formattedPrompt: string): string {
  const marker = "user: ";
  const lastIndex = formattedPrompt.lastIndexOf(marker);
  if (lastIndex === -1) return formattedPrompt.trim();
  let slice = formattedPrompt.slice(lastIndex + marker.length);
  const assistantIndex = slice.lastIndexOf("\nassistant:");
  if (assistantIndex !== -1) {
    slice = slice.slice(0, assistantIndex);
  }
  return slice.trim();
}

function generateNativeFallbackReply(prompt: string, maxTokens: number): string {
  const userMessage = extractLatestUserPrompt(prompt);
  const lower = userMessage.toLowerCase();

  let reply: string;
  if (
    lower.includes("native model") ||
    userMessage.includes("ความสามารถ") ||
    userMessage.includes("ระบบปัจจุบัน")
  ) {
    reply =
      "ZYRQUEN Ω∞ กำลังทำงานในโหมดเว็บจำลอง (In-Memory Runtime) สำหรับสภาพแวดล้อมที่ไม่เชื่อมต่อฐานข้อมูลภายนอก โดยรองรับการยืนยันตัวตน การจัดการบทสนทนา การสร้าง API Key และการสตรีมข้อความตอบกลับผ่าน SSE ของ Native Inference API";
  } else if (
    userMessage.includes("ฝึกโมเดล") ||
    lower.includes("training") ||
    lower.includes("pipeline")
  ) {
    reply =
      "ไปป์ไลน์การฝึกโมเดลใน Repository ประกอบด้วยโมดูลเตรียมชุดข้อมูล (apps/core/native/dataset.py) สำหรับทำความสะอาด คัดกรอง และสร้าง Manifest รวมถึงโมดูลฝึกอบรม (apps/core/native/train.py) ที่รองรับสตรีม Token, Warmup/Cosine LR schedule และการบันทึก Checkpoint";
  } else if (
    userMessage.includes("เทคนิค") ||
    userMessage.includes("ปัญหา") ||
    lower.includes("debug")
  ) {
    reply =
      `แนวทางการวิเคราะห์ปัญหาสำหรับ "${userMessage.slice(0, 120)}":\n1. ตรวจสอบการตั้งค่าตัวแปรสภาพแวดล้อมและการเชื่อมต่อ API\n2. ตรวจสอบบันทึกสถานะและผลตอบกลับของ Endpoint ที่เกี่ยวข้อง\n3. ทดสอบแยกส่วนทีละขั้นตอนตั้งแต่การยืนยันตัวตน ไปจนถึงการสตรีมข้อมูลตอบกลับ`;
  } else {
    reply =
      `ได้รับข้อความของคุณแล้ว: "${userMessage}"\n\nขณะนี้ระบบกำลังตอบกลับผ่านรันไทม์จำลองในหน่วยความจำ (In-Memory Fallback) ของ ZYRQUEN Ω∞ หากต้องการเชื่อมต่อกับโมเดลจริงจาก FastAPI ให้กำหนดค่า ZYRQUEN_API_BASE_URL บนฝั่งเซิร์ฟเวอร์`;
  }

  const maxChars = Math.max(40, maxTokens * 4);
  if (reply.length > maxChars) {
    return `${reply.slice(0, maxChars - 1)}…`;
  }
  return reply;
}

export function getMockHealthStatus() {
  return {
    runtime_status: "ready",
    native_model_loaded: true,
    authority: "in-memory-runtime",
    inference_available: true,
  };
}

export function getMockSessionStatus(authorizationHeader: string | null): {
  status: number;
  payload: Record<string, unknown>;
} {
  const resolved = resolveTokenUser(authorizationHeader);
  if (!resolved.user) {
    return {
      status: resolved.status,
      payload: { detail: resolved.detail },
    };
  }
  return {
    status: 200,
    payload: {
      id: resolved.user.id,
      email: resolved.user.email,
      role: resolved.user.role,
      is_active: resolved.user.isActive,
      created_at: resolved.user.createdAt,
    },
  };
}

export function revokeMockSession(authorizationHeader: string | null): void {
  const token = extractBearerToken(authorizationHeader);
  if (!token) return;
  const store = getStore();
  const entry = store.tokens.get(token);
  if (entry) {
    entry.revoked = true;
  }
}

export async function handleMockBackendRequest(params: {
  method: string;
  path: string;
  authorizationHeader: string | null;
  rawBody?: string;
}): Promise<Response> {
  const method = params.method.toUpperCase();
  const path = params.path.replace(/^\/+/, "");
  const store = getStore();

  if (method === "GET" && (path === "" || path === "health")) {
    return jsonResponse({
      status: "healthy",
      service: "zyrquen-api",
      native_ai: getMockHealthStatus(),
    });
  }

  if (method === "GET" && path === "v1/native-ai/health") {
    return jsonResponse(getMockHealthStatus());
  }

  if (method === "POST" && path === "auth/register") {
    const body = parseJsonBody(params.rawBody);
    const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body?.password === "string" ? body.password : "";
    if (!email || !email.includes("@") || email.length < 5 || email.length > 320) {
      return jsonResponse({ detail: "Invalid email address" }, 422);
    }
    if (password.length < 12 || password.length > 128) {
      return jsonResponse(
        { detail: "Password must be between 12 and 128 characters" },
        422,
      );
    }
    if (store.usersByEmail.has(email)) {
      return jsonResponse({ detail: "Email already registered" }, 409);
    }
    const isFirstUser = store.users.size === 0;
    const user: MockUser = {
      id: randomUUID(),
      email,
      passwordHash: hashPassword(password),
      role: isFirstUser ? "admin" : "user",
      isActive: true,
      createdAt: new Date().toISOString(),
    };
    store.users.set(user.id, user);
    store.usersByEmail.set(email, user.id);
    store.auditLogs.unshift({
      id: randomUUID(),
      actorUserId: user.id,
      action: "user.registered",
      resourceId: user.id,
      createdAt: user.createdAt,
    });
    return jsonResponse({
      id: user.id,
      email: user.email,
      role: user.role,
      is_active: user.isActive,
      created_at: user.createdAt,
    });
  }

  if (method === "POST" && path === "auth/login") {
    const body = parseJsonBody(params.rawBody);
    const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body?.password === "string" ? body.password : "";
    const userId = store.usersByEmail.get(email);
    const user = userId ? store.users.get(userId) : undefined;
    if (!user || !verifyPassword(password, user.passwordHash)) {
      return jsonResponse({ detail: "Invalid email or password" }, 401);
    }
    if (!user.isActive) {
      return jsonResponse({ detail: "Account disabled" }, 403);
    }
    const token = randomBytes(32).toString("hex");
    store.tokens.set(token, {
      token,
      userId: user.id,
      expiresAt: Date.now() + 30 * 60 * 1000,
      revoked: false,
    });
    return jsonResponse({
      access_token: token,
      token_type: "bearer",
    });
  }

  if (method === "POST" && path === "auth/logout") {
    revokeMockSession(params.authorizationHeader);
    return jsonResponse({
      authenticated: false,
      revoked: true,
    });
  }

  // All remaining routes require a valid authenticated user
  const auth = resolveTokenUser(params.authorizationHeader);
  if (!auth.user) {
    return jsonResponse({ detail: auth.detail }, auth.status);
  }
  const currentUser = auth.user;

  if (method === "GET" && path === "auth/me") {
    return jsonResponse({
      id: currentUser.id,
      email: currentUser.email,
      role: currentUser.role,
      is_active: currentUser.isActive,
      created_at: currentUser.createdAt,
    });
  }

  if (method === "GET" && path === "users/me") {
    return jsonResponse({
      id: currentUser.id,
      email: currentUser.email,
    });
  }

  if (method === "PATCH" && path === "users/me") {
    const body = parseJsonBody(params.rawBody);
    const nextEmail = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    if (!nextEmail || !nextEmail.includes("@") || nextEmail.length > 320) {
      return jsonResponse({ detail: "กรุณากรอกอีเมลที่ถูกต้อง" }, 422);
    }
    const existingOwnerId = store.usersByEmail.get(nextEmail);
    if (existingOwnerId && existingOwnerId !== currentUser.id) {
      return jsonResponse({ detail: "อีเมลนี้ถูกใช้งานแล้ว" }, 409);
    }
    store.usersByEmail.delete(currentUser.email);
    currentUser.email = nextEmail;
    store.usersByEmail.set(nextEmail, currentUser.id);
    return jsonResponse({
      id: currentUser.id,
      email: currentUser.email,
    });
  }

  if (method === "GET" && path === "users/me/usage") {
    const records = store.usageRecords
      .filter((record) => record.userId === currentUser.id)
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
    const completed = records.filter((record) => record.status === "completed");
    const inputTokens = completed.reduce((sum, item) => sum + item.inputTokens, 0);
    const outputTokens = completed.reduce((sum, item) => sum + item.outputTokens, 0);
    const updatedAt = completed[0]?.completedAt ?? completed[0]?.createdAt ?? null;
    return jsonResponse({
      successful_requests: completed.length,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
      updated_at: updatedAt,
      records: records.map((record) => ({
        request_id: record.requestId,
        status: record.status,
        input_tokens: record.inputTokens,
        output_tokens: record.outputTokens,
        total_tokens: record.inputTokens + record.outputTokens,
        model_version: record.modelVersion,
        created_at: record.createdAt,
        completed_at: record.completedAt,
      })),
    });
  }

  if (method === "GET" && path === "users/me/quota") {
    const completed = store.usageRecords.filter(
      (record) => record.userId === currentUser.id && record.status === "completed",
    );
    const inputTokens = completed.reduce((sum, item) => sum + item.inputTokens, 0);
    const outputTokens = completed.reduce((sum, item) => sum + item.outputTokens, 0);
    const now = new Date();
    const startOfMonth = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    const endOfMonth = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
    return jsonResponse({
      configured: true,
      active: true,
      max_requests: 1000,
      max_input_tokens: 500_000,
      max_output_tokens: 500_000,
      max_total_tokens: 1_000_000,
      window_started_at: startOfMonth.toISOString(),
      window_ends_at: endOfMonth.toISOString(),
      successful_requests: completed.length,
      running_requests: 0,
      requests_in_use: completed.length,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
    });
  }

  if (method === "GET" && path === "users/me/api-keys") {
    const keys = Array.from(store.apiKeys.values())
      .filter((item) => item.userId === currentUser.id)
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .map((item) => ({
        id: item.id,
        name: item.name,
        key_prefix: item.keyPrefix,
        scope: item.scope,
        created_at: item.createdAt,
        expires_at: item.expiresAt,
        revoked_at: item.revokedAt,
      }));
    return jsonResponse(keys);
  }

  if (method === "POST" && path === "users/me/api-keys") {
    const body = parseJsonBody(params.rawBody);
    const name = typeof body?.name === "string" ? body.name.trim() : "";
    const expiresAtRaw = typeof body?.expires_at === "string" ? body.expires_at : "";
    const expiresAtDate = new Date(expiresAtRaw);
    if (!name || Number.isNaN(expiresAtDate.getTime()) || expiresAtDate <= new Date()) {
      return jsonResponse({ detail: "กรุณาระบุชื่อและวันหมดอายุในอนาคต" }, 422);
    }
    const secret = `zyrq_${randomBytes(24).toString("hex")}`;
    const createdAt = new Date().toISOString();
    const apiKey: MockApiKey = {
      id: randomUUID(),
      userId: currentUser.id,
      name,
      keyPrefix: secret.slice(0, 12),
      scope: "native_inference",
      createdAt,
      expiresAt: expiresAtDate.toISOString(),
      revokedAt: null,
    };
    store.apiKeys.set(apiKey.id, apiKey);
    store.auditLogs.unshift({
      id: randomUUID(),
      actorUserId: currentUser.id,
      action: "api_key.created",
      resourceId: apiKey.id,
      createdAt,
    });
    return jsonResponse(
      {
        id: apiKey.id,
        name: apiKey.name,
        key_prefix: apiKey.keyPrefix,
        scope: apiKey.scope,
        created_at: apiKey.createdAt,
        expires_at: apiKey.expiresAt,
        revoked_at: apiKey.revokedAt,
        key: secret,
      },
      201,
    );
  }

  const deleteApiKeyMatch = /^users\/me\/api-keys\/([^/]+)$/i.exec(path);
  if (method === "DELETE" && deleteApiKeyMatch) {
    const keyId = deleteApiKeyMatch[1];
    const apiKey = store.apiKeys.get(keyId);
    if (!apiKey || apiKey.userId !== currentUser.id) {
      return jsonResponse({ detail: "ไม่พบ API Key" }, 404);
    }
    if (apiKey.revokedAt !== null) {
      return jsonResponse({ detail: "API Key นี้ถูกเพิกถอนแล้ว" }, 409);
    }
    const revokedAt = new Date().toISOString();
    apiKey.revokedAt = revokedAt;
    store.auditLogs.unshift({
      id: randomUUID(),
      actorUserId: currentUser.id,
      action: "api_key.revoked",
      resourceId: apiKey.id,
      createdAt: revokedAt,
    });
    return jsonResponse({ id: apiKey.id, revoked: true });
  }

  const apiKeyUsageMatch = /^users\/me\/api-keys\/([^/]+)\/usage$/i.exec(path);
  if (method === "GET" && apiKeyUsageMatch) {
    const keyId = apiKeyUsageMatch[1];
    const apiKey = store.apiKeys.get(keyId);
    if (!apiKey || apiKey.userId !== currentUser.id) {
      return jsonResponse({ detail: "ไม่พบ API Key" }, 404);
    }
    const completed = store.usageRecords.filter(
      (record) => record.apiKeyId === apiKey.id && record.status === "completed",
    );
    const inputTokens = completed.reduce((sum, item) => sum + item.inputTokens, 0);
    const outputTokens = completed.reduce((sum, item) => sum + item.outputTokens, 0);
    const updatedAt = completed[0]?.completedAt ?? null;
    return jsonResponse({
      key_id: apiKey.id,
      successful_requests: completed.length,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: inputTokens + outputTokens,
      updated_at: updatedAt,
    });
  }

  if (method === "GET" && path === "conversations") {
    const items = Array.from(store.conversations.values())
      .filter((conversation) => conversation.userId === currentUser.id)
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
      .map((conversation) => ({
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.createdAt,
        updated_at: conversation.updatedAt,
        message_count: conversation.messages.length,
      }));
    return jsonResponse(items);
  }

  if (method === "POST" && path === "conversations") {
    const body = parseJsonBody(params.rawBody);
    const title = typeof body?.title === "string" ? body.title.trim() : "";
    if (!title) {
      return jsonResponse({ detail: "Conversation title is required" }, 422);
    }
    const now = new Date().toISOString();
    const conversation: MockConversation = {
      id: randomUUID(),
      userId: currentUser.id,
      title,
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    store.conversations.set(conversation.id, conversation);
    return jsonResponse(
      {
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.createdAt,
        updated_at: conversation.updatedAt,
        message_count: 0,
      },
      201,
    );
  }

  const conversationMatch = /^conversations\/([^/]+)$/i.exec(path);
  if (conversationMatch) {
    const conversationId = conversationMatch[1];
    const conversation = store.conversations.get(conversationId);
    if (!conversation || conversation.userId !== currentUser.id) {
      return jsonResponse({ detail: "Conversation not found" }, 404);
    }
    if (method === "GET") {
      return jsonResponse({
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.createdAt,
        updated_at: conversation.updatedAt,
        message_count: conversation.messages.length,
        messages: conversation.messages.map((message) => ({
          id: message.id,
          role: message.role,
          content: message.content,
          created_at: message.createdAt,
        })),
      });
    }
    if (method === "PATCH") {
      const body = parseJsonBody(params.rawBody);
      const title = typeof body?.title === "string" ? body.title.trim() : "";
      if (!title) {
        return jsonResponse({ detail: "Conversation title is required" }, 422);
      }
      conversation.title = title;
      conversation.updatedAt = new Date().toISOString();
      return jsonResponse({
        id: conversation.id,
        title: conversation.title,
        created_at: conversation.createdAt,
        updated_at: conversation.updatedAt,
        message_count: conversation.messages.length,
      });
    }
    if (method === "DELETE") {
      store.conversations.delete(conversationId);
      return new Response(null, {
        status: 204,
        headers: { "Cache-Control": "no-store" },
      });
    }
  }

  const messagesMatch = /^conversations\/([^/]+)\/messages$/i.exec(path);
  if (method === "POST" && messagesMatch) {
    const conversationId = messagesMatch[1];
    const conversation = store.conversations.get(conversationId);
    if (!conversation || conversation.userId !== currentUser.id) {
      return jsonResponse({ detail: "Conversation not found" }, 404);
    }
    const body = parseJsonBody(params.rawBody);
    const id = typeof body?.id === "string" ? body.id : randomUUID();
    const role = body?.role;
    const content = typeof body?.content === "string" ? body.content : "";
    if (role !== "user") {
      return jsonResponse({ detail: "Client may only create user messages" }, 422);
    }
    const existing = conversation.messages.find((item) => item.id === id);
    if (existing) {
      if (existing.role !== role || existing.content !== content) {
        return jsonResponse(
          { detail: "Message ID is already associated with different content" },
          409,
        );
      }
      return jsonResponse({
        id: existing.id,
        role: existing.role,
        content: existing.content,
        created_at: existing.createdAt,
      });
    }
    const createdAt = new Date().toISOString();
    const message: MockMessage = {
      id,
      conversationId: conversation.id,
      role: "user",
      content,
      createdAt,
      sequence: conversation.messages.length + 1,
    };
    conversation.messages.push(message);
    conversation.updatedAt = createdAt;
    return jsonResponse(
      {
        id: message.id,
        role: message.role,
        content: message.content,
        created_at: message.createdAt,
      },
      201,
    );
  }

  if (method === "POST" && (path === "v1/native-ai/infer" || path === "v1/native-ai/infer/stream")) {
    const body = parseJsonBody(params.rawBody);
    const prompt = typeof body?.prompt === "string" ? body.prompt : "";
    const requestId = typeof body?.request_id === "string" ? body.request_id : randomUUID();
    const conversationId =
      typeof body?.conversation_id === "string" ? body.conversation_id : null;
    const maxTokens =
      typeof body?.max_tokens === "number" && body.max_tokens >= 1 && body.max_tokens <= 1024
        ? body.max_tokens
        : 256;

    if (!prompt.trim()) {
      return jsonResponse({ detail: "Prompt is required" }, 422);
    }
    if (conversationId) {
      const conversation = store.conversations.get(conversationId);
      if (!conversation || conversation.userId !== currentUser.id) {
        return jsonResponse({ detail: "Conversation not found" }, 404);
      }
    }

    const resultText = generateNativeFallbackReply(prompt, maxTokens);
    const inputTokens = estimateTokens(prompt);
    const outputTokens = estimateTokens(resultText);
    const now = new Date().toISOString();

    if (conversationId) {
      const conversation = store.conversations.get(conversationId);
      if (conversation && !conversation.messages.some((m) => m.id === requestId)) {
        conversation.messages.push({
          id: requestId,
          conversationId: conversation.id,
          role: "assistant",
          content: resultText,
          createdAt: now,
          sequence: conversation.messages.length + 1,
        });
        conversation.updatedAt = now;
      }
    }

    if (!store.usageRecords.some((r) => r.requestId === requestId)) {
      store.usageRecords.push({
        requestId,
        userId: currentUser.id,
        conversationId,
        apiKeyId: null,
        status: "completed",
        inputTokens,
        outputTokens,
        modelVersion: "zyrquen-native-inmemory-v1",
        createdAt: now,
        completedAt: now,
      });
    }

    if (path === "v1/native-ai/infer") {
      return jsonResponse({
        status: "success",
        request_id: requestId,
        provider: "ZYRQUEN_NATIVE_CORE",
        model_version: "zyrquen-native-inmemory-v1",
        result: resultText,
      });
    }

    const encoder = new TextEncoder();
    const tokens = resultText.split(/(\s+)/).filter((part) => part.length > 0);
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        let index = 0;
        for (const chunk of tokens) {
          const eventPayload = JSON.stringify({
            text: chunk,
            index,
            is_final: false,
          });
          controller.enqueue(encoder.encode(`data: ${eventPayload}\n\n`));
          index += 1;
          await new Promise((resolve) => setTimeout(resolve, 12));
        }
        const finalPayload = JSON.stringify({
          text: "",
          index,
          is_final: true,
        });
        controller.enqueue(encoder.encode(`data: ${finalPayload}\n\n`));
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      },
    });

    return new Response(stream, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
      },
    });
  }

  if (method === "GET" && path.startsWith("admin/")) {
    if (currentUser.role !== "admin") {
      return jsonResponse(
        { detail: "ไม่มีสิทธิ์เข้าถึงส่วนผู้ดูแลระบบ" },
        403,
      );
    }
    if (path === "admin/overview") {
      const completed = store.usageRecords.filter((r) => r.status === "completed");
      const inputTokens = completed.reduce((sum, item) => sum + item.inputTokens, 0);
      const outputTokens = completed.reduce((sum, item) => sum + item.outputTokens, 0);
      const nowMs = Date.now();
      const activeApiKeys = Array.from(store.apiKeys.values()).filter(
        (key) => key.revokedAt === null && Date.parse(key.expiresAt) > nowMs,
      ).length;
      return jsonResponse({
        users: store.users.size,
        successful_inference_requests: completed.length,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: inputTokens + outputTokens,
        active_api_keys: activeApiKeys,
        configured_quota_policies: store.users.size,
        active_quota_policies: store.users.size,
        native_ai: getMockHealthStatus(),
      });
    }
    if (path === "admin/users") {
      const users = Array.from(store.users.values())
        .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
        .map((user) => ({
          id: user.id,
          email: user.email,
          role: user.role,
          is_active: user.isActive,
          created_at: user.createdAt,
        }));
      return jsonResponse(users);
    }
    if (path === "admin/audit-logs") {
      const logs = store.auditLogs.slice(0, 100).map((entry) => ({
        id: entry.id,
        actor_user_id: entry.actorUserId,
        action: entry.action,
        resource_id: entry.resourceId,
        created_at: entry.createdAt,
      }));
      return jsonResponse(logs);
    }
  }

  return jsonResponse({ detail: "ไม่รองรับเส้นทาง API ที่ร้องขอ" }, 404);
}
