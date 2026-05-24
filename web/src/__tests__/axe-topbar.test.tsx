import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "jest-axe";
import TopBar from "@/components/TopBar";

vi.mock("@/components/ClerkNavAuth", () => ({
  ClerkNavAuth: () => null,
}));

describe("TopBar — axe baseline", () => {
  it("has no axe-detectable a11y violations", async () => {
    const { container } = render(<TopBar />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
