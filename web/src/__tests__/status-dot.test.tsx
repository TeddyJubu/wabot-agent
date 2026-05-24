import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "jest-axe";
import StatusDot from "@/components/StatusDot";
import type { StatusVariant } from "@/components/StatusDot";

// Phase D · L1 — StatusDot must convey state via icon AND colour (WCAG 1.4.1).
// The outer <span> is aria-hidden because all consumers pair the dot with a
// visible text label, so these tests inspect markup rather than role/name.

const VARIANTS: StatusVariant[] = ["ok", "warn", "bad", "pending"];

function firstChild(container: HTMLElement) {
  const node = container.firstElementChild;
  if (!node) throw new Error("StatusDot rendered nothing");
  return node;
}

describe("StatusDot — glyph rendering", () => {
  // Snapshot per variant — exercises the disc+glyph composition and locks
  // the markup so future regressions (e.g. dropping the inner <svg>) trip
  // the test.  Empty inline snapshots are auto-populated on the first run.
  it("matches snapshot for `ok`", () => {
    const { container } = render(<StatusDot variant="ok" />);
    const dot = firstChild(container);
    expect(dot.querySelector("svg")).not.toBeNull();
    expect(dot).toMatchSnapshot();
  });

  it("matches snapshot for `warn`", () => {
    const { container } = render(<StatusDot variant="warn" />);
    const dot = firstChild(container);
    expect(dot.querySelector("svg")).not.toBeNull();
    expect(dot).toMatchSnapshot();
  });

  it("matches snapshot for `bad`", () => {
    const { container } = render(<StatusDot variant="bad" />);
    const dot = firstChild(container);
    expect(dot.querySelector("svg")).not.toBeNull();
    expect(dot).toMatchSnapshot();
  });

  it("matches snapshot for `pending`", () => {
    const { container } = render(<StatusDot variant="pending" />);
    const dot = firstChild(container);
    expect(dot.querySelector("svg")).not.toBeNull();
    expect(dot).toMatchSnapshot();
  });
});

describe("StatusDot — shimmer animation", () => {
  it("applies the `shimmer` class on `ok` by default (animated=true)", () => {
    const { container } = render(<StatusDot variant="ok" />);
    const disc = firstChild(container).querySelector("span");
    expect(disc).not.toBeNull();
    expect(disc!.className).toContain("shimmer");
  });

  it("omits the `shimmer` class on `ok` when animated={false}", () => {
    const { container } = render(<StatusDot variant="ok" animated={false} />);
    const disc = firstChild(container).querySelector("span");
    expect(disc).not.toBeNull();
    expect(disc!.className).not.toContain("shimmer");
  });
});

describe("StatusDot — accessibility", () => {
  it("renders all four variants alongside a label with no axe violations", async () => {
    // Mirror the StatusBar-style "<label> <dot> <value>" pattern so axe sees
    // each dot paired with real text and can flag any colour-only signalling
    // or contrast issues introduced by the inner glyph.
    const { container } = render(
      <ul>
        {VARIANTS.map((variant) => (
          <li key={variant}>
            <span>{variant}</span>
            <StatusDot variant={variant} />
            <span>{variant}</span>
          </li>
        ))}
      </ul>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
