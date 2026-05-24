import { useCallback, useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import SlideOver from "@/components/SlideOver";
import StatusBar from "@/components/StatusBar";
import LeftRail from "@/components/LeftRail";
import HomePanel from "@/components/home/HomePanel";
import CommandPalette from "@/components/CommandPalette";
import GroupsPanel from "@/components/slide-overs/GroupsPanel";
import AgentsPanel from "@/components/slide-overs/AgentsPanel";
import CapabilitiesPage from "@/pages/CapabilitiesPage";
import InsightsPage from "@/pages/InsightsPage";
import SettingsPage from "@/pages/SettingsPage";
import { usePairingStream } from "@/hooks/usePairingStream";
import { fetchSettings } from "@/api/settings";
import { useStore, type SlideOverId } from "@/store";
import { useRoute, useRouteStore } from "@/store/route";

export default function App() {
  const slideOver = useStore((s) => s.slideOver);
  const close = useStore((s) => s.closeSlideOver);
  const open = useStore((s) => s.openSlideOver);
  const setReadiness = useStore((s) => s.setReadiness);

  const [paletteOpen, setPaletteOpen] = useState(false);

  // Live pairing — feeds the Zustand pairing slice so the StatusBar and the
  // /pair page re-render whenever wabot rotates the QR or transitions
  // linked/unlinked.
  usePairingStream();

  useEffect(() => {
    fetchSettings()
      .then((v) => {
        setReadiness({
          model: {
            label: v.llm.live ? `${v.llm.provider}` : "offline",
            variant: v.llm.live ? "ok" : "warn",
          },
          wabot: {
            label: v.wabot.endpoint ? "configured" : "missing",
            variant: v.wabot.endpoint ? "ok" : "warn",
          },
          policy: {
            label: v.send_policy,
            variant: v.send_policy === "allow_all" ? "warn" : "ok",
          },
          memory: { label: "ready", variant: "ok" },
        });
      })
      .catch(() => {
        setReadiness({
          model: { label: "unknown", variant: "warn" },
          wabot: { label: "unknown", variant: "warn" },
          policy: { label: "unknown", variant: "warn" },
          memory: { label: "unknown", variant: "warn" },
        });
      });
  }, [setReadiness]);

  const route = useRoute();

  /**
   * Resolve a CommandPalette / slash sentinel to its destination. Settings,
   * Insights, and Capabilities are full pages now (C1/C2/C4) — the legacy
   * `__open_slide_over__:{settings,overview,runs,tools,integrations}`
   * sentinels still arrive from the SLASH_COMMANDS table for muscle-memory
   * users, so we translate them into route changes. Agents and Groups stay
   * as slide-overs until they get their own pages, so those sentinels still
   * call `openSlideOver(which)` directly.
   */
  const dispatchCommand = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      if (trimmed === "__open_knowledge__") {
        window.location.href = "/knowledge";
        return;
      }
      if (trimmed === "__open_pair__") {
        window.open("/pair", "_blank", "noopener");
        return;
      }
      if (trimmed.startsWith("__open_slide_over__:")) {
        const which = trimmed.split(":")[1] as Exclude<SlideOverId, null>;
        const setRoute = useRouteStore.getState().setRoute;
        if (which === "settings") {
          setRoute("settings");
          return;
        }
        if (which === "overview" || which === "runs") {
          setRoute("insights");
          return;
        }
        if (which === "tools" || which === "integrations") {
          setRoute("capabilities");
          return;
        }
        if (which === "agents") {
          // Agents stays a slide-over for now; the route→openSlideOver effect
          // below picks it up so LeftRail's aria-current="page" stays honest.
          setRoute("agents");
          return;
        }
        if (which === "groups") {
          open("groups");
        }
      }
    },
    [open],
  );

  // Global keybindings for the command palette — Cmd-K / Ctrl-K always opens
  // it; "/" opens it ONLY when nothing typeable is focused (so it doesn't
  // hijack typing inside a text field).
  useEffect(() => {
    function isTypingTarget(): boolean {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      if (el.isContentEditable) return true;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA";
    }
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
        return;
      }
      if (e.key === "/" && !isTypingTarget()) {
        e.preventDefault();
        setPaletteOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // When the rail picks a destination that's still a slide-over (Agents is
  // the last hold-out — Settings shipped in C1, Insights in C2, Capabilities
  // in C4), open the slide-over so a programmatic route change keeps the
  // panel in sync.
  useEffect(() => {
    if (route === "agents") open("agents");
  }, [route, open]);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <div className="flex flex-1">
        <LeftRail />
        <main className="flex-1 px-6 py-8">
          <div className="mb-6">
            <StatusBar />
          </div>
          {route === "home" && <HomePanel />}
          {route === "insights" && <InsightsPage />}
          {route === "capabilities" && <CapabilitiesPage />}
          {route === "settings" && <SettingsPage />}
          {route === "agents" && (
            <div className="text-fg-muted text-sm">
              Opening agents — full page lands in a later epic.
            </div>
          )}
        </main>
      </div>

      {/* Slide-overs that don't yet have their own page: Groups + Agents. */}
      <SlideOver open={slideOver === "groups"} onClose={close} title="WhatsApp groups">
        <GroupsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "agents"} onClose={close} title="Agents">
        <AgentsPanel />
      </SlideOver>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onDispatch={dispatchCommand}
      />
    </div>
  );
}
