import { type KeyboardEvent, useEffect, useState } from "react";
import {
  Conversation,
  Message,
  MessageContent,
} from "@/components/ai-elements/conversation";
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import TopBar from "@/components/TopBar";
import SlideOver from "@/components/SlideOver";
import EmptyState from "@/components/EmptyState";
import SlashMenu from "@/components/SlashMenu";
import ToolCard from "@/components/tool-cards/ToolCard";
import PairingPanel from "@/components/slide-overs/PairingPanel";
import RunsPanel from "@/components/slide-overs/RunsPanel";
import SettingsPanel from "@/components/slide-overs/SettingsPanel";
import { matchSlash } from "@/hooks/useSlashCommands";
import { postChatStream } from "@/api/chat";
import { fetchSettings } from "@/api/settings";
import { useStore, type SlideOverId } from "@/store";

export default function App() {
  const messages = useStore((s) => s.messages);
  const addUser = useStore((s) => s.addUser);
  const startAssistant = useStore((s) => s.startAssistant);
  const appendDelta = useStore((s) => s.appendDelta);
  const finishAssistant = useStore((s) => s.finishAssistant);
  const attachCard = useStore((s) => s.attachCard);
  const slideOver = useStore((s) => s.slideOver);
  const close = useStore((s) => s.closeSlideOver);
  const open = useStore((s) => s.openSlideOver);
  const setReadiness = useStore((s) => s.setReadiness);

  const [input, setInput] = useState("");
  const [slashIdx, setSlashIdx] = useState(0);
  const [pending, setPending] = useState(false);

  const firstToken = input.split(/\s/)[0] ?? "";
  const slashMatches = matchSlash(firstToken);

  useEffect(() => {
    fetchSettings()
      .then((v) => {
        setReadiness({
          model: {
            label: v.openrouter.api_key.set ? "configured" : "offline",
            variant: v.openrouter.api_key.set ? "ok" : "warn",
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

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setInput("");
    setSlashIdx(0);
    if (trimmed.startsWith("__open_slide_over__:")) {
      const which = trimmed.split(":")[1] as Exclude<SlideOverId, null>;
      if (which === "qr" || which === "runs" || which === "settings") open(which);
      return;
    }
    addUser(trimmed);
    setPending(true);
    let assistantId: string | null = null;
    let deltaSeen = false;
    const ensureAssistant = () => {
      if (assistantId == null) assistantId = startAssistant();
      return assistantId;
    };
    try {
      await postChatStream(trimmed, {
        onEvent: (e) => {
          if (e.type === "delta") {
            deltaSeen = true;
            appendDelta(ensureAssistant(), e.text);
          } else if (e.type === "tool_result" && e.ui) {
            attachCard(ensureAssistant(), e.ui);
          } else if (e.type === "final") {
            const id = ensureAssistant();
            if (!deltaSeen && e.output) appendDelta(id, e.output);
            finishAssistant(id);
          } else if (e.type === "error") {
            const id = ensureAssistant();
            appendDelta(id, `\n\n[error: ${e.message}]`);
            finishAssistant(id);
          }
        },
      });
    } catch (err) {
      const id = ensureAssistant();
      appendDelta(id, `\n\n[network error: ${String(err)}]`);
      finishAssistant(id);
    } finally {
      if (assistantId != null) finishAssistant(assistantId);
      setPending(false);
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
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
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && !(e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        const cmd = slashMatches[slashIdx];
        if (cmd) void submit(cmd.expand());
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void submit(input);
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <main className="mx-auto flex w-full max-w-[720px] flex-1 flex-col px-4 pb-40 pt-6">
        {messages.length === 0 ? (
          <EmptyState onPick={(t) => void submit(t)} />
        ) : (
          <Conversation>
            {messages.map((m) => (
              <Message key={m.id} from={m.role}>
                <MessageContent role={m.role}>
                  <p className={m.streaming && !m.text ? "shimmer text-fg-muted" : undefined}>
                    {m.text || (m.streaming ? "thinking…" : "")}
                  </p>
                </MessageContent>
                {m.cards && m.cards.length > 0 && (
                  <div className="mt-2 space-y-2">
                    {m.cards.map((env, idx) => (
                      <ToolCard
                        key={idx}
                        envelope={env}
                        onAction={(actionId) => {
                          if (env.kind === "send_confirm" && actionId === "approve") {
                            void submit("approved");
                          } else if (env.kind === "send_confirm" && actionId === "cancel") {
                            void submit("cancel — do not send");
                          } else if (env.kind === "wabot_status" && actionId === "recheck") {
                            void submit("recheck wabot health");
                          }
                        }}
                      />
                    ))}
                  </div>
                )}
              </Message>
            ))}
          </Conversation>
        )}
      </main>

      <div className="fixed bottom-0 left-1/2 w-full max-w-[720px] -translate-x-1/2 px-4 pb-4">
        <div className="relative">
          {slashMatches.length > 0 && (
            <SlashMenu
              commands={slashMatches}
              activeIdx={slashIdx}
              onPick={(c) => void submit(c.expand())}
            />
          )}
          <PromptInput
            onSubmit={(e) => {
              e.preventDefault();
              void submit(input);
            }}
          >
            <PromptInputTextarea
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setSlashIdx(0);
              }}
              onKeyDown={onKey}
              placeholder="Message wabot-agent…  /  for commands   ⌘↵ to send"
              disabled={pending}
            />
            <PromptInputSubmit disabled={!input.trim() || pending} />
          </PromptInput>
        </div>
      </div>

      <SlideOver open={slideOver === "qr"} onClose={close} title="WhatsApp pairing">
        <PairingPanel />
      </SlideOver>
      <SlideOver open={slideOver === "runs"} onClose={close} title="Recent runs">
        <RunsPanel />
      </SlideOver>
      <SlideOver open={slideOver === "settings"} onClose={close} title="Settings">
        <SettingsPanel />
      </SlideOver>
    </div>
  );
}
