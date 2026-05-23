/**
 * API client for /api/composio — Phase 5.
 *
 * Auth: all endpoints require credentials (operator token via session cookie).
 */

import { parseJson } from "./_http";

export type ComposioStatus = {
  enabled: boolean;
  api_key_present: boolean;
  user_id: string | null;
  last_error: string | null;
};

export type ComposioApp = {
  slug: string;
  name: string;
  description: string | null;
  logo_url: string | null;
  categories: string[];
  auth_schemes: string[];
};

export type ComposioConnectionStatus = "connected" | "pending" | "error" | "disconnected";

export type ComposioConnection = {
  id: number;
  app_slug: string;
  display_name: string;
  status: ComposioConnectionStatus;
  user_id: string | null;
  last_checked_at: string | null;
  metadata: Record<string, unknown> | null;
};

export type ComposioConnectionCreate = ComposioConnection & { redirect_url: string };

export async function getComposioStatus(): Promise<ComposioStatus> {
  const res = await fetch("/api/composio/status", { credentials: "include" });
  return parseJson<ComposioStatus>(res);
}

export async function setComposioApiKey(api_key: string): Promise<ComposioStatus> {
  const res = await fetch("/api/composio/api-key", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key }),
  });
  return parseJson<ComposioStatus>(res);
}

export async function listComposioApps(): Promise<ComposioApp[]> {
  const res = await fetch("/api/composio/apps", { credentials: "include" });
  return parseJson<ComposioApp[]>(res);
}

export async function listComposioConnections(): Promise<ComposioConnection[]> {
  const res = await fetch("/api/composio/connections", { credentials: "include" });
  return parseJson<ComposioConnection[]>(res);
}

export async function createComposioConnection(payload: {
  app_slug: string;
  user_id?: string | null;
}): Promise<ComposioConnectionCreate> {
  const res = await fetch("/api/composio/connections", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson<ComposioConnectionCreate>(res);
}

export async function refreshComposioConnection(id: number): Promise<ComposioConnection> {
  const res = await fetch(`/api/composio/connections/${id}/refresh`, {
    method: "POST",
    credentials: "include",
  });
  return parseJson<ComposioConnection>(res);
}

export async function deleteComposioConnection(id: number): Promise<void> {
  const res = await fetch(`/api/composio/connections/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Delete failed (${res.status})`,
    );
  }
}
