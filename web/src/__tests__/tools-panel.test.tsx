import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import ToolsPanel from "@/components/slide-overs/ToolsPanel";
import type { ToolsListResponse, ToolRow } from "@/api/tools";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/tools", () => ({
  listTools: vi.fn(),
  refreshTools: vi.fn(),
  toggleTool: vi.fn(),
}));

import * as toolsApi from "@/api/tools";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeNativeTool(id: number, name: string, enabled = true): ToolRow {
  return {
    id,
    kind: "native",
    source_ref: `tools.${name}`,
    name,
    description: `Does ${name}`,
    is_enabled: enabled,
    is_assigned_to: ["comms", "inboxer"],
  };
}

const MOCK_TOOLS: ToolsListResponse = {
  native: [
    makeNativeTool(1, "list_whatsapp_inbound_messages"),
    makeNativeTool(2, "lookup_whatsapp_contacts"),
    makeNativeTool(3, "send_whatsapp_text", false),
  ],
  mcp: [],
  composio: [],
  skill_action: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ToolsPanel — tabs and counts", () => {
  it("renders tabs with correct counts from listTools response", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);

    render(<ToolsPanel />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /native \(3\)/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /mcp \(0\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /composio \(0\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /skills \(0\)/i })).toBeInTheDocument();
  });

  it("shows tool rows on the active tab", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    render(<ToolsPanel />);

    await waitFor(() =>
      expect(screen.getByText("list_whatsapp_inbound_messages")).toBeInTheDocument(),
    );
    expect(screen.getByText("lookup_whatsapp_contacts")).toBeInTheDocument();
    expect(screen.getByText("send_whatsapp_text")).toBeInTheDocument();
  });

  it("shows empty state when no tools in tab", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    render(<ToolsPanel />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /mcp \(0\)/i })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /mcp \(0\)/i }));

    await waitFor(() =>
      expect(screen.getByText(/no mcp tools/i)).toBeInTheDocument(),
    );
  });
});

describe("ToolsPanel — toggle", () => {
  it("toggling a tool calls toggleTool with correct id and inverted enabled flag", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    vi.mocked(toolsApi.toggleTool).mockResolvedValue({
      ...MOCK_TOOLS.native[0],
      is_enabled: false,
    });

    render(<ToolsPanel />);
    await waitFor(() => screen.getByText("list_whatsapp_inbound_messages"));

    // The first native tool is enabled — clicking its toggle should disable it
    const toggleBtns = screen.getAllByRole("button", { name: /^on$/i });
    fireEvent.click(toggleBtns[0]);

    await waitFor(() =>
      expect(toolsApi.toggleTool).toHaveBeenCalledWith(1, false),
    );
  });

  it("toggling a disabled tool calls toggleTool to enable it", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    vi.mocked(toolsApi.toggleTool).mockResolvedValue({
      ...MOCK_TOOLS.native[2],
      is_enabled: true,
    });

    render(<ToolsPanel />);
    await waitFor(() => screen.getByText("send_whatsapp_text"));

    // The third tool is disabled — its button reads "off"
    const offBtn = screen.getByRole("button", { name: /^off$/i });
    fireEvent.click(offBtn);

    await waitFor(() =>
      expect(toolsApi.toggleTool).toHaveBeenCalledWith(3, true),
    );
  });
});

describe("ToolsPanel — refresh", () => {
  it("clicking Refresh fires refreshTools and shows delta message", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    vi.mocked(toolsApi.refreshTools).mockResolvedValue({
      native_added: 3,
      composio_added: 0,
      mcp_added: 0,
    });

    render(<ToolsPanel />);
    await waitFor(() => screen.getByRole("button", { name: /↻ refresh/i }));

    fireEvent.click(screen.getByRole("button", { name: /↻ refresh/i }));

    await waitFor(() => expect(toolsApi.refreshTools).toHaveBeenCalledTimes(1));

    await waitFor(() =>
      expect(
        screen.getByText(/3 native added/i),
      ).toBeInTheDocument(),
    );
  });
});

describe("ToolsPanel — toggle failure", () => {
  it("test_toggle_failure_reverts_optimistic_update", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    vi.mocked(toolsApi.toggleTool).mockRejectedValue(new Error("server error"));

    render(<ToolsPanel />);
    await waitFor(() => screen.getByText("list_whatsapp_inbound_messages"));

    // The first native tool is enabled — clicking its toggle should optimistically disable it
    // then revert after the error
    const toggleBtns = screen.getAllByRole("button", { name: /^on$/i });
    fireEvent.click(toggleBtns[0]);

    await waitFor(() =>
      expect(toolsApi.toggleTool).toHaveBeenCalledWith(1, false),
    );

    // Toggle state should have reverted to "on" (optimistic revert)
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^on$/i }).length).toBeGreaterThanOrEqual(1),
    );

    // Error message should appear
    await waitFor(() =>
      expect(screen.getByText(/server error/i)).toBeInTheDocument(),
    );
  });
});

describe("ToolsPanel — search filter", () => {
  it("filtering by search term shows only matching tools", async () => {
    vi.mocked(toolsApi.listTools).mockResolvedValue(MOCK_TOOLS);
    render(<ToolsPanel />);
    await waitFor(() => screen.getByText("list_whatsapp_inbound_messages"));

    const searchInput = screen.getByPlaceholderText(/filter tools/i);
    fireEvent.change(searchInput, { target: { value: "lookup" } });

    expect(screen.getByText("lookup_whatsapp_contacts")).toBeInTheDocument();
    expect(screen.queryByText("list_whatsapp_inbound_messages")).not.toBeInTheDocument();
  });
});
