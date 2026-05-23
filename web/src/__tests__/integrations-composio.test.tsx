import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ComposioSection } from "@/components/slide-overs/integrations/ComposioSection";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/composio", () => ({
  getComposioStatus: vi.fn(),
  setComposioApiKey: vi.fn(),
  listComposioApps: vi.fn(),
  listComposioConnections: vi.fn(),
  createComposioConnection: vi.fn(),
  refreshComposioConnection: vi.fn(),
  deleteComposioConnection: vi.fn(),
}));

import * as composioApi from "@/api/composio";
import type {
  ComposioStatus,
  ComposioApp,
  ComposioConnection,
  ComposioConnectionCreate,
} from "@/api/composio";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const STATUS_DISABLED: ComposioStatus = {
  enabled: false,
  api_key_present: false,
  user_id: null,
  last_error: null,
};

const STATUS_ENABLED: ComposioStatus = {
  enabled: true,
  api_key_present: true,
  user_id: "user_abc123",
  last_error: null,
};

const APP_GMAIL: ComposioApp = {
  slug: "gmail",
  name: "Gmail",
  description: "Google email service",
  logo_url: null,
  categories: ["email", "google"],
  auth_schemes: ["oauth2"],
};

// APP_SLACK reserved for future tests
const _APP_SLACK: ComposioApp = {
  slug: "slack",
  name: "Slack",
  description: "Team messaging",
  logo_url: null,
  categories: ["messaging"],
  auth_schemes: ["oauth2"],
};
void _APP_SLACK;

const CONN_GMAIL_CONNECTED: ComposioConnection = {
  id: 1,
  app_slug: "gmail",
  display_name: "Gmail (john@example.com)",
  status: "connected",
  user_id: "user_abc123",
  last_checked_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  metadata: null,
};

const CONN_SLACK_PENDING: ComposioConnection = {
  id: 2,
  app_slug: "slack",
  display_name: "Slack (workspace)",
  status: "pending",
  user_id: "user_abc123",
  last_checked_at: null,
  metadata: null,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockDisabledState() {
  vi.mocked(composioApi.getComposioStatus).mockResolvedValue(STATUS_DISABLED);
  vi.mocked(composioApi.listComposioApps).mockResolvedValue([]);
  vi.mocked(composioApi.listComposioConnections).mockResolvedValue([]);
}

function mockEnabledState(
  connections: ComposioConnection[] = [],
  apps: ComposioApp[] = [],
) {
  vi.mocked(composioApi.getComposioStatus).mockResolvedValue(STATUS_ENABLED);
  vi.mocked(composioApi.listComposioApps).mockResolvedValue(apps);
  vi.mocked(composioApi.listComposioConnections).mockResolvedValue(connections);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ComposioSection — disabled state (no API key)", () => {
  it("renders 'Composio is not configured' and shows API key form when disabled", async () => {
    mockDisabledState();
    render(<ComposioSection />);

    await waitFor(() =>
      expect(screen.getByText(/Composio is not configured/i)).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/Composio API key/i)).toBeInTheDocument();
  });

  it("Save API key button is disabled when key is too short (7 chars)", async () => {
    mockDisabledState();
    render(<ComposioSection />);

    await waitFor(() => screen.getByLabelText(/Composio API key/i));

    fireEvent.change(screen.getByLabelText(/Composio API key/i), {
      target: { value: "1234567" }, // 7 chars — below 8 minimum
    });

    const saveBtn = screen.getByRole("button", { name: /save api key/i });
    expect(saveBtn).toBeDisabled();
  });

  it("entering valid key and clicking Save calls setComposioApiKey", async () => {
    mockDisabledState();
    vi.mocked(composioApi.setComposioApiKey).mockResolvedValue(STATUS_ENABLED);
    vi.mocked(composioApi.listComposioApps).mockResolvedValue([]);
    vi.mocked(composioApi.listComposioConnections).mockResolvedValue([]);

    render(<ComposioSection />);

    await waitFor(() => screen.getByLabelText(/Composio API key/i));

    fireEvent.change(screen.getByLabelText(/Composio API key/i), {
      target: { value: "valid-api-key-here" },
    });

    const saveBtn = screen.getByRole("button", { name: /save api key/i });
    expect(saveBtn).not.toBeDisabled();

    fireEvent.click(saveBtn);

    await waitFor(() =>
      expect(composioApi.setComposioApiKey).toHaveBeenCalledWith("valid-api-key-here"),
    );
  });
});

describe("ComposioSection — enabled state with connections", () => {
  it("renders connected apps list with 2 rows when enabled", async () => {
    mockEnabledState([CONN_GMAIL_CONNECTED, CONN_SLACK_PENDING]);
    render(<ComposioSection />);

    await waitFor(() =>
      expect(screen.getByText("Gmail (john@example.com)")).toBeInTheDocument(),
    );
    expect(screen.getByText("Slack (workspace)")).toBeInTheDocument();

    // Status pills
    expect(screen.getByText("connected")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("Refresh button on a row calls refreshComposioConnection", async () => {
    mockEnabledState([CONN_GMAIL_CONNECTED]);
    const refreshed: ComposioConnection = { ...CONN_GMAIL_CONNECTED, status: "connected" };
    vi.mocked(composioApi.refreshComposioConnection).mockResolvedValue(refreshed);

    render(<ComposioSection />);

    await waitFor(() => screen.getByLabelText(/Refresh connection Gmail/i));

    fireEvent.click(screen.getByLabelText(/Refresh connection Gmail/i));

    await waitFor(() =>
      expect(composioApi.refreshComposioConnection).toHaveBeenCalledWith(CONN_GMAIL_CONNECTED.id),
    );
  });

  it("Disconnect prompts confirm and calls deleteComposioConnection", async () => {
    mockEnabledState([CONN_GMAIL_CONNECTED]);
    vi.mocked(composioApi.deleteComposioConnection).mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ComposioSection />);

    await waitFor(() => screen.getByLabelText(/Disconnect Gmail/i));

    fireEvent.click(screen.getByLabelText(/Disconnect Gmail/i));

    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() =>
      expect(composioApi.deleteComposioConnection).toHaveBeenCalledWith(CONN_GMAIL_CONNECTED.id),
    );

    confirmSpy.mockRestore();
  });

  it("Disconnect does NOT call API when confirm is cancelled", async () => {
    mockEnabledState([CONN_GMAIL_CONNECTED]);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<ComposioSection />);

    await waitFor(() => screen.getByLabelText(/Disconnect Gmail/i));
    fireEvent.click(screen.getByLabelText(/Disconnect Gmail/i));

    expect(composioApi.deleteComposioConnection).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });
});

describe("ComposioSection — available apps Connect button", () => {
  it("Connect button calls createComposioConnection and opens window.open with redirect_url", async () => {
    // Set up: enabled state, no existing connections, one available app
    vi.mocked(composioApi.getComposioStatus).mockResolvedValue(STATUS_ENABLED);
    vi.mocked(composioApi.listComposioApps).mockResolvedValue([APP_GMAIL]);
    // Initial load returns no connections; poll after connect returns connected
    vi.mocked(composioApi.listComposioConnections)
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValue([{ ...CONN_GMAIL_CONNECTED, status: "connected" }]); // poll

    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    const created: ComposioConnectionCreate = {
      ...CONN_GMAIL_CONNECTED,
      status: "pending",
      redirect_url: "https://auth.composio.dev/oauth/gmail",
    };
    vi.mocked(composioApi.createComposioConnection).mockResolvedValue(created);

    render(<ComposioSection />);

    // Wait for component to load, then open the Available apps collapsible
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Available apps/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Available apps/i }));

    // The Connect button for Gmail should appear
    await waitFor(() =>
      expect(screen.getByLabelText("Connect Gmail")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByLabelText("Connect Gmail"));

    await waitFor(() =>
      expect(composioApi.createComposioConnection).toHaveBeenCalledWith({ app_slug: "gmail" }),
    );

    expect(openSpy).toHaveBeenCalledWith(
      "https://auth.composio.dev/oauth/gmail",
      "_blank",
      "noopener,noreferrer",
    );

    openSpy.mockRestore();
  });

  it("test_polling_stops_when_component_unmounts: no listComposioConnections calls after unmount", async () => {
    vi.mocked(composioApi.getComposioStatus).mockResolvedValue(STATUS_ENABLED);
    vi.mocked(composioApi.listComposioApps).mockResolvedValue([APP_GMAIL]);
    // listComposioConnections: first call is initial load (empty), subsequent calls during poll stay pending
    vi.mocked(composioApi.listComposioConnections).mockResolvedValue([
      { ...CONN_GMAIL_CONNECTED, status: "pending" },
    ]);

    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    const created: ComposioConnectionCreate = {
      ...CONN_GMAIL_CONNECTED,
      status: "pending",
      redirect_url: "https://auth.composio.dev/oauth/gmail",
    };
    vi.mocked(composioApi.createComposioConnection).mockResolvedValue(created);

    // Render with real timers so initial load (async) completes naturally
    const { unmount } = render(<ComposioSection />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Available apps/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Available apps/i }));

    await waitFor(() =>
      expect(screen.getByLabelText("Connect Gmail")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByLabelText("Connect Gmail"));

    await waitFor(() =>
      expect(composioApi.createComposioConnection).toHaveBeenCalled(),
    );

    // Give the useEffect a tick to register pendingSlug and start the first poll sleep
    await new Promise<void>((r) => setTimeout(r, 10));

    // Record call count after connect (before unmount)
    const callsBefore = vi.mocked(composioApi.listComposioConnections).mock.calls.length;

    // Switch to fake timers NOW so we can fast-forward without real waits
    vi.useFakeTimers();

    // Unmount — this sets cancelled=true in the useEffect cleanup
    unmount();

    // Advance 30 seconds worth of poll intervals — loop must not fire
    await vi.advanceTimersByTimeAsync(30_000);

    vi.useRealTimers();

    // No additional calls should have happened after unmount
    const callsAfter = vi.mocked(composioApi.listComposioConnections).mock.calls.length;
    expect(callsAfter).toBe(callsBefore);

    openSpy.mockRestore();
  });

  it("polling: after Connect, listComposioConnections is called again via poll loop", async () => {
    // Set up: enabled state, one available app, no existing connections
    vi.mocked(composioApi.getComposioStatus).mockResolvedValue(STATUS_ENABLED);
    vi.mocked(composioApi.listComposioApps).mockResolvedValue([APP_GMAIL]);
    vi.mocked(composioApi.listComposioConnections)
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValueOnce([{ ...CONN_GMAIL_CONNECTED, status: "pending" }]) // first poll
      .mockResolvedValue([{ ...CONN_GMAIL_CONNECTED, status: "connected" }]); // subsequent polls

    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    const created: ComposioConnectionCreate = {
      ...CONN_GMAIL_CONNECTED,
      status: "pending",
      redirect_url: "https://auth.composio.dev/oauth/gmail",
    };
    vi.mocked(composioApi.createComposioConnection).mockResolvedValue(created);

    render(<ComposioSection />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Available apps/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Available apps/i }));

    await waitFor(() =>
      expect(screen.getByLabelText("Connect Gmail")).toBeInTheDocument(),
    );

    // Use fake timers right before clicking Connect so the poll setTimeout fires immediately
    vi.useFakeTimers({ shouldAdvanceTime: true, advanceTimeDelta: 0 });

    fireEvent.click(screen.getByLabelText("Connect Gmail"));

    await waitFor(() =>
      expect(composioApi.createComposioConnection).toHaveBeenCalled(),
    );

    // Advance time past one POLL_INTERVAL_MS (3000ms) to trigger the first poll
    await vi.advanceTimersByTimeAsync(3500);

    vi.useRealTimers();

    // listComposioConnections should have been called at least twice:
    // once on initial load + at least once during the poll loop
    await waitFor(
      () => {
        expect(vi.mocked(composioApi.listComposioConnections).mock.calls.length).toBeGreaterThanOrEqual(2);
      },
      { timeout: 3000 },
    );

    openSpy.mockRestore();
  });
});
