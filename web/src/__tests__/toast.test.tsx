import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import ToastViewport from "@/components/Toast";
import { useToastStore } from "@/store/toast";

beforeEach(() => {
  useToastStore.getState().clear();
  vi.useRealTimers();
});

describe("ToastViewport", () => {
  it("renders nothing when the queue is empty", () => {
    const { container } = render(<ToastViewport />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders a success toast with role=status", () => {
    render(<ToastViewport />);
    act(() => {
      useToastStore.getState().push("success", "Saved");
    });
    const node = screen.getByText("Saved");
    expect(node).toBeInTheDocument();
    const card = node.closest("[role=status]");
    expect(card).not.toBeNull();
    expect(card).toHaveAttribute("aria-live", "polite");
  });

  it("uses aria-live=assertive for error variant", () => {
    render(<ToastViewport />);
    act(() => {
      useToastStore.getState().push("error", "Boom");
    });
    const node = screen.getByText("Boom");
    const card = node.closest("[role=status]");
    expect(card).not.toBeNull();
    expect(card).toHaveAttribute("aria-live", "assertive");
  });

  it("auto-dismisses after the default duration", () => {
    vi.useFakeTimers();
    render(<ToastViewport />);
    act(() => {
      useToastStore.getState().push("info", "Bye soon");
    });
    expect(screen.getByText("Bye soon")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.queryByText("Bye soon")).toBeNull();
  });

  it("dismisses immediately on close button click and clears its timer", () => {
    vi.useFakeTimers();
    render(<ToastViewport />);
    act(() => {
      useToastStore.getState().push("info", "Click me away");
    });
    expect(screen.getByText("Click me away")).toBeInTheDocument();

    const closeBtn = screen.getByRole("button", { name: /dismiss notification/i });
    act(() => {
      fireEvent.click(closeBtn);
    });
    expect(screen.queryByText("Click me away")).toBeNull();

    // Advancing timers should not error and should not resurrect the toast
    expect(() => {
      act(() => {
        vi.advanceTimersByTime(10_000);
      });
    }).not.toThrow();
    expect(screen.queryByText("Click me away")).toBeNull();
  });

  it("does not auto-dismiss when durationMs is 0", () => {
    vi.useFakeTimers();
    render(<ToastViewport />);
    act(() => {
      useToastStore.getState().push("info", "Sticky", 0);
    });
    expect(screen.getByText("Sticky")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByText("Sticky")).toBeInTheDocument();
  });
});
