import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PolicySection } from "@/components/slide-overs/settings/PolicySection";

type Policy = "dry_run" | "allowlist" | "allow_all" | "owner";

interface Stubs {
  policy?: Policy;
  setPolicy?: (p: Policy) => void;
  owners?: string;
  setOwners?: (v: string) => void;
  recipients?: string;
  setRecipients?: (v: string) => void;
}

function renderSection(overrides: Stubs = {}) {
  const setPolicy = overrides.setPolicy ?? vi.fn();
  const setOwners = overrides.setOwners ?? vi.fn();
  const setRecipients = overrides.setRecipients ?? vi.fn();
  const utils = render(
    <PolicySection
      policy={overrides.policy ?? "dry_run"}
      setPolicy={setPolicy}
      owners={overrides.owners ?? ""}
      setOwners={setOwners}
      recipients={overrides.recipients ?? ""}
      setRecipients={setRecipients}
    />,
  );
  return { ...utils, setPolicy, setOwners, setRecipients };
}

function getRadio(label: Policy): HTMLInputElement {
  // The <label> wraps both the visible text and an sr-only radio; that text
  // is the radio's accessible name. Query by role so we never collide with
  // the same word appearing elsewhere in the section (e.g. the inline
  // "owner policy" span in the helper paragraph).
  return screen.getByRole("radio", { name: label }) as HTMLInputElement;
}

describe("PolicySection — non-destructive radios", () => {
  it.each<Policy>(["dry_run", "allowlist", "owner"])(
    "clicking %s calls setPolicy synchronously without a dialog",
    (choice) => {
      const { setPolicy } = renderSection({ policy: "dry_run" });
      // Click a choice different from the current one to actually trigger onChange.
      const target: Policy = choice === "dry_run" ? "allowlist" : choice;
      fireEvent.click(getRadio(target));
      expect(setPolicy).toHaveBeenCalledTimes(1);
      expect(setPolicy).toHaveBeenCalledWith(target);
      expect(screen.queryByRole("dialog")).toBeNull();
    },
  );
});

describe("PolicySection — allow_all confirmation flow", () => {
  it("opens the dialog instead of calling setPolicy when allow_all is clicked", () => {
    const { setPolicy } = renderSection({ policy: "dry_run" });
    fireEvent.click(getRadio("allow_all"));
    expect(setPolicy).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Switch send policy to allow_all?" }),
    ).toBeInTheDocument();
  });

  it("primary button stays disabled when wrong text is typed", () => {
    renderSection({ policy: "dry_run" });
    fireEvent.click(getRadio("allow_all"));
    const input = screen.getByLabelText("Confirmation input");
    fireEvent.change(input, { target: { value: "allow all" } });
    expect(
      screen.getByRole("button", { name: "Switch to allow_all" }),
    ).toBeDisabled();
  });

  it("primary button enables when exact text ALLOW ALL is typed", () => {
    renderSection({ policy: "dry_run" });
    fireEvent.click(getRadio("allow_all"));
    const input = screen.getByLabelText("Confirmation input");
    fireEvent.change(input, { target: { value: "ALLOW ALL" } });
    expect(
      screen.getByRole("button", { name: "Switch to allow_all" }),
    ).not.toBeDisabled();
  });

  it("clicking the primary button calls setPolicy('allow_all') exactly once", () => {
    const { setPolicy } = renderSection({ policy: "dry_run" });
    fireEvent.click(getRadio("allow_all"));
    fireEvent.change(screen.getByLabelText("Confirmation input"), {
      target: { value: "ALLOW ALL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Switch to allow_all" }));
    expect(setPolicy).toHaveBeenCalledTimes(1);
    expect(setPolicy).toHaveBeenCalledWith("allow_all");
  });

  it("clicking cancel does not call setPolicy and closes the dialog", () => {
    const { setPolicy } = renderSection({ policy: "dry_run" });
    fireEvent.click(getRadio("allow_all"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(setPolicy).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
