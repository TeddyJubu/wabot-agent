import { describe, expect, it, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";

import PairingPanel from "@/components/slide-overs/PairingPanel";
import PairView from "@/components/PairView";
import { useStore } from "@/store";
import type { PairingState } from "@/types/pairing";

// `PairingState` now mirrors the Python PairingPayload one-to-one (every
// Optional field is `T | null`). These tests only care about a handful of
// fields, so this helper fills the rest with safe defaults.
function pairingFixture(overrides: Partial<PairingState>): PairingState {
  return {
    supported: true,
    reachable: false,
    logged_in: null,
    connected: null,
    qr_available: false,
    event: null,
    updated_at: null,
    expires_at: null,
    detail: null,
    ...overrides,
  };
}

beforeEach(() => {
  // Mock EventSource — jsdom doesn't ship one and PairView mounts a
  // pairing stream on render. We swallow the construction entirely;
  // PairView's behavior is driven by the Zustand store anyway.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).EventSource = class FakeEventSource {
    addEventListener(): void {}
    close(): void {}
  };
  useStore.setState({ pairing: null });
});

describe("PairingPanel (slide-over)", () => {
  it("renders 'Checking…' when pairing is null", () => {
    render(<PairingPanel />);
    expect(screen.getByText(/checking/i)).toBeInTheDocument();
  });

  it("renders 'Linked & connected' when the bot is linked and online", () => {
    act(() => {
      useStore.setState({
        pairing: pairingFixture({
          logged_in: true,
          connected: true,
          reachable: true,
        }),
      });
    });
    render(<PairingPanel />);
    expect(screen.getByText(/linked & connected/i)).toBeInTheDocument();
  });

  it("renders 'wabot unreachable' when pairing.reachable is false", () => {
    act(() => {
      useStore.setState({
        pairing: pairingFixture({
          logged_in: false,
          connected: false,
          reachable: false,
        }),
      });
    });
    render(<PairingPanel />);
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument();
  });
});

describe("PairView (public /pair page)", () => {
  it("renders the header and checking state when no pairing data is loaded", () => {
    render(<PairView />);
    // The page-level h1 — distinguishes from the h3 inside PairingQrCard.
    expect(
      screen.getByRole("heading", { level: 1, name: /whatsapp pairing/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/checking/i)).toBeInTheDocument();
  });

  it("shows the connected state when the bot is linked and online", () => {
    act(() => {
      useStore.setState({
        pairing: pairingFixture({
          logged_in: true,
          connected: true,
          reachable: true,
        }),
      });
    });
    render(<PairView />);
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
    expect(
      screen.getByText(/your whatsapp is linked to this bot/i),
    ).toBeInTheDocument();
  });

  it("shows the QR card when a pairing code is available", () => {
    act(() => {
      useStore.setState({
        pairing: pairingFixture({
          qr_available: true,
          logged_in: false,
          connected: false,
          reachable: true,
        }),
      });
    });
    render(<PairView />);
    // PairingQrCard renders an <img alt="WhatsApp pairing QR code"> when available.
    expect(
      screen.getByRole("img", { name: /whatsapp pairing/i }),
    ).toBeInTheDocument();
  });

  it("shows 'wabot unreachable' when reachable is false", () => {
    act(() => {
      useStore.setState({
        pairing: pairingFixture({
          logged_in: false,
          connected: false,
          reachable: false,
        }),
      });
    });
    render(<PairView />);
    expect(screen.getByText(/wabot unreachable/i)).toBeInTheDocument();
  });

  it("renders a footer link back to the full dashboard", () => {
    render(<PairView />);
    const link = screen.getByRole("link", { name: /open full dashboard/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/");
  });
});
