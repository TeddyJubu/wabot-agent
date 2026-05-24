import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { getCosts, type CostsResponse } from "@/api/metrics";

// Fixed palette for providers
const PROVIDER_COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#14b8a6"];

export function CostsTab() {
  const [data, setData] = useState<CostsResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    getCosts({ window: "24h" })
      .then((d) => {
        setData(d);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading") return <p className="text-xs text-fg-muted">Loading costs…</p>;
  if (state === "error") return <p className="text-xs text-bad">Couldn't load cost data.</p>;
  if (!data) return null;

  const providers = data.by_provider.map((p) => p.provider);

  // Build chart data by day, stacked by provider
  const chartData = data.by_day.map((day) => {
    const row: Record<string, string | number> = { date: day.date };
    // Apportion each day's cost proportionally to provider splits
    const total = data.total_usd;
    data.by_provider.forEach((p) => {
      const share = total > 0 ? p.usd / total : 0;
      row[p.provider] = Number((day.usd * share).toFixed(4));
    });
    return row;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <span className="text-xl font-semibold tabular-nums">${data.total_usd.toFixed(4)}</span>
        <span className="text-xs text-fg-muted">total cost ({data.window})</span>
      </div>

      {chartData.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium text-fg-muted">Cost by day & provider</p>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} />
              <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ fontSize: 11 }}
                formatter={(v) => typeof v === "number" ? [`$${v.toFixed(4)}`, undefined] : [String(v), undefined]}
              />
              {providers.map((p, i) => (
                <Area
                  key={p}
                  type="monotone"
                  dataKey={p}
                  stackId="1"
                  stroke={PROVIDER_COLORS[i % PROVIDER_COLORS.length]}
                  fill={PROVIDER_COLORS[i % PROVIDER_COLORS.length]}
                  fillOpacity={0.4}
                />
              ))}
              {providers.length > 1 && (
                <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-xs text-fg-muted">No daily cost data available.</p>
      )}

      {data.by_provider.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-fg-muted">By provider</p>
          <ul className="space-y-1">
            {data.by_provider.map((p, i) => (
              <li key={p.provider} className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5">
                  <span
                    className="size-2 rounded-full"
                    style={{ background: PROVIDER_COLORS[i % PROVIDER_COLORS.length] }}
                  />
                  {p.provider}
                </span>
                <span className="tabular-nums text-fg-muted">${p.usd.toFixed(4)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
