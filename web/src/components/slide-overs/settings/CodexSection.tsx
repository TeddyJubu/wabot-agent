import { useCodexLogin } from "@/hooks/useCodexLogin";
import { type SettingsView } from "@/api/settings";

import { Field, SelectField } from "./Fields";

interface CodexSectionProps {
  view: SettingsView;
  draft: Record<string, string>;
  setDraft: (updater: (d: Record<string, string>) => Record<string, string>) => void;
  setStatus: (msg: string) => void;
  onSettingsRefetch: () => void;
}

/**
 * ChatGPT / Codex provider section of the settings slide-over. Owns its own
 * device-login state via `useCodexLogin`; the parent only refetches
 * /api/settings via `onSettingsRefetch` after a sign-in or disconnect.
 */
export function CodexSection({
  view,
  draft,
  setDraft,
  setStatus,
  onSettingsRefetch,
}: CodexSectionProps) {
  const {
    codexLogin,
    busy: codexBusy,
    startLogin,
    cancelLogin,
    disconnect,
  } = useCodexLogin({
    active: true,
    onLoginComplete: onSettingsRefetch,
    onDisconnect: onSettingsRefetch,
    onStatus: setStatus,
  });

  const signedIn = Boolean(view.codex.logged_in || codexLogin?.logged_in);
  const pending = codexLogin?.session.status === "pending";
  const failed =
    codexLogin?.session.status === "failed" &&
    Boolean(codexLogin.session.detail) &&
    !signedIn;

  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        ChatGPT / Codex
      </legend>
      <div className="rounded-card border border-border bg-bg-card/60 p-3 text-xs">
        {signedIn ? (
          <p className="text-ok/90">
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
          <p className="mt-2 rounded border border-bad/30 bg-bad/10 px-2 py-1.5 text-bad">
            {codexLogin.session.detail}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {!signedIn && (
            <button
              type="button"
              disabled={codexBusy || !view.codex.cli_available || pending}
              className="rounded-pill border border-border px-2.5 py-1 text-xs transition hover:border-accent disabled:opacity-50"
              onClick={() => void startLogin()}
            >
              Sign in with ChatGPT
            </button>
          )}
          {pending && (
            <button
              type="button"
              className="rounded-pill border border-border px-2.5 py-1 text-xs transition hover:border-accent"
              onClick={() => void cancelLogin()}
            >
              Cancel
            </button>
          )}
          {signedIn && (
            <button
              type="button"
              disabled={codexBusy}
              className="rounded-pill border border-bad/40 px-2.5 py-1 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-50"
              onClick={() => void disconnect()}
            >
              Disconnect ChatGPT
            </button>
          )}
        </div>
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
  );
}
