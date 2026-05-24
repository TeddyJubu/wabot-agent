/**
 * API client for /api/metrics — Phase 6.
 *
 * Auth: all endpoints require credentials (operator token via session cookie).
 */

import { parseJson } from "./_http";

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

export type OverviewResponse = {
  messages_today: number;
  messages_today_delta_pct: number | null;
  runs_today: number;
  runs_today_delta_pct: number | null;
  avg_latency_ms_24h: number | null;
  cost_usd_24h: number;
  cost_usd_24h_delta_pct: number | null;
  integrations_health: { ok: number; error: number; unknown: number };
  queue_depth: number;
};

export type RunsSeriesResponse = {
  window: "1h" | "24h" | "7d" | "30d";
  bucket: "minute" | "hour" | "day";
  series: Array<{ timestamp: string; count: number; by_agent: Record<string, number> }>;
};

export type ToolUsageResponse = {
  window: string;
  items: Array<{
    tool_name: string;
    invocations: number;
    avg_latency_ms: number | null;
    errors: number;
  }>;
};

export type CostsResponse = {
  window: string;
  total_usd: number;
  by_day: Array<{ date: string; usd: number }>;
  by_provider: Array<{
    provider: string;
    usd: number;
    model_breakdown: Record<string, number>;
  }>;
};

export type HealthResponse = {
  wabot_daemon: {
    status: "ok" | "error" | "unknown";
    message: string | null;
    last_checked_at: string | null;
  };
  mcp_servers: Array<{
    id: number;
    name: string;
    status: string;
    message: string | null;
    last_checked_at: string | null;
  }>;
  composio: {
    status: string;
    connections_count: number;
    last_error: string | null;
  };
};

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function getOverview(): Promise<OverviewResponse> {
  const res = await fetch("/api/metrics/overview", { credentials: "include" });
  return parseJson<OverviewResponse>(res);
}

export async function getRunsSeries(params: {
  window?: "1h" | "24h" | "7d" | "30d";
  bucket?: "minute" | "hour" | "day";
} = {}): Promise<RunsSeriesResponse> {
  const q = new URLSearchParams();
  if (params.window) q.set("window", params.window);
  if (params.bucket) q.set("bucket", params.bucket);
  const qs = q.toString();
  const res = await fetch(`/api/metrics/runs${qs ? `?${qs}` : ""}`, {
    credentials: "include",
  });
  return parseJson<RunsSeriesResponse>(res);
}

export async function getToolUsage(params: {
  window?: string;
  limit?: number;
} = {}): Promise<ToolUsageResponse> {
  const q = new URLSearchParams();
  if (params.window) q.set("window", params.window);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  const qs = q.toString();
  const res = await fetch(`/api/metrics/tools${qs ? `?${qs}` : ""}`, {
    credentials: "include",
  });
  return parseJson<ToolUsageResponse>(res);
}

export async function getCosts(params: { window?: string } = {}): Promise<CostsResponse> {
  const q = new URLSearchParams();
  if (params.window) q.set("window", params.window);
  const qs = q.toString();
  const res = await fetch(`/api/metrics/costs${qs ? `?${qs}` : ""}`, {
    credentials: "include",
  });
  return parseJson<CostsResponse>(res);
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/metrics/health", { credentials: "include" });
  return parseJson<HealthResponse>(res);
}
