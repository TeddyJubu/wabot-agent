import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import {
  getOverview,
  getRunsSeries,
  getToolUsage,
  getHealth,
  type OverviewResponse,
  type RunsSeriesResponse,
  type ToolUsageResponse,
  type HealthResponse,
} from "@/api/metrics";
import { KpiCard } from "./overview/KpiCard";
import { RunsChart } from "./overview/RunsChart";
import { ToolUsageChart } from "./overview/ToolUsageChart";
import { IntegrationsHealthSummary } from "./overview/IntegrationsHealthSummary";

export default function OverviewPanel() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [runsSeries, setRunsSeries] = useState<RunsSeriesResponse | null>(null);
  const [toolUsage, setToolUsage] = useState<ToolUsageResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setState("loading");
      setError(null);
    }
    try {
      const [ov, rs, tu, hl] = await Promise.all([
        getOverview(),
        getRunsSeries({ window: "24h", bucket: "hour" }),
        getToolUsage({ window: "24h", limit: 10 }),
        getHealth(),
      ]);
      setOverview(ov);
      setRunsSeries(rs);
      setToolUsage(tu);
      setHealth(hl);
      setState("ready");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not load overview";
      setError(msg);
      setState("error");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  const formatMsgCount = (n: number) => n.toLocaleString();
  const formatCost = (n: number) => `$${n.toFixed(2)}`;
  const formatLatency = (ms: number | null) =>
    ms !== null ? `${(ms / 1000).toFixed(1)}s` : "—";

  const healthPill =
    overview
      ? `${overview.integrations_health.ok} OK · ${overview.integrations_health.error} ✗`
      : "—";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-end">
        <button
          onClick={() => void load(true)}
          disabled={refreshing}
          aria-label="Refresh overview"
          className="flex items-center gap-1.5 rounded-card border border-border px-2.5 py-1.5 text-xs text-fg-muted transition hover:bg-bg-app hover:text-fg disabled:opacity-50"
        >
          <RefreshCw className={`size-3 ${refreshing ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {state === "loading" && (
        <p className="text-xs text-fg-muted">Loading overview…</p>
      )}

      {state === "error" && error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      {(state === "ready" || refreshing) && overview && (
        <>
          {/* KPI row */}
          <div className="flex gap-2">
            <KpiCard
              title="Messages today"
              value={formatMsgCount(overview.messages_today)}
              delta={overview.messages_today_delta_pct}
            />
            <KpiCard
              title="Runs today"
              value={String(overview.runs_today)}
              delta={overview.runs_today_delta_pct}
            />
            <KpiCard
              title="Cost 24h"
              value={formatCost(overview.cost_usd_24h)}
              delta={overview.cost_usd_24h_delta_pct}
            />
            <KpiCard
              title="Health"
              value={healthPill}
              delta={null}
            />
          </div>

          {/* Runs chart */}
          <div>
            <p className="mb-2 text-xs font-medium text-fg-muted">Runs (24h, by hour)</p>
            <RunsChart data={runsSeries} />
          </div>

          {/* Tool usage chart */}
          <div>
            <p className="mb-2 text-xs font-medium text-fg-muted">Top tools used (24h)</p>
            <ToolUsageChart data={toolUsage} />
          </div>

          {/* Footer stats */}
          <div className="flex gap-4 text-xs text-fg-muted">
            <span>Queue depth · <span className="text-fg font-medium">{overview.queue_depth}</span></span>
            <span>Avg latency · <span className="text-fg font-medium">{formatLatency(overview.avg_latency_ms_24h)}</span></span>
          </div>

          {/* Health summary */}
          <div>
            <p className="mb-2 text-xs font-medium text-fg-muted">Integration health</p>
            <IntegrationsHealthSummary health={health} />
          </div>
        </>
      )}
    </div>
  );
}
