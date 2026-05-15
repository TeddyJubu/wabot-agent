import { useState } from "react";
import PairingQrCard from "../tool-cards/PairingQrCard";
import { fetchPairing, type PairingState } from "@/api/pairing";
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

  async function manualRefresh() {
    setRefreshing(true);
    try {
      const p = await fetchPairing();
      setPairing(p);
    } finally {
      setRefreshing(false);
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
            id: "refresh",
            label: refreshing ? "Refreshing…" : "Refresh",
            tool: "__pairing_qr",
            args: {},
          },
        ]}
        onAction={() => {
          void manualRefresh();
        }}
      />
      {state?.detail && (
        <p className="rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {state.detail}
        </p>
      )}
    </div>
  );
}
