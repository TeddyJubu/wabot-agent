// Tool events tab — shows invocations per tool.
// The backend does not yet expose a dedicated /api/tool_events endpoint.
// This tab uses the tool usage metrics endpoint as a proxy, and will be
// upgraded to a per-event log once the backend adds that endpoint.

import { useEffect, useState } from "react";
import { getToolUsage, type ToolUsageResponse } from "@/api/metrics";

export function ToolEventsTab() {
  const [data, setData] = useState<ToolUsageResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    getToolUsage({ window: "24h", limit: 50 })
      .then((d) => {
        setData(d);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, []);

  if (state === "loading") return <p className="text-xs text-fg-muted">Loading tool events…</p>;
  if (state === "error") return <p className="text-xs text-bad">Couldn't load tool events.</p>;
  if (!data || data.items.length === 0) {
    return <p className="text-xs text-fg-muted">No tool events in the last 24h.</p>;
  }

  return (
    <div>
      <p className="mb-3 text-xs text-fg-muted">
        Tool invocations (24h) — per-event log coming soon
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-fg-muted">
            <th className="pb-2 font-medium">Tool</th>
            <th className="pb-2 font-medium text-right">Calls</th>
            <th className="pb-2 font-medium text-right">Avg latency</th>
            <th className="pb-2 font-medium text-right">Errors</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((item) => (
            <tr key={item.tool_name} className="border-b border-border/50 last:border-0">
              <td className="py-2 font-mono">{item.tool_name}</td>
              <td className="py-2 text-right tabular-nums">{item.invocations}</td>
              <td className="py-2 text-right tabular-nums text-fg-muted">
                {item.avg_latency_ms !== null
                  ? `${(item.avg_latency_ms / 1000).toFixed(2)}s`
                  : "—"}
              </td>
              <td className="py-2 text-right tabular-nums">
                {item.errors > 0 ? (
                  <span className="text-bad">{item.errors}</span>
                ) : (
                  <span className="text-fg-muted">0</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
