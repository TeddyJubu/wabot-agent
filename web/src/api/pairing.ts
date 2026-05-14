export interface PairingState {
  qr_available: boolean;
  logged_in: boolean | null;
  connected: boolean | null;
  reachable: boolean;
  detail?: string | null;
}

export async function fetchPairing(): Promise<PairingState> {
  const res = await fetch("/api/whatsapp/pairing", { credentials: "include" });
  if (!res.ok) {
    return { qr_available: false, logged_in: null, connected: null, reachable: false };
  }
  return res.json();
}
