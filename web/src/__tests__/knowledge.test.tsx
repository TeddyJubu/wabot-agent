import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { truncateForPrompt } from "../components/knowledge/charUtils";
import ContactFactsEditor from "@/components/knowledge/ContactFactsEditor";
import KnowledgePage from "@/pages/KnowledgePage";
import BlockNoteEditor from "@/components/knowledge/BlockNoteEditor";
import { KnowledgeBudgetExceededError } from "@/api/knowledge";

// ---------------------------------------------------------------------------
// Module-level mocks. Each suite resets / re-stubs as needed.
// ---------------------------------------------------------------------------

vi.mock("@/api/knowledge", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/knowledge")>("@/api/knowledge");
  return {
    ...actual,
    fetchKnowledgeContacts: vi.fn(async () => ({
      contacts: [{ contact: "1555@s.whatsapp.net", fact_count: 1, updated_at: null }],
    })),
    fetchContactFacts: vi.fn(async () => ({
      contact: "1555@s.whatsapp.net",
      facts: [{ key: "name", value: "Alex" }],
    })),
    upsertContactFact: vi.fn(async () => ({ stored: true })),
    deleteContactFact: vi.fn(async () => ({ deleted: true })),
    fetchAgentNotes: vi.fn(async () => ({ items: [] })),
    fetchKnowledgeIndex: vi.fn(async () => ({
      docs: [],
      budgets: { instructions: 10000, contact: 2000 },
    })),
    fetchInstructions: vi.fn(async () => ({
      content: "hello",
      id: "instructions",
      char_count: 5,
      updated_at: null,
    })),
    saveInstructions: vi.fn(async () => ({
      id: "instructions",
      path: "knowledge/instructions.md",
      updated_at: null,
      char_count: 5,
      truncated_preview: "hello",
    })),
  };
});

// BlockNote pulls in heavy editor internals that don't play nicely with jsdom.
// Stub it with a textarea-backed shim that exercises the same prop contract
// (initialMarkdown in, onChange wired to blocksToMarkdownLossy on the editor).
vi.mock("@blocknote/mantine", () => ({
  BlockNoteView: ({
    editor,
    onChange,
  }: {
    editor: { document: unknown; __value: string };
    onChange: () => void;
  }) => (
    <textarea
      data-testid="blocknote-textarea"
      defaultValue={editor.__value}
      onChange={(e) => {
        editor.__value = e.target.value;
        onChange();
      }}
    />
  ),
}));

vi.mock("@blocknote/mantine/style.css", () => ({}));

vi.mock("@blocknote/react", () => ({
  useCreateBlockNote: () => {
    // Minimal editor stand-in: holds the current string, exposes the same
    // async API surface BlockNoteEditor calls. `document` is opaque to us.
    const state = { __value: "", document: {} } as {
      __value: string;
      document: unknown;
      tryParseMarkdownToBlocks: (md: string) => Promise<unknown>;
      replaceBlocks: (doc: unknown, blocks: unknown) => void;
      blocksToMarkdownLossy: (doc: unknown) => Promise<string>;
    };
    state.tryParseMarkdownToBlocks = async (md: string) => {
      state.__value = md;
      return md;
    };
    state.replaceBlocks = () => {};
    state.blocksToMarkdownLossy = async () => state.__value;
    return state;
  },
}));

// ---------------------------------------------------------------------------
// charUtils — unchanged from the original suite, kept for coverage parity.
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// KnowledgePage — Phase 2a: three tabs, no Memory anywhere.
// ---------------------------------------------------------------------------

describe("KnowledgePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders three tabs and never surfaces a Memory tab", async () => {
    render(<KnowledgePage />);
    expect(await screen.findByRole("button", { name: "Instructions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Contacts" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Notes" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Memory" })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// BlockNoteEditor — Phase 2a: 413 inline error + autosave gate.
// ---------------------------------------------------------------------------

describe("BlockNoteEditor 413 handling", () => {
  // Real timers throughout — `waitFor` and `findBy*` poll via `setTimeout`,
  // and the editor's 2s debounce is short enough that we can just wait it out
  // with a sub-second poll interval. Using fake timers here got tangled with
  // the editor's async load -> setState -> microtask chain.
  it("shows the inline budget error when the server returns 413 and gates retries", async () => {
    const onSave = vi
      .fn<(md: string) => Promise<void>>()
      .mockRejectedValue(new KnowledgeBudgetExceededError(10000, 12345));
    const onDirty = vi.fn<(dirty: boolean) => void>();

    render(
      <BlockNoteEditor
        label="Client instructions"
        initialMarkdown=""
        maxChars={10000}
        onSave={onSave}
        onDirtyChange={onDirty}
      />,
    );

    const textarea = await screen.findByTestId("blocknote-textarea");

    // Simulate the user typing a too-large blob.
    fireEvent.change(textarea, { target: { value: "x".repeat(12345) } });

    // 2-second debounce, then async reject — the inline error renders.
    const errorEl = await screen.findByTestId("budget-error", undefined, {
      timeout: 4000,
    });
    expect(errorEl.textContent).toContain("10,000-character budget");

    // The save was attempted exactly once for that oversized payload.
    expect(onSave).toHaveBeenCalledTimes(1);

    // Document is still marked dirty so the navigation ConfirmDialog fires.
    expect(onDirty).toHaveBeenLastCalledWith(true);

    // Further edits at or above the rejected length do NOT schedule another
    // autosave — the editor refuses to hammer the server with known-oversized
    // content. Wait past the debounce window and confirm `onSave` still 1.
    fireEvent.change(textarea, { target: { value: "y".repeat(12345) } });
    await new Promise((r) => setTimeout(r, 2500));
    expect(onSave).toHaveBeenCalledTimes(1);
  }, 15000);

  it("resumes autosave once the user trims back under the rejected length", async () => {
    const onSave = vi
      .fn<(md: string) => Promise<void>>()
      .mockRejectedValueOnce(new KnowledgeBudgetExceededError(10000, 11000))
      .mockResolvedValue();

    render(
      <BlockNoteEditor
        label="Client instructions"
        initialMarkdown=""
        maxChars={10000}
        onSave={onSave}
      />,
    );

    const textarea = await screen.findByTestId("blocknote-textarea");

    fireEvent.change(textarea, { target: { value: "x".repeat(11000) } });
    await screen.findByTestId("budget-error", undefined, { timeout: 4000 });
    expect(onSave).toHaveBeenCalledTimes(1);

    // Trim below the rejected length — autosave should resume.
    fireEvent.change(textarea, { target: { value: "x".repeat(5000) } });
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2), {
      timeout: 4000,
    });
    expect(onSave).toHaveBeenLastCalledWith("x".repeat(5000));
    expect(screen.queryByTestId("budget-error")).not.toBeInTheDocument();
  }, 15000);
});
