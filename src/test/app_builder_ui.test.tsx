import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MultiFileAppBuilder } from '../components/MultiFileAppBuilder';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('MultiFileAppBuilder', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads persistent workspaces, supports multi-file authoring, displays real build/repair evidence, diff, and rollback', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const rawBody = typeof init?.body === 'string' ? init.body : '{}';
      const body = JSON.parse(rawBody) as Record<string, unknown>;

      if (url.endsWith('/api/app-builder/workspaces')) {
        return jsonResponse({
          ok: true,
          output: {
            workspaces: [
              {
                workspace: 'alpha_ws',
                file_count: 2,
                files: ['app/main.py', 'tests/test_app.py'],
                snapshot_count: 1,
                last_snapshot_id: 'snap_0001_init',
                last_verified_snapshot_id: 'snap_0001_init',
                updated_at: '2026-11-27T01:00:00Z',
              },
            ],
          },
        });
      }

      if (url.endsWith('/api/app-builder/history')) {
        if (body.action === 'list') {
          return jsonResponse({
            ok: true,
            output: {
              action: 'list',
              workspace: body.workspace,
              current_files: ['app/main.py', 'tests/test_app.py'],
              snapshots: [
                {
                  snapshot_id: 'snap_0001_init',
                  index: 1,
                  created_at: '2026-11-27T01:00:00Z',
                  action: 'verified_build',
                  label: 'Initial baseline',
                  verified: true,
                  file_count: 2,
                  tests_run: 2,
                },
              ],
            },
          });
        }
        if (body.action === 'read_file') {
          return jsonResponse({
            ok: true,
            output: {
              action: 'read_file',
              file_path: body.file_path,
              content: 'def run():\n    return 42\n',
            },
          });
        }
        if (body.action === 'diff') {
          return jsonResponse({
            ok: true,
            output: {
              action: 'diff',
              compared: 'snap_0001_init -> working_tree',
              changed_files: ['app/main.py'],
              diffs: {
                'app/main.py': '--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-return 42\n+return 99',
              },
            },
          });
        }
        if (body.action === 'rollback') {
          return jsonResponse({
            ok: true,
            summary: 'ย้อนกลับ workspace alpha_ws ไปยัง snap_0001_init สำเร็จ',
            output: {
              action: 'rollback',
              rolled_back_to: body.snapshot_id,
              diffs: {
                'app/main.py': '--- working\n+++ restored\n-return 99\n+return 42',
              },
            },
          });
        }
      }

      if (url.endsWith('/api/app-builder/build')) {
        return jsonResponse({
          ok: true,
          summary: 'สร้างและตรวจสอบแอปหลายไฟล์สำเร็จ',
          output: {
            workspace: body.workspace,
            verified: true,
            build_passed: true,
            lint_passed: true,
            tests_passed: true,
            tests_run: 3,
            repair_rounds_used: 1,
            rolled_back: false,
            files: ['app/main.py', 'app/extra.py', 'tests/test_app.py'],
            duration_ms: 48.2,
            build_evidence: { returncode: 0, stderr: '' },
            lint_evidence: { issue_count: 0, issues: [] },
            test_evidence: { ok: true, tests_run: 3, stderr: 'Ran 3 tests in 0.01s\nOK' },
            stages: [
              { stage: 'diagnose_round_1', status: 'COMPLETED', root_cause: 'syntax_error' },
              { stage: 'rebuild_retest_round_1', status: 'PASS', tests_run: 3 },
            ],
          },
        }, 201);
      }

      return jsonResponse({ ok: false, error: 'Unexpected call' }, 500);
    });

    render(<MultiFileAppBuilder token="tok-builder" />);

    await waitFor(() => {
      expect(screen.getByText(/alpha_ws · 2 ไฟล์ · 1 snapshots/)).toBeTruthy();
      expect(screen.getByText('snap_0001_init')).toBeTruthy();
    });

    // Switch to custom multi-file authoring, add a new file, and run build
    fireEvent.click(
      screen.getByRole('button', { name: /แก้ไข\/เพิ่มหลายไฟล์โดยตรง/ })
    );

    await waitFor(() => {
      expect(screen.getByText('app/main.py')).toBeTruthy();
    });

    fireEvent.change(screen.getByLabelText('เส้นทางไฟล์ใหม่'), {
      target: { value: 'app/extra.py' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'เพิ่มไฟล์' }));

    fireEvent.click(
      screen.getByRole('button', { name: 'สร้าง / อัปเดตและตรวจสอบจริง' })
    );

    await waitFor(() => {
      expect(screen.getByText('VERIFIED')).toBeTruthy();
      expect(screen.getByText('Repair rounds: 1')).toBeTruthy();
      expect(screen.getByText('diagnose_round_1')).toBeTruthy();
      expect(screen.getByText('rebuild_retest_round_1')).toBeTruthy();
    });

    // Load Unified Diff
    fireEvent.click(screen.getByRole('button', { name: 'Diff' }));
    await waitFor(() => {
      expect(screen.getByText('+return 99')).toBeTruthy();
    });

    // Trigger Rollback
    fireEvent.click(screen.getByRole('button', { name: 'ย้อนกลับไปยังรุ่นนี้' }));
    await waitFor(() => {
      expect(
        screen.getByText('ย้อนกลับ workspace alpha_ws ไปยัง snap_0001_init สำเร็จ')
      ).toBeTruthy();
    });

    expect(
      fetchMock.mock.calls.some(([u]) => String(u).endsWith('/api/app-builder/build'))
    ).toBe(true);
  });

  it('displays FAILED verification and rolled_back status honestly when sandbox tests fail', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/api/app-builder/workspaces')) {
        return jsonResponse({ ok: true, output: { workspaces: [] } });
      }
      if (url.endsWith('/api/app-builder/history')) {
        return jsonResponse({
          ok: true,
          output: { action: 'list', workspace: 'my_native_app', current_files: [], snapshots: [] },
        });
      }
      if (url.endsWith('/api/app-builder/build')) {
        return jsonResponse(
          {
            ok: false,
            status: 'FAILED',
            error: 'Sandbox policy violation: openai import blocked',
            output: {
              workspace: 'my_native_app',
              verified: false,
              build_passed: true,
              lint_passed: false,
              tests_passed: false,
              tests_run: 0,
              rolled_back: true,
              repair_rounds_used: 0,
              files: [],
              build_evidence: { returncode: 0 },
              lint_evidence: {
                issue_count: 1,
                issues: [{ file: 'bad.py', rule: 'sandbox_policy', detail: 'External LLM forbidden' }],
              },
              test_evidence: { ok: false, status: 'NOT_RUN', stderr: 'Skipped unit tests' },
              stages: [{ stage: 'rollback_on_failure', status: 'COMPLETED', detail: 'Restored cleanly' }],
            },
          },
          400
        );
      }
      return jsonResponse({ ok: false }, 404);
    });

    render(<MultiFileAppBuilder token="tok-fail" />);

    fireEvent.click(
      screen.getByRole('button', { name: 'สร้าง / อัปเดตและตรวจสอบจริง' })
    );

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
      expect(screen.getByText('Sandbox policy violation: openai import blocked')).toBeTruthy();
      expect(screen.getByText('FAILED')).toBeTruthy();
      expect(screen.getByText('Rolled back')).toBeTruthy();
      expect(screen.getByText(/External LLM forbidden/)).toBeTruthy();
    });
  });
});
