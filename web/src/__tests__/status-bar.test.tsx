import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import type { PairingState } from "@/api/pairing";
import { useStore, type Readiness } from "@/store";
import StatusBar from "@/components/StatusBar";

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

beforeEach(() => {
  useStore.setState({
    readiness: PRISTINE_READINESS,
    pairing: null,
    slideOver: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StatusBar — rendering", () => {
  it("renders exactly 4 chips with both label and value visible", () => {
    render(<StatusBar />);
    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(4);

    // Each chip must surface its own label as visible text — colour alone
    // can never carry the meaning (WCAG 1.4.1).
    for (const label of ["WhatsApp", "Model", "Send policy", "Memory"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }

    // The pending fixture surfaces "Checking…" for model/policy/memory
    // (three times) and "checking" for the WhatsApp chip (pairing === null).
    expect(screen.getAllByText("Checking…")).toHaveLength(3);
    expect(screen.getByText("checking")).toBeInTheDocument();
  });

  it("each chip exposes an icon (svg) alongside its text", () => {
    render(<StatusBar />);
    for (const label of ["WhatsApp", "Model", "Send policy", "Memory"]) {
      const button = screen.getByRole("button", {
        name: new RegExp(`^${label}:`),
      });
      expect(button.querySelector("svg")).not.toBeNull();
    }
  });
});

describe("StatusBar — variant values", () => {
  it("WhatsApp chip shows 'connected' when logged in and connected", () => {
    useStore.setState({ pairing: pairing({ logged_in: true, connected: true }) });
    render(<StatusBar />);
    expect(
      screen.getByRole("button", { name: "WhatsApp: connected" }),
    ).toBeInTheDocument();
  });

  it("WhatsApp chip shows 'scan to pair' when a QR is waiting", () => {
    useStore.setState({
      pairing: pairing({ logged_in: false, qr_available: true, reachable: true }),
    });
    render(<StatusBar />);
    expect(
      screen.getByRole("button", { name: "WhatsApp: scan to pair" }),
    ).toBeInTheDocument();
  });

  it("Model chip reflects the readiness label", () => {
    useStore.setState({
      readiness: {
        ...PRISTINE_READINESS,
        model: { label: "openai", variant: "ok" },
      },
    });
    render(<StatusBar />);
    expect(
      screen.getByRole("button", { name: "Model: openai" }),
    ).toBeInTheDocument();
  });

  it("Send policy chip reflects the readiness label", () => {
    useStore.setState({
      readiness: {
        ...PRISTINE_READINESS,
        policy: { label: "allow_all", variant: "warn" },
      },
    });
    render(<StatusBar />);
    expect(
      screen.getByRole("button", { name: "Send policy: allow_all" }),
    ).toBeInTheDocument();
  });

  it("Memory chip reflects the readiness label", () => {
    useStore.setState({
      readiness: {
        ...PRISTINE_READINESS,
        memory: { label: "unknown", variant: "warn" },
      },
    });
    render(<StatusBar />);
    expect(
      screen.getByRole("button", { name: "Memory: unknown" }),
    ).toBeInTheDocument();
  });
});

describe("StatusBar — interactions", () => {
  it("WhatsApp chip opens /pair in a new tab when unpaired", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<StatusBar />);
    fireEvent.click(
      screen.getByRole("button", { name: /^WhatsApp:/ }),
    );
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("/pair", "_blank", "noopener");
  });

  it("WhatsApp chip still opens /pair when already linked", () => {
    useStore.setState({ pairing: pairing({ logged_in: true, connected: true }) });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<StatusBar />);
    fireEvent.click(
      screen.getByRole("button", { name: "WhatsApp: connected" }),
    );
    expect(openSpy).toHaveBeenCalledWith("/pair", "_blank", "noopener");
  });

  it("Model chip calls openSlideOver('settings')", () => {
    const openSlideOver = vi.fn();
    useStore.setState({ openSlideOver });
    render(<StatusBar />);
    fireEvent.click(screen.getByRole("button", { name: /^Model:/ }));
    expect(openSlideOver).toHaveBeenCalledTimes(1);
    expect(openSlideOver).toHaveBeenCalledWith("settings");
  });

  it("Send policy chip calls openSlideOver('settings')", () => {
    const openSlideOver = vi.fn();
    useStore.setState({ openSlideOver });
    render(<StatusBar />);
    fireEvent.click(screen.getByRole("button", { name: /^Send policy:/ }));
    expect(openSlideOver).toHaveBeenCalledWith("settings");
  });

  it("Memory chip calls openSlideOver('settings')", () => {
    const openSlideOver = vi.fn();
    useStore.setState({ openSlideOver });
    render(<StatusBar />);
    fireEvent.click(screen.getByRole("button", { name: /^Memory:/ }));
    expect(openSlideOver).toHaveBeenCalledWith("settings");
  });
});

describe("StatusBar — accessibility", () => {
  it("has no axe-detectable a11y violations", async () => {
    const { container } = render(<StatusBar />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
