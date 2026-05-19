import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  cancelCodexDeviceLogin,
  fetchCodexLogin,
  startCodexDeviceLogin,
  type CodexLoginView,
} from "@/api/codex";
import {
  fetchSettings,
  patchSettings,
  type ModelProvider,
  type SettingsView,
} from "@/api/settings";

type Policy = "dry_run" | "allowlist" | "allow_all" | "owner";

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  codex: "ChatGPT / Codex",
  openrouter: "OpenRouter",
  ollama: "Ollama (local)",
  ollama_cloud: "Ollama Cloud",
};

export default function SettingsPanel() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [provider, setProvider] = useState<ModelProvider>("codex");
  const [policy, setPolicy] = useState<Policy>("allow_all");
  const [recipients, setRecipients] = useState("");
  const [owners, setOwners] = useState("");
  const [status, setStatus] = useState("");
  const [codexLogin, setCodexLogin] = useState<CodexLoginView | null>(null);
  const [codexBusy, setCodexBusy] = useState(false);
  const codexPollRef = useRef<number | null>(null);

  const refreshCodexLogin = useCallback(async () => {
    try {
      const next = await fetchCodexLogin();
      setCodexLogin(next);
      return next;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    if (provider !== "codex") {
      if (codexPollRef.current) {
        window.clearInterval(codexPollRef.current);
        codexPollRef.current = null;
      }
      return;
    }
    void refreshCodexLogin();
    return () => {
      if (codexPollRef.current) {
        window.clearInterval(codexPollRef.current);
        codexPollRef.current = null;
      }
    };
  }, [provider, refreshCodexLogin]);

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

      {provider === "codex" && (
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
            ChatGPT / Codex
          </legend>
          <div className="rounded-card border border-border bg-bg-card/60 p-3 text-xs">
            {(() => {
              const signedIn = Boolean(view.codex.logged_in || codexLogin?.logged_in);
              const pending = codexLogin?.session.status === "pending";
              const failed =
                codexLogin?.session.status === "failed" &&
                Boolean(codexLogin.session.detail) &&
                !signedIn;

              return (
                <>
                  {signedIn ? (
                    <p className="text-emerald-400/90">
                      Connected via ChatGPT subscription
                      {codexLogin?.auth_mode ? ` (${codexLogin.auth_mode})` : ""}.
                    </p>
                  ) : (
                    <p className="text-fg-muted">Not signed in to ChatGPT / Codex yet.</p>
                  )}
                  {!view.codex.cli_available && (
                    <p className="mt-2 text-fg-muted">
                      Install the Codex CLI on this machine and restart wabot-agent, or paste an
                      access token below.
                    </p>
                  )}
                  {pending && codexLogin.session.url && codexLogin.session.code && (
                    <ol className="mt-3 list-decimal space-y-2 pl-4 text-fg-muted">
                      <li>
                        Open{" "}
                        <a
                          className="text-accent underline"
                          href={codexLogin.session.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          auth.openai.com/codex/device
                        </a>{" "}
                        and sign in.
                      </li>
                      <li>
                        Enter code{" "}
                        <span className="rounded bg-bg-elevated px-1.5 py-0.5 font-mono text-sm text-accent">
                          {codexLogin.session.code}
                        </span>
                      </li>
                      <li className="list-none pl-0">Waiting for approval…</li>
                    </ol>
                  )}
                  {failed && (
                    <p className="mt-2 rounded border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-red-300">
                      {codexLogin.session.detail}
                    </p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {!signedIn && (
                      <button
                        type="button"
                        disabled={codexBusy || !view.codex.cli_available || pending}
                        className="rounded-pill border border-border px-2.5 py-1 text-xs transition hover:border-accent disabled:opacity-50"
                        onClick={async () => {
                          setCodexBusy(true);
                          setStatus("Starting ChatGPT sign-in…");
                          try {
                            const next = await startCodexDeviceLogin();
                            setCodexLogin(next);
                            if (codexPollRef.current) window.clearInterval(codexPollRef.current);
                            codexPollRef.current = window.setInterval(() => {
                              void refreshCodexLogin().then((v) => {
                                if (v?.session.status === "complete" || v?.logged_in) {
                                  if (codexPollRef.current) {
                                    window.clearInterval(codexPollRef.current);
                                  }
                                  codexPollRef.current = null;
                                  setCodexLogin(v);
                                  setStatus("ChatGPT sign-in complete.");
                                  void fetchSettings().then(setView);
                                } else if (v?.session.status === "failed" && !v.logged_in) {
                                  if (codexPollRef.current) {
                                    window.clearInterval(codexPollRef.current);
                                  }
                                  codexPollRef.current = null;
                                  setCodexLogin(v);
                                  setStatus(v.session.detail ?? "Sign-in failed.");
                                }
                              });
                            }, 2000);
                          } catch (err) {
                            setStatus(`Sign-in error: ${String(err)}`);
                          } finally {
                            setCodexBusy(false);
                          }
                        }}
                      >
                        Sign in with ChatGPT
                      </button>
                    )}
                    {pending && (
                      <button
                        type="button"
                        className="rounded-pill border border-border px-2.5 py-1 text-xs transition hover:border-accent"
                        onClick={async () => {
                          setCodexBusy(true);
                          try {
                            const next = await cancelCodexDeviceLogin();
                            setCodexLogin(next);
                            if (codexPollRef.current) window.clearInterval(codexPollRef.current);
                            codexPollRef.current = null;
                            setStatus("Sign-in cancelled.");
                          } finally {
                            setCodexBusy(false);
                          }
                        }}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
          <p className="text-xs text-fg-muted">
            Credentials are stored at <span className="font-mono">{view.codex.auth_path}</span> on
            the machine running wabot-agent.
          </p>
          <SelectField
            label="Model"
            value={draft.codex_model ?? view.codex.model}
            choices={view.codex.model_choices}
            onChange={(v) => setDraft((d) => ({ ...d, codex_model: v }))}
          />
          <SelectField
            label="Reasoning effort"
            value={draft.codex_reasoning_effort ?? view.codex.reasoning_effort}
            choices={view.codex.reasoning_effort_choices}
            choiceLabels={view.codex.reasoning_effort_labels}
            onChange={(v) => setDraft((d) => ({ ...d, codex_reasoning_effort: v }))}
          />
          <Field
            label="Base URL"
            value={draft.codex_base_url ?? view.codex.base_url}
            onChange={(v) => setDraft((d) => ({ ...d, codex_base_url: v }))}
          />
          <Field
            label="Access token (optional override)"
            type="password"
            placeholder={view.codex.access_token.preview ?? "from data/codex/auth.json"}
            value={draft.codex_access_token ?? ""}
            onChange={(v) => setDraft((d) => ({ ...d, codex_access_token: v }))}
          />
          <Field
            label="Account ID (optional override)"
            value={draft.codex_account_id ?? view.codex.account_id ?? ""}
            onChange={(v) => setDraft((d) => ({ ...d, codex_account_id: v }))}
          />
        </fieldset>
      )}

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

interface SelectFieldProps {
  label: string;
  value: string;
  choices: string[];
  choiceLabels?: Record<string, string>;
  onChange: (v: string) => void;
}

function SelectField({ label, value, choices, choiceLabels, onChange }: SelectFieldProps) {
  const options = choices.includes(value) ? choices : [value, ...choices];
  return (
    <label className="block">
      <span className="text-xs text-fg-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm"
      >
        {options.map((choice) => (
          <option key={choice} value={choice}>
            {choiceLabels?.[choice] ?? choice}
          </option>
        ))}
      </select>
    </label>
  );
}
