import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdminStabilityPanel } from '../components/AdminStabilityPanel';
import { MetricHelpTooltip } from '../components/MetricHelpTooltip';
import { SettingsView } from '../components/SettingsView';
import type { AdminOverview, User } from '../types';

const ADMIN_USER: User = {
  id: 'admin-1',
  email: 'admin@zyrquen.local',
  display_name: 'Admin User',
  role: 'admin',
  email_verified: true,
  created_at: '2026-11-27T00:00:00Z',
};

function makeAdminOverview(pendingCount: number): AdminOverview {
  return {
    users: [ADMIN_USER],
    pending_runs: Array.from({ length: pendingCount }, (_, index) => ({
      id: `run-${index + 1}`,
      group_id: 'native_training',
      status: 'PENDING_APPROVAL',
      requires_approval: 1,
      triggered_by: 'admin-1',
      approved_by: null,
      summary: `Tier-2 Approval run #${index + 1}`,
      stages_json: '[]',
      created_at: '2026-11-27T00:00:00Z',
      updated_at: '2026-11-27T00:00:00Z',
    })),
    pending_tool_invocations: [],
    pending_experiments: [],
    pending_kg_proposals: [],
    tools: [],
    audit_logs: [],
    system: {
      python_version: '3.11.2',
      platform: 'Linux',
      cpu_count: 4,
      load_1m: 0.15,
      mem_total_mb: 8192,
      mem_available_mb: 6144,
      disk_free_gb: 120.5,
      disk_total_gb: 256.0,
      sqlite_db_kb: 512,
    },
    training_readiness: {
      gate_status: 'READY_FOR_TRAINING_GATE',
      datasets_total: 1,
      clean_datasets: 1,
      triples_total: 5,
      verified_triples: 5,
      experiments_total: 0,
      approved_experiments: 0,
      pending_experiments: 0,
      pending_training_runs: pendingCount,
      checkpoints_total: 0,
      neural_checkpoints: 0,
      datasets: [],
      checkpoints: [],
      experiments: [],
    },
  };
}

describe('Admin Dashboard Accessibility & Tier-2 Approval Bell', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('toggles metric explanation tooltip on click/focus and closes on Escape', () => {
    render(
      <MetricHelpTooltip
        label="RAM ว่าง / ทั้งหมด"
        description="ปริมาณหน่วยความจำที่เหลือใช้งานได้จริงของเซิร์ฟเวอร์"
      />
    );

    const trigger = screen.getByRole('button', {
      name: /คำอธิบายตัวชี้วัด RAM ว่าง \/ ทั้งหมด/i,
    });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'ปริมาณหน่วยความจำที่เหลือใช้งานได้จริงของเซิร์ฟเวอร์'
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('displays pending Tier-2 Approval workflow count on bell button and metric help tooltips in admin dashboard', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes('/api/admin/overview')) {
        return new Response(JSON.stringify(makeAdminOverview(2)), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(
      <SettingsView
        token="test-token"
        user={ADMIN_USER}
        activeTab="admin"
        autoExpandTrace={true}
        defaultMode="auto"
        onChangeTab={vi.fn()}
        onUpdatePreferences={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    const bellButton = await screen.findByRole('button', {
      name: /Tier-2 Approval workflows awaiting review: 2/i,
    });
    expect(bellButton).toBeInTheDocument();
    expect(bellButton).toHaveTextContent('2');

    const cpuHelpButton = screen.getByRole('button', {
      name: /คำอธิบายตัวชี้วัด CPU ภายใน/i,
    });
    fireEvent.click(cpuHelpButton);
    expect(screen.getByRole('tooltip')).toHaveTextContent('คอร์ CPU');
  });

  it('renders help tooltips on all four AdminStabilityPanel KPI metric cards', () => {
    render(
      <AdminStabilityPanel
        adminData={makeAdminOverview(0)}
        perfSamples={[]}
        clientLatencies={[]}
        cleanupVerification={null}
      />
    );

    expect(
      screen.getByRole('button', { name: /คำอธิบายตัวชี้วัด การใช้งาน JS Heap/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /คำอธิบายตัวชี้วัด สถานะหน่วยความจำ & Thread Cleanup/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /คำอธิบายตัวชี้วัด เวลาแฝงประมวลผล/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /คำอธิบายตัวชี้วัด คอขวดสูงสุดใน Reasoning Trace/i })
    ).toBeInTheDocument();
  });
});
