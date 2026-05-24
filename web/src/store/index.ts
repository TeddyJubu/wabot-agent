import { create } from "zustand";
import type { PairingState } from "@/api/pairing";

export type ReadinessVariant = "ok" | "warn" | "bad" | "pending";

export interface ReadinessRow {
  label: string;
  variant: ReadinessVariant;
}

export interface Readiness {
  overall: ReadinessVariant;
  model: ReadinessRow;
  wabot: ReadinessRow;
  policy: ReadinessRow;
  memory: ReadinessRow;
}

export type SlideOverId = "qr" | "runs" | "groups" | "settings" | "agents" | "tools" | "integrations" | "overview" | null;

interface State {
  readiness: Readiness;
  slideOver: SlideOverId;
  pairing: PairingState | null;

  openSlideOver: (which: Exclude<SlideOverId, null>) => void;
  closeSlideOver: () => void;
  setReadiness: (r: Partial<Readiness>) => void;
  setPairing: (p: PairingState | null) => void;
}

const pendingRow: ReadinessRow = { label: "Checking…", variant: "pending" };

function deriveOverall(r: Readiness): ReadinessVariant {
  const rows = [r.model, r.wabot, r.policy, r.memory];
  if (rows.some((x) => x.variant === "bad")) return "bad";
  if (rows.some((x) => x.variant === "warn" || x.variant === "pending")) return "warn";
  return "ok";
}

export const useStore = create<State>((set) => ({
  slideOver: null,
  pairing: null,
  readiness: {
    overall: "pending",
    model: pendingRow,
    wabot: pendingRow,
    policy: pendingRow,
    memory: pendingRow,
  },

  openSlideOver: (which) => set({ slideOver: which }),
  closeSlideOver: () => set({ slideOver: null }),
  setReadiness: (r) =>
    set((s) => {
      const next = { ...s.readiness, ...r };
      return { readiness: { ...next, overall: deriveOverall(next) } };
    }),
  setPairing: (p) => set({ pairing: p }),
}));
