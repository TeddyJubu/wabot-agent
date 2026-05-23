export interface MaskedField {
  set: boolean;
  preview: string | null;
}

export type ModelProvider = "openai" | "codex" | "openrouter" | "ollama" | "ollama_cloud";

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
  openai: {
    api_key: MaskedField;
    base_url: string;
    model: string;
    live: boolean;
  };
  codex: {
    access_token: MaskedField;
    account_id: string | null;
    auth_path: string;
    base_url: string;
    model: string;
    model_choices: string[];
    reasoning_effort: string;
    reasoning_effort_choices: string[];
    reasoning_effort_labels: Record<string, string>;
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

export interface SettingsTestResult {
  ok: boolean;
  detail: string;
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

export async function testOpenRouter(body: {
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<SettingsTestResult> {
  const res = await fetch("/api/settings/test/openrouter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as SettingsTestResult | null;
  if (!res.ok) {
    throw new Error(data?.detail || `openrouter test failed: ${res.status}`);
  }
  if (!data) throw new Error("openrouter test returned no body");
  return data;
}

export async function testOpenAI(body: {
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<SettingsTestResult> {
  const res = await fetch("/api/settings/test/openai", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as SettingsTestResult | null;
  if (!res.ok) {
    throw new Error(data?.detail || `openai test failed: ${res.status}`);
  }
  if (!data) throw new Error("openai test returned no body");
  return data;
}
