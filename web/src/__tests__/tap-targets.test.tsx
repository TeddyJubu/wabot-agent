import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { SettingsView } from "@/api/settings";
import type {
  HealthResponse,
  OverviewResponse,
  RunsSeriesResponse,
  ToolUsageResponse,
} from "@/api/metrics";
import { useStore, type Readiness } from "@/store";
import { useRouteStore } from "@/store/route";

// ---------------------------------------------------------------------------
// Phase D · L2 — Tap-target audit (WCAG 2.5.5).
//
// jsdom does NOT compute real box sizes (getBoundingClientRect returns 0x0),
// so this audit relies on regex-matching the project's Tailwind size utilities
// on the rendered button's className. The accepted patterns are:
//   - `min-h-[44px]` (rectangular targets; text label naturally provides width)
//   - `h-11` / `h-12` … (explicit fixed height >= 44 px)
//   - `size-11` / `size-12` … (square targets >= 44 px)
//
// Surfaces that already comply use real `it(...)` tests.
// Surfaces that fail are documented with `it.skip(...)` and a precise TODO so
// the parent agent can either accept the existing size or schedule a follow-up.
// Per spec: this file does NOT modify any source — it only audits.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Mocks — minimum needed to mount each surface without hitting real APIs.
// ---------------------------------------------------------------------------

// Used by TopBar and any surface that wraps in <App />-like state.
vi.mock("@/components/ClerkNavAuth", () => ({
  ClerkNavAuth: () => null,
}));

// SettingsPage's only API surface is @/api/settings.
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

// CodexSection drags in a device-login poller — stub it out so timers don't leak.
vi.mock("@/hooks/useCodexLogin", () => ({
  useCodexLogin: () => ({
    codexLogin: null,
    busy: false,
    startLogin: vi.fn(),
    cancelLogin: vi.fn(),
    disconnect: vi.fn(),
  }),
}));

// InsightsPage indirectly mounts OverviewPanel + ActivityPanel; both depend on
// recharts and the metrics API. Stub recharts' ResponsiveContainer (it requires
// real layout measurement) and short-circuit all metrics endpoints.
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
  messages_today: 0,
  messages_today_delta_pct: 0,
  runs_today: 0,
  runs_today_delta_pct: 0,
  avg_latency_ms_24h: 0,
  cost_usd_24h: 0,
  cost_usd_24h_delta_pct: 0,
  integrations_health: { ok: 0, error: 0, unknown: 0 },
  queue_depth: 0,
};
const RUNS_SERIES: RunsSeriesResponse = {
  window: "24h",
  bucket: "hour",
  series: [],
};
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

vi.mock("@/api/runs", () => ({
  fetchRuns: vi.fn(() => Promise.resolve([])),
}));

// CapabilitiesPage mounts IntegrationsPanel + ToolsPanel — stub them so the
// audit stays focused on the page's own tab buttons and doesn't drag in their
// own deep API stubs (each panel has its own dedicated tap-target story).
vi.mock("@/components/slide-overs/IntegrationsPanel", () => ({
  default: () => <div data-testid="integrations-panel-stub" />,
}));
vi.mock("@/components/slide-overs/ToolsPanel", () => ({
  default: () => <div data-testid="tools-panel-stub" />,
}));

// CommandPalette kicks off a lazy `getSearchIndex()` fetch on mount which
// fans out to knowledge/agents/tools APIs. Mirror the command-palette.test.tsx
// pattern: keep the promise pending so the palette stays on its sync
// SLASH_COMMANDS fallback (which is exactly what we want to audit anyway).
const { getSearchIndexMock } = vi.hoisted(() => ({
  getSearchIndexMock: vi.fn<() => Promise<unknown[]>>(
    () => new Promise<unknown[]>(() => {}),
  ),
}));
vi.mock("@/searchIndex", async () => {
  const actual = await vi.importActual<typeof import("@/searchIndex")>(
    "@/searchIndex",
  );
  return {
    ...actual,
    getSearchIndex: getSearchIndexMock,
  };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Rectangular tap target — text-bearing buttons whose width is naturally
 * satisfied by the label. We only require height >= 44 px.
 *
 * Accepts any of:
 *  - `min-h-[44px]`
 *  - `h-11` ... `h-19` (44–76 px in Tailwind's default scale; sticking to
 *     1-digit second char to avoid false positives like `h-1px`)
 *  - `size-11` ... `size-19`
 */
// Regex note: `\b` does NOT match between `]` and a space because both are
// non-word characters. We use `(?=\s|$)` lookaheads at the end of bracketed
// arbitrary-value utilities so `min-h-[44px]` matches whether it ends the
// className or precedes another class.
function assertRectTapTarget(button: HTMLElement, surface: string): void {
  const cls = button.className;
  const ok =
    /(?:^|\s)min-h-\[44px\](?=\s|$)/.test(cls) ||
    /(?:^|\s)h-1[1-9](?=\s|$)/.test(cls) ||
    /(?:^|\s)size-1[1-9](?=\s|$)/.test(cls);
  if (!ok) {
    throw new Error(
      `[${surface}] button missing >=44px height utility. Got className: "${cls}"`,
    );
  }
}

/**
 * Square tap target — icon-only buttons that need BOTH min-w and min-h, or
 * a `size-N` utility that sets both axes simultaneously.
 */
function assertSquareTapTarget(button: HTMLElement, surface: string): void {
  const cls = button.className;
  const okSquareUtility = /(?:^|\s)size-1[1-9](?=\s|$)/.test(cls);
  const okExplicitBoth =
    (/(?:^|\s)min-h-\[44px\](?=\s|$)/.test(cls) ||
      /(?:^|\s)h-1[1-9](?=\s|$)/.test(cls)) &&
    (/(?:^|\s)min-w-\[44px\](?=\s|$)/.test(cls) ||
      /(?:^|\s)w-1[1-9](?=\s|$)/.test(cls));
  if (!okSquareUtility && !okExplicitBoth) {
    throw new Error(
      `[${surface}] icon button missing >=44x44px size utility. Got className: "${cls}"`,
    );
  }
}

/**
 * CommandPalette row tap target — the spec is more lenient here because the
 * palette is keyboard-driven (Enter dispatches; the row click is a convenience
 * affordance). Either `py-2`+ OR `min-h-[44px]` is acceptable.
 */
function assertOptionRowTapTarget(row: HTMLElement, surface: string): void {
  const cls = row.className;
  const ok =
    /(?:^|\s)min-h-\[44px\](?=\s|$)/.test(cls) ||
    /(?:^|\s)h-1[1-9](?=\s|$)/.test(cls) ||
    /(?:^|\s)size-1[1-9](?=\s|$)/.test(cls) ||
    /(?:^|\s)py-[2-9](?=\s|$)/.test(cls) ||
    /(?:^|\s)py-1[0-9](?=\s|$)/.test(cls);
  if (!ok) {
    throw new Error(
      `[${surface}] option row missing >=py-2 or >=44px height utility. Got className: "${cls}"`,
    );
  }
}

// ---------------------------------------------------------------------------
// Store reset — keep route/slideOver/pairing state pristine between cases.
// ---------------------------------------------------------------------------

const PENDING_ROW = { label: "Checking…", variant: "pending" as const };
const PRISTINE_READINESS: Readiness = {
  overall: "pending",
  model: PENDING_ROW,
  wabot: PENDING_ROW,
  policy: PENDING_ROW,
  memory: PENDING_ROW,
};

beforeEach(() => {
  useStore.setState({
    readiness: PRISTINE_READINESS,
    slideOver: null,
    pairing: null,
  });
  useRouteStore.setState({ route: "home" });
  window.history.replaceState(null, "", "/");
});

// ---------------------------------------------------------------------------
// 1. LeftRail — 7 rail buttons, all rectangular (icon + text label).
// ---------------------------------------------------------------------------

describe("Tap targets — LeftRail", () => {
  it("LeftRail buttons are >= 44px (rectangular)", async () => {
    const { default: LeftRail } = await import("@/components/LeftRail");
    render(<LeftRail />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBe(7);
    for (const button of buttons) {
      assertRectTapTarget(button, "LeftRail");
    }
  });
});

// ---------------------------------------------------------------------------
// 2. StatusBar — 4 chip buttons. CURRENTLY UNDER-SPEC (py-2 text-xs ~= 32 px).
// ---------------------------------------------------------------------------

describe("Tap targets — StatusBar", () => {
  it("StatusBar chip buttons satisfy the 44px height floor", async () => {
    // Fixed in Phase D L5: StatusBar.tsx chip className now carries
    // `min-h-[44px]` alongside the original px-3 py-2 text-xs.
    const { default: StatusBar } = await import("@/components/StatusBar");
    render(<StatusBar />);
    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(4);
    for (const chip of chips) {
      assertRectTapTarget(chip, "StatusBar");
    }
  });
});

// ---------------------------------------------------------------------------
// 3. TopBar — IconBtn uses `size-9` (36 px). UNDER-SPEC.
// ---------------------------------------------------------------------------

describe("Tap targets — TopBar", () => {
  it("TopBar icon buttons satisfy the 44x44px floor", async () => {
    // Fixed in Phase D L5: TopBar IconBtn + the Pairing anchor link both
    // upgraded from `size-9` (36 px) to `size-11` (44 px).
    const { default: TopBar } = await import("@/components/TopBar");
    render(<TopBar />);
    const buttons = screen.getAllByRole("button");
    // Filter out the "wabot-agent" status-popover trigger which is a text
    // button, not an icon button — it's not a tap-target concern.
    const iconButtons = buttons.filter(
      (b) => !b.textContent?.includes("wabot-agent"),
    );
    expect(iconButtons.length).toBeGreaterThan(0);
    for (const button of iconButtons) {
      assertSquareTapTarget(button, "TopBar IconBtn");
    }
  });
});

// ---------------------------------------------------------------------------
// 4. ConfirmDialog — primary + secondary buttons. UNDER-SPEC (py-1.5 ~= 32 px).
// ---------------------------------------------------------------------------

describe("Tap targets — ConfirmDialog", () => {
  it("ConfirmDialog primary + cancel buttons satisfy the 44px height floor", async () => {
    // Fixed in Phase D L5: ConfirmDialog Cancel + primary button class lists
    // now carry `min-h-[44px]` and bumped padding to `px-4 py-2`.
    const { ConfirmDialog } = await import("@/components/ConfirmDialog");
    render(
      <ConfirmDialog
        open
        title="Tap-target audit"
        confirmLabel="Confirm"
        cancelLabel="Cancel"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    assertRectTapTarget(cancel, "ConfirmDialog cancel");
    assertRectTapTarget(confirm, "ConfirmDialog confirm");
  });
});

// ---------------------------------------------------------------------------
// 5. SettingsPage tabs — 5 tabs, already shipped with `min-h-[44px]`.
// ---------------------------------------------------------------------------

describe("Tap targets — SettingsPage tabs", () => {
  it("SettingsPage tab buttons are >= 44px (rectangular)", async () => {
    const { default: SettingsPage } = await import("@/pages/SettingsPage");
    render(<SettingsPage />);
    // Page renders a "Loading…" paragraph until fetchSettings resolves.
    await screen.findByRole("tablist", { name: "Settings sections" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(5);
    for (const tab of tabs) {
      assertRectTapTarget(tab, "SettingsPage tab");
    }
  });
});

// ---------------------------------------------------------------------------
// 6. InsightsPage tabs — 2 tabs, already shipped with `min-h-[44px]`.
// ---------------------------------------------------------------------------

describe("Tap targets — InsightsPage tabs", () => {
  it("InsightsPage tab buttons are >= 44px (rectangular)", async () => {
    const { default: InsightsPage } = await import("@/pages/InsightsPage");
    render(<InsightsPage />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    for (const tab of tabs) {
      assertRectTapTarget(tab, "InsightsPage tab");
    }
  });
});

// ---------------------------------------------------------------------------
// 7. CapabilitiesPage tabs — 2 tabs, already shipped with `min-h-[44px]`.
// ---------------------------------------------------------------------------

describe("Tap targets — CapabilitiesPage tabs", () => {
  it("CapabilitiesPage tab buttons are >= 44px (rectangular)", async () => {
    const { default: CapabilitiesPage } = await import(
      "@/pages/CapabilitiesPage"
    );
    render(<CapabilitiesPage />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    for (const tab of tabs) {
      assertRectTapTarget(tab, "CapabilitiesPage tab");
    }
  });
});

// ---------------------------------------------------------------------------
// 8. CommandPalette result rows — keyboard-driven, lenient `py-2` allowed.
// ---------------------------------------------------------------------------

describe("Tap targets — CommandPalette rows", () => {
  it("CommandPalette option rows have >= py-2 or >= 44px height", async () => {
    const { default: CommandPalette } = await import(
      "@/components/CommandPalette"
    );
    render(
      <CommandPalette open onClose={() => {}} onDispatch={() => {}} />,
    );
    // Before the lazy index resolves the palette falls back to the sync
    // SLASH_COMMANDS list — that's enough rows for the audit.
    const options = screen.getAllByRole("option");
    expect(options.length).toBeGreaterThan(0);
    for (const row of options) {
      assertOptionRowTapTarget(row, "CommandPalette option");
    }
  });
});
