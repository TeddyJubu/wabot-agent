import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import type { SettingsView } from "@/api/settings";
import { fetchSettings, patchSettings } from "@/api/settings";
import SettingsPage from "@/pages/SettingsPage";

// ---------------------------------------------------------------------------
// Mocks — same STABLE_SETTINGS fixture as app-shell-v2.test.tsx so the page
// can mount with a deterministic LLM provider / policy / wabot configuration.
// SettingsPage's only network surface is `@/api/settings` (fetch + patch);
// nothing else needs stubbing.
// ---------------------------------------------------------------------------

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

// The Codex section spins up a device-login poller via useCodexLogin. We never
// switch to Codex in any of these tests, but the hook still runs on mount —
// stub it so we don't leak timers / pending promises into the suite.
vi.mock("@/hooks/useCodexLogin", () => ({
  useCodexLogin: () => ({
    codexLogin: null,
    busy: false,
    startLogin: vi.fn(),
    cancelLogin: vi.fn(),
    disconnect: vi.fn(),
  }),
}));

const TAB_LABELS = ["Provider", "Routing", "Wabot", "Policy", "Experimental"] as const;

async function mountReady() {
  const utils = render(<SettingsPage />);
  // The page renders a loading paragraph until fetchSettings resolves, then
  // swaps to the tablist. Wait for the tablist to appear before asserting.
  await screen.findByRole("tablist", { name: "Settings sections" });
  return utils;
}

beforeEach(() => {
  vi.mocked(fetchSettings).mockResolvedValue(STABLE_SETTINGS);
  vi.mocked(patchSettings).mockResolvedValue();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tablist a11y
// ---------------------------------------------------------------------------

describe("SettingsPage — tablist a11y", () => {
  it("renders 5 tabs with correct roles, aria-selected, and a labelled panel", async () => {
    await mountReady();

    const tablist = screen.getByRole("tablist", { name: "Settings sections" });
    expect(tablist).toBeInTheDocument();

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(TAB_LABELS.length);

    // Provider is the default active tab.
    for (const label of TAB_LABELS) {
      const tab = screen.getByRole("tab", { name: label });
      expect(tab).toHaveAttribute(
        "aria-selected",
        label === "Provider" ? "true" : "false",
      );
      expect(tab).toHaveAttribute(
        "aria-controls",
        `settings-panel-${label.toLowerCase()}`,
      );
      expect(tab).toHaveAttribute("tabindex", label === "Provider" ? "0" : "-1");
    }

    // The visible panel is labelled by the active tab.
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "settings-panel-provider");
    expect(panel).toHaveAttribute("aria-labelledby", "settings-tab-provider");
  });
});

// ---------------------------------------------------------------------------
// Arrow-key roving tab-index
// ---------------------------------------------------------------------------

describe("SettingsPage — arrow-key roving", () => {
  it("ArrowRight from the active tab moves activation + focus to the next tab", async () => {
    await mountReady();
    const provider = screen.getByRole("tab", { name: "Provider" });
    provider.focus();
    expect(document.activeElement).toBe(provider);

    fireEvent.keyDown(provider, { key: "ArrowRight" });

    const routing = screen.getByRole("tab", { name: "Routing" });
    expect(routing).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(routing);
  });

  it("ArrowLeft from the first tab wraps to the last", async () => {
    await mountReady();
    const provider = screen.getByRole("tab", { name: "Provider" });
    provider.focus();

    fireEvent.keyDown(provider, { key: "ArrowLeft" });

    const experimental = screen.getByRole("tab", { name: "Experimental" });
    expect(experimental).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(experimental);
  });
});

// ---------------------------------------------------------------------------
// Tap-target floor
// ---------------------------------------------------------------------------

describe("SettingsPage — tap targets", () => {
  it("every tab button reserves a 44px min height", async () => {
    await mountReady();
    for (const label of TAB_LABELS) {
      const tab = screen.getByRole("tab", { name: label });
      expect(tab.className).toMatch(/min-h-\[44px\]/);
    }
  });
});

// ---------------------------------------------------------------------------
// Dirty-confirm flow
// ---------------------------------------------------------------------------

describe("SettingsPage — dirty-state tab switching", () => {
  it("opens a discard dialog when switching tabs with unsaved edits", async () => {
    await mountReady();

    // Provider tab is active and exposes the radio fieldset. Click a different
    // provider radio to mark the form dirty.
    fireEvent.click(screen.getByRole("radio", { name: "ChatGPT / Codex" }));

    // Click the Wabot tab — the page should intercept and prompt to discard.
    fireEvent.click(screen.getByRole("tab", { name: "Wabot" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    expect(dialog).toBeInTheDocument();
    // Provider stays active until the user confirms.
    expect(screen.getByRole("tab", { name: "Provider" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("confirming the discard activates the pending tab and clears the dialog", async () => {
    await mountReady();
    fireEvent.click(screen.getByRole("radio", { name: "ChatGPT / Codex" }));
    fireEvent.click(screen.getByRole("tab", { name: "Wabot" }));

    fireEvent.click(
      await screen.findByRole("button", { name: "Discard and switch" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Discard unsaved changes?" }),
      ).toBeNull();
    });
    expect(screen.getByRole("tab", { name: "Wabot" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("cancelling the discard keeps the user on the original tab", async () => {
    await mountReady();
    fireEvent.click(screen.getByRole("radio", { name: "ChatGPT / Codex" }));
    fireEvent.click(screen.getByRole("tab", { name: "Wabot" }));

    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel" }),
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Discard unsaved changes?" }),
      ).toBeNull();
    });
    expect(screen.getByRole("tab", { name: "Provider" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("does NOT prompt when the form is clean", async () => {
    await mountReady();
    fireEvent.click(screen.getByRole("tab", { name: "Wabot" }));

    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" }),
    ).toBeNull();
    expect(screen.getByRole("tab", { name: "Wabot" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

// ---------------------------------------------------------------------------
// End-to-end save
// ---------------------------------------------------------------------------

describe("SettingsPage — save flow", () => {
  it("saves the dirty provider via patchSettings and resets the dirty flag", async () => {
    await mountReady();

    fireEvent.click(screen.getByRole("radio", { name: "ChatGPT / Codex" }));

    // Submit through the sticky footer button.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    });

    await waitFor(() => {
      expect(patchSettings).toHaveBeenCalledTimes(1);
    });
    expect(patchSettings).toHaveBeenCalledWith({ model_provider: "codex" });

    // Status text confirms the save resolved.
    await screen.findByText("Saved.");

    // After save, the form is clean again — clicking another tab should switch
    // without prompting.
    fireEvent.click(screen.getByRole("tab", { name: "Wabot" }));
    expect(
      screen.queryByRole("dialog", { name: "Discard unsaved changes?" }),
    ).toBeNull();
    expect(screen.getByRole("tab", { name: "Wabot" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

// ---------------------------------------------------------------------------
// Accessibility — jest-axe sweep on the fully-mounted page.
// ---------------------------------------------------------------------------

describe("SettingsPage — accessibility", () => {
  it("has no axe-detectable violations", async () => {
    const { container } = await mountReady();
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
