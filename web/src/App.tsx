import { type KeyboardEvent, useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import SlideOver from "@/components/SlideOver";
import SlashMenu from "@/components/SlashMenu";
import PairingPanel from "@/components/slide-overs/PairingPanel";
import RunsPanel from "@/components/slide-overs/RunsPanel";
import GroupsPanel from "@/components/slide-overs/GroupsPanel";
import SettingsPanel from "@/components/slide-overs/SettingsPanel";
import AgentsPanel from "@/components/slide-overs/AgentsPanel";
import ToolsPanel from "@/components/slide-overs/ToolsPanel";
import { matchSlash } from "@/hooks/useSlashCommands";
import { usePairingStream } from "@/hooks/usePairingStream";
import { fetchSettings } from "@/api/settings";
import { useStore, type SlideOverId } from "@/store";

export default function App() {
  const slideOver = useStore((s) => s.slideOver);
  const close = useStore((s) => s.closeSlideOver);
  const open = useStore((s) => s.openSlideOver);
  const setReadiness = useStore((s) => s.setReadiness);

  const [input, setInput] = useState("");
  const [slashIdx, setSlashIdx] = useState(0);

  const firstToken = input.split(/\s/)[0] ?? "";
  const slashMatches = matchSlash(firstToken);

  // Live pairing — feeds the Zustand pairing slice so PairingPanel re-renders
  // whenever wabot rotates the QR or transitions linked/unlinked.
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
  function dispatchCommand(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setInput("");
    setSlashIdx(0);
    if (trimmed === "__open_knowledge__") {
      window.location.href = "/knowledge";
      return;
    }
    if (trimmed.startsWith("__open_slide_over__:")) {
      const which = trimmed.split(":")[1] as Exclude<SlideOverId, null>;
      if (
        which === "qr" ||
        which === "runs" ||
        which === "settings" ||
        which === "groups" ||
        which === "agents" ||
        which === "tools"
      ) {
        open(which);
      }
    }
  }

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

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <main className="mx-auto flex w-full max-w-[720px] flex-1 flex-col items-center justify-center px-4 pt-16 text-center">
        <p className="text-fg-muted text-sm">
          Use WhatsApp to chat with the bot. Use <kbd>/</kbd> commands below to manage settings.
        </p>
      </main>

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

      <SlideOver open={slideOver === "qr"} onClose={close} title="WhatsApp pairing">
        <PairingPanel />
      </SlideOver>
      <SlideOver open={slideOver === "runs"} onClose={close} title="Recent runs">
        <RunsPanel />
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
    </div>
  );
}
