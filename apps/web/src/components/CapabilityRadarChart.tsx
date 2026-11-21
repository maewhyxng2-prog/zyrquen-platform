"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { Icon } from "./Icon";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

type RadarDatum = {
  key: string;
  label: string;
  shortLabel: string;
  score: number;
};

function shortenCapabilityLabel(label: string): string {
  switch (label) {
    case "Native Representation":
      return "Representation";
    case "Knowledge Acquisition":
      return "Acquisition";
    case "Relational Reasoning":
      return "Reasoning";
    case "Planning & Decomposition":
      return "Planning";
    case "Adaptive Learning":
      return "Adaptive";
    case "Knowledge Integration":
      return "Integration";
    default:
      return label;
  }
}

function CapabilityTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: RadarDatum }>;
}) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const item = payload[0]?.payload;
  if (!item) return null;

  return (
    <div className="radar-tooltip">
      <strong>{item.label}</strong>
      <div className="radar-tooltip-row">
        <span>คะแนนจาก Backend</span>
        <span className="tabular-nums">{item.score.toFixed(1)}%</span>
      </div>
    </div>
  );
}

export function CapabilityRadarChart() {
  const {
    nativeHealth,
    nativeError,
    loading,
    platformVersion,
    modelVersion,
  } = usePlatformHealth();

  const measuredCapabilities = (nativeHealth?.capabilities ?? []).filter(
    (item): item is typeof item & { score: number } =>
      typeof item.score === "number" && !Number.isNaN(item.score),
  );

  const hasData = measuredCapabilities.length > 0;
  const displayVersion = platformVersion || modelVersion;

  const chartData: RadarDatum[] = measuredCapabilities.map((item) => ({
    key: item.key,
    label: item.label,
    shortLabel: shortenCapabilityLabel(item.label),
    score: item.score,
  }));

  const statusTone = nativeError
    ? "warn"
    : hasData
      ? "good"
      : "neutral";

  const statusLabel =
    loading && !nativeHealth
      ? "กำลังตรวจสอบข้อมูลจาก Backend"
      : nativeError
        ? "ไม่สามารถเชื่อมต่อ Backend"
        : hasData
          ? "ผลประเมินจริงจาก Backend"
          : "ยังไม่มีข้อมูลผลประเมินจาก Backend";

  return (
    <Panel className="radar-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">
            <Icon name="activity" size={14} />
            <span>
              CAPABILITY RADAR
              {displayVersion ? ` · ${displayVersion}` : ""}
            </span>
          </div>
          <h2>แผนภาพความสามารถจาก Backend</h2>
        </div>
        <StatusBadge tone={statusTone}>{statusLabel}</StatusBadge>
      </div>

      {hasData ? (
        <div className="radar-layout">
          <div
            aria-label="แผนภาพเรดาร์ความสามารถจาก Backend"
            className="capability-radar-stage"
          >
            <ResponsiveContainer height="100%" minHeight={300} width="100%">
              <RadarChart cx="50%" cy="50%" data={chartData} outerRadius="72%">
                <PolarGrid stroke="#223242" />
                <PolarAngleAxis
                  dataKey="shortLabel"
                  tick={{ fill: "#9aaabc", fontSize: 11 }}
                />
                <PolarRadiusAxis
                  angle={90}
                  domain={[0, 100]}
                  tick={{ fill: "#647589", fontSize: 10 }}
                  tickCount={5}
                />
                <Radar
                  dataKey="score"
                  fill="#45d6e8"
                  fillOpacity={0.3}
                  name="คะแนนที่วัดได้จริง"
                  stroke="#45d6e8"
                  strokeWidth={2}
                />
                <Tooltip content={<CapabilityTooltip />} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <div className="radar-breakdown">
            <div className="radar-breakdown-head">
              <span>ความสามารถ</span>
              <span>คะแนนจาก Backend</span>
            </div>
            {chartData.map((item) => (
              <div className="radar-breakdown-row" key={item.key}>
                <div className="radar-breakdown-label">
                  <strong>{item.label}</strong>
                </div>
                <div className="radar-breakdown-values tabular-nums">
                  <span className="radar-score-live">
                    {item.score.toFixed(1)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="unavailable-block">
          <strong>
            {loading && !nativeHealth
              ? "กำลังตรวจสอบผลประเมินจาก /v1/native-ai/health"
              : nativeError
                ? "ไม่สามารถดึงข้อมูลความสามารถจาก Backend ได้"
                : "ยังไม่มีข้อมูลผลการประเมินความสามารถของโมเดล"}
          </strong>
          <p>
            {nativeError ||
              "Backend ยังไม่ได้ส่งค่าคะแนนความสามารถที่วัดผลจริงกลับมา หน้านี้จะไม่สร้างกราฟหรือตัวเลขจำลองแทนข้อมูลจริง"}
          </p>
        </div>
      )}
    </Panel>
  );
}
