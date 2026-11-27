// @vitest-environment node
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { NativeBenchmarkReport } from '../types';

describe('Full-Stack Real E2E: Express + SQLite + Python Native Core (Zero Fetch Mocks)', () => {
  let server: http.Server;
  let baseUrl = '';
  let tmpDataDir = '';
  let prevDataDir: string | undefined;
  let prevNoAutostart: string | undefined;

  beforeAll(async () => {
    tmpDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zyrquen-e2e-http-'));
    prevDataDir = process.env.ZYRQUEN_DATA_DIR;
    prevNoAutostart = process.env.ZYRQUEN_NO_AUTOSTART;
    process.env.ZYRQUEN_DATA_DIR = tmpDataDir;
    process.env.ZYRQUEN_NO_AUTOSTART = '1';

    const { createApp } = await import('../../server');
    const app = await createApp({ attachVite: false });
    await new Promise<void>((resolve) => {
      server = app.listen(0, '127.0.0.1', () => resolve());
    });
    const addr = server.address();
    if (!addr || typeof addr === 'string') {
      throw new Error('Failed to bind ephemeral E2E server port');
    }
    baseUrl = `http://127.0.0.1:${addr.port}`;
  }, 30_000);

  afterAll(async () => {
    await new Promise<void>((resolve) => {
      if (!server) return resolve();
      server.close(() => resolve());
    });
    if (prevDataDir === undefined) {
      delete process.env.ZYRQUEN_DATA_DIR;
    } else {
      process.env.ZYRQUEN_DATA_DIR = prevDataDir;
    }
    if (prevNoAutostart === undefined) {
      delete process.env.ZYRQUEN_NO_AUTOSTART;
    } else {
      process.env.ZYRQUEN_NO_AUTOSTART = prevNoAutostart;
    }
    fs.rmSync(tmpDataDir, { recursive: true, force: true });
  });

  it('Executes real Auth -> Inference -> KG Memory -> Autonomous DAG Mission -> 7-State Capability Benchmark over HTTP', async () => {
    // 1. Health & Uninitialized Auth Status
    const healthRes = await fetch(`${baseUrl}/api/health`);
    expect(healthRes.status).toBe(200);
    const healthJson = (await healthRes.json()) as { ok: boolean; nativeCore: string };
    expect(healthJson.ok).toBe(true);
    expect(healthJson.nativeCore).toBe('ready');

    // 2. Claim initial admin account in fresh SQLite DB
    const setupRes = await fetch(`${baseUrl}/api/auth/claim-admin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'e2e-admin@zyrquen.local',
        displayName: 'E2E Admin',
        password: 'StrongPassword123!',
      }),
    });
    expect(setupRes.status).toBe(201);
    const setupJson = (await setupRes.json()) as { token: string; user: { role: string } };
    expect(setupJson.token).toBeTruthy();
    expect(setupJson.user.role).toBe('admin');

    const authHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${setupJson.token}`,
    };

    const adminOverviewInit = await fetch(`${baseUrl}/api/admin/overview`, {
      headers: authHeaders,
    });
    expect(adminOverviewInit.status).toBe(200);
    const adminOverviewJson = (await adminOverviewInit.json()) as {
      training_readiness?: { gate_status: string; datasets_total: number; clean_datasets: number };
    };
    expect(adminOverviewJson.training_readiness?.gate_status).toBe('BLOCKED');
    expect(adminOverviewJson.training_readiness?.datasets_total).toBe(0);
    expect(adminOverviewJson.training_readiness?.clean_datasets).toBe(0);

    // 3. Create conversation & test real Python AST math + KG learn/recall + OOD abstention
    const convRes = await fetch(`${baseUrl}/api/conversations`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ title: 'E2E Verification', mode: 'auto' }),
    });
    expect(convRes.status).toBe(201);
    const convJson = (await convRes.json()) as { conversation: { id: string } };
    const cid = convJson.conversation.id;

    const mathRes = await fetch(`${baseUrl}/api/conversations/${cid}/messages`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ content: 'คำนวณ (10 + 15) * 4', mode: 'auto', modelVariant: 'zyrquen-omega-v1' }),
    });
    expect(mathRes.status).toBe(201);
    const mathJson = (await mathRes.json()) as {
      assistant_message: { status: string; content: string; trace_json: string };
    };
    expect(mathJson.assistant_message.status).toBe('VERIFIED');
    const mathTrace = JSON.parse(mathJson.assistant_message.trace_json) as {
      math?: { result?: number };
      external_models_used: boolean;
      task_timings?: Array<{ task: string; duration_ms: number; matched: boolean; status: string }>;
      bottleneck_task?: { task: string; duration_ms: number; share_pct: number } | null;
    };
    expect(mathTrace.math?.result).toBe(100);
    expect(mathTrace.external_models_used).toBe(false);
    expect(Array.isArray(mathTrace.task_timings)).toBe(true);
    expect(mathTrace.task_timings!.length).toBeGreaterThan(0);
    expect(mathTrace.task_timings!.every((t) => typeof t.duration_ms === 'number' && t.duration_ms >= 0)).toBe(true);
    expect(mathTrace.bottleneck_task).toBeTruthy();
    expect(typeof mathTrace.bottleneck_task?.duration_ms).toBe('number');

    // Unseen OOD question must abstain honestly (NOT_LEARNED)
    const oodRes = await fetch(`${baseUrl}/api/conversations/${cid}/messages`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ content: 'ทฤษฎีสัมพัทธภาพทั่วไปคืออะไร', mode: 'auto' }),
    });
    expect(oodRes.status).toBe(201);
    const oodJson = (await oodRes.json()) as {
      assistant_message: { status: string; trace_json: string };
    };
    expect(oodJson.assistant_message.status).toBe('NOT_LEARNED');
    const oodTrace = JSON.parse(oodJson.assistant_message.trace_json) as {
      task_timings?: Array<{ task: string; duration_ms: number }>;
      bottleneck_task?: { task: string; duration_ms: number } | null;
    };
    expect(oodTrace.task_timings?.some((t) => t.task === 'unlearned_boundary')).toBe(true);
    expect(oodTrace.bottleneck_task).toBeTruthy();

    // 3b. Verify Project Dashboard enrichment on /api/conversations and /api/home
    const conv2Res = await fetch(`${baseUrl}/api/conversations`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ title: 'Completed Math Project', mode: 'math' }),
    });
    expect(conv2Res.status).toBe(201);
    const { conversation: conv2 } = (await conv2Res.json()) as { conversation: { id: string } };
    const conv2MsgRes = await fetch(`${baseUrl}/api/conversations/${conv2.id}/messages`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ content: 'คำนวณ 8 * 8', mode: 'math' }),
    });
    expect(conv2MsgRes.status).toBe(201);

    const listProjRes = await fetch(`${baseUrl}/api/conversations`, { headers: authHeaders });
    expect(listProjRes.status).toBe(200);
    const listProjJson = (await listProjRes.json()) as {
      conversations: Array<{
        id: string;
        project_status?: string;
        completion_pct?: number;
        completed_units?: number;
        total_units?: number;
        pending_actions?: Array<{ category: string }>;
      }>;
    };
    const cidSummary = listProjJson.conversations.find((c) => c.id === cid);
    expect(cidSummary?.project_status).toBe('NEEDS_INPUT');
    expect(cidSummary?.completion_pct).toBe(50);
    expect(cidSummary?.completed_units).toBe(1);
    expect(cidSummary?.total_units).toBe(2);
    expect(cidSummary?.pending_actions?.some((a) => a.category === 'clarification')).toBe(true);

    const cid2Summary = listProjJson.conversations.find((c) => c.id === conv2.id);
    expect(cid2Summary?.project_status).toBe('COMPLETED');
    expect(cid2Summary?.completion_pct).toBe(100);
    expect(cid2Summary?.pending_actions).toEqual([]);

    const homeProjRes = await fetch(`${baseUrl}/api/home`, { headers: authHeaders });
    expect(homeProjRes.status).toBe(200);
    const homeProjJson = (await homeProjRes.json()) as {
      recent_conversations: Array<{ id: string; project_status?: string; completion_pct?: number }>;
    };
    expect(homeProjJson.recent_conversations.find((c) => c.id === conv2.id)?.project_status).toBe('COMPLETED');

    // Verify persistent Reasoning Trace stored in SQLite & exposed via workflows endpoints
    const wfRes = await fetch(`${baseUrl}/api/workflows`, { headers: authHeaders });
    expect(wfRes.status).toBe(200);
    const wfJson = (await wfRes.json()) as {
      ok: boolean;
      reasoning_traces: Array<{
        prompt: string;
        status: string;
        engine_path_json: string;
        external_models_used: number;
      }>;
    };
    expect(wfJson.ok).toBe(true);
    expect(wfJson.reasoning_traces.length).toBeGreaterThanOrEqual(2);
    const persistedMath = wfJson.reasoning_traces.find((t) => t.prompt.includes('(10 + 15) * 4'));
    expect(persistedMath).toBeDefined();
    expect(persistedMath?.status).toBe('VERIFIED');
    expect(persistedMath?.external_models_used).toBe(0);
    expect(JSON.parse(persistedMath!.engine_path_json)).toContain('math_ast');

    const traceFilterRes = await fetch(
      `${baseUrl}/api/workflows/reasoning-traces?status=NOT_LEARNED`,
      { headers: authHeaders }
    );
    expect(traceFilterRes.status).toBe(200);
    const traceFilterJson = (await traceFilterRes.json()) as {
      ok: boolean;
      reasoning_traces: Array<{ prompt: string; status: string }>;
    };
    expect(traceFilterJson.ok).toBe(true);
    expect(traceFilterJson.reasoning_traces.some((t) => t.status === 'NOT_LEARNED')).toBe(true);
    expect(traceFilterJson.reasoning_traces.every((t) => t.status === 'NOT_LEARNED')).toBe(true);

    // 4. Autonomous Mission DAG execution with postcondition check
    const missionRes = await fetch(`${baseUrl}/api/autonomous/missions`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({
        goal: 'คำนวณ 7 * 9',
        enableResearch: false,
        enableKnowledgeDev: false,
        enableExecution: true,
      }),
    });
    expect(missionRes.status).toBe(201);
    const missionJson = (await missionRes.json()) as {
      ok: boolean;
      mission: { status: string; external_models_used: number };
      nodes: Array<{ execution_status: string }>;
    };
    expect(missionJson.ok).toBe(true);
    expect(missionJson.mission.status).toBe('COMPLETED');
    expect(missionJson.mission.external_models_used).toBe(0);
    expect(missionJson.nodes.length).toBeGreaterThanOrEqual(3);
    expect(missionJson.nodes.every((n) => n.execution_status === 'COMPLETED')).toBe(true);

    // 4b. Verify admin/overview returns persisted reasoning_traces with task_timings for Recharts stability visualization
    const adminOverviewAfter = await fetch(`${baseUrl}/api/admin/overview`, {
      headers: authHeaders,
    });
    expect(adminOverviewAfter.status).toBe(200);
    const adminAfterJson = (await adminOverviewAfter.json()) as {
      reasoning_traces?: Array<{ trace_json: string; latency_ms: number }>;
    };
    expect(Array.isArray(adminAfterJson.reasoning_traces)).toBe(true);
    expect(adminAfterJson.reasoning_traces!.length).toBeGreaterThanOrEqual(2);
    const firstTraceParsed = JSON.parse(adminAfterJson.reasoning_traces![0].trace_json) as {
      task_timings?: unknown[];
    };
    expect(Array.isArray(firstTraceParsed.task_timings)).toBe(true);

    // 5. Real Developer Benchmark + 7-State Capability Ledger + Baseline Persistence
    const benchRes = await fetch(`${baseUrl}/api/developer/benchmark`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ modelVersion: 'zyrquen-omega-v1' }),
    });
    expect(benchRes.status).toBe(200);
    const benchJson = (await benchRes.json()) as { ok: boolean; report: NativeBenchmarkReport };
    expect(benchJson.ok).toBe(true);
    expect(benchJson.report.environment.external_models_used).toBe(false);
    expect(benchJson.report.summary.false_positives).toBe(0);
    expect(benchJson.report.capability_ledger).toBeDefined();
    const domains = benchJson.report.capability_ledger!.domains;
    expect(Object.keys(domains)).toHaveLength(6);
    expect(domains.native_core.status).toBe('VERIFIED');
    expect(domains.planning.status).toBe('VERIFIED');
    expect(domains.memory.status).toBe('VERIFIED');
    expect(domains.learning.status).toBe('VERIFIED');
    expect(domains.autonomous_execution.status).toBe('VERIFIED');
    expect(domains.research.status).toBe('PARTIAL');
  }, 90_000);

  it('Supports member registration (สมัครสมาชิก) with password confirmation, duplicate 409 check, and user RBAC over HTTP', async () => {
    // 1. Mismatched confirmPassword rejected with 400
    const mismatchRes = await fetch(`${baseUrl}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'member-e2e@zyrquen.local',
        displayName: 'สมาชิก E2E',
        password: 'MemberPassword123!',
        confirmPassword: 'DifferentPassword123!',
      }),
    });
    expect(mismatchRes.status).toBe(400);

    // 2. Valid member registration succeeds with 201 and role='user'
    const regRes = await fetch(`${baseUrl}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'member-e2e@zyrquen.local',
        displayName: 'สมาชิก E2E',
        password: 'MemberPassword123!',
        confirmPassword: 'MemberPassword123!',
      }),
    });
    expect(regRes.status).toBe(201);
    const setCookie = regRes.headers.get('set-cookie') || '';
    expect(setCookie).toContain('zyrquen_session=');
    expect(setCookie).toContain('HttpOnly');

    const regJson = (await regRes.json()) as {
      token: string;
      user: { id: string; email: string; display_name: string; role: string };
    };
    expect(regJson.token).toBeTruthy();
    expect(regJson.user.role).toBe('user');
    expect(regJson.user.email).toBe('member-e2e@zyrquen.local');

    // 3. Duplicate registration returns 409 Conflict
    const dupRes = await fetch(`${baseUrl}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'member-e2e@zyrquen.local',
        displayName: 'สมาชิกซ้ำ',
        password: 'MemberPassword123!',
        confirmPassword: 'MemberPassword123!',
      }),
    });
    expect(dupRes.status).toBe(409);

    // 4. Member can access authenticated routes, but cannot access admin routes (403)
    const meRes = await fetch(`${baseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${regJson.token}` },
    });
    expect(meRes.status).toBe(200);
    const meJson = (await meRes.json()) as { user: { role: string } };
    expect(meJson.user.role).toBe('user');

    const adminOverviewRes = await fetch(`${baseUrl}/api/admin/overview`, {
      headers: { Authorization: `Bearer ${regJson.token}` },
    });
    expect(adminOverviewRes.status).toBe(403);
  }, 30_000);

  it('Exposes platform-independent /api/v1 manifest, failure-driven curriculum synthesis, and continual learning round', async () => {
    // 1. Platform-independent v1 manifest reachable unauthenticated (no secrets exposed)
    const manifestRes = await fetch(`${baseUrl}/api/v1/platform/manifest`);
    expect(manifestRes.status).toBe(200);
    expect(manifestRes.headers.get('x-zyrquen-api-version')).toBe('v1');
    const manifest = (await manifestRes.json()) as {
      platform: string;
      api_version: string;
      supported_clients: string[];
      browser_dependencies_in_core: boolean;
      external_models_used: boolean;
      native_core: { status: string };
    };
    expect(manifest.platform).toBe('ZYRQUEN');
    expect(manifest.api_version).toBe('v1');
    expect(manifest.supported_clients).toContain('mobile-android');
    expect(manifest.supported_clients).toContain('desktop');
    expect(manifest.browser_dependencies_in_core).toBe(false);
    expect(manifest.external_models_used).toBe(false);
    expect(manifest.native_core.status).toBe('ready');

    // 2. Authenticate via /api/v1/auth/login (seeded admin from first test)
    const loginRes = await fetch(`${baseUrl}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'e2e-admin@zyrquen.local',
        password: 'StrongPassword123!',
      }),
    });
    expect(loginRes.status).toBe(200);
    const loginJson = (await loginRes.json()) as { token: string };
    const v1Headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${loginJson.token}`,
    };

    // 3. Failure-Driven Curriculum Synthesis via /api/v1/developer/curriculum/synthesize
    const currRes = await fetch(`${baseUrl}/api/v1/developer/curriculum/synthesize`, {
      method: 'POST',
      headers: v1Headers,
      body: JSON.stringify({ limit: 30 }),
    });
    expect(currRes.status).toBe(201);
    const currJson = (await currRes.json()) as {
      ok: boolean;
      leakage_checked: boolean;
      manifest_sha256: string;
    };
    expect(currJson.ok).toBe(true);
    expect(currJson.leakage_checked).toBe(true);
    expect(currJson.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);

    // 4. Continual Learning Round with Replay + L2 Anchor Consolidation via /api/v1/developer/continual-learning/run
    const clRes = await fetch(`${baseUrl}/api/v1/developer/continual-learning/run`, {
      method: 'POST',
      headers: v1Headers,
      body: JSON.stringify({
        newTrainLines: [
          'zyrquen platform independence แยกแกนปัญญาจาก frontend',
          'continual learning ใช้ experience replay และ l2 anchor',
        ],
        anchorLines: [
          'zyrquen ตรวจสอบสมการด้วย ast เสมอ',
          'zyrquen บันทึกกราฟความรู้ลง sqlite wal',
        ],
        replayRatio: 0.5,
        anchorL2Lambda: 0.04,
        epochs: 3,
        seed: 11,
      }),
    });
    expect(clRes.status).toBe(201);
    const clJson = (await clRes.json()) as {
      ok: boolean;
      continual_metrics: {
        mode: string;
        retention_rate: number;
        forgetting_loss_delta: number;
        replay_samples: number;
      };
    };
    expect(clJson.ok).toBe(true);
    expect(clJson.continual_metrics.mode).toBe('continual_replay_consolidation');
    expect(clJson.continual_metrics.replay_samples).toBeGreaterThanOrEqual(1);
    expect(clJson.continual_metrics.retention_rate).toBeGreaterThanOrEqual(0);
  }, 45_000);
});

describe('Isolated 6-Step Non-Skippable Native Training Pipeline Gate E2E', () => {
  let gateServer: http.Server;
  let gateBaseUrl = '';
  let gateTmpDir = '';
  let prevDataDir: string | undefined;
  let prevNoAutostart: string | undefined;

  beforeAll(async () => {
    gateTmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zyrquen-e2e-6step-'));
    prevDataDir = process.env.ZYRQUEN_DATA_DIR;
    prevNoAutostart = process.env.ZYRQUEN_NO_AUTOSTART;
    process.env.ZYRQUEN_DATA_DIR = gateTmpDir;
    process.env.ZYRQUEN_NO_AUTOSTART = '1';

    const { createApp } = await import('../../server');
    const app = await createApp({ attachVite: false });
    await new Promise<void>((resolve) => {
      gateServer = app.listen(0, '127.0.0.1', () => resolve());
    });
    const addr = gateServer.address();
    if (!addr || typeof addr === 'string') {
      throw new Error('Failed to bind ephemeral 6-step E2E server port');
    }
    gateBaseUrl = `http://127.0.0.1:${addr.port}`;
  }, 30_000);

  afterAll(async () => {
    await new Promise<void>((resolve) => {
      if (!gateServer) return resolve();
      gateServer.close(() => resolve());
    });
    if (prevDataDir === undefined) {
      delete process.env.ZYRQUEN_DATA_DIR;
    } else {
      process.env.ZYRQUEN_DATA_DIR = prevDataDir;
    }
    if (prevNoAutostart === undefined) {
      delete process.env.ZYRQUEN_NO_AUTOSTART;
    } else {
      process.env.ZYRQUEN_NO_AUTOSTART = prevNoAutostart;
    }
    fs.rmSync(gateTmpDir, { recursive: true, force: true });
  });

  it('Enforces strict 6-step non-skippable native training order (Data+Provenance -> Baseline -> Approval -> Train -> Checkpoint Eval)', async () => {
    const setupRes = await fetch(`${gateBaseUrl}/api/auth/claim-admin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'gate-admin@zyrquen.local',
        displayName: 'Gate Admin',
        password: 'StrongPassword123!',
      }),
    });
    expect(setupRes.status).toBe(201);
    const setupJson = (await setupRes.json()) as { token: string };
    const authHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${setupJson.token}`,
    };

    // Initial empty DB must report BLOCKED
    const initOverview = await fetch(`${gateBaseUrl}/api/admin/overview`, { headers: authHeaders });
    expect(initOverview.status).toBe(200);
    const initJson = (await initOverview.json()) as {
      training_readiness?: { gate_status: string; datasets_total: number; baseline_evaluations?: number };
    };
    expect(initJson.training_readiness?.gate_status).toBe('BLOCKED');
    expect(initJson.training_readiness?.datasets_total).toBe(0);
    expect(initJson.training_readiness?.baseline_evaluations).toBe(0);

    // Step 1/2: Synthetic/external LLM provenance must be rejected
    const fakeProvRes = await fetch(`${gateBaseUrl}/api/developer/datasets`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({
        name: 'synthetic-rejected',
        provenance: 'synthetic_llm_gpt',
        content: [
          'alpha fact line one verified',
          'beta fact line two verified',
          'gamma fact line three verified',
          'delta fact line four verified',
          'epsilon fact line five verified',
        ].join('\n'),
      }),
    });
    expect(fakeProvRes.status).toBe(400);

    // Step 1/2: Real dataset ingest succeeds with clean split & SHA-256 manifest
    const realDsRes = await fetch(`${gateBaseUrl}/api/developer/datasets`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({
        name: 'verified-field-corpus',
        provenance: 'human_verified_field_notes',
        content: [
          'native symbolic algebra computes deterministic roots cleanly',
          'knowledge graph stores verified provenance triples in sqlite',
          'planning workflows verify prerequisites before model training',
          'evaluation suites measure generalization on unseen entities',
          'checkpoint governance protects historical baselines from overwrite',
          'resource telemetry tracks real ram cpu and storage margins',
        ].join('\n'),
      }),
    });
    expect(realDsRes.status).toBe(201);
    const realDsJson = (await realDsRes.json()) as {
      ok: boolean;
      dataset: { id: string; leakage_detected: number; total_records: number };
    };
    expect(realDsJson.ok).toBe(true);
    expect(realDsJson.dataset.leakage_detected).toBe(0);
    expect(realDsJson.dataset.total_records).toBeGreaterThanOrEqual(5);

    // Before Step 3 (Baseline Evaluation): readiness must be BLOCKED_NO_BASELINE
    const preBaselineOverview = await fetch(`${gateBaseUrl}/api/admin/overview`, { headers: authHeaders });
    expect(preBaselineOverview.status).toBe(200);
    const preBaselineJson = (await preBaselineOverview.json()) as {
      training_readiness?: { gate_status: string; baseline_evaluations?: number };
    };
    expect(preBaselineJson.training_readiness?.gate_status).toBe('BLOCKED_NO_BASELINE');
    expect(preBaselineJson.training_readiness?.baseline_evaluations).toBe(0);

    // Skipping Step 3 via workflow or experiment must fail closed (400)
    const skipBaselineWf = await fetch(`${gateBaseUrl}/api/workflows/native_training/run`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ datasetId: realDsJson.dataset.id }),
    });
    expect(skipBaselineWf.status).toBe(400);

    const skipBaselineExp = await fetch(`${gateBaseUrl}/api/developer/experiments`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ datasetId: realDsJson.dataset.id, epochs: 2 }),
    });
    expect(skipBaselineExp.status).toBe(400);

    // Step 3: Run genuine baseline evaluation
    const baselineEvalRes = await fetch(`${gateBaseUrl}/api/developer/evaluate`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ suiteName: 'Pre-Training Baseline Suite' }),
    });
    expect(baselineEvalRes.status).toBe(201);

    // Before Step 4 (Approval Gate): direct experiment without approved training run must STILL be blocked (400)
    const skipApprovalExp = await fetch(`${gateBaseUrl}/api/developer/experiments`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ datasetId: realDsJson.dataset.id, epochs: 2 }),
    });
    expect(skipApprovalExp.status).toBe(400);

    // Step 4: Submit native_training workflow to Approval Gate -> PENDING_APPROVAL
    const gateSubmitRes = await fetch(`${gateBaseUrl}/api/workflows/native_training/run`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ datasetId: realDsJson.dataset.id }),
    });
    expect(gateSubmitRes.status).toBe(201);
    const gateSubmitJson = (await gateSubmitRes.json()) as {
      ok: boolean;
      run: { id: string; status: string };
    };
    expect(gateSubmitJson.ok).toBe(true);
    expect(gateSubmitJson.run.status).toBe('PENDING_APPROVAL');

    // Step 4 -> 5 -> 6: Admin approval executes training and post-training checkpoint evaluation
    const approveRes = await fetch(`${gateBaseUrl}/api/workflows/runs/${gateSubmitJson.run.id}/decide`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ decision: 'approve', datasetId: realDsJson.dataset.id }),
    });
    expect(approveRes.status).toBe(200);
    const approveJson = (await approveRes.json()) as {
      ok: boolean;
      run: { status: string; stages_json: string };
    };
    expect(approveJson.ok).toBe(true);
    expect(approveJson.run.status).toBe('COMPLETED');
    const stages = JSON.parse(approveJson.run.stages_json) as Array<{ stage: string; status: string }>;
    expect(stages.map((s) => s.stage)).toEqual([
      'provenance_leakage_gate',
      'baseline_verify',
      'approval_gate',
      'checkpoint_train',
      'checkpoint_eval_gate',
    ]);
    expect(stages.every((s) => s.status === 'PASS')).toBe(true);

    // Now approved experiment can run cleanly
    const expRes = await fetch(`${gateBaseUrl}/api/developer/experiments`, {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({ datasetId: realDsJson.dataset.id, epochs: 2, seed: 7 }),
    });
    expect(expRes.status).toBe(201);
  }, 60_000);

  it('Ingests CSV/JSONL real datasets with SHA-256 checksum verification and enforces Admin Approval Gate for Knowledge Graph commits', async () => {
    // Login as already-initialized admin
    const loginRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'gate-admin@zyrquen.local',
        password: 'StrongPassword123!',
      }),
    });
    expect(loginRes.status).toBe(200);
    const { token: adminToken } = (await loginRes.json()) as { token: string };
    const adminHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${adminToken}`,
    };

    // Register non-admin developer user to verify RBAC enforcement on KG Approval Gate
    const devRegRes = await fetch(`${gateBaseUrl}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'dev-kg@zyrquen.local',
        displayName: 'Dev Contributor',
        password: 'DevPassword123!',
      }),
    });
    expect(devRegRes.status).toBe(201);
    const { token: devToken } = (await devRegRes.json()) as { token: string };
    const devHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${devToken}`,
    };

    const csvPayload = [
      'subject,relation,object',
      'ZyrquenPipeline,enforces,ChecksumVerification',
      'ZyrquenPipeline,detects,TemplateLeakage',
      'ZyrquenPipeline,stages,KgApprovalGate',
      'DatasetBundle,writes,ImmutableManifest',
      'GovernanceGate,protects,KnowledgeGraph',
    ].join('\n');

    const ingRes = await fetch(`${gateBaseUrl}/api/developer/datasets`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({
        name: 'e2e-csv-kg-corpus',
        format: 'csv',
        provenance: 'e2e_verified_spec',
        sourceName: 'spec.csv',
        license: 'CC-BY-4.0',
        content: csvPayload,
      }),
    });
    expect(ingRes.status).toBe(201);
    const ingJson = (await ingRes.json()) as {
      ok: boolean;
      dataset: { id: string; source_format: string; manifest_hash: string };
      checksum: { content_sha256: string; manifest_sha256: string };
      kg_proposal: { id: string; status: string; triple_count: number };
    };
    expect(ingJson.ok).toBe(true);
    expect(ingJson.dataset.source_format).toBe('csv');
    expect(ingJson.checksum.content_sha256).toHaveLength(64);
    expect(ingJson.kg_proposal.status).toBe('PENDING_APPROVAL');
    expect(ingJson.kg_proposal.triple_count).toBe(5);

    // Real SHA-256 verification endpoint passes
    const verifyRes = await fetch(`${gateBaseUrl}/api/developer/datasets/${ingJson.dataset.id}/verify`, {
      headers: devHeaders,
    });
    expect(verifyRes.status).toBe(200);
    const verifyJson = (await verifyRes.json()) as { verified: boolean; disk_verified: boolean };
    expect(verifyJson.verified).toBe(true);
    expect(verifyJson.disk_verified).toBe(true);

    // Before Admin approval: none of the proposed KG triples exist in /api/knowledge
    const preKgRes = await fetch(`${gateBaseUrl}/api/knowledge`, { headers: devHeaders });
    const preKgJson = (await preKgRes.json()) as { triples: Array<{ subject: string }> };
    expect(preKgJson.triples.some((t) => t.subject === 'ZyrquenPipeline')).toBe(false);

    // Non-admin developer MUST receive 403 when trying to approve KG Gate
    const forbiddenApprove = await fetch(`${gateBaseUrl}/api/admin/kg-proposals/${ingJson.kg_proposal.id}/decide`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({ decision: 'approve' }),
    });
    expect(forbiddenApprove.status).toBe(403);

    // Admin approves KG Gate proposal -> triples committed with full provenance
    const adminApprove = await fetch(`${gateBaseUrl}/api/admin/kg-proposals/${ingJson.kg_proposal.id}/decide`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({ decision: 'approve' }),
    });
    expect(adminApprove.status).toBe(200);
    const approveBody = (await adminApprove.json()) as { ok: boolean; committed_triples: number };
    expect(approveBody.ok).toBe(true);
    expect(approveBody.committed_triples).toBe(5);

    const postKgRes = await fetch(`${gateBaseUrl}/api/knowledge`, { headers: devHeaders });
    const postKgJson = (await postKgRes.json()) as { triples: Array<{ subject: string; source: string }> };
    const committed = postKgJson.triples.filter((t) => t.subject === 'ZyrquenPipeline');
    expect(committed.length).toBe(3);
    expect(committed[0].source).toContain('dataset:e2e-csv-kg-corpus|e2e_verified_spec');
  }, 60_000);

  it('Handles natural Thai/English greetings on fresh empty KG and structured CSV attachment inspection over HTTP', async () => {
    // Login as seeded admin (gate-admin) or claim? Re-use existing DB in this test suite or login cleanly:
    const statusRes = await fetch(`${gateBaseUrl}/api/auth/status`);
    const statusJson = (await statusRes.json()) as { initialized: boolean };
    let token = '';
    if (!statusJson.initialized) {
      const claimRes = await fetch(`${gateBaseUrl}/api/auth/claim-admin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: 'gate-admin@zyrquen.local',
          displayName: 'Gate Admin',
          password: 'StrongPassword123!',
        }),
      });
      token = ((await claimRes.json()) as { token: string }).token;
    } else {
      const loginRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: 'gate-admin@zyrquen.local',
          password: 'StrongPassword123!',
        }),
      });
      token = ((await loginRes.json()) as { token: string }).token;
    }
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };

    const convRes = await fetch(`${gateBaseUrl}/api/conversations`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ title: 'Natural Conversation E2E', mode: 'auto' }),
    });
    expect(convRes.status).toBe(201);
    const { conversation } = (await convRes.json()) as { conversation: { id: string } };

    // 1. Exact mandatory Thai greeting response over HTTP
    const hiRes = await fetch(`${gateBaseUrl}/api/conversations/${conversation.id}/messages`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ content: 'สวัสดี', mode: 'auto' }),
    });
    expect(hiRes.status).toBe(201);
    const hiJson = (await hiRes.json()) as {
      assistant_message: { status: string; content: string; trace_json: string };
    };
    expect(hiJson.assistant_message.status).toBe('VERIFIED');
    expect(hiJson.assistant_message.content).toBe(
      'สวัสดีครับ ยินดีต้อนรับ มีอะไรให้ช่วยวันนี้ครับ'
    );
    expect(hiJson.assistant_message.content).not.toContain('ไม่ได้เรียนรู้');
    expect(hiJson.assistant_message.content).not.toContain('Not Learned');
    const hiTrace = JSON.parse(hiJson.assistant_message.trace_json) as {
      external_models_used: boolean;
      cognitive_state?: string;
    };
    expect(hiTrace.external_models_used).toBe(false);
    expect(hiTrace.cognitive_state).toBe('UNDERSTOOD');

    // 2. Structured CSV attachment inspection over HTTP
    const csvAttachRes = await fetch(`${gateBaseUrl}/api/conversations/${conversation.id}/messages`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        content: 'วิเคราะห์ข้อมูลไฟล์นี้',
        mode: 'auto',
        attachment: 'name,score\nalice,90\nbob,80\nbob,80\n',
      }),
    });
    expect(csvAttachRes.status).toBe(201);
    const csvAttachJson = (await csvAttachRes.json()) as {
      assistant_message: { status: string; content: string; trace_json: string };
    };
    expect(csvAttachJson.assistant_message.status).toBe('VERIFIED');
    expect(csvAttachJson.assistant_message.content).toContain('วิเคราะห์ข้อมูลโครงสร้าง');
    const csvTrace = JSON.parse(csvAttachJson.assistant_message.trace_json) as {
      dataset_analysis?: { duplicate_rows?: number };
    };
    expect(csvTrace.dataset_analysis?.duplicate_rows).toBe(1);

    // 3. Real Autonomous Execution from Chat composer goal -> VERIFIED deliverable artifact
    const docGoalRes = await fetch(`${gateBaseUrl}/api/conversations/${conversation.id}/messages`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        content: 'สร้างเอกสารสรุปสถาปัตยกรรมและรายการตรวจสอบความพร้อมระบบ',
        mode: 'auto',
      }),
    });
    expect(docGoalRes.status).toBe(201);
    const docGoalJson = (await docGoalRes.json()) as {
      assistant_message: { status: string; content: string; trace_json: string };
    };
    expect(docGoalJson.assistant_message.status).toBe('VERIFIED');
    const docTrace = JSON.parse(docGoalJson.assistant_message.trace_json) as {
      engine_path?: string[];
      external_models_used: boolean;
      deliverable?: { kind: string; title: string; filename: string; sha256: string; verified: boolean };
    };
    expect(docTrace.external_models_used).toBe(false);
    expect(docTrace.engine_path).toContain('tool_center');
    expect(docTrace.deliverable?.verified).toBe(true);
    expect(docTrace.deliverable?.filename).toMatch(/\.md$/);
    expect(docTrace.deliverable?.sha256).toMatch(/^[a-f0-9]{64}$/);
  }, 45_000);

  it('Executes Native Tool Center (8 Toolkits), 10 Background Support Systems, P5 Gates, Self-Improvement & Software Engineering Benchmark over HTTP', async () => {
    // Login as gate-admin & dev-kg (already created in this isolated test suite)
    const adminLoginRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'gate-admin@zyrquen.local',
        password: 'StrongPassword123!',
      }),
    });
    expect(adminLoginRes.status).toBe(200);
    const { token: adminToken } = (await adminLoginRes.json()) as { token: string };
    const adminHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${adminToken}`,
    };

    const devLoginRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'dev-kg@zyrquen.local',
        password: 'DevPassword123!',
      }),
    });
    expect(devLoginRes.status).toBe(200);
    const { token: devToken } = (await devLoginRes.json()) as { token: string };
    const devHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${devToken}`,
    };

    // 1. GET /api/tool-center returns all 8 toolkits, dependency env, resource snapshot, external_models_used=false
    const overviewRes = await fetch(`${gateBaseUrl}/api/tool-center`, { headers: adminHeaders });
    expect(overviewRes.status).toBe(200);
    const overviewJson = (await overviewRes.json()) as {
      ok: boolean;
      toolkits: Array<{ id: string }>;
      dependency_environment: { ok: boolean; capabilities_checked: number };
      resource_snapshot: { effective_max_workers: number; system: { mem_available_mb: number } };
      external_models_used: boolean;
    };
    expect(overviewJson.ok).toBe(true);
    expect(overviewJson.external_models_used).toBe(false);
    expect(overviewJson.toolkits.map((t) => t.id).sort()).toEqual([
      'api_integration',
      'automation',
      'data',
      'development',
      'document',
      'research',
      'security',
      'testing',
    ]);
    expect(overviewJson.dependency_environment.capabilities_checked).toBeGreaterThan(15);
    expect(overviewJson.resource_snapshot.system.mem_available_mb).toBeGreaterThan(0);

    // 2. POST /api/tool-center/resolve reuses READY capabilities and blocks duplicate creation
    const resolveRes = await fetch(`${gateBaseUrl}/api/tool-center/resolve`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({ goal: 'วิเคราะห์ข้อมูล CSV และตรวจสอบ Python AST พร้อมยืนยันความปลอดภัย' }),
    });
    expect(resolveRes.status).toBe(200);
    const resolveJson = (await resolveRes.json()) as {
      ok: boolean;
      duplicate_creation_blocked: boolean;
      reuse_existing_count: number;
      selected_capabilities: Array<{ capability_id: string }>;
      task_memory_hints: { success_examples_count: number };
    };
    expect(resolveJson.ok).toBe(true);
    expect(resolveJson.duplicate_creation_blocked).toBe(true);
    expect(resolveJson.reuse_existing_count).toBeGreaterThanOrEqual(2);
    expect(resolveJson.task_memory_hints).toBeDefined();

    // 3. POST /api/tool-center/execute runs real capabilities & enforces RBAC + P5 Gate
    const xmlProfileRes = await fetch(`${gateBaseUrl}/api/tool-center/execute`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({
        capabilityId: 'data.profile_structured',
        input: {
          format: 'xml',
          content: '<records><row><item>alpha</item><score>10</score></row><row><item>beta</item><score>20</score></row></records>',
        },
      }),
    });
    expect(xmlProfileRes.status).toBe(201);
    const xmlJson = (await xmlProfileRes.json()) as {
      ok: boolean;
      status: string;
      output: { format: string; row_count: number };
      qa: { verdict: string };
      external_models_used: boolean;
    };
    expect(xmlJson.ok).toBe(true);
    expect(xmlJson.status).toBe('COMPLETED');
    expect(xmlJson.output.format).toBe('xml');
    expect(xmlJson.output.row_count).toBe(2);
    expect(xmlJson.qa.verdict).toBe('SUCCESS');
    expect(xmlJson.external_models_used).toBe(false);

    const sandboxRes = await fetch(`${gateBaseUrl}/api/tool-center/execute`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({
        capabilityId: 'testing.sandbox_run',
        input: { source: 'nums = [3, 6, 9]\nprint(sum(nums))' },
      }),
    });
    expect(sandboxRes.status).toBe(201);
    const sandboxJson = (await sandboxRes.json()) as {
      ok: boolean;
      output: { stdout: string; sandbox_isolated: boolean };
    };
    expect(sandboxJson.output.sandbox_isolated).toBe(true);
    expect(sandboxJson.output.stdout).toBe('18');

    // Non-admin rejected with 403 on admin-only capability
    const blockedRes = await fetch(`${gateBaseUrl}/api/tool-center/execute`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({ capabilityId: 'security.governance_audit', input: { limit: 5 } }),
    });
    expect(blockedRes.status).toBe(403);

    // Non-admin external webhook enters P5 Approval Gate (202 PENDING_APPROVAL) -> Admin approves
    const webhookPendRes = await fetch(`${gateBaseUrl}/api/tool-center/execute`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({
        capabilityId: 'api_integration.webhook_dispatch',
        input: { url: 'https://en.wikipedia.org/wiki/Webhook', body: { event: 'e2e' }, dry_run: true },
      }),
    });
    expect(webhookPendRes.status).toBe(202);
    const webhookPendJson = (await webhookPendRes.json()) as { status: string; invocation_id: string };
    expect(webhookPendJson.status).toBe('PENDING_APPROVAL');

    // Non-admin cannot decide tool-center invocation
    const forbiddenInvDecide = await fetch(
      `${gateBaseUrl}/api/admin/tool-center-invocations/${webhookPendJson.invocation_id}/decide`,
      {
        method: 'POST',
        headers: devHeaders,
        body: JSON.stringify({ decision: 'approve' }),
      }
    );
    expect(forbiddenInvDecide.status).toBe(403);

    const adminInvDecide = await fetch(
      `${gateBaseUrl}/api/admin/tool-center-invocations/${webhookPendJson.invocation_id}/decide`,
      {
        method: 'POST',
        headers: adminHeaders,
        body: JSON.stringify({ decision: 'approve' }),
      }
    );
    expect(adminInvDecide.status).toBe(200);
    const adminInvJson = (await adminInvDecide.json()) as {
      ok: boolean;
      status: string;
      output: { dry_run: boolean };
    };
    expect(adminInvJson.ok).toBe(true);
    expect(adminInvJson.status).toBe('COMPLETED');
    expect(adminInvJson.output.dry_run).toBe(true);

    // 4. POST /api/tool-center/orchestrate executes parallel DAG + idempotent replay
    const orchPayload = {
      goal: 'E2E parallel AST calc & code inspection',
      idempotencyScope: 'e2e-orch-scope-001',
      enableParallel: true,
      steps: [
        {
          step_id: 's1',
          capability_id: 'data.calc_ast',
          input: { expression: '(9 + 6) * 4' },
          depends_on: [],
        },
        {
          step_id: 's2',
          capability_id: 'development.code_analysis',
          input: { language: 'python', source: 'def square(n):\n    return n * n\n' },
          depends_on: [],
        },
        {
          step_id: 's3',
          capability_id: 'testing.contract_assertion',
          input: { cases: [{ name: 'positive', op: 'gt', actual: 60, expected: 0 }] },
          depends_on: ['s1', 's2'],
        },
      ],
    };
    const orchRes = await fetch(`${gateBaseUrl}/api/tool-center/orchestrate`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify(orchPayload),
    });
    expect(orchRes.status).toBe(200);
    const orchJson = (await orchRes.json()) as {
      ok: boolean;
      run_id: string;
      delivery_verdict: string;
      qa_summary: { steps_verified: number };
      external_models_used: boolean;
    };
    expect(orchJson.ok).toBe(true);
    expect(orchJson.delivery_verdict).toBe('SUCCESS');
    expect(orchJson.qa_summary.steps_verified).toBe(3);
    expect(orchJson.external_models_used).toBe(false);

    const orchReplayRes = await fetch(`${gateBaseUrl}/api/tool-center/orchestrate`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify(orchPayload),
    });
    expect(orchReplayRes.status).toBe(200);
    const orchReplayJson = (await orchReplayRes.json()) as { idempotent_replay?: boolean; run_id: string };
    expect(orchReplayJson.idempotent_replay).toBe(true);
    expect(orchReplayJson.run_id).toBe(orchJson.run_id);

    // 5. POST /api/tool-center/self-improve (admin-only) + approval gate
    const forbiddenSelfImp = await fetch(`${gateBaseUrl}/api/tool-center/self-improve`, {
      method: 'POST',
      headers: devHeaders,
      body: JSON.stringify({}),
    });
    expect(forbiddenSelfImp.status).toBe(403);

    const selfImpRes = await fetch(`${gateBaseUrl}/api/tool-center/self-improve`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({}),
    });
    expect(selfImpRes.status).toBe(201);
    const selfImpJson = (await selfImpRes.json()) as {
      ok: boolean;
      approval_required: boolean;
      model_weights_mutated: boolean;
      regression_detected: boolean;
      improved: boolean;
      proposal: { id: string; approval_status: string };
    };
    expect(selfImpJson.ok).toBe(true);
    expect(selfImpJson.approval_required).toBe(true);
    expect(selfImpJson.model_weights_mutated).toBe(false);
    expect(selfImpJson.regression_detected).toBe(false);
    expect(selfImpJson.improved).toBe(true);
    expect(selfImpJson.proposal.approval_status).toBe('PENDING_APPROVAL');

    const impApproveRes = await fetch(
      `${gateBaseUrl}/api/admin/improvement-proposals/${selfImpJson.proposal.id}/decide`,
      {
        method: 'POST',
        headers: adminHeaders,
        body: JSON.stringify({ decision: 'approve', reason: 'E2E zero regression check passed' }),
      }
    );
    expect(impApproveRes.status).toBe(200);
    const impApproveJson = (await impApproveRes.json()) as {
      ok: boolean;
      status: string;
      model_weights_mutated: boolean;
    };
    expect(impApproveJson.ok).toBe(true);
    expect(impApproveJson.status).toBe('APPROVED');
    expect(impApproveJson.model_weights_mutated).toBe(false);

    // 6. POST /api/tool-center/engineering/benchmark & POST /api/tool-center/verify
    const engBenchRes = await fetch(`${gateBaseUrl}/api/tool-center/engineering/benchmark`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({}),
    });
    expect(engBenchRes.status).toBe(200);
    const engBenchJson = (await engBenchRes.json()) as {
      ok: boolean;
      status: string;
      passed: number;
      total: number;
      metrics: { success_rate: number; regression_rate: number };
      external_models_used: boolean;
    };
    expect(engBenchJson.ok).toBe(true);
    expect(engBenchJson.status).toBe('VERIFIED');
    expect(engBenchJson.passed).toBe(engBenchJson.total);
    expect(engBenchJson.metrics.success_rate).toBe(1);
    expect(engBenchJson.metrics.regression_rate).toBe(0);
    expect(engBenchJson.external_models_used).toBe(false);

    const tcVerifyRes = await fetch(`${gateBaseUrl}/api/tool-center/verify`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({}),
    });
    expect(tcVerifyRes.status).toBe(200);
    const tcVerifyJson = (await tcVerifyRes.json()) as {
      ok: boolean;
      status: string;
      passed: number;
      total: number;
    };
    expect(tcVerifyJson.ok).toBe(true);
    expect(tcVerifyJson.status).toBe('VERIFIED');
    expect(tcVerifyJson.passed).toBe(tcVerifyJson.total);

    // 7. POST /api/autonomous/missions attaches real tool_center capabilities_json
    const missionRes = await fetch(`${gateBaseUrl}/api/autonomous/missions`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({
        goal: 'คำนวณ 12 * 12 และวิเคราะห์ความปลอดภัย',
        enableResearch: false,
        enableKnowledgeDev: false,
        enableExecution: true,
      }),
    });
    expect(missionRes.status).toBe(201);
    const missionJson = (await missionRes.json()) as {
      ok: boolean;
      mission: { status: string; capabilities_json: string; external_models_used: number };
    };
    expect(missionJson.ok).toBe(true);
    expect(missionJson.mission.external_models_used).toBe(0);
    const capsParsed = JSON.parse(missionJson.mission.capabilities_json) as {
      tool_center?: { principle: string; selected_capabilities: unknown[] };
    };
    expect(capsParsed.tool_center).toBeDefined();
    expect(capsParsed.tool_center?.selected_capabilities.length).toBeGreaterThanOrEqual(1);

    // 8. PII Redaction Audit Logging & Secure Audit Export (JSON + formula-safe CSV + RBAC)
    const piiIngestRes = await fetch(`${gateBaseUrl}/api/developer/datasets`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({
        name: 'pii-audit-corpus',
        provenance: 'internal_pii_test',
        sourceName: 'internal_pii_test',
        format: 'text',
        extractKg: false,
        redactPii: true,
        content: [
          'Contact customer alice.secret@example.org for ticket 101',
          'Backup phone 081-234-5678 recorded in support queue',
          'Citizen ID 1-1004-00123-45-6 verified before masking',
          'Non-PII technical note alpha on neural pipeline',
          'Non-PII technical note beta on safety verification',
        ].join('\n'),
      }),
    });
    expect(piiIngestRes.status).toBe(201);
    const piiIngestJson = (await piiIngestRes.json()) as {
      ok: boolean;
      pii_redaction_summary?: { email: number; phone: number; thai_id: number; total_redacted: number };
    };
    expect(piiIngestJson.ok).toBe(true);
    expect(piiIngestJson.pii_redaction_summary?.email).toBe(1);
    expect(piiIngestJson.pii_redaction_summary?.phone).toBe(1);
    expect(piiIngestJson.pii_redaction_summary?.thai_id).toBe(1);
    expect(piiIngestJson.pii_redaction_summary?.total_redacted).toBeGreaterThanOrEqual(3);

    // Non-admin user must be blocked with 403
    const userRegRes = await fetch(`${gateBaseUrl}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'regular-user@zyrquen.local',
        displayName: 'Regular User',
        password: 'RegularPassword123!',
      }),
    });
    expect(userRegRes.status).toBe(201);
    const userRegJson = (await userRegRes.json()) as { token: string };
    const forbiddenExportRes = await fetch(
      `${gateBaseUrl}/api/admin/audit-logs/export?focus=pii_redaction&format=json`,
      { headers: { Authorization: `Bearer ${userRegJson.token}` } }
    );
    expect(forbiddenExportRes.status).toBe(403);

    // Admin exports PII-redaction-focused audit logs in secure JSON format
    const exportJsonRes = await fetch(
      `${gateBaseUrl}/api/admin/audit-logs/export?focus=pii_redaction&format=json`,
      { headers: { Authorization: `Bearer ${adminToken}` } }
    );
    expect(exportJsonRes.status).toBe(200);
    expect(exportJsonRes.headers.get('content-disposition')).toContain('attachment; filename="zyrquen-audit-pii_redaction-');
    expect(exportJsonRes.headers.get('x-content-type-options')).toBe('nosniff');
    expect(exportJsonRes.headers.get('cache-control')).toContain('no-store');
    const shaHeader = exportJsonRes.headers.get('x-zyrquen-export-sha256') || '';
    const jsonFileShaHeader = exportJsonRes.headers.get('x-zyrquen-file-sha256') || '';
    expect(shaHeader.length).toBe(64);
    expect(jsonFileShaHeader.length).toBe(64);

    const exportBodyText = await exportJsonRes.text();
    const computedJsonFileSha = crypto
      .createHash('sha256')
      .update(exportBodyText, 'utf8')
      .digest('hex');
    expect(computedJsonFileSha).toBe(jsonFileShaHeader);
    expect(exportBodyText).not.toContain('alice.secret@example.org');
    expect(exportBodyText).not.toContain('081-234-5678');
    expect(exportBodyText).not.toContain('1-1004-00123-45-6');
    const exportPayload = JSON.parse(exportBodyText) as {
      ok: boolean;
      schema: string;
      focus: string;
      sanitization_applied: boolean;
      integrity_sha256: string;
      pii_redaction_event_count: number;
      exported_count: number;
      events: Array<{
        action: string;
        actor_email_masked: string;
        is_pii_redaction_event: boolean;
      }>;
    };
    expect(exportPayload.ok).toBe(true);
    expect(exportPayload.schema).toBe('zyrquen.audit-export.v1');
    expect(exportPayload.focus).toBe('pii_redaction');
    expect(exportPayload.sanitization_applied).toBe(true);
    expect(exportPayload.integrity_sha256).toBe(shaHeader);
    expect(exportPayload.pii_redaction_event_count).toBeGreaterThanOrEqual(1);
    expect(exportPayload.events.every((e) => e.is_pii_redaction_event)).toBe(true);
    expect(exportPayload.events.some((e) => e.action === 'PII_REDACTION')).toBe(true);
    expect(exportPayload.events.every((e) => e.actor_email_masked.includes('***@'))).toBe(true);

    // Admin exports sanitized CSV format
    const exportCsvRes = await fetch(
      `${gateBaseUrl}/api/admin/audit-logs/export?focus=pii_redaction&format=csv`,
      { headers: { Authorization: `Bearer ${adminToken}` } }
    );
    expect(exportCsvRes.status).toBe(200);
    expect(exportCsvRes.headers.get('content-type')).toContain('text/csv');
    const csvFileShaHeader = exportCsvRes.headers.get('x-zyrquen-file-sha256') || '';
    const csvText = await exportCsvRes.text();
    const computedCsvFileSha = crypto.createHash('sha256').update(csvText, 'utf8').digest('hex');
    expect(computedCsvFileSha).toBe(csvFileShaHeader);
    expect(csvText).toContain('PII_REDACTION');
    expect(csvText).not.toContain('alice.secret@example.org');

    // 9. Native Code Understanding & Problem-Solving Training Pipeline (AST + Sandbox + Approval Gate)
    const codeCurateRes = await fetch(`${gateBaseUrl}/api/developer/code-training/curate`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({ name: 'code-problem-solving-e2e' }),
    });
    expect(codeCurateRes.status).toBe(201);
    const codeCurateJson = (await codeCurateRes.json()) as {
      ok: boolean;
      dataset: { id: string; leakage_detected: number };
      code_verification: {
        total_tasks: number;
        verified_tasks: number;
        failed_tasks: number;
        ast_records_added: number;
        splits_counts: { train: number; val: number; test: number };
      };
    };
    expect(codeCurateJson.ok).toBe(true);
    expect(codeCurateJson.dataset.leakage_detected).toBe(0);
    expect(codeCurateJson.code_verification.verified_tasks).toBeGreaterThanOrEqual(14);
    expect(codeCurateJson.code_verification.failed_tasks).toBe(0);
    expect(codeCurateJson.code_verification.splits_counts.train).toBeGreaterThan(0);
    expect(codeCurateJson.code_verification.splits_counts.val).toBeGreaterThan(0);
    expect(codeCurateJson.code_verification.splits_counts.test).toBeGreaterThan(0);

    const codeExpRes = await fetch(`${gateBaseUrl}/api/developer/code-training/experiment`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({
        datasetId: codeCurateJson.dataset.id,
        epochs: 3,
        seed: 42,
      }),
    });
    expect(codeExpRes.status).toBe(201);
    const codeExpJson = (await codeExpRes.json()) as {
      ok: boolean;
      improved: boolean;
      external_models_used: boolean;
      experiment: { id: string; approval_status: string };
      metrics: {
        initial_train_loss: number;
        final_train_loss: number;
        initial_val_loss: number;
        final_val_loss: number;
        unseen_execution_verified: boolean;
      };
    };
    expect(codeExpJson.ok).toBe(true);
    expect(codeExpJson.external_models_used).toBe(false);
    expect(codeExpJson.metrics.unseen_execution_verified).toBe(true);
    expect(codeExpJson.metrics.final_train_loss).toBeLessThan(codeExpJson.metrics.initial_train_loss);

    if (codeExpJson.experiment.approval_status === 'PENDING_APPROVAL') {
      const approveCodeExpRes = await fetch(
        `${gateBaseUrl}/api/admin/experiments/${codeExpJson.experiment.id}/decide`,
        {
          method: 'POST',
          headers: adminHeaders,
          body: JSON.stringify({ decision: 'approve' }),
        }
      );
      expect(approveCodeExpRes.status).toBe(200);
    }

    const codeEvalRes = await fetch(`${gateBaseUrl}/api/developer/code-training/evaluate`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({}),
    });
    expect(codeEvalRes.status).toBe(200);
    const codeEvalJson = (await codeEvalRes.json()) as {
      ok: boolean;
      status: string;
      external_models_used: boolean;
      contrastive_probe?: { total: number; passed: number; accuracy: number };
    };
    expect(codeEvalJson.ok).toBe(true);
    expect(codeEvalJson.external_models_used).toBe(false);
    expect(['VERIFIED', 'PARTIAL', 'NOT_RUN']).toContain(codeEvalJson.status);
  }, 120_000);

  it('Enforces auth/ownership isolation on /api/v1/workflows/logs and executes Multi-file App Builder + Real Build Runner over HTTP', async () => {
    const adminLoginRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'gate-admin@zyrquen.local',
        password: 'StrongPassword123!',
      }),
    });
    expect(adminLoginRes.status).toBe(200);
    const { token: adminToken } = (await adminLoginRes.json()) as { token: string };
    const adminHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${adminToken}`,
    };

    const userLoginRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'regular-user@zyrquen.local',
        password: 'RegularPassword123!',
      }),
    });
    expect(userLoginRes.status).toBe(200);
    const { token: userToken } = (await userLoginRes.json()) as { token: string };
    const userHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${userToken}`,
    };

    // 1. Workflow Execution Logs (/api/v1/workflows/logs) Auth & Ownership Isolation
    const unauthLogsRes = await fetch(`${gateBaseUrl}/api/v1/workflows/logs`);
    expect(unauthLogsRes.status).toBe(401);

    const badRunIdRes = await fetch(`${gateBaseUrl}/api/v1/workflows/logs?run_id=../escape`, {
      headers: adminHeaders,
    });
    expect(badRunIdRes.status).toBe(400);

    const missingRunIdRes = await fetch(`${gateBaseUrl}/api/v1/workflows/logs?run_id=missing-run-id`, {
      headers: adminHeaders,
    });
    expect(missingRunIdRes.status).toBe(404);

    // Authenticated user with zero workflow runs MUST receive 200 with empty lists, NEVER 403
    for (const flag of ['true', 'false']) {
      const emptyUserLogsRes = await fetch(
        `${gateBaseUrl}/api/v1/workflows/logs?active_only=${flag}`,
        { headers: userHeaders }
      );
      expect(emptyUserLogsRes.status).toBe(200);
      const emptyUserLogsJson = (await emptyUserLogsRes.json()) as {
        items: unknown[];
        active_runs: unknown[];
      };
      expect(emptyUserLogsJson.items).toEqual([]);
      expect(emptyUserLogsJson.active_runs).toEqual([]);
    }

    // Trigger an admin-owned workflow run and a regular-user-owned workflow run
    const adminWfRes = await fetch(`${gateBaseUrl}/api/workflows/system_ops/run`, {
      method: 'POST',
      headers: adminHeaders,
      body: JSON.stringify({}),
    });
    expect(adminWfRes.status).toBe(201);
    const adminWfJson = (await adminWfRes.json()) as { ok: boolean; run: { id: string } };
    expect(adminWfJson.ok).toBe(true);

    const userWfRes = await fetch(`${gateBaseUrl}/api/workflows/system_ops/run`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({}),
    });
    expect(userWfRes.status).toBe(201);
    const userWfJson = (await userWfRes.json()) as { ok: boolean; run: { id: string } };
    expect(userWfJson.ok).toBe(true);

    // Non-admin querying admin's run_id MUST be rejected with 403
    const crossRunRes = await fetch(
      `${gateBaseUrl}/api/v1/workflows/logs?run_id=${encodeURIComponent(adminWfJson.run.id)}&active_only=false`,
      { headers: userHeaders }
    );
    expect(crossRunRes.status).toBe(403);

    // Non-admin listing logs sees ONLY their own runs, never admin's run
    const userLogsRes = await fetch(`${gateBaseUrl}/api/v1/workflows/logs?active_only=false`, {
      headers: userHeaders,
    });
    expect(userLogsRes.status).toBe(200);
    const userLogsJson = (await userLogsRes.json()) as {
      items: Array<{ run_id: string; level: string }>;
    };
    expect(userLogsJson.items.some((item) => item.run_id === userWfJson.run.id)).toBe(true);
    expect(userLogsJson.items.some((item) => item.run_id === adminWfJson.run.id)).toBe(false);

    // Invalid log level filter returns 400; valid level+search returns scoped entries
    const invalidLevelRes = await fetch(
      `${gateBaseUrl}/api/v1/workflows/logs?active_only=false&level=BADLEVEL`,
      { headers: userHeaders }
    );
    expect(invalidLevelRes.status).toBe(400);

    const filteredLogsRes = await fetch(
      `${gateBaseUrl}/api/v1/workflows/logs?active_only=false&level=INFO&search=system_ops`,
      { headers: userHeaders }
    );
    expect(filteredLogsRes.status).toBe(200);
    const filteredLogsJson = (await filteredLogsRes.json()) as {
      items: Array<{ run_id: string; level: string; workflow_key: string }>;
    };
    expect(filteredLogsJson.items.length).toBeGreaterThan(0);
    expect(filteredLogsJson.items.every((item) => item.level === 'INFO')).toBe(true);
    expect(filteredLogsJson.items.every((item) => item.run_id === userWfJson.run.id)).toBe(true);

    // 2. Multi-file Persistent App Builder + Real Build Runner + Workspace History over HTTP
    const wsName = 'e2e_http_app';
    const buildAppRes = await fetch(`${gateBaseUrl}/api/app-builder/build`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({
        workspace: wsName,
        goal: 'Build multi-file task tracker CLI',
        appName: 'tracker_cli',
        blueprint: 'python_cli_app',
      }),
    });
    expect(buildAppRes.status).toBe(201);
    const buildAppJson = (await buildAppRes.json()) as {
      ok: boolean;
      qa: { verdict: string };
      output: {
        verified: boolean;
        build_passed: boolean;
        lint_passed: boolean;
        tests_passed: boolean;
        tests_run: number;
        snapshot_id: string;
        files: string[];
      };
    };
    expect(buildAppJson.ok).toBe(true);
    expect(buildAppJson.qa.verdict).toBe('SUCCESS');
    expect(buildAppJson.output.verified).toBe(true);
    expect(buildAppJson.output.build_passed).toBe(true);
    expect(buildAppJson.output.lint_passed).toBe(true);
    expect(buildAppJson.output.tests_passed).toBe(true);
    expect(buildAppJson.output.tests_run).toBeGreaterThanOrEqual(3);
    expect(buildAppJson.output.files).toContain('tracker_cli/engine.py');

    // Dedicated GET /api/app-builder/workspaces lists persisted workspace
    const listWsRes = await fetch(`${gateBaseUrl}/api/app-builder/workspaces`, {
      headers: userHeaders,
    });
    expect(listWsRes.status).toBe(200);
    const listWsJson = (await listWsRes.json()) as {
      ok: boolean;
      output: { workspaces: Array<{ workspace: string; file_count: number }> };
    };
    expect(listWsJson.ok).toBe(true);
    expect(listWsJson.output.workspaces.some((w) => w.workspace === wsName)).toBe(true);

    // Incremental partial multi-file patch + real verification
    const patchAppRes = await fetch(`${gateBaseUrl}/api/app-builder/build`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({
        workspace: wsName,
        goal: 'Update README and add version note in manifest',
        patches: {
          'README.md': [{ old: 'Entrypoint', new: 'Main Entrypoint' }],
        },
      }),
    });
    expect(patchAppRes.status).toBe(201);
    const patchAppJson = (await patchAppRes.json()) as {
      ok: boolean;
      output: { verified: boolean; snapshot_id: string; diffs: Record<string, string> };
    };
    expect(patchAppJson.ok).toBe(true);
    expect(patchAppJson.output.verified).toBe(true);
    expect(patchAppJson.output.snapshot_id).not.toBe(buildAppJson.output.snapshot_id);
    expect(patchAppJson.output.diffs['README.md']).toContain('+');

    // Workspace history read_file + traversal/internal blocking via /api/app-builder/history
    const readFileRes = await fetch(`${gateBaseUrl}/api/app-builder/history`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({
        workspace: wsName,
        action: 'read_file',
        file_path: 'README.md',
      }),
    });
    expect(readFileRes.status).toBe(200);
    const readFileJson = (await readFileRes.json()) as {
      ok: boolean;
      output: { content: string };
    };
    expect(readFileJson.ok).toBe(true);
    expect(readFileJson.output.content).toContain('Main Entrypoint');

    const blockedReadRes = await fetch(`${gateBaseUrl}/api/app-builder/history`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({
        workspace: wsName,
        action: 'read_file',
        file_path: '.zyrquen_history/history.json',
      }),
    });
    expect(blockedReadRes.status).toBe(403);

    // Dedicated POST /api/app-builder/verify confirms workspace passes compileall + lint + unittest
    const runnerRes = await fetch(`${gateBaseUrl}/api/app-builder/verify`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({ workspace: wsName, runLint: true, runTests: true }),
    });
    expect(runnerRes.status).toBe(200);
    const runnerJson = (await runnerRes.json()) as {
      ok: boolean;
      output: { verified: boolean; build_passed: boolean; lint_passed: boolean; tests_passed: boolean };
    };
    expect(runnerJson.ok).toBe(true);
    expect(runnerJson.output.verified).toBe(true);

    // Rollback to initial snapshot reverts README change cleanly
    const rollbackRes = await fetch(`${gateBaseUrl}/api/app-builder/history`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({
        workspace: wsName,
        action: 'rollback',
        snapshot_id: buildAppJson.output.snapshot_id,
      }),
    });
    expect(rollbackRes.status).toBe(200);

    // External LLM import is strictly blocked and rolled back
    const badLlmRes = await fetch(`${gateBaseUrl}/api/app-builder/build`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({
        workspace: 'e2e_blocked_llm',
        goal: 'Attempt forbidden external import',
        files: {
          'bad.py': 'from openai import OpenAI\n',
          'test_bad.py': 'import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n',
        },
      }),
    });
    expect(badLlmRes.status).toBe(400);
    const badLlmJson = (await badLlmRes.json()) as {
      ok: boolean;
      output: { verified: boolean; lint_passed: boolean; rolled_back: boolean };
    };
    expect(badLlmJson.ok).toBe(false);
    expect(badLlmJson.output.verified).toBe(false);
    expect(badLlmJson.output.lint_passed).toBe(false);
    expect(badLlmJson.output.rolled_back).toBe(true);
  }, 60_000);

  it('Executes API Keys bulk-revoke, email verification, password reset, persistent JWT logout revocation, and OAuth 2.0 login/link/unlink lockout prevention over HTTP', async () => {
    // 1. Register user: email_verified=false, honest EMAIL_PROVIDER_NOT_CONFIGURED
    const regEmail = `auth-e2e-${Date.now()}@zyrquen.local`;
    const regRes = await fetch(`${gateBaseUrl}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: regEmail,
        displayName: 'Auth E2E User',
        password: 'InitialPassword123!',
        confirmPassword: 'InitialPassword123!',
      }),
    });
    expect(regRes.status).toBe(201);
    const regJson = (await regRes.json()) as {
      token: string;
      user: { id: string; email_verified: boolean; has_password?: boolean };
      verification: { emailSent: boolean; deliveryReason: string | null };
    };
    expect(regJson.user.email_verified).toBe(false);
    expect(regJson.verification.emailSent).toBe(false);
    expect(regJson.verification.deliveryReason).toBe('EMAIL_PROVIDER_NOT_CONFIGURED');

    const userHeaders = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${regJson.token}`,
    };

    // Resend returns honest EMAIL_PROVIDER_NOT_CONFIGURED
    const resendRes = await fetch(`${gateBaseUrl}/api/auth/verification/resend`, {
      method: 'POST',
      headers: userHeaders,
    });
    expect(resendRes.status).toBe(200);
    const resendJson = (await resendRes.json()) as {
      ok: boolean;
      verification: { emailSent: boolean; deliveryReason: string | null };
    };
    expect(resendJson.ok).toBe(true);
    expect(resendJson.verification.deliveryReason).toBe('EMAIL_PROVIDER_NOT_CONFIGURED');

    // Verify email via SHA-256 token stored in SQLite
    const rawVerifyToken = crypto.randomBytes(24).toString('base64url');
    const verifyTokenHash = crypto.createHash('sha256').update(rawVerifyToken).digest('hex');
    const createVerifyOut = JSON.parse(
      execFileSync('python3', ['python_core/db_bridge.py'], {
        cwd: process.cwd(),
        env: { ...process.env, ZYRQUEN_DATA_DIR: gateTmpDir, PYTHONPATH: path.resolve(process.cwd(), 'python_core') },
        input: JSON.stringify({
          action: 'auth_create_token',
          payload: {
            user_id: regJson.user.id,
            token_type: 'email_verify',
            token_hash: verifyTokenHash,
            target_email: regEmail,
            expires_in_sec: 3600,
          },
        }),
      }).toString('utf-8')
    ) as { ok: boolean };
    expect(createVerifyOut.ok).toBe(true);

    const verifyRes = await fetch(`${gateBaseUrl}/api/auth/verify-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: rawVerifyToken }),
    });
    expect(verifyRes.status).toBe(200);
    const verifyJson = (await verifyRes.json()) as { ok: boolean; user: { email_verified: boolean } };
    expect(verifyJson.ok).toBe(true);
    expect(verifyJson.user.email_verified).toBe(true);

    // 2. Bulk revoke developer API keys
    const k1Res = await fetch(`${gateBaseUrl}/api/developer/keys`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({ name: 'e2e-bulk-1', quota_daily: 500 }),
    });
    const k2Res = await fetch(`${gateBaseUrl}/api/developer/keys`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({ name: 'e2e-bulk-2', quota_daily: 500 }),
    });
    const k3Res = await fetch(`${gateBaseUrl}/api/developer/keys`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({ name: 'e2e-keep-3', quota_daily: 500 }),
    });
    expect(k1Res.status).toBe(201);
    expect(k2Res.status).toBe(201);
    expect(k3Res.status).toBe(201);
    const k1Id = ((await k1Res.json()) as { key: { id: string } }).key.id;
    const k2Id = ((await k2Res.json()) as { key: { id: string } }).key.id;
    const k3Id = ((await k3Res.json()) as { key: { id: string } }).key.id;

    const bulkEmptyRes = await fetch(`${gateBaseUrl}/api/developer/keys/bulk-revoke`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({ ids: [] }),
    });
    expect(bulkEmptyRes.status).toBe(400);

    const bulkRevokeRes = await fetch(`${gateBaseUrl}/api/developer/keys/bulk-revoke`, {
      method: 'POST',
      headers: userHeaders,
      body: JSON.stringify({ ids: [k1Id, k2Id] }),
    });
    expect(bulkRevokeRes.status).toBe(200);
    const bulkRevokeJson = (await bulkRevokeRes.json()) as {
      ok: boolean;
      revokedCount: number;
      revokedIds: string[];
    };
    expect(bulkRevokeJson.ok).toBe(true);
    expect(bulkRevokeJson.revokedCount).toBe(2);
    expect(bulkRevokeJson.revokedIds).toEqual(expect.arrayContaining([k1Id, k2Id]));

    const overviewRes = await fetch(`${gateBaseUrl}/api/developer/overview`, { headers: userHeaders });
    const overviewJson = (await overviewRes.json()) as {
      keys: Array<{ id: string; revoked: boolean | number }>;
    };
    expect(Boolean(overviewJson.keys.find((k) => k.id === k1Id)?.revoked)).toBe(true);
    expect(Boolean(overviewJson.keys.find((k) => k.id === k2Id)?.revoked)).toBe(true);
    expect(Boolean(overviewJson.keys.find((k) => k.id === k3Id)?.revoked)).toBe(false);

    // 3. Forgot password + reset password + login with new password
    const forgotRes = await fetch(`${gateBaseUrl}/api/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: regEmail }),
    });
    expect(forgotRes.status).toBe(200);

    const rawResetToken = crypto.randomBytes(24).toString('base64url');
    const resetTokenHash = crypto.createHash('sha256').update(rawResetToken).digest('hex');
    execFileSync('python3', ['python_core/db_bridge.py'], {
      cwd: process.cwd(),
      env: { ...process.env, ZYRQUEN_DATA_DIR: gateTmpDir, PYTHONPATH: path.resolve(process.cwd(), 'python_core') },
      input: JSON.stringify({
        action: 'auth_create_token',
        payload: {
          user_id: regJson.user.id,
          token_type: 'password_reset',
          token_hash: resetTokenHash,
          target_email: regEmail,
          expires_in_sec: 1800,
        },
      }),
    });

    const resetRes = await fetch(`${gateBaseUrl}/api/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: rawResetToken, password: 'UpdatedPassword456!' }),
    });
    expect(resetRes.status).toBe(200);

    const loginNewRes = await fetch(`${gateBaseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: regEmail, password: 'UpdatedPassword456!' }),
    });
    expect(loginNewRes.status).toBe(200);
    const loginNewJson = (await loginNewRes.json()) as {
      token: string;
      user: { email_verified: boolean; has_password: boolean };
    };
    expect(loginNewJson.user.email_verified).toBe(true);
    expect(loginNewJson.user.has_password).toBe(true);

    // 4. Logout persists JWT revocation in SQLite
    const logoutRes = await fetch(`${gateBaseUrl}/api/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${loginNewJson.token}` },
    });
    expect(logoutRes.status).toBe(200);
    const meAfterLogout = await fetch(`${gateBaseUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${loginNewJson.token}` },
    });
    expect(meAfterLogout.status).toBe(401);

    // 5. OAuth 2.0 unconfigured -> 503, then mock local OAuth provider test
    const unconfGh = await fetch(`${gateBaseUrl}/api/auth/oauth/github/url`);
    expect(unconfGh.status).toBe(503);

    const mockOAuthServer = http.createServer((req, res) => {
      const reqUrl = new URL(req.url || '/', 'http://127.0.0.1');
      if (reqUrl.pathname === '/github/token') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ access_token: 'mock-gh-access-token' }));
        return;
      }
      if (reqUrl.pathname === '/github/user') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(
          JSON.stringify({
            id: 900123,
            login: 'octo-zyrquen',
            name: 'Octo Zyrquen',
            avatar_url: 'https://avatars.example.test/octo.png',
          })
        );
        return;
      }
      if (reqUrl.pathname === '/github/emails') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(
          JSON.stringify([
            { email: 'oauth-user@zyrquen.local', primary: true, verified: true },
          ])
        );
        return;
      }
      if (reqUrl.pathname === '/google/token') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ access_token: 'mock-google-access-token' }));
        return;
      }
      if (reqUrl.pathname === '/google/userinfo') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(
          JSON.stringify({
            sub: 'google-sub-777',
            email: 'oauth-user@zyrquen.local',
            email_verified: true,
            name: 'Google Zyrquen',
            picture: 'https://lh3.example.test/g.png',
          })
        );
        return;
      }
      res.writeHead(404).end();
    });

    await new Promise<void>((resolve) => mockOAuthServer.listen(0, '127.0.0.1', () => resolve()));
    const mockAddr = mockOAuthServer.address();
    if (!mockAddr || typeof mockAddr === 'string') {
      throw new Error('Failed to start mock OAuth server');
    }
    const mockBase = `http://127.0.0.1:${mockAddr.port}`;
    const envKeys = [
      'ZYRQUEN_OAUTH_ALLOW_TEST_ENDPOINTS',
      'GITHUB_OAUTH_CLIENT_ID',
      'GITHUB_OAUTH_CLIENT_SECRET',
      'ZYRQUEN_GITHUB_AUTH_URL',
      'ZYRQUEN_GITHUB_TOKEN_URL',
      'ZYRQUEN_GITHUB_USER_URL',
      'ZYRQUEN_GITHUB_EMAILS_URL',
      'GOOGLE_OAUTH_CLIENT_ID',
      'GOOGLE_OAUTH_CLIENT_SECRET',
      'ZYRQUEN_GOOGLE_AUTH_URL',
      'ZYRQUEN_GOOGLE_TOKEN_URL',
      'ZYRQUEN_GOOGLE_USERINFO_URL',
    ] as const;
    const prevEnv: Record<string, string | undefined> = {};
    for (const k of envKeys) prevEnv[k] = process.env[k];

    try {
      process.env.ZYRQUEN_OAUTH_ALLOW_TEST_ENDPOINTS = '1';
      process.env.GITHUB_OAUTH_CLIENT_ID = 'gh-client-test';
      process.env.GITHUB_OAUTH_CLIENT_SECRET = 'gh-secret-test';
      process.env.ZYRQUEN_GITHUB_AUTH_URL = `${mockBase}/github/authorize`;
      process.env.ZYRQUEN_GITHUB_TOKEN_URL = `${mockBase}/github/token`;
      process.env.ZYRQUEN_GITHUB_USER_URL = `${mockBase}/github/user`;
      process.env.ZYRQUEN_GITHUB_EMAILS_URL = `${mockBase}/github/emails`;
      process.env.GOOGLE_OAUTH_CLIENT_ID = 'google-client-test';
      process.env.GOOGLE_OAUTH_CLIENT_SECRET = 'google-secret-test';
      process.env.ZYRQUEN_GOOGLE_AUTH_URL = `${mockBase}/google/authorize`;
      process.env.ZYRQUEN_GOOGLE_TOKEN_URL = `${mockBase}/google/token`;
      process.env.ZYRQUEN_GOOGLE_USERINFO_URL = `${mockBase}/google/userinfo`;

      const providersRes = await fetch(`${gateBaseUrl}/api/auth/providers`);
      const providersJson = (await providersRes.json()) as {
        providers: { github: { configured: boolean }; google: { configured: boolean } };
      };
      expect(providersJson.providers.github.configured).toBe(true);
      expect(providersJson.providers.google.configured).toBe(true);

      const ghUrlRes = await fetch(`${gateBaseUrl}/api/auth/oauth/github/url`);
      expect(ghUrlRes.status).toBe(200);
      const ghAuthUrl = new URL(((await ghUrlRes.json()) as { url: string }).url);
      const ghState = ghAuthUrl.searchParams.get('state') || '';
      expect(ghState).toBeTruthy();

      const ghCbRes = await fetch(
        `${gateBaseUrl}/api/auth/oauth/github/callback?code=gh-code-1&state=${encodeURIComponent(ghState)}`
      );
      expect(ghCbRes.status).toBe(200);
      const ghHtml = await ghCbRes.text();
      expect(ghHtml).toContain('OAUTH_AUTH_SUCCESS');
      const tokenMatch = ghHtml.match(/"token":"([^"]+)"/);
      expect(tokenMatch?.[1]).toBeTruthy();
      const oauthToken = tokenMatch![1];
      const oauthHeaders = {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${oauthToken}`,
      };

      // Link Google identity to OAuth user
      const gLinkUrlRes = await fetch(`${gateBaseUrl}/api/auth/oauth/google/url?intent=link`, {
        headers: oauthHeaders,
      });
      expect(gLinkUrlRes.status).toBe(200);
      const gState = new URL(((await gLinkUrlRes.json()) as { url: string }).url).searchParams.get('state') || '';
      const gLinkCbRes = await fetch(
        `${gateBaseUrl}/api/auth/oauth/google/callback?code=g-code-1&state=${encodeURIComponent(gState)}`
      );
      expect(gLinkCbRes.status).toBe(200);
      expect(await gLinkCbRes.text()).toContain('OAUTH_LINK_SUCCESS');

      const identitiesRes = await fetch(`${gateBaseUrl}/api/auth/identities`, { headers: oauthHeaders });
      expect(identitiesRes.status).toBe(200);
      const identitiesJson = (await identitiesRes.json()) as {
        has_password: boolean;
        identities: Array<{ provider: string }>;
      };
      expect(identitiesJson.has_password).toBe(false);
      expect(identitiesJson.identities.map((i) => i.provider)).toEqual(
        expect.arrayContaining(['github', 'google'])
      );

      // Unlink Google succeeds; unlinking last GitHub without password is blocked (409)
      const unlinkGoogle = await fetch(`${gateBaseUrl}/api/auth/identities/google`, {
        method: 'DELETE',
        headers: oauthHeaders,
      });
      expect(unlinkGoogle.status).toBe(200);

      const unlinkLastGh = await fetch(`${gateBaseUrl}/api/auth/identities/github`, {
        method: 'DELETE',
        headers: oauthHeaders,
      });
      expect(unlinkLastGh.status).toBe(409);

      // Set initial password, then unlinking GitHub succeeds
      const setPwdRes = await fetch(`${gateBaseUrl}/api/auth/password`, {
        method: 'POST',
        headers: oauthHeaders,
        body: JSON.stringify({ newPassword: 'OAuthSetPassword789!' }),
      });
      expect(setPwdRes.status).toBe(200);

      const unlinkGhAfterPwd = await fetch(`${gateBaseUrl}/api/auth/identities/github`, {
        method: 'DELETE',
        headers: oauthHeaders,
      });
      expect(unlinkGhAfterPwd.status).toBe(200);
    } finally {
      for (const k of envKeys) {
        if (prevEnv[k] === undefined) delete process.env[k];
        else process.env[k] = prevEnv[k];
      }
      await new Promise<void>((resolve) => mockOAuthServer.close(() => resolve()));
    }
  }, 45_000);
});



