import { type KeyboardEvent, useCallback, useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import SlideOver from "@/components/SlideOver";
import SlashMenu from "@/components/SlashMenu";
import StatusBar from "@/components/StatusBar";
import LeftRail from "@/components/LeftRail";
import HomePanel from "@/components/home/HomePanel";
import CommandPalette from "@/components/CommandPalette";
import ActivityPanel from "@/components/slide-overs/ActivityPanel";
import OverviewPanel from "@/components/slide-overs/OverviewPanel";
import GroupsPanel from "@/components/slide-overs/GroupsPanel";
import SettingsPanel from "@/components/slide-overs/SettingsPanel";
import AgentsPanel from "@/components/slide-overs/AgentsPanel";
import ToolsPanel from "@/components/slide-overs/ToolsPanel";
import IntegrationsPanel from "@/components/slide-overs/IntegrationsPanel";
import { matchSlash } from "@/hooks/useSlashCommands";
import { usePairingStream } from "@/hooks/usePairingStream";
import { fetchSettings } from "@/api/settings";
import { useStore, type SlideOverId } from "@/store";
import { useUiFlag } from "@/store/uiFlag";
import { useRoute } from "@/store/route";

export default function App() {
  const slideOver = useStore((s) => s.slideOver);
  const close = useStore((s) => s.closeSlideOver);
  const open = useStore((s) => s.openSlideOver);
  const setReadiness = useStore((s) => s.setReadiness);

  const [input, setInput] = useState("");
  const [slashIdx, setSlashIdx] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const firstToken = input.split(/\s/)[0] ?? "";
  const slashMatches = matchSlash(firstToken);

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

  // Slash-command dispatch — resolves navigation targets (slide-overs, pages).
  // The dashboard is now status + slash-commands + slide-overs only; the in-dashboard
  // chat composer was removed in Phase 6 per plan.md P2. WhatsApp is the canonical
  // operator interface.
  const dispatchCommand = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setInput("");
      setSlashIdx(0);
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
        if (
          which === "runs" ||
          which === "settings" ||
          which === "groups" ||
          which === "agents" ||
          which === "tools" ||
          which === "integrations" ||
          which === "overview"
        ) {
          open(which);
        }
      }
    },
    [open],
  );

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (slashMatches.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIdx((i) => Math.min(i + 1, slashMatches.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIdx((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Tab" || e.key === "Enter") {
        e.preventDefault();
        const cmd = slashMatches[slashIdx];
        if (cmd) dispatchCommand(cmd.expand());
        return;
      }
    }
    if (e.key === "Enter") {
      e.preventDefault();
      dispatchCommand(input);
    }
  }

  const uiV2 = useUiFlag();
  const route = useRoute();

  // Global keybindings for the command palette — Cmd-K / Ctrl-K always opens
  // it; "/" opens it ONLY when nothing typeable is focused (so it doesn't
  // hijack typing inside the bottom slash input under flag-off, or any other
  // text field). The handler runs in capture-free bubble mode so individual
  // inputs can still intercept these keys if they need to.
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

  // When the v2 rail picks a destination that's really a slide-over (until
  // C1/C4 ship full pages for them), open it via the existing store action.
  // LeftRail already calls openSlideOver on click; this effect keeps the
  // slide-over in sync if the route is changed programmatically (e.g. by a
  // future command palette dispatch).
  useEffect(() => {
    if (!uiV2) return;
    if (route === "agents") open("agents");
    else if (route === "capabilities") open("tools");
    else if (route === "settings") open("settings");
  }, [uiV2, route, open]);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      {uiV2 ? (
        <div className="flex flex-1">
          <LeftRail />
          <main className="flex-1 px-6 py-8">
            <div className="mb-6">
              <StatusBar />
            </div>
            {route === "home" && <HomePanel />}
            {route === "insights" && <OverviewPanel />}
            {(route === "agents" ||
              route === "capabilities" ||
              route === "settings") && (
              <div className="text-fg-muted text-sm">
                Opening {route} — full page lands in Phase C.
              </div>
            )}
          </main>
        </div>
      ) : (
        <main className="mx-auto flex w-full max-w-[720px] flex-1 flex-col items-center justify-center px-4 pt-16 text-center">
          <p className="text-fg-muted text-sm">
            Use WhatsApp to chat with the bot. Use <kbd>/</kbd> commands below to manage settings.
          </p>
        </main>
      )}

      {!uiV2 && (
        <div className="fixed bottom-0 left-1/2 w-full max-w-[720px] -translate-x-1/2 px-4 pb-4">
          <div className="relative">
            {slashMatches.length > 0 && (
              <SlashMenu
                commands={slashMatches}
                activeIdx={slashIdx}
                onPick={(c) => dispatchCommand(c.expand())}
              />
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                dispatchCommand(input);
              }}
              className="relative rounded-card border border-border bg-bg-card p-2 shadow-sm transition focus-within:border-accent/40"
            >
              <input
                type="text"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  setSlashIdx(0);
                }}
                onKeyDown={onKey}
                placeholder="Type / for commands"
                className="block w-full rounded-card bg-transparent px-3 py-2 text-sm placeholder:text-fg-muted focus:outline-none"
              />
            </form>
          </div>
        </div>
      )}

      <SlideOver open={slideOver === "runs"} onClose={close} title="Activity">
        <ActivityPanel />
      </SlideOver>
      <SlideOver open={slideOver === "overview"} onClose={close} title="Overview">
        <OverviewPanel />
      </SlideOver>
      <SlideOver open={slideOver === "groups"} onClose={close} title="WhatsApp groups">
        <GroupsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "settings"} onClose={close} title="Settings">
        <SettingsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "agents"} onClose={close} title="Agents">
        <AgentsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "tools"} onClose={close} title="Tools">
        <ToolsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "integrations"} onClose={close} title="Integrations">
        <IntegrationsPanel />
      </SlideOver>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onDispatch={dispatchCommand}
      />
    </div>
  );
}
