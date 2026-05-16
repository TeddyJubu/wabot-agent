import type { PairingState } from "@/types/pairing";

export type { PairingState };

export async function fetchPairing(): Promise<PairingState> {
  const res = await fetch("/api/whatsapp/pairing", { credentials: "include" });
  if (!res.ok) {
    return {
      supported: false,
      reachable: false,
      logged_in: null,
      connected: null,
      qr_available: false,
      event: null,
      updated_at: null,
      expires_at: null,
      detail: null,
    };
  }
  return res.json();
}

export interface PairingSubscription {
  close: () => void;
}

/**
 * Open an EventSource to /api/stream and call `onState` whenever a
 * `pairing_changed` event arrives, or when the initial `ready_snapshot`
 * carries a pairing payload.
 *
 * `EventSource` already auto-reconnects on transport errors; the only thing
 * we add is a guard that ignores events after `close()` is called.
 *
 * Returns a handle whose `close()` tears down the EventSource.
 */
export function subscribePairing(
  onState: (s: PairingState) => void,
): PairingSubscription {
  let closed = false;
  const es = new EventSource("/api/stream", { withCredentials: true });

  const handlePairing = (raw: string) => {
    if (closed) return;
    try {
      const data = JSON.parse(raw) as PairingState;
      onState(data);
    } catch {
      // Malformed payload — the next pairing tick will resync.
    }
  };

  es.addEventListener("pairing_changed", (ev) => {
    handlePairing((ev as MessageEvent).data);
  });

  es.addEventListener("ready_snapshot", (ev) => {
    if (closed) return;
    try {
      const data = JSON.parse((ev as MessageEvent).data);
      if (data && data.pairing) onState(data.pairing as PairingState);
    } catch {
      // Ignore malformed snapshots.
    }
  });

  return {
    close: () => {
      closed = true;
      es.close();
    },
  };
}
