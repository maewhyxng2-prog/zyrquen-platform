import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkflowLogsConsole } from '../components/WorkflowLogsConsole';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('WorkflowLogsConsole', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('renders Loading state first and then authentic Empty state when backend returns zero runs', async () => {
    let resolveFetch!: (res: Response) => void;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );

    render(<WorkflowLogsConsole token="tok-empty" />);

    expect(
      screen.getByText(/กำลังเชื่อมต่อ \/api\/v1\/workflows\/logs/i)
    ).toBeTruthy();

    await act(async () => {
      resolveFetch(
        jsonResponse({
          items: [],
          active_runs: [],
          active_only: true,
          polled_at: '2026-11-27T02:00:00Z',
        })
      );
    });

    await waitFor(() => {
      expect(
        screen.getByText('ยังไม่มี Workflow ที่กำลังทำงานในขณะนี้')
      ).toBeTruthy();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/workflows/logs?active_only=true&limit=100'),
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('renders Unauthorized state honestly when token is empty or HTTP 401 is returned', async () => {
    const onAuthError = vi.fn();
    const { rerender } = render(
      <WorkflowLogsConsole token="" onAuthError={onAuthError} />
    );

    expect(screen.getByText('ต้องยืนยันตัวตน (401)')).toBeTruthy();
    expect(
      screen.getByText(/กรุณาเข้าสู่ระบบเพื่อดู Execution Logs จริง/i)
    ).toBeTruthy();

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ error: 'Not authenticated' }, 401)
    );

    rerender(<WorkflowLogsConsole token="expired-tok" onAuthError={onAuthError} />);

    await waitFor(() => {
      expect(onAuthError).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText('ต้องยืนยันตัวตน (401)')).toBeTruthy();
  });

  it('renders Error state on HTTP 403/500 without fabricating fallback logs', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ error: 'Forbidden' }, 403)
    );

    render(<WorkflowLogsConsole token="tok-user" />);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
    });
    expect(
      screen.getByText('ไม่มีสิทธิ์เข้าถึง Execution Logs ของ Workflow ที่ระบุ')
    ).toBeTruthy();
    expect(screen.queryByRole('log')).toBeNull();
  });

  it('supports active workflow selection, level filtering, message search, and filter reset', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('run_id=run-b')) {
        return jsonResponse({
          items: [
            {
              id: 'log-b1',
              run_id: 'run-b-9999',
              workflow_key: 'evaluation.verify',
              step_key: 'eval_step',
              level: 'ERROR',
              event_type: 'step.failed',
              status: 'FAILED',
              message: 'Checkpoint hash mismatch detected',
              timestamp: '2026-11-27T02:01:00Z',
            },
          ],
          active_runs: [
            {
              id: 'run-a-1111',
              workflow_key: 'system_ops',
              status: 'RUNNING',
              started_at: '2026-11-27T02:00:00Z',
            },
            {
              id: 'run-b-9999',
              workflow_key: 'evaluation.verify',
              status: 'RUNNING',
              started_at: '2026-11-27T02:00:10Z',
            },
          ],
          active_only: true,
          polled_at: '2026-11-27T02:01:05Z',
        });
      }

      return jsonResponse({
        items: [
          {
            id: 'log-1',
            run_id: 'run-a-1111',
            workflow_key: 'system_ops',
            step_key: 'health_check',
            level: 'INFO',
            event_type: 'step.completed',
            status: 'COMPLETED',
            message: 'Native runtime check passed',
            timestamp: '2026-11-27T02:00:00Z',
          },
          {
            id: 'log-2',
            run_id: 'run-b-9999',
            workflow_key: 'evaluation.verify',
            step_key: 'eval_step',
            level: 'ERROR',
            event_type: 'step.failed',
            status: 'FAILED',
            message: 'Checkpoint hash mismatch detected',
            timestamp: '2026-11-27T02:01:00Z',
          },
        ],
        active_runs: [
          {
            id: 'run-a-1111',
            workflow_key: 'system_ops',
            status: 'RUNNING',
            started_at: '2026-11-27T02:00:00Z',
          },
          {
            id: 'run-b-9999',
            workflow_key: 'evaluation.verify',
            status: 'RUNNING',
            started_at: '2026-11-27T02:00:10Z',
          },
        ],
        active_only: true,
        polled_at: '2026-11-27T02:01:05Z',
      });
    });

    render(<WorkflowLogsConsole token="tok-valid" />);

    await waitFor(() => {
      expect(screen.getByText('Native runtime check passed')).toBeTruthy();
      expect(screen.getByText('Checkpoint hash mismatch detected')).toBeTruthy();
    });

    // Level filter -> ERROR
    fireEvent.click(screen.getByRole('button', { name: 'ERROR' }));
    await waitFor(() => {
      expect(screen.queryByText('Native runtime check passed')).toBeNull();
      expect(screen.getByText('Checkpoint hash mismatch detected')).toBeTruthy();
    });

    // Search non-matching text -> Empty filter state with reset button
    const searchInput = screen.getByLabelText('ค้นหาข้อความหรือ workflow ใน Logs');
    fireEvent.change(searchInput, { target: { value: 'does-not-exist' } });
    await waitFor(() => {
      expect(screen.getByText('ไม่พบ Orchestration Logs ที่ตรงกับเงื่อนไข')).toBeTruthy();
    });

    fireEvent.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }));
    await waitFor(() => {
      expect(screen.getByText('Native runtime check passed')).toBeTruthy();
    });

    // Select specific active workflow run_id
    fireEvent.change(screen.getByLabelText('เลือก Workflow Run'), {
      target: { value: 'run-b-9999' },
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes('run_id=run-b-9999'))
      ).toBe(true);
    });
  });

  it('polls every 2.5s and stops polling when paused', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        items: [],
        active_runs: [],
        active_only: true,
        polled_at: '2026-11-27T02:00:00Z',
      })
    );

    render(<WorkflowLogsConsole token="tok-poll" />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const initialCalls = fetchMock.mock.calls.length;
    expect(initialCalls).toBeGreaterThanOrEqual(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });
    const afterOneInterval = fetchMock.mock.calls.length;
    expect(afterOneInterval).toBeGreaterThan(initialCalls);

    // Pause polling
    fireEvent.click(screen.getByRole('button', { name: 'หยุดชั่วคราว' }));
    expect(screen.getByText('Paused')).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5200);
    });
    expect(fetchMock.mock.calls.length).toBe(afterOneInterval);

    // Resume polling
    fireEvent.click(screen.getByRole('button', { name: 'ติดตามต่อเนื่อง' }));
    expect(screen.getByText('Live 2.5s')).toBeTruthy();
  });
});
