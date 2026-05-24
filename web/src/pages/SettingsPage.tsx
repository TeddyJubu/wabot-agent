import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  fetchSettings,
  patchSettings,
  type ModelProvider,
  type SettingsView,
} from "@/api/settings";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { HelpPopover } from "@/components/HelpPopover";
import { CodexSection } from "@/components/slide-overs/settings/CodexSection";
import { ModelRoutingSection } from "@/components/slide-overs/settings/ModelRoutingSection";
import { OllamaSection } from "@/components/slide-overs/settings/OllamaSection";
import { OpenAISection } from "@/components/slide-overs/settings/OpenAISection";
import { OpenRouterSection } from "@/components/slide-overs/settings/OpenRouterSection";
import { PolicySection } from "@/components/slide-overs/settings/PolicySection";
import { WabotSection } from "@/components/slide-overs/settings/WabotSection";

type Policy = "dry_run" | "allowlist" | "allow_all" | "owner";

type TabId = "provider" | "routing" | "wabot" | "policy" | "experimental";

interface TabSpec {
  id: TabId;
  label: string;
}

const TABS: readonly TabSpec[] = [
  { id: "provider", label: "Provider" },
  { id: "routing", label: "Routing" },
  { id: "wabot", label: "Wabot" },
  { id: "policy", label: "Policy" },
  { id: "experimental", label: "Experimental" },
];

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  openai: "OpenAI API",
  codex: "ChatGPT / Codex",
  openrouter: "OpenRouter",
  ollama: "Ollama (local)",
  ollama_cloud: "Ollama Cloud",
};

interface TabButtonProps {
  tab: TabSpec;
  isActive: boolean;
  onClick: () => void;
  buttonRef: (el: HTMLButtonElement | null) => void;
}

function TabButton({ tab, isActive, onClick, buttonRef }: TabButtonProps) {
  return (
    <button
      ref={buttonRef}
      type="button"
      role="tab"
      id={`settings-tab-${tab.id}`}
      aria-selected={isActive}
      aria-controls={`settings-panel-${tab.id}`}
      tabIndex={isActive ? 0 : -1}
      onClick={onClick}
      className={`px-4 py-3 min-h-[44px] text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        isActive
          ? "border-b-2 border-accent text-accent"
          : "text-fg-muted hover:text-fg"
      }`}
    >
      {tab.label}
    </button>
  );
}

interface SaveFooterProps {
  status: string;
}

function SaveFooter({ status }: SaveFooterProps) {
  return (
    <div className="sticky bottom-0 mt-6 flex items-center justify-between border-t border-border bg-bg-app/95 py-3 backdrop-blur">
      <span className="text-xs text-fg-muted">{status}</span>
      <button
        type="submit"
        className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg transition hover:opacity-90"
      >
        Save changes
      </button>
    </div>
  );
}

/**
 * Full-page Settings view shipped in Epic C1. Replaces the legacy
 * SettingsPanel slide-over for users running under `?ui=v2`. Hosts a five-tab
 * sub-nav (Provider / Routing / Wabot / Policy / Experimental) on top of one
 * shared form so Save still commits everything at once. The slide-over
 * version of SettingsPanel is retained for flag-off users through the
 * one-release deprecation window.
 */
export default function SettingsPage() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [provider, setProvider] = useState<ModelProvider>("codex");
  const [policy, setPolicy] = useState<Policy>("dry_run");
  const [recipients, setRecipients] = useState("");
  const [owners, setOwners] = useState("");
  const [subagentsEnabled, setSubagentsEnabled] = useState(false);
  const [status, setStatus] = useState("");
  const [activeTab, setActiveTab] = useState<TabId>("provider");
  const [pendingTab, setPendingTab] = useState<TabId | null>(null);

  // Roving tab-index pattern needs refs per-tab so ArrowLeft/ArrowRight can
  // shift focus when the active tab changes.
  const tabRefs = useRef<Record<TabId, HTMLButtonElement | null>>({
    provider: null,
    routing: null,
    wabot: null,
    policy: null,
    experimental: null,
  });
  // Tracks whether the user just used the keyboard to change the active tab —
  // we only steal focus in that case so a mouse click doesn't yank focus away.
  const focusAfterChange = useRef(false);

  /**
   * Snap the controlled form fields back to the server's truth. After a save
   * we re-fetch and call this so every dirty-comparison field starts fresh —
   * not just provider + subagents. Without it, the server's normalisation of
   * recipients/owners ("a,b" → "a, b") leaves `isDirty` stuck true even
   * though the save succeeded.
   */
  const resetDraftFromView = useCallback((v: SettingsView) => {
    setProvider(v.llm.provider);
    setPolicy(v.send_policy);
    setRecipients(v.allowed_recipients.join(", "));
    setOwners(v.owner_numbers.join(", "));
    setSubagentsEnabled(v.subagents_enabled ?? false);
    setDraft({});
  }, []);

  useEffect(() => {
    fetchSettings()
      .then((v) => {
        setView(v);
        resetDraftFromView(v);
      })
      .catch((err) => setStatus(`Couldn't load: ${String(err)}`));
  }, [resetDraftFromView]);

  useEffect(() => {
    if (!focusAfterChange.current) return;
    focusAfterChange.current = false;
    tabRefs.current[activeTab]?.focus();
  }, [activeTab]);

  const isDirty = useMemo(() => {
    if (!view) return false;
    if (provider !== view.llm.provider) return true;
    if (policy !== view.send_policy) return true;
    if (recipients !== view.allowed_recipients.join(", ")) return true;
    if (owners !== view.owner_numbers.join(", ")) return true;
    if (subagentsEnabled !== (view.subagents_enabled ?? false)) return true;
    if (Object.values(draft).some((v) => v !== "")) return true;
    return false;
  }, [view, provider, policy, recipients, owners, subagentsEnabled, draft]);

  if (!view) {
    return <p className="text-xs text-fg-muted">{status || "Loading…"}</p>;
  }

  const refetchSettings = () => {
    void fetchSettings()
      .then((next) => {
        setView(next);
        resetDraftFromView(next);
      })
      .catch((err) => setStatus(`Couldn't refresh: ${String(err)}`));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus("Saving…");
    const body: Record<string, unknown> = {};
    if (provider !== view.llm.provider) {
      body.model_provider = provider;
    }
    if (policy !== view.send_policy) {
      body.send_policy = policy;
      if (policy === "allow_all") body.confirm_allow_all = true;
    }
    if (recipients !== view.allowed_recipients.join(", ")) {
      body.allowed_recipients = recipients
        .split(/[,\n]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    }
    if (owners !== view.owner_numbers.join(", ")) {
      body.owner_numbers = owners
        .split(/[,\n]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    }
    if (subagentsEnabled !== (view.subagents_enabled ?? false)) {
      body.subagents_enabled = subagentsEnabled;
    }
    for (const [key, value] of Object.entries(draft)) {
      if (value !== "") body[key] = value;
    }
    try {
      await patchSettings(body);
      setStatus("Saved.");
      const next = await fetchSettings();
      setView(next);
      // Re-derive EVERY form field from the new server view so isDirty
      // settles to false (matches CodeRabbit finding #9). Without this,
      // server-normalised strings like recipients leave isDirty stuck true.
      resetDraftFromView(next);
    } catch (err) {
      setStatus(`Error: ${String(err)}`);
    }
  };

  const requestTab = (next: TabId) => {
    if (next === activeTab) return;
    if (!isDirty) {
      setActiveTab(next);
      return;
    }
    setPendingTab(next);
  };

  const confirmDiscard = () => {
    if (!pendingTab) return;
    resetDraftFromView(view);
    setActiveTab(pendingTab);
    setPendingTab(null);
  };

  const cancelDiscard = () => {
    setPendingTab(null);
  };

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const currentIdx = TABS.findIndex((t) => t.id === activeTab);
    if (currentIdx < 0) return;
    // ArrowLeft from the first tab wraps to the last; ArrowRight from the last
    // tab wraps to the first. Standard WAI-ARIA Authoring Practices roving
    // tablist pattern.
    const nextIdx =
      event.key === "ArrowRight"
        ? (currentIdx + 1) % TABS.length
        : (currentIdx - 1 + TABS.length) % TABS.length;
    const nextTab = TABS[nextIdx];
    if (!nextTab) return;
    focusAfterChange.current = true;
    // Keyboard navigation between tabs is a focus-only move that should not
    // be guarded by the unsaved-changes confirm — that's reserved for
    // click-driven section switches per the C1 spec.
    setActiveTab(nextTab.id);
  };

  let panelBody: ReactNode = null;
  if (activeTab === "provider") {
    panelBody = (
      <div className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
            LLM provider
          </legend>
          <div className="flex flex-wrap gap-2">
            {view.llm.provider_choices.map((p) => (
              <label
                key={p}
                className={`cursor-pointer rounded-pill border px-2.5 py-1 text-xs transition ${
                  provider === p
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border"
                }`}
              >
                <input
                  type="radio"
                  name="model_provider"
                  className="sr-only"
                  checked={provider === p}
                  onChange={() => setProvider(p)}
                />
                {PROVIDER_LABELS[p]}
              </label>
            ))}
          </div>
          <p className="text-xs text-fg-muted">
            Active: <span className="font-mono">{view.llm.model}</span>
            {view.llm.live
              ? ""
              : " (offline — set API key or disable offline mode)"}
          </p>
        </fieldset>

        {provider === "openai" && (
          <OpenAISection
            view={view}
            draft={draft}
            setDraft={setDraft}
            setStatus={setStatus}
          />
        )}
        {provider === "codex" && (
          <CodexSection
            view={view}
            draft={draft}
            setDraft={setDraft}
            setStatus={setStatus}
            onSettingsRefetch={refetchSettings}
          />
        )}
        {provider === "openrouter" && (
          <OpenRouterSection
            view={view}
            draft={draft}
            setDraft={setDraft}
            setStatus={setStatus}
          />
        )}
        {(provider === "ollama" || provider === "ollama_cloud") && (
          <OllamaSection
            view={view}
            draft={draft}
            setDraft={setDraft}
            provider={provider}
          />
        )}
      </div>
    );
  } else if (activeTab === "routing") {
    panelBody = <ModelRoutingSection view={view} onSaved={refetchSettings} />;
  } else if (activeTab === "wabot") {
    panelBody = <WabotSection view={view} draft={draft} setDraft={setDraft} />;
  } else if (activeTab === "policy") {
    panelBody = (
      <PolicySection
        policy={policy}
        setPolicy={setPolicy}
        owners={owners}
        setOwners={setOwners}
        recipients={recipients}
        setRecipients={setRecipients}
      />
    );
  } else if (activeTab === "experimental") {
    panelBody = (
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          Experimental
        </legend>
        <div className="flex items-start gap-2">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={subagentsEnabled}
              onChange={(e) => setSubagentsEnabled(e.target.checked)}
            />
            <span className="text-xs">
              <span className="font-medium">Use multi-agent orchestrator</span>
              <span className="text-fg-muted ml-1">
                — routes each request to a specialist subagent (scraper, memory,
                comms, scheduler, inboxer). Opt-in. Default: off.
              </span>
            </span>
          </label>
          <HelpPopover term="subagents">
            Routes each WhatsApp request to a specialist subagent (scraper,
            memory, comms, scheduler, inboxer) instead of one general agent.
            Opt-in; default off.
          </HelpPopover>
        </div>
      </fieldset>
    );
  }

  const currentTabLabel =
    TABS.find((t) => t.id === activeTab)?.label ?? activeTab;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="mb-4 text-lg font-semibold">Settings</h1>
      <form onSubmit={submit}>
        <div
          role="tablist"
          aria-label="Settings sections"
          className="flex border-b border-border"
          onKeyDown={onTabKeyDown}
        >
          {TABS.map((tab) => (
            <TabButton
              key={tab.id}
              tab={tab}
              isActive={activeTab === tab.id}
              onClick={() => requestTab(tab.id)}
              buttonRef={(el) => {
                tabRefs.current[tab.id] = el;
              }}
            />
          ))}
        </div>
        <div
          role="tabpanel"
          id={`settings-panel-${activeTab}`}
          aria-labelledby={`settings-tab-${activeTab}`}
          className="pt-6"
        >
          {panelBody}
        </div>
        <SaveFooter status={status} />
      </form>

      <ConfirmDialog
        open={pendingTab !== null}
        title="Discard unsaved changes?"
        description={`Switching tabs will lose your edits in ${currentTabLabel}.`}
        confirmLabel="Discard and switch"
        variant="danger"
        onConfirm={confirmDiscard}
        onCancel={cancelDiscard}
      />
    </div>
  );
}
