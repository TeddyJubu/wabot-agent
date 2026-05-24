import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import OverviewPanel from "@/components/slide-overs/OverviewPanel";
import type {
  OverviewResponse,
  RunsSeriesResponse,
  ToolUsageResponse,
  HealthResponse,
} from "@/api/metrics";

// ---------------------------------------------------------------------------
// Mock recharts — ResponsiveContainer requires a real DOM size measurement
// ---------------------------------------------------------------------------

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

// ---------------------------------------------------------------------------
// Mock API
// ---------------------------------------------------------------------------

vi.mock("@/api/metrics", () => ({
  getOverview: vi.fn(),
  getRunsSeries: vi.fn(),
  getToolUsage: vi.fn(),
  getCosts: vi.fn(),
  getHealth: vi.fn(),
}));

import * as metricsApi from "@/api/metrics";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const OVERVIEW: OverviewResponse = {
  messages_today: 1284,
  messages_today_delta_pct: 12,
  runs_today: 342,
  runs_today_delta_pct: 4,
  avg_latency_ms_24h: 1200,
  cost_usd_24h: 3.81,
  cost_usd_24h_delta_pct: -8,
  integrations_health: { ok: 7, error: 1, unknown: 0 },
  queue_depth: 7,
};

const RUNS_SERIES: RunsSeriesResponse = {
  window: "24h",
  bucket: "hour",
  series: [],
};

const TOOL_USAGE: ToolUsageResponse = {
  window: "24h",
  items: [
    { tool_name: "web_search", invocations: 45, avg_latency_ms: 800, errors: 0 },
    { tool_name: "memory_write", invocations: 22, avg_latency_ms: 50, errors: 0 },
  ],
};

const HEALTH: HealthResponse = {
  wabot_daemon: { status: "ok", message: null, last_checked_at: "2026-01-01T00:00:00" },
  mcp_servers: [
    { id: 1, name: "filesystem", status: "ok", message: null, last_checked_at: null },
  ],
  composio: { status: "ok", connections_count: 2, last_error: null },
};

const EMPTY_OVERVIEW: OverviewResponse = {
  messages_today: 0,
  messages_today_delta_pct: null,
  runs_today: 0,
  runs_today_delta_pct: null,
  avg_latency_ms_24h: null,
  cost_usd_24h: 0,
  cost_usd_24h_delta_pct: null,
  integrations_health: { ok: 0, error: 0, unknown: 0 },
  queue_depth: 0,
};

function mockAllApis(ov: OverviewResponse = OVERVIEW) {
  vi.mocked(metricsApi.getOverview).mockResolvedValue(ov);
  vi.mocked(metricsApi.getRunsSeries).mockResolvedValue(RUNS_SERIES);
  vi.mocked(metricsApi.getToolUsage).mockResolvedValue(TOOL_USAGE);
  vi.mocked(metricsApi.getHealth).mockResolvedValue(HEALTH);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OverviewPanel — KPI tiles", () => {
  it("renders KPI tiles with values from mocked getOverview", async () => {
    mockAllApis();
    render(<OverviewPanel />);

    await waitFor(() => expect(screen.getByText("1,284")).toBeInTheDocument());

    expect(screen.getByText("342")).toBeInTheDocument();
    expect(screen.getByText("$3.81")).toBeInTheDocument();
  });

  it("shows queue depth and avg latency in footer stats", async () => {
    mockAllApis();
    render(<OverviewPanel />);

    await waitFor(() => screen.getByText("1,284"));
    expect(screen.getByText("7")).toBeInTheDocument();
    // latency 1200ms -> 1.2s
    expect(screen.getByText("1.2s")).toBeInTheDocument();
  });
});

describe("OverviewPanel — delta indicators", () => {
  it("shows percentage text for positive delta", async () => {
    mockAllApis();
    render(<OverviewPanel />);

    await waitFor(() => screen.getByText("1,284"));

    // Messages today delta = +12% — percentage text should appear
    const deltaEls = screen.getAllByText("12%");
    expect(deltaEls.length).toBeGreaterThan(0);
  });

  it("shows percentage text for negative delta", async () => {
    mockAllApis();
    render(<OverviewPanel />);

    await waitFor(() => screen.getByText("1,284"));

    // Cost delta = -8% — absolute value shown
    const deltaEls = screen.getAllByText("8%");
    expect(deltaEls.length).toBeGreaterThan(0);
  });

  it("shows neutral indicator for null delta", async () => {
    mockAllApis(EMPTY_OVERVIEW);
    render(<OverviewPanel />);

    // All deltas null -> aria-label "delta nil" on the containers
    // Wait for the overview to load (queue depth 0 shows in footer)
    await waitFor(() => {
      const nilIndicators = screen.getAllByLabelText("delta nil");
      // 4 KPI cards, all with null delta
      expect(nilIndicators.length).toBeGreaterThanOrEqual(1);
    });
  });
});

describe("OverviewPanel — Refresh button", () => {
  it("Refresh button calls all four APIs again", async () => {
    mockAllApis();
    render(<OverviewPanel />);

    await waitFor(() => screen.getByText("1,284"));

    expect(metricsApi.getOverview).toHaveBeenCalledTimes(1);
    expect(metricsApi.getRunsSeries).toHaveBeenCalledTimes(1);
    expect(metricsApi.getToolUsage).toHaveBeenCalledTimes(1);
    expect(metricsApi.getHealth).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /refresh overview/i }));

    await waitFor(() => expect(metricsApi.getOverview).toHaveBeenCalledTimes(2));
    expect(metricsApi.getRunsSeries).toHaveBeenCalledTimes(2);
    expect(metricsApi.getToolUsage).toHaveBeenCalledTimes(2);
    expect(metricsApi.getHealth).toHaveBeenCalledTimes(2);
  });
});

describe("OverviewPanel — empty state", () => {
  it("renders when all values are 0 / null", async () => {
    mockAllApis(EMPTY_OVERVIEW);
    render(<OverviewPanel />);

    // All numeric KPIs show 0
    await waitFor(() => {
      const zeros = screen.getAllByText("0");
      expect(zeros.length).toBeGreaterThan(0);
    });
  });

  it("shows error state when getOverview rejects", async () => {
    vi.mocked(metricsApi.getOverview).mockRejectedValue(new Error("network error"));
    vi.mocked(metricsApi.getRunsSeries).mockResolvedValue(RUNS_SERIES);
    vi.mocked(metricsApi.getToolUsage).mockResolvedValue(TOOL_USAGE);
    vi.mocked(metricsApi.getHealth).mockResolvedValue(HEALTH);

    render(<OverviewPanel />);

    await waitFor(() => expect(screen.getByText(/network error/i)).toBeInTheDocument());
  });
});
