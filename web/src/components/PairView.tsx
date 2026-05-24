import { useEffect, useState } from "react";
import { useStore } from "@/store";
import { usePairingStream } from "@/hooks/usePairingStream";
import { ClerkNavAuth } from "@/components/ClerkNavAuth";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import PairingQrCard from "@/components/tool-cards/PairingQrCard";
import {
  disconnectWhatsappConnection,
  fetchPairing,
  requestNewPairingQr,
} from "@/api/pairing";
import type { PairingState } from "@/api/pairing";

function statusText(p: PairingState | null): string {
  if (!p) return "Checking…";
  if (p.logged_in) return p.connected ? "Connected" : "Linked (offline)";
  if (p.qr_available) return "Scan to connect";
  if (!p.reachable) return "wabot unreachable";
  return "Not linked";
}

function statusClass(p: PairingState | null): string {
  if (!p) return "text-fg-muted";
  if (p.logged_in && p.connected) return "text-ok";
  if (!p.reachable) return "text-warn";
  return "text-fg-muted";
}

/**
 * Public, mobile-first WhatsApp pairing page rendered at /pair.
 *
 * Subscribes to /api/stream via `usePairingStream` so the QR re-renders
 * instantly when wabot rotates the pairing code. Reuses the dashboard's
 * PairingQrCard for visual consistency.
 */
export default function PairView() {
  usePairingStream();
  const pairing = useStore((s) => s.pairing);
  const setPairing = useStore((s) => s.setPairing);
  const [refreshing, setRefreshing] = useState(false);
  const [requestingQr, setRequestingQr] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDisconnectOpen, setConfirmDisconnectOpen] = useState(false);

  function runDisconnect() {
    setDisconnecting(true);
    setError(null);
    void disconnectWhatsappConnection()
      .then((state) => {
        setPairing(state);
        if (!state.qr_available) {
          setError("WhatsApp was disconnected. A new QR should appear within a minute.");
        }
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not disconnect WhatsApp."),
      )
      .finally(() => setDisconnecting(false));
  }

  useEffect(() => {
    if (pairing?.logged_in || pairing?.qr_available) return;
    const id = window.setInterval(() => {
      void fetchPairing().then(setPairing).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(id);
  }, [pairing?.logged_in, pairing?.qr_available, setPairing]);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-[480px] flex-col px-4 py-8">
      <div className="mb-4 flex justify-end">
        <ClerkNavAuth />
      </div>
      <header className="mb-6 space-y-1 text-center">
        <h1 className="text-xl font-semibold tracking-tight">WhatsApp pairing</h1>
        <p className={`text-sm ${statusClass(pairing)}`}>{statusText(pairing)}</p>
      </header>

      <div>
        {pairing?.logged_in ? (
          <div className="rounded-card border border-border bg-bg-card p-6 text-center shadow-sm">
            <div aria-hidden className="mb-2 text-3xl">✓</div>
            <p className="text-sm text-fg-muted">
              Your WhatsApp is linked to this bot.
            </p>
            <button
              type="button"
              disabled={disconnecting}
              className="mt-4 inline-flex items-center gap-1.5 rounded-pill border border-bad/40 px-2.5 py-1 text-xs text-bad hover:bg-bad/10 disabled:opacity-50"
              onClick={() => setConfirmDisconnectOpen(true)}
            >
              {disconnecting ? "Disconnecting…" : "Disconnect WhatsApp"}
            </button>
          </div>
        ) : (
          <PairingQrCard
            data={{
              available: !!pairing?.qr_available,
              linked_device: null,
            }}
            actions={[
              {
                id: "new_qr",
                label: requestingQr ? "Starting…" : "New QR",
                tool: "__pairing_qr",
                args: {},
              },
              {
                id: "refresh",
                label: refreshing ? "Refreshing…" : "Refresh",
                tool: "__pairing_qr",
                args: {},
              },
            ]}
            onAction={(id) => {
              if (id === "new_qr") {
                setRequestingQr(true);
                setError(null);
                void requestNewPairingQr()
                  .then((state) => {
                    setPairing(state);
                    if (!state.qr_available) {
                      setError(
                        "Restarting wabot — the QR should appear within a minute. Keep this page open.",
                      );
                    }
                  })
                  .catch((err) =>
                    setError(err instanceof Error ? err.message : "Could not request a new QR."),
                  )
                  .finally(() => setRequestingQr(false));
                return;
              }
              setRefreshing(true);
              setError(null);
              void fetchPairing()
                .then(setPairing)
                .finally(() => setRefreshing(false));
            }}
          />
        )}
      </div>

      {(error || pairing?.detail) && (
        <p className="mt-3 rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {error ?? pairing?.detail}
        </p>
      )}

      <footer className="mt-auto pt-8 text-center text-xs text-fg-muted">
        <a href="/" className="underline hover:text-fg">
          Open full dashboard
        </a>
      </footer>

      <ConfirmDialog
        open={confirmDisconnectOpen}
        title="Disconnect WhatsApp?"
        description="This logs the current account out of the wabot daemon. You'll need to scan a new QR before the bot can send or reply again."
        confirmLabel="Disconnect"
        variant="danger"
        onConfirm={() => {
          setConfirmDisconnectOpen(false);
          runDisconnect();
        }}
        onCancel={() => setConfirmDisconnectOpen(false)}
      />
    </div>
  );
}
