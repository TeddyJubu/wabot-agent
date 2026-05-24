import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import InsightsPage from "@/pages/InsightsPage";
import type {
  HealthResponse,
  OverviewResponse,
  RunsSeriesResponse,
  ToolUsageResponse,
} from "@/api/metrics";

// ---------------------------------------------------------------------------
// Mock recharts — ResponsiveContainer needs real DOM measurement otherwise.
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
// Mock API modules — InsightsPage indirectly fans out to metrics (OverviewPanel,
// inside ActivityPanel sub-tabs) and runs (ActivityPanel default tab).
// ---------------------------------------------------------------------------

vi.mock("@/api/metrics", () => ({
  getOverview: vi.fn(),
  getRunsSeries: vi.fn(),
  getToolUsage: vi.fn(),
  getCosts: vi.fn(),
  getHealth: vi.fn(),
}));

vi.mock("@/api/runs", () => ({
  fetchRuns: vi.fn(),
}));

import * as metricsApi from "@/api/metrics";
import * as runsApi from "@/api/runs";

// ---------------------------------------------------------------------------
// Fixtures — mirror overview-panel.test.tsx so OverviewPanel mounts to its
// "ready" state and exposes the 1,284 marker we assert on for "Live".
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
  ],
};

const HEALTH: HealthResponse = {
  wabot_daemon: {
    status: "ok",
    message: null,
    last_checked_at: "2026-01-01T00:00:00",
  },
  mcp_servers: [
    { id: 1, name: "filesystem", status: "ok", message: null, last_checked_at: null },
  ],
  composio: { status: "ok", connections_count: 2, last_error: null },
};

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(metricsApi.getOverview).mockResolvedValue(OVERVIEW);
  vi.mocked(metricsApi.getRunsSeries).mockResolvedValue(RUNS_SERIES);
  vi.mocked(metricsApi.getToolUsage).mockResolvedValue(TOOL_USAGE);
  vi.mocked(metricsApi.getHealth).mockResolvedValue(HEALTH);
  vi.mocked(runsApi.fetchRuns).mockResolvedValue([]);
  // Reset URL hash so each test starts from a known state.
  window.history.replaceState(null, "", "/");
});

// ---------------------------------------------------------------------------
// Tablist a11y
// ---------------------------------------------------------------------------

describe("InsightsPage — tablist a11y", () => {
  it("renders a labelled tablist with two correctly-wired tabs and panel", () => {
    render(<InsightsPage />);

    const tablist = screen.getByRole("tablist", { name: "Insights sections" });
    expect(tablist).toBeInTheDocument();

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);

    const live = screen.getByRole("tab", { name: "Live" });
    const log = screen.getByRole("tab", { name: "Log" });

    expect(live).toHaveAttribute("aria-selected", "true");
    expect(live).toHaveAttribute("aria-controls", "insights-panel-live");
    expect(live).toHaveAttribute("tabindex", "0");

    expect(log).toHaveAttribute("aria-selected", "false");
    expect(log).toHaveAttribute("aria-controls", "insights-panel-log");
    expect(log).toHaveAttribute("tabindex", "-1");

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "insights-panel-live");
    expect(panel).toHaveAttribute("aria-labelledby", "insights-tab-live");
  });
});

// ---------------------------------------------------------------------------
// Default tab — Live
// ---------------------------------------------------------------------------

describe("InsightsPage — default tab", () => {
  it("mounts the Live (OverviewPanel) tab by default with no hash", async () => {
    render(<InsightsPage />);

    // OverviewPanel KPI marker — proves the Live panel is mounted + loaded.
    await waitFor(() =>
      expect(screen.getByText("1,284")).toBeInTheDocument(),
    );

    // The Log panel should NOT be mounted (so fetchRuns shouldn't have run).
    expect(runsApi.fetchRuns).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Tab switching — clicking Log mounts ActivityPanel
// ---------------------------------------------------------------------------

describe("InsightsPage — tab switching", () => {
  it("clicking Log activates the Log tab and mounts ActivityPanel", async () => {
    render(<InsightsPage />);
    await waitFor(() => screen.getByText("1,284"));

    fireEvent.click(screen.getByRole("tab", { name: "Log" }));

    const logTab = screen.getByRole("tab", { name: "Log" });
    expect(logTab).toHaveAttribute("aria-selected", "true");
    expect(logTab).toHaveAttribute("tabindex", "0");

    const liveTab = screen.getByRole("tab", { name: "Live" });
    expect(liveTab).toHaveAttribute("aria-selected", "false");
    expect(liveTab).toHaveAttribute("tabindex", "-1");

    // Panel swap: tabpanel is now the Log panel.
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "insights-panel-log");
    expect(panel).toHaveAttribute("aria-labelledby", "insights-tab-log");

    // ActivityPanel's default sub-tab is Runs — fetchRuns should have fired.
    await waitFor(() => expect(runsApi.fetchRuns).toHaveBeenCalled());

    // The ActivityPanel sub-tab "Runs" should be present as a tab.
    expect(screen.getByRole("tab", { name: "Runs" })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// URL hash sync
// ---------------------------------------------------------------------------

describe("InsightsPage — URL hash sync", () => {
  it("updates window.location.hash when switching tabs", async () => {
    render(<InsightsPage />);
    await waitFor(() => screen.getByText("1,284"));

    fireEvent.click(screen.getByRole("tab", { name: "Log" }));
    expect(window.location.hash).toBe("#log");

    fireEvent.click(screen.getByRole("tab", { name: "Live" }));
    expect(window.location.hash).toBe("#live");
  });

  it("deep-link to #log activates the Log tab on first mount", async () => {
    window.history.replaceState(null, "", "/#log");

    render(<InsightsPage />);

    const logTab = screen.getByRole("tab", { name: "Log" });
    expect(logTab).toHaveAttribute("aria-selected", "true");

    // Live should NOT have fetched data — only Log is mounted.
    expect(metricsApi.getOverview).not.toHaveBeenCalled();
    await waitFor(() => expect(runsApi.fetchRuns).toHaveBeenCalled());
  });
});

// ---------------------------------------------------------------------------
// Arrow-key roving
// ---------------------------------------------------------------------------

describe("InsightsPage — arrow-key roving", () => {
  it("ArrowRight from the active tab moves activation + focus to the next tab", async () => {
    render(<InsightsPage />);
    await waitFor(() => screen.getByText("1,284"));

    const live = screen.getByRole("tab", { name: "Live" });
    live.focus();
    expect(document.activeElement).toBe(live);

    fireEvent.keyDown(live, { key: "ArrowRight" });

    const log = screen.getByRole("tab", { name: "Log" });
    expect(log).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(log);
  });

  it("ArrowLeft from the first tab wraps to the last", async () => {
    render(<InsightsPage />);
    await waitFor(() => screen.getByText("1,284"));

    const live = screen.getByRole("tab", { name: "Live" });
    live.focus();

    fireEvent.keyDown(live, { key: "ArrowLeft" });

    const log = screen.getByRole("tab", { name: "Log" });
    expect(log).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(log);
  });
});

// ---------------------------------------------------------------------------
// Tap-target floor
// ---------------------------------------------------------------------------

describe("InsightsPage — tap targets", () => {
  it("every tab button reserves a 44px min height", () => {
    render(<InsightsPage />);

    for (const label of ["Live", "Log"] as const) {
      const tab = screen.getByRole("tab", { name: label });
      expect(tab.className).toMatch(/min-h-\[44px\]/);
    }
  });
});

// ---------------------------------------------------------------------------
// Accessibility — jest-axe sweep on the fully-mounted page.
// ---------------------------------------------------------------------------

describe("InsightsPage — accessibility", () => {
  it("has no axe-detectable violations", async () => {
    const { container } = render(<InsightsPage />);
    await waitFor(() => screen.getByText("1,284"));
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
