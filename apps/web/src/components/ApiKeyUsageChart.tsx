"use client";

import { useSyncExternalStore } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ApiKeyDailyUsagePoint, ApiKeyMetadata, ApiKeyUsage } from "@/lib/types";

type ChartPoint = ApiKeyDailyUsagePoint & {
  shortDate: string;
  fullDate: string;
};

function formatShortUtcDate(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString("th-TH", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function formatFullUtcDate(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString("th-TH", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatCompactTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function UsageTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div className="radar-tooltip">
      <strong>{point.fullDate} (UTC)</strong>
      <div className="radar-tooltip-row">
        <span>Total Tokens</span>
        <strong>{point.totalTokens.toLocaleString("th-TH")}</strong>
      </div>
      <div className="radar-tooltip-row">
        <span>Input Tokens</span>
        <span>{point.inputTokens.toLocaleString("th-TH")}</span>
      </div>
      <div className="radar-tooltip-row">
        <span>Output Tokens</span>
        <span>{point.outputTokens.toLocaleString("th-TH")}</span>
      </div>
      <div className="radar-tooltip-row">
        <span>Requests</span>
        <span>{point.successfulRequests.toLocaleString("th-TH")}</span>
      </div>
    </div>
  );
}

function subscribeClientMount() {
  return () => {};
}

export function ApiKeyUsageChart({
  selectedKey,
  usage,
  loading,
}: {
  selectedKey: ApiKeyMetadata | null;
  usage: ApiKeyUsage | null;
  loading: boolean;
}) {
  const mounted = useSyncExternalStore(
    subscribeClientMount,
    () => true,
    () => false,
  );

  if (!selectedKey) return null;

  const chartData: ChartPoint[] = (usage?.dailyUsage ?? []).map((item) => ({
    ...item,
    shortDate: formatShortUtcDate(item.date),
    fullDate: formatFullUtcDate(item.date),
  }));

  const sevenDayTokens = chartData.reduce((acc, d) => acc + d.totalTokens, 0);
  const sevenDayRequests = chartData.reduce(
    (acc, d) => acc + d.successfulRequests,
    0,
  );

  return (
    <div className="settings-usage-panel" aria-live="polite">
      <div className="settings-usage-head">
        <div>
          <strong>การใช้งาน Token ย้อนหลัง 7 วัน · {selectedKey.name}</strong>
          <small>
            <code>{selectedKey.keyPrefix}…</code>
            {usage?.updatedAt
              ? ` · อัปเดตล่าสุด ${new Date(usage.updatedAt).toLocaleString("th-TH")}`
              : " · ข้อมูลจริงจาก Backend"}
          </small>
        </div>
        {usage && (
          <div className="settings-usage-kpis">
            <span>
              7 วัน: <strong>{sevenDayTokens.toLocaleString("th-TH")}</strong> Tokens (
              {sevenDayRequests.toLocaleString("th-TH")} Req)
            </span>
            <span>
              สะสมทั้งหมด: <strong>{usage.totalTokens.toLocaleString("th-TH")}</strong>{" "}
              Tokens ({usage.successfulRequests.toLocaleString("th-TH")} Req)
            </span>
          </div>
        )}
      </div>

      {loading ? (
        <p className="settings-key-meta">กำลังโหลดกราฟการใช้งาน 7 วันล่าสุด...</p>
      ) : !usage ? (
        <p className="settings-key-meta">ยังไม่มีข้อมูลการใช้งานสำหรับคีย์ที่เลือก</p>
      ) : (
        <>
          <div className="settings-usage-chart" role="img" aria-label={`กราฟ Token 7 วันของ ${selectedKey.name}`}>
            {mounted ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={chartData}
                  margin={{ top: 8, right: 10, left: -12, bottom: 0 }}
                >
                  <CartesianGrid stroke="#1e2943" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="shortDate"
                    stroke="#64748b"
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                    tickLine={false}
                    axisLine={{ stroke: "#1e2943" }}
                  />
                  <YAxis
                    allowDecimals={false}
                    stroke="#64748b"
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                    tickFormatter={formatCompactTokens}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(59, 130, 246, 0.08)" }}
                    content={<UsageTooltip />}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: "11px", paddingTop: "6px", color: "#94a3b8" }}
                    formatter={(value: string) =>
                      value === "inputTokens" ? "Input Tokens" : "Output Tokens"
                    }
                  />
                  <Bar
                    dataKey="inputTokens"
                    name="inputTokens"
                    stackId="tokens"
                    fill="#3b82f6"
                    radius={[0, 0, 3, 3]}
                    maxBarSize={32}
                  />
                  <Bar
                    dataKey="outputTokens"
                    name="outputTokens"
                    stackId="tokens"
                    fill="#22d3ee"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={32}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="settings-usage-skeleton" />
            )}
          </div>
          {sevenDayTokens === 0 && (
            <p className="settings-key-meta">
              ยังไม่มีการเรียกใช้ Native Inference ผ่าน API Key นี้ในช่วง 7 วันที่ผ่านมา
            </p>
          )}
        </>
      )}
    </div>
  );
}
