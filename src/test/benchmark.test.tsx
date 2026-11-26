import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsView } from '../components/SettingsView';
import {
  assertBenchmarkReportIntegrity,
  evaluateAbstentionAccuracy,
  evaluateSourceVerification,
  runNativeCapabilityBenchmark,
} from '../lib/benchmark';
import type { NativeBenchmarkReport } from '../types';

function buildRealisticReport(
  overrides: Partial<NativeBenchmarkReport> = {}
): NativeBenchmarkReport {
  const cases: NativeBenchmarkReport['cases'] = [
    {
      id: 'RSN-01',
      category: 'reasoning',
      polarity: 'positive',
      input: 'คำนวณ (2^12 - 96) / 16',
      passed: true,
      expected: 'VERIFIED (250)',
      actual: 'VERIFIED (250)',
      failure_type: null,
      engine_path: ['math_ast'],
      detail: '250',
    },
    {
      id: 'RSN-09',
      category: 'reasoning',
      polarity: 'positive',
      input: 'แก้สมการ: x^2 - 5x + 6 = 0',
      passed: false,
      expected: 'VERIFIED (roots(2,3))',
      actual: 'NOT_LEARNED (None)',
      failure_type: 'REASONING_CAPABILITY_GAP',
      engine_path: ['algebra_blocked'],
      detail: 'Not supported yet in P1',
    },
    {
      id: 'NEG-01',
      category: 'negative_abstention',
      polarity: 'negative',
      input: '[auto] ทฤษฎีสัมพัทธภาพทั่วไปคืออะไร',
      passed: true,
      expected: 'NOT_LEARNED',
      actual: 'NOT_LEARNED',
      failure_type: null,
      engine_path: ['abstention'],
      detail: 'ไม่พบข้อมูล',
    },
    {
      id: 'NEG-02',
      category: 'negative_abstention',
      polarity: 'negative',
      input: '[knowledge] มหาสมุทรแปซิฟิก อยู่ที่ไหน',
      passed: true,
      expected: 'NOT_LEARNED',
      actual: 'NOT_LEARNED',
      failure_type: null,
      engine_path: ['abstention'],
      detail: 'ไม่พบข้อมูล',
    },
    {
      id: 'LEAK-04',
      category: 'leakage_detection',
      polarity: 'positive',
      input: "Near-Duplicate Punctuation Leakage Probe ('!!')",
      passed: true,
      expected: 'Either deduplicated (>=1) or flagged leakage_detected=1',
      actual: 'removed=1, leakage_detected=0',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-01',
      category: 'anti_fabrication',
      polarity: 'negative',
      input: 'Fabricated Source Detection (missing/invalid URL & blocked provider)',
      passed: true,
      expected: 'Reject/quarantine fabricated sources',
      actual: 'trust_grade=BLOCKED, providers=[]',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-02',
      category: 'anti_fabrication',
      polarity: 'invariant',
      input: 'Invalid URL & Non-Allowlisted Domain Rejection',
      passed: true,
      expected: 'All invalid/disallowed URLs rejected (False x4)',
      actual: '(False, False, False, False)',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-03',
      category: 'anti_fabrication',
      polarity: 'invariant',
      input: 'Unsupported Recommendation Rejection (0 evidence items)',
      passed: true,
      expected: 'trust_grade=INSUFFICIENT_EVIDENCE',
      actual: 'trust_grade=INSUFFICIENT_EVIDENCE',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-04',
      category: 'anti_fabrication',
      polarity: 'positive',
      input: 'Stale Evidence Handling (2020-01-01 retrieved_at)',
      passed: true,
      expected: 'Evidence flagged STALE',
      actual: 'trust_grade=STALE',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-05',
      category: 'anti_fabrication',
      polarity: 'invariant',
      input: 'Missing Evidence Abstention',
      passed: true,
      expected: 'overall_status=PARTIAL, heldout_test=NOT_RUN',
      actual: 'overall=PARTIAL, heldout=NOT_RUN',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-06',
      category: 'anti_fabrication',
      polarity: 'invariant',
      input: 'Mock Data Isolation & Zero External Model Leakage',
      passed: true,
      expected: 'Fixtures isolated',
      actual: 'isolated=True',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
    {
      id: 'AFB-07',
      category: 'anti_fabrication',
      polarity: 'invariant',
      input: 'False Success Prevention',
      passed: true,
      expected: '(BLOCKED, FAILED, PENDING_APPROVAL)',
      actual: '(BLOCKED, FAILED, PENDING_APPROVAL)',
      failure_type: null,
      engine_path: [],
      detail: '',
    },
  ];

  const baseCases = overrides.cases ?? cases;
  const passed = baseCases.filter((c) => c.passed).length;
  const failed = baseCases.length - passed;
  const negCases = baseCases.filter((c) => c.polarity === 'negative');
  const falsePositives = negCases.filter((c) => !c.passed).length;
  const posCases = baseCases.filter((c) => c.polarity === 'positive');
  const falseNegatives = posCases.filter((c) => !c.passed).length;

  return {
    benchmark_version: 'P1-1-baseline-v1',
    environment: {
      python_version: '3.11.2',
      platform: 'Linux',
      model_version: 'zyrquen-omega-v1',
      checkpoint_version: 1,
      checkpoint_vocab_size: 42,
      external_models_used: false,
      ...(overrides.environment || {}),
    },
    summary: {
      total_cases: baseCases.length,
      passed,
      failed,
      overall_score: Math.round((passed / baseCases.length) * 10000) / 10000,
      false_positives: falsePositives,
      negative_cases_total: negCases.length,
      false_positive_rate:
        negCases.length > 0 ? Math.round((falsePositives / negCases.length) * 10000) / 10000 : 0,
      false_negatives: falseNegatives,
      positive_cases_total: posCases.length,
      false_negative_rate:
        posCases.length > 0 ? Math.round((falseNegatives / posCases.length) * 10000) / 10000 : 0,
      ...(overrides.summary || {}),
    },
    category_scores: overrides.category_scores || {
      reasoning: { total: 2, passed: 1, failed: 1, score: 0.5 },
      negative_abstention: { total: 2, passed: 2, failed: 0, score: 1 },
      leakage_detection: { total: 1, passed: 1, failed: 0, score: 1 },
      anti_fabrication: { total: 7, passed: 7, failed: 0, score: 1 },
    },
    leakage_detection: overrides.leakage_detection || {
      fixture_isolation: { isolated: true, overlaps: [] },
      clean_split_leakage_detected: 0,
      exact_dedup_passed: true,
      near_dup_leakage_caught: true,
    },
    builtin_core_eval: overrides.builtin_core_eval || {
      overall_status: 'VERIFIED',
      math_score: 1,
      knowledge_score: 1,
      planning_score: 1,
      test_accuracy: 0.8,
      perplexity: 2.5,
    },
    failure_types: overrides.failure_types || { REASONING_CAPABILITY_GAP: 1 },
    failures: overrides.failures || baseCases.filter((c) => !c.passed),
    unmeasurable_limitations: overrides.unmeasurable_limitations || [
      'Live HTTPS network quality not scored offline.',
    ],
    cases: baseCases,
  };
}

describe('src/lib/benchmark.ts — Anti-Fabrication, Source Verification & Abstention Accuracy', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('คำนวณ Source Verification และ Abstention Accuracy จากรายงานจริงและพิมพ์ลง Console', async () => {
    const report = buildRealisticReport();
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const groupSpy = vi.spyOn(console, 'group').mockImplementation(() => {});
    const groupEndSpy = vi.spyOn(console, 'groupEnd').mockImplementation(() => {});

    globalThis.fetch = vi.fn(async (input, init) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/developer/benchmark');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(String(init?.body))).toEqual({ modelVersion: 'zyrquen-kg-v2' });
      return new Response(
        JSON.stringify({ ok: true, executed_at: '2026-11-24T04:00:00Z', report }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }) as unknown as typeof fetch;

    const result = await runNativeCapabilityBenchmark('dev-token', {
      modelVersion: 'zyrquen-kg-v2',
    });

    expect(result.integrityVerified).toBe(true);
    expect(result.sourceVerification.status).toBe('VERIFIED');
    expect(result.sourceVerification.passed).toBe(7);
    expect(result.sourceVerification.checks.fabricatedSourceRejected).toBe(true);
    expect(result.sourceVerification.checks.staleEvidenceFlagged).toBe(true);
    expect(result.abstentionAccuracy.status).toBe('VERIFIED');
    expect(result.abstentionAccuracy.overallAbstentionAccuracy).toBe(1);
    expect(result.abstentionAccuracy.falsePositives).toBe(0);
    expect(result.abstentionAccuracy.negativeCasesTotal).toBe(3);

    expect(groupSpy).toHaveBeenCalledTimes(1);
    expect(infoSpy).toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled(); // Because RSN-09 failed honestly
    expect(groupEndSpy).toHaveBeenCalledTimes(1);
  });

  it('ปฏิเสธรายงานที่แอบใช้ External Model หรือตัวเลขสรุปไม่ตรงกับเคสจริง (Anti-Fabrication)', () => {
    const externalReport = buildRealisticReport({
      environment: {
        python_version: '3.11.2',
        platform: 'Linux',
        model_version: 'zyrquen-omega-v1',
        checkpoint_version: 1,
        checkpoint_vocab_size: 42,
        external_models_used: true,
      },
    });
    expect(() => assertBenchmarkReportIntegrity(externalReport)).toThrow(
      /External model dependency detected/
    );

    const tamperedSummary = buildRealisticReport();
    tamperedSummary.summary.passed = 999;
    expect(() => assertBenchmarkReportIntegrity(tamperedSummary)).toThrow(
      /Summary counts do not match/
    );
  });

  it('ตรวจจับการละเมิด Abstention (False Positive) และ Source Verification ล้มเหลวได้แม่นยำ', () => {
    const base = buildRealisticReport();
    const breachedCases = base.cases.map((c) => {
      if (c.id === 'NEG-01') return { ...c, passed: false, actual: 'VERIFIED' };
      if (c.id === 'AFB-01') return { ...c, passed: false, actual: 'CORROBORATED_MULTI_SOURCE' };
      return c;
    });
    const breached = buildRealisticReport({ cases: breachedCases });

    const sv = evaluateSourceVerification(breached);
    const aa = evaluateAbstentionAccuracy(breached);

    expect(sv.status).toBe('FAILED');
    expect(sv.checks.fabricatedSourceRejected).toBe(false);
    expect(aa.status).toBe('FAILED');
    expect(aa.falsePositives).toBe(2);
    expect(aa.overallAbstentionAccuracy).toBeLessThan(1);
  });

  it('ไม่จำลองคะแนนเมื่อ Backend ล้มเหลว และแสดงผลในหน้านักพัฒนา SettingsView อย่างซื่อสัตย์', async () => {
    const report = buildRealisticReport();
    let shouldFail = true;

    vi.spyOn(console, 'info').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'group').mockImplementation(() => {});
    vi.spyOn(console, 'groupEnd').mockImplementation(() => {});

    globalThis.fetch = vi.fn(async (input) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/developer/overview') {
        return new Response(
          JSON.stringify({
            keys: [],
            datasets: [],
            checkpoints: [],
            evaluations: [],
            usage: { total_requests: 0, avg_latency_ms: 0, daily_quota: 1000, recent: [] },
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
      if (url === '/api/developer/benchmark') {
        if (shouldFail) {
          return new Response(
            JSON.stringify({ error: 'Python benchmark process crashed' }),
            { status: 500 }
          );
        }
        return new Response(
          JSON.stringify({ ok: true, executed_at: '2026-11-24T04:00:00Z', report }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({ error: 'Not found' }), { status: 404 });
    }) as unknown as typeof fetch;

    await expect(runNativeCapabilityBenchmark('dev-token')).rejects.toThrow(
      'Python benchmark process crashed'
    );

    render(
      <SettingsView
        token="dev-token"
        user={{
          id: 'u-dev',
          email: 'dev@zyrquen.local',
          display_name: 'นักพัฒนา',
          role: 'user',
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
      await screen.findByText(/Capability Benchmark \(Zero-Mock Native Probe\)/i)
    ).toBeInTheDocument();

    // First click hits 500 error: must show error and NEVER fabricate metrics
    fireEvent.click(screen.getByRole('button', { name: /รัน Benchmark จริง/i }));
    expect(await screen.findByText('Python benchmark process crashed')).toBeInTheDocument();
    expect(screen.queryByText(/Source Verification \(Anti-Fabrication\)/i)).not.toBeInTheDocument();

    // Second click succeeds against real endpoint payload
    shouldFail = false;
    fireEvent.click(screen.getByRole('button', { name: /รัน Benchmark จริง/i }));

    await waitFor(() => {
      expect(screen.getByText(/Source Verification \(Anti-Fabrication\)/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/VERIFIED \(7\/7\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/100\.0%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Zero External LLMs/)).toBeInTheDocument();
    expect(screen.getByText(/1 FAILED/)).toBeInTheDocument();
    expect(screen.getByText(/\[RSN-09\]/)).toBeInTheDocument();
    expect(screen.getByText(/Live HTTPS network quality not scored offline\./)).toBeInTheDocument();
  });

  it('Online-First: แสดงสถานะการเชื่อมต่อล้มเหลวและปุ่มเชื่อมต่อใหม่เมื่อ Cloud Core ขาดการเชื่อมต่อ และไม่จำลองคำตอบ AI', async () => {
    const { default: App } = await import('../App');
    const { streamConversationMessage, ApiError } = await import('../lib/api');

    let serverReachable = false;
    globalThis.fetch = vi.fn(async (input) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (!serverReachable) {
        throw new TypeError('Failed to fetch');
      }
      if (url === '/api/auth/status') {
        return new Response(
          JSON.stringify({ initialized: false, userCount: 0, envPasscodeConfigured: false }),
          { status: 200 }
        );
      }
      if (url === '/api/health') {
        return new Response(JSON.stringify({ ok: true, nativeCore: 'ready' }), { status: 200 });
      }
      return new Response(JSON.stringify({ error: 'Not found' }), { status: 404 });
    }) as unknown as typeof fetch;

    render(<App />);
    expect(
      await screen.findByText('ไม่สามารถเชื่อมต่อกับระบบออนไลน์ได้')
    ).toBeInTheDocument();

    // Streaming AI request during network drop must reject with status 0 and never fabricate text
    await expect(
      streamConversationMessage('c1', {
        token: 'tok',
        content: 'คำนวณ 1 + 1',
        mode: 'math',
        modelVariant: 'zyrquen-omega-v1',
      })
    ).rejects.toMatchObject({ status: 0 } satisfies Partial<InstanceType<typeof ApiError>>);

    serverReachable = true;
    fireEvent.click(screen.getByRole('button', { name: 'เชื่อมต่อใหม่อีกครั้ง' }));
    expect(await screen.findByText('ตั้งค่าผู้ดูแลระบบเริ่มต้น')).toBeInTheDocument();
  });
});
