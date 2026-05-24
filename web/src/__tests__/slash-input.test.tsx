import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { SettingsView } from "@/api/settings";
import { useStore, type Readiness } from "@/store";
import { useUiFlagStore } from "@/store/uiFlag";
import App from "@/App";

// ---------------------------------------------------------------------------
// Characterization — proves the legacy bottom slash <input> still dispatches
// the same three navigation sentinels that the new CommandPalette must keep
// covering (per UX-IMPLEMENTATION-PLAN.md line 132: "Test before delete").
//
// Mocks mirror the pattern in app-routing.test.tsx so <App /> renders without
// touching Clerk, the pairing stream, or real settings.
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

const PENDING_ROW = { label: "Checking…", variant: "pending" as const };
const PRISTINE_READINESS: Readiness = {
  overall: "pending",
  model: PENDING_ROW,
  wabot: PENDING_ROW,
  policy: PENDING_ROW,
  memory: PENDING_ROW,
};

const originalLocation = window.location;

function clearSearch() {
  window.history.replaceState({}, "", "/");
  useUiFlagStore.getState().resetUiFlagFromUrl();
}

beforeEach(() => {
  clearSearch();
  useStore.setState({
    readiness: PRISTINE_READINESS,
    slideOver: null,
    pairing: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  if (window.location !== originalLocation) {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
  }
});

async function typeIntoBottomInput(value: string) {
  const input = await screen.findByPlaceholderText("Type / for commands");
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("Bottom slash input — characterization (flag OFF)", () => {
  it("/qr opens /pair in a new tab", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<App />);

    // Wait until App has mounted the bottom input.
    await screen.findByPlaceholderText("Type / for commands");
    await typeIntoBottomInput("/qr");

    expect(openSpy).toHaveBeenCalledWith("/pair", "_blank", "noopener");
  });

  it("/runs opens the runs slide-over", async () => {
    render(<App />);
    await screen.findByPlaceholderText("Type / for commands");
    await typeIntoBottomInput("/runs");

    await waitFor(() => {
      expect(useStore.getState().slideOver).toBe("runs");
    });
  });

  it("/knowledge navigates to /knowledge", async () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { href: "" },
    });

    render(<App />);
    await screen.findByPlaceholderText("Type / for commands");
    await typeIntoBottomInput("/knowledge");

    expect(window.location.href).toBe("/knowledge");
  });
});
