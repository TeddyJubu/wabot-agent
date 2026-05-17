import { type FormEvent, useEffect, useState } from "react";
import {
  fetchSettings,
  patchSettings,
  type ModelProvider,
  type SettingsView,
} from "@/api/settings";

type Policy = "dry_run" | "allowlist" | "allow_all" | "owner";

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  openrouter: "OpenRouter",
  ollama: "Ollama (local)",
  ollama_cloud: "Ollama Cloud",
};

export default function SettingsPanel() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [provider, setProvider] = useState<ModelProvider>("openrouter");
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

      {provider === "openrouter" && (
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
            OpenRouter
          </legend>
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
      )}

      {(provider === "ollama" || provider === "ollama_cloud") && (
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
      )}

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">wabot</legend>
        <Field
          label="Endpoint"
          value={draft.wabot_endpoint ?? view.wabot.endpoint}
          onChange={(v) => setDraft((d) => ({ ...d, wabot_endpoint: v }))}
        />
        <Field
          label="Token"
          type="password"
          placeholder={view.wabot.token.preview ?? ""}
          value={draft.wabot_token ?? ""}
          onChange={(v) => setDraft((d) => ({ ...d, wabot_token: v }))}
        />
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          Send policy
        </legend>
        <div className="flex flex-wrap gap-2">
          {(["dry_run", "allowlist", "owner", "allow_all"] as const).map((p) => (
            <label
              key={p}
              className={`cursor-pointer rounded-pill border px-2.5 py-1 text-xs transition ${
                policy === p ? "border-accent bg-accent/10 text-accent" : "border-border"
              }`}
            >
              <input
                type="radio"
                name="policy"
                className="sr-only"
                checked={policy === p}
                onChange={() => {
                  if (
                    p === "allow_all" &&
                    !window.confirm("Allow-all removes the recipient guard. Continue?")
                  ) {
                    return;
                  }
                  setPolicy(p);
                }}
              />
              {p}
            </label>
          ))}
        </div>
        <label className="block">
          <span className="text-xs text-fg-muted">Owner numbers (owner policy)</span>
          <textarea
            rows={2}
            value={owners}
            onChange={(e) => setOwners(e.target.value)}
            placeholder="+6580286424"
            className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
          />
        </label>
        <p className="text-xs text-fg-muted">
          With <span className="font-mono">owner</span> policy, the dashboard and these numbers may
          message anyone; other inbound chats can only reply in-thread.
        </p>
        <label className="block">
          <span className="text-xs text-fg-muted">Allowed recipients (optional extras)</span>
          <textarea
            rows={3}
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            placeholder="+15550001111, +15550002222"
            className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
          />
        </label>
      </fieldset>

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

interface FieldProps {
  label: string;
  value: string;
  placeholder?: string;
  type?: string;
  onChange: (v: string) => void;
}

function Field({ label, value, placeholder, type = "text", onChange }: FieldProps) {
  return (
    <label className="block">
      <span className="text-xs text-fg-muted">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
      />
    </label>
  );
}
