import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { ModelRegistryModal } from '../components/ModelRegistryModal';
import { SettingsView } from '../components/SettingsView';
import type { CheckpointItem, DatasetItem, EvaluationItem } from '../types';

const SAMPLE_DATASETS: DatasetItem[] = [
  {
    id: 'ds-alpha',
    name: 'zyrquen-core-corpus-v1',
    manifest_hash: 'abcdef1234567890',
    total_records: 120,
    train_count: 84,
    val_count: 18,
    test_count: 18,
    leakage_detected: 0,
    status: 'VERIFIED',
    created_at: '2026-11-24T00:00:00Z',
  },
];

const SAMPLE_CHECKPOINTS: CheckpointItem[] = [
  {
    id: 'ckpt-2',
    version: 2,
    dataset_id: 'ds-alpha',
    vocab_size: 512,
    ngram_order: 0,
    train_loss: 1.85,
    val_loss: 2.12,
    perplexity: 8.33,
    eval_accuracy: 0.64,
    eval_status: 'NEURAL_VERIFIED',
    created_at: '2026-11-26T01:00:00Z',
  },
  {
    id: 'ckpt-1',
    version: 1,
    dataset_id: 'ds-alpha',
    vocab_size: 256,
    ngram_order: 3,
    train_loss: 2.95,
    val_loss: 3.15,
    perplexity: 23.34,
    eval_accuracy: 0.42,
    eval_status: 'PASS',
    created_at: '2026-11-25T01:00:00Z',
  },
];

const SAMPLE_EVALUATIONS: EvaluationItem[] = [
  {
    id: 'eval-2',
    checkpoint_version: 2,
    suite_name: 'native_suite_v2',
    overall_status: 'PASS',
    math_score: 0.9,
    knowledge_score: 0.85,
    planning_score: 0.8,
    test_accuracy: 0.72,
    perplexity: 8.33,
    baseline_delta_json: null,
    created_at: '2026-11-26T02:00:00Z',
  },
  {
    id: 'eval-1',
    checkpoint_version: 1,
    suite_name: 'native_suite_v1',
    overall_status: 'PASS',
    math_score: 0.7,
    knowledge_score: 0.75,
    planning_score: 0.8,
    test_accuracy: 0.55,
    perplexity: 23.34,
    baseline_delta_json: null,
    created_at: '2026-11-25T02:00:00Z',
  },
];

describe('ModelRegistryModal side-by-side version comparison', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('renders side-by-side comparison with deltas, zero-regression verdict, swap, and registry tab', () => {
    const onDownload = vi.fn();
    const onClose = vi.fn();

    render(
      <ModelRegistryModal
        open={true}
        initialTab="compare"
        checkpoints={SAMPLE_CHECKPOINTS}
        evaluations={SAMPLE_EVALUATIONS}
        datasets={SAMPLE_DATASETS}
        onDownloadArtifact={onDownload}
        onClose={onClose}
      />
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/Model Registry & Version Comparison/)).toBeInTheDocument();

    const baseSelect = within(dialog).getByLabelText('เลือกเวอร์ชันฐาน (Version A)') as HTMLSelectElement;
    const candSelect = within(dialog).getByLabelText('เลือกเวอร์ชันเปรียบเทียบ (Version B)') as HTMLSelectElement;
    expect(baseSelect.value).toBe('v1');
    expect(candSelect.value).toBe('v2');

    // Verdict strip reflects real improvements and 0 regressions
    expect(within(dialog).getByText(/ZERO REGRESSION/)).toBeInTheDocument();
    expect(within(dialog).getByText('ดีขึ้น 7')).toBeInTheDocument();
    expect(within(dialog).getByText('คงที่ 1')).toBeInTheDocument();
    expect(within(dialog).getByText('ถดถอย 0')).toBeInTheDocument();

    // Side-by-side performance metrics & deltas
    expect(within(dialog).getByText('Validation Loss')).toBeInTheDocument();
    expect(within(dialog).getByText('-1.0300')).toBeInTheDocument();
    expect(within(dialog).getByText('+22.0 pp')).toBeInTheDocument();

    // Swap A <-> B flips direction and detects regression from v2 -> v1
    fireEvent.click(within(dialog).getByLabelText('สลับเวอร์ชัน A และ B'));
    expect(baseSelect.value).toBe('v2');
    expect(candSelect.value).toBe('v1');
    expect(within(dialog).getByText(/REGRESSION DETECTED/)).toBeInTheDocument();

    // Switch to Registry list view and assign comparison from table row
    fireEvent.click(within(dialog).getByRole('tab', { name: /รายการเวอร์ชัน/ }));
    expect(within(dialog).getByRole('table')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'เทียบ v1' }));
    expect(within(dialog).getByText(/ZERO REGRESSION/)).toBeInTheDocument();

    // Artifact download inside modal passes exact version label
    fireEvent.click(within(dialog).getByRole('button', { name: 'Manifest v2' }));
    expect(onDownload).toHaveBeenCalledWith('manifest', 'v2');

    // Escape closes modal
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('handles single-version and empty-registry states honestly without fake metrics', () => {
    const { rerender } = render(
      <ModelRegistryModal
        open={true}
        checkpoints={[]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText('ยังไม่มีเวอร์ชันโมเดลใน Model Registry')).toBeInTheDocument();

    rerender(
      <ModelRegistryModal
        open={true}
        checkpoints={[SAMPLE_CHECKPOINTS[0]]}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText(/มีเพียง 1 เวอร์ชันใน Registry \(v2\)/)).toBeInTheDocument();
    expect(screen.getByText(/SAME VERSION/)).toBeInTheDocument();
  });

  it('opens Model Registry modal directly from SettingsView Developer Console', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/developer/overview') {
        return new Response(
          JSON.stringify({
            keys: [],
            datasets: SAMPLE_DATASETS,
            kg_proposals: [],
            checkpoints: SAMPLE_CHECKPOINTS,
            evaluations: SAMPLE_EVALUATIONS,
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
      return new Response(JSON.stringify({ error: `Unhandled: ${url}` }), { status: 404 });
    }) as unknown as typeof fetch;

    const sv = render(
      <SettingsView
        token="t-registry"
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

    const compareBtn = await screen.findByRole('button', { name: 'เปรียบเทียบเวอร์ชัน' });
    await screen.findByRole('button', { name: /Checkpoint v2/ });
    fireEvent.click(compareBtn);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Performance Visualization \(v1 vs v2\)/)).toBeInTheDocument();

    sv.unmount();
  });
});
