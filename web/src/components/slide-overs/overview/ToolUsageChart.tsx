import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { ToolUsageResponse } from "@/api/metrics";

interface ToolUsageChartProps {
  data: ToolUsageResponse | null;
}

export function ToolUsageChart({ data }: ToolUsageChartProps) {
  if (!data || data.items.length === 0) {
    return (
      <div className="flex h-28 items-center justify-center text-xs text-fg-muted">
        No tool usage data
      </div>
    );
  }

  const chartData = data.items
    .slice(0, 10)
    .map((item) => ({
      name: item.tool_name.length > 20 ? item.tool_name.slice(0, 18) + "…" : item.tool_name,
      invocations: item.invocations,
    }))
    .reverse(); // highest at top for horizontal

  return (
    <ResponsiveContainer width="100%" height={Math.max(120, chartData.length * 24)}>
      <BarChart
        data={chartData}
        layout="vertical"
        margin={{ top: 0, right: 8, bottom: 0, left: 8 }}
      >
        <XAxis type="number" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fontSize: 10 }}
          tickLine={false}
          width={110}
        />
        <Tooltip contentStyle={{ fontSize: 11 }} />
        <Bar dataKey="invocations" fill="#6366f1" radius={[0, 2, 2, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
