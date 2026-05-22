import { type ModelProvider, type SettingsView } from "@/api/settings";

import { Field } from "./Fields";

interface OllamaSectionProps {
  view: SettingsView;
  draft: Record<string, string>;
  setDraft: (updater: (d: Record<string, string>) => Record<string, string>) => void;
  /** Which Ollama mode: local daemon ("ollama") or hosted cloud ("ollama_cloud"). */
  provider: ModelProvider;
}

/**
 * Ollama provider section. Renders either the local-base-URL form
 * (provider="ollama") or the cloud API-key + base-URL form
 * (provider="ollama_cloud"). The parent owns selection of which one is
 * active via the provider radio.
 */
export function OllamaSection({ view, draft, setDraft, provider }: OllamaSectionProps) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        Ollama
      </legend>
      <Field
        label="Model"
        placeholder={provider === "ollama_cloud" ? "minimax-m2.7" : "minimax-m2.7:cloud"}
        value={draft.ollama_model ?? view.ollama.model}
        onChange={(v) => setDraft((d) => ({ ...d, ollama_model: v }))}
      />
      {provider === "ollama" ? (
        <Field
          label="Local base URL"
          value={draft.ollama_base_url ?? view.ollama.base_url}
          onChange={(v) => setDraft((d) => ({ ...d, ollama_base_url: v }))}
        />
      ) : (
        <>
          <Field
            label="API key"
            type="password"
            placeholder={view.ollama.api_key.preview ?? "ollama key"}
            value={draft.ollama_api_key ?? ""}
            onChange={(v) => setDraft((d) => ({ ...d, ollama_api_key: v }))}
          />
          <Field
            label="Cloud base URL"
            value={draft.ollama_cloud_base_url ?? view.ollama.cloud_base_url}
            onChange={(v) => setDraft((d) => ({ ...d, ollama_cloud_base_url: v }))}
          />
        </>
      )}
    </fieldset>
  );
}
