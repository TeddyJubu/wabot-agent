import { create } from "zustand";
import type { UiEnvelope } from "@/types/ui-envelope";
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

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  cards?: UiEnvelope[];
}

export type SlideOverId = "qr" | "runs" | "settings" | null;

interface State {
  messages: ChatMessage[];
  readiness: Readiness;
  slideOver: SlideOverId;
  pairing: PairingState | null;

  addUser: (text: string) => string;
  startAssistant: () => string;
  appendDelta: (id: string, delta: string) => void;
  finishAssistant: (id: string) => void;
  attachCard: (id: string, envelope: UiEnvelope) => void;
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
  messages: [],
  slideOver: null,
  pairing: null,
  readiness: {
    overall: "pending",
    model: pendingRow,
    wabot: pendingRow,
    policy: pendingRow,
    memory: pendingRow,
  },

  addUser: (text) => {
    const id = crypto.randomUUID();
    set((s) => ({ messages: [...s.messages, { id, role: "user", text }] }));
    return id;
  },
  startAssistant: () => {
    const id = crypto.randomUUID();
    set((s) => ({
      messages: [...s.messages, { id, role: "assistant", text: "", streaming: true, cards: [] }],
    }));
    return id;
  },
  appendDelta: (id, delta) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, text: m.text + delta } : m)),
    })),
  finishAssistant: (id) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
    })),
  attachCard: (id, envelope) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, cards: [...(m.cards ?? []), envelope] } : m,
      ),
    })),
  openSlideOver: (which) => set({ slideOver: which }),
  closeSlideOver: () => set({ slideOver: null }),
  setReadiness: (r) =>
    set((s) => {
      const next = { ...s.readiness, ...r };
      return { readiness: { ...next, overall: deriveOverall(next) } };
    }),
  setPairing: (p) => set({ pairing: p }),
}));
