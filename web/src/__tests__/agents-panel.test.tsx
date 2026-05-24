import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import AgentsPanel from "@/components/slide-overs/AgentsPanel";
import type { AgentSummary, AgentDetail } from "@/api/agents";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/agents", () => ({
  listAgents: vi.fn(),
  getAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  createAgent: vi.fn(),
  setAgentTools: vi.fn(),
  setAgentSkills: vi.fn(),
  testAgent: vi.fn(),
}));

vi.mock("@/api/tools", () => ({
  listTools: vi.fn().mockResolvedValue({ native: [], mcp: [], composio: [], skill_action: [] }),
  refreshTools: vi.fn(),
  toggleTool: vi.fn(),
}));

import * as agentsApi from "@/api/agents";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BUILTIN_SUMMARY: AgentSummary = {
  id: 1,
  slug: "orchestrator",
  display_name: "Orchestrator",
  description: "Root orchestrator agent",
  is_builtin: true,
  is_enabled: true,
  parent_slug: null,
  handoff_filter: null,
  tool_count: 5,
  skill_count: 0,
  updated_at: "2026-01-01T00:00:00",
};

const SCRAPER_SUMMARY: AgentSummary = {
  id: 2,
  slug: "scraper",
  display_name: "Scraper",
  description: "Web scraper",
  is_builtin: true,
  is_enabled: true,
  parent_slug: "orchestrator",
  handoff_filter: "remove_all_tools",
  tool_count: 12,
  skill_count: 1,
  updated_at: "2026-01-01T00:00:00",
};

const SCRAPER_DETAIL: AgentDetail = {
  ...SCRAPER_SUMMARY,
  instructions: "You are the scraper agent.",
  tool_ids: [10, 11, 12],
  skill_ids: [1],
};

const CUSTOM_SUMMARY: AgentSummary = {
  id: 10,
  slug: "my_researcher",
  display_name: "My Researcher",
  description: null,
  is_builtin: false,
  is_enabled: true,
  parent_slug: "orchestrator",
  handoff_filter: null,
  tool_count: 3,
  skill_count: 0,
  updated_at: "2026-01-01T00:00:00",
};

const CUSTOM_DETAIL: AgentDetail = {
  ...CUSTOM_SUMMARY,
  instructions: "You are my custom researcher.",
  tool_ids: [1, 2, 3],
  skill_ids: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AgentsPanel — list view", () => {
  it("renders builtin and custom agents from listAgents", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([
      BUILTIN_SUMMARY,
      SCRAPER_SUMMARY,
      CUSTOM_SUMMARY,
    ]);

    render(<AgentsPanel />);

    await waitFor(() => expect(screen.getByText("orchestrator")).toBeInTheDocument());

    // Builtins section
    expect(screen.getByText(/builtins \(2\)/i)).toBeInTheDocument();
    expect(screen.getByText("orchestrator")).toBeInTheDocument();
    expect(screen.getByText("scraper")).toBeInTheDocument();

    // Custom section
    expect(screen.getByText(/custom \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText("my_researcher")).toBeInTheDocument();
  });

  it("shows the + New button", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([BUILTIN_SUMMARY]);
    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("orchestrator"));
    expect(screen.getByRole("button", { name: "+ New" })).toBeInTheDocument();
  });

  it("shows error state when listAgents rejects", async () => {
    vi.mocked(agentsApi.listAgents).mockRejectedValue(new Error("network error"));
    render(<AgentsPanel />);
    await waitFor(() => screen.getByText(/network error/i));
  });
});

describe("AgentsPanel — editor view", () => {
  it("clicking an agent opens the editor with prefilled fields", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));

    fireEvent.click(screen.getByText("scraper"));

    await waitFor(() =>
      expect(screen.getByDisplayValue("Scraper")).toBeInTheDocument(),
    );

    // Instructions textarea should be prefilled
    expect(screen.getByDisplayValue("You are the scraper agent.")).toBeInTheDocument();

    // Back button appears
    expect(screen.getByRole("button", { name: /← back/i })).toBeInTheDocument();
  });

  it("Save calls updateAgent with the current form values", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);
    vi.mocked(agentsApi.updateAgent).mockResolvedValue({
      ...SCRAPER_DETAIL,
      display_name: "Scraper v2",
    });

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByDisplayValue("Scraper"));

    // Edit display name
    const nameInput = screen.getByDisplayValue("Scraper");
    fireEvent.change(nameInput, { target: { value: "Scraper v2" } });

    // Click Save
    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    fireEvent.click(saveBtn);

    await waitFor(() =>
      expect(agentsApi.updateAgent).toHaveBeenCalledWith(
        "scraper",
        expect.objectContaining({ display_name: "Scraper v2" }),
      ),
    );
  });

  it("Delete button is disabled for builtin agents", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByRole("button", { name: /delete/i }));

    const deleteBtn = screen.getByRole("button", { name: /delete/i });
    expect(deleteBtn).toBeDisabled();
  });

  it("Delete button is enabled for custom agents", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([CUSTOM_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(CUSTOM_DETAIL);

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("my_researcher"));
    fireEvent.click(screen.getByText("my_researcher"));
    await waitFor(() => screen.getByRole("button", { name: /delete/i }));

    const deleteBtn = screen.getByRole("button", { name: /delete/i });
    expect(deleteBtn).not.toBeDisabled();
  });

  it("Back button returns to list view", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByRole("button", { name: /← back/i }));

    fireEvent.click(screen.getByRole("button", { name: /← back/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "+ New" })).toBeInTheDocument(),
    );
  });
});

describe("AgentsPanel — create form", () => {
  it("clicking + New shows the create form", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([]);
    render(<AgentsPanel />);
    await waitFor(() => screen.getByRole("button", { name: "+ New" }));

    fireEvent.click(screen.getByRole("button", { name: "+ New" }));
    expect(screen.getByText("New agent")).toBeInTheDocument();
  });

  it("cancel returns to list", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([]);
    render(<AgentsPanel />);
    await waitFor(() => screen.getByRole("button", { name: "+ New" }));

    fireEvent.click(screen.getByRole("button", { name: "+ New" }));
    // There are two Cancel buttons — pick the one in the form header area
    const cancelBtns = screen.getAllByRole("button", { name: /cancel/i });
    fireEvent.click(cancelBtns[0]);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "+ New" })).toBeInTheDocument(),
    );
  });
});

describe("AgentsPanel — create form validation", () => {
  it("shows no slug error while field is empty", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([]);
    render(<AgentsPanel />);
    await waitFor(() => screen.getByRole("button", { name: "+ New" }));
    fireEvent.click(screen.getByRole("button", { name: "+ New" }));

    // No error when field is untouched
    expect(
      screen.queryByText(/slug must start/i),
    ).not.toBeInTheDocument();
  });

  it("shows Create button disabled when form is incomplete", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([]);
    render(<AgentsPanel />);
    await waitFor(() => screen.getByRole("button", { name: "+ New" }));
    fireEvent.click(screen.getByRole("button", { name: "+ New" }));

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    expect(createBtn).toBeDisabled();
  });
});

describe("AgentsPanel — error surfacing", () => {
  it("test_save_shows_error_on_500", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);
    vi.mocked(agentsApi.updateAgent).mockRejectedValue(new Error("Internal Server Error"));

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByDisplayValue("Scraper"));

    // Edit the display name to make the form dirty
    const nameInput = screen.getByDisplayValue("Scraper");
    fireEvent.change(nameInput, { target: { value: "Scraper X" } });

    // Click Save
    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    fireEvent.click(saveBtn);

    await waitFor(() =>
      expect(screen.getByText(/internal server error/i)).toBeInTheDocument(),
    );
  });

  it("test_create_shows_error_on_409", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([]);
    vi.mocked(agentsApi.createAgent).mockRejectedValue(new Error("Agent with this slug already exists"));

    render(<AgentsPanel />);
    await waitFor(() => screen.getByRole("button", { name: "+ New" }));
    fireEvent.click(screen.getByRole("button", { name: "+ New" }));

    // Fill in slug, display name, and instructions (all required for canSubmit)
    const slugInput = screen.getByPlaceholderText(/my_researcher/i);
    fireEvent.change(slugInput, { target: { value: "my_agent" } });

    const nameInput = screen.getByPlaceholderText(/my researcher/i);
    fireEvent.change(nameInput, { target: { value: "My Agent" } });

    const instructionsInput = screen.getByPlaceholderText(/you are the/i);
    fireEvent.change(instructionsInput, { target: { value: "You are a helpful agent." } });

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    expect(createBtn).not.toBeDisabled();
    fireEvent.click(createBtn);

    await waitFor(() =>
      expect(screen.getByText(/already exists/i)).toBeInTheDocument(),
    );
  });
});

describe("AgentsPanel — dirty-state guards", () => {
  it("test_cancel_after_tool_save_preserves_edits", async () => {
    const updatedWithTools: AgentDetail = {
      ...SCRAPER_DETAIL,
      tool_ids: [10, 11, 12, 99],
    };

    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);
    vi.mocked(agentsApi.setAgentTools).mockResolvedValue(updatedWithTools);

    // listTools is already mocked to return empty in the vi.mock at top of file

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByDisplayValue("Scraper"));

    // User edits the display_name field
    const nameInput = screen.getByDisplayValue("Scraper");
    fireEvent.change(nameInput, { target: { value: "Scraper Edited" } });

    // Open the tool assignment drawer
    const manageBtn = screen.getAllByRole("button", { name: /manage…/i })[0];
    fireEvent.click(manageBtn);

    // Wait for the tool assignment drawer to open and click Save
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save \(/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /save \(/i }));

    // After the tool save, we're back in the editor
    await waitFor(() => screen.getByDisplayValue("Scraper Edited"));

    // Now click Cancel — should reset to the SAVED state (the prop's original
    // display_name "Scraper"), NOT keep "Scraper Edited" since savedRef now
    // points to updatedWithTools (which still has display_name "Scraper")
    const cancelBtn = screen.getByRole("button", { name: /^cancel$/i });
    fireEvent.click(cancelBtn);

    // display_name should revert to "Scraper" (what the server confirmed), not "Scraper Edited"
    await waitFor(() =>
      expect(screen.getByDisplayValue("Scraper")).toBeInTheDocument(),
    );
    expect(screen.queryByDisplayValue("Scraper Edited")).not.toBeInTheDocument();
  });

  it("test_back_with_unsaved_changes_shows_confirm", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByDisplayValue("Scraper"));

    // Edit a field to make it dirty
    const nameInput = screen.getByDisplayValue("Scraper");
    fireEvent.change(nameInput, { target: { value: "Scraper Changed" } });

    // Click Back — opens the ConfirmDialog instead of falling back to navigation.
    const backBtn = screen.getByRole("button", { name: /← back/i });
    fireEvent.click(backBtn);

    const dialog = await screen.findByRole("dialog", {
      name: /discard unsaved changes/i,
    });

    // Cancel — should still be in the editor with edits intact.
    fireEvent.click(within(dialog).getByRole("button", { name: /^cancel$/i }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByDisplayValue("Scraper Changed")).toBeInTheDocument();
  });

  it("test_back_with_unsaved_changes_confirmed_returns_to_list", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([SCRAPER_SUMMARY]);
    vi.mocked(agentsApi.getAgent).mockResolvedValue(SCRAPER_DETAIL);

    render(<AgentsPanel />);
    await waitFor(() => screen.getByText("scraper"));
    fireEvent.click(screen.getByText("scraper"));
    await waitFor(() => screen.getByDisplayValue("Scraper"));

    const nameInput = screen.getByDisplayValue("Scraper");
    fireEvent.change(nameInput, { target: { value: "Scraper Changed" } });

    fireEvent.click(screen.getByRole("button", { name: /← back/i }));
    const dialog = await screen.findByRole("dialog", {
      name: /discard unsaved changes/i,
    });

    // Confirm — should drop edits and return to list view.
    fireEvent.click(
      within(dialog).getByRole("button", { name: /discard and go back/i }),
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "+ New" })).toBeInTheDocument(),
    );
  });
});
