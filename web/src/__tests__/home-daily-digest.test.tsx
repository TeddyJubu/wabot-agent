import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import type {
  OverviewResponse,
  RunsSeriesResponse,
} from "@/api/metrics";
import type { PairingState } from "@/api/pairing";
import { useStore, type Readiness } from "@/store";
import DailyDigest from "@/components/home/DailyDigest";

// ---------------------------------------------------------------------------
// Mock recharts — ResponsiveContainer requires a real DOM size measurement.
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
// Mock metrics API
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

const EMPTY_RUNS: RunsSeriesResponse = {
  window: "24h",
  bucket: "hour",
  series: [],
};

const ACTIVE_RUNS: RunsSeriesResponse = {
  window: "24h",
  bucket: "hour",
  series: [
    { timestamp: "2026-05-24T00:00:00", count: 3, by_agent: {} },
    { timestamp: "2026-05-24T01:00:00", count: 7, by_agent: {} },
    { timestamp: "2026-05-24T02:00:00", count: 2, by_agent: {} },
  ],
};

const PENDING_ROW = { label: "Checking…", variant: "pending" as const };
const HEALTHY_READINESS: Readiness = {
  overall: "ok",
  model: { label: "openai", variant: "ok" },
  wabot: { label: "configured", variant: "ok" },
  policy: { label: "dry_run", variant: "ok" },
  memory: { label: "ready", variant: "ok" },
};
const PRISTINE_READINESS: Readiness = {
  overall: "pending",
  model: PENDING_ROW,
  wabot: PENDING_ROW,
  policy: PENDING_ROW,
  memory: PENDING_ROW,
};

function pairing(overrides: Partial<PairingState> = {}): PairingState {
  return {
    qr_available: false,
    logged_in: true,
    connected: true,
    reachable: true,
    ...overrides,
  };
}

function mockMetrics(
  ov: OverviewResponse = OVERVIEW,
  rs: RunsSeriesResponse = EMPTY_RUNS,
) {
  vi.mocked(metricsApi.getOverview).mockResolvedValue(ov);
  vi.mocked(metricsApi.getRunsSeries).mockResolvedValue(rs);
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    readiness: HEALTHY_READINESS,
    pairing: pairing(),
    slideOver: null,
  });
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// KPI tiles
// ---------------------------------------------------------------------------

describe("DailyDigest — KPI tiles", () => {
  it("renders formatted values from getOverview", async () => {
    mockMetrics();
    render(<DailyDigest />);

    await waitFor(() => expect(screen.getByText("1,284")).toBeInTheDocument());
    expect(screen.getByText("342")).toBeInTheDocument();
    expect(screen.getByText("$3.81")).toBeInTheDocument();
    // Queue depth tile renders the value too.
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("labels each tile", async () => {
    mockMetrics();
    render(<DailyDigest />);

    await waitFor(() => screen.getByText("1,284"));
    for (const label of [
      "Messages today",
      "Runs today",
      "Cost 24h",
      "Queue depth",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});

// ---------------------------------------------------------------------------
// Sparkline
// ---------------------------------------------------------------------------

describe("DailyDigest — sparkline", () => {
  it("renders the sparkline when the series is non-empty", async () => {
    mockMetrics(OVERVIEW, ACTIVE_RUNS);
    render(<DailyDigest />);

    await waitFor(() =>
      expect(screen.getByTestId("responsive-container")).toBeInTheDocument(),
    );
  });

  it("shows a placeholder when the series is empty", async () => {
    mockMetrics(OVERVIEW, EMPTY_RUNS);
    render(<DailyDigest />);

    await waitFor(() =>
      expect(
        screen.getByText(/No activity in the last 24 hours/i),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("responsive-container")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Next action card
// ---------------------------------------------------------------------------

describe("DailyDigest — Next action card", () => {
  it("warns when send policy is allow_all and the button opens settings", async () => {
    const openSlideOver = vi.fn();
    useStore.setState({
      openSlideOver,
      readiness: {
        ...PRISTINE_READINESS,
        model: { label: "openai", variant: "ok" },
        wabot: { label: "configured", variant: "ok" },
        memory: { label: "ready", variant: "ok" },
        policy: { label: "allow_all", variant: "warn" },
      },
    });
    mockMetrics();
    render(<DailyDigest />);

    expect(
      await screen.findByText(
        /Send policy is allow_all\. Review who can be messaged\./i,
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(openSlideOver).toHaveBeenCalledWith("settings");
  });

  it("shows the all-systems-normal copy when everything is healthy", async () => {
    mockMetrics();
    render(<DailyDigest />);

    expect(
      await screen.findByText(/All systems normal/i),
    ).toBeInTheDocument();
    // No "Open settings" warning button.
    expect(screen.queryByRole("button", { name: "Open settings" })).toBeNull();
  });

  it("warns when wabot endpoint is not configured", async () => {
    const openSlideOver = vi.fn();
    useStore.setState({
      openSlideOver,
      readiness: {
        ...HEALTHY_READINESS,
        wabot: { label: "missing", variant: "warn" },
      },
    });
    mockMetrics();
    render(<DailyDigest />);

    expect(
      await screen.findByText(/wabot endpoint isn't configured/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(openSlideOver).toHaveBeenCalledWith("settings");
  });

  it("warns when WhatsApp is not paired and the button opens /pair", async () => {
    useStore.setState({
      pairing: pairing({ logged_in: false, connected: false }),
    });
    mockMetrics();
    render(<DailyDigest />);

    expect(
      await screen.findByText(/WhatsApp isn't paired/i),
    ).toBeInTheDocument();

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open /pair" }));
    expect(openSpy).toHaveBeenCalledWith("/pair", "_blank", "noopener");
  });
});

// ---------------------------------------------------------------------------
// Accessibility
// ---------------------------------------------------------------------------

describe("DailyDigest — accessibility", () => {
  it("has no axe-detectable a11y violations", async () => {
    mockMetrics();
    const { container } = render(<DailyDigest />);
    await waitFor(() => screen.getByText("1,284"));
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
