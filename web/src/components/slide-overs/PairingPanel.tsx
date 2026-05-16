import { useState } from "react";
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

export default function PairingPanel() {
  const state = useStore((s) => s.pairing);
  const setPairing = useStore((s) => s.setPairing);
  const [refreshing, setRefreshing] = useState(false);
  const [requestingQr, setRequestingQr] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setRequestingQr(true);
    setError(null);
    try {
      setPairing(await requestNewPairingQr());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not request a new QR.");
    } finally {
      setRequestingQr(false);
    }
  }

  const status = describe(state);
  return (
    <div className="space-y-3">
      <p className="text-xs uppercase tracking-wider text-fg-muted">{status}</p>
      <PairingQrCard
        data={{ available: !!state?.qr_available, linked_device: null }}
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
      {(error || state?.detail) && (
        <p className="rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {error ?? state?.detail}
        </p>
      )}
    </div>
  );
}
