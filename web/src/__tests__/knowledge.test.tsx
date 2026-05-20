import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { truncateForPrompt } from "../components/knowledge/charUtils";
import ContactFactsEditor from "@/components/knowledge/ContactFactsEditor";

vi.mock("@/api/knowledge", () => ({
  fetchKnowledgeContacts: vi.fn(async () => ({
    contacts: [{ contact: "1555@s.whatsapp.net", fact_count: 1, updated_at: null }],
  })),
  fetchContactFacts: vi.fn(async () => ({
    contact: "1555@s.whatsapp.net",
    facts: [{ key: "name", value: "Alex" }],
  })),
  upsertContactFact: vi.fn(async () => ({ stored: true })),
  deleteContactFact: vi.fn(async () => ({ deleted: true })),
}));

describe("charUtils", () => {
  it("warns when near budget via truncate suffix", () => {
    const long = "a".repeat(50);
    const out = truncateForPrompt(long, 20);
    expect(out).toContain("[truncated]");
    expect(out.length).toBeLessThanOrEqual(20);
  });
});

describe("ContactFactsEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders contact facts and add row control", async () => {
    render(<ContactFactsEditor />);
    expect(await screen.findByDisplayValue("name")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Alex")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("add-fact-row"));
    await waitFor(() => {
      expect(screen.getAllByPlaceholderText("key").length).toBeGreaterThan(1);
    });
  });
});
