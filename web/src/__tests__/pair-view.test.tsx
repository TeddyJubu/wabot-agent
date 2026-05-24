import { describe, expect, it, beforeEach, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import PairView from "@/components/PairView";
import { useStore } from "@/store";
import { disconnectWhatsappConnection } from "@/api/pairing";

vi.mock("@/api/pairing", () => ({
  fetchPairing: vi.fn().mockRejectedValue(new Error("not mocked")),
  requestNewPairingQr: vi.fn(),
  disconnectWhatsappConnection: vi.fn(),
  subscribePairing: vi.fn(() => ({ close: vi.fn() })),
}));

vi.mock("@/components/ClerkNavAuth", () => ({
  ClerkNavAuth: () => <div data-testid="clerk-nav-auth" />,
}));

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
  vi.clearAllMocks();
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
        pairing: {
          qr_available: false,
          logged_in: true,
          connected: true,
          reachable: true,
        },
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
        pairing: {
          qr_available: true,
          logged_in: false,
          connected: false,
          reachable: true,
        },
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
        pairing: {
          qr_available: false,
          logged_in: false,
          connected: false,
          reachable: false,
        },
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

  it("can disconnect the linked WhatsApp account", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(disconnectWhatsappConnection).mockResolvedValue({
      qr_available: true,
      logged_in: false,
      connected: true,
      reachable: true,
    });
    act(() => {
      useStore.setState({
        pairing: {
          qr_available: false,
          logged_in: true,
          connected: true,
          reachable: true,
        },
      });
    });
    render(<PairView />);

    fireEvent.click(screen.getByRole("button", { name: /disconnect whatsapp/i }));

    await waitFor(() => expect(disconnectWhatsappConnection).toHaveBeenCalledTimes(1));
    expect(useStore.getState().pairing?.qr_available).toBe(true);
  });
});
