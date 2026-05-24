import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import GroupsPanel from "@/components/slide-overs/GroupsPanel";
import type { GroupDetail, GroupSummary } from "@/api/groups";

// ---------------------------------------------------------------------------
// Mock API module
// ---------------------------------------------------------------------------

vi.mock("@/api/groups", () => ({
  fetchGroups: vi.fn(),
  fetchGroup: vi.fn(),
  fetchGroupInvite: vi.fn(),
  createGroup: vi.fn(),
  joinGroup: vi.fn(),
  leaveGroup: vi.fn(),
  removeGroupPicture: vi.fn(),
  setGroupPicture: vi.fn(),
  updateGroup: vi.fn(),
  updateGroupParticipants: vi.fn(),
}));

import * as groupsApi from "@/api/groups";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ALPHA_SUMMARY: GroupSummary = {
  jid: "120363111111@g.us",
  name: "Alpha Squad",
  participant_count: 3,
};

const BETA_SUMMARY: GroupSummary = {
  jid: "120363222222@g.us",
  name: "Beta Group",
  participant_count: 5,
};

const ALPHA_DETAIL: GroupDetail = {
  jid: ALPHA_SUMMARY.jid,
  name: "Alpha Squad",
  topic: "Internal coordination",
  participant_count: 3,
  participants: [
    { jid: "+15550001111", is_admin: true },
    { jid: "+15550002222" },
    { jid: "+15550003333" },
  ],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(groupsApi.fetchGroups).mockResolvedValue([]);
});

describe("GroupsPanel — list load", () => {
  it("renders the list of groups returned by fetchGroups", async () => {
    vi.mocked(groupsApi.fetchGroups).mockResolvedValue([ALPHA_SUMMARY, BETA_SUMMARY]);

    render(<GroupsPanel />);

    await waitFor(() => expect(screen.getByText("Alpha Squad")).toBeInTheDocument());
    expect(screen.getByText("Beta Group")).toBeInTheDocument();
    expect(screen.getByText(/Your groups \(2\)/i)).toBeInTheDocument();
  });

  it("calls fetchGroups on mount", async () => {
    render(<GroupsPanel />);
    await waitFor(() => expect(groupsApi.fetchGroups).toHaveBeenCalledTimes(1));
  });
});

describe("GroupsPanel — create form", () => {
  it("Create button is disabled when name is empty", async () => {
    render(<GroupsPanel />);
    await waitFor(() => expect(groupsApi.fetchGroups).toHaveBeenCalled());

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    expect(createBtn).toBeDisabled();
  });

  it("clicking Create with empty name does NOT call createGroup", async () => {
    render(<GroupsPanel />);
    await waitFor(() => expect(groupsApi.fetchGroups).toHaveBeenCalled());

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    // Even if we attempt to click, the button is disabled.
    fireEvent.click(createBtn);
    expect(groupsApi.createGroup).not.toHaveBeenCalled();
  });

  it("submitting with a valid name calls createGroup with parsed phones", async () => {
    vi.mocked(groupsApi.createGroup).mockResolvedValue({});

    render(<GroupsPanel />);
    await waitFor(() => expect(groupsApi.fetchGroups).toHaveBeenCalled());

    const nameInput = screen.getByPlaceholderText("Group name");
    fireEvent.change(nameInput, { target: { value: "New Team" } });

    const membersInput = screen.getByPlaceholderText(/Members \(\+65/i);
    fireEvent.change(membersInput, {
      target: { value: "+15550001111, +15550002222" },
    });

    const createBtn = screen.getByRole("button", { name: /^create$/i });
    expect(createBtn).not.toBeDisabled();
    fireEvent.click(createBtn);

    await waitFor(() =>
      expect(groupsApi.createGroup).toHaveBeenCalledWith("New Team", [
        "+15550001111",
        "+15550002222",
      ]),
    );
  });
});

describe("GroupsPanel — selecting a group reveals editor", () => {
  it("clicking a group loads its detail and renders the editor", async () => {
    vi.mocked(groupsApi.fetchGroups).mockResolvedValue([ALPHA_SUMMARY]);
    vi.mocked(groupsApi.fetchGroup).mockResolvedValue(ALPHA_DETAIL);

    render(<GroupsPanel />);
    await waitFor(() => expect(screen.getByText("Alpha Squad")).toBeInTheDocument());

    // Click the group row
    fireEvent.click(screen.getByText("Alpha Squad"));

    // Editor header appears
    await waitFor(() =>
      expect(screen.getByText(/Manage Alpha Squad/i)).toBeInTheDocument(),
    );

    // Name + topic are prefilled
    expect(screen.getByDisplayValue("Alpha Squad")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Internal coordination")).toBeInTheDocument();

    // The selected jid is shown in the editor (as mono text)
    expect(screen.getByText(ALPHA_SUMMARY.jid)).toBeInTheDocument();
  });
});

describe("GroupsPanel — editor participant actions", () => {
  beforeEach(() => {
    vi.mocked(groupsApi.fetchGroups).mockResolvedValue([ALPHA_SUMMARY]);
    vi.mocked(groupsApi.fetchGroup).mockResolvedValue(ALPHA_DETAIL);
    vi.mocked(groupsApi.updateGroupParticipants).mockResolvedValue({});
  });

  async function openEditor() {
    render(<GroupsPanel />);
    await waitFor(() => screen.getByText("Alpha Squad"));
    fireEvent.click(screen.getByText("Alpha Squad"));
    await waitFor(() => screen.getByText(/Manage Alpha Squad/i));
  }

  it("add parses comma-separated phones and calls updateGroupParticipants with action=add", async () => {
    await openEditor();

    const memberInput = screen.getByPlaceholderText(
      /Phone numbers to add\/remove/i,
    );
    fireEvent.change(memberInput, {
      target: { value: "+15550001111, +15550002222" },
    });

    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() =>
      expect(groupsApi.updateGroupParticipants).toHaveBeenCalledWith(
        ALPHA_SUMMARY.jid,
        ["+15550001111", "+15550002222"],
        "add",
      ),
    );
  });

  it("remove calls updateGroupParticipants with action=remove", async () => {
    await openEditor();

    const memberInput = screen.getByPlaceholderText(
      /Phone numbers to add\/remove/i,
    );
    fireEvent.change(memberInput, { target: { value: "+15550009999" } });

    fireEvent.click(screen.getByRole("button", { name: /^remove$/i }));

    await waitFor(() =>
      expect(groupsApi.updateGroupParticipants).toHaveBeenCalledWith(
        ALPHA_SUMMARY.jid,
        ["+15550009999"],
        "remove",
      ),
    );
  });

  it("promote calls updateGroupParticipants with action=promote", async () => {
    await openEditor();

    const memberInput = screen.getByPlaceholderText(
      /Phone numbers to add\/remove/i,
    );
    fireEvent.change(memberInput, { target: { value: "+15550002222" } });

    fireEvent.click(screen.getByRole("button", { name: /^promote$/i }));

    await waitFor(() =>
      expect(groupsApi.updateGroupParticipants).toHaveBeenCalledWith(
        ALPHA_SUMMARY.jid,
        ["+15550002222"],
        "promote",
      ),
    );
  });

  it("demote calls updateGroupParticipants with action=demote", async () => {
    await openEditor();

    const memberInput = screen.getByPlaceholderText(
      /Phone numbers to add\/remove/i,
    );
    fireEvent.change(memberInput, { target: { value: "+15550001111" } });

    fireEvent.click(screen.getByRole("button", { name: /^demote$/i }));

    await waitFor(() =>
      expect(groupsApi.updateGroupParticipants).toHaveBeenCalledWith(
        ALPHA_SUMMARY.jid,
        ["+15550001111"],
        "demote",
      ),
    );
  });

  it("participant action buttons are disabled when the phones field is empty", async () => {
    await openEditor();

    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^remove$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^promote$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^demote$/i })).toBeDisabled();
  });
});
