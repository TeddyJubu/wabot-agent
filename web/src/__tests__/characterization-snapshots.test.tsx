import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import type { SettingsView } from "@/api/settings";
import { useStore, type Readiness } from "@/store";
import TopBar from "@/components/TopBar";
import StatusPopover from "@/components/StatusPopover";
import App from "@/App";

// ---------------------------------------------------------------------------
// Mocks shared by multiple tests
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

// ---------------------------------------------------------------------------
// Pristine readiness — matches the initial value in `src/store/index.ts`. We
// reset before every test so a previous test's mutation can't drift these
// snapshots.
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
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Characterization snapshots — pre-flag UI", () => {
  it("<TopBar /> matches snapshot", () => {
    const { container } = render(<TopBar />);
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("<App /> empty hero <main> matches snapshot", async () => {
    const { container } = render(<App />);

    const main = container.querySelector("main");
    expect(main).not.toBeNull();

    // Wait for the empty-hero copy to be in the DOM so the snapshot is stable.
    await waitFor(() => {
      expect(main!.textContent ?? "").toMatch(/Use WhatsApp to chat with the bot/);
    });

    expect(main!.innerHTML).toMatchSnapshot();
  });

  it("<StatusPopover /> matches snapshot", () => {
    const { container } = render(<StatusPopover onClose={() => {}} />);
    expect(container.innerHTML).toMatchSnapshot();
  });
});
