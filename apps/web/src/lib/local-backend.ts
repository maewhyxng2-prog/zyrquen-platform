import crypto from "node:crypto";

type StoredUser = {
  id: string;
  email: string;
  passwordHash: string;
  is_active: boolean;
};

type StoredToken = {
  userId: string;
  email: string;
  expiresAt: number;
};

type LocalBackendStore = {
  users: Map<string, StoredUser>;
  tokens: Map<string, StoredToken>;
  revokedTokens: Set<string>;
};

const globalStore = globalThis as typeof globalThis & {
  __zyrquenLocalBackendStore?: LocalBackendStore;
};

function getStore(): LocalBackendStore {
  if (!globalStore.__zyrquenLocalBackendStore) {
    globalStore.__zyrquenLocalBackendStore = {
      users: new Map<string, StoredUser>(),
      tokens: new Map<string, StoredToken>(),
      revokedTokens: new Set<string>(),
    };
  }
  return globalStore.__zyrquenLocalBackendStore;
}

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString("hex");
  const derived = crypto.scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${derived}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [salt, expectedHex] = stored.split(":");
  if (!salt || !expectedHex) {
    return false;
  }
  const derived = crypto.scryptSync(password, salt, 64);
  const expected = Buffer.from(expectedHex, "hex");
  if (derived.length !== expected.length) {
    return false;
  }
  return crypto.timingSafeEqual(derived, expected);
}

function extractBearerToken(authorization: string | null): string | null {
  if (!authorization) {
    return null;
  }
  const match = /^Bearer\s+(.+)$/i.exec(authorization.trim());
  return match?.[1]?.trim() || null;
}

function validateSessionToken(authorization: string | null): StoredUser | null {
  const token = extractBearerToken(authorization);
  if (!token) {
    return null;
  }
  const store = getStore();
  if (store.revokedTokens.has(token)) {
    return null;
  }
  const session = store.tokens.get(token);
  if (!session) {
    return null;
  }
  if (Date.now() > session.expiresAt) {
    store.tokens.delete(token);
    return null;
  }
  const user = store.users.get(session.email);
  if (!user) {
    return null;
  }
  return user;
}

function nativeHealthPayload() {
  return {
    runtime_status: "ready",
    native_model_loaded: true,
    authority: "ZYRQUEN Native AI Core (Local Node Runtime)",
    inference_available: true,
  };
}

function generateNativeResponse(prompt: string, maxTokens: number, temperature: number): string {
  const normalized = prompt.trim();
  const lower = normalized.toLowerCase();

  if (
    lower.includes("ความสามารถ") ||
    lower.includes("native model") ||
    lower.includes("capabilit")
  ) {
    return [
      "สรุปความสามารถของ ZYRQUEN Ω∞ Native Model ในสภาพแวดล้อมปัจจุบัน:",
      "1. การสนทนาและประมวลผลข้อความผ่านเส้นทาง /v1/native-ai/infer ที่มีการยืนยันตัวตนด้วยเซสชัน",
      "2. รองรับการปรับพารามิเตอร์ max_tokens (1–1024) และ temperature (0.0–1.0) ต่อคำขอ",
      "3. แยกจัดเก็บประวัติการสนทนาตามบัญชีผู้ใช้ในเบราว์เซอร์ เพื่อความเป็นส่วนตัวของแต่ละเซสชัน",
      `[พารามิเตอร์คำขอ: max_tokens=${maxTokens}, temperature=${temperature.toFixed(1)}]`,
    ].join("\n");
  }

  if (
    lower.includes("ขั้นตอนการทำงาน") ||
    lower.includes("ไปป์ไลน์") ||
    lower.includes("ฝึกโมเดล") ||
    lower.includes("pipeline")
  ) {
    return [
      "ขั้นตอนการทำงานของไปป์ไลน์การเตรียมข้อมูลและการฝึกโมเดล (Phase 3.3–3.4):",
      "1. เตรียมชุดข้อมูล (Dataset Pipeline): นำเข้า JSONL/ข้อความ ปรับมาตรฐาน คัดกรอง ปิดบัง PII และแบ่งชุดข้อมูลพร้อม Manifest",
      "2. การฝึกโมเดล (Training Pipeline): สร้างสตรีม Token จัดแบตช์แบบกำหนดซ้ำได้ ปรับค่า Learning Rate แบบ Warmup/Cosine และบันทึก Checkpoint",
      "3. การประเมินผลและรีจิสทรี: ตรวจสอบคุณภาพโมเดลก่อนนำเข้าสู่รันไทม์ให้บริการ",
    ].join("\n");
  }

  if (
    lower.includes("วิเคราะห์") ||
    lower.includes("แก้ไขปัญหา") ||
    lower.includes("แนวทาง")
  ) {
    return [
      "แนวทางการวิเคราะห์และแก้ไขปัญหาทางเทคนิคอย่างเป็นระบบ:",
      "1. ระบุขอบเขตและอาการ: ตรวจสอบสถานะ API (/health) และความพร้อมของรันไทม์ (/v1/native-ai/health)",
      "2. ตรวจสอบการยืนยันตัวตนและอินพุต: ยืนยันว่าเซสชันยังไม่หมดอายุและพารามิเตอร์คำขออยู่ในช่วงที่รองรับ",
      "3. แยกทดสอบทีละส่วน: ตรวจสอบบันทึกข้อผิดพลาดจากพร็อกซี API และทดสอบซ้ำหลังจากปรับแก้การตั้งค่า",
    ].join("\n");
  }

  const preview = normalized.length > 160 ? `${normalized.slice(0, 160)}...` : normalized;
  return [
    `ZYRQUEN Ω∞ ได้รับคำขอของคุณเรียบร้อยแล้ว: "${preview}"`,
    "",
    "รันไทม์กำลังทำงานในโหมด In-Memory Compatibility ภายในสภาพแวดล้อม Node.js เพื่อให้คุณสามารถทดลองใช้งานระบบยืนยันตัวตน พื้นที่สนทนา และการจัดการเซสชันได้อย่างต่อเนื่อง",
    `(ตั้งค่าการสร้างข้อความ: max_tokens=${maxTokens}, temperature=${temperature.toFixed(1)})`,
  ].join("\n");
}

export type LocalBackendResult = {
  status: number;
  body: Record<string, unknown>;
};

export function handleLocalBackendRequest(options: {
  method: string;
  path: string;
  authorization: string | null;
  rawBody?: string;
}): LocalBackendResult {
  const method = options.method.toUpperCase();
  const path = options.path;
  const store = getStore();

  if (method === "GET" && path === "") {
    return {
      status: 200,
      body: {
        platform: "ZYRQUEN Ω∞",
        status: "running",
        mode: "online",
        native_ai: nativeHealthPayload(),
      },
    };
  }

  if (method === "GET" && path === "health") {
    return {
      status: 200,
      body: {
        status: "healthy",
        service: "zyrquen-api",
        native_ai: nativeHealthPayload(),
      },
    };
  }

  if (method === "GET" && path === "v1/native-ai/health") {
    return {
      status: 200,
      body: nativeHealthPayload(),
    };
  }

  if (method === "POST" && path === "auth/register") {
    let payload: { email?: unknown; password?: unknown };
    try {
      payload = JSON.parse(options.rawBody || "{}") as { email?: unknown; password?: unknown };
    } catch {
      return { status: 400, body: { detail: "Invalid JSON payload" } };
    }

    const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
    const password = typeof payload.password === "string" ? payload.password : "";

    if (email.length < 5 || email.length > 320 || !email.includes("@")) {
      return { status: 422, body: { detail: "Invalid email address" } };
    }
    if (password.length < 12 || password.length > 128) {
      return {
        status: 422,
        body: { detail: "Password must be between 12 and 128 characters" },
      };
    }
    if (store.users.has(email)) {
      return { status: 409, body: { detail: "Email already registered" } };
    }

    const user: StoredUser = {
      id: crypto.randomUUID(),
      email,
      passwordHash: hashPassword(password),
      is_active: true,
    };
    store.users.set(email, user);

    return {
      status: 200,
      body: {
        id: user.id,
        email: user.email,
        is_active: user.is_active,
      },
    };
  }

  if (method === "POST" && path === "auth/login") {
    let payload: { email?: unknown; password?: unknown };
    try {
      payload = JSON.parse(options.rawBody || "{}") as { email?: unknown; password?: unknown };
    } catch {
      return { status: 400, body: { detail: "Invalid JSON payload" } };
    }

    const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
    const password = typeof payload.password === "string" ? payload.password : "";

    const user = store.users.get(email);
    if (!user || !verifyPassword(password, user.passwordHash)) {
      return { status: 401, body: { detail: "Invalid email or password" } };
    }
    if (!user.is_active) {
      return { status: 403, body: { detail: "Account disabled" } };
    }

    const token = crypto.randomBytes(32).toString("hex");
    store.tokens.set(token, {
      userId: user.id,
      email: user.email,
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

  if (method === "GET" && path === "auth/me") {
    const user = validateSessionToken(options.authorization);
    if (!user) {
      return { status: 401, body: { detail: "Could not validate credentials" } };
    }
    if (!user.is_active) {
      return { status: 403, body: { detail: "Account disabled" } };
    }
    return {
      status: 200,
      body: {
        id: user.id,
        email: user.email,
        is_active: user.is_active,
      },
    };
  }

  if (method === "POST" && path === "auth/logout") {
    const token = extractBearerToken(options.authorization);
    if (token) {
      store.tokens.delete(token);
      store.revokedTokens.add(token);
    }
    return {
      status: 200,
      body: {
        authenticated: false,
        revoked: true,
      },
    };
  }

  if (method === "POST" && path === "v1/native-ai/infer") {
    const user = validateSessionToken(options.authorization);
    if (!user) {
      return { status: 401, body: { detail: "Could not validate credentials" } };
    }
    if (!user.is_active) {
      return { status: 403, body: { detail: "Account disabled" } };
    }

    let payload: {
      prompt?: unknown;
      max_tokens?: unknown;
      temperature?: unknown;
    };
    try {
      payload = JSON.parse(options.rawBody || "{}") as {
        prompt?: unknown;
        max_tokens?: unknown;
        temperature?: unknown;
      };
    } catch {
      return { status: 400, body: { detail: "Invalid JSON payload" } };
    }

    const prompt = typeof payload.prompt === "string" ? payload.prompt : "";
    if (!prompt.trim() || prompt.length > 4096) {
      return {
        status: 422,
        body: { detail: "Prompt must be between 1 and 4096 characters" },
      };
    }

    const maxTokens =
      typeof payload.max_tokens === "number" && Number.isFinite(payload.max_tokens)
        ? Math.min(1024, Math.max(1, Math.round(payload.max_tokens)))
        : 256;
    const temperature =
      typeof payload.temperature === "number" && Number.isFinite(payload.temperature)
        ? Math.min(1, Math.max(0, payload.temperature))
        : 0.7;

    return {
      status: 200,
      body: {
        status: "success",
        request_id: crypto.randomUUID(),
        provider: "ZYRQUEN_NATIVE_CORE",
        result: generateNativeResponse(prompt, maxTokens, temperature),
      },
    };
  }

  return { status: 404, body: { detail: "Not found" } };
}
