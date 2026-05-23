import { useState } from "react";

import { patchSettings, type ModelChoice, type ModelRouting, type SettingsView } from "@/api/settings";

// TODO: In a future iteration, fetch the available providers from the backend
// registry (e.g. GET /api/settings/providers) instead of hardcoding this list.
// The registry is already in place (providers.py) — the API endpoint just needs
// to be wired up.
const PROVIDER_OPTIONS = [
  "openai",
  "openrouter",
  "codex",
  "ollama",
  "ollama_cloud",
] as const;

type VisiblePurpose = {
  key: string;
  label: string;
  description: string;
};

const VISIBLE_PURPOSES: VisiblePurpose[] = [
  {
    key: "chat",
    label: "Chat reply",
    description: "Every WhatsApp reply the bot sends",
  },
  {
    key: "scraping",
    label: "Web scraping",
    description: "Web scraping and research subagent",
  },
  {
    key: "memory_extraction",
    label: "Memory extraction",
    description: "Mem0 fact extraction from conversations",
  },
  {
    key: "vision",
    label: "Vision",
    description: "Processing image inputs from messages",
  },
];

const ADVANCED_PURPOSES: VisiblePurpose[] = [
  {
    key: "tool_reasoning",
    label: "Tool reasoning",
    description: "The model that decides which tool to call (future use)",
  },
  {
    key: "transcription",
    label: "Transcription",
    description: "Voice note transcription (currently uses local Whisper)",
  },
  {
    key: "background_research",
    label: "Background research",
    description: "Long async research jobs",
  },
];

function purposeDefaultPlaceholder(purposeKey: string, view: SettingsView): string {
  const provider = view.llm.provider;
  const model = view.llm.model;
  return `${model} (${provider} default)`;
}

interface RoutingRowProps {
  purpose: VisiblePurpose;
  choice: ModelChoice | undefined;
  view: SettingsView;
  onChange: (key: string, choice: ModelChoice | null) => void;
}

function RoutingRow({ purpose, choice, view, onChange }: RoutingRowProps) {
  const isDefault = choice == null;

  return (
    <div
      className={`grid grid-cols-[1fr_auto_auto_auto] items-center gap-2 rounded-card border border-border p-2 text-xs transition ${
        isDefault ? "opacity-60" : ""
      }`}
    >
      {/* Purpose label + description */}
      <div>
        <span className="font-medium">{purpose.label}</span>
        <p className="text-fg-muted">{purpose.description}</p>
      </div>

      {/* Provider dropdown */}
      <select
        disabled={isDefault}
        value={choice?.provider ?? view.llm.provider}
        className="rounded border border-border bg-bg-card px-1.5 py-1 text-xs disabled:opacity-40"
        onChange={(e) => {
          onChange(purpose.key, {
            provider: e.target.value,
            model: choice?.model ?? "",
          });
        }}
      >
        {PROVIDER_OPTIONS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>

      {/* Model text input */}
      <input
        disabled={isDefault}
        type="text"
        placeholder={purposeDefaultPlaceholder(purpose.key, view)}
        value={choice?.model ?? ""}
        className="w-36 rounded border border-border bg-bg-card px-1.5 py-1 text-xs placeholder:text-fg-muted/60 disabled:opacity-40"
        onChange={(e) => {
          onChange(purpose.key, {
            provider: choice?.provider ?? view.llm.provider,
            model: e.target.value,
          });
        }}
      />

      {/* "Use default" checkbox */}
      <label className="flex items-center gap-1 text-fg-muted">
        <input
          type="checkbox"
          checked={isDefault}
          onChange={(e) => {
            if (e.target.checked) {
              onChange(purpose.key, null); // remove entry → use global default
            } else {
              onChange(purpose.key, {
                provider: view.llm.provider,
                model: "",
              });
            }
          }}
        />
        Default
      </label>
    </div>
  );
}

interface ModelRoutingSectionProps {
  view: SettingsView;
  onSaved: () => void;
}

/**
 * Per-purpose model routing section in the settings panel.
 *
 * Shows 4 visible purposes by default; a "Show advanced" toggle reveals 3 more.
 * Each row has a provider dropdown, a model text input, and a "Use default"
 * checkbox. When "Use default" is checked, the row is greyed out and its key
 * is omitted from the saved routing dict — meaning that purpose falls back to
 * the global provider.
 *
 * On save, PATCHes /api/settings with only the non-default entries.
 * Wired into SettingsPanel between the provider sections and PolicySection.
 */
export function ModelRoutingSection({ view, onSaved }: ModelRoutingSectionProps) {
  // Local state: a copy of the current routing, with null meaning "use default".
  const [routing, setRouting] = useState<ModelRouting>(() => view.model_routing ?? {});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [status, setStatus] = useState("");

  const handleChange = (key: string, choice: ModelChoice | null) => {
    setRouting((prev) => {
      const next = { ...prev };
      if (choice === null) {
        delete next[key];
      } else {
        next[key] = choice;
      }
      return next;
    });
  };

  const handleSave = async () => {
    setStatus("Saving…");
    try {
      await patchSettings({ model_routing: routing });
      setStatus("Saved.");
      onSaved();
    } catch (err) {
      setStatus(`Error: ${String(err)}`);
    }
  };

  const allPurposes = showAdvanced
    ? [...VISIBLE_PURPOSES, ...ADVANCED_PURPOSES]
    : VISIBLE_PURPOSES;

  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        Per-purpose model routing
      </legend>
      <p className="text-xs text-fg-muted">
        Override the global provider/model for specific tasks. Leave a row on "Default" to use
        the global provider.
      </p>

      <div className="space-y-1.5">
        {allPurposes.map((p) => (
          <RoutingRow
            key={p.key}
            purpose={p}
            choice={routing[p.key]}
            view={view}
            onChange={handleChange}
          />
        ))}
      </div>

      <button
        type="button"
        className="text-xs text-fg-muted underline-offset-2 hover:underline"
        onClick={() => setShowAdvanced((v) => !v)}
      >
        {showAdvanced ? "Hide advanced" : "Show advanced"}
      </button>

      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-fg-muted">{status}</span>
        <button
          type="button"
          className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg transition hover:opacity-90"
          onClick={() => void handleSave()}
        >
          Save routing
        </button>
      </div>
    </fieldset>
  );
}
