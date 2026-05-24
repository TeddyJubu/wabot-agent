import { clsx } from "clsx";
import {
  BarChart3,
  Bot,
  BookOpen,
  Home,
  Settings as SettingsIcon,
  Smartphone,
  Wrench,
} from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import { useStore } from "@/store";
import { useRoute, useRouteStore, type Route } from "@/store/route";

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

type RailItem = {
  /** Stable id used as React key and to drive `aria-current`. */
  id: Route;
  label: string;
  icon: IconComponent;
};

type RailGroup = {
  heading: string;
  items: RailItem[];
};

const GROUPS: RailGroup[] = [
  {
    heading: "Run",
    items: [
      { id: "home", label: "Home", icon: Home },
      { id: "pairing", label: "Pairing", icon: Smartphone },
      { id: "insights", label: "Insights", icon: BarChart3 },
    ],
  },
  {
    heading: "Build",
    items: [
      { id: "knowledge", label: "Knowledge", icon: BookOpen },
      { id: "agents", label: "Agents", icon: Bot },
      { id: "capabilities", label: "Capabilities", icon: Wrench },
    ],
  },
  {
    heading: "Connect",
    items: [{ id: "settings", label: "Settings", icon: SettingsIcon }],
  },
];

/**
 * Resolve the click action for a rail item. Some destinations stay in the
 * shell (`setRoute`); others hand off to a separate surface (new tab or
 * full-page nav). Settings (C1), Insights (C2), and Capabilities (C4) ship as
 * full pages and only need a route change. Agents still opens the existing
 * slide-over as a stop-gap until a later epic promotes it to a dedicated
 * page.
 */
function activate(id: Route): void {
  const setRoute = useRouteStore.getState().setRoute;
  const openSlideOver = useStore.getState().openSlideOver;

  switch (id) {
    case "pairing":
      window.open("/pair", "_blank", "noopener");
      return;
    case "knowledge":
      window.location.href = "/knowledge";
      return;
    case "agents":
      setRoute("agents");
      openSlideOver("agents");
      return;
    case "capabilities":
      // C4 promoted Capabilities to a full page; no slide-over hand-off here.
      setRoute("capabilities");
      return;
    case "settings":
      // C1 promoted Settings to a full page; no slide-over hand-off here.
      setRoute("settings");
      return;
    case "home":
    case "insights":
      setRoute(id);
      return;
  }
}

export default function LeftRail() {
  const current = useRoute();

  return (
    <nav
      aria-label="Primary"
      className="sticky top-14 flex h-[calc(100vh-3.5rem)] w-56 shrink-0 flex-col gap-4 overflow-y-auto border-r border-border bg-bg-app/60 p-3"
    >
      {GROUPS.map((group) => (
        <div key={group.heading} className="flex flex-col gap-1">
          <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-fg-muted">
            {group.heading}
          </div>
          {group.items.map((item) => {
            const Icon = item.icon;
            const isActive = current === item.id;
            return (
              <button
                key={item.id}
                type="button"
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
                onClick={() => activate(item.id)}
                className={clsx(
                  "inline-flex min-h-[44px] min-w-[44px] items-center gap-3 rounded-card border-l-2 px-3 py-2 text-left text-sm transition",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  isActive
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-transparent text-fg-muted hover:bg-bg-card hover:text-fg",
                )}
              >
                <Icon aria-hidden="true" className="size-4 shrink-0" />
                <span className="font-medium">{item.label}</span>
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
