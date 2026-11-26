import { useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  Clock,
  Cpu,
  Gauge,
  HardDrive,
  RotateCw,
  ShieldCheck,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  isMalformedOrEmptyTraceText,
  sanitizeTraceDisplayText,
  serializeTableToTsv,
} from '../lib/clipboard';
import type {
  AdminOverview,
  ClientLatencySample,
  MemorySnapshot,
  NativeTrace,
  ReasoningTaskTiming,
  ThreadCleanupVerification,
} from '../types';
import { CopyButton } from './CopyButton';

interface AdminStabilityPanelProps {
  adminData: AdminOverview | null;
  perfSamples: MemorySnapshot[];
  clientLatencies: ClientLatencySample[];
  cleanupVerification: ThreadCleanupVerification | null;
  loading?: boolean;
  onCapturePerfSample?: () => void;
  onRefreshAdmin?: () => void;
}

function formatTimeShort(ts: number | string): string {
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleTimeString('th-TH', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

const CHART_TOOLTIP_STYLE = {
  backgroundColor: 'var(--color-surface-raised)',
  borderColor: 'var(--color-border)',
  borderRadius: '0.75rem',
  fontSize: '12px',
  color: 'var(--color-text)',
};

export function AdminStabilityPanel({
  adminData,
  perfSamples,
  clientLatencies,
  cleanupVerification,
  loading = false,
  onCapturePerfSample,
  onRefreshAdmin,
}: AdminStabilityPanelProps) {
  const latestSample = perfSamples.length > 0 ? perfSamples[perfSamples.length - 1] : null;
  const anyHeapSupported = perfSamples.some((s) => s.heapSupported && s.usedJSHeapMB !== null);

  const heapChartData = useMemo(
    () =>
      perfSamples.map((s, idx) => ({
        idx: idx + 1,
        time: formatTimeShort(s.timestamp),
        usedJSHeapMB: s.usedJSHeapMB ?? 0,
        totalJSHeapMB: s.totalJSHeapMB ?? 0,
        streamBufferKB: Math.round((s.streamBufferBytes / 1024) * 100) / 100,
        activeStreams: s.activeStreamCount,
        pendingLoads: s.pendingThreadLoads,
      })),
    [perfSamples]
  );

  const latencyChartData = useMemo(() => {
    const tracePoints = (adminData?.reasoning_traces || [])
      .slice()
      .reverse()
      .map((t, idx) => ({
        idx: idx + 1,
        time: formatTimeShort(t.created_at),
        label: sanitizeTraceDisplayText(t.prompt).slice(0, 28) || t.mode,
        source: 'Native Trace',
        nativeLatencyMs: Math.round((Number(t.latency_ms) || 0) * 100) / 100,
        clientLatencyMs: null as number | null,
      }));

    const clientPoints = clientLatencies.map((c, idx) => ({
      idx: tracePoints.length + idx + 1,
      time: formatTimeShort(c.timestamp),
      label: c.label,
      source: 'Client Stream',
      nativeLatencyMs: null as number | null,
      clientLatencyMs: Math.round((Number(c.latencyMs) || 0) * 100) / 100,
    }));

    const apiPoints =
      tracePoints.length === 0
        ? (adminData?.recent_api_usage || [])
            .slice()
            .reverse()
            .map((u, idx) => ({
              idx: idx + 1,
              time: formatTimeShort(u.created_at),
              label: `${u.method} ${u.endpoint}`,
              source: 'API Usage',
              nativeLatencyMs: Math.round((Number(u.latency_ms) || 0) * 100) / 100,
              clientLatencyMs: null as number | null,
            }))
        : [];

    return [...tracePoints, ...apiPoints, ...clientPoints].slice(-40);
  }, [adminData?.reasoning_traces, adminData?.recent_api_usage, clientLatencies]);

  const taskBottleneckStats = useMemo(() => {
    const map = new Map<string, { task: string; totalMs: number; maxMs: number; count: number }>();
    for (const traceRow of adminData?.reasoning_traces || []) {
      let parsed: NativeTrace;
      try {
        parsed = JSON.parse(traceRow.trace_json) as NativeTrace;
      } catch {
        continue;
      }
      const timings: ReasoningTaskTiming[] = Array.isArray(parsed.task_timings)
        ? parsed.task_timings
        : [];
      for (const t of timings) {
        if (!t?.task || isMalformedOrEmptyTraceText(t.task)) continue;
        const dur = Number(t.duration_ms) || 0;
        const prev = map.get(t.task) || { task: t.task, totalMs: 0, maxMs: 0, count: 0 };
        prev.totalMs += dur;
        prev.maxMs = Math.max(prev.maxMs, dur);
        prev.count += 1;
        map.set(t.task, prev);
      }
    }
    return Array.from(map.values())
      .map((entry) => ({
        task: entry.task,
        avgMs: Math.round((entry.totalMs / entry.count) * 100) / 100,
        maxMs: Math.round(entry.maxMs * 100) / 100,
        count: entry.count,
      }))
      .sort((a, b) => b.maxMs - a.maxMs)
      .slice(0, 10);
  }, [adminData?.reasoning_traces]);

  const latencySummary = useMemo(() => {
    const values = latencyChartData
      .map((p) => p.nativeLatencyMs ?? p.clientLatencyMs)
      .filter((v): v is number => typeof v === 'number' && !Number.isNaN(v));
    if (values.length === 0) {
      return { avgMs: 0, maxMs: 0, count: 0 };
    }
    const sum = values.reduce((acc, v) => acc + v, 0);
    return {
      avgMs: Math.round((sum / values.length) * 100) / 100,
      maxMs: Math.round(Math.max(...values) * 100) / 100,
      count: values.length,
    };
  }, [latencyChartData]);

  const slowestTask = taskBottleneckStats.length > 0 ? taskBottleneckStats[0] : null;
  const sys = adminData?.system;

  return (
    <div className="space-y-6" aria-label="แผงตรวจสอบความเสถียรเนทีฟ PerformanceMonitor">
      <div className="flex flex-col gap-3 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-[var(--color-accent)]" />
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              ความเสถียรสภาพแวดล้อมเนทีฟ (PerformanceMonitor &amp; Bottleneck Telemetry)
            </h3>
          </div>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            ติดตามแนวโน้มการใช้งานฮีป (JS Heap), บัฟเฟอร์สตรีมมิ่ง, เวลาแฝงในการประมวลผล และคอขวดของงานใน Reasoning Trace แบบเรียลไทม์
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CopyButton
            getText={() =>
              [
                `ZYRQUEN Stability & Bottleneck Telemetry`,
                `Memory Status: ${
                  latestSample?.leakWarning
                    ? 'LEAK_WARNING'
                    : cleanupVerification?.clean === false
                      ? 'THREAD_LEAK'
                      : 'STABLE'
                }`,
                `Latency Avg/Max: ${latencySummary.avgMs} ms / ${latencySummary.maxMs} ms (${latencySummary.count} samples)`,
                slowestTask
                  ? `Slowest Task: ${slowestTask.task} (Max ${slowestTask.maxMs} ms, Avg ${slowestTask.avgMs} ms)`
                  : 'Slowest Task: none',
                taskBottleneckStats.length > 0
                  ? serializeTableToTsv(
                      ['Task', 'Runs', 'Avg (ms)', 'Max (ms)'],
                      taskBottleneckStats.map((r) => [r.task, r.count, r.avgMs, r.maxMs])
                    )
                  : '',
              ]
                .filter(Boolean)
                .join('\n\n')
            }
            ariaLabel="คัดลอกรายงานเสถียรภาพระบบ"
            title="คัดลอกรายงานเสถียรภาพและตารางคอขวด"
            size="xs"
          />
          {onCapturePerfSample && (
            <button
              type="button"
              onClick={onCapturePerfSample}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--zyrquen-indigo)] bg-[var(--zyrquen-indigo)]/20 px-3 text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)]"
            >
              <Gauge className="h-3.5 w-3.5" />
              <span>สุ่มเก็บเมตริกทันที</span>
            </button>
          )}
          {onRefreshAdmin && (
            <button
              type="button"
              disabled={loading}
              onClick={onRefreshAdmin}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50"
            >
              <RotateCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>รีเฟรชข้อมูล</span>
            </button>
          )}
        </div>
      </div>

      {/* KPI Summary Cards */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <div className="flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
            <span>การใช้งาน JS Heap (PerformanceMonitor)</span>
            <HardDrive className="h-3.5 w-3.5 text-[var(--color-accent)]" />
          </div>
          {latestSample?.heapSupported && latestSample.usedJSHeapMB !== null ? (
            <>
              <p className="mt-2 font-mono text-xl font-bold text-[var(--color-text)] tabular-nums">
                {latestSample.usedJSHeapMB} MB
              </p>
              <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                Total {latestSample.totalJSHeapMB ?? '-'} MB · Δ{' '}
                {latestSample.heapDeltaMB !== null
                  ? `${latestSample.heapDeltaMB >= 0 ? '+' : ''}${latestSample.heapDeltaMB} MB`
                  : '0 MB'}
              </p>
            </>
          ) : (
            <>
              <p className="mt-2 text-sm font-semibold text-[var(--color-warning)]">
                เบราว์เซอร์ไม่เปิดเผย performance.memory
              </p>
              <p className="mt-1 text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                Stream Buffer: {latestSample ? `${latestSample.streamBufferBytes} B` : '0 B'} · เก็บแล้ว {perfSamples.length} จุด
              </p>
            </>
          )}
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <div className="flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
            <span>สถานะหน่วยความจำ &amp; Thread Cleanup</span>
            {latestSample?.leakWarning || cleanupVerification?.clean === false ? (
              <AlertTriangle className="h-3.5 w-3.5 text-[var(--color-warning)]" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5 text-[var(--color-success)]" />
            )}
          </div>
          <p
            className={`mt-2 font-mono text-xl font-bold ${
              latestSample?.leakWarning || cleanupVerification?.clean === false
                ? 'text-[var(--color-warning)]'
                : 'text-[var(--color-success)]'
            }`}
          >
            {latestSample?.leakWarning
              ? 'LEAK_WARNING'
              : cleanupVerification?.clean === false
                ? 'THREAD_LEAK'
                : 'STABLE'}
          </p>
          <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
            ตัวอย่าง {perfSamples.length} จุด · Pending {latestSample?.pendingThreadLoads ?? 0} · Aborted{' '}
            {cleanupVerification?.abortedCount ?? 0}
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <div className="flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
            <span>เวลาแฝงประมวลผล (เฉลี่ย / สูงสุด)</span>
            <Clock className="h-3.5 w-3.5 text-[var(--color-accent)]" />
          </div>
          <p className="mt-2 font-mono text-xl font-bold text-[var(--color-text)] tabular-nums">
            {latencySummary.avgMs} ms
          </p>
          <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
            Max {latencySummary.maxMs} ms · จาก {latencySummary.count} รายการ
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <div className="flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
            <span>คอขวดสูงสุดใน Reasoning Trace</span>
            <Cpu className="h-3.5 w-3.5 text-[var(--color-warning)]" />
          </div>
          {slowestTask ? (
            <>
              <p className="mt-2 truncate font-mono text-base font-bold text-[var(--color-warning)]">
                {slowestTask.task}
              </p>
              <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                Max {slowestTask.maxMs} ms · Avg {slowestTask.avgMs} ms ({slowestTask.count}x)
              </p>
            </>
          ) : (
            <>
              <p className="mt-2 text-sm font-semibold text-[var(--color-text-secondary)]">ยังไม่มีข้อมูล Task Timing</p>
              <p className="mt-1 text-[11px] text-[var(--color-text-muted)]">
                {sys ? `Python ${sys.python_version} · DB ${sys.sqlite_db_kb} KB` : 'รอการประมวลผลในเวิร์กสเปซ'}
              </p>
            </>
          )}
        </div>
      </section>

      {/* Chart 1 & Chart 2 */}
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-[var(--color-text)]">
                แนวโน้มการใช้งานฮีปและบัฟเฟอร์ (PerformanceMonitor)
              </h4>
              <p className="text-xs text-[var(--color-text-secondary)]">
                {anyHeapSupported
                  ? 'usedJSHeapMB, totalJSHeapMB และ streamBufferKB ต่อช่วงเวลา'
                  : 'แสดง streamBufferKB และโหลดเธรดจริง (runtime นี้ไม่รองรับ performance.memory)'}
              </p>
            </div>
            <span className="font-mono text-[11px] text-[var(--color-accent)] tabular-nums">
              {heapChartData.length} samples
            </span>
          </div>

          {heapChartData.length === 0 ? (
            <div className="flex h-[240px] items-center justify-center rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-xs text-[var(--color-text-secondary)]">
              ยังไม่มีตัวอย่างจาก PerformanceMonitor — กด &ldquo;สุ่มเก็บเมตริกทันที&rdquo; หรือใช้งานเวิร์กสเปซ
            </div>
          ) : (
            <div className="h-[240px] w-full" data-testid="recharts-heap-chart">
              <ResponsiveContainer width="100%" height={240} minWidth={240}>
                <AreaChart data={heapChartData} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="zyrqUsedHeapGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#21D4FD" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="#21D4FD" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="zyrqTotalHeapGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#B47AFF" stopOpacity={0.28} />
                      <stop offset="95%" stopColor="#B47AFF" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="time" stroke="var(--color-text-muted)" fontSize={11} />
                  <YAxis stroke="var(--color-text-muted)" fontSize={11} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: '11px' }} />
                  {anyHeapSupported && (
                    <Area
                      type="monotone"
                      dataKey="totalJSHeapMB"
                      name="Total JS Heap (MB)"
                      stroke="#B47AFF"
                      fillOpacity={1}
                      fill="url(#zyrqTotalHeapGrad)"
                    />
                  )}
                  {anyHeapSupported && (
                    <Area
                      type="monotone"
                      dataKey="usedJSHeapMB"
                      name="Used JS Heap (MB)"
                      stroke="#21D4FD"
                      fillOpacity={1}
                      fill="url(#zyrqUsedHeapGrad)"
                    />
                  )}
                  <Area
                    type="monotone"
                    dataKey="streamBufferKB"
                    name="Stream Buffer (KB)"
                    stroke="#34D399"
                    fillOpacity={0.18}
                    fill="#34D399"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-[var(--color-text)]">
                แนวโน้มเวลาแฝงในการประมวลผลเมื่อเวลาผ่านไป
              </h4>
              <p className="text-xs text-[var(--color-text-secondary)]">
                เปรียบเทียบ Native Core Latency (ms) จาก SQLite กับ Client Stream Latency (ms)
              </p>
            </div>
            <span className="font-mono text-[11px] text-[var(--color-accent)] tabular-nums">
              {latencyChartData.length} traces
            </span>
          </div>

          {latencyChartData.length === 0 ? (
            <div className="flex h-[240px] items-center justify-center rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-xs text-[var(--color-text-secondary)]">
              ยังไม่มีประวัติเวลาแฝงในการประมวลผล — ส่งคำถามในเวิร์กสเปซเพื่อเริ่มบันทึกข้อมูล
            </div>
          ) : (
            <div className="h-[240px] w-full" data-testid="recharts-latency-chart">
              <ResponsiveContainer width="100%" height={240} minWidth={240}>
                <LineChart data={latencyChartData} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="time" stroke="var(--color-text-muted)" fontSize={11} />
                  <YAxis stroke="var(--color-text-muted)" fontSize={11} unit=" ms" />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: '11px' }} />
                  <Line
                    type="monotone"
                    dataKey="nativeLatencyMs"
                    name="Native Core (ms)"
                    stroke="#5865F2"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="clientLatencyMs"
                    name="Client Round-Trip (ms)"
                    stroke="#21D4FD"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      </div>

      {/* Chart 3: Reasoning Trace Task Bottleneck Breakdown */}
      <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 className="text-sm font-semibold text-[var(--color-text)]">
              การกระจายเวลาทำงานแยกราย Task ใน Reasoning Trace (Bottleneck Breakdown)
            </h4>
            <p className="text-xs text-[var(--color-text-secondary)]">
              สรุปค่าเฉลี่ย (Avg ms) และจุดสูงสุด (Max ms) ของแต่ละโมดูลในสถาปัตยกรรมเนทีฟเพื่อชี้เป้าคอขวด
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-[var(--color-warning)] tabular-nums">
              {taskBottleneckStats.length} tasks
            </span>
            {taskBottleneckStats.length > 0 && (
              <CopyButton
                getText={() =>
                  serializeTableToTsv(
                    ['Task', 'Runs', 'Avg (ms)', 'Max (ms)'],
                    taskBottleneckStats.map((r) => [r.task, r.count, r.avgMs, r.maxMs])
                  )
                }
                label="คัดลอกตาราง"
                ariaLabel="คัดลอกตาราง Bottleneck"
                title="คัดลอกตาราง Bottleneck Breakdown เป็นรูปแบบคั่นด้วยแท็บ (TSV)"
                size="xs"
              />
            )}
          </div>
        </div>

        {taskBottleneckStats.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-xs text-[var(--color-text-secondary)]">
            ยังไม่มีบันทึก task_timings จากการประมวลผลล่าสุด
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-12">
            <div className="h-[240px] w-full lg:col-span-7" data-testid="recharts-bottleneck-chart">
              <ResponsiveContainer width="100%" height={240} minWidth={240}>
                <BarChart data={taskBottleneckStats} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="task" stroke="var(--color-text-muted)" fontSize={10} interval={0} angle={-15} textAnchor="end" height={54} />
                  <YAxis stroke="var(--color-text-muted)" fontSize={11} unit=" ms" />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: '11px' }} />
                  <Bar dataKey="avgMs" name="Avg (ms)" fill="#21D4FD" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="maxMs" name="Max (ms)" fill="#B47AFF" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] lg:col-span-5">
              {taskBottleneckStats.map((row) => (
                <div
                  key={row.task}
                  className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-xs"
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono font-medium text-[var(--color-text)]">{row.task}</p>
                    <p className="font-mono text-[10px] text-[var(--color-text-muted)] tabular-nums">
                      รัน {row.count} ครั้ง
                    </p>
                  </div>
                  <div className="shrink-0 text-right font-mono tabular-nums">
                    <p className="text-[var(--zyrquen-violet)]">max {row.maxMs} ms</p>
                    <p className="text-[11px] text-[var(--color-accent)]">avg {row.avgMs} ms</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
