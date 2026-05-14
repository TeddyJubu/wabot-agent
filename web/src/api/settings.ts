export interface MaskedField {
  set: boolean;
  preview: string | null;
}

export interface SettingsView {
  env_source: string;
  send_policy: "dry_run" | "allowlist" | "allow_all";
  send_policy_choices: string[];
  allowed_recipients: string[];
  max_agent_turns: number;
  openrouter: {
    api_key: MaskedField;
    base_url: string;
    model: string;
    live: boolean;
  };
  wabot: {
    endpoint: string;
    token: MaskedField;
    token_file?: string | null;
  };
}

export async function fetchSettings(): Promise<SettingsView> {
  const res = await fetch("/api/settings", { credentials: "include" });
  if (!res.ok) throw new Error(`settings: ${res.status}`);
  return res.json();
}

export async function patchSettings(body: Record<string, unknown>): Promise<void> {
  const res = await fetch("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `settings PATCH failed: ${res.status}`);
  }
}
