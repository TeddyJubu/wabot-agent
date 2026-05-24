import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { ConfirmDialog } from "@/components/ConfirmDialog";

describe("ConfirmDialog — visibility", () => {
  it("renders nothing when open={false}", () => {
    const { container } = render(
      <ConfirmDialog
        open={false}
        title="Hidden"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders dialog with correct ARIA when open", () => {
    render(
      <ConfirmDialog
        open
        title="Delete thing?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Delete thing?");
  });
});

describe("ConfirmDialog — focus management", () => {
  it("moves focus to the cancel button when no requireTyped is set", () => {
    render(
      <ConfirmDialog
        open
        title="Plain confirm"
        cancelLabel="Cancel"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(document.activeElement).toBe(cancel);
  });

  it("moves focus to the input when requireTyped is set", () => {
    render(
      <ConfirmDialog
        open
        title="Typed confirm"
        requireTyped="ALLOW ALL"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const input = screen.getByLabelText("Confirmation input");
    expect(document.activeElement).toBe(input);
  });
});

describe("ConfirmDialog — keyboard handling", () => {
  it("fires onCancel when ESC is pressed", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Esc test"
        onConfirm={() => {}}
        onCancel={onCancel}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("cycles focus from last back to first on Tab", () => {
    render(
      <ConfirmDialog
        open
        title="Tab test"
        confirmLabel="Confirm"
        cancelLabel="Cancel"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    // Focus the last focusable (confirm), press Tab, focus should wrap to first (cancel).
    confirm.focus();
    expect(document.activeElement).toBe(confirm);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
  });

  it("cycles focus from first to last on Shift+Tab", () => {
    render(
      <ConfirmDialog
        open
        title="Shift tab test"
        confirmLabel="Confirm"
        cancelLabel="Cancel"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    cancel.focus();
    fireEvent.keyDown(screen.getByRole("dialog"), {
      key: "Tab",
      shiftKey: true,
    });
    expect(document.activeElement).toBe(confirm);
  });
});

describe("ConfirmDialog — typed confirmation gate", () => {
  it("disables primary until exact text typed, then enables it", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Type to confirm"
        requireTyped="ALLOW ALL"
        confirmLabel="Switch"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const primary = screen.getByRole("button", { name: "Switch" });
    expect(primary).toBeDisabled();

    const input = screen.getByLabelText("Confirmation input");
    fireEvent.change(input, { target: { value: "allow all" } });
    expect(primary).toBeDisabled();

    fireEvent.change(input, { target: { value: "ALLOW ALL " } });
    expect(primary).toBeDisabled();

    fireEvent.change(input, { target: { value: "ALLOW ALL" } });
    expect(primary).not.toBeDisabled();

    fireEvent.click(primary);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("primary is enabled immediately when no requireTyped is set", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Plain"
        confirmLabel="Go"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const primary = screen.getByRole("button", { name: "Go" });
    expect(primary).not.toBeDisabled();
    fireEvent.click(primary);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog — cancel", () => {
  it("fires onCancel when the cancel button is clicked", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Cancel test"
        cancelLabel="No"
        onConfirm={() => {}}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "No" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog — accessibility", () => {
  it("has no axe violations", async () => {
    const { baseElement } = render(
      <ConfirmDialog
        open
        title="Axe check"
        description="A short description for context."
        requireTyped="ALLOW ALL"
        confirmLabel="Switch to allow_all"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const results = await axe(baseElement);
    expect(results).toHaveNoViolations();
  });
});
