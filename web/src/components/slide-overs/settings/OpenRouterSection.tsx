import { useState } from "react";

import { testOpenRouter, type SettingsView } from "@/api/settings";

import { Field } from "./Fields";

interface OpenRouterSectionProps {
  view: SettingsView;
  draft: Record<string, string>;
  setDraft: (updater: (d: Record<string, string>) => Record<string, string>) => void;
  setStatus: (msg: string) => void;
}

/**
 * OpenRouter provider section. Owns its own `busy` flag for the Test button;
 * everything else is read-through props from the parent SettingsPanel.
 */
export function OpenRouterSection({
  view,
  draft,
  setDraft,
  setStatus,
}: OpenRouterSectionProps) {
  const [busy, setBusy] = useState(false);

  const runTest = async () => {
    setBusy(true);
    setStatus("Testing OpenRouter…");
    try {
      const result = await testOpenRouter({
        api_key: draft.openrouter_api_key || undefined,
        base_url: draft.openrouter_base_url ?? view.openrouter.base_url,
        model: draft.openrouter_model ?? view.openrouter.model,
      });
      setStatus(result.ok ? result.detail : `OpenRouter test failed: ${result.detail}`);
    } catch (err) {
      setStatus(`OpenRouter test error: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        OpenRouter
      </legend>
      <div className="rounded-card border border-border bg-bg-card/60 p-3 text-xs">
        <p className={view.openrouter.live ? "text-emerald-400/90" : "text-fg-muted"}>
          {view.openrouter.live
            ? "OpenRouter is the active dashboard chat provider."
            : "Paste an OpenRouter key, save, and dashboard chat will use OpenRouter."}
        </p>
        <p className="mt-1 text-fg-muted">
          The key is stored server-side; the browser only sends it to this dashboard backend.
        </p>
        <button
          type="button"
          disabled={busy}
          className="mt-3 rounded-pill border border-border px-2.5 py-1 text-xs transition hover:border-accent disabled:opacity-50"
          onClick={() => void runTest()}
        >
          Test OpenRouter
        </button>
      </div>
      <Field
        label="API key"
        type="password"
        placeholder={view.openrouter.api_key.preview ?? "sk-or-…"}
        value={draft.openrouter_api_key ?? ""}
        onChange={(v) => setDraft((d) => ({ ...d, openrouter_api_key: v }))}
      />
      <Field
        label="Model"
        value={draft.openrouter_model ?? view.openrouter.model}
        onChange={(v) => setDraft((d) => ({ ...d, openrouter_model: v }))}
      />
      <Field
        label="Base URL"
        value={draft.openrouter_base_url ?? view.openrouter.base_url}
        onChange={(v) => setDraft((d) => ({ ...d, openrouter_base_url: v }))}
      />
    </fieldset>
  );
}
