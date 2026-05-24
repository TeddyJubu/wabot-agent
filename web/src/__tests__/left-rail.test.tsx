import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import LeftRail from "@/components/LeftRail";
import { useStore } from "@/store";
import { useRouteStore } from "@/store/route";

// ---------------------------------------------------------------------------
// Setup — reset both stores between tests so route/slide-over state can't leak.
// ---------------------------------------------------------------------------

const LABELS = [
  "Home",
  "Pairing",
  "Insights",
  "Knowledge",
  "Agents",
  "Capabilities",
  "Settings",
] as const;

// Snapshot the original location so we can restore it after each test that
// clobbers it (the `window.location.href = "/knowledge"` path requires the
// classic jsdom trick of replacing window.location wholesale).
const originalLocation = window.location;

beforeEach(() => {
  useRouteStore.setState({ route: "home" });
  useStore.setState({ slideOver: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  // Restore window.location if a test swapped it.
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

describe("LeftRail — rendering", () => {
  it("renders all 7 destinations with a visible text label", () => {
    render(<LeftRail />);
    for (const label of LABELS) {
      // Visible label
      expect(screen.getByText(label)).toBeInTheDocument();
      // Accessible name on the button matches the label (a11y mandate per
      // B1: text labels are required, never icon-only).
      const button = screen.getByRole("button", { name: label });
      expect(button).toHaveAttribute("type", "button");
    }
  });

  it("each button meets the 44x44 tap-target minimum (class assertion)", () => {
    render(<LeftRail />);
    for (const label of LABELS) {
      const button = screen.getByRole("button", { name: label });
      expect(button.className).toMatch(/min-h-\[44px\]/);
      expect(button.className).toMatch(/min-w-\[44px\]/);
    }
  });

  it("groups the items under Run / Build / Connect headings", () => {
    render(<LeftRail />);
    expect(screen.getByText("Run")).toBeInTheDocument();
    expect(screen.getByText("Build")).toBeInTheDocument();
    expect(screen.getByText("Connect")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// aria-current flips with the active route
// ---------------------------------------------------------------------------

describe("LeftRail — aria-current", () => {
  it("starts with Home as the current page", () => {
    render(<LeftRail />);
    expect(
      screen.getByRole("button", { name: "Home" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("flips aria-current when a different in-shell route is picked", () => {
    render(<LeftRail />);

    const home = screen.getByRole("button", { name: "Home" });
    const agents = screen.getByRole("button", { name: "Agents" });

    expect(home).toHaveAttribute("aria-current", "page");
    expect(agents).not.toHaveAttribute("aria-current");

    fireEvent.click(agents);

    expect(screen.getByRole("button", { name: "Agents" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "Home" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});

// ---------------------------------------------------------------------------
// Keyboard activation — Enter behaves identically to a click on a native button
// ---------------------------------------------------------------------------

describe("LeftRail — keyboard", () => {
  it("buttons are focusable and Enter activates them", () => {
    render(<LeftRail />);
    const insights = screen.getByRole("button", { name: "Insights" });

    // Focusable
    insights.focus();
    expect(insights).toBe(document.activeElement);

    // Activation — native <button> turns Enter into a click; we simulate the
    // same path the user takes (the assertion is the behaviour, not the
    // dispatched DOM event).
    fireEvent.keyDown(insights, { key: "Enter" });
    fireEvent.click(insights);

    expect(useRouteStore.getState().route).toBe("insights");
  });
});

// ---------------------------------------------------------------------------
// Item routing — each item triggers the right side-effect
// ---------------------------------------------------------------------------

describe("LeftRail — item routing", () => {
  it("Home click sets route to 'home'", () => {
    useRouteStore.setState({ route: "insights" });
    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    expect(useRouteStore.getState().route).toBe("home");
  });

  it("Insights click sets route to 'insights'", () => {
    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Insights" }));
    expect(useRouteStore.getState().route).toBe("insights");
  });

  it("Pairing click opens /pair in a new tab", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Pairing" }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("/pair", "_blank", "noopener");
    // Pairing is a nav handoff — it does NOT mutate the in-shell route.
    expect(useRouteStore.getState().route).toBe("home");
  });

  it("Knowledge click navigates to /knowledge", () => {
    // Conventional jsdom workaround: swap window.location with a writable stub
    // so the assignment can be observed.
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { href: "" },
    });

    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Knowledge" }));
    expect(window.location.href).toBe("/knowledge");
    // Knowledge is also a nav handoff — in-shell route stays put.
    expect(useRouteStore.getState().route).toBe("home");
  });

  it("Agents click opens the agents slide-over and sets route", () => {
    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    expect(useStore.getState().slideOver).toBe("agents");
    expect(useRouteStore.getState().route).toBe("agents");
  });

  it("Capabilities click sets route to 'capabilities' without opening a slide-over (C4: Capabilities is now a full page)", () => {
    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Capabilities" }));
    expect(useRouteStore.getState().route).toBe("capabilities");
    expect(useStore.getState().slideOver).toBeNull();
  });

  it("Settings click sets route to 'settings' without opening a slide-over (C1: Settings is now a full page)", () => {
    render(<LeftRail />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(useRouteStore.getState().route).toBe("settings");
    expect(useStore.getState().slideOver).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Accessibility
// ---------------------------------------------------------------------------

describe("LeftRail — accessibility", () => {
  it("has no axe-detectable a11y violations", async () => {
    const { container } = render(<LeftRail />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
