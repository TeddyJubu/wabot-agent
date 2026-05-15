import { useEffect } from "react";
import { subscribePairing } from "@/api/pairing";
import { useStore } from "@/store";

/**
 * Mount once at the top of the app shell (or the PairView). Opens a single
 * EventSource and feeds `pairing_changed` updates into the Zustand pairing
 * slice. All consumers read via `useStore((s) => s.pairing)`.
 *
 * Safe to call from multiple components in the same React tree: each instance
 * opens its own EventSource. In practice we call it once — at the top of
 * `App` for the dashboard, and once at the top of `PairView` for `/pair`.
 */
export function usePairingStream(): void {
  const setPairing = useStore((s) => s.setPairing);

  useEffect(() => {
    const sub = subscribePairing(setPairing);
    return () => sub.close();
  }, [setPairing]);
}
