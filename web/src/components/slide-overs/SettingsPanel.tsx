import { type FormEvent, useEffect, useState } from "react";

import {
  fetchSettings,
  patchSettings,
  type ModelProvider,
  type SettingsView,
} from "@/api/settings";

import { CodexSection } from "./settings/CodexSection";
import { ModelRoutingSection } from "./settings/ModelRoutingSection";
import { OllamaSection } from "./settings/OllamaSection";
import { OpenAISection } from "./settings/OpenAISection";
import { OpenRouterSection } from "./settings/OpenRouterSection";
import { PolicySection } from "./settings/PolicySection";
import { WabotSection } from "./settings/WabotSection";

type Policy = "dry_run" | "allowlist" | "allow_all" | "owner";

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  openai: "OpenAI API",
  codex: "ChatGPT / Codex",
  openrouter: "OpenRouter",
  ollama: "Ollama (local)",
  ollama_cloud: "Ollama Cloud",
};

/**
 * Settings slide-over. Orchestrates the shared form state (provider, policy,
 * recipients, owners, draft, status, view) and delegates each provider's UI
 * to a dedicated section component. Each section reads `view`/`draft` and
 * writes back through `setDraft`; the codex section additionally owns its
 * device-login polling via the `useCodexLogin` hook.
 *
 * Carved out as part of MASTER ME-6 — see settings/*.tsx siblings.
 */
export default function SettingsPanel() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [provider, setProvider] = useState<ModelProvider>("codex");
  const [policy, setPolicy] = useState<Policy>("dry_run");
  const [recipients, setRecipients] = useState("");
  const [owners, setOwners] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    fetchSettings()
      .then((v) => {
        setView(v);
        setProvider(v.llm.provider);
        setPolicy(v.send_policy);
        setRecipients(v.allowed_recipients.join(", "));
        setOwners(v.owner_numbers.join(", "));
      })
      .catch((err) => setStatus(`Couldn't load: ${String(err)}`));
  }, []);

  if (!view) {
    return <p className="text-xs text-fg-muted">{status || "Loading…"}</p>;
  }

  const refetchSettings = () => {
    void fetchSettings().then(setView);
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
    for (const [key, value] of Object.entries(draft)) {
      if (value !== "") body[key] = value;
    }
    try {
      await patchSettings(body);
      setStatus("Saved.");
      setDraft({});
      const next = await fetchSettings();
      setView(next);
      setProvider(next.llm.provider);
    } catch (err) {
      setStatus(`Error: ${String(err)}`);
    }
  };

  return (
    <form className="space-y-4" onSubmit={submit}>
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          LLM provider
        </legend>
        <div className="flex flex-wrap gap-2">
          {view.llm.provider_choices.map((p) => (
            <label
              key={p}
              className={`cursor-pointer rounded-pill border px-2.5 py-1 text-xs transition ${
                provider === p ? "border-accent bg-accent/10 text-accent" : "border-border"
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
          {view.llm.live ? "" : " (offline — set API key or disable offline mode)"}
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

      <ModelRoutingSection view={view} onSaved={refetchSettings} />

      <WabotSection view={view} draft={draft} setDraft={setDraft} />

      <PolicySection
        policy={policy}
        setPolicy={setPolicy}
        owners={owners}
        setOwners={setOwners}
        recipients={recipients}
        setRecipients={setRecipients}
      />

      <div className="flex items-center justify-between">
        <span className="text-xs text-fg-muted">{status}</span>
        <button
          type="submit"
          className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg transition hover:opacity-90"
        >
          Save changes
        </button>
      </div>
    </form>
  );
}
