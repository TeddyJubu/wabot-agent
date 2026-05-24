import { create } from "zustand";

export type ToastVariant = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  variant: ToastVariant;
  message: string;
  /** Auto-dismiss delay in ms. 0 disables auto-dismiss. */
  durationMs: number;
}

interface ToastState {
  toasts: ToastItem[];
  push: (variant: ToastVariant, message: string, durationMs?: number) => number;
  dismiss: (id: number) => void;
  clear: () => void;
}

let nextId = 1;
const DEFAULT_DURATION_MS = 4000;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (variant, message, durationMs = DEFAULT_DURATION_MS) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, variant, message, durationMs }] }));
    return id;
  },
  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

/** Hook returning push/dismiss helpers + the current list. */
export function useToast() {
  const toasts = useToastStore((s) => s.toasts);
  const push = useToastStore((s) => s.push);
  const dismiss = useToastStore((s) => s.dismiss);
  return { toasts, push, dismiss };
}
