import { type FormEvent, useEffect, useState } from "react";
import { fetchSettings, patchSettings, type SettingsView } from "@/api/settings";

type Policy = "dry_run" | "allowlist" | "allow_all";

export default function SettingsPanel() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [policy, setPolicy] = useState<Policy>("dry_run");
  const [recipients, setRecipients] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    fetchSettings()
      .then((v) => {
        setView(v);
        setPolicy(v.send_policy);
        setRecipients(v.allowed_recipients.join(", "));
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
    if (policy !== view.send_policy) {
      body.send_policy = policy;
      // confirm_allow_all is only meaningful on transition into allow_all.
      // The radio-click handler gathered fresh window.confirm() consent then;
      // re-saving with policy already at allow_all must not implicitly renew it.
      if (policy === "allow_all") body.confirm_allow_all = true;
    }
    if (recipients !== view.allowed_recipients.join(", ")) {
      body.allowed_recipients = recipients
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
    } catch (err) {
      setStatus(`Error: ${String(err)}`);
    }
  };

  return (
    <form className="space-y-4" onSubmit={submit}>
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
          {(["dry_run", "allowlist", "allow_all"] as const).map((p) => (
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
          <span className="text-xs text-fg-muted">Allowed recipients</span>
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
