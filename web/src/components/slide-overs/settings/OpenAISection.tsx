import { useState } from "react";

import { testOpenAI, type SettingsView } from "@/api/settings";

import { Field } from "./Fields";

interface OpenAISectionProps {
  view: SettingsView;
  draft: Record<string, string>;
  setDraft: (updater: (d: Record<string, string>) => Record<string, string>) => void;
  setStatus: (msg: string) => void;
}

/**
 * OpenAI provider section. Mirrors the OpenRouter section pattern — owns its
 * own `busy` flag for the Test button; everything else is read-through props
 * from the parent SettingsPanel.
 */
export function OpenAISection({
  view,
  draft,
  setDraft,
  setStatus,
}: OpenAISectionProps) {
  const [busy, setBusy] = useState(false);

  const runTest = async () => {
    setBusy(true);
    setStatus("Testing OpenAI…");
    try {
      const result = await testOpenAI({
        api_key: draft.openai_api_key || undefined,
        base_url: draft.openai_base_url ?? view.openai.base_url,
        model: draft.openai_model ?? view.openai.model,
      });
      setStatus(result.ok ? result.detail : `OpenAI test failed: ${result.detail}`);
    } catch (err) {
      setStatus(`OpenAI test error: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        OpenAI API
      </legend>
      <div className="rounded-card border border-border bg-bg-card/60 p-3 text-xs">
        <p className={view.openai.live ? "text-ok/90" : "text-fg-muted"}>
          {view.openai.live
            ? "OpenAI API is the active dashboard chat provider."
            : "Paste an OpenAI key, save, and dashboard chat will use OpenAI."}
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
          Test OpenAI
        </button>
      </div>
      <Field
        label="API key"
        type="password"
        placeholder={view.openai.api_key.preview ?? "sk-…"}
        value={draft.openai_api_key ?? ""}
        onChange={(v) => setDraft((d) => ({ ...d, openai_api_key: v }))}
      />
      <Field
        label="Model"
        value={draft.openai_model ?? view.openai.model}
        onChange={(v) => setDraft((d) => ({ ...d, openai_model: v }))}
      />
      <Field
        label="Base URL"
        value={draft.openai_base_url ?? view.openai.base_url}
        onChange={(v) => setDraft((d) => ({ ...d, openai_base_url: v }))}
      />
    </fieldset>
  );
}
