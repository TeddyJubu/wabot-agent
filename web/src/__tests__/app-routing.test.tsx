import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { SettingsView } from "@/api/settings";
import { useStore, type Readiness } from "@/store";
import App from "@/App";

// ---------------------------------------------------------------------------
// Mocks — mirror the pattern in characterization-snapshots.test.tsx so App can
// render without hitting Clerk, the pairing stream, or real settings.
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

beforeEach(() => {
  useStore.setState({
    readiness: PRISTINE_READINESS,
    slideOver: null,
    pairing: null,
  });
});

// ---------------------------------------------------------------------------
// Tests — proving the dashboard no longer hosts the pairing slide-over.
// /pair is the canonical pairing surface; the topbar icon and /qr slash command
// both route there in a new tab.
// ---------------------------------------------------------------------------

describe("App routing — pairing slide-over removed", () => {
  it("does not render a 'WhatsApp pairing' slide-over dialog", async () => {
    render(<App />);

    // Sanity — wait for the hero copy so we know App actually mounted.
    await waitFor(() => {
      expect(
        screen.getByText(/Use WhatsApp to chat with the bot/i),
      ).toBeInTheDocument();
    });

    expect(
      screen.queryByRole("dialog", { name: /whatsapp pairing/i }),
    ).toBeNull();
  });

  it("renders the hero copy directing operators to WhatsApp", async () => {
    render(<App />);
    await waitFor(() => {
      expect(
        screen.getByText(/Use WhatsApp to chat with the bot/i),
      ).toBeInTheDocument();
    });
  });
});
