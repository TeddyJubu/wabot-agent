import { useEffect, useState } from "react";
import PairingQrCard from "../tool-cards/PairingQrCard";
import { fetchPairing, type PairingState } from "@/api/pairing";

function describe(state: PairingState | null): string | null {
  if (!state) return null;
  if (state.logged_in) return state.connected ? "Linked & connected" : "Linked";
  if (state.qr_available) return "Ready to pair";
  if (!state.reachable) return "wabot unreachable";
  return "Not linked";
}

export default function PairingPanel() {
  const [state, setState] = useState<PairingState | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchPairing()
      .then((p) => {
        if (!cancelled) setState(p);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const status = describe(state);
  return (
    <div className="space-y-3">
      {status && (
        <p className="text-xs uppercase tracking-wider text-fg-muted">{status}</p>
      )}
      <PairingQrCard
        data={{ available: !!state?.qr_available, linked_device: null }}
        actions={[{ id: "refresh", label: "Refresh", tool: "__pairing_qr", args: {} }]}
        onAction={() => setTick((t) => t + 1)}
      />
      {state?.detail && (
        <p className="rounded-card border border-border bg-bg-app p-3 text-xs text-fg-muted">
          {state.detail}
        </p>
      )}
    </div>
  );
}
