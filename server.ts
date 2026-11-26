import crypto from 'crypto';
import { spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import dotenv from 'dotenv';
import express from 'express';
import type { NextFunction, Request, Response } from 'express';
import fs from 'fs';
import path from 'path';
import readline from 'readline';
import { fileURLToPath } from 'url';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PORT = 3000;
const SESSION_SECRET =
  process.env.ZYRQUEN_SESSION_SECRET || crypto.randomBytes(32).toString('hex');
const TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
const revokedTokenIds = new Set<string>();

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: 'admin' | 'user';
  created_at: string;
}

interface AuthedRequest extends Request {
  user?: AuthUser;
  tokenJti?: string;
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

function runPythonScript<T = Record<string, unknown>>(
  scriptName: 'zyrquen_core.py' | 'db_bridge.py',
  input: Record<string, unknown>
): Promise<T> {
  return getPythonWorker().call<T>(scriptName, input);
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
        metrics: Record<string, unknown>;
        counts: Record<string, number>;
      }>('zyrquen_core.py', { cmd: 'health', payload: {} });
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
          status: pyHealth.ok ? 'ready' : 'degraded',
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
        native_core: { status: 'offline' },
      });
    }
  });

  app.get('/api/health', async (_req, res) => {
    try {
      const pyHealth = await runPythonScript<{
        ok: boolean;
        metrics: Record<string, unknown>;
        counts: Record<string, number>;
      }>('zyrquen_core.py', { cmd: 'health', payload: {} });
      res.json({
        ok: true,
        nativeCore: pyHealth.ok ? 'ready' : 'degraded',
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

    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: created.user.id,
        actor_email: created.user.email,
        action: 'AUTH_REGISTER',
        target: created.user.id,
        outcome: 'SUCCESS',
      },
    });

    const token = signToken(created.user);
    setSessionCookie(req, res, token);
    res.status(201).json({ token, user: created.user });
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
      dataset?: { id: string; name: string; total_records: number; status?: string };
      kg_proposal?: { id: string; status: string; triple_count: number } | null;
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
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'DATASET_INGEST',
        target: String(result.dataset?.id || name),
        outcome: `${String(result.dataset?.status || 'READY')} (${result.dataset?.total_records ?? 0} records)`,
      },
    });
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
      const report = await new Promise<Record<string, unknown>>((resolve, reject) => {
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

  app.get('/api/admin/audit-logs', requireAuth, requireAdmin, async (req: AuthedRequest, res: Response) => {
    const requestedLimit = Number(req.query.limit ?? 500);
    const limit = Number.isFinite(requestedLimit)
      ? Math.max(1, Math.min(Math.trunc(requestedLimit), 500))
      : 500;
    const logs = await runPythonScript('db_bridge.py', {
      action: 'admin_audit_logs',
      payload: { limit },
    });
    res.json(logs);
  });

  app.post('/api/admin/audit-logs/export', requireAuth, requireAdmin, async (req: AuthedRequest, res: Response) => {
    const format = req.body?.format === 'json' ? 'JSON' : 'CSV';
    const exportedCount = Number(req.body?.exported_count);
    if (!Number.isInteger(exportedCount) || exportedCount < 0 || exportedCount > 500) {
      res.status(400).json({ error: 'Invalid exported_count' });
      return;
    }
    await runPythonScript('db_bridge.py', {
      action: 'log_audit',
      payload: {
        actor_id: req.user!.id,
        actor_email: req.user!.email,
        action: 'PII_AUDIT_EXPORT',
        target: 'PII_AUDIT_LOGS',
        outcome: 'SUCCESS',
        details: { format, exported_count: exportedCount, includes_raw_pii: false },
      },
    });
    res.status(201).json({ ok: true });
  });

  app.get('/api/admin/overview', requireAuth, requireAdmin, async (_req: AuthedRequest, res: Response) => {
    const data = await runPythonScript('db_bridge.py', {
      action: 'admin_overview',
      payload: {},
    });
    res.json(data);
  });

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

  const shouldAttachVite = options.attachVite ?? process.env.NODE_ENV !== 'production';
  if (shouldAttachVite) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else if (process.env.NODE_ENV === 'production') {
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
