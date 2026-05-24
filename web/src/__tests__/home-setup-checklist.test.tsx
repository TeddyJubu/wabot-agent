import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import type { PairingState } from "@/api/pairing";
import { useStore, type Readiness } from "@/store";
import SetupChecklist from "@/components/home/SetupChecklist";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/knowledge", () => ({
  fetchKnowledgeIndex: vi.fn(() =>
    Promise.resolve({
      docs: [],
      budgets: { instructions: 0, memory: 0, contact: 0 },
    }),
  ),
}));

import * as knowledgeApi from "@/api/knowledge";

// ---------------------------------------------------------------------------
// Fixtures + setup
// ---------------------------------------------------------------------------

const PENDING_ROW = { label: "Checking…", variant: "pending" as const };
const PRISTINE_READINESS: Readiness = {
  overall: "pending",
  model: PENDING_ROW,
  wabot: PENDING_ROW,
  policy: PENDING_ROW,
  memory: PENDING_ROW,
};

function pairing(overrides: Partial<PairingState> = {}): PairingState {
  return {
    qr_available: false,
    logged_in: false,
    connected: false,
    reachable: true,
    ...overrides,
  };
}

// Snapshot window.location so tests that overwrite `href` can restore it.
const originalLocation = window.location;

beforeEach(() => {
  useStore.setState({
    readiness: PRISTINE_READINESS,
    pairing: null,
    slideOver: null,
  });
  localStorage.clear();
  vi.mocked(knowledgeApi.fetchKnowledgeIndex).mockResolvedValue({
    docs: [],
    budgets: { instructions: 0, memory: 0, contact: 0 },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  if (window.location !== originalLocation) {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
  }
});

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe("SetupChecklist — rendering", () => {
  it("renders all four steps with their titles", () => {
    render(<SetupChecklist isSignedIn={false} />);
    // Titles render as <p> inside each <li>; action buttons re-use some of
    // the same words ("Sign in"), so target the title element by tag to
    // avoid the button collision rather than relying on visible-text match.
    for (const title of [
      "Sign in",
      "Pair WhatsApp",
      "Pick a model",
      "Add knowledge",
    ]) {
      expect(
        screen.getByText(title, { selector: "p" }),
      ).toBeInTheDocument();
    }

    // The list itself is labelled for assistive tech.
    expect(screen.getByLabelText("Setup checklist")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Step 1 — Sign in
// ---------------------------------------------------------------------------

describe("SetupChecklist — Sign in step", () => {
  it("is active with a Sign in button when isSignedIn=false", () => {
    render(<SetupChecklist isSignedIn={false} />);
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("type", "button");
  });

  it("is done when isSignedIn=true", () => {
    render(<SetupChecklist isSignedIn={true} />);
    // No Sign in action button — instead a Done pill is rendered next to
    // the row.
    expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
    // The first step row is the "Sign in" row, so its Done pill should be
    // present somewhere in the list.
    expect(screen.getAllByText("Done").length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Step 2 — Pair WhatsApp
// ---------------------------------------------------------------------------

describe("SetupChecklist — Pair WhatsApp step", () => {
  it("shows the Open /pair action when pairing.logged_in is false", () => {
    useStore.setState({ pairing: pairing({ logged_in: false }) });
    render(<SetupChecklist isSignedIn={true} />);

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    fireEvent.click(screen.getByRole("button", { name: "Open /pair" }));
    expect(openSpy).toHaveBeenCalledWith("/pair", "_blank", "noopener");
  });

  it("is done when pairing.logged_in flips to true", () => {
    const { rerender } = render(<SetupChecklist isSignedIn={true} />);
    // While pairing is null the action is visible.
    expect(screen.getByRole("button", { name: "Open /pair" })).toBeInTheDocument();

    useStore.setState({
      pairing: pairing({ logged_in: true, connected: true, qr_available: false, reachable: true }),
    });
    rerender(<SetupChecklist isSignedIn={true} />);

    expect(screen.queryByRole("button", { name: "Open /pair" })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Step 3 — Pick a model
// ---------------------------------------------------------------------------

describe("SetupChecklist — Pick a model step", () => {
  it("is done when readiness.model.variant === 'ok'", () => {
    useStore.setState({
      readiness: {
        ...PRISTINE_READINESS,
        model: { label: "openai", variant: "ok" },
      },
    });
    render(<SetupChecklist isSignedIn={true} />);
    expect(screen.queryByRole("button", { name: "Open settings" })).toBeNull();
  });

  it("is active and its action calls openSlideOver('settings') when variant is 'warn'", () => {
    const openSlideOver = vi.fn();
    useStore.setState({
      openSlideOver,
      readiness: {
        ...PRISTINE_READINESS,
        model: { label: "offline", variant: "warn" },
      },
    });
    render(<SetupChecklist isSignedIn={true} />);

    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    expect(openSlideOver).toHaveBeenCalledWith("settings");
  });
});

// ---------------------------------------------------------------------------
// Step 4 — Add knowledge
// ---------------------------------------------------------------------------

describe("SetupChecklist — Add knowledge step", () => {
  it("is active with a Visit knowledge button when the index has no docs", async () => {
    render(<SetupChecklist isSignedIn={true} />);
    await waitFor(() =>
      expect(knowledgeApi.fetchKnowledgeIndex).toHaveBeenCalled(),
    );
    expect(
      screen.getByRole("button", { name: "Visit knowledge" }),
    ).toBeInTheDocument();
  });

  it("is done when the index returns at least one document", async () => {
    vi.mocked(knowledgeApi.fetchKnowledgeIndex).mockResolvedValue({
      docs: [
        {
          id: "i",
          path: "instructions.md",
          updated_at: null,
          char_count: 10,
          truncated_preview: "Hello",
        },
      ],
      budgets: { instructions: 0, memory: 0, contact: 0 },
    });

    render(<SetupChecklist isSignedIn={true} />);
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Visit knowledge" }),
      ).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// onDismiss
// ---------------------------------------------------------------------------

describe("SetupChecklist — Skip setup", () => {
  it("renders a Skip setup button when onDismiss is provided", () => {
    render(<SetupChecklist isSignedIn={false} onDismiss={() => {}} />);
    expect(
      screen.getByRole("button", { name: "Skip setup" }),
    ).toBeInTheDocument();
  });

  it("does not render Skip setup when onDismiss is omitted", () => {
    render(<SetupChecklist isSignedIn={false} />);
    expect(screen.queryByRole("button", { name: "Skip setup" })).toBeNull();
  });

  it("calls onDismiss when clicked", () => {
    const onDismiss = vi.fn();
    render(<SetupChecklist isSignedIn={false} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Skip setup" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Accessibility
// ---------------------------------------------------------------------------

describe("SetupChecklist — accessibility", () => {
  it("has no axe-detectable a11y violations", async () => {
    const { container } = render(
      <SetupChecklist isSignedIn={false} onDismiss={() => {}} />,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
