export interface CodexLoginSession {
  status: "idle" | "pending" | "complete" | "failed";
  url: string | null;
  code: string | null;
  detail: string | null;
}

export interface CodexLoginView {
  cli_available: boolean;
  logged_in: boolean;
  auth_mode: string | null;
  auth_path: string;
  session: CodexLoginSession;
}

export async function fetchCodexLogin(): Promise<CodexLoginView> {
  const res = await fetch("/api/codex/login", { credentials: "include" });
  if (!res.ok) throw new Error(`codex login status: ${res.status}`);
  return res.json();
}

export async function startCodexDeviceLogin(): Promise<CodexLoginView> {
  const res = await fetch("/api/codex/login/device", {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `codex device login: ${res.status}`);
  }
  return res.json();
}

export async function cancelCodexDeviceLogin(): Promise<CodexLoginView> {
  const res = await fetch("/api/codex/login/device/cancel", {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`codex login cancel: ${res.status}`);
  return res.json();
}
