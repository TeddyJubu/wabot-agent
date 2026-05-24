import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ActivityPanel from "@/components/slide-overs/ActivityPanel";
import type { Run } from "@/api/runs";
import type { CostsResponse, ToolUsageResponse } from "@/api/metrics";

// ---------------------------------------------------------------------------
// Mock recharts
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
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/runs", () => ({
  fetchRuns: vi.fn(),
}));

vi.mock("@/api/metrics", () => ({
  getOverview: vi.fn(),
  getRunsSeries: vi.fn(),
  getToolUsage: vi.fn(),
  getCosts: vi.fn(),
  getHealth: vi.fn(),
}));

import * as runsApi from "@/api/runs";
import * as metricsApi from "@/api/metrics";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeRun(i: number, daysAgo = 0): Run {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return {
    run_id: `run-${String(i).padStart(4, "0")}-aaaa-bbbb`,
    sender: i % 2 === 0 ? "orchestrator" : "scraper",
    user_input: `User message ${i}`,
    final_output: `Reply ${i}`,
    created_at: d.toISOString(),
  };
}

const RUNS_100 = Array.from({ length: 100 }, (_, i) => makeRun(i));
const RUNS_STALE = Array.from({ length: 5 }, (_, i) => makeRun(i, 10)); // older than 7d

const COSTS: CostsResponse = {
  window: "24h",
  total_usd: 1.5,
  by_day: [
    { date: "2026-01-01", usd: 0.5 },
    { date: "2026-01-02", usd: 1.0 },
  ],
  by_provider: [
    { provider: "anthropic", usd: 1.2, model_breakdown: { "claude-sonnet-4": 1.2 } },
    { provider: "openai", usd: 0.3, model_breakdown: { "gpt-4o": 0.3 } },
  ],
};

const TOOL_USAGE: ToolUsageResponse = {
  window: "24h",
  items: [
    { tool_name: "web_search", invocations: 10, avg_latency_ms: 500, errors: 0 },
  ],
};

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Default: getToolUsage for the ToolEventsTab
  vi.mocked(metricsApi.getToolUsage).mockResolvedValue(TOOL_USAGE);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ActivityPanel — Runs tab (default)", () => {
  it("renders Runs tab by default with fetched runs", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue(RUNS_100);

    render(<ActivityPanel />);

    // Should call fetchRuns with 100
    await waitFor(() => expect(runsApi.fetchRuns).toHaveBeenCalledWith(100));

    // First run should be visible
    await waitFor(() => expect(screen.getByText("User message 0")).toBeInTheDocument());
  });

  it("shows empty state when no runs", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue([]);

    render(<ActivityPanel />);

    await waitFor(() =>
      expect(screen.getByText(/no runs match your filters/i)).toBeInTheDocument(),
    );
  });

  it("Runs tab is selected by default (aria-selected)", () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue([]);

    render(<ActivityPanel />);

    const runsTab = screen.getByRole("tab", { name: "Runs" });
    expect(runsTab).toHaveAttribute("aria-selected", "true");
  });
});

describe("ActivityPanel — tab switching", () => {
  it("switching to Costs tab renders getCosts data", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue([]);
    vi.mocked(metricsApi.getCosts).mockResolvedValue(COSTS);

    render(<ActivityPanel />);

    // Click Costs tab
    fireEvent.click(screen.getByRole("tab", { name: "Costs" }));

    await waitFor(() => expect(metricsApi.getCosts).toHaveBeenCalledWith({ window: "24h" }));

    // Total cost shown
    await waitFor(() => expect(screen.getByText("$1.5000")).toBeInTheDocument());
  });

  it("switching to Inbox tab shows inbox content", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue(RUNS_100);

    render(<ActivityPanel />);

    fireEvent.click(screen.getByRole("tab", { name: "Inbox" }));

    await waitFor(() => expect(screen.getByText("User message 0")).toBeInTheDocument());
  });

  it("switching to Tool events tab calls getToolUsage", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue([]);

    render(<ActivityPanel />);

    fireEvent.click(screen.getByRole("tab", { name: "Tool events" }));

    await waitFor(() => expect(metricsApi.getToolUsage).toHaveBeenCalled());
  });
});

describe("ActivityPanel — filter dropdowns", () => {
  it("agent filter dropdown changes visible runs", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue(RUNS_100);

    render(<ActivityPanel />);

    await waitFor(() => screen.getByText("User message 0"));

    const agentSelect = screen.getByLabelText("Filter by agent");

    // Filter to orchestrator only (even indices in RUNS_100)
    fireEvent.change(agentSelect, { target: { value: "orchestrator" } });

    // "User message 0" (sender=orchestrator) should still be visible
    await waitFor(() => expect(screen.getByText("User message 0")).toBeInTheDocument());

    // "User message 1" (sender=scraper) should not be visible
    expect(screen.queryByText("User message 1")).not.toBeInTheDocument();
  });

  it("time window filter hides runs older than selected window", async () => {
    vi.mocked(runsApi.fetchRuns).mockResolvedValue(RUNS_STALE);

    render(<ActivityPanel />);

    // Wait for runs to load
    await waitFor(() => expect(runsApi.fetchRuns).toHaveBeenCalled());

    // Change to 1h window — stale runs (10 days old) should be filtered out
    const windowSelect = screen.getByLabelText("Filter by time window");
    fireEvent.change(windowSelect, { target: { value: "1h" } });

    await waitFor(() =>
      expect(screen.getByText(/no runs match your filters/i)).toBeInTheDocument(),
    );
  });

  // -------------------------------------------------------------------------
  // Phase 6 review SHOULD FIX 2: long WhatsApp text is PII; truncate by
  // default with explicit show-full toggle per row.
  // -------------------------------------------------------------------------

  it("truncates long user_input by default and reveals full text on 'show full'", async () => {
    const longInput = "x".repeat(200);
    const run: Run = {
      run_id: "long-run-aaaa-bbbb",
      sender: "orchestrator",
      user_input: longInput,
      final_output: "ok",
      created_at: new Date().toISOString(),
    };
    vi.mocked(runsApi.fetchRuns).mockResolvedValue([run]);

    render(<ActivityPanel />);
    await waitFor(() => expect(runsApi.fetchRuns).toHaveBeenCalled());

    // Truncated text (80 chars + ellipsis) is visible; the full 200-char
    // string is NOT in the DOM until the user clicks Show Full.
    expect(screen.getByText(/^x{80}…$/)).toBeInTheDocument();
    expect(screen.queryByText(longInput)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show full/i }));

    expect(screen.getByText(longInput)).toBeInTheDocument();
    expect(screen.queryByText(/^x{80}…$/)).not.toBeInTheDocument();

    // Clicking again collapses back to truncated.
    fireEvent.click(screen.getByRole("button", { name: /show less/i }));
    expect(screen.getByText(/^x{80}…$/)).toBeInTheDocument();
  });
});
