import { create } from "zustand";

/**
 * Top-level destinations for the v2 navigation shell.
 *
 * - "pairing" and "knowledge" are *navigation* targets: picking them in the
 *   LeftRail hands off to the browser (new tab / full-page nav) instead of
 *   mutating this store. They are still listed in the union so the rail can
 *   present them as siblings of in-shell routes.
 * - "agents", "capabilities", and "settings" temporarily open the matching
 *   slide-over until C1/C4 promote them to real pages.
 */
export type Route =
  | "home"
  | "pairing"
  | "insights"
  | "knowledge"
  | "agents"
  | "capabilities"
  | "settings";

interface RouteState {
  route: Route;
  setRoute: (r: Route) => void;
}

export const useRouteStore = create<RouteState>((set) => ({
  route: "home",
  setRoute: (route) => set({ route }),
}));

/** Convenience hook — returns the current top-level route. */
export function useRoute(): Route {
  return useRouteStore((s) => s.route);
}
