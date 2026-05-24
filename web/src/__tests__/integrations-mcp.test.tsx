import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { McpServersSection } from "@/components/slide-overs/integrations/McpServersSection";
import type { McpServerRow } from "@/api/mcp";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/mcp", () => ({
  listMcpServers: vi.fn(),
  createMcpServer: vi.fn(),
  updateMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  checkMcpServer: vi.fn(),
  searchMcpRegistry: vi.fn().mockResolvedValue([]),
  installMcpFromRegistry: vi.fn(),
}));

import * as mcpApi from "@/api/mcp";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SERVER_OK: McpServerRow = {
  id: 1,
  name: "brave-search",
  transport: "stdio",
  config_json: '{"command":"npx","args":["-y","brave-search-mcp"]}',
  is_enabled: true,
  health_status: "ok",
  health_message: null,
  last_checked_at: "2026-01-01T12:00:00",
};

const SERVER_ERROR: McpServerRow = {
  id: 2,
  name: "broken-mcp",
  transport: "http",
  config_json: '{"url":"http://localhost:9999"}',
  is_enabled: true,
  health_status: "error",
  health_message: "Connection refused",
  last_checked_at: "2026-01-01T11:00:00",
};

const SERVER_UNKNOWN: McpServerRow = {
  id: 3,
  name: "new-server",
  transport: "stdio",
  config_json: "{}",
  is_enabled: true,
  health_status: null,
  health_message: null,
  last_checked_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("McpServersSection — server rows", () => {
  it("renders MCP server rows with health dots and transport pills", () => {
    render(
      <McpServersSection
        servers={[SERVER_OK, SERVER_ERROR, SERVER_UNKNOWN]}
        onRefresh={() => undefined}
      />,
    );

    expect(screen.getByText("brave-search")).toBeInTheDocument();
    expect(screen.getByText("broken-mcp")).toBeInTheDocument();
    expect(screen.getByText("new-server")).toBeInTheDocument();

    // Transport pills
    const stdioPills = screen.getAllByText("stdio");
    expect(stdioPills.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("http")).toBeInTheDocument();

    // Health dots
    expect(screen.getByLabelText("Health: healthy")).toBeInTheDocument();
    expect(screen.getByLabelText("Health: error")).toBeInTheDocument();
    expect(screen.getByLabelText("Health: unknown")).toBeInTheDocument();
  });

  it("renders empty state when no servers and add form is closed", () => {
    render(<McpServersSection servers={[]} onRefresh={() => undefined} />);
    expect(screen.getByText(/No MCP servers configured yet/i)).toBeInTheDocument();
  });
});

describe("McpServersSection — Add server form", () => {
  it("clicking + Add server shows the form", () => {
    render(<McpServersSection servers={[]} onRefresh={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /\+ add server/i }));
    expect(screen.getByText(/add mcp server/i)).toBeInTheDocument();
  });

  it("Add server form validates JSON before POST — invalid JSON shows error", async () => {
    render(<McpServersSection servers={[]} onRefresh={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /\+ add server/i }));

    // Fill name
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "test-server" } });

    // Enter invalid JSON
    const configTextarea = screen.getByLabelText(/config json/i);
    fireEvent.change(configTextarea, { target: { value: "{ invalid json" } });

    // The submit button inside the form is of type="submit"; target it by role=button name "Add server"
    // but exclude the + Add server toggle button (which says "+ Add server") by using exact text
    const addButtons = screen.getAllByRole("button", { name: /add server/i });
    // The submit button is the one with type submit (not the "+ Add server" toggle)
    const submitBtn = addButtons.find(
      (btn) => (btn as HTMLButtonElement).type === "submit",
    );
    if (!submitBtn) throw new Error("Submit button not found");
    fireEvent.click(submitBtn);

    // The error paragraph should appear (not the textarea content itself)
    await waitFor(() => {
      const errorParagraph = screen.getByText(/invalid json/i, { selector: "p" });
      expect(errorParagraph).toBeInTheDocument();
    });
    expect(mcpApi.createMcpServer).not.toHaveBeenCalled();
  });

  it("Add server form submits with valid JSON", async () => {
    vi.mocked(mcpApi.createMcpServer).mockResolvedValue(SERVER_UNKNOWN);
    const onRefresh = vi.fn();

    render(<McpServersSection servers={[]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: /\+ add server/i }));

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "new-server" } });
    fireEvent.change(screen.getByLabelText(/config json/i), {
      target: { value: '{"command":"node","args":["index.js"]}' },
    });

    // Click the submit button inside the form (type="submit")
    const addButtons = screen.getAllByRole("button", { name: /add server/i });
    const submitBtn = addButtons.find(
      (btn) => (btn as HTMLButtonElement).type === "submit",
    );
    if (!submitBtn) throw new Error("Submit button not found");
    fireEvent.click(submitBtn);

    await waitFor(() =>
      expect(mcpApi.createMcpServer).toHaveBeenCalledWith(
        expect.objectContaining({ name: "new-server" }),
      ),
    );
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});

describe("McpServersSection — Check button", () => {
  it("Check button calls checkMcpServer and updates the row health", async () => {
    vi.mocked(mcpApi.checkMcpServer).mockResolvedValue({
      health_status: "ok",
      health_message: null,
      tool_count: 5,
    });

    render(<McpServersSection servers={[SERVER_ERROR]} onRefresh={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: /check server broken-mcp/i }));

    await waitFor(() =>
      expect(mcpApi.checkMcpServer).toHaveBeenCalledWith(SERVER_ERROR.id),
    );

    // Health dot should now be green (ok)
    await waitFor(() =>
      expect(screen.getByLabelText("Health: healthy")).toBeInTheDocument(),
    );
  });
});

describe("McpServersSection — Delete", () => {
  it("Delete opens the ConfirmDialog and cascades through API on confirm", async () => {
    vi.mocked(mcpApi.deleteMcpServer).mockResolvedValue(undefined);
    const onRefresh = vi.fn();

    render(<McpServersSection servers={[SERVER_OK]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: /delete server brave-search/i }));

    const dialog = await screen.findByRole("dialog", {
      name: /delete mcp server/i,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(mcpApi.deleteMcpServer).toHaveBeenCalledWith(SERVER_OK.id));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("Delete does NOT call API when the dialog is cancelled", async () => {
    const onRefresh = vi.fn();

    render(<McpServersSection servers={[SERVER_OK]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: /delete server brave-search/i }));

    const dialog = await screen.findByRole("dialog", {
      name: /delete mcp server/i,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^cancel$/i }));

    expect(mcpApi.deleteMcpServer).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// BLOCKER 2 — config_json must be sent as an object, not a string
// ---------------------------------------------------------------------------

describe("AddMcpServerForm — config_json object dispatch", () => {
  it("test_add_server_parses_json_before_submit — submits config_json as an object", async () => {
    vi.mocked(mcpApi.createMcpServer).mockResolvedValue(SERVER_UNKNOWN);
    const onRefresh = vi.fn();

    render(<McpServersSection servers={[]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: /\+ add server/i }));

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "new-server" } });
    fireEvent.change(screen.getByLabelText(/config json/i), {
      target: { value: '{"command":"npx","args":["x"]}' },
    });

    const addButtons = screen.getAllByRole("button", { name: /add server/i });
    const submitBtn = addButtons.find((btn) => (btn as HTMLButtonElement).type === "submit");
    if (!submitBtn) throw new Error("Submit button not found");
    fireEvent.click(submitBtn);

    await waitFor(() =>
      expect(mcpApi.createMcpServer).toHaveBeenCalledWith(
        expect.objectContaining({
          config_json: { command: "npx", args: ["x"] },
        }),
      ),
    );
  });

  it("test_add_server_rejects_invalid_json — shows error and does not call createMcpServer", async () => {
    const onRefresh = vi.fn();

    render(<McpServersSection servers={[]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: /\+ add server/i }));

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "bad-server" } });
    fireEvent.change(screen.getByLabelText(/config json/i), {
      target: { value: "not valid json" },
    });

    const addButtons = screen.getAllByRole("button", { name: /add server/i });
    const submitBtn = addButtons.find((btn) => (btn as HTMLButtonElement).type === "submit");
    if (!submitBtn) throw new Error("Submit button not found");
    fireEvent.click(submitBtn);

    await waitFor(() => {
      const errorParagraph = screen.getByText(/invalid json/i, { selector: "p" });
      expect(errorParagraph).toBeInTheDocument();
    });
    expect(mcpApi.createMcpServer).not.toHaveBeenCalled();
  });
});
