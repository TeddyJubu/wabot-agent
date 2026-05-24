import { create } from "zustand";

interface UiFlagState {
  v2: boolean;
  setUiFlag: (value: boolean) => void;
  resetUiFlagFromUrl: () => void;
}

function readV2FromUrl(): boolean {
  if (typeof window === "undefined") return false;
  const params = new URLSearchParams(window.location.search);
  return params.get("ui") === "v2";
}

export const useUiFlagStore = create<UiFlagState>((set) => ({
  v2: readV2FromUrl(),
  setUiFlag: (value) => set({ v2: value }),
  resetUiFlagFromUrl: () => set({ v2: readV2FromUrl() }),
}));

/** Convenience hook — returns true when the URL has `?ui=v2`. */
export function useUiFlag(): boolean {
  return useUiFlagStore((s) => s.v2);
}
