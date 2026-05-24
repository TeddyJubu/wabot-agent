import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";

// ---------------------------------------------------------------------------
// Mock the panel imports so this test stays focused on the tab shell + routing.
// IntegrationsPanel and ToolsPanel have their own dedicated integration tests
// (`integrations-*.test.tsx`, `tools-panel.test.tsx`) — exercising them again
// here would just drag in their API stubs without adding signal.
// ---------------------------------------------------------------------------

vi.mock("@/components/slide-overs/IntegrationsPanel", () => ({
  default: () => <div data-testid="integrations-panel">IntegrationsPanel stub</div>,
}));
vi.mock("@/components/slide-overs/ToolsPanel", () => ({
  default: () => <div data-testid="tools-panel">ToolsPanel stub</div>,
}));

import CapabilitiesPage from "@/pages/CapabilitiesPage";

// ---------------------------------------------------------------------------
// Setup — reset the URL hash before every test so deep-link assertions can't
// leak across cases. We use a "/" path; the page only reads the hash.
// ---------------------------------------------------------------------------

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

// ---------------------------------------------------------------------------
// Tablist a11y
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — tablist a11y", () => {
  it("renders a labelled tablist with two correctly-wired tabs and panel", () => {
    render(<CapabilitiesPage />);

    const tablist = screen.getByRole("tablist", { name: "Capabilities sections" });
    expect(tablist).toBeInTheDocument();

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);

    const sources = screen.getByRole("tab", { name: "Sources" });
    const tools = screen.getByRole("tab", { name: "Tools" });

    expect(sources).toHaveAttribute("aria-selected", "true");
    expect(sources).toHaveAttribute("aria-controls", "capabilities-panel-sources");
    expect(sources).toHaveAttribute("tabindex", "0");

    expect(tools).toHaveAttribute("aria-selected", "false");
    expect(tools).toHaveAttribute("aria-controls", "capabilities-panel-tools");
    expect(tools).toHaveAttribute("tabindex", "-1");

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "capabilities-panel-sources");
    expect(panel).toHaveAttribute("aria-labelledby", "capabilities-tab-sources");
  });
});

// ---------------------------------------------------------------------------
// Default tab — Sources
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — default tab", () => {
  it("mounts the Sources (IntegrationsPanel) tab by default with no hash", () => {
    render(<CapabilitiesPage />);

    expect(screen.getByTestId("integrations-panel")).toBeInTheDocument();
    // Tools panel should NOT be mounted under the default tab.
    expect(screen.queryByTestId("tools-panel")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Tab switching + URL hash sync
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — tab switching", () => {
  it("clicking Tools activates the Tools tab and mounts ToolsPanel", () => {
    render(<CapabilitiesPage />);

    fireEvent.click(screen.getByRole("tab", { name: "Tools" }));

    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    expect(toolsTab).toHaveAttribute("aria-selected", "true");
    expect(toolsTab).toHaveAttribute("tabindex", "0");

    const sourcesTab = screen.getByRole("tab", { name: "Sources" });
    expect(sourcesTab).toHaveAttribute("aria-selected", "false");
    expect(sourcesTab).toHaveAttribute("tabindex", "-1");

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "capabilities-panel-tools");
    expect(panel).toHaveAttribute("aria-labelledby", "capabilities-tab-tools");

    expect(screen.getByTestId("tools-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("integrations-panel")).not.toBeInTheDocument();

    expect(window.location.hash).toBe("#tools");
  });

  it("clicking Sources from Tools updates the hash back to #sources", () => {
    render(<CapabilitiesPage />);

    fireEvent.click(screen.getByRole("tab", { name: "Tools" }));
    expect(window.location.hash).toBe("#tools");

    fireEvent.click(screen.getByRole("tab", { name: "Sources" }));
    expect(window.location.hash).toBe("#sources");
  });
});

// ---------------------------------------------------------------------------
// Deep-link to #tools
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — deep linking", () => {
  it("deep-link to #tools activates the Tools tab on first mount", () => {
    window.history.replaceState(null, "", "/#tools");

    render(<CapabilitiesPage />);

    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    expect(toolsTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("tools-panel")).toBeInTheDocument();
    // No filter chip when arriving via the plain hash.
    expect(screen.queryByText(/Filtered by source/)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Cross-link breadcrumb chip
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — cross-link breadcrumb", () => {
  it("renders a 'Filtered by source: composio' chip when arriving via #tools?source=composio", () => {
    window.history.replaceState(null, "", "/#tools?source=composio");

    render(<CapabilitiesPage />);

    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    expect(toolsTab).toHaveAttribute("aria-selected", "true");

    // Chip is visible with the source name.
    expect(screen.getByText(/Filtered by source/)).toBeInTheDocument();
    expect(screen.getByText("composio")).toBeInTheDocument();
  });

  it("Clear filter strips the query from the hash and hides the chip", () => {
    window.history.replaceState(null, "", "/#tools?source=composio");

    render(<CapabilitiesPage />);

    expect(screen.getByText(/Filtered by source/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));

    expect(screen.queryByText(/Filtered by source/)).toBeNull();
    expect(window.location.hash).toBe("#tools");
    // Still on the Tools tab — the clear action only removes the filter chip.
    const toolsTab = screen.getByRole("tab", { name: "Tools" });
    expect(toolsTab).toHaveAttribute("aria-selected", "true");
  });
});

// ---------------------------------------------------------------------------
// Arrow-key roving
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — arrow-key roving", () => {
  it("ArrowRight from the active tab moves activation + focus to the next tab", () => {
    render(<CapabilitiesPage />);

    const sources = screen.getByRole("tab", { name: "Sources" });
    sources.focus();
    expect(document.activeElement).toBe(sources);

    fireEvent.keyDown(sources, { key: "ArrowRight" });

    const tools = screen.getByRole("tab", { name: "Tools" });
    expect(tools).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tools);
  });

  it("ArrowLeft from the first tab wraps to the last", () => {
    render(<CapabilitiesPage />);

    const sources = screen.getByRole("tab", { name: "Sources" });
    sources.focus();

    fireEvent.keyDown(sources, { key: "ArrowLeft" });

    const tools = screen.getByRole("tab", { name: "Tools" });
    expect(tools).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tools);
  });

  it("ArrowRight from the last tab wraps to the first", () => {
    window.history.replaceState(null, "", "/#tools");
    render(<CapabilitiesPage />);

    const tools = screen.getByRole("tab", { name: "Tools" });
    tools.focus();

    fireEvent.keyDown(tools, { key: "ArrowRight" });

    const sources = screen.getByRole("tab", { name: "Sources" });
    expect(sources).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(sources);
  });
});

// ---------------------------------------------------------------------------
// Tap-target floor
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — tap targets", () => {
  it("every tab button reserves a 44px min height", () => {
    render(<CapabilitiesPage />);

    for (const label of ["Sources", "Tools"] as const) {
      const tab = screen.getByRole("tab", { name: label });
      expect(tab.className).toMatch(/min-h-\[44px\]/);
    }
  });
});

// ---------------------------------------------------------------------------
// Accessibility — jest-axe sweep on the fully-mounted page.
// ---------------------------------------------------------------------------

describe("CapabilitiesPage — accessibility", () => {
  it("has no axe-detectable violations on the default tab", async () => {
    const { container } = render(<CapabilitiesPage />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("has no axe-detectable violations on the Tools tab with a filter chip", async () => {
    window.history.replaceState(null, "", "/#tools?source=composio");
    const { container } = render(<CapabilitiesPage />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
