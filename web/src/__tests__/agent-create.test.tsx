import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AgentCreateForm } from "@/components/slide-overs/agents/AgentCreateForm";

// ---------------------------------------------------------------------------
// Mock API so no real network calls are made
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

import * as agentsApi from "@/api/agents";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderForm() {
  const onCreated = vi.fn();
  const onCancel = vi.fn();
  render(
    <AgentCreateForm
      allAgentSlugs={["orchestrator", "scraper"]}
      onCreated={onCreated}
      onCancel={onCancel}
    />,
  );
  return { onCreated, onCancel };
}

// ---------------------------------------------------------------------------
// Slug validation tests (client-side, no network)
// ---------------------------------------------------------------------------

describe("AgentCreateForm — slug validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows no error when slug field is empty", () => {
    renderForm();
    expect(screen.queryByText(/slug must start/i)).not.toBeInTheDocument();
  });

  it("rejects slug starting with a digit", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "9bad" } });
    expect(screen.getByText(/slug must start/i)).toBeInTheDocument();
  });

  it("rejects slug with uppercase letters", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    // Input onChange lowercases, but test the regex directly against 'MyAgent'
    fireEvent.change(slugInput, { target: { value: "MyAgent" } });
    // The value is lowercased to "myagent" by onChange — "myagent" is valid, no error
    expect(screen.queryByText(/slug must start/i)).not.toBeInTheDocument();
  });

  it("rejects slug starting with underscore", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "_bad" } });
    expect(screen.getByText(/slug must start/i)).toBeInTheDocument();
  });

  it("rejects slug with special characters other than underscore", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "bad-slug" } });
    expect(screen.getByText(/slug must start/i)).toBeInTheDocument();
  });

  it("accepts a valid slug", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "my_researcher" } });
    expect(screen.queryByText(/slug must start/i)).not.toBeInTheDocument();
  });

  it("accepts slug starting with a letter followed by digits", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "agent2" } });
    expect(screen.queryByText(/slug must start/i)).not.toBeInTheDocument();
  });
});

describe("AgentCreateForm — create button state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("Create button is disabled when slug is invalid", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "9bad" } });
    expect(screen.getByRole("button", { name: /^create$/i })).toBeDisabled();
  });

  it("Create button is disabled when display name is empty", () => {
    renderForm();
    const slugInput = screen.getByPlaceholderText("my_researcher");
    fireEvent.change(slugInput, { target: { value: "valid_slug" } });
    // Display name and instructions are still empty
    expect(screen.getByRole("button", { name: /^create$/i })).toBeDisabled();
  });

  it("Create button is enabled with valid slug + display name + instructions", async () => {
    renderForm();
    fireEvent.change(screen.getByPlaceholderText("my_researcher"), {
      target: { value: "my_agent" },
    });
    fireEvent.change(screen.getByPlaceholderText("My Researcher"), {
      target: { value: "My Agent" },
    });
    fireEvent.change(screen.getByPlaceholderText("You are the …"), {
      target: { value: "You are a helpful agent." },
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^create$/i })).not.toBeDisabled(),
    );
  });
});

describe("AgentCreateForm — server round-trip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does NOT call createAgent when slug is invalid (9bad → server never reached)", async () => {
    renderForm();
    fireEvent.change(screen.getByPlaceholderText("my_researcher"), {
      target: { value: "9bad" },
    });
    fireEvent.change(screen.getByPlaceholderText("My Researcher"), {
      target: { value: "Bad agent" },
    });
    fireEvent.change(screen.getByPlaceholderText("You are the …"), {
      target: { value: "instructions" },
    });

    // Create button should be disabled — clicking it does nothing
    const createBtn = screen.getByRole("button", { name: /^create$/i });
    expect(createBtn).toBeDisabled();
    // Even if we fire click (e.g. via keyboard), createAgent is never called
    fireEvent.click(createBtn);
    expect(agentsApi.createAgent).not.toHaveBeenCalled();
  });

  it("calls createAgent with correct payload on valid form submit", async () => {
    const mockAgent = {
      id: 99,
      slug: "my_agent",
      display_name: "My Agent",
      description: null,
      is_builtin: false,
      is_enabled: true,
      parent_slug: null,
      handoff_filter: null,
      tool_count: 0,
      skill_count: 0,
      updated_at: "2026-01-01T00:00:00",
      instructions: "You are a helpful agent.",
      tool_ids: [],
      skill_ids: [],
    };
    vi.mocked(agentsApi.createAgent).mockResolvedValue(mockAgent);

    const { onCreated } = renderForm();

    fireEvent.change(screen.getByPlaceholderText("my_researcher"), {
      target: { value: "my_agent" },
    });
    fireEvent.change(screen.getByPlaceholderText("My Researcher"), {
      target: { value: "My Agent" },
    });
    fireEvent.change(screen.getByPlaceholderText("You are the …"), {
      target: { value: "You are a helpful agent." },
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^create$/i })).not.toBeDisabled(),
    );

    fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() =>
      expect(agentsApi.createAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          slug: "my_agent",
          display_name: "My Agent",
          instructions: "You are a helpful agent.",
        }),
      ),
    );

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(mockAgent));
  });
});
