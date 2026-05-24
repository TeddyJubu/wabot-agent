import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { SettingsView } from "@/api/settings";
import type {
  OverviewResponse,
  RunsSeriesResponse,
  ToolUsageResponse,
  HealthResponse,
} from "@/api/metrics";
import { useStore, type Readiness } from "@/store";
import { useUiFlagStore } from "@/store/uiFlag";
import { useRouteStore } from "@/store/route";
import App from "@/App";

// ---------------------------------------------------------------------------
// Mocks — mirror app-routing.test.tsx + overview-panel.test.tsx so <App />
// can mount without hitting Clerk, the pairing stream, real settings, or
// real metrics endpoints (the Insights route renders OverviewPanel).
// ---------------------------------------------------------------------------

vi.mock("@/components/ClerkNavAuth", () => ({
  ClerkNavAuth: () => null,
}));

vi.mock("@/hooks/usePairingStream", () => ({
  usePairingStream: () => {},
}));

const STABLE_SETTINGS: SettingsView = {
  env_source: "env",
  send_policy: "dry_run",
  send_policy_choices: ["dry_run", "allowlist", "allow_all", "owner"],
  allowed_recipients: [],
  owner_numbers: [],
  max_agent_turns: 8,
  model_routing: {},
  subagents_enabled: false,
  llm: {
    provider: "openai",
    provider_choices: ["openai", "codex", "openrouter", "ollama", "ollama_cloud"],
    model: "gpt-4o",
    label: "openai · gpt-4o",
    live: true,
  },
  openai: {
    api_key: { set: true, preview: "sk-…abcd" },
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o",
    live: true,
  },
  codex: {
    access_token: { set: false, preview: null },
    account_id: null,
    auth_path: "",
    base_url: "",
    model: "",
    model_choices: [],
    reasoning_effort: "medium",
    reasoning_effort_choices: ["low", "medium", "high"],
    reasoning_effort_labels: { low: "Low", medium: "Medium", high: "High" },
    live: false,
    logged_in: false,
    cli_available: false,
  },
  openrouter: {
    api_key: { set: false, preview: null },
    base_url: "https://openrouter.ai/api/v1",
    model: "",
    live: false,
  },
  ollama: {
    api_key: { set: false, preview: null },
    model: "",
    base_url: "http://localhost:11434",
    cloud_base_url: "",
    live: false,
  },
  wabot: {
    endpoint: "http://localhost:8080",
    token: { set: true, preview: "tok…1234" },
    token_file: null,
  },
};

vi.mock("@/api/settings", () => ({
  fetchSettings: vi.fn(() => Promise.resolve(STABLE_SETTINGS)),
  patchSettings: vi.fn(() => Promise.resolve()),
  testOpenRouter: vi.fn(() => Promise.resolve({ ok: true, detail: "" })),
  testOpenAI: vi.fn(() => Promise.resolve({ ok: true, detail: "" })),
}));

// recharts ResponsiveContainer needs a real layout — replace with a div.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

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
const RUNS_SERIES: RunsSeriesResponse = { window: "24h", bucket: "hour", series: [] };
const TOOL_USAGE: ToolUsageResponse = { window: "24h", items: [] };
const HEALTH: HealthResponse = {
  wabot_daemon: { status: "ok", message: null, last_checked_at: null },
  mcp_servers: [],
  composio: { status: "ok", connections_count: 0, last_error: null },
};

vi.mock("@/api/metrics", () => ({
  getOverview: vi.fn(() => Promise.resolve(OVERVIEW)),
  getRunsSeries: vi.fn(() => Promise.resolve(RUNS_SERIES)),
  getToolUsage: vi.fn(() => Promise.resolve(TOOL_USAGE)),
  getCosts: vi.fn(() => Promise.resolve({ window: "24h", items: [] })),
  getHealth: vi.fn(() => Promise.resolve(HEALTH)),
}));

// ---------------------------------------------------------------------------
// Setup — flip the URL flag to ?ui=v2 and reset every relevant store.
// ---------------------------------------------------------------------------

const PENDING_ROW = { label: "Checking…", variant: "pending" as const };
const PRISTINE_READINESS: Readiness = {
  overall: "pending",
  model: PENDING_ROW,
  wabot: PENDING_ROW,
  policy: PENDING_ROW,
  memory: PENDING_ROW,
};

function setSearch(search: string) {
  window.history.replaceState(
    {},
    "",
    search ? `/?${search.replace(/^\?/, "")}` : "/",
  );
  useUiFlagStore.getState().resetUiFlagFromUrl();
}

beforeEach(() => {
  setSearch("ui=v2");
  useStore.setState({
    readiness: PRISTINE_READINESS,
    slideOver: null,
    pairing: null,
  });
  useRouteStore.setState({ route: "home" });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("App shell (v2)", () => {
  it("renders the primary navigation rail behind ?ui=v2", async () => {
    render(<App />);
    expect(
      await screen.findByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
  });

  it("defaults to the Home route with HomePanel mounted", async () => {
    render(<App />);
    // B3 ships HomePanel for the Home route. Without a ClerkProvider in this
    // test (no `@clerk/clerk-react` mock), HomePanel's internal ClerkBoundary
    // catches the useUser() throw and degrades to the signed-out state, which
    // renders the SetupChecklist (its <ol aria-label="Setup checklist">).
    expect(
      await screen.findByLabelText("Setup checklist"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Home" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("clicking Insights swaps the content slot to OverviewPanel", async () => {
    render(<App />);

    // Make sure the rail is mounted before clicking.
    const insights = await screen.findByRole("button", { name: "Insights" });
    fireEvent.click(insights);

    // OverviewPanel renders a KPI tile showing `messages_today` formatted with
    // a thousands separator once getOverview resolves. We assert on that text
    // rather than the recharts ResponsiveContainer test-id, because with an
    // empty `series` fixture RunsChart short-circuits to a placeholder div
    // before reaching ResponsiveContainer (see overview/RunsChart.tsx).
    await waitFor(() => {
      expect(screen.getByText("1,284")).toBeInTheDocument();
    });

    // And the Home view (SetupChecklist via ClerkBoundary fallback) is gone.
    expect(screen.queryByLabelText("Setup checklist")).toBeNull();
  });
});
