import { useEffect, useState } from "react";
import PairingQrCard from "../tool-cards/PairingQrCard";
import { fetchPairing, requestNewPairingQr, type PairingState } from "@/api/pairing";
import { useStore } from "@/store";

function describe(state: PairingState | null): string {
  if (!state) return "Checking…";
  if (state.logged_in) return state.connected ? "Linked & connected" : "Linked";
  if (state.qr_available) return "Ready to pair";
  if (!state.reachable) return "wabot unreachable";
  return "Not linked";
}

function isLinked(state: PairingState | null): boolean {
  return Boolean(state?.logged_in && state.connected);
}

export default function PairingPanel() {
  const state = useStore((s) => s.pairing);
  const setPairing = useStore((s) => s.setPairing);
  const [refreshing, setRefreshing] = useState(false);
  const [requestingQr, setRequestingQr] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetchPairing()
      .then(setPairing)
      .catch(() => undefined);
  }, [setPairing]);

  async function manualRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      setPairing(await fetchPairing());
    } finally {
      setRefreshing(false);
    }
  }

  async function newQr() {
    if (isLinked(state)) {
      setError(
        "WhatsApp is already linked. To pair a different phone, unlink this device in WhatsApp → Linked devices first, then tap New QR.",
      );
      return;
    }
    setRequestingQr(true);
    setError(null);
    try {
      const next = await requestNewPairingQr();
      setPairing(next);
      if (isLinked(next)) {
        setError(null);
      } else if (!next.qr_available) {
        setError(
          "Restarting wabot — the QR should appear within a minute. Keep this panel open.",
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not request a new QR.");
    } finally {
      setRequestingQr(false);
    }
  }

  const status = describe(state);
  const linked = isLinked(state);
  return (
    <div className="space-y-3">
      <p className="text-xs uppercase tracking-wider text-fg-muted">{status}</p>
      {linked ? (
        <div className="rounded-card border border-border bg-bg-card p-6 text-center shadow-sm">
          <div aria-hidden className="mb-2 text-3xl">
            ✓
          </div>
          <p className="text-sm text-fg-muted">Your WhatsApp is linked to this bot.</p>
          <button
            type="button"
            onClick={() => void manualRefresh()}
            className="mt-4 inline-flex items-center gap-1.5 rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
          >
            {refreshing ? "Refreshing…" : "Refresh status"}
          </button>
        </div>
      ) : (
        <PairingQrCard
          data={{
            available: !!state?.qr_available,
            linked_device: state?.logged_in ? "linked (reconnecting?)" : null,
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
            if (id === "new_qr") void newQr();
            else void manualRefresh();
          }}
        />
      )}
      {(error || (!linked && state?.detail)) && (
        <p className="rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {error ?? state?.detail}
        </p>
      )}
    </div>
  );
}
