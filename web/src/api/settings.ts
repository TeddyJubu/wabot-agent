export interface MaskedField {
  set: boolean;
  preview: string | null;
}

export type ModelProvider = "codex" | "openrouter" | "ollama" | "ollama_cloud";

export interface SettingsView {
  env_source: string;
  send_policy: "dry_run" | "allowlist" | "allow_all" | "owner";
  send_policy_choices: string[];
  allowed_recipients: string[];
  owner_numbers: string[];
  max_agent_turns: number;
  llm: {
    provider: ModelProvider;
    provider_choices: ModelProvider[];
    model: string;
    label: string;
    live: boolean;
  };
  codex: {
    access_token: MaskedField;
    account_id: string | null;
    auth_path: string;
    base_url: string;
    model: string;
    live: boolean;
    logged_in: boolean;
    cli_available: boolean;
  };
  openrouter: {
    api_key: MaskedField;
    base_url: string;
    model: string;
    live: boolean;
  };
  ollama: {
    api_key: MaskedField;
    model: string;
    base_url: string;
    cloud_base_url: string;
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
