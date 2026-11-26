import fs from 'node:fs';
import path from 'node:path';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App, {
  PerformanceMonitor,
  verifyThreadEffectCleanup,
  type MemorySnapshot,
  type ThreadLoadEntry,
} from '../App';
import { AuthGate } from '../components/AuthGate';
import { MemoryWorkflowsView } from '../components/MemoryWorkflowsView';
import { SettingsView } from '../components/SettingsView';
import { SpacetimeFabric } from '../components/SpacetimeFabric';
import { TemporalIntelligenceCore } from '../components/TemporalIntelligenceCore';
import { ZyrquenEmblem } from '../components/ZyrquenEmblem';
import { streamConversationMessage } from '../lib/api';

function mockFetch(handlers: Record<string, (init?: RequestInit) => Response | Promise<Response>>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const path = url.split('?')[0];
    const key = `${init?.method || 'GET'} ${path}`;
    const handler = handlers[key] || handlers[path];
    if (!handler) {
      return new Response(JSON.stringify({ error: `Unhandled route: ${key}` }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return handler(init);
  }) as unknown as typeof fetch;
}

describe('ZYRQUEN ประสบการณ์แอปพลิเคชันภาษาไทยเป็นหลัก', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
    vi.restoreAllMocks();
  });

  it('แสดงหน้าตั้งค่าผู้ดูแลระบบเริ่มต้นเมื่อยังไม่มีบัญชี และสมัครผู้ดูแลสำเร็จ', async () => {
    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: false, userCount: 0, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'POST /api/auth/claim-admin': () =>
        new Response(
          JSON.stringify({
            token: 'mem-token-1',
            user: {
              id: 'u1',
              email: 'admin@zyrquen.local',
              display_name: 'หัวหน้าทีมวิจัย',
              role: 'admin',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 201 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [],
            counts: { triples: 0, checkpoints: 0, datasets: 0, pending_approvals: 0 },
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 4096,
              mem_available_mb: 2048,
              disk_free_gb: 20,
              disk_total_gb: 50,
              sqlite_db_kb: 16,
            },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(JSON.stringify({ conversations: [] }), { status: 200 }),
    });

    render(<App />);

    expect(await screen.findByText('ตั้งค่าผู้ดูแลระบบเริ่มต้น')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('ชื่อที่แสดง'), {
      target: { value: 'หัวหน้าทีมวิจัย' },
    });
    fireEvent.change(screen.getByLabelText('อีเมล'), {
      target: { value: 'admin@zyrquen.local' },
    });
    fireEvent.change(screen.getByLabelText('รหัสผ่าน'), {
      target: { value: 'supersecure99' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ตั้งค่าผู้ดูแลและเข้าใช้งาน/i }));

    expect(await screen.findByText('คุณต้องการสร้างอะไรวันนี้?')).toBeInTheDocument();
    expect(screen.getByText(/ผู้ใช้งาน: หัวหน้าทีมวิจัย/i)).toBeInTheDocument();
    expect(screen.getByText('พัฒนาซอฟต์แวร์')).toBeInTheDocument();
    expect(screen.getByText('วิเคราะห์ข้อมูล')).toBeInTheDocument();
  });

  it('อนุญาตให้สมัครสมาชิกใหม่ (role=user) ทั้งก่อนและหลังตั้งค่าผู้ดูแล พร้อมตรวจสอบยืนยันรหัสผ่าน', async () => {
    let registerPayloads: Array<Record<string, unknown>> = [];
    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: false, userCount: 0, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'POST /api/auth/register': (init) => {
        const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
        registerPayloads.push(body);
        return new Response(
          JSON.stringify({
            token: 'member-token-1',
            user: {
              id: 'u-mem-1',
              email: 'newmember@zyrquen.local',
              display_name: 'สมาชิกใหม่',
              role: 'user',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 201 }
        );
      },
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [],
            counts: { triples: 0, checkpoints: 0, datasets: 0, pending_approvals: 0 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(JSON.stringify({ conversations: [] }), { status: 200 }),
    });

    render(<App />);

    // Default shows admin claim, while สมัครสมาชิก tab is immediately accessible
    expect(await screen.findByText('ตั้งค่าผู้ดูแลระบบเริ่มต้น')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'สมัครสมาชิก' }));

    expect(await screen.findByText('สมัครสมาชิกใหม่ (บัญชีผู้ใช้งานทั่วไป)')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('ชื่อที่แสดง'), {
      target: { value: 'สมาชิกใหม่' },
    });
    fireEvent.change(screen.getByLabelText('อีเมล'), {
      target: { value: 'newmember@zyrquen.local' },
    });
    fireEvent.change(screen.getByLabelText('รหัสผ่าน'), {
      target: { value: 'memberpass123' },
    });
    fireEvent.change(screen.getByLabelText('ยืนยันรหัสผ่าน'), {
      target: { value: 'wrongconfirm123' },
    });

    const submitButtons = screen.getAllByRole('button', { name: 'สมัครสมาชิก' });
    fireEvent.click(submitButtons[submitButtons.length - 1]);

    expect(await screen.findByRole('alert')).toHaveTextContent('รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน');
    expect(registerPayloads).toHaveLength(0);

    fireEvent.change(screen.getByLabelText('ยืนยันรหัสผ่าน'), {
      target: { value: 'memberpass123' },
    });
    fireEvent.click(submitButtons[submitButtons.length - 1]);

    expect(await screen.findByText('คุณต้องการสร้างอะไรวันนี้?')).toBeInTheDocument();
    expect(screen.getByText(/ผู้ใช้งาน: สมาชิกใหม่/i)).toBeInTheDocument();
    expect(registerPayloads).toHaveLength(1);
    expect(registerPayloads[0]).toMatchObject({
      email: 'newmember@zyrquen.local',
      displayName: 'สมาชิกใหม่',
    });
  });

  it('นำทาง หน้าหลัก -> เวิร์กสเปซ -> ตั้งค่า -> ออกจากระบบ, รองรับประวัติเบราว์เซอร์ และตรวจสอบสิทธิ์ RBAC', async () => {
    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: true, userCount: 2, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'POST /api/auth/login': () =>
        new Response(
          JSON.stringify({
            token: 'user-token',
            user: {
              id: 'u2',
              email: 'member@zyrquen.local',
              display_name: 'สมาชิกทดสอบ',
              role: 'user',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 200 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [],
            counts: { triples: 1, checkpoints: 0, datasets: 0, pending_approvals: 0 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(JSON.stringify({ conversations: [] }), { status: 200 }),
      'POST /api/conversations': () =>
        new Response(
          JSON.stringify({
            conversation: {
              id: 'c1',
              title: 'คำนวณ (2^12 - 96) / 16',
              mode: 'math',
              updated_at: '2026-11-24T00:00:00Z',
              message_count: 0,
            },
          }),
          { status: 201 }
        ),
      'GET /api/conversations/c1': () =>
        new Response(
          JSON.stringify({
            conversation: {
              id: 'c1',
              title: 'คำนวณ (2^12 - 96) / 16',
              mode: 'math',
              updated_at: '2026-11-24T00:00:00Z',
              message_count: 2,
            },
            messages: [],
          }),
          { status: 200 }
        ),
      'GET /api/conversations/c1/summary': () =>
        new Response(
          JSON.stringify({
            ok: true,
            summary: {
              bullets: [
                'คำนวณ AST ยืนยันผล: `(2**12 - 96) / 16` = `250`',
                'หัวข้อหลักที่สนทนา: คำนวณ',
              ],
              metrics: { total_messages: 2, verified_count: 1, not_learned_count: 0 },
            },
          }),
          { status: 200 }
        ),
      'POST /api/conversations/c1/stream': (() => {
        let msgSeq = 0;
        return (init?: RequestInit) => {
          msgSeq += 1;
          const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
          const meta = (body.metadata || {}) as Record<string, unknown>;
          (globalThis as unknown as { __lastStreamMeta?: Record<string, unknown> }).__lastStreamMeta = meta;
          return new Response(
            JSON.stringify({
              title: 'คำนวณ (2^12 - 96) / 16',
              user_message: {
                id: `m-u-${msgSeq}`,
                conversation_id: 'c1',
                role: 'user',
                content: 'คำนวณ (2^12 - 96) / 16',
                mode: 'math',
                trace_json: null,
                status: 'USER',
                created_at: '2026-11-24T00:00:01Z',
              },
              assistant_message: {
                id: `m-a-${msgSeq}`,
                conversation_id: 'c1',
                role: 'assistant',
                content: '**ผลลัพธ์:** `250`',
                mode: 'math',
                trace_json: JSON.stringify({
                  engine_path: ['math_ast'],
                  model_version: meta.modelVersion || 'zyrquen-omega-v1',
                  latency_ms: 4.2,
                  external_models_used: false,
                }),
                status: 'VERIFIED',
                created_at: '2026-11-24T00:00:02Z',
              },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        };
      })(),
      'GET /api/developer/overview': (() => {
        return () =>
          new Response(
            JSON.stringify({
              keys: [],
              datasets: [
                {
                  id: 'ds-1',
                  name: 'zyrquen-core-corpus',
                  manifest_hash: 'abcdef1234567890',
                  total_records: 8,
                  train_count: 5,
                  val_count: 1,
                  test_count: 2,
                  leakage_detected: 0,
                  status: 'READY',
                  created_at: '2026-11-24T00:00:00Z',
                },
              ],
              checkpoints: [],
              evaluations: (globalThis as unknown as { __mockEvals?: Array<Record<string, unknown>> }).__mockEvals || [],
              usage: { total_requests: 5, avg_latency_ms: 12.4, daily_quota: 1000, recent: [] },
            }),
            { status: 200 }
          );
      })(),
      'POST /api/workflows/native_training/run': () =>
        new Response(
          JSON.stringify({
            ok: true,
            run: {
              id: 'r-train-1',
              group_id: 'native_training',
              status: 'PENDING_APPROVAL',
              requires_approval: 1,
              summary: 'Approval Gate active: ฝึกโมเดลภายใน requires Admin authorization.',
            },
          }),
          { status: 201 }
        ),
      'POST /api/developer/evaluate': () => {
        const evalRecord = {
          id: 'ev-1',
          checkpoint_version: null,
          suite_name: 'ZYRQUEN Scientific Benchmark v1',
          overall_status: 'PARTIAL',
          math_score: 1.0,
          knowledge_score: 0.0,
          planning_score: 1.0,
          test_accuracy: null,
          perplexity: null,
          baseline_delta_json: null,
          created_at: '2026-11-24T00:00:00Z',
        };
        (globalThis as unknown as { __mockEvals?: Array<Record<string, unknown>> }).__mockEvals = [evalRecord];
        return new Response(
          JSON.stringify({ ok: true, evaluation: evalRecord }),
          { status: 201 }
        );
      },
      'GET /api/developer/tools': () =>
        new Response(
          JSON.stringify({
            tools: [
              {
                id: 'web_search',
                name: 'ค้นหาเว็บสาธารณะ (Web Search Tool)',
                category: 'web',
                description: 'ค้นหาสาธารณะ',
                endpoint_allowlist_json: '["en.wikipedia.org"]',
                permission_mode: 'approval_required',
                enabled: 1,
                quota_daily: 50,
                calls_today: 0,
                last_reset_date: '2026-11-24',
                updated_at: '2026-11-24T00:00:00Z',
              },
              {
                id: 'calc_ast',
                name: 'คำนวณ AST / สมการ / สถิติ (Compute Tool)',
                category: 'compute',
                description: 'คำนวณ AST ภายใน',
                endpoint_allowlist_json: '[]',
                permission_mode: 'auto',
                enabled: 1,
                quota_daily: 200,
                calls_today: 1,
                last_reset_date: '2026-11-24',
                updated_at: '2026-11-24T00:00:00Z',
              },
            ],
            invocations: [],
            workspace_files: [],
          }),
          { status: 200 }
        ),
      'POST /api/developer/tools/calc_ast/invoke': () =>
        new Response(
          JSON.stringify({
            ok: true,
            status: 'COMPLETED',
            analysis: {
              summary: 'ZYRQUEN Native Compute ยืนยันผลลัพธ์จากเครื่องมือ AST ภายในเรียบร้อยแล้ว',
            },
          }),
          { status: 201 }
        ),
      'POST /api/auth/logout': () =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
    });

    (globalThis as unknown as { __mockEvals?: Array<Record<string, unknown>> }).__mockEvals = [];

    render(<App />);

    const emailInput = await screen.findByLabelText('อีเมล');
    fireEvent.change(emailInput, { target: { value: 'member@zyrquen.local' } });
    fireEvent.change(screen.getByLabelText('รหัสผ่าน'), { target: { value: 'password123' } });
    const signInButtons = screen.getAllByRole('button', { name: 'เข้าสู่ระบบ' });
    fireEvent.click(signInButtons[signInButtons.length - 1]);

    expect(await screen.findByText('คุณต้องการสร้างอะไรวันนี้?')).toBeInTheDocument();
    expect(screen.getByText(/ผู้ใช้งาน: สมาชิกทดสอบ/i)).toBeInTheDocument();

    // Model Variant selection lives in Settings -> Account/Workspace
    fireEvent.click(screen.getAllByRole('button', { name: 'ตั้งค่า' })[0]);
    const variantSelect = await screen.findByLabelText('เลือกรุ่นโมเดล (Model Variant)');
    fireEvent.change(variantSelect, { target: { value: 'zyrquen-ast-pro' } });

    fireEvent.click(screen.getAllByRole('button', { name: 'ภาพรวม' })[0]);
    const homeGoalInput = await screen.findByLabelText(
      'อธิบายเป้าหมายหรือแนบไฟล์เพื่อให้ ZYRQUEN เริ่มดำเนินงาน'
    );
    fireEvent.change(homeGoalInput, { target: { value: 'คำนวณ (2^12 - 96) / 16' } });
    fireEvent.click(screen.getByRole('button', { name: 'เริ่มดำเนินงาน' }));
    expect(await screen.findByText('250')).toBeInTheDocument();
    expect(window.location.search).toContain('view=workspace');

    const composer = screen.getByLabelText('ช่องพิมพ์คำสั่งงาน');
    fireEvent.change(composer, { target: { value: 'คำนวณ 10 + 15' } });
    fireEvent.keyDown(composer, { key: 'Enter', shiftKey: false });
    await waitFor(() => {
      expect(screen.getAllByText('250').length).toBeGreaterThan(0);
    });
    expect(
      (globalThis as unknown as { __lastStreamMeta?: Record<string, unknown> }).__lastStreamMeta?.modelVersion
    ).toBe('zyrquen-ast-pro');

    // Smart Summary collapsible panel
    fireEvent.click(screen.getByRole('button', { name: /สรุปผลลัพธ์/i }));
    expect(await screen.findByText(/Smart Summary/i)).toBeInTheDocument();
    expect(await screen.findByText(/คำนวณ AST ยืนยันผล/i)).toBeInTheDocument();

    // Ctrl+K Command Palette shortcut + Fuse.js typo tolerance
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(await screen.findByRole('dialog', { name: /Command Palette/i })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('ค้นหาคำสั่งด่วน'), { target: { value: 'Accont' } });
    fireEvent.click(await screen.findByRole('button', { name: /ไปที่ ตั้งค่าบัญชีผู้ใช้/i }));
    expect(await screen.findByText('โปรไฟล์และเซสชัน')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'ผู้ดูแลระบบ' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'นักพัฒนา' }));
    expect(await screen.findByText('จัดการ API Keys')).toBeInTheDocument();
    expect(await screen.findByText('12.4 ms')).toBeInTheDocument();
    expect(await screen.findByText('zyrquen-core-corpus')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'ส่งคำขอฝึก (Gate)' }));
    expect(await screen.findByText(/เข้า Approval Gate แล้ว/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'ประเมินผลเทียบ Baseline' }));
    expect(await screen.findByText(/ผลประเมินล่าสุด \(PARTIAL\)/i)).toBeInTheDocument();

    // External Tool Registry & Governed Invocation inside Developer Settings
    expect(await screen.findByText('Tool Registry & โควตาเครื่องมือภายนอก')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('เลือกเครื่องมือ'), { target: { value: 'calc_ast' } });
    fireEvent.change(screen.getByPlaceholderText('แก้สมการ: 3x + 7 = 22'), {
      target: { value: 'แก้สมการ: 3x + 7 = 22' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'เรียกเครื่องมือ' }));
    expect(
      await screen.findByText(/ZYRQUEN Native Compute ยืนยันผลลัพธ์/i)
    ).toBeInTheDocument();

    // Alt+N global shortcut starts a fresh Workspace conversation
    fireEvent.keyDown(window, { key: 'n', altKey: true });
    expect(await screen.findByText('พื้นที่ดำเนินงาน ZYRQUEN')).toBeInTheDocument();

    window.history.replaceState({}, '', '/');
    fireEvent(window, new PopStateEvent('popstate'));
    expect(await screen.findByText('คุณต้องการสร้างอะไรวันนี้?')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: 'ตั้งค่า' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'ออกจากระบบ' }));
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'เข้าสู่ระบบ' }).length).toBeGreaterThan(0);
    });
  }, 15_000);

  it('ซ่อนแถบนำทางล่างบนมือถือใน Workspace, เปิดประวัติบทสนทนา และรันเวิร์กโฟลว์ในหน้าความจำได้', async () => {
    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: true, userCount: 1, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'POST /api/auth/login': () =>
        new Response(
          JSON.stringify({
            token: 'admin-token',
            user: {
              id: 'u1',
              email: 'admin@zyrquen.local',
              display_name: 'ผู้ดูแลหลัก',
              role: 'admin',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 200 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [
              {
                id: 'c-prev',
                title: 'เซสชันคณิตศาสตร์ก่อนหน้า',
                mode: 'math',
                updated_at: '2026-11-24T00:00:00Z',
                message_count: 2,
              },
            ],
            counts: { triples: 2, checkpoints: 1, datasets: 1, pending_approvals: 0 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(
          JSON.stringify({
            conversations: [
              {
                id: 'c-prev',
                title: 'เซสชันคณิตศาสตร์ก่อนหน้า',
                mode: 'math',
                updated_at: '2026-11-24T00:00:00Z',
                message_count: 2,
              },
            ],
          }),
          { status: 200 }
        ),
      'GET /api/knowledge': () =>
        new Response(
          JSON.stringify({
            triples: [
              {
                id: 't1',
                subject: 'ZYRQUEN',
                relation: 'ใช้งาน',
                object: 'Python Native Core',
                source: 'test',
                confidence: 1,
                created_by: 'u1',
                created_at: '2026-11-24T00:00:00Z',
              },
            ],
          }),
          { status: 200 }
        ),
      'GET /api/workflows': () =>
        new Response(
          JSON.stringify({
            groups: [
              {
                id: 'system_ops',
                name: 'ปฏิบัติการระบบ (System Operations)',
                description: 'ตรวจสุขภาพระบบ',
                requires_approval: false,
                stages: ['health_probe'],
              },
              {
                id: 'native_training',
                name: 'ฝึกโมเดลภายใน (Native Training)',
                description: 'ฝึก Checkpoint รุ่นใหม่',
                requires_approval: true,
                stages: ['approval_gate'],
              },
            ],
            runs: [],
          }),
          { status: 200 }
        ),
      'POST /api/workflows/system_ops/run': () =>
        new Response(
          JSON.stringify({
            run: {
              id: 'r1',
              group_id: 'system_ops',
              status: 'COMPLETED',
              requires_approval: 0,
              triggered_by: 'u1',
              approved_by: null,
              summary: 'System Operations verified.',
              stages_json: JSON.stringify([{ stage: 'health_probe', status: 'PASS', detail: 'OK' }]),
              created_at: '2026-11-24T00:00:00Z',
              updated_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 201 }
        ),
    });

    render(<App />);
    const emailInput = await screen.findByLabelText('อีเมล');
    fireEvent.change(emailInput, { target: { value: 'admin@zyrquen.local' } });
    fireEvent.change(screen.getByLabelText('รหัสผ่าน'), { target: { value: 'password123' } });
    const signInButtons = screen.getAllByRole('button', { name: 'เข้าสู่ระบบ' });
    fireEvent.click(signInButtons[signInButtons.length - 1]);

    expect(await screen.findByText('เซสชันคณิตศาสตร์ก่อนหน้า')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'แถบนำทางมือถือ' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'เปิดพื้นที่ดำเนินงาน' }));
    expect(await screen.findByLabelText('ช่องพิมพ์คำสั่งงาน')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'แถบนำทางมือถือ' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'เปิดประวัติการสนทนา' }));
    expect(await screen.findByRole('dialog', { name: 'ประวัติการสนทนา' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'ปิดรายการงาน' }));

    fireEvent.click(screen.getAllByRole('button', { name: 'ตั้งค่า' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'เปิดหน้าความจำและเวิร์กโฟลว์' }));
    expect(await screen.findByText('ความจำและระบบเวิร์กโฟลว์ภายใน')).toBeInTheDocument();

    // Global fuzzy search with Fuse.js queries across Knowledge Fragments & Workflow Definitions simultaneously
    const globalSearch = screen.getByLabelText('ค้นหากราฟความรู้และเวิร์กโฟลว์');
    fireEvent.change(globalSearch, { target: { value: 'System Operatons' } });
    expect(await screen.findByText('ปฏิบัติการระบบ (System Operations)')).toBeInTheDocument();
    expect(screen.queryByText('ฝึกโมเดลภายใน (Native Training)')).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: 'เริ่มรันเวิร์กโฟลว์' }));
    expect(await screen.findByText('System Operations verified.')).toBeInTheDocument();

    fireEvent.change(globalSearch, { target: { value: 'Pythn' } });
    expect(await screen.findByText('Python Native Core')).toBeInTheDocument();
  });

  it('รับเสียงผ่าน SpeechRecognition API ลงในช่องข้อความ และบังคับใช้งานแบบเชื่อมต่ออินเทอร์เน็ตเท่านั้น', async () => {
    class MockSpeechRecognition {
      lang = 'th-TH';
      interimResults = false;
      continuous = false;
      onresult: ((ev: { resultIndex: number; results: Array<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null = null;
      onerror: ((ev: { error: string }) => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        expect(this.interimResults).toBe(true);
        expect(this.continuous).toBe(true);
        // First emit interim partial spoken text
        this.onresult?.({
          resultIndex: 0,
          results: [{ isFinal: false, 0: { transcript: 'คำนวณ 25' } }],
        });
        // Then commit final transcript seamlessly without duplicating interim text
        this.onresult?.({
          resultIndex: 0,
          results: [{ isFinal: true, 0: { transcript: 'คำนวณ 25 * 4' } }],
        });
        this.onend?.();
      }
      stop() {
        this.onend?.();
      }
    }

    (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition = MockSpeechRecognition;

    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: true, userCount: 1, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'POST /api/auth/login': () =>
        new Response(
          JSON.stringify({
            token: 'voice-token',
            user: {
              id: 'u1',
              email: 'admin@zyrquen.local',
              display_name: 'ผู้ดูแลเสียง',
              role: 'admin',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 200 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [],
            counts: { triples: 0, checkpoints: 0, datasets: 0, pending_approvals: 0 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(JSON.stringify({ conversations: [] }), { status: 200 }),
    });

    render(<App />);
    const emailInput = await screen.findByLabelText('อีเมล');
    fireEvent.change(emailInput, { target: { value: 'admin@zyrquen.local' } });
    fireEvent.change(screen.getByLabelText('รหัสผ่าน'), { target: { value: 'password123' } });
    const signInButtons = screen.getAllByRole('button', { name: 'เข้าสู่ระบบ' });
    fireEvent.click(signInButtons[signInButtons.length - 1]);

    expect(await screen.findByText('คุณต้องการสร้างอะไรวันนี้?')).toBeInTheDocument();
    expect(screen.getByText(/ผู้ใช้งาน: ผู้ดูแลเสียง/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'เปิดพื้นที่ดำเนินงาน' }));

    const micBtn = await screen.findByRole('button', { name: /พิมพ์ด้วยเสียง/i });
    fireEvent.click(micBtn);

    const textarea = screen.getByLabelText('ช่องพิมพ์คำสั่งงาน') as HTMLTextAreaElement;
    expect(textarea.value).toContain('คำนวณ 25 * 4');

    // Enforce online-only connectivity
    fireEvent(window, new Event('offline'));
    expect(await screen.findByText('ต้องเชื่อมต่ออินเทอร์เน็ตเท่านั้น')).toBeInTheDocument();
    fireEvent(window, new Event('online'));
    expect(await screen.findByLabelText('ช่องพิมพ์คำสั่งงาน')).toBeInTheDocument();

    delete (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition;
  });

  it('แสดงกล่องหลักฐานวิเคราะห์จาก Native Core (>) และรายการใน SafeMessageText อย่างปลอดภัย', async () => {
    const { SafeMessageText } = await import('../components/SafeMessageText');
    render(
      <SafeMessageText
        content={
          '**ผลสังเคราะห์หลักฐานโดย ZYRQUEN Native Core** (`web_search` · ระดับความน่าเชื่อถือ: `CORROBORATED_MULTI_SOURCE`)\n\n' +
          '> [CORROBORATED_MULTI_SOURCE] Native Core ประเมินหลักฐานจาก 2 แหล่ง\n\n' +
          '- คำสำคัญที่สอดคล้องข้ามแหล่งข้อมูล: `sqlite, database`'
        }
      />
    );

    expect(
      screen.getByText(/ผลสังเคราะห์หลักฐานโดย ZYRQUEN Native Core/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/\[CORROBORATED_MULTI_SOURCE\] Native Core ประเมินหลักฐานจาก 2 แหล่ง/)
    ).toBeInTheDocument();
    expect(screen.getByText('sqlite, database')).toBeInTheDocument();
  });

  it('ตรวจสอบ ExternalToolAdapter (validate/run/audit), ToolRegistry P5 Gate และตัวบอกสถานะเครื่องมือใน WorkspaceView', async () => {
    const { externalToolAdapter } = await import('../lib/tools');
    const { ToolRegistry } = await import('../components/ToolRegistry');
    const { WorkspaceView } = await import('../components/WorkspaceView');

    // 1. Adapter validation blocks insecure HTTP & external AI hosts
    const badHttp = externalToolAdapter.validate('doc_fetch', { url: 'http://en.wikipedia.org/wiki/SQLite' });
    expect(badHttp.ok).toBe(false);
    const badLlm = externalToolAdapter.validate('doc_fetch', { url: 'https://api.openai.com/v1/models' });
    expect(badLlm.ok).toBe(false);
    const badPath = externalToolAdapter.validate('workspace_file_read', { action: 'read', filename: '../secret.txt' });
    expect(badPath.ok).toBe(false);

    // 2. Adapter run() validates, invokes backend, and records audit entries
    const decideCalls: string[] = [];
    mockFetch({
      'POST /api/developer/tools/calc_ast/invoke': () =>
        new Response(
          JSON.stringify({
            ok: true,
            status: 'COMPLETED',
            invocation: {
              id: 'inv-99',
              tool_id: 'calc_ast',
              conversation_id: null,
              user_id: 'u2',
              status: 'COMPLETED',
              input_json: '{"expression":"2+3"}',
              output_json: '{"result":5}',
              analysis_summary: 'ผลคำนวณ AST = 5',
              approved_by: null,
              latency_ms: 1.5,
              created_at: '2026-11-24T00:00:00Z',
            },
            analysis: { trust_grade: 'INTERNAL_DETERMINISTIC', summary: 'ผลคำนวณ AST = 5' },
          }),
          { status: 201 }
        ),
      'POST /api/admin/tool-invocations/inv-gate-1/decide': () => {
        decideCalls.push('inv-gate-1');
        return new Response(JSON.stringify({ ok: true, status: 'COMPLETED' }), { status: 200 });
      },
    });

    const runRes = await externalToolAdapter.run('calc_ast', { expression: '2 + 3' }, 'tok-1');
    expect(runRes.ok).toBe(true);
    expect(runRes.status).toBe('COMPLETED');
    const entries = externalToolAdapter.audit({
      toolId: 'calc_ast',
      action: 'TEST_AUDIT_CHECK',
      outcome: 'COMPLETED',
      timestamp: '2026-11-24T00:00:00Z',
    });
    expect(entries.some((e) => e.action === 'TEST_AUDIT_CHECK')).toBe(true);

    // 3. ToolRegistry Admin P5 Gate renders & approves
    const onRefresh = vi.fn();
    render(
      <ToolRegistry
        token="admin-tok"
        userRole="admin"
        mode="admin"
        pendingInvocations={[
          {
            id: 'inv-gate-1',
            tool_id: 'web_search',
            conversation_id: null,
            user_id: 'u2',
            status: 'PENDING_APPROVAL',
            input_json: '{"query":"SQLite"}',
            output_json: null,
            analysis_summary: null,
            approved_by: null,
            latency_ms: 0,
            created_at: '2026-11-24T00:00:00Z',
          },
        ]}
        adminTools={[]}
        onRefresh={onRefresh}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'อนุมัติเครื่องมือ' }));
    await waitFor(() => {
      expect(decideCalls).toEqual(['inv-gate-1']);
    });

    // 4. WorkspaceView shows subtle tool status indicator while awaiting tool response
    let resolveSend!: () => void;
    const sendPromise = new Promise<void>((r) => {
      resolveSend = r;
    });
    const { rerender } = render(
      <WorkspaceView
        token="tok-1"
        conversations={[]}
        activeConversationId="c1"
        activeTitle="ทดสอบ"
        messages={[]}
        loadingThread={false}
        sending={false}
        error={null}
        autoExpandTrace={false}
        defaultMode="auto"
        onSelectConversation={vi.fn()}
        onNewConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onSendMessage={vi.fn(() => sendPromise)}
      />
    );

    const box = screen.getByLabelText('ช่องพิมพ์คำสั่งงาน');
    fireEvent.change(box, { target: { value: 'ค้นคว้า: SQLite' } });
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: false });

    rerender(
      <WorkspaceView
        token="tok-1"
        conversations={[]}
        activeConversationId="c1"
        activeTitle="ทดสอบ"
        messages={[]}
        loadingThread={false}
        sending={true}
        error={null}
        autoExpandTrace={false}
        defaultMode="auto"
        onSelectConversation={vi.fn()}
        onNewConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onSendMessage={vi.fn(() => sendPromise)}
      />
    );

    expect(await screen.findByRole('status')).toHaveTextContent('กำลังสืบค้นข้อมูลและตรวจสอบหลักฐาน...');
    await act(async () => {
      resolveSend();
    });

    // 5. ToolRegistry enforces role & system policy restrictions in developer mode
    render(
      <ToolRegistry
        token="user-tok"
        userRole="user"
        mode="developer"
        toolsData={{
          tools: [
            {
              id: 'web_search',
              name: 'ค้นหาเว็บสาธารณะ',
              category: 'web',
              description: 'ปิดโดยผู้ดูแล',
              endpoint_allowlist_json: '[]',
              permission_mode: 'disabled',
              enabled: 0,
              quota_daily: 50,
              calls_today: 0,
              last_reset_date: '2026-11-24',
              updated_at: '2026-11-24T00:00:00Z',
            },
          ],
          invocations: [],
          workspace_files: [],
        }}
        onRefresh={vi.fn()}
      />
    );
    expect(screen.getByRole('button', { name: 'ถูกจำกัดสิทธิ์' })).toBeDisabled();
  });

  it('PerformanceMonitor ติดตามหน่วยความจำขณะสตรีมมิ่งต่อเนื่องและทำความสะอาดตัวจับเวลาเมื่อออกจากหน้าจอ', async () => {
    vi.useFakeTimers();
    const samples: MemorySnapshot[] = [];
    const origPerfMemory = (performance as unknown as { memory?: unknown }).memory;

    try {
      // 1. ทดสอบเมื่อ runtime มี performance.memory (Chromium/V8)
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: {
          usedJSHeapSize: 20 * 1024 * 1024,
          totalJSHeapSize: 40 * 1024 * 1024,
          jsHeapSizeLimit: 2048 * 1024 * 1024,
        },
      });

      const { rerender, unmount } = render(
        <PerformanceMonitor
          active={true}
          streaming={true}
          streamingContent="ส่วนที่ 1"
          messageCount={2}
          getActiveStreamCount={() => 1}
          getPendingThreadLoads={() => 0}
          sampleIntervalMs={250}
          onSample={(s) => samples.push(s)}
        />
      );

      expect(samples.length).toBeGreaterThanOrEqual(1);
      expect(samples[0].heapSupported).toBe(true);
      expect(samples[0].usedJSHeapMB).toBe(20);
      expect(samples[0].heapDeltaMB).toBe(0);
      expect(samples[0].leakWarning).toBe(false);

      // จำลองสตรีมมิ่งต่อเนื่องและหน่วยความจำเพิ่มขึ้นเกินเกณฑ์เตือน
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: {
          usedJSHeapSize: 72 * 1024 * 1024,
          totalJSHeapSize: 96 * 1024 * 1024,
          jsHeapSizeLimit: 2048 * 1024 * 1024,
        },
      });

      rerender(
        <PerformanceMonitor
          active={true}
          streaming={true}
          streamingContent={'ข้อมูลสตรีมมิ่งต่อเนื่อง '.repeat(20)}
          messageCount={3}
          getActiveStreamCount={() => 1}
          getPendingThreadLoads={() => 0}
          sampleIntervalMs={250}
          onSample={(s) => samples.push(s)}
        />
      );

      act(() => {
        vi.advanceTimersByTime(300);
      });

      const latest = samples[samples.length - 1];
      expect(latest.streamBufferBytes).toBeGreaterThan(200);
      expect(latest.heapDeltaMB).toBe(52);
      expect(latest.leakWarning).toBe(true);

      const countBeforeUnmount = samples.length;
      unmount();
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      // หลัง unmount ต้องไม่มี interval ค้างมาเรียก onSample อีก
      expect(samples.length).toBe(countBeforeUnmount);

      // 2. เมื่อ runtime ไม่มี performance.memory ต้องรายงาน heapSupported=false อย่างตรงไปตรงมา
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: undefined,
      });
      const fallbackSamples: MemorySnapshot[] = [];
      const fallbackView = render(
        <PerformanceMonitor
          active={true}
          streaming={false}
          streamingContent={null}
          messageCount={0}
          getActiveStreamCount={() => 0}
          getPendingThreadLoads={() => 0}
          onSample={(s) => fallbackSamples.push(s)}
        />
      );
      expect(fallbackSamples[0].heapSupported).toBe(false);
      expect(fallbackSamples[0].usedJSHeapMB).toBeNull();
      fallbackView.unmount();
    } finally {
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: origPerfMemory,
      });
      vi.useRealTimers();
    }
  });

  it('verifyThreadEffectCleanup และ useEffect ใน loadConversationThread ยกเลิกคำขอค้างเมื่อสลับห้องสนทนาและป้องกัน Memory Leak', async () => {
    // 1. ตรวจสอบหน่วยฟังก์ชัน verifyThreadEffectCleanup ทั้งกรณีสะอาดและกรณีรั่วไหล
    const cleanCtrl = new AbortController();
    cleanCtrl.abort();
    const cleanEntries: ThreadLoadEntry[] = [
      {
        requestId: 1,
        conversationId: 'c1',
        controller: cleanCtrl,
        cleanedUp: true,
        settled: false,
      },
    ];
    expect(verifyThreadEffectCleanup(cleanEntries)).toMatchObject({
      clean: true,
      abortedCount: 1,
      leakedRequestIds: [],
    });

    const leakedCtrl = new AbortController();
    const leakedEntries: ThreadLoadEntry[] = [
      {
        requestId: 2,
        conversationId: 'c2',
        controller: leakedCtrl,
        cleanedUp: true,
        settled: false,
      },
    ];
    expect(verifyThreadEffectCleanup(leakedEntries)).toMatchObject({
      clean: false,
      leakedRequestIds: [2],
    });

    // 2. ทดสอบระดับ App: สลับจาก c1 ไป c2 ระหว่างที่ GET /api/conversations/c1 ยังไม่ตอบกลับ
    const observedSignals: Record<string, AbortSignal | null | undefined> = {};
    let resolveC1!: (resp: Response) => void;
    const c1Deferred = new Promise<Response>((resolve) => {
      resolveC1 = resolve;
    });

    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: true, userCount: 1, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'GET /api/auth/me': () =>
        new Response(
          JSON.stringify({
            user: {
              id: 'u1',
              email: 'admin@zyrquen.local',
              display_name: 'ผู้ดูแล',
              role: 'admin',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 200 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [],
            counts: { triples: 0, checkpoints: 0, datasets: 0, pending_approvals: 0 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(
          JSON.stringify({
            conversations: [
              { id: 'c1', title: 'ห้องที่หนึ่ง', mode: 'auto', updated_at: '2026-11-24T00:00:00Z', message_count: 1 },
              { id: 'c2', title: 'ห้องที่สอง', mode: 'auto', updated_at: '2026-11-24T00:01:00Z', message_count: 1 },
            ],
          }),
          { status: 200 }
        ),
      'GET /api/conversations/c1': (init) => {
        observedSignals.c1 = init?.signal;
        return c1Deferred;
      },
      'GET /api/conversations/c2': (init) => {
        observedSignals.c2 = init?.signal;
        return new Response(
          JSON.stringify({
            conversation: {
              id: 'c2',
              title: 'ห้องที่สอง',
              mode: 'auto',
              updated_at: '2026-11-24T00:01:00Z',
              message_count: 1,
            },
            messages: [
              {
                id: 'm-c2',
                conversation_id: 'c2',
                role: 'assistant',
                content: 'เนื้อหาที่ถูกต้องของห้องที่สอง',
                mode: 'auto',
                trace_json: null,
                status: 'VERIFIED',
                created_at: '2026-11-24T00:01:00Z',
              },
            ],
          }),
          { status: 200 }
        );
      },
    });

    window.history.replaceState({}, '', '/?view=workspace&cid=c1');
    const view = render(<App />);

    await waitFor(() => {
      expect(observedSignals.c1).toBeDefined();
    });

    // เปิดรายการงานแล้วสลับไปห้อง c2 ทันทีก่อนที่ c1 จะตอบกลับ
    fireEvent.click(await screen.findByRole('button', { name: 'เปิดประวัติการสนทนา' }));
    const room2Buttons = await screen.findAllByText('ห้องที่สอง');
    fireEvent.click(room2Buttons[room2Buttons.length - 1]);

    expect(await screen.findByText('เนื้อหาที่ถูกต้องของห้องที่สอง')).toBeInTheDocument();
    expect(observedSignals.c1?.aborted).toBe(true);
    expect(observedSignals.c2?.aborted).toBe(false);

    // แม้ c1 จะตอบกลับมาทีหลัง ข้อมูลเก่าของ c1 ต้องไม่เขียนทับห้อง c2
    await act(async () => {
      resolveC1(
        new Response(
          JSON.stringify({
            conversation: {
              id: 'c1',
              title: 'ห้องที่หนึ่ง',
              mode: 'auto',
              updated_at: '2026-11-24T00:00:00Z',
              message_count: 1,
            },
            messages: [
              {
                id: 'm-c1-stale',
                conversation_id: 'c1',
                role: 'assistant',
                content: 'ข้อมูลเก่าที่ควรโดนยกเลิก',
                mode: 'auto',
                trace_json: null,
                status: 'VERIFIED',
                created_at: '2026-11-24T00:00:00Z',
              },
            ],
          }),
          { status: 200 }
        )
      );
      await Promise.resolve();
    });

    expect(screen.queryByText('ข้อมูลเก่าที่ควรโดนยกเลิก')).not.toBeInTheDocument();
    expect(screen.getByText('เนื้อหาที่ถูกต้องของห้องที่สอง')).toBeInTheDocument();
    const perfState = (
      window as unknown as {
        __ZYRQUEN_PERF_MONITOR__?: { cleanupVerification?: { clean: boolean } | null };
      }
    ).__ZYRQUEN_PERF_MONITOR__;
    expect(perfState?.cleanupVerification?.clean).toBe(true);

    // 3. ทดสอบการยกเลิก stream reader ใน streamConversationMessage
    const cancelSpy = vi.fn(async () => {});
    const encoder = new TextEncoder();
    let reads = 0;
    const mockBody = new ReadableStream<Uint8Array>({
      pull(controller) {
        reads += 1;
        if (reads === 1) {
          controller.enqueue(encoder.encode('event: delta\ndata: {"delta":"กำลังคิด..."}\n\n'));
        }
      },
      cancel: cancelSpy,
    });
    globalThis.fetch = vi.fn(async () => {
      return new Response(mockBody, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }) as unknown as typeof fetch;

    const streamAbort = new AbortController();
    const deltas: string[] = [];
    const streamPromise = streamConversationMessage('c2', {
      token: 't1',
      content: 'ทดสอบสตรีม',
      mode: 'auto',
      modelVariant: 'zyrquen-omega-v1',
      signal: streamAbort.signal,
      onDelta: (partial) => {
        deltas.push(partial);
        streamAbort.abort();
      },
    });

    await expect(streamPromise).rejects.toThrow();
    expect(deltas).toEqual(['กำลังคิด...']);
    expect(cancelSpy).toHaveBeenCalled();

    view.unmount();
  });

  it('P0: ปราศจากแพ็กเกจหรือการนำเข้า External LLM SDK (@google/genai, OpenAI, Anthropic) ในระบบจริง', () => {
    const rootDir = process.cwd();
    const pkg = JSON.parse(fs.readFileSync(path.join(rootDir, 'package.json'), 'utf8')) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const allDeps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
    expect(allDeps['@google/genai']).toBeUndefined();
    expect(allDeps['openai']).toBeUndefined();
    expect(allDeps['@anthropic-ai/sdk']).toBeUndefined();

    const sdkOrEndpointPattern =
      /@google\/genai|GoogleGenAI|@anthropic-ai\/sdk|from\s+['"]openai['"]|import\s+openai\b|import\s+anthropic\b|google\.generativeai|https:\/\/(?:api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com)/;

    const serverSource = fs.readFileSync(path.join(rootDir, 'server.ts'), 'utf8');
    expect(serverSource).not.toMatch(sdkOrEndpointPattern);

    const srcFiles = fs
      .readdirSync(path.join(rootDir, 'src'), { recursive: true })
      .map((f) => String(f))
      .filter((f) => /\.(ts|tsx)$/.test(f) && !f.startsWith('test/'));
    for (const rel of srcFiles) {
      const content = fs.readFileSync(path.join(rootDir, 'src', rel), 'utf8');
      expect(content, `External LLM reference in src/${rel}`).not.toMatch(sdkOrEndpointPattern);
    }

    const pyFiles = fs
      .readdirSync(path.join(rootDir, 'python_core'))
      .filter((f) => f.endsWith('.py'));
    for (const pyFile of pyFiles) {
      const content = fs.readFileSync(path.join(rootDir, 'python_core', pyFile), 'utf8');
      expect(content, `External LLM reference in python_core/${pyFile}`).not.toMatch(sdkOrEndpointPattern);
    }
  });

  it('P1: จัดการภารกิจอัตโนมัติ (DAG Nodes, Evidence, Resume, Cancel) ใน MemoryWorkflowsView', async () => {
    const initialMission = {
      id: 'm-101',
      goal: 'ค้นคว้าเรื่อง SQLite WAL',
      status: 'AWAITING_APPROVAL',
      capabilities_json: '{}',
      stages_json: '[]',
      knowledge_developed_json: '[]',
      research_summary_json: '{}',
      report_markdown: 'รอการอนุมัติ',
      external_models_used: 0,
      created_by: 'u1',
      created_at: '2026-11-24T00:00:00Z',
      updated_at: '2026-11-24T00:00:00Z',
    };
    const resumedMission = { ...initialMission, status: 'COMPLETED' };
    const cancelledMission = { ...initialMission, status: 'CANCELLED' };

    const calledUrls: string[] = [];
    mockFetch({
      'GET /api/knowledge': () => new Response(JSON.stringify({ triples: [] }), { status: 200 }),
      'GET /api/workflows': () => new Response(JSON.stringify({ groups: [], runs: [] }), { status: 200 }),
      'GET /api/autonomous/missions': () =>
        new Response(JSON.stringify({ missions: [initialMission] }), { status: 200 }),
      'GET /api/autonomous/missions/m-101': () => {
        calledUrls.push('GET /api/autonomous/missions/m-101');
        return new Response(
          JSON.stringify({
            mission: initialMission,
            nodes: [
              {
                id: 'nd-1',
                mission_id: 'm-101',
                task_id: 'node_goal_analysis',
                node_json: JSON.stringify({ title: 'วิเคราะห์เป้าหมาย', dependencies: [] }),
                execution_status: 'COMPLETED',
                attempt_count: 1,
                idempotency_key: 'k1',
                last_error: null,
                updated_at: '2026-11-24T00:00:00Z',
              },
              {
                id: 'nd-2',
                mission_id: 'm-101',
                task_id: 'node_research_discover',
                node_json: JSON.stringify({
                  title: 'ค้นคว้าข้ามแหล่ง',
                  dependencies: ['node_goal_analysis'],
                }),
                execution_status: 'AWAITING_APPROVAL',
                attempt_count: 1,
                idempotency_key: 'k2',
                last_error: null,
                updated_at: '2026-11-24T00:00:00Z',
              },
            ],
            evidence: [
              {
                id: 'ev-1',
                mission_id: 'm-101',
                node_id: 'node_research_discover',
                source_url: 'https://en.wikipedia.org/wiki/SQLite',
                provider: 'en.wikipedia.org',
                retrieved_at: '2026-11-24T00:00:00Z',
                trust_grade: 'CORROBORATED_MULTI_SOURCE',
                content_sha256: 'abc',
                extracted_claims_json: '[]',
              },
            ],
          }),
          { status: 200 }
        );
      },
      'POST /api/autonomous/missions/m-101/resume': () => {
        calledUrls.push('POST /api/autonomous/missions/m-101/resume');
        return new Response(
          JSON.stringify({ ok: true, mission: resumedMission, nodes: [], evidence: [] }),
          { status: 200 }
        );
      },
      'POST /api/autonomous/missions/m-102/cancel': () => {
        calledUrls.push('POST /api/autonomous/missions/m-102/cancel');
        return new Response(
          JSON.stringify({ ok: true, mission: { ...cancelledMission, id: 'm-102' } }),
          { status: 200 }
        );
      },
      'POST /api/autonomous/missions': () => {
        calledUrls.push('POST /api/autonomous/missions');
        return new Response(
          JSON.stringify({
            ok: true,
            mission: { ...initialMission, id: 'm-102', goal: 'คำนวณ 2 + 2', status: 'EXECUTING' },
            nodes: [],
            evidence: [],
          }),
          { status: 200 }
        );
      },
    });

    render(
      <MemoryWorkflowsView
        token="t-admin"
        user={{
          id: 'u1',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
      />
    );

    const missionsTab = await screen.findByRole('button', { name: /ภารกิจอัตโนมัติ \(1\)/ });
    fireEvent.click(missionsTab);

    fireEvent.click(await screen.findByText('ค้นคว้าเรื่อง SQLite WAL'));
    expect(await screen.findByText('node_research_discover')).toBeInTheDocument();
    expect(screen.getByText('https://en.wikipedia.org/wiki/SQLite')).toBeInTheDocument();
    expect(screen.getByText('CORROBORATED_MULTI_SOURCE')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /ดำเนินต่อ \(Resume\)/ }));
    await waitFor(() => {
      expect(calledUrls).toContain('POST /api/autonomous/missions/m-101/resume');
    });

    // Launch a new mission and cancel it
    const goalInput = screen.getByLabelText('เป้าหมายภารกิจอัตโนมัติ');
    fireEvent.change(goalInput, { target: { value: 'คำนวณ 2 + 2' } });
    fireEvent.click(screen.getByRole('button', { name: /เริ่มภารกิจอัตโนมัติ/ }));
    await waitFor(() => {
      expect(calledUrls).toContain('POST /api/autonomous/missions');
    });

    const cancelBtn = await screen.findByRole('button', { name: /ยกเลิกภารกิจ/ });
    fireEvent.click(cancelBtn);
    await waitFor(() => {
      expect(calledUrls).toContain('POST /api/autonomous/missions/m-102/cancel');
    });
  });

  it('P2: คัดกรองความจำ รันการทดลอง Neural Transformer และอนุมัติโปรโมต Checkpoint ใน SettingsView', async () => {
    const called: string[] = [];
    const expPending = {
      id: 'exp-1',
      hypothesis: 'ฝึก Native Transformer จาก Random Init (14,200 params)',
      dataset_id: 'ds-1',
      baseline_ckpt_id: null,
      candidate_ckpt_id: null,
      baseline_metrics_json: JSON.stringify({ initial_val_loss: 5.812 }),
      candidate_metrics_json: JSON.stringify({
        final_val_loss: 4.105,
        val_perplexity: 60.6,
        param_count: 14200,
      }),
      improved: 1,
      approval_status: 'PENDING_APPROVAL',
      approved_by: null,
      created_at: '2026-11-24T00:00:00Z',
    };

    mockFetch({
      'GET /api/developer/overview': () =>
        new Response(
          JSON.stringify({
            keys: [],
            datasets: [],
            checkpoints: [],
            evaluations: [],
            experiments: [expPending],
            usage: { total_requests: 0, avg_latency_ms: 0, daily_quota: 1000, recent: [] },
          }),
          { status: 200 }
        ),
      'GET /api/developer/tools': () =>
        new Response(JSON.stringify({ tools: [], invocations: [], workspace_files: [] }), {
          status: 200,
        }),
      'POST /api/developer/curate-corpus': () => {
        called.push('POST /api/developer/curate-corpus');
        return new Response(
          JSON.stringify({ ok: true, dataset: { id: 'ds-1', total_records: 8 } }),
          { status: 201 }
        );
      },
      'POST /api/developer/experiments': () => {
        called.push('POST /api/developer/experiments');
        return new Response(
          JSON.stringify({
            ok: true,
            experiment: expPending,
            improved: true,
            metrics: { final_val_loss: 4.105 },
          }),
          { status: 201 }
        );
      },
      'GET /api/admin/overview': () =>
        new Response(
          JSON.stringify({
            users: [],
            pending_runs: [],
            pending_tool_invocations: [],
            pending_experiments: [expPending],
            tools: [],
            audit_logs: [],
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 4096,
              mem_available_mb: 2048,
              disk_free_gb: 20,
              disk_total_gb: 50,
              sqlite_db_kb: 16,
            },
          }),
          { status: 200 }
        ),
      'POST /api/admin/experiments/exp-1/decide': () => {
        called.push('POST /api/admin/experiments/exp-1/decide');
        return new Response(
          JSON.stringify({ ok: true, experiment: { ...expPending, approval_status: 'APPROVED' } }),
          { status: 200 }
        );
      },
    });

    const devView = render(
      <SettingsView
        token="t-admin"
        user={{
          id: 'u-admin',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
        activeTab="developer"
        autoExpandTrace={false}
        defaultMode="auto"
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    expect(
      await screen.findByText(/การเรียนรู้จากความจำ & Neural Transformer \(P2\)/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/val_loss: 5\.8120 → 4\.1050/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'สร้างชุดข้อมูลจากความจำที่ยืนยันแล้ว' }));
    await waitFor(() => {
      expect(called).toContain('POST /api/developer/curate-corpus');
    });

    fireEvent.click(screen.getByRole('button', { name: 'รันการทดลอง Neural Transformer' }));
    await waitFor(() => {
      expect(called).toContain('POST /api/developer/experiments');
    });

    devView.unmount();

    render(
      <SettingsView
        token="t-admin"
        user={{
          id: 'u-admin',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
        activeTab="admin"
        autoExpandTrace={false}
        defaultMode="auto"
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    expect(
      await screen.findByText(/คิวอนุมัติ Neural Experiment \(Self-Improvement Gate\)/i)
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'อนุมัติโปรโมต Checkpoint' }));
    await waitFor(() => {
      expect(called).toContain('POST /api/admin/experiments/exp-1/decide');
    });
  });

  it('หน้าผู้ดูแลระบบแสดง Training Readiness Gate (BLOCKED เมื่อไม่มีชุดข้อมูลแม้ RAM/Disk ว่าง) และนำเข้าชุดข้อมูล 5+ รายการได้โดยตรง', async () => {
    let ingested = false;
    mockFetch({
      'GET /api/admin/overview': () =>
        new Response(
          JSON.stringify({
            users: [],
            pending_runs: [],
            pending_tool_invocations: [],
            pending_experiments: [],
            tools: [],
            audit_logs: [],
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 12288,
              mem_available_mb: 11574,
              disk_free_gb: 566.42,
              disk_total_gb: 566.74,
              sqlite_db_kb: 204,
            },
            training_readiness: {
              gate_status: ingested ? 'READY_FOR_TRAINING_GATE' : 'BLOCKED',
              datasets_total: ingested ? 1 : 0,
              clean_datasets: ingested ? 1 : 0,
              triples_total: 0,
              verified_triples: 0,
              experiments_total: 0,
              approved_experiments: 0,
              pending_experiments: 0,
              pending_training_runs: 0,
              checkpoints_total: 0,
              neural_checkpoints: 0,
              datasets: ingested
                ? [
                    {
                      id: 'ds-admin-1',
                      name: 'admin-real-corpus',
                      manifest_hash: 'abcd1234',
                      total_records: 5,
                      train_count: 3,
                      val_count: 1,
                      test_count: 1,
                      leakage_detected: 0,
                      status: 'READY',
                      created_at: '2026-11-24T00:00:00Z',
                    },
                  ]
                : [],
              checkpoints: [],
              experiments: [],
            },
          }),
          { status: 200 }
        ),
      'POST /api/developer/datasets': () => {
        ingested = true;
        return new Response(
          JSON.stringify({
            ok: true,
            deduplicated_removed: 0,
            dataset: {
              id: 'ds-admin-1',
              name: 'admin-real-corpus',
              manifest_hash: 'abcd1234',
              total_records: 5,
              train_count: 3,
              val_count: 1,
              test_count: 1,
              leakage_detected: 0,
              status: 'READY',
              created_at: '2026-11-24T00:00:00Z',
            },
          }),
          { status: 201 }
        );
      },
    });

    render(
      <SettingsView
        token="t-admin"
        user={{
          id: 'u-admin',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
        activeTab="admin"
        autoExpandTrace={false}
        defaultMode="auto"
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    expect(
      await screen.findByText(/ความพร้อมก่อนเริ่มฝึก Native Model \(Training Readiness Gate\)/i)
    ).toBeInTheDocument();
    expect(screen.getAllByText('BLOCKED').length).toBeGreaterThanOrEqual(1);

    fireEvent.change(screen.getByLabelText('ชื่อชุดข้อมูล Admin'), {
      target: { value: 'admin-real-corpus' },
    });
    fireEvent.change(screen.getByLabelText('เนื้อหาชุดข้อมูล Admin'), {
      target: {
        value: [
          'ประโยคจริงข้อที่หนึ่งสำหรับฝึกโมเดล',
          'ประโยคจริงข้อที่สองสำหรับตรวจสอบข้อมูล',
          'ประโยคจริงข้อที่สามสำหรับประเมินผล',
          'ประโยคจริงข้อที่สี่สำหรับการเรียนรู้ภายใน',
          'ประโยคจริงข้อที่ห้าสำหรับทดสอบความถูกต้อง',
        ].join('\n'),
      },
    });
    fireEvent.click(screen.getByRole('button', { name: 'นำเข้าชุดข้อมูลและตรวจ Data Leakage' }));

    expect(await screen.findByText('READY_FOR_TRAINING_GATE')).toBeInTheDocument();
    expect(await screen.findByText('admin-real-corpus')).toBeInTheDocument();
  });

  it('ZyrquenEmblem & zyrquen-logo.svg: แสดงโลโก้เรขาคณิตแบบเคลื่อนไหวและเร่งความเร็วเมื่อกำลังประมวลผล', () => {
    const svgFile = fs.readFileSync(path.join(process.cwd(), 'public', 'zyrquen-logo.svg'), 'utf8');
    expect(svgFile).toContain('<polygon');
    expect(svgFile).toContain('<animateTransform');
    expect(svgFile).toContain('<animateMotion');

    const { container } = render(
      <div>
        <ZyrquenEmblem size={28} />
        <ZyrquenEmblem size={44} active />
      </div>
    );

    const svgs = container.querySelectorAll('svg.zyrq-emblem-root');
    expect(svgs).toHaveLength(2);
    expect(svgs[0].getAttribute('data-animated')).toBe('true');
    expect(svgs[0].getAttribute('data-processing')).toBe('false');
    expect(svgs[1].getAttribute('data-processing')).toBe('true');
    expect(svgs[1].classList.contains('zyrq-emblem-active')).toBe(true);
    expect(container.querySelectorAll('.zyrq-emblem-trace')).toHaveLength(2);
    expect(container.querySelectorAll('.zyrq-emblem-orbit')).toHaveLength(2);
    expect(container.querySelectorAll('.zyrq-emblem-orbit-rev')).toHaveLength(2);
    expect(container.querySelectorAll('.zyrq-emblem-nucleus')).toHaveLength(2);
    expect(container.querySelectorAll('.zyrq-emblem-node-a')).toHaveLength(2);
    expect(container.querySelectorAll('.zyrq-emblem-node-b')).toHaveLength(2);

    const gradientIds = Array.from(container.querySelectorAll('linearGradient')).map((el) => el.id);
    expect(new Set(gradientIds).size).toBe(gradientIds.length);
  });

  it('แสดงผลและค้นหา Log การตัดสินใจ (Reasoning Trace) ย้อนหลังในหน้าเวิร์กโฟลว์ได้ครบถ้วน', async () => {
    const sampleTraces = [
      {
        id: 'rt-1',
        user_id: 'u-admin',
        conversation_id: 'conv-1',
        message_id: 'msg-1',
        prompt: 'คำนวณ (10 + 15) * 4',
        response_preview: '**ผลลัพธ์:** `100`',
        mode: 'math',
        model_version: 'zyrquen-omega-v1',
        status: 'VERIFIED',
        engine_path_json: JSON.stringify(['math_ast']),
        trace_json: JSON.stringify({
          engine_path: ['math_ast'],
          model_version: 'zyrquen-omega-v1',
          external_models_used: false,
          math: {
            expression: '(10 + 15) * 4',
            result: 100,
            steps: ['10 + 15 = 25', '25 * 4 = 100'],
          },
        }),
        latency_ms: 3.4,
        external_models_used: 0,
        created_at: '2026-11-24T10:00:00Z',
      },
      {
        id: 'rt-2',
        user_id: 'u-admin',
        conversation_id: 'conv-1',
        message_id: 'msg-2',
        prompt: 'อธิบายสิ่งที่ไม่เคยสอน',
        response_preview: '**สถานะ: ยังไม่ได้เรียนรู้ในแกนสมองภายใน (Not Learned)**',
        mode: 'auto',
        model_version: 'zyrquen-omega-v1',
        status: 'NOT_LEARNED',
        engine_path_json: JSON.stringify(['unlearned_boundary']),
        trace_json: JSON.stringify({
          engine_path: ['unlearned_boundary'],
          model_version: 'zyrquen-omega-v1',
          external_models_used: false,
        }),
        latency_ms: 2.1,
        external_models_used: 0,
        created_at: '2026-11-24T10:01:00Z',
      },
    ];

    mockFetch({
      'GET /api/knowledge': () => new Response(JSON.stringify({ triples: [] }), { status: 200 }),
      'GET /api/workflows': () =>
        new Response(
          JSON.stringify({ groups: [], runs: [], reasoning_traces: sampleTraces }),
          { status: 200 }
        ),
      'GET /api/autonomous/missions': () =>
        new Response(JSON.stringify({ missions: [] }), { status: 200 }),
    });

    render(
      <MemoryWorkflowsView
        token="t-admin"
        user={{
          id: 'u-admin',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
      />
    );

    fireEvent.click(await screen.findByRole('button', { name: /ระบบเวิร์กโฟลว์/i }));

    expect(
      await screen.findByText(/บันทึกการตัดสินใจย้อนหลัง \(Reasoning Trace\)/i)
    ).toBeInTheDocument();
    expect(screen.getAllByText('คำนวณ (10 + 15) * 4').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('math_ast')).toBeInTheDocument();
    expect(screen.getByText('10 + 15 = 25')).toBeInTheDocument();
    expect(screen.getByText('25 * 4 = 100')).toBeInTheDocument();

    // Filter by NOT_LEARNED
    fireEvent.change(screen.getByLabelText('กรองสถานะ Reasoning Trace'), {
      target: { value: 'NOT_LEARNED' },
    });
    expect(screen.queryByText('math_ast')).not.toBeInTheDocument();
    expect(screen.getByText('unlearned_boundary')).toBeInTheDocument();
  });

  it('แสดงบันทึกเวลาทำงานราย Task และ Bottleneck Profiler ใน Reasoning Trace และแสดงกราฟ Recharts ในแท็บความเสถียรเนทีฟของผู้ดูแลระบบ', async () => {
    const timedTrace = {
      id: 'rt-timed-1',
      user_id: 'u-admin',
      conversation_id: 'conv-1',
      message_id: 'msg-timed-1',
      prompt: 'คำนวณ (12 + 8) * 3',
      response_preview: '**ผลลัพธ์:** `60`',
      mode: 'auto',
      model_version: 'zyrquen-omega-v1',
      status: 'VERIFIED',
      engine_path_json: JSON.stringify(['math_ast']),
      trace_json: JSON.stringify({
        engine_path: ['math_ast'],
        model_version: 'zyrquen-omega-v1',
        latency_ms: 14.8,
        external_models_used: false,
        task_timings: [
          { order: 1, task: 'autonomous_mission_detect', duration_ms: 0.4, matched: false, status: 'SKIPPED' },
          { order: 2, task: 'math_ast', duration_ms: 14.4, matched: true, status: 'VERIFIED' },
        ],
        bottleneck_task: { task: 'math_ast', duration_ms: 14.4, share_pct: 97.3 },
      }),
      latency_ms: 14.8,
      external_models_used: 0,
      created_at: '2026-11-24T10:05:00Z',
    };

    mockFetch({
      'GET /api/knowledge': () => new Response(JSON.stringify({ triples: [] }), { status: 200 }),
      'GET /api/workflows': () =>
        new Response(
          JSON.stringify({ groups: [], runs: [], reasoning_traces: [timedTrace] }),
          { status: 200 }
        ),
      'GET /api/autonomous/missions': () =>
        new Response(JSON.stringify({ missions: [] }), { status: 200 }),
      'GET /api/admin/overview': () =>
        new Response(
          JSON.stringify({
            users: [],
            pending_runs: [],
            pending_tool_invocations: [],
            pending_experiments: [],
            tools: [],
            audit_logs: [],
            reasoning_traces: [timedTrace],
            recent_api_usage: [],
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 4096,
              mem_available_mb: 2048,
              disk_free_gb: 20,
              disk_total_gb: 50,
              sqlite_db_kb: 32,
            },
          }),
          { status: 200 }
        ),
    });

    const memView = render(
      <MemoryWorkflowsView
        token="t-admin"
        user={{
          id: 'u-admin',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
      />
    );

    fireEvent.click(await screen.findByRole('button', { name: /ระบบเวิร์กโฟลว์/i }));
    expect(await screen.findByText(/Bottleneck: math_ast \(14\.4 ms\)/i)).toBeInTheDocument();
    expect(screen.getByText(/บันทึกเวลาทำงานแยกราย Task/i)).toBeInTheDocument();
    expect(screen.getByText('autonomous_mission_detect')).toBeInTheDocument();
    memView.unmount();

    const onCapture = vi.fn();
    render(
      <SettingsView
        token="t-admin"
        user={{
          id: 'u-admin',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-24T00:00:00Z',
        }}
        activeTab="admin"
        autoExpandTrace={false}
        defaultMode="auto"
        perfSamples={[
          {
            timestamp: 1700000000000,
            heapSupported: true,
            usedJSHeapMB: 24.5,
            totalJSHeapMB: 48,
            jsHeapLimitMB: 2048,
            streamBufferBytes: 1024,
            messageCount: 2,
            activeStreamCount: 0,
            pendingThreadLoads: 0,
            heapDeltaMB: 0,
            leakWarning: false,
          },
          {
            timestamp: 1700000002000,
            heapSupported: true,
            usedJSHeapMB: 26.2,
            totalJSHeapMB: 48,
            jsHeapLimitMB: 2048,
            streamBufferBytes: 2048,
            messageCount: 4,
            activeStreamCount: 1,
            pendingThreadLoads: 0,
            heapDeltaMB: 1.7,
            leakWarning: false,
          },
        ]}
        clientLatencies={[
          {
            timestamp: 1700000002000,
            label: 'คำนวณ (12 + 8) * 3',
            endpoint: '/api/conversations/conv-1/stream',
            latencyMs: 19.5,
            status: 'VERIFIED',
          },
        ]}
        cleanupVerification={{
          clean: true,
          activeCount: 0,
          abortedCount: 1,
          leakedRequestIds: [],
          checkedAt: 1700000002000,
        }}
        onCapturePerfSample={onCapture}
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    const stabilityTab = await screen.findByRole('tab', {
      name: /ความเสถียรเนทีฟ \(PerformanceMonitor\)/i,
    });
    fireEvent.click(stabilityTab);

    expect(
      await screen.findByText(
        /ความเสถียรสภาพแวดล้อมเนทีฟ \(PerformanceMonitor & Bottleneck Telemetry\)/i,
        undefined,
        { timeout: 5000 }
      )
    ).toBeInTheDocument();
    expect(screen.getByText('26.2 MB')).toBeInTheDocument();
    expect(screen.getByText('STABLE')).toBeInTheDocument();
    expect(screen.getByTestId('recharts-heap-chart')).toBeInTheDocument();
    expect(screen.getByTestId('recharts-latency-chart')).toBeInTheDocument();
    expect(screen.getByTestId('recharts-bottleneck-chart')).toBeInTheDocument();
    expect(screen.getAllByText('math_ast').length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole('button', { name: 'สุ่มเก็บเมตริกทันที' }));
    expect(onCapture).toHaveBeenCalledTimes(1);
  });

  it('แสดงผล TemporalIntelligenceCore, SpacetimeFabric, IntersectionObserver pause และสลับธีม Neural Aurora Dark/Light', () => {
    window.localStorage.removeItem('zyrquen_theme');
    document.documentElement.classList.remove('light', 'dark');

    // Mock IntersectionObserver to verify offscreen animation pause
    let triggerIntersect: ((entries: IntersectionObserverEntry[]) => void) | null = null;
    const prevIO = globalThis.IntersectionObserver;
    globalThis.IntersectionObserver = class MockIO {
      constructor(cb: IntersectionObserverCallback) {
        triggerIntersect = (entries) => cb(entries, this as unknown as IntersectionObserver);
      }
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
      takeRecords = () => [];
      root = null;
      rootMargin = '';
      thresholds = [];
    } as unknown as typeof IntersectionObserver;

    try {
      const { container, rerender } = render(
        <>
          <TemporalIntelligenceCore variant="prominent" size={148} active />
          <TemporalIntelligenceCore variant="ambient" size={40} />
          <SpacetimeFabric density="expansive" />
        </>
      );

      const cores = container.querySelectorAll('[data-temporal-core]');
      expect(cores).toHaveLength(2);
      expect(cores[0]).toHaveAttribute('data-temporal-core', 'prominent');
      expect(cores[0]).toHaveAttribute('data-active', 'true');
      expect(cores[0].className).toContain('zyrq-temporal-active');
      expect(cores[1]).toHaveAttribute('data-temporal-core', 'ambient');

      // Check all 6 animation classes & unique SVG defs IDs
      expect(container.querySelector('.zyrq-temporal-pulse')).toBeTruthy();
      expect(container.querySelector('.zyrq-temporal-ring-cw')).toBeTruthy();
      expect(container.querySelector('.zyrq-temporal-ring-ccw')).toBeTruthy();
      expect(container.querySelector('.zyrq-temporal-energy-path')).toBeTruthy();
      expect(container.querySelector('.zyrq-spacetime-warp')).toBeTruthy();
      expect(container.querySelector('.zyrq-temporal-particle-track-a')).toBeTruthy();

      const gradIds = Array.from(container.querySelectorAll('linearGradient[id]')).map((el) =>
        el.getAttribute('id')
      );
      expect(new Set(gradIds).size).toBe(gradIds.length);

      const fabric = container.querySelector('[data-spacetime-fabric="expansive"]');
      expect(fabric).toBeTruthy();
      expect(fabric).toHaveAttribute('data-offscreen', 'false');

      act(() => {
        triggerIntersect?.([{ isIntersecting: false } as IntersectionObserverEntry]);
      });
      expect(fabric).toHaveAttribute('data-offscreen', 'true');

      // Switch to compact AuthGate mode on สมัครสมาชิก & test Light/Dark theme persistence
      rerender(
        <AuthGate
          authStatus={{ initialized: true, userCount: 1, envPasscodeConfigured: false }}
          onAuthenticated={vi.fn()}
        />
      );
      expect(document.querySelector('[data-temporal-core="prominent"]')).toBeTruthy();
      fireEvent.click(screen.getByRole('button', { name: 'สมัครสมาชิก' }));
      expect(document.querySelector('[data-temporal-core="compact"]')).toBeTruthy();

      const toggleBtn = screen.getByRole('button', { name: /เปลี่ยนเป็นโหมดสว่าง/i });
      fireEvent.click(toggleBtn);
      expect(document.documentElement.classList.contains('light')).toBe(true);
      expect(document.documentElement.dataset.theme).toBe('light');
      expect(window.localStorage.getItem('zyrquen_theme')).toBe('light');

      const backToDarkBtn = screen.getByRole('button', { name: /เปลี่ยนเป็นโหมดมืด/i });
      fireEvent.click(backToDarkBtn);
      expect(document.documentElement.classList.contains('dark')).toBe(true);
      expect(document.documentElement.dataset.theme).toBe('dark');
      expect(window.localStorage.getItem('zyrquen_theme')).toBe('dark');
    } finally {
      globalThis.IntersectionObserver = prevIO;
    }
  });

  it('ปุ่มคัดลอกใน WorkspaceView คัดลอกข้อความไทย/อังกฤษ/หลายบรรทัด/ยาว, กรอง JSON ภายใน, รองรับ fallback มือถือ และจัดการ error เมื่อคลิปบอร์ดถูกบล็อก', async () => {
    const { WorkspaceView } = await import('../components/WorkspaceView');
    const { sanitizeAssistantDisplayContent, toPlainAssistantCopyText } = await import(
      '../components/SafeMessageText'
    );

    const origClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const origExecCommand = (document as unknown as { execCommand?: unknown }).execCommand;
    const copiedTexts: string[] = [];

    try {
      // 1. Mock modern Clipboard API
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: vi.fn(async (txt: string) => {
            copiedTexts.push(txt);
          }),
        },
      });

      const longBody = Array.from({ length: 24 }, (_, idx) => `บรรทัดที่ ${idx + 1}: ข้อมูลยืนยันต่อเนื่อง`).join('\n');
      const leakedJsonMsg = JSON.stringify({
        response: 'สวัสดีครับ ยินดีต้อนรับ มีอะไรให้ช่วยวันนี้ครับ',
        cognitive_pipeline: { stage: 'internal' },
        inference_gap: 'none',
        epistemic_state: 'UNDERSTOOD',
        model_weights_changed: false,
      });

      const messages = [
        {
          id: 'm-thai',
          conversation_id: 'c-copy',
          role: 'assistant' as const,
          content: 'สวัสดีครับ **ZYRQUEN** พร้อมช่วยเหลือ\n> ข้อความอ้างอิง\n- รายการที่ `1`',
          mode: 'auto' as const,
          trace_json: JSON.stringify({ engine_path: ['cognitive_pipeline'], latency_ms: 4.2 }),
          status: 'UNDERSTOOD',
          created_at: '2026-11-25T00:00:00Z',
        },
        {
          id: 'm-en',
          conversation_id: 'c-copy',
          role: 'assistant' as const,
          content: 'Hello! Native reasoning check passed with 100% deterministic verification.',
          mode: 'auto' as const,
          trace_json: null,
          status: 'UNDERSTOOD',
          created_at: '2026-11-25T00:01:00Z',
        },
        {
          id: 'm-long',
          conversation_id: 'c-copy',
          role: 'assistant' as const,
          content: longBody,
          mode: 'auto' as const,
          trace_json: null,
          status: 'VERIFIED',
          created_at: '2026-11-25T00:02:00Z',
        },
        {
          id: 'm-json-leak',
          conversation_id: 'c-copy',
          role: 'assistant' as const,
          content: leakedJsonMsg,
          mode: 'auto' as const,
          trace_json: null,
          status: 'UNDERSTOOD',
          created_at: '2026-11-25T00:03:00Z',
        },
      ];

      render(
        <WorkspaceView
          token="tok-copy"
          conversations={[]}
          activeConversationId="c-copy"
          activeTitle="ทดสอบปุ่มคัดลอก"
          messages={messages}
          loadingThread={false}
          sending={false}
          error={null}
          autoExpandTrace={false}
          defaultMode="auto"
          onSelectConversation={vi.fn()}
          onNewConversation={vi.fn()}
          onDeleteConversation={vi.fn()}
          onSendMessage={vi.fn(async () => {})}
        />
      );

      // Assistant identity must display "ZYRQUEN" on every assistant card and never expose raw internal JSON fields or Developer Trace in Chat UI
      expect(screen.getAllByText('ZYRQUEN').length).toBeGreaterThanOrEqual(4);
      expect(screen.queryByText(/cognitive_pipeline/)).not.toBeInTheDocument();
      expect(screen.queryByText(/model_weights_changed/)).not.toBeInTheDocument();
      expect(screen.queryByText('Developer Trace')).not.toBeInTheDocument();
      expect(screen.queryByText(/Tool Registry/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Toolkit Catalog/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Capability Library/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Execution Engine Dashboard/i)).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'ตั้งค่าโมเดลและพื้นที่ทำงาน' })).not.toBeInTheDocument();
      expect(screen.getByText('สวัสดีครับ ยินดีต้อนรับ มีอะไรให้ช่วยวันนี้ครับ')).toBeInTheDocument();

      const copyButtons = screen.getAllByRole('button', { name: 'คัดลอกข้อความตอบกลับ' });
      expect(copyButtons).toHaveLength(4);

      // Copy Thai + multiline + Markdown-stripped plain text
      fireEvent.click(copyButtons[0]);
      expect(await screen.findByText('คัดลอกแล้ว')).toBeInTheDocument();
      expect(copiedTexts[0]).toBe('สวัสดีครับ ZYRQUEN พร้อมช่วยเหลือ\nข้อความอ้างอิง\n- รายการที่ 1');

      // Copy English
      fireEvent.click(copyButtons[1]);
      await waitFor(() => expect(copiedTexts).toHaveLength(2));
      expect(copiedTexts[1]).toBe('Hello! Native reasoning check passed with 100% deterministic verification.');

      // Copy long text without truncation
      fireEvent.click(copyButtons[2]);
      await waitFor(() => expect(copiedTexts).toHaveLength(3));
      expect(copiedTexts[2]).toBe(longBody);

      // Copy sanitized message from leaked JSON without internal keys
      fireEvent.click(copyButtons[3]);
      await waitFor(() => expect(copiedTexts).toHaveLength(4));
      expect(copiedTexts[3]).toBe('สวัสดีครับ ยินดีต้อนรับ มีอะไรให้ช่วยวันนี้ครับ');

      // Verify sanitize/copy utility handles mixed diagnostic lines without discarding useful text
      const mixed = 'คำตอบจริงของระบบ\ncognitive_pipeline: {"a":1}\ninference_gap: none\nบรรทัดที่สอง';
      expect(sanitizeAssistantDisplayContent(mixed)).toBe('คำตอบจริงของระบบ\nบรรทัดที่สอง');
      expect(toPlainAssistantCopyText(mixed)).toBe('คำตอบจริงของระบบ\nบรรทัดที่สอง');

      // 2. Android/legacy fallback when navigator.clipboard is undefined
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: undefined,
      });
      const execSpy = vi.fn(() => true);
      (document as unknown as { execCommand?: unknown }).execCommand = execSpy;

      fireEvent.click(copyButtons[0]);
      await waitFor(() => {
        expect(execSpy).toHaveBeenCalledWith('copy');
      });

      // 3. Graceful failure handling when clipboard API & execCommand both fail
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: vi.fn(async () => {
            throw new Error('Permission denied');
          }),
        },
      });
      (document as unknown as { execCommand?: unknown }).execCommand = vi.fn(() => false);

      fireEvent.click(copyButtons[1]);
      expect(await screen.findByText(/คัดลอกไม่สำเร็จ/)).toBeInTheDocument();
    } finally {
      if (origClipboard) {
        Object.defineProperty(navigator, 'clipboard', origClipboard);
      } else {
        delete (navigator as unknown as { clipboard?: unknown }).clipboard;
      }
      (document as unknown as { execCommand?: unknown }).execCommand = origExecCommand;
    }
  });

  it('กู้คืนเซสชันอัตโนมัติเมื่อ cid ใน URL คืนค่า 404 โดยไม่แสดง Conversation not found', async () => {
    let createdCidCount = 0;
    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: true, userCount: 1, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'GET /api/auth/me': () =>
        new Response(
          JSON.stringify({
            user: {
              id: 'u1',
              email: 'admin@zyrquen.local',
              display_name: 'ผู้ดูแล',
              role: 'admin',
              created_at: '2026-11-25T00:00:00Z',
            },
          }),
          { status: 200 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: [],
            counts: { triples: 0, checkpoints: 0, datasets: 0, pending_approvals: 0 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(JSON.stringify({ conversations: [] }), { status: 200 }),
      'GET /api/conversations/stale-cid-404': () =>
        new Response(JSON.stringify({ error: 'Conversation not found' }), { status: 404 }),
      'POST /api/conversations': () => {
        createdCidCount += 1;
        return new Response(
          JSON.stringify({
            conversation: {
              id: 'fresh-cid-1',
              title: 'สวัสดี',
              mode: 'auto',
              updated_at: '2026-11-25T00:00:00Z',
            },
          }),
          { status: 201 }
        );
      },
      'POST /api/conversations/fresh-cid-1/stream': () =>
        new Response(
          JSON.stringify({
            title: 'สวัสดี',
            modelVersion: 'zyrquen-omega-v1',
            user_message: {
              id: 'u-hi',
              conversation_id: 'fresh-cid-1',
              role: 'user',
              content: 'สวัสดี',
              mode: 'auto',
              trace_json: null,
              status: 'USER',
              created_at: '2026-11-25T00:00:00Z',
            },
            assistant_message: {
              id: 'a-hi',
              conversation_id: 'fresh-cid-1',
              role: 'assistant',
              content: 'สวัสดีครับ ยินดีต้อนรับ มีอะไรให้ช่วยวันนี้ครับ',
              mode: 'auto',
              trace_json: JSON.stringify({ engine_path: ['cognitive_pipeline'], latency_ms: 2.1 }),
              status: 'VERIFIED',
              created_at: '2026-11-25T00:00:01Z',
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        ),
    });

    window.history.replaceState({}, '', '/?view=workspace&cid=stale-cid-404');
    render(<App />);

    // Must recover cleanly into fresh empty workspace without surfacing "Conversation not found"
    expect(await screen.findByText('พื้นที่ดำเนินงาน ZYRQUEN')).toBeInTheDocument();
    expect(screen.queryByText(/Conversation not found/i)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.search).not.toContain('stale-cid-404');
    });

    // Sending a message afterwards creates a fresh session and displays natural Thai greeting
    const composer = screen.getByLabelText('ช่องพิมพ์คำสั่งงาน');
    fireEvent.change(composer, { target: { value: 'สวัสดี' } });
    fireEvent.keyDown(composer, { key: 'Enter', shiftKey: false });

    expect(
      await screen.findByText('สวัสดีครับ ยินดีต้อนรับ มีอะไรให้ช่วยวันนี้ครับ')
    ).toBeInTheDocument();
    expect(createdCidCount).toBe(1);
    expect(screen.queryByText(/Conversation not found/i)).not.toBeInTheDocument();
  });

  it('Universal Copy: คัดลอกโค้ดหลายบรรทัดพร้อมการเยื้อง, ตาราง TSV, รายงานภารกิจ/เวิร์กโฟลว์/เสถียรภาพ และคัดกรองข้อมูลลับไม่ให้หลุด', async () => {
    const { WorkspaceView } = await import('../components/WorkspaceView');
    const { HomeView } = await import('../components/HomeView');
    const { AdminStabilityPanel } = await import('../components/AdminStabilityPanel');
    const { serializeTableToTsv, redactSensitiveData } = await import('../lib/clipboard');

    const origClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const copiedTexts: string[] = [];

    try {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: vi.fn(async (txt: string) => {
            copiedTexts.push(txt);
          }),
        },
      });

      const pythonCode = [
        'def compute_mean(values):',
        '    # คอมเมนต์ต้องอยู่ครบไม่ถูกตัด',
        '    if not values:',
        '        return 0.0',
        '    return sum(values) / len(values)',
      ].join('\n');

      const mdMessage = [
        'สรุปผลวิเคราะห์โครงสร้างโค้ดและตารางข้อมูล:',
        '',
        '```python',
        pythonCode,
        '```',
        '',
        '| โมดูล | สถานะ | หมายเหตุ |',
        '| --- | --- | --- |',
        '| dataset_leakage_detector | VERIFIED | ตรวจแฮชสมบูรณ์ |',
        '| checkpoint_tracker | VERIFIED | ไม่เขียนทับของเดิม |',
      ].join('\n');

      const secretLeakedTrace = JSON.stringify({
        engine_path: ['tools_engine'],
        latency_ms: 8.4,
        token: 'secret-jwt-should-not-copy',
        api_key: 'zyrq_secret_12345',
        password_hash: 'hash_xyz',
      });

      // 1. WorkspaceView: Code block (with indentation + # comment), Markdown TSV Table, Redacted Developer Trace, and Error banner
      const ws = render(
        <WorkspaceView
          token="tok-univ"
          conversations={[]}
          activeConversationId="c-univ"
          activeTitle="ทดสอบ Universal Copy"
          messages={[
            {
              id: 'm-code-table',
              conversation_id: 'c-univ',
              role: 'assistant',
              content: mdMessage,
              mode: 'auto',
              trace_json: secretLeakedTrace,
              status: 'VERIFIED',
              created_at: '2026-11-25T00:00:00Z',
            },
          ]}
          loadingThread={false}
          sending={false}
          error="การเชื่อมต่อฐานข้อมูลขัดข้อง (SQLITE_BUSY)"
          autoExpandTrace={true}
          defaultMode="auto"
          onSelectConversation={vi.fn()}
          onNewConversation={vi.fn()}
          onDeleteConversation={vi.fn()}
          onSendMessage={vi.fn(async () => {})}
        />
      );

      // Copy code block preserving exact indentation and `#` comment without fences/line numbers
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกโค้ด' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(1));
      expect(copiedTexts[0]).toBe(pythonCode);
      expect(copiedTexts[0]).not.toContain('```');

      // Copy Markdown table as Tab-Separated Values (TSV)
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกตาราง' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(2));
      expect(copiedTexts[1]).toBe(
        serializeTableToTsv(
          ['โมดูล', 'สถานะ', 'หมายเหตุ'],
          [
            ['dataset_leakage_detector', 'VERIFIED', 'ตรวจแฮชสมบูรณ์'],
            ['checkpoint_tracker', 'VERIFIED', 'ไม่เขียนทับของเดิม'],
          ]
        )
      );
      expect(copiedTexts[1]).toContain('\t');

      // Developer Trace panel must NOT clutter Chat Workspace; verify secret redaction directly & full message copy
      expect(screen.queryByRole('button', { name: 'คัดลอก Developer Trace' })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกข้อความตอบกลับ' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(3));
      expect(copiedTexts[2]).toContain('สรุปผลวิเคราะห์โครงสร้างโค้ดและตารางข้อมูล:');

      const redactedTraceJson = JSON.stringify(redactSensitiveData(JSON.parse(secretLeakedTrace)));
      expect(redactedTraceJson).toContain('"tools_engine"');
      expect(redactedTraceJson).not.toContain('secret-jwt-should-not-copy');
      expect(redactedTraceJson).not.toContain('zyrq_secret_12345');
      expect(redactedTraceJson).not.toContain('hash_xyz');

      // Copy Error Alert
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกข้อความข้อผิดพลาด' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(4));
      expect(copiedTexts[3]).toBe('การเชื่อมต่อฐานข้อมูลขัดข้อง (SQLITE_BUSY)');

      ws.unmount();

      // 2. HomeView: Project Status Summary Copy (TSV metrics)
      const hv = render(
        <HomeView
          user={{
            id: 'u1',
            email: 'admin@zyrquen.local',
            display_name: 'Admin',
            role: 'admin',
            created_at: '2026-11-25T00:00:00Z',
          }}
          homeSummary={{
            recent_conversations: [],
            counts: { triples: 12, checkpoints: 2, datasets: 3, pending_approvals: 1 },
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 4096,
              mem_available_mb: 2048,
              disk_free_gb: 20,
              disk_total_gb: 50,
              sqlite_db_kb: 16,
            },
          }}
          nativeReady={true}
          loading={false}
          error={null}
          onStartPrompt={vi.fn()}
          onOpenConversation={vi.fn()}
          onNavigate={vi.fn()}
          onRetry={vi.fn()}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกสรุปสถานะระบบ' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(5));
      expect(copiedTexts[4]).toContain('Active Projects\t0');
      expect(copiedTexts[4]).toContain('Datasets\t3');
      expect(copiedTexts[4]).toContain('Pending Gate Approvals\t1');
      hv.unmount();

      // 3. AdminStabilityPanel: Bottleneck TSV table & Stability Report Copy
      const asp = render(
        <AdminStabilityPanel
          adminData={{
            users: [],
            pending_runs: [],
            audit_logs: [],
            reasoning_traces: [
              {
                id: 'rt-1',
                conversation_id: 'c1',
                message_id: null,
                user_id: 'u1',
                prompt: 'ทดสอบคอขวด',
                response_preview: 'ผ่าน',
                status: 'VERIFIED',
                mode: 'auto',
                model_version: 'zyrquen-omega-v1',
                engine_path_json: '["cognitive_pipeline"]',
                trace_json: JSON.stringify({
                  task_timings: [
                    { task: 'cognitive_pipeline', order: 1, duration_ms: 4.5, matched: true, status: 'VERIFIED' },
                  ],
                }),
                latency_ms: 4.5,
                external_models_used: 0,
                created_at: '2026-11-25T00:00:00Z',
              },
            ],
            recent_api_usage: [],
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 4096,
              mem_available_mb: 2048,
              disk_free_gb: 20,
              disk_total_gb: 50,
              sqlite_db_kb: 16,
            },
          }}
          perfSamples={[]}
          clientLatencies={[]}
          cleanupVerification={null}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกตาราง Bottleneck' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(6));
      expect(copiedTexts[5]).toContain('Task\tRuns\tAvg (ms)\tMax (ms)');
      expect(copiedTexts[5]).toContain('cognitive_pipeline\t1\t4.5\t4.5');
      asp.unmount();

      // 4. MemoryWorkflowsView: Mission Report Copy (Goal + DAG Nodes TSV)
      mockFetch({
        'GET /api/knowledge': () => new Response(JSON.stringify({ triples: [] }), { status: 200 }),
        'GET /api/workflows': () =>
          new Response(
            JSON.stringify({
              groups: [],
              runs: [
                {
                  id: 'wr-1',
                  group_id: 'system_ops',
                  status: 'PASS',
                  summary: 'ระบบและฐานข้อมูล SQLite พร้อมทำงาน',
                  stages_json: JSON.stringify([{ stage: 'health_check', status: 'PASS', detail: 'OK' }]),
                  created_at: '2026-11-25T00:00:00Z',
                },
              ],
              reasoning_traces: [],
            }),
            { status: 200 }
          ),
        'GET /api/autonomous/missions': () =>
          new Response(
            JSON.stringify({
              missions: [
                {
                  id: 'ms-copy-1',
                  user_id: 'u1',
                  goal: 'ตรวจสอบความพร้อมชุดข้อมูลในเวิร์กสเปซ',
                  status: 'COMPLETED',
                  created_at: '2026-11-25T00:00:00Z',
                  updated_at: '2026-11-25T00:00:05Z',
                },
              ],
            }),
            { status: 200 }
          ),
        'GET /api/autonomous/missions/ms-copy-1': () =>
          new Response(
            JSON.stringify({
              mission: {
                id: 'ms-copy-1',
                user_id: 'u1',
                goal: 'ตรวจสอบความพร้อมชุดข้อมูลในเวิร์กสเปซ',
                status: 'COMPLETED',
                created_at: '2026-11-25T00:00:00Z',
                updated_at: '2026-11-25T00:00:05Z',
              },
              nodes: [
                {
                  id: 'nd-1',
                  mission_id: 'ms-copy-1',
                  task_id: 'workspace_artifact_inspect',
                  execution_status: 'COMPLETED',
                  attempt_count: 1,
                  node_json: JSON.stringify({ title: 'ตรวจสอบไฟล์ชุดข้อมูล' }),
                  last_error: null,
                },
              ],
              evidence: [],
            }),
            { status: 200 }
          ),
      });

      const mw = render(
        <MemoryWorkflowsView
          token="tok-univ"
          user={{
            id: 'u1',
            email: 'admin@zyrquen.local',
            display_name: 'Admin',
            role: 'admin',
            created_at: '2026-11-25T00:00:00Z',
          }}
        />
      );
      fireEvent.click(await screen.findByRole('button', { name: /ภารกิจอัตโนมัติ/ }));
      fireEvent.click(await screen.findByText('ตรวจสอบความพร้อมชุดข้อมูลในเวิร์กสเปซ'));
      const copyMissionBtn = await screen.findByRole('button', { name: 'คัดลอกรายงานภารกิจ' });
      fireEvent.click(copyMissionBtn);
      await waitFor(() => expect(copiedTexts).toHaveLength(7));
      expect(copiedTexts[6]).toContain('ตรวจสอบความพร้อมชุดข้อมูลในเวิร์กสเปซ');
      expect(copiedTexts[6]).toContain('workspace_artifact_inspect\tCOMPLETED\t1');
      mw.unmount();
    } finally {
      if (origClipboard) {
        Object.defineProperty(navigator, 'clipboard', origClipboard);
      } else {
        delete (navigator as unknown as { clipboard?: unknown }).clipboard;
      }
    }
  });

  it('นำทาง 6 แท็บ Workspace (ภาพรวม, โปรเจกต์, งานของฉัน, สร้างงาน, วิเคราะห์, คลังผลงาน) และใช้งานจริงผ่าน API ได้ครบถ้วน', async () => {
    const workspaceFilesState = [
      {
        name: 'architecture-plan.md',
        size_bytes: 256,
        modified_at: '2026-11-25T01:00:00Z',
      },
    ];
    const conversationsState = [
      {
        id: 'proj-1',
        title: 'โปรเจกต์วิเคราะห์ระบบ',
        mode: 'auto',
        updated_at: '2026-11-25T01:00:00Z',
        message_count: 2,
      },
    ];

    mockFetch({
      'GET /api/auth/status': () =>
        new Response(
          JSON.stringify({ initialized: true, userCount: 1, envPasscodeConfigured: false }),
          { status: 200 }
        ),
      'GET /api/health': () =>
        new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 }),
      'GET /api/auth/me': () =>
        new Response(
          JSON.stringify({
            user: {
              id: 'u1',
              email: 'admin@zyrquen.local',
              display_name: 'วิศวกรหลัก',
              role: 'admin',
              created_at: '2026-11-25T00:00:00Z',
            },
          }),
          { status: 200 }
        ),
      'GET /api/home': () =>
        new Response(
          JSON.stringify({
            recent_conversations: conversationsState,
            recent_missions: [
              {
                id: 'm-ws-1',
                goal: 'วิเคราะห์โครงสร้างโมดูลระบบ',
                status: 'COMPLETED',
                created_at: '2026-11-25T01:00:00Z',
                updated_at: '2026-11-25T01:01:00Z',
              },
            ],
            counts: { triples: 5, checkpoints: 1, datasets: 2, pending_approvals: 0, missions: 1 },
            system: { python_version: '3.11.2' },
          }),
          { status: 200 }
        ),
      'GET /api/conversations': () =>
        new Response(JSON.stringify({ conversations: conversationsState }), { status: 200 }),
      'POST /api/conversations': (init) => {
        const body = init?.body ? (JSON.parse(String(init.body)) as { title?: string }) : {};
        const created = {
          id: 'proj-new',
          title: body.title || 'โปรเจกต์ใหม่',
          mode: 'auto',
          updated_at: '2026-11-25T02:00:00Z',
          message_count: 0,
        };
        conversationsState.unshift(created);
        return new Response(JSON.stringify({ conversation: created }), { status: 201 });
      },
      'GET /api/developer/tools': () =>
        new Response(
          JSON.stringify({
            tools: [
              {
                id: 'calc_ast',
                name: 'คำนวณ AST',
                category: 'compute',
                description: 'AST',
                endpoint_allowlist_json: '[]',
                permission_mode: 'auto',
                enabled: 1,
                quota_daily: 200,
                calls_today: 0,
                last_reset_date: '2026-11-25',
                updated_at: '2026-11-25T00:00:00Z',
              },
            ],
            invocations: [],
            workspace_files: workspaceFilesState,
          }),
          { status: 200 }
        ),
      'POST /api/developer/workspace-files': (init) => {
        const body = init?.body ? (JSON.parse(String(init.body)) as { name?: string }) : {};
        const fname = body.name || 'notes.md';
        workspaceFilesState.unshift({
          name: fname,
          size_bytes: 128,
          modified_at: '2026-11-25T02:00:00Z',
        });
        return new Response(JSON.stringify({ ok: true, name: fname }), { status: 201 });
      },
      'POST /api/developer/tools/calc_ast/invoke': () =>
        new Response(
          JSON.stringify({
            ok: true,
            status: 'COMPLETED',
            analysis: { summary: 'ผลวิเคราะห์ AST: 2048' },
          }),
          { status: 201 }
        ),
      'POST /api/developer/tools/workspace_file_read/invoke': () =>
        new Response(
          JSON.stringify({
            ok: true,
            status: 'COMPLETED',
            output: { content: '# แผนสถาปัตยกรรมระบบ\nรองรับการทำงานแบบโมดูล' },
          }),
          { status: 200 }
        ),
      'GET /api/autonomous/missions': () =>
        new Response(
          JSON.stringify({
            missions: [
              {
                id: 'm-ws-1',
                goal: 'วิเคราะห์โครงสร้างโมดูลระบบ',
                status: 'COMPLETED',
                report_markdown: '# รายงานผลภารกิจ\nตรวจพบโครงสร้างสมบูรณ์',
                created_at: '2026-11-25T01:00:00Z',
                updated_at: '2026-11-25T01:01:00Z',
              },
            ],
          }),
          { status: 200 }
        ),
      'GET /api/autonomous/missions/m-ws-1': () =>
        new Response(
          JSON.stringify({
            mission: {
              id: 'm-ws-1',
              goal: 'วิเคราะห์โครงสร้างโมดูลระบบ',
              status: 'COMPLETED',
              report_markdown: '# รายงานผลภารกิจ\nตรวจพบโครงสร้างสมบูรณ์',
              created_at: '2026-11-25T01:00:00Z',
              updated_at: '2026-11-25T01:01:00Z',
            },
            nodes: [],
            evidence: [],
          }),
          { status: 200 }
        ),
      'GET /api/workflows/reasoning-traces': () =>
        new Response(
          JSON.stringify({
            reasoning_traces: [
              {
                id: 'rt-ws-1',
                conversation_id: 'proj-1',
                message_id: null,
                user_id: 'u1',
                prompt: 'ตรวจสอบข้อมูลระบบ',
                response_preview: 'ตรวจสอบครบถ้วนแล้ว',
                status: 'VERIFIED',
                mode: 'auto',
                model_version: 'zyrquen-omega-v1',
                engine_path_json: '["cognitive_pipeline"]',
                trace_json: JSON.stringify({ engine_path: ['cognitive_pipeline'] }),
                latency_ms: 4.5,
                created_at: '2026-11-25T01:00:00Z',
              },
            ],
          }),
          { status: 200 }
        ),
      'GET /api/workflows': () =>
        new Response(JSON.stringify({ groups: [], runs: [] }), { status: 200 }),
      'GET /api/knowledge': () =>
        new Response(JSON.stringify({ triples: [] }), { status: 200 }),
    });

    render(<App />);

    // 1. Overview (ภาพรวม) displays workspace hero + 6 task-oriented tabs without chatbot mode tabs
    expect(await screen.findByText('คุณต้องการสร้างอะไรวันนี้?')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'ภาพรวม' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'โปรเจกต์' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'งานของฉัน' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'สร้างงาน' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'วิเคราะห์' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'คลังผลงาน' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'อัตโนมัติ' })).not.toBeInTheDocument();

    // 2. Projects (โปรเจกต์)
    fireEvent.click(screen.getAllByRole('button', { name: 'โปรเจกต์' })[0]);
    expect(
      await screen.findByText('โปรเจกต์วิเคราะห์ระบบ', {}, { timeout: 4000 })
    ).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText('ชื่อโปรเจกต์', {}, { timeout: 4000 }), {
      target: { value: 'โปรเจกต์สร้าง API' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'สร้างและเปิดโปรเจกต์' }));
    expect(await screen.findByText('พื้นที่ดำเนินงาน ZYRQUEN')).toBeInTheDocument();

    // 3. My Tasks (งานของฉัน)
    fireEvent.click(screen.getAllByRole('button', { name: 'งานของฉัน' })[0]);
    expect((await screen.findAllByText('วิเคราะห์โครงสร้างโมดูลระบบ')).length).toBeGreaterThan(0);

    // 4. Create (สร้างงาน) — direct file artifact creation
    fireEvent.click(screen.getAllByRole('button', { name: 'สร้างงาน' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: /เขียนไฟล์ลงคลังตรง/ }));
    fireEvent.change(screen.getByLabelText(/ชื่อไฟล์/), {
      target: { value: 'spec-sheet.md' },
    });
    fireEvent.change(screen.getByLabelText('เนื้อหาไฟล์'), {
      target: { value: '# Spec Sheet' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'บันทึกไฟล์ลงคลังผลงาน' }));
    expect(
      await screen.findByText(/บันทึกไฟล์ "spec-sheet\.md" ลงในคลังผลงานเรียบร้อยแล้ว/)
    ).toBeInTheDocument();

    // 5. Analysis (วิเคราะห์) — deterministic AST computation
    fireEvent.click(screen.getAllByRole('button', { name: 'วิเคราะห์' })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'คำนวณและแก้สมการ' }));
    fireEvent.change(screen.getByLabelText('นิพจน์หรือสมการที่ต้องการคำนวณ'), {
      target: { value: '2^11' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'คำนวณผลลัพธ์' }));
    expect(await screen.findByText('ผลวิเคราะห์ AST: 2048')).toBeInTheDocument();

    // 6. Artifacts (คลังผลงาน) — inspect & preview file content
    fireEvent.click(screen.getAllByRole('button', { name: 'คลังผลงาน' })[0]);
    fireEvent.click(await screen.findByText('architecture-plan.md'));
    expect(await screen.findByText(/# แผนสถาปัตยกรรมระบบ/)).toBeInTheDocument();
  }, 15_000);

  it('ProjectDashboard: แสดงการ์ดสถานะ เปอร์เซ็นต์ความคืบหน้า และรายการค้างดำเนินการทั้งใน HomeView และ ProjectsView พร้อมตัวกรองและคัดลอกสรุป TSV', async () => {
    const { HomeView } = await import('../components/HomeView');
    const { ProjectsView } = await import('../components/IntelligenceWorkspaceViews');
    const origClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const copiedTexts: string[] = [];

    const projectsFixture = [
      {
        id: 'proj-active',
        title: 'โปรเจกต์อัปเกรดสถาปัตยกรรม',
        mode: 'plan' as const,
        updated_at: '2026-11-25T01:30:00Z',
        message_count: 4,
        project_status: 'ACTIVE' as const,
        completion_pct: 67,
        completed_units: 2,
        total_units: 3,
        pending_actions: [
          {
            id: 'step-3',
            title: 'รันชุดทดสอบรวมระบบหลังปรับปรุง',
            status: 'IN_PROGRESS',
            category: 'task' as const,
          },
        ],
        last_activity_summary: 'ดำเนินการแล้ว 2 จาก 3 ขั้นตอน',
      },
      {
        id: 'proj-approval',
        title: 'โปรเจกต์สืบค้นเอกสารภายนอก',
        mode: 'auto' as const,
        updated_at: '2026-11-25T01:45:00Z',
        message_count: 2,
        project_status: 'AWAITING_APPROVAL' as const,
        completion_pct: 50,
        completed_units: 1,
        total_units: 2,
        pending_actions: [
          {
            id: 'inv-1',
            title: 'รออนุมัติการใช้เครื่องมือ doc_fetch',
            status: 'PENDING_APPROVAL',
            category: 'approval' as const,
          },
        ],
        last_activity_summary: 'รออนุมัติ Gate จากผู้ดูแล',
      },
      {
        id: 'proj-done',
        title: 'โปรเจกต์ตรวจความถูกต้อง AST',
        mode: 'math' as const,
        updated_at: '2026-11-25T02:00:00Z',
        message_count: 2,
        project_status: 'COMPLETED' as const,
        completion_pct: 100,
        completed_units: 2,
        total_units: 2,
        pending_actions: [],
        last_activity_summary: 'ผ่านการตรวจสอบครบทุกขั้นตอน',
      },
    ];

    try {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: vi.fn(async (txt: string) => {
            copiedTexts.push(txt);
          }),
        },
      });

      const onOpenFromHome = vi.fn();
      const onNavigate = vi.fn();

      // 1. HomeView (overview variant)
      const homeRender = render(
        <HomeView
          user={{
            id: 'u1',
            email: 'admin@zyrquen.local',
            display_name: 'Admin',
            role: 'admin',
            created_at: '2026-11-25T00:00:00Z',
          }}
          homeSummary={{
            recent_conversations: projectsFixture,
            counts: { triples: 3, checkpoints: 1, datasets: 1, pending_approvals: 1, missions: 0 },
            system: {
              python_version: '3.11.2',
              platform: 'Linux',
              cpu_count: 4,
              load_1m: 0.1,
              mem_total_mb: 4096,
              mem_available_mb: 2048,
              disk_free_gb: 20,
              disk_total_gb: 50,
              sqlite_db_kb: 16,
            },
          }}
          nativeReady={true}
          loading={false}
          error={null}
          onStartPrompt={vi.fn()}
          onOpenConversation={onOpenFromHome}
          onNavigate={onNavigate}
          onRetry={vi.fn()}
        />
      );

      expect(screen.getByText('· เฉลี่ย 72% · ค้างดำเนินการ 2 รายการ')).toBeInTheDocument();
      expect(screen.getByText('67% (2/3)')).toBeInTheDocument();
      expect(screen.getByText('100% (2/2)')).toBeInTheDocument();
      expect(screen.getByRole('progressbar', { name: 'ความคืบหน้า โปรเจกต์อัปเกรดสถาปัตยกรรม' })).toHaveAttribute(
        'aria-valuenow',
        '67'
      );
      expect(screen.getByRole('progressbar', { name: 'ความคืบหน้า โปรเจกต์ตรวจความถูกต้อง AST' })).toHaveAttribute(
        'aria-valuenow',
        '100'
      );
      expect(screen.getByText('รันชุดทดสอบรวมระบบหลังปรับปรุง')).toBeInTheDocument();
      expect(screen.getByText('รออนุมัติการใช้เครื่องมือ doc_fetch')).toBeInTheDocument();
      expect(screen.getByText('ไม่มีรายการค้างดำเนินการ')).toBeInTheDocument();

      // Copy TSV summary from ProjectDashboard
      fireEvent.click(screen.getByRole('button', { name: 'คัดลอกสรุปแดชบอร์ดโปรเจกต์' }));
      await waitFor(() => expect(copiedTexts).toHaveLength(1));
      expect(copiedTexts[0]).toContain('ZYRQUEN Project Dashboard Summary');
      expect(copiedTexts[0]).toContain('โปรเจกต์อัปเกรดสถาปัตยกรรม\tกำลังดำเนินการ\t67% (2/3)');
      expect(copiedTexts[0]).toContain('โปรเจกต์สืบค้นเอกสารภายนอก\tรออนุมัติ\t50% (1/2)');

      // Filter by 'เสร็จสมบูรณ์'
      fireEvent.click(screen.getByRole('tab', { name: 'เสร็จสมบูรณ์ (1)' }));
      expect(screen.getByText('โปรเจกต์ตรวจความถูกต้อง AST')).toBeInTheDocument();
      expect(screen.queryByText('โปรเจกต์อัปเกรดสถาปัตยกรรม')).not.toBeInTheDocument();

      // Filter by 'มีงานค้าง'
      fireEvent.click(screen.getByRole('tab', { name: 'มีงานค้าง (2)' }));
      expect(screen.getByText('โปรเจกต์อัปเกรดสถาปัตยกรรม')).toBeInTheDocument();
      expect(screen.getByText('โปรเจกต์สืบค้นเอกสารภายนอก')).toBeInTheDocument();
      expect(screen.queryByText('โปรเจกต์ตรวจความถูกต้อง AST')).not.toBeInTheDocument();

      // Open project from overview card
      fireEvent.click(screen.getAllByRole('button', { name: 'เปิดโปรเจกต์เพื่อทำงานต่อ' })[0]);
      expect(onOpenFromHome).toHaveBeenCalledWith('proj-active');
      homeRender.unmount();

      // 2. ProjectsView (full variant with search & delete)
      mockFetch({
        'GET /api/developer/tools': () =>
          new Response(JSON.stringify({ tools: [], invocations: [], workspace_files: [] }), { status: 200 }),
        'GET /api/autonomous/missions': () =>
          new Response(JSON.stringify({ missions: [] }), { status: 200 }),
      });
      const onOpenFromProjects = vi.fn();
      const onDeleteProject = vi.fn(async () => {});
      render(
        <ProjectsView
          token="tok-proj"
          conversations={projectsFixture}
          onCreateProject={vi.fn(async () => {})}
          onOpenConversation={onOpenFromProjects}
          onDeleteProject={onDeleteProject}
          onNavigate={vi.fn()}
        />
      );

      expect(screen.getByText('แดชบอร์ดโปรเจกต์ (3)')).toBeInTheDocument();
      const searchInput = screen.getByLabelText('ค้นหาโปรเจกต์');
      fireEvent.change(searchInput, { target: { value: 'doc_fetch' } });
      expect(screen.getByText('แดชบอร์ดโปรเจกต์ (1)')).toBeInTheDocument();
      expect(screen.getByText('โปรเจกต์สืบค้นเอกสารภายนอก')).toBeInTheDocument();
      expect(screen.queryByText('โปรเจกต์ตรวจความถูกต้อง AST')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'เปิดโปรเจกต์' }));
      expect(onOpenFromProjects).toHaveBeenCalledWith('proj-approval');

      fireEvent.click(screen.getByRole('button', { name: 'ลบโปรเจกต์ โปรเจกต์สืบค้นเอกสารภายนอก' }));
      expect(onDeleteProject).toHaveBeenCalledWith('proj-approval');
    } finally {
      if (origClipboard) {
        Object.defineProperty(navigator, 'clipboard', origClipboard);
      } else {
        delete (navigator as unknown as { clipboard?: unknown }).clipboard;
      }
    }
  });

  it('AppShell: Desktop Sidebar ย่อ/ขยายได้, Mobile Bottom Bar มี 5 ปุ่มหลัก และ Side Drawer มีเมนูระบบครบ 5 รายการ', async () => {
    const { AppShell } = await import('../components/AppShell');
    const onNavigate = vi.fn();

    const { rerender } = render(
      <AppShell
        activeScreen="overview"
        activeSettingsTab="account"
        screenTitle="ภาพรวม"
        user={{
          id: 'u1',
          email: 'admin@zyrquen.local',
          display_name: 'Admin',
          role: 'admin',
          created_at: '2026-11-25T00:00:00Z',
        }}
        onNavigate={onNavigate}
        onBack={vi.fn()}
        onOpenProfile={vi.fn()}
        onOpenCommandPalette={vi.fn()}
      >
        <div>เนื้อหาทดสอบ</div>
      </AppShell>
    );

    // Desktop Left Sidebar: collapse & expand toggle + breadcrumb
    const sidebar = screen.getByRole('complementary', { name: 'แถบนำทางด้านข้าง' });
    expect(sidebar).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'เส้นทางตำแหน่ง' })).toBeInTheDocument();

    const collapseBtn = screen.getByRole('button', { name: 'ย่อแถบด้านข้าง' });
    fireEvent.click(collapseBtn);
    expect(screen.getByRole('button', { name: 'ขยายแถบด้านข้าง' })).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'ขยายแถบด้านข้าง' }));
    expect(screen.getByRole('button', { name: 'ย่อแถบด้านข้าง' })).toHaveAttribute('aria-expanded', 'true');

    // Mobile Bottom Bar: exact 5 primary items in approved order
    const mobileNav = screen.getByRole('navigation', { name: 'แถบนำทางมือถือ' });
    const mobileButtons = Array.from(mobileNav.querySelectorAll('button')).map((b) =>
      b.textContent?.trim()
    );
    expect(mobileButtons).toEqual(['ภาพรวม', 'โปรเจกต์', 'สร้างงาน', 'งานของฉัน', 'คลังผลงาน']);
    expect(screen.queryByRole('dialog', { name: 'เมนูเพิ่มเติม' })).not.toBeInTheDocument();

    // Mobile Side Drawer: open via เพิ่มเติม, verify 5 system items, close with Escape
    const moreBtn = screen.getByRole('button', { name: 'เพิ่มเติม' });
    fireEvent.click(moreBtn);

    const drawer = screen.getByRole('dialog', { name: 'เมนูเพิ่มเติม' });
    expect(drawer).toBeInTheDocument();
    const drawerNav = screen.getByRole('navigation', { name: 'เมนูเพิ่มเติมในแถบข้าง' });
    const drawerLabels = Array.from(drawerNav.querySelectorAll('button')).map((b) =>
      b.textContent?.trim()
    );
    expect(drawerLabels).toEqual([
      'วิเคราะห์',
      'ความรู้และ Workflow',
      'โมเดลและการฝึก',
      'สิทธิ์และความปลอดภัย',
      'ตั้งค่า',
    ]);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'เมนูเพิ่มเติม' })).not.toBeInTheDocument();

    // Verify route callbacks from drawer items (admin user)
    fireEvent.click(moreBtn);
    const drawerButtons = screen
      .getByRole('navigation', { name: 'เมนูเพิ่มเติมในแถบข้าง' })
      .querySelectorAll('button');
    fireEvent.click(drawerButtons[0]); // วิเคราะห์
    expect(onNavigate).toHaveBeenCalledWith('analysis');
    expect(screen.queryByRole('dialog', { name: 'เมนูเพิ่มเติม' })).not.toBeInTheDocument();

    fireEvent.click(moreBtn);
    const drawerButtons2 = screen
      .getByRole('navigation', { name: 'เมนูเพิ่มเติมในแถบข้าง' })
      .querySelectorAll('button');
    fireEvent.click(drawerButtons2[2]); // โมเดลและการฝึก
    expect(onNavigate).toHaveBeenCalledWith('settings', 'developer');

    fireEvent.click(moreBtn);
    const drawerButtons3 = screen
      .getByRole('navigation', { name: 'เมนูเพิ่มเติมในแถบข้าง' })
      .querySelectorAll('button');
    fireEvent.click(drawerButtons3[3]); // สิทธิ์และความปลอดภัย (admin -> admin tab)
    expect(onNavigate).toHaveBeenCalledWith('settings', 'admin');

    // Non-admin RBAC: สิทธิ์และความปลอดภัย routes safely to account tab, never admin
    rerender(
      <AppShell
        activeScreen="overview"
        activeSettingsTab="account"
        screenTitle="ภาพรวม"
        user={{
          id: 'u2',
          email: 'member@zyrquen.local',
          display_name: 'Member',
          role: 'user',
          created_at: '2026-11-25T00:00:00Z',
        }}
        onNavigate={onNavigate}
        onBack={vi.fn()}
        onOpenProfile={vi.fn()}
      >
        <div>เนื้อหาทดสอบ</div>
      </AppShell>
    );
    fireEvent.click(screen.getByRole('button', { name: 'เพิ่มเติม' }));
    const memberDrawerButtons = screen
      .getByRole('navigation', { name: 'เมนูเพิ่มเติมในแถบข้าง' })
      .querySelectorAll('button');
    fireEvent.click(memberDrawerButtons[3]);
    expect(onNavigate).toHaveBeenLastCalledWith('settings', 'account');
  });

  it('WorkspaceView Command Workspace: รองรับการเลือก Project, แนบไฟล์, เอกสาร/โค้ด/Artifacts, Approval Gate และไม่แสดงเครื่องมือภายใน', async () => {
    const { WorkspaceView } = await import('../components/WorkspaceView');
    const onSelectConversation = vi.fn();
    const onNewConversation = vi.fn();
    const onRefreshConversation = vi.fn(async () => {});
    const onSendMessage = vi.fn(async () => {});

    let decideCalled = false;
    mockFetch({
      'POST /api/admin/tool-invocations/inv-gate-1/decide': () => {
        decideCalled = true;
        return new Response(JSON.stringify({ ok: true, status: 'COMPLETED' }), { status: 200 });
      },
    });

    const richMarkdown = [
      '### แผนงานและผลลัพธ์',
      '',
      '1. วิเคราะห์เป้าหมายและวางแผน',
      '2. ดำเนินการตรวจสอบไฟล์ [อ้างอิงเอกสาร](https://example.com/spec) และบล็อกลิงก์ [unsafe](javascript:alert(1))',
      '',
      '---',
      '',
      '```typescript',
      'export const ready = true;',
      '```',
    ].join('\n');

    render(
      <WorkspaceView
        token="tok-cmd"
        userRole="admin"
        conversations={[
          {
            id: 'proj-1',
            title: 'โปรเจกต์ระบบฐานข้อมูล',
            mode: 'auto',
            created_at: '2026-11-25T00:00:00Z',
            updated_at: '2026-11-25T00:00:00Z',
            message_count: 3,
          },
          {
            id: 'proj-2',
            title: 'โปรเจกต์รายงานอัตโนมัติ',
            mode: 'auto',
            created_at: '2026-11-25T00:00:00Z',
            updated_at: '2026-11-25T00:00:00Z',
            message_count: 1,
          },
        ]}
        activeConversationId="proj-1"
        activeTitle="โปรเจกต์ระบบฐานข้อมูล"
        messages={[
          {
            id: 'u-att-1',
            conversation_id: 'proj-1',
            role: 'user',
            content: 'สรุปไฟล์นี้ให้หน่อย\n\n[Attachment: 42 chars]',
            mode: 'auto',
            trace_json: null,
            status: 'USER',
            created_at: '2026-11-25T00:00:00Z',
          },
          {
            id: 'a-art-1',
            conversation_id: 'proj-1',
            role: 'assistant',
            content: richMarkdown,
            mode: 'auto',
            trace_json: JSON.stringify({
              engine_path: ['tool_center', 'document.spec_generate'],
              latency_ms: 4.2,
              deliverable: {
                kind: 'document',
                title: 'เอกสารสรุปสถาปัตยกรรม',
                filename: 'architecture-summary.md',
                language: 'markdown',
                sha256: 'abc1234567890def',
                verified: true,
                content: '# Architecture Summary\n\nVerified content',
              },
            }),
            status: 'VERIFIED',
            created_at: '2026-11-25T00:00:01Z',
          },
          {
            id: 'a-gate-1',
            conversation_id: 'proj-1',
            role: 'assistant',
            content: 'ขั้นตอนเชื่อมต่อ Webhook ต้องได้รับการอนุมัติก่อนส่งคำขอจริง',
            mode: 'auto',
            trace_json: JSON.stringify({
              engine_path: ['external_tool', 'approval_gate'],
              latency_ms: 1.5,
              external_tool: {
                invocation_id: 'inv-gate-1',
                tool_id: 'webhook_dispatch',
                status: 'PENDING_APPROVAL',
              },
            }),
            status: 'PENDING_APPROVAL',
            created_at: '2026-11-25T00:00:02Z',
          },
        ]}
        loadingThread={false}
        sending={false}
        error={null}
        defaultMode="auto"
        onSelectConversation={onSelectConversation}
        onNewConversation={onNewConversation}
        onDeleteConversation={vi.fn()}
        onSendMessage={onSendMessage}
        onRefreshConversation={onRefreshConversation}
      />
    );

    // 1. UI Restrictions: No Developer Tools / Tool Registry / Execution Engine Dashboard
    expect(screen.queryByText('Developer Trace')).not.toBeInTheDocument();
    expect(screen.queryByText(/Tool Registry/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Toolkit Catalog/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Capability Library/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Execution Engine Dashboard/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'ตั้งค่าโมเดลและพื้นที่ทำงาน' })).not.toBeInTheDocument();

    // 2. Clean Attachment badge in user message
    expect(screen.getByText('สรุปไฟล์นี้ให้หน่อย')).toBeInTheDocument();
    expect(screen.getByText('ไฟล์แนบ (42 ตัวอักษร)')).toBeInTheDocument();

    // 3. Rich Markdown rendering: ordered list, safe external link, sanitized unsafe link, code download button
    expect(screen.getByText('วิเคราะห์เป้าหมายและวางแผน')).toBeInTheDocument();
    const safeLink = screen.getByRole('link', { name: 'อ้างอิงเอกสาร' });
    expect(safeLink).toHaveAttribute('href', 'https://example.com/spec');
    expect(screen.queryByRole('link', { name: 'unsafe' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ดาวน์โหลดไฟล์โค้ด' })).toBeInTheDocument();

    // 4. Deliverable artifact card rendered cleanly with copy & download
    expect(screen.getByText('เอกสารสรุปสถาปัตยกรรม')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'คัดลอกเนื้อหาผลงาน' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ดาวน์โหลดผลงาน' })).toBeInTheDocument();

    // 5. Conversation selector switches thread and creates new conversation
    const conversationSelect = screen.getByLabelText('เลือกบทสนทนา') as HTMLSelectElement;
    expect(conversationSelect.value).toBe('proj-1');
    fireEvent.change(conversationSelect, { target: { value: 'proj-2' } });
    expect(onSelectConversation).toHaveBeenCalledWith('proj-2');
    fireEvent.change(conversationSelect, { target: { value: '__new__' } });
    expect(onNewConversation).toHaveBeenCalledTimes(1);

    // 6. Inline Approval Gate submits real decision and refreshes thread
    fireEvent.click(screen.getByRole('button', { name: 'อนุมัติและทำต่อ' }));
    expect(await screen.findByText(/อนุมัติแล้ว \(COMPLETED\)/)).toBeInTheDocument();
    expect(decideCalled).toBe(true);
    expect(onRefreshConversation).toHaveBeenCalled();

    // 7. User prompt copy & long-text character counter
    const copyPromptBtn = screen.getByRole('button', { name: 'คัดลอกคำสั่ง' });
    expect(copyPromptBtn).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'คัดลอกข้อความตอบกลับ' }).length).toBe(2);

    const composer = screen.getByLabelText('ช่องพิมพ์คำสั่งงาน');
    fireEvent.change(composer, { target: { value: 'ก'.repeat(320) } });
    expect(screen.getByText('320 ตัวอักษร')).toBeInTheDocument();
  });

  it('WorkspaceView: แสดงปุ่มหยุดการทำงานเมื่อกำลังส่งคำสั่งและเรียก onCancelSending ได้จริง', async () => {
    const { WorkspaceView } = await import('../components/WorkspaceView');
    const onCancelSending = vi.fn();

    render(
      <WorkspaceView
        token="tok-stop"
        conversations={[]}
        activeConversationId="proj-1"
        activeTitle="ทดสอบหยุดคำสั่ง"
        messages={[]}
        loadingThread={false}
        sending={true}
        streamingContent="กำลังประมวลผลแผนงาน..."
        error={null}
        defaultMode="auto"
        onSelectConversation={vi.fn()}
        onNewConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onSendMessage={vi.fn(async () => {})}
        onCancelSending={onCancelSending}
      />
    );

    const stopBtn = screen.getByRole('button', { name: 'หยุดการทำงาน' });
    fireEvent.click(stopBtn);
    expect(onCancelSending).toHaveBeenCalledTimes(1);
  });

  it('Reasoning Trace UI & Validation: กรองข้อความผิดรูปแบบ เช่น รายละเอียดและข้อกำหนด: ะะี และแสดงเฉพาะแผนที่ตรวจสอบแล้วพร้อมสถานะจริง', async () => {
    const {
      isMalformedOrEmptyTraceText,
      sanitizeTraceDisplayText,
      validateTracePlan,
      filterValidTraceSteps,
    } = await import('../lib/clipboard');
    const { WorkspaceView } = await import('../components/WorkspaceView');
    const { MemoryWorkflowsView } = await import('../components/MemoryWorkflowsView');
    const { CreateArtifactView, ArtifactsView } = await import('../components/IntelligenceWorkspaceViews');

    // 1. Unit checks for sanitization & plan validation
    expect(isMalformedOrEmptyTraceText('รายละเอียดและข้อกำหนด: ะะี')).toBe(true);
    expect(isMalformedOrEmptyTraceText('วางแผนและพัฒนาซอร์สโค้ด\n\nรายละเอียดและข้อกำหนด:\nะะี')).toBe(true);
    expect(sanitizeTraceDisplayText('วางแผนและพัฒนาซอร์สโค้ด\n\nรายละเอียดและข้อกำหนด:\nะะี')).toBe('');
    expect(sanitizeTraceDisplayText('หัวข้อที่ถูกต้อง\nรายละเอียดและข้อกำหนด: ะะี')).toBe('หัวข้อที่ถูกต้อง');
    expect(
      filterValidTraceSteps(['1. ขั้นตอนปกติ', 'รายละเอียดและข้อกำหนด: ะะี', 's1 · x [undefined]: ok'])
    ).toEqual(['1. ขั้นตอนปกติ']);

    expect(
      validateTracePlan({
        goal: 'รายละเอียดและข้อกำหนด: ะะี',
        plan_status: 'NEEDS_CLARIFICATION',
        plan_valid: false,
        is_actionable_goal: false,
        steps: [
          { step_id: 's1', title: 'placeholder', status: 'BLOCKED', detail: 'ะะี' },
        ],
      }).valid
    ).toBe(false);

    const validPlanCheck = validateTracePlan({
      goal: 'ตรวจสอบโมดูล planner_intelligence.py',
      plan_status: 'PLANNED',
      plan_valid: true,
      is_actionable_goal: true,
      status_transitions: [
        { from_status: 'DRAFT', to_status: 'PLANNED' },
        { step_id: 'step_inspect', from_status: 'DRAFT', to_status: 'READY' },
      ],
      steps: [
        {
          step_id: 'step_inspect',
          title: 'สำรวจโครงสร้างโมดูล',
          status: 'READY',
          depends_on: [],
          requires_approval: false,
          detail: 'ตรวจอ่านฟังก์ชันวิเคราะห์เป้าหมาย',
        },
        {
          step_id: 'step_verify',
          title: 'ทดสอบการตรวจสอบย้อนหลัง',
          status: 'BLOCKED',
          depends_on: ['step_inspect'],
          requires_approval: false,
          detail: 'รอขั้นตอนสำรวจเสร็จสมบูรณ์',
        },
      ],
    });
    expect(validPlanCheck.valid).toBe(true);
    expect(validPlanCheck.steps.length).toBe(2);

    // 2. WorkspaceView renders validated plan card cleanly and filters corrupt user spec & invalid plan
    const wv = render(
      <WorkspaceView
        token="tok-trace"
        conversations={[{ id: 'proj-t', title: 'Audit', mode: 'plan', created_at: '', updated_at: '', message_count: 3 }]}
        activeConversationId="proj-t"
        activeTitle="Audit"
        messages={[
          {
            id: 'm-bad-user',
            conversation_id: 'proj-t',
            role: 'user',
            content: 'วางแผนและพัฒนาซอร์สโค้ด\n\nรายละเอียดและข้อกำหนด:\nะะี',
            mode: 'plan',
            trace_json: null,
            status: 'USER',
            created_at: '2026-11-25T00:00:00Z',
          },
          {
            id: 'm-bad-plan',
            conversation_id: 'proj-t',
            role: 'assistant',
            content: 'ต้องการข้อมูลเพิ่มเติมก่อนวางแผน (NEEDS_CLARIFICATION)',
            mode: 'plan',
            trace_json: JSON.stringify({
              engine_path: ['native_planner'],
              plan: {
                goal: 'รายละเอียดและข้อกำหนด: ะะี',
                plan_status: 'NEEDS_CLARIFICATION',
                plan_valid: false,
                steps: [{ step_id: 's1', title: 'TBD', status: 'BLOCKED', detail: 'ะะี' }],
              },
            }),
            status: 'NEEDS_CLARIFICATION',
            created_at: '2026-11-25T00:00:01Z',
          },
          {
            id: 'm-good-plan',
            conversation_id: 'proj-t',
            role: 'assistant',
            content: '**แผนปฏิบัติการเชิงโครงสร้าง**',
            mode: 'plan',
            trace_json: JSON.stringify({
              engine_path: ['native_planner'],
              plan: {
                goal: 'ตรวจสอบโมดูล planner_intelligence.py',
                plan_status: 'PLANNED',
                plan_valid: true,
                is_actionable_goal: true,
                status_transitions: [
                  { from_status: 'DRAFT', to_status: 'PLANNED' },
                  { step_id: 'step_inspect', from_status: 'DRAFT', to_status: 'READY' },
                ],
                steps: [
                  {
                    step_id: 'step_inspect',
                    title: 'สำรวจโครงสร้างโมดูล',
                    status: 'READY',
                    depends_on: [],
                    detail: 'ตรวจอ่านฟังก์ชันวิเคราะห์เป้าหมาย',
                  },
                ],
              },
            }),
            status: 'PLANNED',
            created_at: '2026-11-25T00:00:02Z',
          },
        ]}
        loadingThread={false}
        sending={false}
        error={null}
        defaultMode="plan"
        onSelectConversation={vi.fn()}
        onNewConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onSendMessage={vi.fn(async () => {})}
      />
    );

    expect(screen.queryByText(/ะะี/)).not.toBeInTheDocument();
    expect(screen.getByText('คำสั่งไม่สมบูรณ์ (ถูกคัดกรอง)')).toBeInTheDocument();
    expect(screen.getByText('วางแผนแล้ว · พร้อมตรวจสอบ')).toBeInTheDocument();
    expect(screen.getByText('แผนงานที่ตรวจสอบแล้ว')).toBeInTheDocument();
    expect(screen.getByText('ตรวจสอบโมดูล planner_intelligence.py')).toBeInTheDocument();
    expect(screen.getByText('READY')).toBeInTheDocument();
    expect(screen.getByText('DRAFT → PLANNED')).toBeInTheDocument();
    expect(screen.queryByText('Developer Trace')).not.toBeInTheDocument();
    wv.unmount();

    // 3. MemoryWorkflowsView filters malformed Reasoning Trace entries & [undefined] placeholder plans
    mockFetch({
      'GET /api/knowledge': () => new Response(JSON.stringify({ triples: [] }), { status: 200 }),
      'GET /api/workflows': () =>
        new Response(
          JSON.stringify({
            groups: [],
            runs: [],
            reasoning_traces: [
              {
                id: 'tr-bad',
                user_id: 'u1',
                conversation_id: null,
                prompt: 'รายละเอียดและข้อกำหนด: ะะี',
                mode: 'plan',
                response_preview: 'รายละเอียดและข้อกำหนด: ะะี',
                model_version: 'zyrquen-native-v1',
                engine_path_json: JSON.stringify(['native_planner']),
                trace_json: JSON.stringify({
                  plan: {
                    goal: 'รายละเอียดและข้อกำหนด: ะะี',
                    plan_status: 'NEEDS_CLARIFICATION',
                    plan_valid: false,
                    steps: [{ step_id: 's0', title: 'Bad Step', status: undefined, detail: 'ะะี' }],
                  },
                  task_timings: [{ task: '', duration_ms: 1.0, matched: false, status: 'UNKNOWN' }],
                }),
                external_models_used: 0,
                status: 'UNKNOWN',
                latency_ms: 2.1,
                created_at: '2026-11-25T00:00:00Z',
              },
            ],
          }),
          { status: 200 }
        ),
      'GET /api/autonomous/missions': () => new Response(JSON.stringify({ missions: [] }), { status: 200 }),
    });

    const mw = render(
      <MemoryWorkflowsView
        token="tok-wf"
        user={{ id: 'u1', email: 'u1@test.local', display_name: 'Tester', role: 'user', created_at: '' }}
      />
    );

    fireEvent.click(await screen.findByRole('button', { name: /ระบบเวิร์กโฟลว์/ }));
    const filteredLabels = await screen.findAllByText('คำสั่งไม่สมบูรณ์หรือผิดรูปแบบ (ถูกคัดกรอง)');
    expect(filteredLabels.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/ะะี/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Bad Step/)).not.toBeInTheDocument();
    mw.unmount();

    // 4. CreateArtifactView blocks malformed input before calling onStartTask
    const onStartTask = vi.fn(async () => {});
    const cv = render(<CreateArtifactView token="tok-create" onStartTask={onStartTask} onNavigate={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('ข้อกำหนดและรายละเอียดที่ต้องการ'), {
      target: { value: 'ะะี' },
    });
    fireEvent.click(screen.getByRole('button', { name: /เริ่มสร้างงาน/ }));
    expect(await screen.findByText(/หัวข้อหรือรายละเอียดไม่สมบูรณ์หรือมีอักขระผิดรูปแบบ/)).toBeInTheDocument();
    expect(onStartTask).not.toHaveBeenCalled();
    cv.unmount();

    // 5. ArtifactsView omits UNKNOWN/NEEDS_CLARIFICATION corrupt traces while keeping verified ones
    mockFetch({
      'GET /api/developer/tools': () => new Response(JSON.stringify({ workspace_files: [] }), { status: 200 }),
      'GET /api/autonomous/missions': () => new Response(JSON.stringify({ missions: [] }), { status: 200 }),
      'GET /api/workflows/reasoning-traces': () =>
        new Response(
          JSON.stringify({
            reasoning_traces: [
              {
                id: 'art-bad',
                user_id: 'u1',
                conversation_id: null,
                prompt: 'รายละเอียดและข้อกำหนด: ะะี',
                mode: 'plan',
                response_preview: 'รายละเอียดและข้อกำหนด: ะะี',
                model_version: 'v1',
                engine_path_json: '[]',
                trace_json: '{}',
                external_models_used: 0,
                status: 'UNKNOWN',
                latency_ms: 1,
                created_at: '2026-11-25T00:00:00Z',
              },
              {
                id: 'art-good',
                user_id: 'u1',
                conversation_id: null,
                prompt: 'สรุปผลการตรวจสอบโครงสร้าง',
                mode: 'auto',
                response_preview: 'ผลตรวจสอบผ่านเกณฑ์ครบถ้วน',
                model_version: 'v1',
                engine_path_json: '[]',
                trace_json: '{}',
                external_models_used: 0,
                status: 'VERIFIED',
                latency_ms: 4,
                created_at: '2026-11-25T00:00:05Z',
              },
            ],
          }),
          { status: 200 }
        ),
    });

    const av = render(<ArtifactsView token="tok-art" onOpenConversation={vi.fn()} onNavigate={vi.fn()} />);
    expect(await screen.findByText('สรุปผลการตรวจสอบโครงสร้าง')).toBeInTheDocument();
    expect(screen.queryByText(/ะะี/)).not.toBeInTheDocument();
    av.unmount();
  });

  it('หน้าผู้ดูแลระบบมีปุ่มส่งออก Audit Log ที่เน้นเหตุการณ์ PII Redaction ในรูปแบบไฟล์ปลอดภัยพร้อม SHA-256', async () => {
    const calledUrls: string[] = [];
    const createdBlobUrls: string[] = [];
    const revokedBlobUrls: string[] = [];
    const origCreateObjectURL = URL.createObjectURL;
    const origRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => {
      const url = `blob:zyrquen-test-${createdBlobUrls.length + 1}`;
      createdBlobUrls.push(url);
      return url;
    });
    URL.revokeObjectURL = vi.fn((url: string) => {
      revokedBlobUrls.push(url);
    });

    const piiAuditLog = {
      id: 'audit-pii-1',
      actor_id: 'u-admin',
      actor_email: 'admin@zyrquen.local',
      action: 'PII_REDACTION',
      target: 'ds-customer-corpus',
      outcome: 'REDACTED_3_PII_ITEMS',
      details_json: JSON.stringify({
        event_category: 'pii_redaction',
        pii_redacted: true,
        total_redacted: 3,
      }),
      created_at: '2026-11-26T00:00:00Z',
    };
    const otherAuditLog = {
      id: 'audit-other-1',
      actor_id: 'u-admin',
      actor_email: 'admin@zyrquen.local',
      action: 'ROLE_UPDATED',
      target: 'u-user-2',
      outcome: 'USER',
      details_json: '{}',
      created_at: '2026-11-25T23:55:00Z',
    };

    try {
      mockFetch({
        'GET /api/admin/overview': () =>
          new Response(
            JSON.stringify({
              users: [],
              pending_runs: [],
              pending_tool_invocations: [],
              pending_experiments: [],
              pending_kg_proposals: [],
              tools: [],
              audit_logs: [piiAuditLog, otherAuditLog],
              system: {
                python_version: '3.11.2',
                platform: 'Linux',
                cpu_count: 4,
                load_1m: 0.1,
                mem_total_mb: 4096,
                mem_available_mb: 2048,
                disk_free_gb: 20,
                disk_total_gb: 50,
                sqlite_db_kb: 32,
              },
            }),
            { status: 200 }
          ),
        'GET /api/admin/audit-logs/export': (init) => {
          const authHeader = (init?.headers as Record<string, string> | undefined)?.Authorization;
          expect(authHeader).toBe('Bearer t-admin-export');
          const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
          const lastUrl = String(calls[calls.length - 1]?.[0] || '');
          calledUrls.push(lastUrl);
          const body = JSON.stringify({
            schema: 'zyrquen.audit-export.v1',
            focus: lastUrl.includes('focus=all') ? 'all' : 'pii_redaction',
            exported_count: 1,
            pii_redaction_event_count: 1,
            integrity_sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
            sanitization_applied: true,
            events: [
              {
                id: 'audit-pii-1',
                actor_id: 'u-admin',
                actor_email_masked: 'ad***@zyrquen.local',
                action: 'PII_REDACTION',
                target: 'ds-customer-corpus',
                outcome: 'REDACTED_3_PII_ITEMS',
                is_pii_redaction_event: true,
              },
            ],
          });
          return new Response(body, {
            status: 200,
            headers: {
              'Content-Type': 'application/json; charset=utf-8',
              'Content-Disposition': 'attachment; filename="zyrquen-audit-pii_redaction-test.json"',
              'X-Zyrquen-Export-Sha256':
                '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
              'X-Zyrquen-Export-Count': '1',
              'X-Zyrquen-Pii-Events': '1',
            },
          });
        },
      });

      const sv = render(
        <SettingsView
          token="t-admin-export"
          user={{
            id: 'u-admin',
            email: 'admin@zyrquen.local',
            display_name: 'Admin',
            role: 'admin',
            created_at: '2026-11-26T00:00:00Z',
          }}
          activeTab="admin"
          autoExpandTrace={false}
          defaultMode="auto"
          onChangeTab={vi.fn()}
          onUpdatePreferences={vi.fn()}
          onLogout={vi.fn()}
        />
      );

      expect(await screen.findByText(/PII Redaction: 1/)).toBeInTheDocument();
      const exportBtn = screen.getByRole('button', { name: 'ส่งออก Audit Log (PII Redaction)' });
      fireEvent.click(exportBtn);

      await waitFor(() => {
        expect(calledUrls).toContain('/api/admin/audit-logs/export?focus=pii_redaction&format=json');
      });
      expect(
        await screen.findByText(/zyrquen-audit-pii_redaction-test\.json/)
      ).toBeInTheDocument();
      expect(screen.getByText(/SHA-256: 0123456789abcdef…/)).toBeInTheDocument();
      expect(createdBlobUrls.length).toBe(1);
      expect(revokedBlobUrls).toEqual(createdBlobUrls);

      // Switch to CSV format and verify CSV export trigger
      fireEvent.change(screen.getByLabelText('รูปแบบไฟล์ส่งออก Audit Log'), {
        target: { value: 'csv' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'ส่งออก Audit Log (PII Redaction)' }));
      await waitFor(() => {
        expect(calledUrls).toContain('/api/admin/audit-logs/export?focus=pii_redaction&format=csv');
      });

      sv.unmount();
    } finally {
      URL.createObjectURL = origCreateObjectURL;
      URL.revokeObjectURL = origRevokeObjectURL;
    }
  });

  it('แท็บนักพัฒนามีเครื่องมือฝึกโมเดลให้เข้าใจโค้ดและแก้ปัญหา พร้อมแสดงผลจริงและข้อจำกัด', async () => {
    mockFetch({
      'GET /api/developer/overview': () =>
        new Response(
          JSON.stringify({
            keys: [],
            datasets: [],
            kg_proposals: [],
            checkpoints: [],
            evaluations: [],
            experiments: [],
            usage: { total_requests: 0, avg_latency_ms: 0, daily_quota: 500, recent: [] },
          }),
          { status: 200 }
        ),
      'GET /api/developer/tools': () =>
        new Response(
          JSON.stringify({ tools: [], invocations: [], workspace_files: [] }),
          { status: 200 }
        ),
      'POST /api/developer/code-training/curate': () =>
        new Response(
          JSON.stringify({
            ok: true,
            dataset: { id: 'ds-code-1', name: 'code-problem-solving-corpus', total_records: 52 },
            code_verification: {
              total_tasks: 14,
              verified_tasks: 14,
              failed_tasks: 0,
              ast_records_added: 24,
              splits_counts: { train: 36, val: 10, test: 6 },
            },
          }),
          { status: 201 }
        ),
      'POST /api/developer/code-training/experiment': () =>
        new Response(
          JSON.stringify({
            ok: true,
            improved: true,
            external_models_used: false,
            experiment: {
              id: 'exp-code-1',
              hypothesis: 'ฝึก Native Transformer ด้านความเข้าใจโค้ดและแก้ปัญหา',
              approval_status: 'PENDING_APPROVAL',
              dataset_id: 'ds-code-1',
            },
            metrics: {
              training_focus: 'code_understanding_and_problem_solving',
              param_count: 42368,
              initial_train_loss: 6.0123,
              final_train_loss: 3.1045,
              initial_val_loss: 5.998,
              final_val_loss: 4.512,
              val_perplexity: 91.1,
              test_loss: 4.72,
              test_perplexity: 112.17,
              test_accuracy: 0.24,
              pre_contrastive_accuracy: 0.33,
              post_contrastive_accuracy: 0.67,
              unseen_execution_verified: true,
              regression_detected: false,
              honest_limitations: ['ข้อจำกัดจริงของ NativeTransformerLM ขนาดเล็กบน CPU'],
            },
          }),
          { status: 201 }
        ),
      'POST /api/developer/code-training/evaluate': () =>
        new Response(
          JSON.stringify({
            ok: true,
            status: 'VERIFIED',
            checkpoint_version: 2,
            unseen_test_loss: 4.65,
            unseen_test_perplexity: 104.58,
            unseen_token_accuracy: 0.25,
            contrastive_probe: { total: 3, passed: 2, accuracy: 0.6667 },
            external_models_used: false,
          }),
          { status: 200 }
        ),
    });

    const sv = render(
      <SettingsView
        token="t-dev-code"
        user={{
          id: 'u-dev',
          email: 'dev@zyrquen.local',
          display_name: 'Dev',
          role: 'user',
          created_at: '2026-11-26T00:00:00Z',
        }}
        activeTab="developer"
        autoExpandTrace={false}
        defaultMode="auto"
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    expect(
      await screen.findByText(/ฝึกโมเดลให้เข้าใจโค้ดและแก้ปัญหา/)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'เตรียมชุดข้อมูลโค้ด & แก้บั๊ก' }));
    expect(
      await screen.findByText(/ผลการตรวจ AST & Sandbox ก่อนฝึก \(14\/14 งานผ่านเงื่อนไข\)/)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'ฝึกทดลอง Native Model ด้านโค้ด' }));
    expect(await screen.findByText(/PENDING_APPROVAL · external_models=false/)).toBeInTheDocument();
    expect(screen.getByText(/6\.0123 → 3\.1045/)).toBeInTheDocument();
    expect(screen.getByText(/ข้อจำกัดจริงของ NativeTransformerLM ขนาดเล็กบน CPU/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'ทดสอบบนโจทย์โค้ด Unseen' }));
    expect(await screen.findByText(/VERIFIED · v2/)).toBeInTheDocument();
    expect(screen.getByText(/contrastive: 2\/3 \(67%\)/)).toBeInTheDocument();

    sv.unmount();
  });

  it('แสดงส่วน Training Artifact History ใน Developer Console และดาวน์โหลด Raw Training Logs / Manifest JSON ตามรุ่นที่เลือก', async () => {
    const requestedUrls: Array<{ url: string; auth: string | null }> = [];
    const createObjectUrlSpy = vi.fn(() => 'blob:zyrquen-test-artifact');
    const revokeObjectUrlSpy = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: createObjectUrlSpy,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: revokeObjectUrlSpy,
    });

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      const headers = new Headers(init?.headers);
      if (url === '/api/developer/overview') {
        return new Response(
          JSON.stringify({
            keys: [],
            datasets: [],
            kg_proposals: [],
            checkpoints: [
              {
                id: 'ckpt-2',
                version: 2,
                dataset_id: 'ds-1',
                vocab_size: 320,
                ngram_order: 0,
                train_loss: 2.15,
                val_loss: 2.41,
                perplexity: 11.13,
                eval_accuracy: 0.42,
                eval_status: 'NEURAL_VERIFIED',
                created_at: '2026-11-26T01:00:00Z',
              },
              {
                id: 'ckpt-1',
                version: 1,
                dataset_id: 'ds-1',
                vocab_size: 120,
                ngram_order: 3,
                train_loss: 3.1,
                val_loss: 3.4,
                perplexity: 29.96,
                eval_accuracy: 0.15,
                eval_status: 'PASS',
                created_at: '2026-11-25T01:00:00Z',
              },
            ],
            evaluations: [],
            experiments: [],
            usage: { total_requests: 0, avg_latency_ms: 0, daily_quota: 500, recent: [] },
          }),
          { status: 200 }
        );
      }
      if (url === '/api/developer/tools') {
        return new Response(
          JSON.stringify({ tools: [], invocations: [], workspace_files: [] }),
          { status: 200 }
        );
      }
      if (url.startsWith('/api/developer/artifacts/')) {
        requestedUrls.push({ url, auth: headers.get('Authorization') });
        if (url.includes('/v2/download?kind=manifest')) {
          return new Response(JSON.stringify({ schema: 'zyrquen.model-artifact-manifest.v1', model_version: 'v2' }), {
            status: 200,
            headers: {
              'Content-Type': 'application/json; charset=utf-8',
              'Content-Disposition': 'attachment; filename="zyrquen-v2-manifest.json"',
            },
          });
        }
        if (url.includes('/v2/download?kind=logs')) {
          return new Response('{"event":"training_step","epoch":1,"train_loss":2.85}\n', {
            status: 200,
            headers: {
              'Content-Type': 'application/x-ndjson; charset=utf-8',
              'Content-Disposition': 'attachment; filename="zyrquen-v2-training-logs.jsonl"',
            },
          });
        }
        if (url.includes('/v1/download?kind=logs')) {
          return new Response(JSON.stringify({ error: 'No raw training logs recorded for Checkpoint v1.' }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' },
          });
        }
      }
      return new Response(JSON.stringify({ error: `Unhandled route: ${url}` }), { status: 404 });
    }) as unknown as typeof fetch;

    const sv = render(
      <SettingsView
        token="t-dev-artifact"
        user={{
          id: 'u-dev',
          email: 'dev@zyrquen.local',
          display_name: 'Dev',
          role: 'user',
          created_at: '2026-11-26T00:00:00Z',
        }}
        activeTab="developer"
        autoExpandTrace={false}
        defaultMode="auto"
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    expect(await screen.findByText('Training Artifact History')).toBeInTheDocument();
    const versionSelect = await screen.findByLabelText('เลือกรุ่นโมเดลใน Training Artifact History');
    expect((versionSelect as HTMLSelectElement).value).toBe('v2');

    fireEvent.click(screen.getByRole('button', { name: 'Download Manifest JSON' }));
    expect(await screen.findByText(/ดาวน์โหลด zyrquen-v2-manifest\.json สำหรับ v2 เรียบร้อยแล้ว/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Download Raw Training Logs' }));
    expect(await screen.findByText(/ดาวน์โหลด zyrquen-v2-training-logs\.jsonl สำหรับ v2 เรียบร้อยแล้ว/)).toBeInTheDocument();

    fireEvent.change(versionSelect, { target: { value: 'v1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Download Raw Training Logs' }));
    expect(await screen.findByText(/No raw training logs recorded for Checkpoint v1\./)).toBeInTheDocument();

    expect(requestedUrls).toEqual([
      { url: '/api/developer/artifacts/v2/download?kind=manifest', auth: 'Bearer t-dev-artifact' },
      { url: '/api/developer/artifacts/v2/download?kind=logs', auth: 'Bearer t-dev-artifact' },
      { url: '/api/developer/artifacts/v1/download?kind=logs', auth: 'Bearer t-dev-artifact' },
    ]);
    expect(createObjectUrlSpy).toHaveBeenCalledTimes(2);
    expect(revokeObjectUrlSpy).toHaveBeenCalledTimes(2);

    sv.unmount();
  });
});





