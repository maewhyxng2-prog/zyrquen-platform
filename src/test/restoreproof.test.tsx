import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RestoreProofPanel } from '../components/RestoreProofPanel';
import type { RestoreProofUiPayload } from '../types';

const EMPTY_PAYLOAD: RestoreProofUiPayload = {
  schema_version: '1.0.0',
  product: 'RealityCheck — RestoreProof',
  source_mode: 'live_verification',
  is_demo: false,
  generated_at: '2026-11-26T06:00:00+00:00',
  summary: {
    total_runs: 0,
    runs_today: 0,
    passed_runs: 0,
    failed_runs: 0,
    pass_rate_pct: null,
    avg_duration_sec: null,
    avg_duration_label: null,
  },
  latest_run: null,
  steps: [],
  technical_details: null,
  history: [],
  reliability: {
    score_pct: null,
    score_label: null,
    computation_rule: 'no_verified_runs_yet',
    checks: [],
    verdict_text: 'ยังไม่มีหลักฐานการตรวจสอบจริง ไม่สามารถยืนยันความพร้อมใช้งานได้',
  },
};

const FAILED_SCENARIO_PAYLOAD: RestoreProofUiPayload = {
  schema_version: '1.0.0',
  product: 'RealityCheck — RestoreProof',
  source_mode: 'live_verification',
  is_demo: false,
  generated_at: '2026-11-26T06:10:00+00:00',
  summary: {
    total_runs: 1,
    runs_today: 1,
    passed_runs: 0,
    failed_runs: 1,
    pass_rate_pct: 0,
    avg_duration_sec: 0.04,
    avg_duration_label: '40 ms',
  },
  latest_run: {
    run_id: 'run_202611260610',
    status: 'failed',
    status_label: 'ไม่ผ่านการตรวจสอบ',
    headline: 'พบความคลาดเคลื่อนหรือการกู้คืนไม่สำเร็จตามหลักฐานจริง',
    checked_at: '2026-11-26T06:10:00+00:00',
    source_name: 'Tampered/Missing Manifest Probe (Failure Case 2)',
    data_size_bytes: 512,
    data_size_label: '512 B',
    duration_sec: 0.04,
    duration_label: '40 ms',
    discrepancies: [
      "Missing files after restore: ['app.sqlite']",
      "Hash mismatches after restore: ['config.json']",
    ],
  },
  steps: [
    {
      step_key: 'integrity_check',
      title: 'ตรวจสอบข้อมูล Backup (Integrity Check)',
      status: 'failed',
      duration_sec: 0.01,
      duration_label: '10 ms',
      detail: "พบไฟล์ที่ checksum ไม่ตรง: ['config.json']",
    },
    {
      step_key: 'isolated_restore',
      title: 'ทดลอง Restore ในระบบแยก',
      status: 'passed',
      duration_sec: 0.02,
      duration_label: '20 ms',
      detail: 'ทดลองแตกไฟล์และกู้คืนในพื้นที่แยกสำเร็จ',
    },
    {
      step_key: 'data_completeness',
      title: 'ตรวจสอบความครบถ้วนของข้อมูล',
      status: 'failed',
      duration_sec: 0.01,
      duration_label: '10 ms',
      detail: 'ข้อมูลหลังกู้คืนไม่ครบหรือไม่ตรงตาม manifest',
    },
    {
      step_key: 'service_health',
      title: 'ตรวจสอบการทำงานของบริการ',
      status: 'passed',
      duration_sec: 0.0,
      duration_label: '0 ms',
      detail: 'ผ่านการกู้คืน (ไม่ได้ระบุคำสั่ง health-cmd แยก)',
    },
  ],
  technical_details: {
    backup_type: 'SQLite + Config (.zip)',
    file_size_label: '512 B',
    checksum_sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    checksum_short: 'e3b0c44298....b855',
    restore_time_label: '20 ms',
    data_integrity_pct: 33.33,
    data_integrity_label: '33.33%',
    service_status: 'OK',
  },
  history: [
    { date: '2026-11-26', label: '26/11', passed_count: 0, failed_count: 1, pass_rate_pct: 0 },
  ],
  reliability: {
    score_pct: 0,
    score_label: '0%',
    computation_rule: 'min(historical_pass_rate_pct, latest_verified_subchecks_pct)',
    checks: [
      { key: 'restore_verified', label: 'Restore สำเร็จ', passed: true },
      { key: 'data_complete', label: 'ข้อมูลครบถ้วน', passed: false },
      { key: 'service_healthy', label: 'บริการทำงานปกติ', passed: true },
    ],
    verdict_text: 'ไม่ผ่านการตรวจสอบจริง — ห้ามถือว่า Backup พร้อมใช้งานจนกว่าจะแก้ไขข้อขัดแย้ง',
  },
};

describe('RestoreProofPanel UI Fail-Closed & Interaction', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts strictly fail-closed when no runs exist and never fabricates PASS or 100%', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true, ui_payload: EMPTY_PAYLOAD }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    );

    render(<RestoreProofPanel token="test-token" />);

    await waitFor(() => {
      expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent(
        'UNVERIFIED / NO DATA'
      );
    });
    expect(screen.getByTestId('restoreproof-reliability-score')).toHaveTextContent('—');
    expect(screen.queryByTestId('restoreproof-demo-banner')).not.toBeInTheDocument();
    expect(screen.getByText(/ยังไม่มีผลการตรวจสอบ Backup จริง/i)).toBeInTheDocument();
  });

  it('toggles Demo Fixture with explicit warning banner and returns cleanly to live fail-closed state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true, ui_payload: EMPTY_PAYLOAD }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    );

    render(<RestoreProofPanel token="test-token" />);
    await waitFor(() => {
      expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent(
        'UNVERIFIED / NO DATA'
      );
    });

    fireEvent.click(screen.getByRole('button', { name: /ดูตัวอย่าง \(Demo Fixture\)/i }));
    expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent('DEMO FIXTURE');
    expect(screen.getByTestId('restoreproof-demo-banner')).toBeInTheDocument();
    expect(screen.getByTestId('restoreproof-reliability-score')).toHaveTextContent('83.33%');

    fireEvent.click(screen.getByRole('button', { name: /ปิดโหมดตัวอย่าง/i }));
    expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent(
      'UNVERIFIED / NO DATA'
    );
    expect(screen.queryByTestId('restoreproof-demo-banner')).not.toBeInTheDocument();
  });

  it('executes failure scenario and renders live discrepancies accurately', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/restoreproof/status')) {
        return new Response(JSON.stringify({ ok: true, ui_payload: EMPTY_PAYLOAD }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('/api/restoreproof/verify-scenario')) {
        return new Response(
          JSON.stringify({
            ok: true,
            reports: [{ overall_passed: false }],
            ui_payload: FAILED_SCENARIO_PAYLOAD,
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } }
        );
      }
      return new Response('{}', { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<RestoreProofPanel token="test-token" />);
    await waitFor(() => {
      expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent(
        'UNVERIFIED / NO DATA'
      );
    });

    fireEvent.click(screen.getByRole('button', { name: /Case 2: ไฟล์หาย/i }));

    await waitFor(() => {
      expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent('LIVE VERIFICATION');
    });
    expect(screen.getByTestId('restoreproof-reliability-score')).toHaveTextContent('0%');
    const discBox = screen.getByTestId('restoreproof-discrepancies');
    expect(discBox).toHaveTextContent('app.sqlite');
    expect(discBox).toHaveTextContent('config.json');
  });

  it('rejects malformed uploaded JSON file without crashing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true, ui_payload: EMPTY_PAYLOAD }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    );

    render(<RestoreProofPanel token="test-token" />);
    await waitFor(() => {
      expect(screen.getByTestId('restoreproof-mode-badge')).toHaveTextContent(
        'UNVERIFIED / NO DATA'
      );
    });

    const input = screen.getByLabelText(/อัปโหลดไฟล์ restoreproof_ui_payload\.json/i);
    const badFile = new File(['{invalid_json'], 'bad.json', { type: 'application/json' });
    fireEvent.change(input, { target: { files: [badFile] } });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/ไม่สามารถอ่านไฟล์/i);
    });
  });
});
