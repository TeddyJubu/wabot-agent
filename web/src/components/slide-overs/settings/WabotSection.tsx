import { type SettingsView } from "@/api/settings";

import { Field } from "./Fields";

interface WabotSectionProps {
  view: SettingsView;
  draft: Record<string, string>;
  setDraft: (updater: (d: Record<string, string>) => Record<string, string>) => void;
}

/**
 * Wabot daemon settings — endpoint URL + bearer token. Loopback-only enforcement
 * happens server-side (see ``api/dependencies._require_loopback_url``); this
 * UI just collects the inputs.
 */
export function WabotSection({ view, draft, setDraft }: WabotSectionProps) {
  return (
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
  );
}
