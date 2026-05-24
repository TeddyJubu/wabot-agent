import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";

import { HelpPopover } from "@/components/HelpPopover";

/**
 * Wrapping the popover in a container that includes an external element gives
 * outside-click tests a real "outside" target to dispatch a mousedown on.
 */
function renderHarness(term = "MCP") {
  return render(
    <div>
      <button type="button" data-testid="outside">
        outside
      </button>
      <HelpPopover term={term}>Body text for {term}.</HelpPopover>
    </div>,
  );
}

describe("HelpPopover — trigger", () => {
  it("renders a trigger with the term-derived accessible name", () => {
    renderHarness("MCP");
    const trigger = screen.getByRole("button", { name: "What is MCP?" });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("opens the popover on click and flips aria-expanded to true", () => {
    renderHarness("MCP");
    const trigger = screen.getByRole("button", { name: "What is MCP?" });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAccessibleName("MCP — explanation");
    expect(dialog).toHaveTextContent("Body text for MCP.");
  });
});

describe("HelpPopover — dismissal", () => {
  it("closes on ESC and returns focus to the trigger", () => {
    renderHarness("MCP");
    const trigger = screen.getByRole("button", { name: "What is MCP?" });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("closes when the user clicks outside the wrapper", () => {
    renderHarness("MCP");
    const trigger = screen.getByRole("button", { name: "What is MCP?" });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes when the Close button is clicked and returns focus to the trigger", () => {
    renderHarness("MCP");
    const trigger = screen.getByRole("button", { name: "What is MCP?" });
    fireEvent.click(trigger);
    const close = screen.getByRole("button", { name: "Close" });
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});

describe("HelpPopover — accessibility", () => {
  it("has no axe violations when closed", async () => {
    const { baseElement } = renderHarness("MCP");
    const results = await axe(baseElement);
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations when open", async () => {
    const { baseElement } = renderHarness("MCP");
    fireEvent.click(screen.getByRole("button", { name: "What is MCP?" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const results = await axe(baseElement);
    expect(results).toHaveNoViolations();
  });
});
