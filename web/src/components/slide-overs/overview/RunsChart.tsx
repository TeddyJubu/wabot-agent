import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { RunsSeriesResponse } from "@/api/metrics";

interface RunsChartProps {
  data: RunsSeriesResponse | null;
}

// Fixed palette for up to 8 agents
const AGENT_COLORS = [
  "#6366f1",
  "#22c55e",
  "#f59e0b",
  "#ef4444",
  "#14b8a6",
  "#a855f7",
  "#ec4899",
  "#64748b",
];

function formatTs(ts: string, bucket: string): string {
  const d = new Date(ts);
  if (bucket === "day") return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (bucket === "hour") return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function RunsChart({ data }: RunsChartProps) {
  if (!data || data.series.length === 0) {
    return (
      <div className="flex h-36 items-center justify-center text-xs text-fg-muted">
        No run data for this window
      </div>
    );
  }

  // Collect all agent keys across series
  const agentKeys = Array.from(
    new Set(data.series.flatMap((s) => Object.keys(s.by_agent))),
  );

  const chartData = data.series.map((s) => ({
    label: formatTs(s.timestamp, data.bucket),
    total: s.count,
    ...s.by_agent,
  }));

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
        <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} />
        <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip contentStyle={{ fontSize: 11 }} />
        {agentKeys.length > 0 ? (
          agentKeys.map((agent, i) => (
            <Bar
              key={agent}
              dataKey={agent}
              stackId="a"
              fill={AGENT_COLORS[i % AGENT_COLORS.length]}
            />
          ))
        ) : (
          <Bar dataKey="total" stackId="a" fill={AGENT_COLORS[0]} />
        )}
        {agentKeys.length > 1 && <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />}
      </BarChart>
    </ResponsiveContainer>
  );
}
