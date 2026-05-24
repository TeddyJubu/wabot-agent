import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";

// ---------------------------------------------------------------------------
// Mock @/searchIndex so the lazy index fetch in CommandPalette never resolves
// for the legacy assertions below — that keeps them looking at the sync
// command-only fallback (the source of truth for the original tests). The
// new grouped-results describe block at the bottom of this file overrides
// `getSearchIndex` with a known fixture per-test using `mockResolvedValueOnce`.
// ---------------------------------------------------------------------------

// The default implementation is a never-resolving promise so the existing
// command-only tests keep seeing the synchronous SLASH_COMMANDS fallback.
// Typed as `Promise<unknown[]>` so a later `mockResolvedValue(FIXTURE)` —
// where FIXTURE is `SearchResult[]` — doesn't fight the inferred `never`
// return type. The mock factory runs hoisted before any imports, so the
// concrete `SearchResult` type isn't in scope yet.
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

import CommandPalette from "@/components/CommandPalette";
import { SLASH_COMMANDS } from "@/hooks/useSlashCommands";
import type { SearchResult } from "@/searchIndex";
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
// CommandPalette in isolation — no App, no store needed.
// ---------------------------------------------------------------------------

describe("CommandPalette — visibility", () => {
  it("renders nothing when open={false}", () => {
    const { container, baseElement } = render(
      <CommandPalette open={false} onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
    expect(
      baseElement.querySelector('[role="dialog"]'),
    ).toBeNull();
  });

  it("renders a labelled modal dialog when open", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const dialog = screen.getByRole("dialog", { name: "Command palette" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("focuses the input on open", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const input = screen.getByRole("combobox");
    expect(document.activeElement).toBe(input);
  });
});

describe("CommandPalette — closing", () => {
  it("calls onClose when ESC is pressed", () => {
    const onClose = vi.fn();
    render(
      <CommandPalette open onClose={onClose} onDispatch={vi.fn()} />,
    );
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(
      <CommandPalette open onClose={onClose} onDispatch={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("cmdp-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("restores focus to the previously focused element on close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Trigger";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { rerender } = render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    // Palette steals focus on mount.
    expect(document.activeElement).toBe(screen.getByRole("combobox"));

    rerender(
      <CommandPalette open={false} onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});

describe("CommandPalette — filtering", () => {
  it("lists every SLASH_COMMAND when query is empty", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    expect(screen.getAllByRole("option")).toHaveLength(SLASH_COMMANDS.length);
  });

  it("narrows by name match", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "qr" } });
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("/qr");
  });

  it("narrows by description match", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const input = screen.getByRole("combobox");
    // "kn" matches both name (/knowledge) and description ("knowledge editor").
    fireEvent.change(input, { target: { value: "kn" } });
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("/knowledge");
  });
});

describe("CommandPalette — keyboard navigation", () => {
  it("ArrowDown moves aria-activedescendant from item 0 to item 1", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("aria-activedescendant", "cmdp-item-0");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", "cmdp-item-1");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("ArrowUp clamps at the first item", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowUp" });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowUp" });
    expect(input).toHaveAttribute("aria-activedescendant", "cmdp-item-0");
  });

  it("Enter on the active item calls onDispatch with the sentinel and then onClose", () => {
    const onDispatch = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette open onClose={onClose} onDispatch={onDispatch} />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "qr" } });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Enter" });

    expect(onDispatch).toHaveBeenCalledTimes(1);
    expect(onDispatch).toHaveBeenCalledWith("__open_pair__");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("CommandPalette — combobox ARIA", () => {
  it("declares combobox role with the listbox controls", () => {
    render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("aria-controls", "cmdp-listbox");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-activedescendant");
  });
});

describe("CommandPalette — accessibility", () => {
  it("has no axe violations", async () => {
    const { baseElement } = render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    const results = await axe(baseElement);
    expect(results).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------
// App integration — palette mount, flag-gated bottom input removal, global
// keybindings. Mocks mirror app-shell-v2.test.tsx for the v2 shell so the
// Home placeholder + Insights (OverviewPanel) routes can mount cleanly when
// B3's Home view eventually wires real data.
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
  useStore.setState({
    readiness: PRISTINE_READINESS,
    slideOver: null,
    pairing: null,
  });
  useRouteStore.setState({ route: "home" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// Re-apply the never-resolving default for `getSearchIndex` after each test —
// `vi.restoreAllMocks()` above clears the implementation, which would otherwise
// leave the palette calling `.then` on `undefined` in the next test.
beforeEach(() => {
  getSearchIndexMock.mockImplementation(() => new Promise<never>(() => {}));
});

describe("App + CommandPalette wiring", () => {
  it("removes the bottom slash input under ?ui=v2", async () => {
    setSearch("ui=v2");
    render(<App />);

    // Wait for the rail to mount so we know the v2 shell is up.
    await screen.findByRole("navigation", { name: "Primary" });

    expect(
      screen.queryByPlaceholderText("Type / for commands"),
    ).toBeNull();
  });

  it("keeps the bottom slash input mounted with the flag off", async () => {
    setSearch("");
    render(<App />);
    expect(
      await screen.findByPlaceholderText("Type / for commands"),
    ).toBeInTheDocument();
  });

  it("opens the palette on Cmd-K", async () => {
    setSearch("ui=v2");
    render(<App />);
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.keyDown(window, { key: "k", metaKey: true });

    expect(
      await screen.findByRole("dialog", { name: "Command palette" }),
    ).toBeInTheDocument();
  });

  it("opens the palette on '/' when no input is focused", async () => {
    setSearch("ui=v2");
    render(<App />);
    await screen.findByRole("navigation", { name: "Primary" });

    // Move focus away from any input — to <body> — by blurring activeElement.
    (document.activeElement as HTMLElement | null)?.blur?.();

    fireEvent.keyDown(window, { key: "/" });

    expect(
      await screen.findByRole("dialog", { name: "Command palette" }),
    ).toBeInTheDocument();
  });

  it("ESC closes the palette once opened", async () => {
    setSearch("ui=v2");
    render(<App />);
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = await screen.findByRole("dialog", {
      name: "Command palette",
    });

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Command palette" }),
      ).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// Epic C5 — Cross-cutting search: grouped result rendering, ranking-driven
// ordering, keyboard navigation across group boundaries, and sentinel
// dispatch from non-command results.
// ---------------------------------------------------------------------------

const FIXTURE_RESULTS: SearchResult[] = [
  {
    kind: "command",
    id: "/qr",
    label: "/qr",
    description: "Open WhatsApp pairing QR",
    sentinel: "__open_pair__",
  },
  {
    kind: "knowledge",
    id: "knowledge:model-notes",
    label: "model-notes.md",
    description: "model routing notes for the weekly brief",
    sentinel: "__open_knowledge__",
  },
  {
    kind: "agent",
    id: "agent:router",
    label: "Router",
    description: "Default routing agent",
    sentinel: "__open_slide_over__:agents",
  },
  {
    kind: "tool",
    id: "tool:model_pick",
    label: "model_pick",
    description: "Pick a model for a purpose",
    sentinel: "__open_slide_over__:tools",
  },
  {
    kind: "settings",
    id: "settings:provider",
    label: "Provider",
    description: "Model provider (OpenAI, Codex, OpenRouter, Ollama)",
    sentinel: "__open_slide_over__:settings",
  },
];

describe("CommandPalette — grouped results from search index", () => {
  beforeEach(() => {
    getSearchIndexMock.mockReset();
    getSearchIndexMock.mockResolvedValue(FIXTURE_RESULTS);
  });

  it("renders one group per kind with accessible names", async () => {
    render(<CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />);

    // Wait for the index to resolve — first non-command group is a good marker.
    await screen.findByRole("group", { name: "Knowledge" });

    expect(screen.getByRole("group", { name: "Commands" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Knowledge" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Agents" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Tools" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Settings" })).toBeInTheDocument();
  });

  it("typing 'model' surfaces Settings + tool + knowledge entries, with the highest-ranked result first", async () => {
    render(<CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />);
    await screen.findByRole("group", { name: "Knowledge" });

    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "model" } });

    const options = screen.getAllByRole("option");
    const labels = options.map((o) => o.textContent ?? "");

    // The "model_pick" tool (label includes "model") and the
    // "model-notes.md" knowledge doc (label starts with "model") both match.
    // The Provider settings entry also matches via its description keywords.
    expect(labels.some((l) => l.includes("model-notes.md"))).toBe(true);
    expect(labels.some((l) => l.includes("model_pick"))).toBe(true);
    expect(labels.some((l) => l.includes("Provider"))).toBe(true);

    // "model-notes.md" starts with "model" (score 500) so it ranks above
    // "model_pick" which only contains it via includes (score 100). The
    // first visible option must therefore be the knowledge entry.
    expect(options[0]?.textContent ?? "").toContain("model-notes.md");
  });

  it("ArrowDown traverses across group boundaries", async () => {
    render(<CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />);
    await screen.findByRole("group", { name: "Knowledge" });

    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("aria-activedescendant", "cmdp-item-0");

    const dialog = screen.getByRole("dialog");
    fireEvent.keyDown(dialog, { key: "ArrowDown" });
    fireEvent.keyDown(dialog, { key: "ArrowDown" });

    // After two ArrowDowns, the active descendant is item 2 — which lives in
    // a different group than item 0 (the first command).
    expect(input).toHaveAttribute("aria-activedescendant", "cmdp-item-2");
    const options = screen.getAllByRole("option");
    expect(options[2]).toHaveAttribute("aria-selected", "true");
  });

  it("Enter on a knowledge result dispatches __open_knowledge__ and closes", async () => {
    const onDispatch = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette open onClose={onClose} onDispatch={onDispatch} />,
    );
    await screen.findByRole("group", { name: "Knowledge" });

    const input = screen.getByRole("combobox");
    // Narrow to the knowledge entry only, so it lands at activeIdx=0.
    fireEvent.change(input, { target: { value: "model-notes" } });

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Enter" });

    expect(onDispatch).toHaveBeenCalledTimes(1);
    expect(onDispatch).toHaveBeenCalledWith("__open_knowledge__");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("remains axe-clean with grouped results rendered", async () => {
    const { baseElement } = render(
      <CommandPalette open onClose={vi.fn()} onDispatch={vi.fn()} />,
    );
    await screen.findByRole("group", { name: "Knowledge" });

    const results = await axe(baseElement);
    expect(results).toHaveNoViolations();
  });
});
