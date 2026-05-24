import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import type {
  OverviewResponse,
  RunsSeriesResponse,
} from "@/api/metrics";
import type { PairingState } from "@/api/pairing";
import { useStore, type Readiness } from "@/store";
import HomePanel from "@/components/home/HomePanel";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockClerkUserState = {
  isSignedIn: false as boolean,
  user: null as null | { firstName: string | null },
};

vi.mock("@clerk/clerk-react", () => ({
  useUser: () => ({
    isLoaded: true,
    isSignedIn: mockClerkUserState.isSignedIn,
    user: mockClerkUserState.user,
  }),
}));

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

vi.mock("@/api/metrics", () => ({
  getOverview: vi.fn(),
  getRunsSeries: vi.fn(),
  getToolUsage: vi.fn(),
  getCosts: vi.fn(),
  getHealth: vi.fn(),
}));

vi.mock("@/api/knowledge", () => ({
  fetchKnowledgeIndex: vi.fn(() =>
    Promise.resolve({
      docs: [],
      budgets: { instructions: 0, contact: 0 },
    }),
  ),
}));

import * as metricsApi from "@/api/metrics";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PENDING_ROW = { label: "Checking…", variant: "pending" as const };

const PRISTINE_READINESS: Readiness = {
  overall: "pending",
  model: PENDING_ROW,
  wabot: PENDING_ROW,
  policy: PENDING_ROW,
  memory: PENDING_ROW,
};

const HEALTHY_READINESS: Readiness = {
  overall: "ok",
  model: { label: "openai", variant: "ok" },
  wabot: { label: "configured", variant: "ok" },
  policy: { label: "dry_run", variant: "ok" },
  memory: { label: "ready", variant: "ok" },
};

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

function pairing(overrides: Partial<PairingState> = {}): PairingState {
  return {
    qr_available: false,
    logged_in: true,
    connected: true,
    reachable: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockClerkUserState.isSignedIn = false;
  mockClerkUserState.user = null;
  vi.mocked(metricsApi.getOverview).mockResolvedValue(OVERVIEW);
  vi.mocked(metricsApi.getRunsSeries).mockResolvedValue(EMPTY_RUNS);
  useStore.setState({
    readiness: PRISTINE_READINESS,
    pairing: null,
    slideOver: null,
  });
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Default state — signed out, no pairing → SetupChecklist
// ---------------------------------------------------------------------------

describe("HomePanel — picks SetupChecklist by default", () => {
  it("renders the SetupChecklist when nothing is signed in or paired", () => {
    render(<HomePanel />);

    expect(screen.getByLabelText("Setup checklist")).toBeInTheDocument();
    expect(screen.queryByLabelText("Daily digest")).toBeNull();
  });

  it("greets 'there' when the user has no first name", () => {
    render(<HomePanel />);
    expect(
      screen.getByRole("heading", { name: /Welcome back, there\./i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Foundations complete → DailyDigest
// ---------------------------------------------------------------------------

describe("HomePanel — picks DailyDigest once foundations are done", () => {
  it("swaps to DailyDigest when signed in + paired + model ok", async () => {
    mockClerkUserState.isSignedIn = true;
    mockClerkUserState.user = { firstName: "Teddy" };
    useStore.setState({
      readiness: HEALTHY_READINESS,
      pairing: pairing({ logged_in: true }),
    });

    render(<HomePanel />);

    await waitFor(() =>
      expect(screen.getByLabelText("Daily digest")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Setup checklist")).toBeNull();

    expect(
      screen.getByRole("heading", { name: /Welcome back, Teddy\./i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Dismissed checklist persists via localStorage
// ---------------------------------------------------------------------------

describe("HomePanel — dismissed checklist", () => {
  it("renders DailyDigest when the checklist was previously dismissed", async () => {
    localStorage.setItem("wabot:dismissedChecklist", "1");

    render(<HomePanel />);

    // Even though foundations are incomplete, dismissal forces the digest.
    await waitFor(() =>
      expect(screen.getByLabelText("Daily digest")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Setup checklist")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Accessibility — both surfaces
// ---------------------------------------------------------------------------

describe("HomePanel — accessibility", () => {
  it("checklist state has no axe-detectable a11y violations", async () => {
    const { container } = render(<HomePanel />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("digest state has no axe-detectable a11y violations", async () => {
    mockClerkUserState.isSignedIn = true;
    mockClerkUserState.user = { firstName: "Teddy" };
    useStore.setState({
      readiness: HEALTHY_READINESS,
      pairing: pairing({ logged_in: true }),
    });

    const { container } = render(<HomePanel />);
    await waitFor(() => screen.getByLabelText("Daily digest"));
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
