import crypto from 'crypto';
import { spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import dotenv from 'dotenv';
import express from 'express';
import type { NextFunction, Request, Response } from 'express';
import fs from 'fs';
import path from 'path';
import readline from 'readline';
import { fileURLToPath } from 'url';
import {
  runFallbackBenchmark,
  runFallbackCoreCommand,
  runFallbackDbBridge,
} from './server_fallback.ts';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PORT = Number(process.env.PORT) || 3000;
const SESSION_SECRET =
  process.env.ZYRQUEN_SESSION_SECRET || crypto.randomBytes(32).toString('hex');
const TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
const revokedTokenIds = new Set<string>();
let pythonUnavailable = process.env.ZYRQUEN_NODE_FALLBACK === '1';

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: 'admin' | 'user';
  created_at: string;
  email_verified?: boolean;
  email_verified_at?: string | null;
  avatar_url?: string | null;
  has_password?: boolean;
}

interface AuthedRequest extends Request {
  user?: AuthUser;
  tokenJti?: string;
  tokenExp?: number;
}

interface PendingWorkerCall {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
  timer: NodeJS.Timeout;
}

class PythonWorkerClient {
  private child: ChildProcessWithoutNullStreams | null = null;
  private readyPromise: Promise<void> | null = null;
  private pending = new Map<string, PendingWorkerCall>();
  private rl: readline.Interface | null = null;
  private stderrTail = '';
  readonly dataDir: string;

  constructor(dataDir: string) {
    this.dataDir = dataDir;
  }

  private ensureStarted(): Promise<void> {
    if (this.readyPromise && this.child && !this.child.killed && this.child.exitCode === null) {
      return this.readyPromise;
    }

    this.readyPromise = new Promise<void>((resolve, reject) => {
      const workerPath = path.resolve(__dirname, 'python_core', 'worker.py');
      const child = spawn('python3', [workerPath], {
        cwd: __dirname,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONPATH: path.resolve(__dirname, 'python_core'),
        },
      });
      child.unref();
      this.child = child;
      this.stderrTail = '';

      let settledReady = false;
      const rl = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
      this.rl = rl;

      child.stderr.on('data', (chunk: Buffer) => {
        this.stderrTail = (this.stderrTail + chunk.toString('utf-8')).slice(-2000);
      });

      rl.on('line', (line: string) => {
        if (!line.trim()) return;
        let msg: { id?: string; ready?: boolean; ok?: boolean; result?: unknown; error?: string };
        try {
          msg = JSON.parse(line);
        } catch {
          return;
        }
        if (msg.ready && !settledReady) {
          settledReady = true;
          resolve();
          return;
        }
        if (!msg.id) return;
        const entry = this.pending.get(msg.id);
        if (!entry) return;
        this.pending.delete(msg.id);
        clearTimeout(entry.timer);
        if (msg.ok) {
          entry.resolve(msg.result);
        } else {
          entry.reject(new Error(msg.error || 'Python worker call failed'));
        }
      });

      const failAll = (err: Error) => {
        if (!settledReady) {
          settledReady = true;
          reject(err);
        }
        for (const [id, entry] of this.pending.entries()) {
          clearTimeout(entry.timer);
          entry.reject(err);
          this.pending.delete(id);
        }
        this.rl?.close();
        this.rl = null;
        this.child = null;
        this.readyPromise = null;
      };

      child.on('error', (err) => failAll(err));
      child.on('exit', (code) => {
        failAll(new Error(this.stderrTail.trim() || `Python worker exited with code ${code ?? 'unknown'}`));
      });
    });

    return this.readyPromise;
  }

  async call<T>(scriptName: 'zyrquen_core.py' | 'db_bridge.py', input: Record<string, unknown>): Promise<T> {
    await this.ensureStarted();
    const child = this.child;
    if (!child || child.exitCode !== null) {
      throw new Error('Python worker unavailable');
    }
    const id = crypto.randomUUID();
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Python worker timeout for ${scriptName}`));
      }, 60_000);
      timer.unref();
      this.pending.set(id, {
        resolve: resolve as (v: unknown) => void,
        reject,
        timer,
      });
      const frame = JSON.stringify({ id, script: scriptName, input }) + '\n';
      child.stdin.write(frame, (err) => {
        if (err) {
          const entry = this.pending.get(id);
          if (entry) {
            clearTimeout(entry.timer);
            this.pending.delete(id);
            entry.reject(err);
          }
        }
      });
    });
  }

  dispose(): void {
    for (const [id, entry] of this.pending.entries()) {
      clearTimeout(entry.timer);
      entry.reject(new Error('Python worker disposed'));
      this.pending.delete(id);
    }
    this.rl?.close();
    this.rl = null;
    if (this.child && this.child.exitCode === null) {
      this.child.kill('SIGTERM');
    }
    this.child = null;
    this.readyPromise = null;
  }
}

let activeWorker: PythonWorkerClient | null = null;
let exitHookRegistered = false;

function getPythonWorker(): PythonWorkerClient {
  const currentDataDir = process.env.ZYRQUEN_DATA_DIR || '';
  if (activeWorker && activeWorker.dataDir !== currentDataDir) {
    activeWorker.dispose();
    activeWorker = null;
  }
  if (!activeWorker) {
    activeWorker = new PythonWorkerClient(currentDataDir);
  }
  if (!exitHookRegistered) {
    exitHookRegistered = true;
    process.once('exit', () => {
      activeWorker?.dispose();
    });
  }
  return activeWorker;
}

async function runPythonScript<T = Record<string, unknown>>(
  scriptName: 'zyrquen_core.py' | 'db_bridge.py',
  input: Record<string, unknown>
): Promise<T> {
  if (!pythonUnavailable) {
    try {
      return await getPythonWorker().call<T>(scriptName, input);
    } catch (err) {
      const code = (err as NodeJS.ErrnoException | undefined)?.code;
      const message = err instanceof Error ? err.message : String(err);
      if (code === 'ENOENT' || code === 'EACCES' || /spawn python3 ENOENT/i.test(message)) {
        pythonUnavailable = true;
        console.warn('[ZYRQUEN] python3 unavailable in this container; switching to Node.js runtime fallback.');
      } else {
        throw err;
      }
    }
  }

  if (scriptName === 'db_bridge.py') {
    return runFallbackDbBridge(
      String(input.action || ''),
      (input.payload as Record<string, unknown>) || {}
    ) as unknown as T;
  }
  return runFallbackCoreCommand(
    String(input.cmd || ''),
    (input.payload as Record<string, unknown>) || {}
  ) as unknown as T;
}

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString('hex');
  const derived = crypto.scryptSync(password, salt, 64).toString('hex');
  return `${salt}:${derived}`;
}

function verifyPassword(password: string, storedHash: string): boolean {
  const parts = storedHash.split(':');
  if (parts.length !== 2) return false;
  const [salt, expectedHex] = parts;
  const derived = crypto.scryptSync(password, salt, 64);
  const expected = Buffer.from(expectedHex, 'hex');
  if (derived.length !== expected.length) return false;
  return crypto.timingSafeEqual(derived, expected);
}

function signToken(user: AuthUser): string {
  const payload = {
    sub: user.id,
    email: user.email,
    role: user.role,
    jti: crypto.randomUUID(),
    exp: Date.now() + TOKEN_TTL_MS,
  };
  const encoded = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig = crypto
    .createHmac('sha256', SESSION_SECRET)
    .update(encoded)
    .digest('base64url');
  return `${encoded}.${sig}`;
}

function verifyToken(token: string): { sub: string; jti: string; exp: number } | null {
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const [encoded, sig] = parts;
  const expectedSig = crypto
    .createHmac('sha256', SESSION_SECRET)
    .update(encoded)
    .digest('base64url');
  const a = Buffer.from(sig);
  const b = Buffer.from(expectedSig);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    const parsed = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf-8')) as {
      sub: string;
      jti: string;
      exp: number;
    };
    if (!parsed.sub || !parsed.jti || parsed.exp < Date.now()) return null;
    if (revokedTokenIds.has(parsed.jti)) return null;
    return parsed;
  } catch {
    return null;
  }
}

const SESSION_COOKIE_NAME = 'zyrquen_session';

function parseCookies(cookieHeader: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!cookieHeader) return out;
  for (const part of cookieHeader.split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const key = part.slice(0, idx).trim();
    const val = part.slice(idx + 1).trim();
    if (key) {
      try {
        out[key] = decodeURIComponent(val);
      } catch {
        out[key] = val;
      }
    }
  }
  return out;
}

function setSessionCookie(req: Request, res: Response, token: string): void {
  const isHttps = req.secure || req.headers['x-forwarded-proto'] === 'https';
  const attrs = [
    `${SESSION_COOKIE_NAME}=${encodeURIComponent(token)}`,
    'HttpOnly',
    'Path=/',
    `Max-Age=${Math.floor(TOKEN_TTL_MS / 1000)}`,
    isHttps ? 'SameSite=None; Secure; Partitioned' : 'SameSite=Lax',
  ];
  res.setHeader('Set-Cookie', attrs.join('; '));
}

function clearSessionCookie(req: Request, res: Response): void {
  const isHttps = req.secure || req.headers['x-forwarded-proto'] === 'https';
  const attrs = [
    `${SESSION_COOKIE_NAME}=`,
    'HttpOnly',
    'Path=/',
    'Max-Age=0',
    isHttps ? 'SameSite=None; Secure; Partitioned' : 'SameSite=Lax',
  ];
  res.setHeader('Set-Cookie', attrs.join('; '));
}

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 160;
}

type OAuthProvider = 'google' | 'github';

interface PendingOAuthState {
  nonce: string;
  provider: OAuthProvider;
  intent: 'login' | 'link';
  userId?: string;
  redirectUri: string;
  codeVerifier: string;
  targetOrigin: string;
  expiresAt: number;
}

const OAUTH_STATE_TTL_MS = 10 * 60 * 1000;
const pendingOAuthStates = new Map<string, PendingOAuthState>();

function pruneExpiredOAuthStates(): void {
  const now = Date.now();
  for (const [nonce, entry] of pendingOAuthStates.entries()) {
    if (entry.expiresAt <= now) {
      pendingOAuthStates.delete(nonce);
    }
  }
}

function signOAuthState(nonce: string): string {
  const sig = crypto
    .createHmac('sha256', SESSION_SECRET)
    .update(`oauth_state:${nonce}`)
    .digest('base64url');
  return `${nonce}.${sig}`;
}

function verifyOAuthState(rawState: string): string | null {
  const parts = rawState.split('.');
  if (parts.length !== 2) return null;
  const [nonce, sig] = parts;
  if (!nonce || !sig) return null;
  const expected = crypto
    .createHmac('sha256', SESSION_SECRET)
    .update(`oauth_state:${nonce}`)
    .digest('base64url');
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  return nonce;
}

function createPkcePair(): { codeVerifier: string; codeChallenge: string } {
  const codeVerifier = crypto.randomBytes(32).toString('base64url');
  const codeChallenge = crypto
    .createHash('sha256')
    .update(codeVerifier)
    .digest('base64url');
  return { codeVerifier, codeChallenge };
}

function normalizeOrigin(candidate: string | undefined): string | null {
  if (!candidate) return null;
  try {
    const parsed = new URL(candidate.trim());
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

function resolvePublicBaseUrl(req: Request): string {
  const configuredAppUrl = normalizeOrigin(process.env.APP_URL);
  if (configuredAppUrl) {
    return configuredAppUrl;
  }
  const forwardedProto = String(req.headers['x-forwarded-proto'] || '')
    .split(',')[0]
    .trim();
  const proto = forwardedProto || (req.secure ? 'https' : req.protocol || 'http');
  const host = String(req.headers['x-forwarded-host'] || req.get('host') || '')
    .split(',')[0]
    .trim();
  if (host) {
    return `${proto}://${host}`;
  }
  return `http://127.0.0.1:${PORT}`;
}

function resolveAllowedClientOrigin(req: Request, originParam: unknown): string {
  const baseOrigin = resolvePublicBaseUrl(req);
  const requestedOrigin = normalizeOrigin(typeof originParam === 'string' ? originParam : '');
  if (!requestedOrigin) return baseOrigin;
  try {
    const host = new URL(requestedOrigin).hostname;
    if (host === 'localhost' || host === '127.0.0.1' || host.endsWith('.run.app')) {
      return requestedOrigin;
    }
  } catch {
    // ignore invalid
  }
  return baseOrigin;
}

function allowTestOAuthEndpoints(): boolean {
  return (
    (process.env.NODE_ENV === 'test' || Boolean(process.env.VITEST)) &&
    process.env.ZYRQUEN_OAUTH_ALLOW_TEST_ENDPOINTS === '1'
  );
}

function getOAuthProviderConfig(provider: OAuthProvider, baseUrl: string) {
  const cleanBase = baseUrl.replace(/\/+$/, '');
  const callbackPath = `/api/auth/oauth/${provider}/callback`;
  const callbackUrl = `${cleanBase}${callbackPath}`;

  if (provider === 'github') {
    const clientId = (process.env.GITHUB_OAUTH_CLIENT_ID || '').trim();
    const clientSecret = (process.env.GITHUB_OAUTH_CLIENT_SECRET || '').trim();
    const useTest = allowTestOAuthEndpoints();
    return {
      provider,
      name: 'GitHub',
      configured: Boolean(clientId && clientSecret),
      clientId,
      clientSecret,
      scopes: ['read:user', 'user:email'],
      callbackPath,
      callbackUrl,
      authorizeUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_AUTH_URL) ||
        'https://github.com/login/oauth/authorize',
      tokenUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_TOKEN_URL) ||
        'https://github.com/login/oauth/access_token',
      userUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_USER_URL) ||
        'https://api.github.com/user',
      emailsUrl:
        (useTest && process.env.ZYRQUEN_GITHUB_EMAILS_URL) ||
        'https://api.github.com/user/emails',
    };
  }

  const clientId = (process.env.GOOGLE_OAUTH_CLIENT_ID || '').trim();
  const clientSecret = (process.env.GOOGLE_OAUTH_CLIENT_SECRET || '').trim();
  const useTest = allowTestOAuthEndpoints();
  return {
    provider,
    name: 'Google',
    configured: Boolean(clientId && clientSecret),
    clientId,
    clientSecret,
    scopes: ['openid', 'email', 'profile'],
    callbackPath,
    callbackUrl,
    authorizeUrl:
      (useTest && process.env.ZYRQUEN_GOOGLE_AUTH_URL) ||
      'https://accounts.google.com/o/oauth2/v2/auth',
    tokenUrl:
      (useTest && process.env.ZYRQUEN_GOOGLE_TOKEN_URL) ||
      'https://oauth2.googleapis.com/token',
    userInfoUrl:
      (useTest && process.env.ZYRQUEN_GOOGLE_USERINFO_URL) ||
      'https://openidconnect.googleapis.com/v1/userinfo',
  };
}

function escapeHtmlText(val: string): string {
  return val
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderOAuthCallbackHtml(
  targetOrigin: string,
  payload: Record<string, unknown>,
  statusLabel: string
): string {
  const safePayloadJson = JSON.stringify(payload).replace(/</g, '\\u003c');
  const safeOriginJson = JSON.stringify(targetOrigin || '*').replace(/</g, '\\u003c');
  const safeLabel = escapeHtmlText(statusLabel);
  return `<!DOCTYPE html>
<html lang="th">
<head><meta charset="utf-8"><title>ZYRQUEN Authentication</title></head>
<body style="font-family:system-ui,sans-serif;background:#090d16;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px;text-align:center;">
  <div>
    <p style="font-size:15px;margin:0 0 8px;">${safeLabel}</p>
    <p style="font-size:12px;color:#94a3b8;margin:0;">หน้าต่างนี้จะปิดลงโดยอัตโนมัติ...</p>
  </div>
  <script>
    (function () {
      var payload = ${safePayloadJson};
      var targetOrigin = ${safeOriginJson};
      try {
        if (window.opener && !window.opener.closed) {
          try {
            window.opener.postMessage(payload, targetOrigin);
          } catch (_err) {
            window.opener.postMessage(payload, '*');
          }
          window.close();
          return;
        }
      } catch (_e) {}
      if (payload && payload.type === 'OAUTH_AUTH_SUCCESS') {
        window.location.replace('/');
      }
    })();
  </script>
</body>
</html>`;
}

async function sendTransactionalEmail(params: {
  to: string;
  subject: string;
  html: string;
  text: string;
}): Promise<{ sent: boolean; reason: string | null }> {
  const apiKey = (process.env.RESEND_API_KEY || '').trim();
  const from = (process.env.EMAIL_FROM || '').trim();
  if (!apiKey || !from) {
    return { sent: false, reason: 'EMAIL_PROVIDER_NOT_CONFIGURED' };
  }
  try {
    const resp = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from,
        to: [params.to],
        subject: params.subject,
        html: params.html,
        text: params.text,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) {
      return { sent: false, reason: `EMAIL_PROVIDER_HTTP_${resp.status}` };
    }
    return { sent: true, reason: null };
  } catch {
    return { sent: false, reason: 'EMAIL_SEND_FAILED' };
  }
}

async function issueAndSendVerificationEmail(
  req: Request,
  user: Pick<AuthUser, 'id' | 'email' | 'display_name'>
): Promise<{ required: boolean; emailSent: boolean; deliveryReason: string | null }> {
  const rawToken = crypto.randomBytes(32).toString('base64url');
  const tokenHash = crypto.createHash('sha256').update(rawToken).digest('hex');
  await runPythonScript('db_bridge.py', {
    action: 'auth_create_token',
    payload: {
      user_id: user.id,
      token_type: 'email_verify',
      token_hash: tokenHash,
      target_email: user.email,
      expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    },
  });

  const baseUrl = resolvePublicBaseUrl(req);
  const verifyUrl = `${baseUrl}/?verify_token=${encodeURIComponent(rawToken)}`;
  const safeName = escapeHtmlText(user.display_name || user.email);
  const safeVerifyUrl = escapeHtmlText(verifyUrl);
  const delivery = await sendTransactionalEmail({
    to: user.email,
    subject: 'ยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ',
    text: `สวัสดี ${user.display_name || user.email},\n\nกรุณาคลิกลิงก์ด้านล่างเพื่อยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ (ลิงก์มีอายุ 24 ชั่วโมง):\n${verifyUrl}\n`,
    html: `<div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#0f172a;">
      <h2 style="margin:0 0 12px;">ยืนยันอีเมลบัญชี ZYRQUEN</h2>
      <p>สวัสดี ${safeName},</p>
      <p>กรุณากดปุ่มด้านล่างเพื่อยืนยันที่อยู่อีเมลของคุณ (ลิงก์มีอายุ 24 ชั่วโมง):</p>
      <p style="margin:24px 0;"><a href="${safeVerifyUrl}" style="display:inline-block;background:#2563eb;color:#ffffff;padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:600;">Verify Email</a></p>
      <p style="font-size:12px;color:#475569;word-break:break-all;">หรือคัดลอกลิงก์นี้: ${safeVerifyUrl}</p>
    </div>`,
  });

  return {
    required: true,
    emailSent: delivery.sent,
    deliveryReason: delivery.reason,
  };
}


async function requireAuth(req: AuthedRequest, res: Response, next: NextFunction) {
  const header = req.headers.authorization || '';
  const bearerToken = header.startsWith('Bearer ') ? header.slice(7).trim() : '';
  const cookieToken = parseCookies(req.headers.cookie)[SESSION_COOKIE_NAME] || '';
  const token = bearerToken || cookieToken;
  if (!token) {
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  const isMutation = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method.toUpperCase());
  if (!bearerToken && cookieToken && isMutation) {
    const requestedWith = String(req.headers['x-requested-with'] || '');
    const originHeader = String(req.headers.origin || '');
    const expectedHost = String(req.headers['x-forwarded-host'] || req.headers.host || '').split(',')[0].trim();
    let originMatches = false;
    if (originHeader && expectedHost) {
      try {
        originMatches = new URL(originHeader).host === expectedHost;
      } catch {
        originMatches = false;
      }
    }
    if (!requestedWith && !originMatches) {
      res.status(403).json({ error: 'CSRF check failed for cookie-authenticated mutation' });
      return;
    }
  }
  const decoded = verifyToken(token);
  if (!decoded) {
    res.status(401).json({ error: 'Invalid or expired session token' });
    return;
  }
  try {
    const revokedCheck = await runPythonScript<{ ok: boolean; revoked?: boolean }>('db_bridge.py', {
      action: 'auth_is_token_revoked',
      payload: { jti: decoded.jti },
    });
    if (revokedCheck.revoked) {
      revokedTokenIds.add(decoded.jti);
      res.status(401).json({ error: 'Invalid or expired session token' });
      return;
    }
    const result = await runPythonScript<{ ok: boolean; user: AuthUser | null }>('db_bridge.py', {
      action: 'auth_find_by_id',
      payload: { user_id: decoded.sub },
    });
    if (!result.ok || !result.user) {
      res.status(401).json({ error: 'Account no longer exists' });
      return;
    }
    req.user = result.user;
    req.tokenJti = decoded.jti;
    req.tokenExp = decoded.exp;
    next();
  } catch {
    res.status(500).json({ error: 'Session verification failed' });
  }
}

function requireAdmin(req: AuthedRequest, res: Response, next: NextFunction) {
  if (!req.user || req.user.role !== 'admin') {
    res.status(403).json({ error: 'Administrator privileges required' });
    return;
  }
  next();
}

export async function createApp(options: { attachVite?: boolean } = {}) {
  await runPythonScript('zyrquen_core.py', { cmd: 'init', payload: {} });

  const app = express();
  app.set('trust proxy', 1);
  app.use(express.json({ limit: '2mb' }));

  // Platform-independent versioned API routing: /api/v1/* -> /api/*
  app.use((req: Request, res: Response, next: NextFunction) => {
    if (
      req.url === '/api/v1' ||
      req.url.startsWith('/api/v1/') ||
      req.url.startsWith('/api/v1?')
    ) {
      res.setHeader('X-ZYRQUEN-API-Version', 'v1');
      req.url = req.url.replace(/^\/api\/v1(?=\/|\?|$)/, '/api');
    }
    next();
  });

  // Record API usage latency for authenticated /api routes
  app.use('/api', (req: AuthedRequest, res: Response, next: NextFunction) => {
    const started = performance.now();
    res.on('finish', () => {
      if (req.user && !req.path.startsWith('/health')) {
        const latencyMs = Math.round((performance.now() - started) * 10) / 10;
        void runPythonScript('db_bridge.py', {
          action: 'log_api_usage',
          payload: {
            user_id: req.user.id,
            key_id: null,
            endpoint: req.path,
            method: req.method,
            status_code: res.statusCode,
            latency_ms: latencyMs,
          },
        }).catch(() => {});
      }
    });
    next();
  });

  app.get('/api/platform/manifest', async (_req, res) => {
    try {
      const pyHealth = await runPythonScript<{
        ok: boolean;
        native_core_ready?: boolean;
        native_training_ready?: boolean;
        metrics: Record<string, unknown>;
        counts: Record<string, number>;
      }>('zyrquen_core.py', { cmd: 'health', payload: {} });
      const nativeReady = !pythonUnavailable && pyHealth.ok && pyHealth.native_core_ready !== false;
      const nativeTrainingReady =
        !pythonUnavailable && pyHealth.ok && pyHealth.native_training_ready !== false;
      res.json({
        platform: 'ZYRQUEN',
        tagline: 'Autonomous Foundational Intelligence',
        architecture: 'One Native Intelligence Core, Multiple Platforms',
        api_version: 'v1',
        supported_api_prefixes: ['/api/v1', '/api'],
        supported_clients: ['web', 'desktop', 'mobile-android', 'mobile-ios', 'cli'],
        browser_dependencies_in_core: false,
        external_models_used: false,
        data_portability: ['json', 'jsonl', 'sqlite-wal', 'json.gz-checkpoint'],
        native_core: {
          status: nativeReady ? 'ready' : 'degraded',
          native_training_ready: nativeTrainingReady,
          counts: pyHealth.counts,
          python_version: pyHealth.metrics?.python_version,
        },
        capabilities: [
          'inference',
          'causal_reasoning',
          'knowledge_graph',
          'dag_missions',
          'native_transformer_training',
          'continual_learning_replay',
          'failure_driven_curriculum',
          'scientific_evaluation',
        ],
      });
    } catch {
      res.status(503).json({
        platform: 'ZYRQUEN',
        api_version: 'v1',
        native_core: { status: 'offline', native_training_ready: false },
      });
    }
  });

  app.get('/api/health', async (_req, res) => {
    try {
      const pyHealth = await runPythonScript<{
        ok: boolean;
        native_core_ready?: boolean;
        native_training_ready?: boolean;
        metrics: Record<string, unknown>;
        counts: Record<string, number>;
      }>('zyrquen_core.py', { cmd: 'health', payload: {} });
      const nativeReady = !pythonUnavailable && pyHealth.ok && pyHealth.native_core_ready !== false;
      const nativeTrainingReady =
        !pythonUnavailable && pyHealth.ok && pyHealth.native_training_ready !== false;
      res.json({
        ok: true,
        nativeCore: nativeReady ? 'ready' : 'degraded',
        nativeTrainingReady,
        pythonVersion: pyHealth.metrics?.python_version,
        counts: pyHealth.counts,
        timestamp: new Date().toISOString(),
      });
    } catch {
      res.status(503).json({ ok: false, nativeCore: 'offline', timestamp: new Date().toISOString() });
    }
  });

  app.get('/api/auth/status', async (_req, res) => {
    try {
      const status = await runPythonScript<{ ok: boolean; initialized: boolean; user_count: number }>(
        'db_bridge.py',
        { action: 'auth_status', payload: {} }
      );
      const envPasscodeConfigured = Boolean((process.env.ZYRQUEN_ADMIN_PASSCODE || '').trim());
      res.json({
        initialized: status.initialized,
        userCount: status.user_count,
        envPasscodeConfigured,
      });
    } catch {
      res.status(500).json({ error: 'Unable to check auth status' });
    }
  });

  app.post('/api/auth/claim-admin', async (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    const displayName = String(req.body?.displayName || '').trim();
    const password = String(req.body?.password || '');
    const passcode = String(req.body?.passcode || '');

    if (!isValidEmail(email) || displayName.length < 2 || displayName.length > 80 || password.length < 8 || password.length > 256) {
      res.status(400).json({ error: 'Provide a valid email, display name (2+ chars), and password (8-256 chars).' });
      return;
    }

    const status = await runPythonScript<{ ok: boolean; initialized: boolean }>('db_bridge.py', {
      action: 'auth_status',
      payload: {},
    });
    if (status.initialized) {
      res.status(409).json({ error: 'Administrator already claimed. Sign in instead.' });
      return;
    }

    const configuredPasscode = (process.env.ZYRQUEN_ADMIN_PASSCODE || '').trim();
    if (configuredPasscode) {
      const a = Buffer.from(passcode);
      const b = Buffer.from(configuredPasscode);
      if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
        res.status(403).json({ error: 'Invalid administrator setup passcode.' });
        return;
      }
    }

    const created = await runPythonScript<{ ok: boolean; user?: AuthUser; error?: string }>('db_bridge.py', {
      action: 'auth_create_user',
      payload: {
        email,
        display_name: displayName,
        role: 'admin',
        password_hash: hashPassword(password),
      },
    });
    if (!created.ok || !created.user) {
      const isDup = created.error?.includes('UNIQUE');
      res.status(isDup ? 409 : 400).json({
        error: isDup ? 'อีเมลนี้ถูกใช้งานแล้ว กรุณาใช้อีเมลอื่น' : created.error || 'Failed to claim admin account',
      });
      return;
    }

    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: created.user.id,
        actor_email: created.user.email,
        action: 'ADMIN_CLAIMED',
        target: created.user.id,
        outcome: 'SUCCESS',
      },
    });

    const token = signToken(created.user);
    setSessionCookie(req, res, token);
    res.status(201).json({ token, user: created.user });
  });

  app.post('/api/auth/register', async (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    const displayName = String(req.body?.displayName || '').trim();
    const password = String(req.body?.password || '');
    const confirmPassword = req.body?.confirmPassword !== undefined ? String(req.body.confirmPassword) : undefined;

    if (!isValidEmail(email)) {
      res.status(400).json({ error: 'รูปแบบอีเมลไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง' });
      return;
    }
    if (displayName.length < 2 || displayName.length > 80) {
      res.status(400).json({ error: 'ชื่อที่แสดงต้องมีความยาว 2–80 ตัวอักษร' });
      return;
    }
    if (password.length < 8 || password.length > 256) {
      res.status(400).json({ error: 'รหัสผ่านต้องมีความยาว 8–256 ตัวอักษร' });
      return;
    }
    if (confirmPassword !== undefined && password !== confirmPassword) {
      res.status(400).json({ error: 'รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน' });
      return;
    }

    const existing = await runPythonScript<{ ok: boolean; user: AuthUser | null }>('db_bridge.py', {
      action: 'auth_find_by_email',
      payload: { email },
    });
    if (existing.user) {
      res.status(409).json({ error: 'อีเมลนี้ถูกสมัครสมาชิกแล้ว กรุณาเข้าสู่ระบบหรือใช้อีเมลอื่น' });
      return;
    }

    const created = await runPythonScript<{ ok: boolean; user?: AuthUser; error?: string }>('db_bridge.py', {
      action: 'auth_create_user',
      payload: {
        email,
        display_name: displayName,
        role: 'user',
        password_hash: hashPassword(password),
      },
    });
    if (!created.ok || !created.user) {
      const isDup = created.error?.includes('UNIQUE');
      res.status(isDup ? 409 : 400).json({
        error: isDup ? 'อีเมลนี้ถูกสมัครสมาชิกแล้ว กรุณาเข้าสู่ระบบหรือใช้อีเมลอื่น' : created.error || 'สมัครสมาชิกไม่สำเร็จ',
      });
      return;
    }

    const verification = await issueAndSendVerificationEmail(req, created.user);

    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: created.user.id,
        actor_email: created.user.email,
        action: 'AUTH_REGISTER',
        target: created.user.id,
        outcome: verification.emailSent ? 'SUCCESS_VERIFICATION_SENT' : 'SUCCESS_EMAIL_NOT_CONFIGURED',
      },
    });

    const token = signToken(created.user);
    setSessionCookie(req, res, token);
    res.status(201).json({ token, user: created.user, verification });
  });

  app.post('/api/auth/login', async (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    const password = String(req.body?.password || '');
    if (!isValidEmail(email) || !password || password.length > 256) {
      res.status(400).json({ error: 'กรุณากรอกอีเมลและรหัสผ่านให้ถูกต้อง' });
      return;
    }

    const found = await runPythonScript<{
      ok: boolean;
      user: (AuthUser & { password_hash: string }) | null;
    }>('db_bridge.py', {
      action: 'auth_find_by_email',
      payload: { email },
    });

    if (!found.user || !verifyPassword(password, found.user.password_hash)) {
      res.status(401).json({ error: 'อีเมลหรือรหัสผ่านไม่ถูกต้อง' });
      return;
    }

    const safeUser: AuthUser = {
      id: found.user.id,
      email: found.user.email,
      display_name: found.user.display_name,
      role: found.user.role,
      created_at: found.user.created_at,
      email_verified: Boolean(found.user.email_verified),
      email_verified_at: found.user.email_verified_at ?? null,
      avatar_url: found.user.avatar_url ?? null,
      has_password: Boolean(found.user.has_password ?? (found.user.password_hash && found.user.password_hash.includes(':'))),
    };

    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: safeUser.id,
        actor_email: safeUser.email,
        action: 'AUTH_LOGIN',
        target: safeUser.id,
        outcome: 'SUCCESS',
      },
    });

    const token = signToken(safeUser);
    setSessionCookie(req, res, token);
    res.json({ token, user: safeUser });
  });

  app.post('/api/auth/logout', requireAuth, async (req: AuthedRequest, res: Response) => {
    if (req.tokenJti) {
      revokedTokenIds.add(req.tokenJti);
      await runPythonScript('db_bridge.py', {
        action: 'auth_revoke_token',
        payload: {
          jti: req.tokenJti,
          user_id: req.user?.id || null,
          expires_at: new Date(req.tokenExp || Date.now() + TOKEN_TTL_MS).toISOString(),
        },
      });
    }
    clearSessionCookie(req, res);
    if (req.user) {
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user.id,
          actor_email: req.user.email,
          action: 'AUTH_LOGOUT',
          target: req.user.id,
          outcome: 'SUCCESS',
        },
      });
    }
    res.json({ ok: true });
  });

  app.get('/api/auth/me', requireAuth, (req: AuthedRequest, res: Response) => {
    res.json({ user: req.user });
  });

  app.get('/api/auth/providers', (req: Request, res: Response) => {
    const baseUrl = resolvePublicBaseUrl(req);
    const github = getOAuthProviderConfig('github', baseUrl);
    const google = getOAuthProviderConfig('google', baseUrl);
    const emailConfigured = Boolean(
      (process.env.RESEND_API_KEY || '').trim() && (process.env.EMAIL_FROM || '').trim()
    );
    res.json({
      providers: {
        github: {
          id: 'github',
          name: github.name,
          configured: github.configured,
          scopes: github.scopes,
          callbackPath: github.callbackPath,
          callbackUrl: github.callbackUrl,
        },
        google: {
          id: 'google',
          name: google.name,
          configured: google.configured,
          scopes: google.scopes,
          callbackPath: google.callbackPath,
          callbackUrl: google.callbackUrl,
        },
      },
      emailVerification: {
        emailProviderConfigured: emailConfigured,
        provider: emailConfigured ? 'resend' : null,
      },
    });
  });

  app.get('/api/auth/oauth/:provider/url', async (req: Request, res: Response) => {
    const rawProvider = String(req.params.provider || '').toLowerCase();
    if (rawProvider !== 'github' && rawProvider !== 'google') {
      res.status(400).json({ error: 'Unsupported OAuth provider' });
      return;
    }
    const provider: OAuthProvider = rawProvider;
    const intent = req.query.intent === 'link' ? 'link' : 'login';

    let linkUserId: string | undefined;
    if (intent === 'link') {
      const header = req.headers.authorization || '';
      const bearerToken = header.startsWith('Bearer ') ? header.slice(7).trim() : '';
      const cookieToken = parseCookies(req.headers.cookie)[SESSION_COOKIE_NAME] || '';
      const tok = bearerToken || cookieToken;
      const decoded = tok ? verifyToken(tok) : null;
      if (!decoded) {
        res.status(401).json({ error: 'Authentication required to link an external account' });
        return;
      }
      const revokedCheck = await runPythonScript<{ ok: boolean; revoked?: boolean }>('db_bridge.py', {
        action: 'auth_is_token_revoked',
        payload: { jti: decoded.jti },
      });
      if (revokedCheck.revoked) {
        revokedTokenIds.add(decoded.jti);
        res.status(401).json({ error: 'Authentication required to link an external account' });
        return;
      }
      linkUserId = decoded.sub;
    }

    const baseUrl = resolvePublicBaseUrl(req);
    const cfg = getOAuthProviderConfig(provider, baseUrl);
    if (!cfg.configured) {
      res.status(503).json({
        error: `ยังไม่ได้ตั้งค่า ${cfg.name} OAuth 2.0 บนเซิร์ฟเวอร์ (${provider === 'github' ? 'GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET' : 'GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET'})`,
        code: 'OAUTH_NOT_CONFIGURED',
        provider,
        callbackUrl: cfg.callbackUrl,
      });
      return;
    }

    pruneExpiredOAuthStates();
    const nonce = crypto.randomBytes(24).toString('base64url');
    const signedState = signOAuthState(nonce);
    const { codeVerifier, codeChallenge } = createPkcePair();
    const targetOrigin = resolveAllowedClientOrigin(req, req.query.origin);

    pendingOAuthStates.set(nonce, {
      nonce,
      provider,
      intent,
      userId: linkUserId,
      redirectUri: cfg.callbackUrl,
      codeVerifier,
      targetOrigin,
      expiresAt: Date.now() + OAUTH_STATE_TTL_MS,
    });

    const params = new URLSearchParams({
      client_id: cfg.clientId,
      redirect_uri: cfg.callbackUrl,
      response_type: 'code',
      scope: cfg.scopes.join(' '),
      state: signedState,
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
    });
    if (provider === 'google') {
      params.set('prompt', 'select_account');
    }

    res.json({
      url: `${cfg.authorizeUrl}?${params.toString()}`,
      provider,
      callbackUrl: cfg.callbackUrl,
    });
  });

  app.get(
    ['/api/auth/oauth/:provider/callback', '/api/auth/oauth/:provider/callback/'],
    async (req: Request, res: Response) => {
      const rawProvider = String(req.params.provider || '').toLowerCase();
      const defaultOrigin = resolvePublicBaseUrl(req);
      if (rawProvider !== 'github' && rawProvider !== 'google') {
        res
          .status(400)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              defaultOrigin,
              { type: 'OAUTH_AUTH_ERROR', error: 'ผู้ให้บริการ OAuth ไม่ถูกต้อง' },
              'ผู้ให้บริการไม่ถูกต้อง'
            )
          );
        return;
      }
      const provider: OAuthProvider = rawProvider;
      const rawState = String(req.query.state || '');
      const nonce = verifyOAuthState(rawState);
      const stateEntry = nonce ? pendingOAuthStates.get(nonce) : undefined;
      if (nonce) pendingOAuthStates.delete(nonce);

      const targetOrigin = stateEntry?.targetOrigin || defaultOrigin;

      if (req.query.error) {
        const providerErr = String(req.query.error_description || req.query.error || 'การเข้าสู่ระบบถูกยกเลิก');
        res
          .status(400)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              targetOrigin,
              { type: 'OAUTH_AUTH_ERROR', provider, error: providerErr },
              'การยืนยันตัวตนถูกยกเลิก'
            )
          );
        return;
      }

      if (
        !stateEntry ||
        stateEntry.provider !== provider ||
        stateEntry.expiresAt <= Date.now()
      ) {
        res
          .status(400)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              targetOrigin,
              {
                type: 'OAUTH_AUTH_ERROR',
                provider,
                error: 'OAuth state ไม่ถูกต้องหรือหมดอายุ กรุณาลองใหม่อีกครั้ง',
              },
              'เซสชัน OAuth หมดอายุ'
            )
          );
        return;
      }

      const code = String(req.query.code || '').trim();
      if (!code) {
        res
          .status(400)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              targetOrigin,
              { type: 'OAUTH_AUTH_ERROR', provider, error: 'ไม่ได้รับ Authorization Code จากผู้ให้บริการ' },
              'ไม่ได้รับรหัสยืนยันจากผู้ให้บริการ'
            )
          );
        return;
      }

      const cfg = getOAuthProviderConfig(provider, defaultOrigin);
      if (!cfg.configured) {
        res
          .status(503)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              targetOrigin,
              { type: 'OAUTH_AUTH_ERROR', provider, error: 'OAuth provider is not configured on server' },
              'ยังไม่ได้ตั้งค่า OAuth บนเซิร์ฟเวอร์'
            )
          );
        return;
      }

      try {
        let providerUserId = '';
        let providerEmail = '';
        let providerEmailVerified = false;
        let providerDisplayName = '';
        let providerAvatarUrl = '';

        if (provider === 'github') {
          const tokenResp = await fetch(cfg.tokenUrl, {
            method: 'POST',
            headers: {
              Accept: 'application/json',
              'Content-Type': 'application/x-www-form-urlencoded',
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
            throw new Error(tokenJson.error_description || tokenJson.error || 'GitHub token exchange failed');
          }

          const ghHeaders = {
            Authorization: `Bearer ${tokenJson.access_token}`,
            Accept: 'application/vnd.github+json',
            'User-Agent': 'ZYRQUEN-Platform',
          };
          const [userResp, emailsResp] = await Promise.all([
            fetch(cfg.userUrl!, { headers: ghHeaders, signal: AbortSignal.timeout(10_000) }),
            fetch(cfg.emailsUrl!, { headers: ghHeaders, signal: AbortSignal.timeout(10_000) }),
          ]);
          if (!userResp.ok) {
            throw new Error(`GitHub user lookup failed (${userResp.status})`);
          }
          const ghUser = (await userResp.json()) as {
            id?: number | string;
            login?: string;
            name?: string;
            email?: string;
            avatar_url?: string;
          };
          providerUserId = ghUser.id !== undefined ? String(ghUser.id) : '';
          providerDisplayName = String(ghUser.name || ghUser.login || '').trim();
          providerAvatarUrl = String(ghUser.avatar_url || '').trim();

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
            method: 'POST',
            headers: {
              Accept: 'application/json',
              'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
              client_id: cfg.clientId,
              client_secret: cfg.clientSecret,
              code,
              redirect_uri: stateEntry.redirectUri,
              code_verifier: stateEntry.codeVerifier,
              grant_type: 'authorization_code',
            }).toString(),
            signal: AbortSignal.timeout(12_000),
          });
          const tokenJson = (await tokenResp.json().catch(() => ({}))) as {
            access_token?: string;
            error_description?: string;
            error?: string;
          };
          if (!tokenResp.ok || !tokenJson.access_token) {
            throw new Error(tokenJson.error_description || tokenJson.error || 'Google token exchange failed');
          }

          const infoResp = await fetch(cfg.userInfoUrl!, {
            headers: {
              Authorization: `Bearer ${tokenJson.access_token}`,
              Accept: 'application/json',
            },
            signal: AbortSignal.timeout(10_000),
          });
          if (!infoResp.ok) {
            throw new Error(`Google userinfo lookup failed (${infoResp.status})`);
          }
          const gUser = (await infoResp.json()) as {
            sub?: string;
            email?: string;
            email_verified?: boolean;
            name?: string;
            picture?: string;
          };
          providerUserId = String(gUser.sub || '').trim();
          providerEmail = String(gUser.email || '').trim().toLowerCase();
          providerEmailVerified = Boolean(gUser.email_verified);
          providerDisplayName = String(gUser.name || '').trim();
          providerAvatarUrl = String(gUser.picture || '').trim();
        }

        if (stateEntry.intent === 'link' && stateEntry.userId) {
          const linkRes = await runPythonScript<{
            ok: boolean;
            identity?: Record<string, unknown>;
            error?: string;
            error_code?: string;
          }>('db_bridge.py', {
            action: 'auth_link_identity',
            payload: {
              user_id: stateEntry.userId,
              provider,
              provider_user_id: providerUserId,
              email: providerEmail,
              email_verified: providerEmailVerified,
              display_name: providerDisplayName,
              avatar_url: providerAvatarUrl,
            },
          });

          if (!linkRes.ok) {
            res
              .status(409)
              .type('html')
              .send(
                renderOAuthCallbackHtml(
                  targetOrigin,
                  {
                    type: 'OAUTH_AUTH_ERROR',
                    provider,
                    code: linkRes.error_code || 'LINK_FAILED',
                    error: linkRes.error || 'ไม่สามารถเชื่อมบัญชีภายนอกได้',
                  },
                  'ไม่สามารถเชื่อมบัญชีได้'
                )
              );
            return;
          }

          await runPythonScript('db_bridge.py', {
            action: 'log_audit',
            payload: {
              actor_id: stateEntry.userId,
              actor_email: providerEmail || stateEntry.userId,
              action: 'AUTH_IDENTITY_LINK',
              target: `${provider}:${providerUserId}`,
              outcome: 'SUCCESS',
            },
          });

          res
            .status(200)
            .type('html')
            .send(
              renderOAuthCallbackHtml(
                targetOrigin,
                {
                  type: 'OAUTH_LINK_SUCCESS',
                  provider,
                  identity: linkRes.identity,
                },
                `เชื่อมต่อบัญชี ${cfg.name} เรียบร้อยแล้ว`
              )
            );
          return;
        }

        const loginRes = await runPythonScript<{
          ok: boolean;
          action?: string;
          user?: AuthUser;
          error?: string;
          error_code?: string;
        }>('db_bridge.py', {
          action: 'auth_oauth_login_or_register',
          payload: {
            provider,
            provider_user_id: providerUserId,
            email: providerEmail,
            email_verified: providerEmailVerified,
            display_name: providerDisplayName,
            avatar_url: providerAvatarUrl,
          },
        });

        if (!loginRes.ok || !loginRes.user) {
          res
            .status(403)
            .type('html')
            .send(
              renderOAuthCallbackHtml(
                targetOrigin,
                {
                  type: 'OAUTH_AUTH_ERROR',
                  provider,
                  code: loginRes.error_code || 'OAUTH_REJECTED',
                  error: loginRes.error || 'ไม่สามารถเข้าสู่ระบบผ่านบัญชีภายนอกได้',
                },
                'ไม่สามารถเข้าสู่ระบบได้'
              )
            );
          return;
        }

        const sessionToken = signToken(loginRes.user);
        setSessionCookie(req, res, sessionToken);

        await runPythonScript('db_bridge.py', {
          action: 'log_audit',
          payload: {
            actor_id: loginRes.user.id,
            actor_email: loginRes.user.email,
            action: 'AUTH_OAUTH_LOGIN',
            target: `${provider}:${loginRes.action || 'login'}`,
            outcome: 'SUCCESS',
          },
        });

        res
          .status(200)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              targetOrigin,
              {
                type: 'OAUTH_AUTH_SUCCESS',
                provider,
                token: sessionToken,
                user: loginRes.user,
              },
              `เข้าสู่ระบบด้วย ${cfg.name} สำเร็จ`
            )
          );
      } catch (err) {
        res
          .status(500)
          .type('html')
          .send(
            renderOAuthCallbackHtml(
              targetOrigin,
              {
                type: 'OAUTH_AUTH_ERROR',
                provider,
                error: err instanceof Error ? err.message : 'OAuth authentication failed',
              },
              'การยืนยันตัวตนไม่สำเร็จ'
            )
          );
      }
    }
  );

  app.post('/api/auth/verification/resend', requireAuth, async (req: AuthedRequest, res: Response) => {
    const user = req.user!;
    if (user.email_verified) {
      res.json({ ok: true, alreadyVerified: true });
      return;
    }
    const verification = await issueAndSendVerificationEmail(req, user);
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: user.id,
        actor_email: user.email,
        action: 'AUTH_VERIFICATION_RESEND',
        target: user.id,
        outcome: verification.emailSent ? 'SENT' : verification.deliveryReason || 'NOT_SENT',
      },
    });
    res.json({ ok: true, alreadyVerified: false, verification });
  });

  app.post('/api/auth/verify-email', async (req: Request, res: Response) => {
    const rawToken = String(req.body?.token || '').trim();
    if (!rawToken || rawToken.length < 16 || rawToken.length > 512) {
      res.status(400).json({ error: 'โทเคนยืนยันอีเมลไม่ถูกต้อง' });
      return;
    }
    const tokenHash = crypto.createHash('sha256').update(rawToken).digest('hex');
    const verified = await runPythonScript<{
      ok: boolean;
      user?: AuthUser;
      error?: string;
    }>('db_bridge.py', {
      action: 'auth_consume_email_verify_token',
      payload: { token_hash: tokenHash },
    });
    if (!verified.ok || !verified.user) {
      res.status(400).json({ error: verified.error || 'ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: verified.user.id,
        actor_email: verified.user.email,
        action: 'AUTH_EMAIL_VERIFIED',
        target: verified.user.id,
        outcome: 'SUCCESS',
      },
    });
    res.json({ ok: true, user: verified.user });
  });

  app.post('/api/auth/forgot-password', async (req: Request, res: Response) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    if (!isValidEmail(email)) {
      res.status(400).json({ error: 'กรุณากรอกอีเมลให้ถูกต้อง' });
      return;
    }

    const found = await runPythonScript<{ ok: boolean; user: AuthUser | null }>('db_bridge.py', {
      action: 'auth_find_by_email',
      payload: { email },
    });
    let emailSent = false;
    let deliveryReason: string | null = null;
    if (found.ok && found.user) {
      const rawToken = crypto.randomBytes(32).toString('base64url');
      const tokenHash = crypto.createHash('sha256').update(rawToken).digest('hex');
      await runPythonScript('db_bridge.py', {
        action: 'auth_create_token',
        payload: {
          user_id: found.user.id,
          token_type: 'password_reset',
          token_hash: tokenHash,
          target_email: found.user.email,
          expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'),
        },
      });
      const resetUrl = `${resolvePublicBaseUrl(req)}/?reset_token=${encodeURIComponent(rawToken)}`;
      const safeResetUrl = escapeHtmlText(resetUrl);
      const delivery = await sendTransactionalEmail({
        to: found.user.email,
        subject: 'รีเซ็ตรหัสผ่านบัญชี ZYRQUEN ของคุณ',
        text: `คุณได้ร้องขอการรีเซ็ตรหัสผ่านบัญชี ZYRQUEN (ลิงก์มีอายุ 30 นาที):\n${resetUrl}\n`,
        html: `<div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#0f172a;">
          <h2 style="margin:0 0 12px;">รีเซ็ตรหัสผ่าน ZYRQUEN</h2>
          <p>กดปุ่มด้านล่างเพื่อตั้งรหัสผ่านใหม่ (ลิงก์มีอายุ 30 นาที):</p>
          <p style="margin:24px 0;"><a href="${safeResetUrl}" style="display:inline-block;background:#2563eb;color:#ffffff;padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:600;">ตั้งรหัสผ่านใหม่</a></p>
        </div>`,
      });
      emailSent = delivery.sent;
      deliveryReason = delivery.reason;
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: found.user.id,
          actor_email: found.user.email,
          action: 'AUTH_PASSWORD_RESET_REQUESTED',
          target: found.user.id,
          outcome: emailSent ? 'SENT' : deliveryReason || 'NOT_SENT',
        },
      });
    }

    res.json({
      ok: true,
      message: 'หากอีเมลนี้ลงทะเบียนอยู่ในระบบ เราได้ดำเนินการส่งคำแนะนำสำหรับรีเซ็ตรหัสผ่านแล้ว',
      emailProviderConfigured: Boolean(
        (process.env.RESEND_API_KEY || '').trim() && (process.env.EMAIL_FROM || '').trim()
      ),
      deliveryReason: emailSent ? null : deliveryReason,
    });
  });

  app.post('/api/auth/reset-password', async (req: Request, res: Response) => {
    const rawToken = String(req.body?.token || '').trim();
    const newPassword = String(req.body?.password || '');
    if (!rawToken || rawToken.length < 16 || rawToken.length > 512) {
      res.status(400).json({ error: 'โทเคนรีเซ็ตรหัสผ่านไม่ถูกต้อง' });
      return;
    }
    if (newPassword.length < 8 || newPassword.length > 256) {
      res.status(400).json({ error: 'รหัสผ่านใหม่ต้องมีความยาว 8–256 ตัวอักษร' });
      return;
    }
    const tokenHash = crypto.createHash('sha256').update(rawToken).digest('hex');
    const result = await runPythonScript<{ ok: boolean; user?: AuthUser; error?: string }>('db_bridge.py', {
      action: 'auth_consume_password_reset_token',
      payload: {
        token_hash: tokenHash,
        new_password_hash: hashPassword(newPassword),
      },
    });
    if (!result.ok || !result.user) {
      res.status(400).json({ error: result.error || 'ลิงก์รีเซ็ตรหัสผ่านไม่ถูกต้องหรือหมดอายุแล้ว' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: result.user.id,
        actor_email: result.user.email,
        action: 'AUTH_PASSWORD_RESET_COMPLETED',
        target: result.user.id,
        outcome: 'SUCCESS',
      },
    });
    res.json({ ok: true });
  });

  app.get('/api/auth/identities', requireAuth, async (req: AuthedRequest, res: Response) => {
    const result = await runPythonScript<{
      ok: boolean;
      email: string;
      email_verified: boolean;
      email_verified_at: string | null;
      has_password: boolean;
      identities: Array<Record<string, unknown>>;
    }>('db_bridge.py', {
      action: 'auth_list_identities',
      payload: { user_id: req.user!.id },
    });
    res.json(result);
  });

  app.delete('/api/auth/identities/:provider', requireAuth, async (req: AuthedRequest, res: Response) => {
    const rawProvider = String(req.params.provider || '').toLowerCase();
    if (rawProvider !== 'github' && rawProvider !== 'google') {
      res.status(400).json({ error: 'Invalid provider' });
      return;
    }
    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      error_code?: string;
    }>('db_bridge.py', {
      action: 'auth_unlink_identity',
      payload: { user_id: req.user!.id, provider: rawProvider },
    });
    if (!result.ok) {
      const status =
        result.error_code === 'NOT_FOUND'
          ? 404
          : result.error_code === 'LOCKOUT_PREVENTED'
            ? 409
            : 400;
      res.status(status).json({ error: result.error || 'ไม่สามารถยกเลิกการเชื่อมต่อบัญชีได้' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'AUTH_IDENTITY_UNLINK',
        target: rawProvider,
        outcome: 'SUCCESS',
      },
    });
    res.json({ ok: true, provider: rawProvider });
  });

  app.post('/api/auth/password', requireAuth, async (req: AuthedRequest, res: Response) => {
    const currentPassword = String(req.body?.currentPassword || '');
    const newPassword = String(req.body?.newPassword || '');
    if (newPassword.length < 8 || newPassword.length > 256) {
      res.status(400).json({ error: 'รหัสผ่านใหม่ต้องมีความยาว 8–256 ตัวอักษร' });
      return;
    }
    const found = await runPythonScript<{
      ok: boolean;
      user: (AuthUser & { password_hash: string }) | null;
    }>('db_bridge.py', {
      action: 'auth_find_by_email',
      payload: { email: req.user!.email },
    });
    if (!found.user) {
      res.status(404).json({ error: 'Account not found' });
      return;
    }
    const alreadyHasPassword = Boolean(found.user.password_hash && found.user.password_hash.includes(':'));
    if (alreadyHasPassword) {
      if (!currentPassword || !verifyPassword(currentPassword, found.user.password_hash)) {
        res.status(401).json({ error: 'รหัสผ่านปัจจุบันไม่ถูกต้อง' });
        return;
      }
    }
    const updated = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
      action: 'auth_set_password',
      payload: {
        user_id: req.user!.id,
        new_password_hash: hashPassword(newPassword),
      },
    });
    if (!updated.ok) {
      res.status(400).json({ error: updated.error || 'อัปเดตรหัสผ่านไม่สำเร็จ' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: alreadyHasPassword ? 'AUTH_PASSWORD_CHANGED' : 'AUTH_PASSWORD_SET',
        target: req.user!.id,
        outcome: 'SUCCESS',
      },
    });
    res.json({ ok: true, has_password: true });
  });

  app.get('/api/home', requireAuth, async (req: AuthedRequest, res: Response) => {
    const summary = await runPythonScript('db_bridge.py', {
      action: 'home_summary',
      payload: { user_id: req.user!.id },
    });
    res.json(summary);
  });

  app.get('/api/conversations', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'conv_list',
      payload: { user_id: req.user!.id },
    });
    res.json(data);
  });

  app.post('/api/conversations', requireAuth, async (req: AuthedRequest, res: Response) => {
    const title = String(req.body?.title || 'New Native Session').slice(0, 120);
    const mode = ['auto', 'math', 'knowledge', 'model', 'plan'].includes(req.body?.mode)
      ? req.body.mode
      : 'auto';
    const data = await runPythonScript('db_bridge.py', {
      action: 'conv_create',
      payload: { user_id: req.user!.id, title, mode },
    });
    res.status(201).json(data);
  });

  app.get('/api/conversations/:id', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
      action: 'conv_get',
      payload: { user_id: req.user!.id, conversation_id: req.params.id },
    });
    if (!data.ok) {
      res.status(404).json({ error: data.error || 'Conversation not found' });
      return;
    }
    res.json(data);
  });

  app.get('/api/conversations/:id/summary', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript<{ ok: boolean; error?: string; summary?: Record<string, unknown> }>(
      'db_bridge.py',
      {
        action: 'conv_summary',
        payload: { user_id: req.user!.id, conversation_id: req.params.id },
      }
    );
    if (!data.ok) {
      res.status(404).json({ error: data.error || 'Conversation not found' });
      return;
    }
    res.json(data);
  });

  app.delete('/api/conversations/:id', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript<{ ok: boolean }>('db_bridge.py', {
      action: 'conv_delete',
      payload: { user_id: req.user!.id, conversation_id: req.params.id },
    });
    if (!data.ok) {
      res.status(404).json({ error: 'Conversation not found' });
      return;
    }
    res.json({ ok: true });
  });

  app.post('/api/conversations/:id/messages', requireAuth, async (req: AuthedRequest, res: Response) => {
    const prompt = String(req.body?.content || '').trim();
    const attachment = String(req.body?.attachment || '').slice(0, 8000);
    const mode = ['auto', 'math', 'knowledge', 'model', 'plan'].includes(req.body?.mode)
      ? req.body.mode
      : 'auto';
    const rawModelVersion =
      req.body?.metadata?.modelVersion ||
      req.body?.metadata?.model_version ||
      req.body?.modelVariant ||
      'zyrquen-omega-v1';
    const modelVersion = String(rawModelVersion).trim().slice(0, 64) || 'zyrquen-omega-v1';

    if (!prompt && !attachment) {
      res.status(400).json({ error: 'Message content or attachment is required.' });
      return;
    }

    try {
      // Verify ownership before inference
      const convCheck = await runPythonScript<{ ok: boolean }>('db_bridge.py', {
        action: 'conv_get',
        payload: { user_id: req.user!.id, conversation_id: req.params.id },
      });
      if (!convCheck.ok) {
        res.status(404).json({ error: 'Conversation not found' });
        return;
      }

      const inference = await runPythonScript<{
        ok: boolean;
        error?: string;
        content?: string;
        status?: string;
        trace?: Record<string, unknown>;
      }>('zyrquen_core.py', {
        cmd: 'infer',
        payload: {
          prompt: prompt || 'Analyze attached context',
          mode,
          user_id: req.user!.id,
          conversation_id: req.params.id,
          attachment,
          model_version: modelVersion,
        },
      });

      if (!inference.ok || typeof inference.content !== 'string' || !inference.status) {
        res.status(502).json({
          error: inference.error || 'Python Native Core failed to return a valid inference response',
        });
        return;
      }
      if (inference.trace?.external_models_used !== false) {
        res.status(500).json({ error: 'Native integrity violation: external_models_used must be false' });
        return;
      }

      const userDisplay = attachment
        ? `${prompt || 'Attached snippet'}\n\n[Attachment: ${attachment.length} chars]`
        : prompt;

      const saved = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
        action: 'conv_save_exchange',
        payload: {
          user_id: req.user!.id,
          conversation_id: req.params.id,
          user_content: userDisplay,
          mode,
          assistant_content: inference.content,
          assistant_status: inference.status,
          trace: inference.trace,
        },
      });

      if (!saved.ok) {
        res.status(500).json({ error: saved.error || 'Failed to persist message' });
        return;
      }
      res.status(201).json(saved);
    } catch (err) {
      res.status(500).json({
        error: err instanceof Error ? err.message : 'Native inference failed',
      });
    }
  });

  app.post('/api/conversations/:id/stream', requireAuth, async (req: AuthedRequest, res: Response) => {
    const prompt = String(req.body?.content || '').trim();
    const attachment = String(req.body?.attachment || '').slice(0, 8000);
    const mode = ['auto', 'math', 'knowledge', 'model', 'plan'].includes(req.body?.mode)
      ? req.body.mode
      : 'auto';
    const rawModelVersion =
      req.body?.metadata?.modelVersion ||
      req.body?.metadata?.model_version ||
      req.body?.modelVariant ||
      'zyrquen-omega-v1';
    const modelVersion = String(rawModelVersion).trim().slice(0, 64) || 'zyrquen-omega-v1';

    if (!prompt && !attachment) {
      res.status(400).json({ error: 'Message content or attachment is required.' });
      return;
    }

    try {
      const convCheck = await runPythonScript<{ ok: boolean }>('db_bridge.py', {
        action: 'conv_get',
        payload: { user_id: req.user!.id, conversation_id: req.params.id },
      });
      if (!convCheck.ok) {
        res.status(404).json({ error: 'Conversation not found' });
        return;
      }

      const inference = await runPythonScript<{
        ok: boolean;
        error?: string;
        content?: string;
        status?: string;
        trace?: Record<string, unknown>;
      }>('zyrquen_core.py', {
        cmd: 'infer',
        payload: {
          prompt: prompt || 'Analyze attached context',
          mode,
          user_id: req.user!.id,
          conversation_id: req.params.id,
          attachment,
          model_version: modelVersion,
        },
      });

      if (!inference.ok || typeof inference.content !== 'string' || !inference.status) {
        res.status(502).json({
          error: inference.error || 'Python Native Core failed to return a valid inference response',
        });
        return;
      }
      if (inference.trace?.external_models_used !== false) {
        res.status(500).json({ error: 'Native integrity violation: external_models_used must be false' });
        return;
      }

      const userDisplay = attachment
        ? `${prompt || 'Attached snippet'}\n\n[Attachment: ${attachment.length} chars]`
        : prompt;

      const saved = await runPythonScript<{
        ok: boolean;
        error?: string;
        title?: string;
        user_message?: Record<string, unknown>;
        assistant_message?: Record<string, unknown>;
      }>('db_bridge.py', {
        action: 'conv_save_exchange',
        payload: {
          user_id: req.user!.id,
          conversation_id: req.params.id,
          user_content: userDisplay,
          mode,
          assistant_content: inference.content,
          assistant_status: inference.status,
          trace: inference.trace,
        },
      });

      if (!saved.ok) {
        res.status(500).json({ error: saved.error || 'Failed to persist message' });
        return;
      }

      res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
      res.setHeader('Cache-Control', 'no-cache, no-transform');
      res.setHeader('Connection', 'keep-alive');

      const writeEvent = (event: string, data: unknown) => {
        res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      };

      writeEvent('meta', {
        title: saved.title,
        modelVersion,
        user_message: saved.user_message,
      });

      const fullText = inference.content;
      const chunkSize = 48;
      for (let i = 0; i < fullText.length; i += chunkSize) {
        writeEvent('delta', { delta: fullText.slice(i, i + chunkSize) });
      }

      writeEvent('done', {
        title: saved.title,
        modelVersion,
        user_message: saved.user_message,
        assistant_message: saved.assistant_message,
      });
      res.end();
    } catch (err) {
      if (!res.headersSent) {
        res.status(500).json({
          error: err instanceof Error ? err.message : 'Native streaming inference failed',
        });
      } else {
        res.write(
          `event: error\ndata: ${JSON.stringify({ error: err instanceof Error ? err.message : 'Native streaming inference failed' })}\n\n`
        );
        res.end();
      }
    }
  });

  app.get('/api/knowledge', requireAuth, async (req: AuthedRequest, res: Response) => {
    const q = String(req.query.q || '').slice(0, 120);
    const data = await runPythonScript('db_bridge.py', {
      action: 'knowledge_list',
      payload: { q },
    });
    res.json(data);
  });

  app.post('/api/knowledge', requireAuth, async (req: AuthedRequest, res: Response) => {
    const subject = String(req.body?.subject || '').trim().slice(0, 120);
    const relation = String(req.body?.relation || '').trim().slice(0, 80);
    const object = String(req.body?.object || '').trim().slice(0, 200);
    if (!subject || !relation || !object) {
      res.status(400).json({ error: 'Subject, relation, and object are all required.' });
      return;
    }
    const created = await runPythonScript('db_bridge.py', {
      action: 'knowledge_create',
      payload: {
        subject,
        relation,
        object,
        user_id: req.user!.id,
        source: 'memory_studio',
      },
    });
    res.status(201).json(created);
  });

  app.delete('/api/knowledge/:id', requireAuth, async (req: AuthedRequest, res: Response) => {
    const deleted = await runPythonScript<{ ok: boolean }>('db_bridge.py', {
      action: 'knowledge_delete',
      payload: {
        triple_id: req.params.id,
        user_id: req.user!.id,
        is_admin: req.user!.role === 'admin',
      },
    });
    if (!deleted.ok) {
      res.status(404).json({ error: 'Triple not found or insufficient permission' });
      return;
    }
    res.json({ ok: true });
  });

  app.get('/api/workflows', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'workflows_list',
      payload: {
        user_id: req.user!.id,
        is_admin: req.user!.role === 'admin',
      },
    });
    res.json(data);
  });

  app.get('/api/workflows/reasoning-traces', requireAuth, async (req: AuthedRequest, res: Response) => {
    const q = String(req.query.q || '').trim().slice(0, 120);
    const status = String(req.query.status || '').trim().slice(0, 32);
    const rawLimit = Number(req.query.limit ?? 40);
    const limit = Number.isFinite(rawLimit) ? Math.max(1, Math.min(100, Math.round(rawLimit))) : 40;
    const data = await runPythonScript('db_bridge.py', {
      action: 'reasoning_traces_list',
      payload: {
        user_id: req.user!.id,
        is_admin: req.user!.role === 'admin',
        q,
        status,
        limit,
      },
    });
    res.json(data);
  });

  type WorkflowLogRunRecord = {
    id: string;
    group_id?: string;
    status?: string;
    triggered_by?: string | null;
    summary?: string | null;
    stages_json?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };

  const handleWorkflowLogs = async (req: AuthedRequest, res: Response) => {
    const activeOnly = String(req.query.active_only ?? 'true').toLowerCase() !== 'false';
    const runIdFilter = String(req.query.run_id ?? '').trim() || null;
    if (runIdFilter && !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(runIdFilter)) {
      res.status(400).json({ error: 'Invalid workflow run_id identifier.' });
      return;
    }
    const rawLimit = Number(req.query.limit ?? 100);
    const limit = Number.isFinite(rawLimit) ? Math.max(1, Math.min(500, Math.round(rawLimit))) : 100;
    const isAdmin = req.user!.role === 'admin';
    const currentUid = req.user!.id;

    let explicitRun: WorkflowLogRunRecord | null = null;
    if (runIdFilter) {
      const lookup = await runPythonScript<{
        ok: boolean;
        run?: WorkflowLogRunRecord | null;
      }>('db_bridge.py', {
        action: 'workflow_get_run',
        payload: { run_id: runIdFilter },
      });
      explicitRun = lookup.run ?? null;
      if (!explicitRun) {
        res.status(404).json({ error: 'Workflow run not found' });
        return;
      }
      if (!isAdmin && explicitRun.triggered_by !== currentUid) {
        res.status(403).json({ error: 'Forbidden' });
        return;
      }
    }

    const data = await runPythonScript<{
      ok: boolean;
      runs?: WorkflowLogRunRecord[];
    }>('db_bridge.py', {
      action: 'workflows_list',
      payload: {
        user_id: currentUid,
        is_admin: isAdmin,
      },
    });

    const activeStatuses = new Set([
      'PENDING',
      'PENDING_APPROVAL',
      'RUNNING',
      'VERIFYING',
      'WAITING_APPROVAL',
      'WAITING_RESOURCE',
    ]);

    const levelFor = (st?: string | null): 'INFO' | 'WARN' | 'ERROR' => {
      const upper = String(st || '').toUpperCase();
      if (upper.includes('FAIL') || upper.includes('ERROR') || upper.includes('REJECT')) return 'ERROR';
      if (upper.includes('WAIT') || upper.includes('PENDING') || upper.includes('BLOCK') || upper.includes('CANCEL')) return 'WARN';
      return 'INFO';
    };

    const runs = (Array.isArray(data.runs) ? data.runs : []).filter(
      (r) => isAdmin || r.triggered_by === currentUid
    );
    const activeRuns = runs.filter((r) => activeStatuses.has(String(r.status || '').toUpperCase()));
    const targetRuns = explicitRun
      ? [explicitRun]
      : activeOnly
        ? activeRuns
        : runs.slice(0, 25);

    const items: Array<Record<string, unknown>> = [];
    for (const r of targetRuns) {
      const status = String(r.status || 'UNKNOWN');
      const workflowKey = String(r.group_id || 'workflow');
      const ts = r.updated_at || r.created_at || null;
      items.push({
        id: `run:${r.id}:${status}`,
        run_id: r.id,
        workflow_key: workflowKey,
        step_key: null,
        level: levelFor(status),
        event_type: `workflow.${status.toLowerCase()}`,
        status,
        actor_id: r.triggered_by || 'orchestrator',
        message: r.summary || `Workflow ${workflowKey} is ${status}`,
        details: null,
        timestamp: ts,
      });

      if (typeof r.stages_json === 'string' && r.stages_json.trim()) {
        try {
          const stages = JSON.parse(r.stages_json) as Array<Record<string, unknown>>;
          if (Array.isArray(stages)) {
            stages.forEach((stage, idx) => {
              const stepKey = String(stage.name || stage.step_key || stage.stage || `stage_${idx + 1}`);
              const stepStatus = String(stage.status || status);
              items.push({
                id: `step:${r.id}:${stepKey}:${stepStatus}:${idx}`,
                run_id: r.id,
                workflow_key: workflowKey,
                step_key: stepKey,
                level: levelFor(stepStatus),
                event_type: `step.${stepStatus.toLowerCase()}`,
                status: stepStatus,
                actor_id: r.triggered_by || 'orchestrator',
                message: String(stage.detail || stage.summary || `${stepKey}: ${stepStatus}`),
                details: null,
                timestamp: String(stage.updated_at || stage.finished_at || stage.started_at || ts || ''),
              });
            });
          }
        } catch {
          // Ignore malformed stage JSON
        }
      }
    }

    items.sort((a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || '')));

    res.json({
      items: items.slice(0, limit),
      active_runs: activeRuns.map((r) => ({
        id: r.id,
        workflow_key: String(r.group_id || 'workflow'),
        status: String(r.status || 'UNKNOWN'),
        started_at: r.created_at ?? null,
      })),
      active_only: activeOnly,
      polled_at: new Date().toISOString(),
    });
  };

  app.get('/api/workflows/logs', requireAuth, handleWorkflowLogs);
  app.get('/api/v1/workflows/logs', requireAuth, handleWorkflowLogs);

  app.post('/api/workflows/:groupId/run', requireAuth, async (req: AuthedRequest, res: Response) => {
    const datasetId = req.body?.datasetId ? String(req.body.datasetId) : null;
    const result = await runPythonScript<{ ok: boolean; run?: Record<string, unknown>; error?: string }>(
      'zyrquen_core.py',
      {
        cmd: 'run_workflow',
        payload: {
          group_id: req.params.groupId,
          user_id: req.user!.id,
          approved_by: null,
          dataset_id: datasetId,
        },
      }
    );
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Workflow run failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: `WORKFLOW_${req.params.groupId.toUpperCase()}`,
        target: String(result.run?.id || req.params.groupId),
        outcome: String(result.run?.status || 'UNKNOWN'),
      },
    });
    res.status(201).json(result);
  });

  app.get('/api/autonomous/missions', requireAuth, async (_req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'missions_list',
      payload: {},
    });
    res.json(data);
  });

  app.post('/api/autonomous/missions', requireAuth, async (req: AuthedRequest, res: Response) => {
    const goal = String(req.body?.goal || '').trim().slice(0, 400);
    if (!goal) {
      res.status(400).json({ error: 'Mission goal is required.' });
      return;
    }
    const enableResearch = (req.body?.enableResearch ?? req.body?.enable_research) !== false;
    const enableKnowledgeDev =
      (req.body?.enableKnowledgeDev ?? req.body?.enable_knowledge_dev) !== false;
    const enablePlanning = (req.body?.enablePlanning ?? req.body?.enable_planning) !== false;
    const enableExecution = (req.body?.enableExecution ?? req.body?.enable_execution) !== false;

    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      mission?: Record<string, unknown>;
    }>('zyrquen_core.py', {
      cmd: 'run_mission',
      payload: {
        goal,
        user_id: req.user!.id,
        user_role: req.user!.role,
        enable_research: enableResearch,
        enable_knowledge_dev: enableKnowledgeDev,
        enable_planning: enablePlanning,
        enable_execution: enableExecution,
      },
    });
    if (!result.ok || !result.mission) {
      res.status(400).json({ error: result.error || 'Autonomous mission failed' });
      return;
    }
    if (Number(result.mission.external_models_used ?? 0) !== 0) {
      res.status(500).json({ error: 'Native integrity violation: external_models_used must be 0' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'AUTONOMOUS_MISSION',
        target: String(result.mission.id || 'mission'),
        outcome: String(result.mission.status || 'UNKNOWN'),
      },
    });
    res.status(201).json(result);
  });

  app.get('/api/autonomous/missions/:id', requireAuth, async (req: AuthedRequest, res: Response) => {
    const missionId = String(req.params.id || '').trim().slice(0, 64);
    if (!missionId) {
      res.status(400).json({ error: 'Mission id is required.' });
      return;
    }
    const data = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
      action: 'mission_detail',
      payload: { mission_id: missionId },
    });
    if (!data.ok) {
      res.status(404).json({ error: data.error || 'Mission not found' });
      return;
    }
    res.json(data);
  });

  app.post('/api/autonomous/missions/:id/resume', requireAuth, async (req: AuthedRequest, res: Response) => {
    const missionId = String(req.params.id || '').trim().slice(0, 64);
    if (!missionId) {
      res.status(400).json({ error: 'Mission id is required.' });
      return;
    }
    const detail = await runPythonScript<{
      ok: boolean;
      mission?: { created_by?: string };
      error?: string;
    }>('db_bridge.py', {
      action: 'mission_detail',
      payload: { mission_id: missionId },
    });
    if (!detail.ok || !detail.mission) {
      res.status(404).json({ error: detail.error || 'Mission not found' });
      return;
    }
    if (detail.mission.created_by !== req.user!.id && req.user!.role !== 'admin') {
      res.status(403).json({ error: 'Insufficient permission to resume this mission' });
      return;
    }
    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      mission?: Record<string, unknown>;
    }>('zyrquen_core.py', {
      cmd: 'resume_mission',
      payload: {
        mission_id: missionId,
        approved_by: null,
      },
    });
    if (!result.ok || !result.mission) {
      res.status(400).json({ error: result.error || 'Unable to resume mission' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'AUTONOMOUS_MISSION_RESUME',
        target: missionId,
        outcome: String(result.mission.status || 'UNKNOWN'),
      },
    });
    res.json(result);
  });

  app.post('/api/autonomous/missions/:id/cancel', requireAuth, async (req: AuthedRequest, res: Response) => {
    const missionId = String(req.params.id || '').trim().slice(0, 64);
    if (!missionId) {
      res.status(400).json({ error: 'Mission id is required.' });
      return;
    }
    const detail = await runPythonScript<{
      ok: boolean;
      mission?: { created_by?: string };
      error?: string;
    }>('db_bridge.py', {
      action: 'mission_detail',
      payload: { mission_id: missionId },
    });
    if (!detail.ok || !detail.mission) {
      res.status(404).json({ error: detail.error || 'Mission not found' });
      return;
    }
    if (detail.mission.created_by !== req.user!.id && req.user!.role !== 'admin') {
      res.status(403).json({ error: 'Insufficient permission to cancel this mission' });
      return;
    }
    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      mission?: Record<string, unknown>;
    }>('zyrquen_core.py', {
      cmd: 'cancel_mission',
      payload: { mission_id: missionId },
    });
    if (!result.ok || !result.mission) {
      res.status(400).json({ error: result.error || 'Unable to cancel mission' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'AUTONOMOUS_MISSION_CANCEL',
        target: missionId,
        outcome: String(result.mission.status || 'CANCELLED'),
      },
    });
    res.json(result);
  });

  app.post(
    '/api/workflows/runs/:runId/decide',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const decision = req.body?.decision === 'reject' ? 'reject' : 'approve';
      const datasetId = req.body?.datasetId ? String(req.body.datasetId) : null;
      const result = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
        action: 'workflow_decide',
        payload: {
          run_id: req.params.runId,
          decision,
          admin_email: req.user!.email,
          admin_id: req.user!.id,
          dataset_id: datasetId,
        },
      });
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Decision failed' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: `APPROVAL_GATE_${decision.toUpperCase()}`,
          target: req.params.runId,
          outcome: 'RECORDED',
        },
      });
      res.json(result);
    }
  );

  app.get('/api/developer/overview', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'dev_overview',
      payload: { user_id: req.user!.id },
    });
    res.json(data);
  });

  app.get(
    '/api/developer/artifacts/:version/download',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      const versionParam = String(req.params.version || '').trim();
      const kind = String(req.query.kind || '').trim().toLowerCase();
      if (!/^[A-Za-z0-9._-]{1,64}$/.test(versionParam)) {
        res.status(400).json({ error: 'Invalid model version identifier.' });
        return;
      }
      if (kind !== 'logs' && kind !== 'manifest') {
        res.status(400).json({ error: "Query parameter 'kind' must be 'logs' or 'manifest'." });
        return;
      }

      const result = await runPythonScript<{
        ok: boolean;
        status?: number;
        error?: string;
        filename?: string;
        content_type?: string;
        content?: string;
      }>('db_bridge.py', {
        action: 'dev_artifact_download',
        payload: { version: versionParam, kind },
      });

      if (!result.ok || typeof result.content !== 'string') {
        const statusCode = result.status === 400 || result.status === 404 ? result.status : 404;
        res.status(statusCode).json({ error: result.error || 'Training artifact not found.' });
        return;
      }

      const safeFilename = String(result.filename || `zyrquen-${versionParam}-${kind}.json`).replace(
        /[^A-Za-z0-9._-]/g,
        '_'
      );
      const fileSha256 = crypto.createHash('sha256').update(result.content, 'utf8').digest('hex');

      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: 'TRAINING_ARTIFACT_DOWNLOAD',
          target: `${versionParam}:${kind}`,
          outcome: `OK (${fileSha256.slice(0, 12)})`,
        },
      }).catch(() => null);

      res.setHeader('Content-Disposition', `attachment; filename="${safeFilename}"`);
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
      res.setHeader('Pragma', 'no-cache');
      res.setHeader('X-Zyrquen-File-Sha256', fileSha256);
      res.setHeader('Content-Type', result.content_type || 'application/json; charset=utf-8');
      res.status(200).send(result.content);
    }
  );

  app.post('/api/developer/keys', requireAuth, async (req: AuthedRequest, res: Response) => {
    const name = String(req.body?.name || '').trim().slice(0, 64);
    const scopes = Array.isArray(req.body?.scopes)
      ? req.body.scopes.map(String).slice(0, 5)
      : ['infer:read'];
    if (name.length < 2) {
      res.status(400).json({ error: 'API key name must be at least 2 characters.' });
      return;
    }
    const rawSecret = `zyrq_${crypto.randomBytes(24).toString('hex')}`;
    const keyPrefix = rawSecret.slice(0, 12);
    const keyHash = crypto.createHash('sha256').update(rawSecret).digest('hex');

    const created = await runPythonScript<{ ok: boolean; key?: Record<string, unknown> }>('db_bridge.py', {
      action: 'dev_key_create',
      payload: {
        user_id: req.user!.id,
        name,
        key_prefix: keyPrefix,
        key_hash: keyHash,
        scopes,
        quota_daily: 1000,
      },
    });
    res.status(201).json({ ...created, plaintextKey: rawSecret });
  });

  app.delete('/api/developer/keys/:id', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript<{ ok: boolean }>('db_bridge.py', {
      action: 'dev_key_revoke',
      payload: { key_id: req.params.id, user_id: req.user!.id },
    });
    if (!data.ok) {
      res.status(404).json({ error: 'API key not found' });
      return;
    }
    res.json({ ok: true });
  });

  app.post('/api/developer/keys/bulk-revoke', requireAuth, async (req: AuthedRequest, res: Response) => {
    const rawIds = Array.isArray(req.body?.ids) ? req.body.ids : null;
    if (!rawIds || rawIds.length === 0) {
      res.status(400).json({ error: 'กรุณาเลือก API Key อย่างน้อย 1 รายการ' });
      return;
    }
    const ids = Array.from(
      new Set(rawIds.map((id: unknown) => String(id || '').trim()).filter(Boolean))
    ).slice(0, 100);
    if (ids.length === 0) {
      res.status(400).json({ error: 'กรุณาเลือก API Key อย่างน้อย 1 รายการ' });
      return;
    }

    const data = await runPythonScript<{
      ok: boolean;
      revoked_ids?: string[];
      revoked_count?: number;
      error?: string;
    }>('db_bridge.py', {
      action: 'dev_key_bulk_revoke',
      payload: { key_ids: ids, user_id: req.user!.id },
    });

    if (!data.ok || !data.revoked_count) {
      res.status(404).json({ error: 'ไม่พบ API Key ที่ใช้งานอยู่ตามรายการที่เลือก' });
      return;
    }

    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'API_KEYS_BULK_REVOKE',
        target: `${data.revoked_count} keys`,
        outcome: 'SUCCESS',
        details_json: JSON.stringify({ revoked_ids: data.revoked_ids || [] }),
      },
    });

    res.json({
      ok: true,
      revokedIds: data.revoked_ids || [],
      revokedCount: data.revoked_count,
    });
  });

  app.post('/api/developer/datasets', requireAuth, async (req: AuthedRequest, res: Response) => {
    const name = String(req.body?.name || '').trim().slice(0, 80);
    const content = req.body?.content !== undefined ? String(req.body.content).slice(0, 1500000) : '';
    const splits =
      req.body?.splits && typeof req.body.splits === 'object' && !Array.isArray(req.body.splits)
        ? req.body.splits
        : undefined;
    const provenance = String(req.body?.provenance || 'developer_manual_corpus').trim().slice(0, 160);
    const sourceName = String(
      req.body?.sourceName || req.body?.source_name || provenance || 'developer_manual_corpus'
    )
      .trim()
      .slice(0, 120);
    const license = String(req.body?.license || 'INTERNAL_VERIFIED').trim().slice(0, 120);
    const format = String(req.body?.format || 'auto').trim().toLowerCase().slice(0, 24);
    const extractKg = req.body?.extractKg ?? req.body?.extract_kg ?? true;
    const redactPii = req.body?.redactPii ?? req.body?.redact_pii ?? true;
    const strictEntityIsolation =
      req.body?.strictEntityIsolation ?? req.body?.strict_entity_isolation ?? false;

    if (!name || (!content && !splits)) {
      res.status(400).json({ error: 'Dataset name and content (or splits) are required.' });
      return;
    }
    const result = await runPythonScript<{
      ok: boolean;
      dataset?: { id: string; name: string; total_records: number; status?: string; source_format?: string };
      kg_proposal?: { id: string; status: string; triple_count: number } | null;
      pii_redaction_summary?: {
        email: number;
        thai_id: number;
        card_number: number;
        phone: number;
        total_redacted: number;
      };
      error?: string;
    }>('zyrquen_core.py', {
      cmd: 'ingest_dataset',
      payload: {
        name,
        content,
        splits,
        provenance,
        source_name: sourceName,
        license,
        format,
        extract_kg: Boolean(extractKg),
        redact_pii: Boolean(redactPii),
        strict_entity_isolation: Boolean(strictEntityIsolation),
        user_id: req.user!.id,
      },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Dataset ingestion failed' });
      return;
    }
    const piiSummary = result.pii_redaction_summary;
    const totalPiiRedacted = Number(piiSummary?.total_redacted || 0);
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'DATASET_INGEST',
        target: String(result.dataset?.id || name),
        outcome: `${String(result.dataset?.status || 'READY')} (${result.dataset?.total_records ?? 0} records)`,
        details: {
          pii_redacted: Boolean(redactPii),
          pii_redaction_summary: piiSummary || null,
          source_format: result.dataset?.source_format || format,
        },
      },
    });
    if (Boolean(redactPii) && totalPiiRedacted > 0) {
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: 'PII_REDACTION',
          target: String(result.dataset?.id || name),
          outcome: `REDACTED_${totalPiiRedacted}_PII_ITEMS`,
          details: {
            event_category: 'pii_redaction',
            pii_redacted: true,
            total_redacted: totalPiiRedacted,
            categories: piiSummary,
            dataset_name: name,
          },
        },
      });
    }
    res.status(201).json(result);
  });

  app.get('/api/developer/datasets/:id/verify', requireAuth, async (req: AuthedRequest, res: Response) => {
    const datasetId = String(req.params.id || '').trim().slice(0, 64);
    if (!datasetId) {
      res.status(400).json({ error: 'Dataset ID is required.' });
      return;
    }
    const result = await runPythonScript<{ ok: boolean; verified?: boolean; error?: string }>(
      'zyrquen_core.py',
      {
        cmd: 'verify_dataset',
        payload: { dataset_id: datasetId },
      }
    );
    if (!result.ok && result.error === 'Dataset not found') {
      res.status(404).json({ error: result.error });
      return;
    }
    res.json(result);
  });

  app.get('/api/developer/kg-proposals', requireAuth, async (_req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'kg_proposals_list',
      payload: {},
    });
    res.json(data);
  });

  app.post('/api/developer/evaluate', requireAuth, async (req: AuthedRequest, res: Response) => {
    const suiteName = String(req.body?.suiteName || 'ZYRQUEN Scientific Benchmark v1').slice(0, 80);
    const result = await runPythonScript<{
      ok: boolean;
      evaluation?: Record<string, unknown>;
      error?: string;
    }>('zyrquen_core.py', {
      cmd: 'evaluate',
      payload: { user_id: req.user!.id, suite_name: suiteName },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Evaluation failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'SCIENTIFIC_EVALUATION',
        target: String(result.evaluation?.id || 'suite'),
        outcome: String(result.evaluation?.overall_status || 'UNKNOWN'),
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/curate-corpus', requireAuth, async (req: AuthedRequest, res: Response) => {
    const name = String(req.body?.name || 'verified-knowledge-corpus').trim().slice(0, 80) || 'verified-knowledge-corpus';
    const result = await runPythonScript<{ ok: boolean; error?: string; dataset?: Record<string, unknown> }>(
      'zyrquen_core.py',
      {
        cmd: 'curate_corpus',
        payload: { user_id: req.user!.id, name },
      }
    );
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Corpus curation failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'CORPUS_CURATED',
        target: String(result.dataset?.id || name),
        outcome: 'READY',
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/experiments', requireAuth, async (req: AuthedRequest, res: Response) => {
    const datasetId = req.body?.datasetId ? String(req.body.datasetId).trim().slice(0, 64) : null;
    const rawEpochs = Number(req.body?.epochs ?? 8);
    const epochs = Number.isFinite(rawEpochs) ? Math.max(2, Math.min(20, Math.round(rawEpochs))) : 8;
    const rawSeed = Number(req.body?.seed ?? 42);
    const seed = Number.isFinite(rawSeed) ? Math.round(rawSeed) : 42;
    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      experiment?: Record<string, unknown>;
      improved?: boolean;
    }>('zyrquen_core.py', {
      cmd: 'run_experiment',
      payload: {
        user_id: req.user!.id,
        dataset_id: datasetId,
        epochs,
        seed,
        require_baseline_and_approval: true,
      },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Neural experiment failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'NEURAL_EXPERIMENT_RUN',
        target: String(result.experiment?.id || 'experiment'),
        outcome: String(result.experiment?.approval_status || 'RECORDED'),
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/code-training/curate', requireAuth, async (req: AuthedRequest, res: Response) => {
    const name =
      String(req.body?.name || 'code-problem-solving-corpus').trim().slice(0, 80) ||
      'code-problem-solving-corpus';
    const extraTasks = Array.isArray(req.body?.extraTasks) ? req.body.extraTasks.slice(0, 25) : undefined;
    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      dataset?: Record<string, unknown>;
      code_verification?: Record<string, unknown>;
    }>('zyrquen_core.py', {
      cmd: 'curate_code_corpus',
      payload: {
        user_id: req.user!.id,
        name,
        extra_tasks: extraTasks,
      },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Code corpus curation failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'CODE_CORPUS_CURATED',
        target: String(result.dataset?.id || name),
        outcome: `VERIFIED_${String(result.code_verification?.verified_tasks ?? 0)}`,
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/code-training/experiment', requireAuth, async (req: AuthedRequest, res: Response) => {
    const datasetId = req.body?.datasetId ? String(req.body.datasetId).trim().slice(0, 64) : null;
    const rawEpochs = Number(req.body?.epochs ?? 3);
    const epochs = Number.isFinite(rawEpochs) ? Math.max(2, Math.min(8, Math.round(rawEpochs))) : 3;
    const rawSeed = Number(req.body?.seed ?? 42);
    const seed = Number.isFinite(rawSeed) ? Math.round(rawSeed) : 42;
    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      experiment?: Record<string, unknown>;
      improved?: boolean;
      metrics?: Record<string, unknown>;
      external_models_used?: boolean;
    }>('zyrquen_core.py', {
      cmd: 'run_code_training_experiment',
      payload: {
        user_id: req.user!.id,
        dataset_id: datasetId,
        epochs,
        seed,
      },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Code training experiment failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'CODE_TRAINING_EXPERIMENT',
        target: String(result.experiment?.id || 'code-experiment'),
        outcome: String(result.experiment?.approval_status || 'RECORDED'),
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/code-training/evaluate', requireAuth, async (req: AuthedRequest, res: Response) => {
    const result = await runPythonScript<{
      ok: boolean;
      status?: string;
      error?: string;
      external_models_used?: boolean;
    }>('zyrquen_core.py', {
      cmd: 'evaluate_code_model',
      payload: {},
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Code model evaluation failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'CODE_MODEL_EVALUATED',
        target: 'native_code_probe',
        outcome: String(result.status || 'UNKNOWN'),
      },
    });
    res.status(200).json(result);
  });

  app.post('/api/developer/real-only-training', requireAuth, requireAdmin, async (req: AuthedRequest, res: Response) => {
    const dataPath = String(req.body?.dataPath || '').trim().slice(0, 300);
    if (!dataPath) {
      res.status(400).json({ ok: false, status: 'BLOCKED', error: 'STOP: dataPath is required for real-only JSONL training.' });
      return;
    }
    const rawEpochs = Number(req.body?.epochs ?? 5);
    const epochs = Number.isFinite(rawEpochs) ? Math.max(1, Math.min(200, Math.round(rawEpochs))) : 5;
    const rawLr = Number(req.body?.lr ?? 0.05);
    const lr = Number.isFinite(rawLr) && rawLr > 0 && rawLr <= 1.0 ? rawLr : 0.05;
    const rawSeed = Number(req.body?.seed ?? 42);
    const seed = Number.isFinite(rawSeed) ? Math.round(rawSeed) : 42;
    const rawMinSamples = Number(req.body?.minSamples ?? 30);
    const minSamples = Number.isFinite(rawMinSamples) ? Math.max(30, Math.min(10000, Math.round(rawMinSamples))) : 30;

    const result = await runPythonScript<{
      ok: boolean;
      status?: string;
      error?: string;
      run_id?: string;
      approval?: string;
      external_models_used?: boolean;
    }>('zyrquen_core.py', {
      cmd: 'run_real_only_jsonl_training',
      payload: {
        user_id: req.user!.id,
        data_path: dataPath,
        epochs,
        lr,
        seed,
        min_samples: minSamples,
        sandbox_audit: Boolean(req.body?.sandboxAudit),
        require_sandbox_pass: Boolean(req.body?.requireSandboxPass),
      },
    });
    if (!result.ok) {
      res.status(400).json(result);
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'REAL_ONLY_JSONL_TRAINING',
        target: String(result.run_id || 'real-only-run'),
        outcome: String(result.approval || result.status || 'RECORDED'),
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/curriculum/synthesize', requireAuth, async (req: AuthedRequest, res: Response) => {
    const rawLimit = Number(req.body?.limit ?? 50);
    const limit = Number.isFinite(rawLimit) ? Math.max(1, Math.min(200, Math.round(rawLimit))) : 50;
    const heldoutPrompts = Array.isArray(req.body?.heldoutPrompts)
      ? req.body.heldoutPrompts.slice(0, 200).map((item: unknown) => String(item))
      : undefined;

    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      curriculum_count?: number;
      manifest_sha256?: string;
    }>('zyrquen_core.py', {
      cmd: 'synthesize_curriculum',
      payload: { limit, heldout_prompts: heldoutPrompts },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Curriculum synthesis failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'CURRICULUM_SYNTHESIZED',
        target: String(result.manifest_sha256 || 'curriculum').slice(0, 16),
        outcome: `ITEMS_${String(result.curriculum_count ?? 0)}`,
      },
    });
    res.status(201).json(result);
  });

  app.post('/api/developer/continual-learning/run', requireAuth, async (req: AuthedRequest, res: Response) => {
    const newTrainLines = Array.isArray(req.body?.newTrainLines)
      ? req.body.newTrainLines.slice(0, 200).map((s: unknown) => String(s))
      : undefined;
    const anchorLines = Array.isArray(req.body?.anchorLines)
      ? req.body.anchorLines.slice(0, 200).map((s: unknown) => String(s))
      : undefined;
    const rawEpochs = Number(req.body?.epochs ?? 6);
    const epochs = Number.isFinite(rawEpochs) ? Math.max(1, Math.min(20, Math.round(rawEpochs))) : 6;
    const rawReplay = Number(req.body?.replayRatio ?? 0.35);
    const replayRatio = Number.isFinite(rawReplay) ? Math.max(0, Math.min(1, rawReplay)) : 0.35;
    const rawLambda = Number(req.body?.anchorL2Lambda ?? 0.02);
    const anchorL2Lambda = Number.isFinite(rawLambda) ? Math.max(0, Math.min(1, rawLambda)) : 0.02;
    const rawSeed = Number(req.body?.seed ?? 42);
    const seed = Number.isFinite(rawSeed) ? Math.round(rawSeed) : 42;

    const result = await runPythonScript<{
      ok: boolean;
      error?: string;
      experiment?: Record<string, unknown>;
      catastrophic_forgetting_detected?: boolean;
    }>('zyrquen_core.py', {
      cmd: 'run_continual_round',
      payload: {
        user_id: req.user!.id,
        new_train_lines: newTrainLines,
        anchor_lines: anchorLines,
        epochs,
        replay_ratio: replayRatio,
        anchor_l2_lambda: anchorL2Lambda,
        seed,
      },
    });
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Continual learning round failed' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'CONTINUAL_LEARNING_ROUND',
        target: String(result.experiment?.id || 'continual'),
        outcome: String(result.experiment?.approval_status || 'RECORDED'),
      },
    });
    res.status(201).json(result);
  });

  const ALLOWED_BENCHMARK_MODELS = new Set([
    'zyrquen-omega-v1',
    'zyrquen-ast-pro',
    'zyrquen-kg-v2',
    'zyrquen-ngram-ckpt',
    'zyrquen-neural-v1',
  ]);

  app.post('/api/developer/benchmark', requireAuth, async (req: AuthedRequest, res: Response) => {
    const requestedModel = String(req.body?.modelVersion || 'zyrquen-omega-v1').trim();
    if (!ALLOWED_BENCHMARK_MODELS.has(requestedModel)) {
      res.status(400).json({ error: 'Unsupported modelVersion for native benchmark' });
      return;
    }

    try {
      if (pythonUnavailable) {
        const blocked = runFallbackBenchmark(requestedModel);
        res.status(503).json(blocked);
        return;
      }

      let report: Record<string, unknown>;
      try {
        report = await new Promise<Record<string, unknown>>((resolve, reject) => {
          const pyCode = [
            'import json, sys',
            'from tests.benchmark_suite import run_capability_benchmark',
            'print(json.dumps(run_capability_benchmark(model_version=sys.argv[1], persist_baseline=True), ensure_ascii=False))',
          ].join('; ');
          const child = spawn('python3', ['-c', pyCode, requestedModel], {
            cwd: __dirname,
            stdio: ['ignore', 'pipe', 'pipe'],
            env: {
              ...process.env,
              PYTHONPATH: path.resolve(__dirname, 'python_core'),
            },
          });

          let stdout = '';
          let stderr = '';
          const timer = setTimeout(() => {
            child.kill('SIGTERM');
            reject(new Error('Native capability benchmark timed out'));
          }, 60_000);

          child.stdout.on('data', (chunk: Buffer) => {
            stdout += chunk.toString('utf-8');
          });
          child.stderr.on('data', (chunk: Buffer) => {
            stderr += chunk.toString('utf-8');
          });
          child.on('error', (err) => {
            clearTimeout(timer);
            reject(err);
          });
          child.on('close', (code) => {
            clearTimeout(timer);
            if (code !== 0) {
              reject(new Error(stderr.trim() || `Benchmark exited with code ${code}`));
              return;
            }
            try {
              const parsed = JSON.parse(stdout.trim()) as Record<string, unknown>;
              resolve(parsed);
            } catch (err) {
              reject(new Error(`Invalid JSON from benchmark_suite.py: ${(err as Error).message}`));
            }
          });
        });
      } catch (spawnErr) {
        const code = (spawnErr as NodeJS.ErrnoException | undefined)?.code;
        const msg = spawnErr instanceof Error ? spawnErr.message : String(spawnErr);
        if (code === 'ENOENT' || code === 'EACCES' || /spawn python3 ENOENT/i.test(msg)) {
          pythonUnavailable = true;
          const blocked = runFallbackBenchmark(requestedModel);
          res.status(503).json(blocked);
          return;
        }
        throw spawnErr;
      }

      const summary = (report.summary || {}) as Record<string, unknown>;
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: 'CAPABILITY_BENCHMARK_RUN',
          target: requestedModel,
          outcome: `${String(summary.passed ?? 0)}/${String(summary.total_cases ?? 0)}`,
        },
      });

      res.status(200).json({
        ok: true,
        executed_at: new Date().toISOString(),
        report,
      });
    } catch (err) {
      res.status(500).json({
        error: err instanceof Error ? err.message : 'Native capability benchmark failed',
      });
    }
  });

  app.get('/api/developer/tools', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'tools_overview',
      payload: { user_id: req.user!.id },
    });
    res.json(data);
  });

  app.post('/api/developer/workspace-files', requireAuth, async (req: AuthedRequest, res: Response) => {
    const filename = String(req.body?.filename || '').trim().slice(0, 96);
    const content = String(req.body?.content || '').slice(0, 50000);
    if (!filename || !content) {
      res.status(400).json({ error: 'Filename and content are required.' });
      return;
    }
    const result = await runPythonScript<{ ok: boolean; error?: string; file?: Record<string, unknown> }>(
      'db_bridge.py',
      {
        action: 'tools_upload_file',
        payload: { filename, content },
      }
    );
    if (!result.ok) {
      res.status(400).json({ error: result.error || 'Failed to save workspace file' });
      return;
    }
    res.status(201).json(result);
  });

  app.post(
    '/api/developer/tools/:toolId/invoke',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      const toolId = String(req.params.toolId || '').trim();
      const input =
        req.body?.input && typeof req.body.input === 'object' ? req.body.input : {};
      const result = await runPythonScript<{
        ok: boolean;
        status?: string;
        error?: string;
        invocation?: Record<string, unknown>;
      }>('db_bridge.py', {
        action: 'tools_invoke',
        payload: {
          tool_id: toolId,
          input,
          user_id: req.user!.id,
          conversation_id: req.body?.conversationId ? String(req.body.conversationId) : null,
        },
      });
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Tool invocation failed' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: `TOOL_INVOKE_${toolId.toUpperCase()}`,
          target: String(result.invocation?.id || toolId),
          outcome: String(result.status || 'UNKNOWN'),
        },
      });
      res.status(201).json(result);
    }
  );

  // --- ZYRQUEN Native Tool Center & Background Support Systems API ---
  app.get('/api/tool-center', requireAuth, async (req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'tool_center_overview',
      payload: { user_id: req.user!.id, user_role: req.user!.role },
    });
    res.json(data);
  });

  app.post('/api/tool-center/resolve', requireAuth, async (req: AuthedRequest, res: Response) => {
    const goal = String(req.body?.goal || '').trim().slice(0, 600);
    if (!goal) {
      res.status(400).json({ error: 'goal is required.' });
      return;
    }
    const data = await runPythonScript('db_bridge.py', {
      action: 'tool_center_resolve',
      payload: { goal, user_role: req.user!.role },
    });
    res.json(data);
  });

  app.post('/api/tool-center/execute', requireAuth, async (req: AuthedRequest, res: Response) => {
    const capabilityId = String(req.body?.capabilityId || req.body?.capability_id || '').trim().slice(0, 120);
    if (!capabilityId) {
      res.status(400).json({ error: 'capabilityId is required.' });
      return;
    }
    const input = req.body?.input && typeof req.body.input === 'object' ? req.body.input : {};
    const result = await runPythonScript<{
      ok: boolean;
      status?: string;
      error?: string;
    }>('db_bridge.py', {
      action: 'tool_center_execute',
      payload: {
        capability_id: capabilityId,
        input,
        user_id: req.user!.id,
        user_role: req.user!.role,
        project_id: req.body?.projectId ? String(req.body.projectId).slice(0, 64) : null,
        conversation_id: req.body?.conversationId ? String(req.body.conversationId).slice(0, 64) : null,
      },
    });
    if (result.status === 'BLOCKED') {
      res.status(403).json(result);
      return;
    }
    if (!result.ok) {
      res.status(400).json(result);
      return;
    }
    res.status(result.status === 'PENDING_APPROVAL' ? 202 : 201).json(result);
  });

  app.post('/api/tool-center/orchestrate', requireAuth, async (req: AuthedRequest, res: Response) => {
    const goal = String(req.body?.goal || '').trim().slice(0, 600);
    const steps = Array.isArray(req.body?.steps) ? req.body.steps : null;
    if (!goal || !steps || steps.length === 0) {
      res.status(400).json({ error: 'goal and non-empty steps array are required.' });
      return;
    }
    const result = await runPythonScript<{
      ok: boolean;
      status?: string;
      error_code?: string;
      error?: string;
    }>('db_bridge.py', {
      action: 'tool_center_orchestrate',
      payload: {
        goal,
        steps,
        user_id: req.user!.id,
        user_role: req.user!.role,
        shared_context: req.body?.sharedContext && typeof req.body.sharedContext === 'object' ? req.body.sharedContext : null,
        idempotency_scope: req.body?.idempotencyScope ? String(req.body.idempotencyScope).slice(0, 80) : null,
        enable_parallel: req.body?.enableParallel !== false,
      },
    });
    if (result.error_code === 'PERMISSION_BLOCKED') {
      res.status(403).json(result);
      return;
    }
    if (!result.ok && result.status !== 'PARTIAL_SUCCESS') {
      res.status(400).json(result);
      return;
    }
    res.status(200).json(result);
  });

  app.post('/api/tool-center/verify', requireAuth, async (req: AuthedRequest, res: Response) => {
    const toolkitId = req.body?.toolkitId ? String(req.body.toolkitId).trim().slice(0, 64) : '';
    const result = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
      action: 'tool_center_verify',
      payload: { toolkit_id: toolkitId || null },
    });
    if (!result.ok) {
      res.status(400).json(result);
      return;
    }
    res.json(result);
  });

  app.post(
    '/api/tool-center/self-improve',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const sandboxProbeCode =
        typeof req.body?.sandboxProbeCode === 'string'
          ? req.body.sandboxProbeCode.slice(0, 12000)
          : undefined;
      const result = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
        action: 'tool_center_self_improve',
        payload: {
          user_id: req.user!.id,
          sandbox_probe_code: sandboxProbeCode,
        },
      });
      if (!result.ok) {
        res.status(400).json(result);
        return;
      }
      res.status(201).json(result);
    }
  );

  app.post(
    '/api/tool-center/engineering/benchmark',
    requireAuth,
    async (_req: AuthedRequest, res: Response) => {
      const result = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
        action: 'tool_center_engineering_benchmark',
        payload: {},
      });
      if (!result.ok) {
        res.status(400).json(result);
        return;
      }
      res.json(result);
    }
  );

  app.get('/api/admin/overview', requireAuth, requireAdmin, async (_req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'admin_overview',
      payload: {},
    });
    res.json(data);
  });

  app.post(
    '/api/admin/overview/summary',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const summary = await runPythonScript<{ ok: boolean; error?: string }>('db_bridge.py', {
        action: 'admin_overview_summary',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
        },
      });
      if (!summary.ok) {
        res.status(500).json({ error: summary.error || 'Failed to generate admin overview summary' });
        return;
      }
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
      res.json(summary);
    }
  );

  app.get(
    '/api/admin/audit-logs/export',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const rawFocus = String(req.query.focus || 'pii_redaction').trim().toLowerCase();
      const focus = rawFocus === 'all' ? 'all' : 'pii_redaction';
      const rawFormat = String(req.query.format || 'json').trim().toLowerCase();
      const format = rawFormat === 'csv' ? 'csv' : 'json';
      const rawLimit = Number(req.query.limit ?? 1000);
      const limit = Number.isFinite(rawLimit) ? Math.max(1, Math.min(5000, Math.floor(rawLimit))) : 1000;

      const exportData = await runPythonScript<{
        ok: boolean;
        error?: string;
        schema: string;
        focus: 'pii_redaction' | 'all';
        format: 'json' | 'csv';
        exported_at: string;
        exported_by: { id: string; actor_email_masked: string };
        total_scanned: number;
        pii_redaction_event_count: number;
        exported_count: number;
        integrity_sha256: string;
        sanitization_applied: boolean;
        events: Array<{
          id: string;
          created_at: string;
          actor_id: string;
          actor_email_masked: string;
          action: string;
          target: string;
          outcome: string;
          is_pii_redaction_event: boolean;
          pii_redaction_summary: Record<string, unknown> | null;
          details: Record<string, unknown>;
          export_redactions_applied: number;
        }>;
      }>('db_bridge.py', {
        action: 'admin_export_audit_logs',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          focus,
          format,
          limit,
        },
      });

      if (!exportData.ok) {
        res.status(500).json({ error: exportData.error || 'Audit log export failed' });
        return;
      }

      const safeStamp = new Date().toISOString().replace(/[:.]/g, '-');
      const filename = `zyrquen-audit-${focus}-${safeStamp}.${format}`;

      res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
      res.setHeader('Pragma', 'no-cache');
      res.setHeader('X-Zyrquen-Export-Sha256', exportData.integrity_sha256);
      res.setHeader('X-Zyrquen-Export-Count', String(exportData.exported_count));
      res.setHeader('X-Zyrquen-Pii-Events', String(exportData.pii_redaction_event_count));

      if (format === 'csv') {
        const escapeSafeCsvCell = (val: unknown): string => {
          const raw = val === null || val === undefined ? '' : String(val);
          const flattened = raw.replace(/\r?\n/g, ' ');
          const neutralized = /^[=+\-@\t\r]/.test(flattened) ? `'${flattened}` : flattened;
          return /[",]/.test(neutralized) ? `"${neutralized.replace(/"/g, '""')}"` : neutralized;
        };
        const headers = [
          'id',
          'created_at',
          'actor_id',
          'actor_email_masked',
          'action',
          'target',
          'outcome',
          'is_pii_redaction_event',
          'pii_redaction_summary',
          'details_json',
          'integrity_sha256',
        ];
        const rows = exportData.events.map((ev) =>
          [
            ev.id,
            ev.created_at,
            ev.actor_id,
            ev.actor_email_masked,
            ev.action,
            ev.target,
            ev.outcome,
            ev.is_pii_redaction_event ? 'true' : 'false',
            ev.pii_redaction_summary ? JSON.stringify(ev.pii_redaction_summary) : '',
            JSON.stringify(ev.details || {}),
            exportData.integrity_sha256,
          ]
            .map(escapeSafeCsvCell)
            .join(',')
        );
        const csvBody = [headers.join(','), ...rows].join('\r\n');
        const fileSha256 = crypto.createHash('sha256').update(csvBody, 'utf8').digest('hex');
        res.setHeader('X-Zyrquen-File-Sha256', fileSha256);
        res.setHeader('Content-Type', 'text/csv; charset=utf-8');
        res.status(200).send(csvBody);
        return;
      }

      const jsonBody = JSON.stringify(exportData, null, 2);
      const fileSha256 = crypto.createHash('sha256').update(jsonBody, 'utf8').digest('hex');
      res.setHeader('X-Zyrquen-File-Sha256', fileSha256);
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.status(200).send(jsonBody);
    }
  );

  app.patch(
    '/api/admin/users/:id/role',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const role = req.body?.role === 'admin' ? 'admin' : 'user';
      if (req.params.id === req.user!.id && role !== 'admin') {
        res.status(400).json({ error: 'Cannot demote your own active administrator account.' });
        return;
      }
      const updated = await runPythonScript<{ ok: boolean }>('db_bridge.py', {
        action: 'admin_user_role',
        payload: { target_user_id: req.params.id, role },
      });
      if (!updated.ok) {
        res.status(404).json({ error: 'User not found' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: 'ROLE_UPDATED',
          target: req.params.id,
          outcome: role.toUpperCase(),
        },
      });
      res.json({ ok: true });
    }
  );

  app.patch(
    '/api/admin/tools/:toolId',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const permissionMode = req.body?.permission_mode ? String(req.body.permission_mode) : undefined;
      const enabled = typeof req.body?.enabled === 'boolean' ? req.body.enabled : undefined;
      const quotaDaily =
        req.body?.quota_daily !== undefined ? Number(req.body.quota_daily) : undefined;
      const endpointAllowlist = Array.isArray(req.body?.endpoint_allowlist)
        ? req.body.endpoint_allowlist.map(String)
        : undefined;

      const updated = await runPythonScript<{ ok: boolean; error?: string; tool?: Record<string, unknown> }>(
        'db_bridge.py',
        {
          action: 'admin_tools_update',
          payload: {
            tool_id: req.params.toolId,
            permission_mode: permissionMode,
            enabled,
            quota_daily: quotaDaily,
            endpoint_allowlist: endpointAllowlist,
          },
        }
      );
      if (!updated.ok) {
        res.status(400).json({ error: updated.error || 'Failed to update tool policy' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: 'ADMIN_TOOL_POLICY_UPDATED',
          target: req.params.toolId,
          outcome: String(updated.tool?.permission_mode || 'UPDATED').toUpperCase(),
        },
      });
      res.json(updated);
    }
  );

  app.post(
    '/api/admin/tool-invocations/:invocationId/decide',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const decision = req.body?.decision === 'reject' ? 'reject' : 'approve';
      const result = await runPythonScript<{ ok: boolean; error?: string; status?: string }>(
        'db_bridge.py',
        {
          action: 'admin_tool_decide',
          payload: {
            invocation_id: req.params.invocationId,
            decision,
            admin_email: req.user!.email,
          },
        }
      );
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Tool decision failed' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: `TOOL_GATE_${decision.toUpperCase()}`,
          target: req.params.invocationId,
          outcome: String(result.status || decision.toUpperCase()),
        },
      });
      res.json(result);
    }
  );

  app.post(
    '/api/admin/experiments/:id/decide',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const expId = String(req.params.id || '').trim().slice(0, 64);
      const decision = req.body?.decision === 'reject' ? 'reject' : 'approve';
      const result = await runPythonScript<{
        ok: boolean;
        error?: string;
        experiment?: Record<string, unknown>;
      }>('zyrquen_core.py', {
        cmd: 'decide_experiment',
        payload: {
          experiment_id: expId,
          decision,
          admin_email: req.user!.email,
          admin_id: req.user!.id,
        },
      });
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Experiment decision failed' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: `EXPERIMENT_GATE_${decision.toUpperCase()}`,
          target: expId,
          outcome: String(result.experiment?.approval_status || decision.toUpperCase()),
        },
      });
      res.json(result);
    }
  );

  app.post(
    '/api/admin/kg-proposals/:id/decide',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const proposalId = String(req.params.id || '').trim().slice(0, 64);
      const decision = req.body?.decision === 'reject' ? 'reject' : 'approve';
      const reason = req.body?.reason ? String(req.body.reason).trim().slice(0, 240) : undefined;
      const result = await runPythonScript<{
        ok: boolean;
        error?: string;
        proposal?: Record<string, unknown>;
        committed_triples?: number;
      }>('zyrquen_core.py', {
        cmd: 'decide_kg_proposal',
        payload: {
          proposal_id: proposalId,
          decision,
          admin_email: req.user!.email,
          admin_id: req.user!.id,
          reason,
        },
      });
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Knowledge Graph proposal decision failed' });
        return;
      }
      await runPythonScript('db_bridge.py', {
        action: 'log_audit',
        payload: {
          actor_id: req.user!.id,
          actor_email: req.user!.email,
          action: `KG_INGEST_GATE_${decision.toUpperCase()}`,
          target: proposalId,
          outcome: String(result.proposal?.status || decision.toUpperCase()),
        },
      });
      res.json(result);
    }
  );

  app.post(
    '/api/admin/tool-center-invocations/:invocationId/decide',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const decision = req.body?.decision === 'reject' ? 'reject' : 'approve';
      const result = await runPythonScript<{ ok: boolean; error?: string; status?: string }>(
        'db_bridge.py',
        {
          action: 'tool_center_decide',
          payload: {
            invocation_id: String(req.params.invocationId || '').trim().slice(0, 64),
            decision,
            admin_email: req.user!.email,
          },
        }
      );
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Tool Center invocation decision failed' });
        return;
      }
      res.json(result);
    }
  );

  app.post(
    '/api/admin/improvement-proposals/:id/decide',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      const proposalId = String(req.params.id || '').trim().slice(0, 64);
      const decision = req.body?.decision === 'approve' ? 'approve' : 'reject';
      const reason = req.body?.reason ? String(req.body.reason).trim().slice(0, 240) : undefined;
      const result = await runPythonScript<{ ok: boolean; error?: string; status?: string }>(
        'db_bridge.py',
        {
          action: 'tool_center_decide_improvement',
          payload: {
            proposal_id: proposalId,
            decision,
            admin_email: req.user!.email,
            admin_id: req.user!.id,
            reason,
          },
        }
      );
      if (!result.ok) {
        res.status(400).json({ error: result.error || 'Improvement proposal decision failed' });
        return;
      }
      res.json(result);
    }
  );

  // RealityCheck — RestoreProof (Sandbox & Full Control Center)
  type RestoreProofBridgeResult = {
    ok: boolean;
    status_code?: number;
    error?: string;
    [key: string]: unknown;
  };

  async function callRestoreProofBridge(
    action: string,
    payload: Record<string, unknown>,
    res: Response,
    successStatus = 200
  ): Promise<void> {
    if (pythonUnavailable) {
      res.status(503).json({
        ok: false,
        error: 'Python isolated verification worker is unavailable (fail-closed: UNVERIFIED).',
      });
      return;
    }
    try {
      const result = await runPythonScript<RestoreProofBridgeResult>('db_bridge.py', {
        action,
        payload,
      });
      if (!result || typeof result !== 'object' || !result.ok) {
        const code = typeof result?.status_code === 'number' ? result.status_code : 400;
        res.status(code).json({
          ok: false,
          error: result?.error || `RestoreProof action failed (${action})`,
        });
        return;
      }
      res.status(successStatus).json(result);
    } catch (err) {
      res.status(500).json({
        ok: false,
        error: err instanceof Error ? err.message : 'RestoreProof bridge failure',
      });
    }
  }

  app.get('/api/restoreproof/status', requireAuth, async (_req: AuthedRequest, res: Response) => {
    await callRestoreProofBridge('restoreproof_status', {}, res, 200);
  });

  app.post(
    '/api/restoreproof/verify-scenario',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      const scenario = String(req.body?.scenario || '').trim();
      const allowedScenarios = new Set([
        'valid_sqlite_backup',
        'corrupt_archive',
        'missing_tampered_file',
        'failed_health_check',
        'run_all_3_failures',
      ]);
      if (!allowedScenarios.has(scenario)) {
        res.status(400).json({ ok: false, error: `Unsupported scenario: ${scenario || '(empty)'}` });
        return;
      }
      await callRestoreProofBridge(
        'restoreproof_verify_scenario',
        { scenario, actor: req.user!.email },
        res,
        201
      );
    }
  );

  app.post(
    '/api/restoreproof/verify-bundle',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'restoreproof_verify_bundle',
        {
          sourceName: req.body?.sourceName,
          backupType: req.body?.backupType,
          files: req.body?.files,
          minFiles: req.body?.minFiles,
          simulateTamper: req.body?.simulateTamper,
          actor: req.user!.email,
        },
        res,
        201
      );
    }
  );

  app.delete('/api/restoreproof/history', requireAuth, async (_req: AuthedRequest, res: Response) => {
    await callRestoreProofBridge('restoreproof_history_clear', {}, res, 200);
  });

  app.get(
    '/api/restoreproof/control/overview',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_overview',
        { actor: req.user!.email },
        res,
        200
      );
    }
  );

  app.post(
    '/api/restoreproof/control/backups',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_create_backup',
        {
          name: req.body?.name,
          preset: req.body?.preset,
          uri: req.body?.uri,
          backup_format: req.body?.backup_format,
          actor: req.user!.email,
        },
        res,
        201
      );
    }
  );

  app.post(
    '/api/restoreproof/control/backups/:id/check',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_check_backup',
        {
          backup_id: String(req.params.id || '').trim().slice(0, 64),
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.delete(
    '/api/restoreproof/control/backups/:id',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_delete_backup',
        {
          backup_id: String(req.params.id || '').trim().slice(0, 64),
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.post(
    '/api/restoreproof/control/targets',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_create_target',
        {
          name: req.body?.name,
          engine: req.body?.engine,
          isolation_mode: req.body?.isolation_mode,
          target_dbname: req.body?.target_dbname,
          host: req.body?.host,
          port: req.body?.port,
          user: req.body?.user,
          drop_after_verify: req.body?.drop_after_verify,
          actor: req.user!.email,
        },
        res,
        201
      );
    }
  );

  app.delete(
    '/api/restoreproof/control/targets/:id',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_delete_target',
        {
          target_id: String(req.params.id || '').trim().slice(0, 64),
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.post(
    '/api/restoreproof/control/verifications',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_start_verification',
        {
          backup_source_id: req.body?.backup_source_id,
          target_id: req.body?.target_id,
          target_dbname: req.body?.target_dbname,
          isolation_mode: req.body?.isolation_mode,
          min_total_rows: req.body?.min_total_rows,
          required_tables: req.body?.required_tables,
          priority: req.body?.priority,
          timeout_sec: req.body?.timeout_sec,
          max_retries: req.body?.max_retries,
          drop_after_verify: req.body?.drop_after_verify,
          skip_sha256: req.body?.skip_sha256,
          expected_sha256: req.body?.expected_sha256,
          worker_id: req.body?.worker_id,
          actor: req.user!.email,
        },
        res,
        201
      );
    }
  );

  app.post(
    '/api/restoreproof/control/runs/:id/cancel',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_cancel_run',
        {
          run_id: String(req.params.id || '').trim().slice(0, 64),
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.post(
    '/api/restoreproof/control/runs/:id/retry',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_retry_run',
        {
          run_id: String(req.params.id || '').trim().slice(0, 64),
          force: Boolean(req.body?.force),
          actor: req.user!.email,
        },
        res,
        201
      );
    }
  );

  app.get(
    '/api/restoreproof/control/compare',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_compare_runs',
        {
          run_a: String(req.query.a || '').trim().slice(0, 64),
          run_b: String(req.query.b || '').trim().slice(0, 64),
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.post(
    '/api/restoreproof/control/workers',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_save_worker',
        {
          id: req.body?.id,
          name: req.body?.name,
          endpoint: req.body?.endpoint,
          isolation_modes: req.body?.isolation_modes,
          max_concurrent: req.body?.max_concurrent,
          status: req.body?.status,
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.put(
    '/api/restoreproof/control/policies',
    requireAuth,
    requireAdmin,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_update_policies',
        {
          ...((req.body as Record<string, unknown>) || {}),
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  app.post(
    '/api/restoreproof/control/assistant/command',
    requireAuth,
    async (req: AuthedRequest, res: Response) => {
      await callRestoreProofBridge(
        'rp_control_assistant_command',
        {
          message: req.body?.message,
          confirm_execution: Boolean(req.body?.confirm_execution),
          context_run_id: req.body?.context_run_id,
          context_backup_id: req.body?.context_backup_id,
          actor: req.user!.email,
        },
        res,
        200
      );
    }
  );

  const isProductionEnv =
    process.env.NODE_ENV === 'production' ||
    (Boolean(process.env.K_SERVICE) && process.env.NODE_ENV !== 'development');
  const shouldAttachVite = options.attachVite ?? !isProductionEnv;
  if (shouldAttachVite) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else if (isProductionEnv) {
    const distDir = path.resolve(__dirname, 'dist');
    app.use(
      express.static(distDir, {
        maxAge: '7d',
        setHeaders: (res, filePath) => {
          if (filePath.endsWith(`${path.sep}index.html`)) {
            res.setHeader('Cache-Control', 'no-cache');
          } else if (filePath.includes(`${path.sep}assets${path.sep}`)) {
            res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
          }
        },
      })
    );
    app.get('*', (_req, res) => {
      const indexFile = path.resolve(distDir, 'index.html');
      if (fs.existsSync(indexFile)) {
        res.sendFile(indexFile);
      } else {
        res.status(404).send('Build output missing. Run npm run build.');
      }
    });
  }

  return app;
}

async function startServer() {
  const app = await createApp();
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`ZYRQUEN server listening on http://0.0.0.0:${PORT}`);
  });
}

const isDirectEntry =
  Boolean(process.argv[1]) &&
  path.resolve(process.argv[1]) === __filename &&
  process.env.ZYRQUEN_NO_AUTOSTART !== '1';

if (isDirectEntry) {
  startServer().catch((err) => {
    console.error('Failed to start ZYRQUEN server:', err);
    process.exit(1);
  });
}
